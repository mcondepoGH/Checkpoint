"""Lógica de sincronización de un juego entre dos dispositivos y el hub."""
import hashlib
import json
import os
import re
import shutil
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional

from . import locking, settings
from .apierror import describe_code, error_body
from .config import ON_CONFLICT, Config, ConfigError, resolve_ref
from .redact import redact
from .transport import Transport, TransportError, get_transport

VERSION_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{6}(-\d+)?$")


class SyncAbort(Exception):
    """Fin controlado sin tocar nada (o error ya reportado). Contrato i18n: `code` (`err.sync.<causa>`) +
    `params`; sin texto en español (la UI traduce). `str(e)` es técnico, para logs y CLI."""

    def __init__(self, code: str, **params):
        super().__init__(describe_code(code, params))
        self.code, self.params = code, params

    def body(self) -> dict:
        return error_body(self.code, **self.params)


def _set(status: dict, result: str, code: str, **params):
    """Resultado con mensaje estructurado: `code`/`params` (la UI los traduce). `message` es solo el respaldo
    técnico que leen scheduler, historial y CLI (code + params, no traducido)."""
    status.update(result=result, code=code, params=params, message=describe_code(code, params))


@dataclass
class Fingerprint:
    hash: Optional[str]
    mtime: int
    files: int
    size: int = 0

    @property
    def empty(self) -> bool:
        return self.files == 0


def fingerprint(root: Path) -> Fingerprint:
    root = Path(root)
    if not root.is_dir():
        return Fingerprint(None, 0, 0)
    entries = []
    mt = size = 0
    for p in sorted(root.rglob("*")):
        if p.is_symlink() or not p.is_file():
            continue
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        entries.append(f"{p.relative_to(root).as_posix()}\0{h.hexdigest()}")
        st = p.stat()
        mt = max(mt, int(st.st_mtime))
        size += st.st_size
    if not entries:
        return Fingerprint(None, 0, 0)
    return Fingerprint(hashlib.sha256("\n".join(entries).encode()).hexdigest(), mt, len(entries), size)


def relfiles(root: Path) -> set:
    root = Path(root)
    if not root.is_dir():
        return set()
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file() and not p.is_symlink()}


def _fmt(ts: int) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S") if ts else "-"


def _version_key(name: str):
    """Orden cronológico por el nombre (AAAA-MM-DD_HHMMSS[-n]); el sufijo -n se compara como número."""
    stamp, _, n = name[:17], name[17:18], name[18:]
    return (stamp, int(n) if n.isdigit() else 0)


def list_versions(data_dir: Path, game: str, names: Optional[Dict[str, str]] = None) -> List[dict]:
    """Versiones guardadas de `game` (id). `names` ({id de origen: nombre}) añade el nombre visible a cada origen."""
    names = names or {}
    base = Path(data_dir) / "versions" / game
    out = []
    if base.is_dir():
        for d in sorted(base.iterdir(), key=lambda d: _version_key(d.name), reverse=True):
            if d.is_dir() and VERSION_RE.match(d.name):
                sources = []
                for s in sorted(d.iterdir()):
                    if s.is_dir():
                        fp = fingerprint(s)
                        sources.append({"source": s.name, "name": names.get(s.name, s.name),
                                        "files": fp.files, "mtime": _fmt(fp.mtime)})
                out.append({"version": d.name, "sources": sources})
    return out


def count_versions(data_dir: Path, game: str) -> int:
    base = Path(data_dir) / "versions" / game
    if not base.is_dir():
        return 0
    return sum(1 for d in base.iterdir() if d.is_dir() and not d.is_symlink() and VERSION_RE.match(d.name))


def prune_versions(data_dir: Path, game: str, keep: int, log=lambda m: None, protect: Optional[str] = None) -> List[str]:
    """Borra las versiones MÁS ANTIGUAS de `game` hasta dejar `keep` (0 = sin límite: no borra nada).

    Orden por el nombre de la versión (no por mtime). Nunca borra `protect` (la recién creada) ni deja
    menos de 1. Solo toca directorios reales dentro de data/versions/<slug>/ (symlinks se ignoran).
    Devuelve los nombres borrados. El llamador debe tener el lock del juego.
    """
    if keep <= 0:
        return []
    base = Path(data_dir) / "versions" / game
    root = (Path(data_dir) / "versions").resolve()
    if base.is_symlink() or not base.is_dir() or base.resolve().parent != root:
        return []
    base = base.resolve()
    dirs = sorted((d for d in base.iterdir()
                   if d.is_dir() and not d.is_symlink() and VERSION_RE.match(d.name)),
                  key=lambda d: _version_key(d.name))
    done: List[str] = []
    for d in dirs[: max(0, len(dirs) - keep)]:
        if d.name == protect or d.resolve().parent != base:
            continue
        try:
            shutil.rmtree(d)
        except OSError as e:
            log(f"no se pudo eliminar la versión {d.name}: {e}")
            continue
        done.append(d.name)
    if done:
        log(f"poda (máx. {keep}): eliminadas {len(done)} versiones antiguas: {', '.join(done)}")
    return done


@contextmanager
def _game_lock(data_dir: Path, gs: str):
    """Mismo lock por juego que run_sync; falla si hay otra operación en curso."""
    try:
        with locking.locked(Path(data_dir) / "locks" / f"{gs}.lock"):
            yield
    except locking.LockBusy:
        raise SyncAbort("err.sync.op_in_progress")


def _new_version_dir(data_dir: Path, game: str) -> Path:
    base = Path(data_dir) / "versions" / game
    base.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    d, i = base / stamp, 0
    while d.exists():
        i += 1
        d = base / f"{stamp}-{i}"
    d.mkdir()
    return d


def _replace_dir(src: Path, dst: Path):
    """Sustituye dst por copia de src de forma casi atómica."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    new = dst.with_name(dst.name + ".new")
    old = dst.with_name(dst.name + ".old")
    for t in (new, old):
        if t.exists():
            shutil.rmtree(t)
    shutil.copytree(src, new)
    if dst.exists():
        os.rename(dst, old)
    os.rename(new, dst)
    if old.exists():
        shutil.rmtree(old)


# Diferencia de mtime por debajo de la cual no se puede decir cuál es "el más reciente" (deriva de reloj).
CLOCK_TOLERANCE = 2


# ---- baseline: huella que cada participante tenía tras la última sync completa ----
def _state_path(data_dir: Path, game: str) -> Path:
    return Path(data_dir) / "state" / f"{game}.json"


def load_baseline(data_dir: Path, game: str) -> Dict[str, Optional[str]]:
    """{origen: hash|None}. None = estaba vacío. Sin fichero o ilegible = sin baseline (comportamiento seguro)."""
    try:
        raw = json.loads(_state_path(data_dir, game).read_text())
        base = raw["base"]
        if isinstance(base, dict) and all(v is None or isinstance(v, str) for v in base.values()):
            return dict(base)
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return {}


def save_baseline(data_dir: Path, game: str, updates: Dict[str, Optional[str]]) -> None:
    """Fusiona `updates` (origen -> hash) en el baseline. Escritura atómica."""
    p = _state_path(data_dir, game)
    p.parent.mkdir(parents=True, exist_ok=True)
    base = load_baseline(data_dir, game)
    base.update(updates)
    tmp = p.with_name(f".{p.name}.tmp")
    tmp.write_text(json.dumps({"base": base, "updated": datetime.now().isoformat(timespec="seconds")}))
    os.replace(tmp, p)


def _prefer_device(keys: List[str]) -> str:
    """Entre contenidos idénticos, el origen real es un dispositivo antes que el hub."""
    return next((k for k in keys if k != "hub"), keys[0])


def decide(fps: Dict[str, Fingerprint], base: Dict[str, Optional[str]]) -> dict:
    """Decide qué participantes (dispositivos en línea + 'hub') mandan. Función pura.

    Devuelve {"kind": "same"|"winner"|"conflict", "winner": clave, "sides": [claves], "reason": str}.
    `base[d]` = lo que el dispositivo d tenía (y el hub, igual) en su última sync; `base["hub"]` = lo que el hub
    tenía tras la última escritura. Con baseline completo:
    - un dispositivo cambió si su hash actual != su baseline; el hub cambió por fuera (p. ej. restaurar una
      versión) si hash != base["hub"];
    - un dispositivo que cambió sobre una base que el hub ya superó compite con el hub (conflicto);
    - si compite un único contenido, gana; si compiten varios distintos, conflicto; si nadie cambió, el hub
      (estado más reciente sincronizado) actualiza a los dispositivos rezagados.
    Sin baseline y contenidos distintos con datos -> conflicto (nunca se decide por mtime). Un lado vacío nunca
    gana a uno con datos (se rellena). Sin baseline y los dos dispositivos coinciden: el hub está desfasado.
    """
    if len({fp.hash for fp in fps.values()}) == 1:
        return {"kind": "same"}
    nonempty = [k for k, fp in fps.items() if not fp.empty]
    if len({fps[k].hash for k in nonempty}) == 1:
        return {"kind": "winner", "winner": _prefer_device(nonempty)}
    if all(k in base for k in fps):
        devs = [k for k in fps if k != "hub"]
        hub_h = fps["hub"].hash
        changed = [k for k in devs if not fps[k].empty and fps[k].hash != base[k]]
        holders = list(changed)
        stale_base = any(hub_h is not None and fps[k].hash != hub_h and base[k] != hub_h for k in changed)
        if not fps["hub"].empty and (stale_base or hub_h != base["hub"]):
            holders.append("hub")
        if holders:
            if len({fps[k].hash for k in holders}) == 1:
                return {"kind": "winner", "winner": _prefer_device(holders)}
            return {"kind": "conflict", "sides": holders, "reason": "both-changed"}
        if not fps["hub"].empty:  # nadie cambió: los dispositivos van por detrás del hub
            return {"kind": "winner", "winner": "hub"}
        return {"kind": "conflict", "sides": nonempty, "reason": "inconsistent"}
    devs = [k for k in nonempty if k != "hub"]
    if len(devs) > 1 and len({fps[k].hash for k in devs}) == 1:
        return {"kind": "winner", "winner": devs[0]}
    return {"kind": "conflict", "sides": nonempty, "reason": "no-baseline"}


def pick_resolution(resolution: str, sides: List[str], fps: Dict[str, Fingerprint],
                    dn: Callable[[str], str] = lambda k: k) -> Optional[str]:
    """Elige ganador para un conflicto. None = indeterminado (relojes demasiado parecidos).
    Lanza SyncAbort si `resolution` no es válida."""
    if resolution == "newest":
        ranked = sorted(sides, key=lambda k: fps[k].mtime, reverse=True)
        top = ranked[0]
        for k in ranked[1:]:
            if fps[k].hash != fps[top].hash and fps[top].mtime - fps[k].mtime < CLOCK_TOLERANCE:
                return None
        return _prefer_device([k for k in ranked if fps[k].hash == fps[top].hash])
    if resolution == "hub":
        name = "hub"
    elif resolution.startswith("device:"):
        name = resolution[len("device:"):]
    else:
        raise SyncAbort("err.sync.resolution_invalid", value=resolution)
    if name not in fps:
        raise SyncAbort("err.sync.side_unavailable", name=dn(name))
    if fps[name].empty:
        raise SyncAbort("err.sync.side_empty", name=dn(name))
    return name


def valid_resolution(value) -> bool:
    return isinstance(value, str) and (value in ("newest", "hub") or
                                       (value.startswith("device:") and len(value) > 7))


def _side(k: str, fp: Fingerprint, name: Optional[str] = None) -> dict:
    """Un lado de un conflicto: `id` es el origen (id de dispositivo o 'hub'), `name` lo que se muestra."""
    return {"id": k, "name": name or k, "hub": k == "hub", "mtime": fp.mtime, "size": fp.size, "files": fp.files, "hash": fp.hash}


def resolve_game(cfg: Config, ref) -> str:
    """Id del juego al que apunta `ref` (id o nombre). SyncAbort si no existe o es ambiguo."""
    try:
        gid = resolve_ref(cfg.games, ref)
    except ConfigError as e:
        raise SyncAbort("err.sync.ref_invalid", cause=e.body())
    if gid is None:
        raise SyncAbort("err.sync.game_unknown", ref=ref)
    return gid


def _origin_id(cfg: Config, gid: str, ref):
    """Id de origen de `ref` (id o nombre de uno de los dispositivos del juego, o 'hub'); si no, `ref` tal cual."""
    if ref == "hub" or not isinstance(ref, str):
        return ref
    devs = {d: cfg.devices[d] for d in cfg.games[gid].devices if d in cfg.devices}
    try:
        return resolve_ref(devs, ref) or ref
    except ConfigError as e:
        raise SyncAbort("err.sync.ref_invalid", cause=e.body())


def run_sync(cfg: Config, game: str, dry_run: bool = False, data_dir: Optional[Path] = None,
             log: Callable[[str], None] = print,
             transports: Optional[Dict[str, Transport]] = None,
             resolution: Optional[str] = None, expect: Optional[Dict[str, str]] = None,
             conflict_policy: Optional[str] = None) -> dict:
    """Devuelve dict de estado. Lanza SyncAbort si no se pudo ejecutar.

    game: id del juego o su nombre (se resuelve a id; todo lo interno usa el id).
    resolution: 'newest' | 'hub' | 'device:<id o nombre>' (sync manual, resuelve un conflicto).
    expect: {origen (id o nombre): hash} que el usuario vio al elegir; si ya no coincide se devuelve el conflicto nuevo.
    conflict_policy: 'skip' | 'newest' (sync automática); sin ninguno de los dos, un conflicto se devuelve sin tocar nada."""
    data_dir = Path(data_dir or settings.DATA_DIR)
    game = resolve_game(cfg, game)
    if resolution is not None and not valid_resolution(resolution):
        raise SyncAbort("err.sync.resolution_invalid", value=resolution)
    if resolution is not None and resolution.startswith("device:"):
        resolution = "device:" + _origin_id(cfg, game, resolution[len("device:"):])
    if expect:
        expect = {_origin_id(cfg, game, k): v for k, v in expect.items()}
    if conflict_policy is not None and conflict_policy not in ON_CONFLICT:
        raise SyncAbort("err.sync.policy_invalid", value=conflict_policy)
    g = cfg.games[game]
    started = datetime.now()
    gs = game  # el id interno es la única clave de rutas de disco; el nombre es solo la etiqueta
    logdir = data_dir / "logs" / gs
    logdir.mkdir(parents=True, exist_ok=True)
    logfile = logdir / (started.strftime("%Y-%m-%d_%H%M%S") + ".log")

    def L(msg):
        line = redact(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
        with open(logfile, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        log(line)

    status = {"game": game, "name": g.name, "dry_run": dry_run, "started": started.isoformat(timespec="seconds"),
              "result": "error", "message": "", "log": logfile.name}

    try:
        handle = locking.acquire(data_dir / "locks" / f"{gs}.lock")
    except locking.LockBusy:
        raise SyncAbort("err.sync.sync_in_progress")
    try:
        try:
            _do_sync(cfg, game, g, dry_run, data_dir, L, transports, status, resolution, expect, conflict_policy)
        except SyncAbort as e:
            _set(status, "aborted", e.code, **e.params)
            L(f"ABORTADO: {e}")
        except TransportError as e:
            _set(status, "error", e.code, **e.params)
            L(f"ERROR: {e}")
        except Exception as e:  # nunca dejar la excepción sin registrar
            _set(status, "error", "err.sync.unexpected", type=type(e).__name__, detail=str(e))
            L(f"ERROR inesperado: {type(e).__name__}: {e}")
    finally:
        handle.release()
    status["finished"] = datetime.now().isoformat(timespec="seconds")
    sd = data_dir / "status"
    sd.mkdir(parents=True, exist_ok=True)
    keep_conflict = False
    if dry_run and status["result"] != "conflict":  # un dry-run no borra la marca de conflicto pendiente
        try:
            keep_conflict = json.loads((sd / f"{gs}.json").read_text()).get("result") == "conflict"
        except (OSError, ValueError, AttributeError):
            pass
    if not keep_conflict:
        tmp = sd / f".{gs}.tmp"
        tmp.write_text(json.dumps(status))
        os.replace(tmp, sd / f"{gs}.json")
    return status


def _check_process(g, tr, online, L=None, dn=lambda k: k):
    if not g.process:
        return
    for n in online:
        try:
            running = tr[n].process_running(g.process)
        except TransportError as e:
            raise SyncAbort("err.sync.process_check_failed", device=dn(n), cause=e.body())
        if running:
            raise SyncAbort("err.sync.process_open", process=g.process, device=dn(n))
    if L:
        L(f"{g.process} no está abierto")


def _do_sync(cfg, game, g, dry_run, data_dir, L, transports, status, resolution=None, expect=None,
             conflict_policy=None):
    def resolution_text(r):  # 'device:<id>' -> 'device:<nombre>' para los logs
        return "device:" + dn(r[7:]) if isinstance(r, str) and r.startswith("device:") else r

    labels = list(g.devices)  # ids de dispositivo; en mensajes se muestra siempre el nombre

    def dn(k):
        return k if k == "hub" else (cfg.devices[k].name if k in cfg.devices else k)

    def dns(ks):
        return ", ".join(dn(k) for k in ks)

    tr = {n: (transports or {}).get(n) or get_transport(cfg.devices[n]) for n in labels}
    L(f"sync {g.name} {'(simulación (dry-run)) ' if dry_run else ''}entre {dn(labels[0])} y {dn(labels[1])}")

    # 1. Conectividad: un dispositivo offline se compara solo con el hub; si no responde ninguno, no se toca nada.
    online, offline = [], []
    for n in labels:
        try:
            tr[n].check()
            if getattr(tr[n], "first_use", False):
                L(f"{dn(n)}: host key guardada (primer uso)")
            L(f"{dn(n)}: conexión OK")
            online.append(n)
        except TransportError as e:
            L(f"{dn(n)}: no responde ({e})")
            offline.append(n)
    status["offline"] = offline
    if not online:
        raise SyncAbort("err.sync.all_offline", devices=dns(offline))
    if offline:
        L(f"{dns(offline)} offline: se compara {dn(online[0])} solo con el hub")

    # 2. Proceso abierto.
    _check_process(g, tr, online, L, dn)

    with tempfile.TemporaryDirectory(prefix="checkpoint-") as td:
        tmp = Path(td)
        dirs: Dict[str, Path] = {}
        # 3. Descarga a temporal.
        for n in online:
            d = tmp / n
            d.mkdir()
            if tr[n].exists(g.paths[n]):
                L(f"{dn(n)}: descargando {g.paths[n]}")
                tr[n].pull(g.paths[n], d)
            else:
                L(f"{dn(n)}: la ruta no existe todavía (se trata como vacía)")
            dirs[n] = d
        hub = data_dir / "hub" / game
        dirs["hub"] = hub

        fps = {k: fingerprint(v) for k, v in dirs.items()}
        for k, fp in fps.items():
            L(f"{dn(k)}: {fp.files} ficheros, hash {(fp.hash or '-')[:12]}, mtime máx {_fmt(fp.mtime)}")

        raw = load_baseline(data_dir, game)
        base = {k: raw[k] for k in fps if k in raw}
        L("baseline: " + ", ".join(f"{dn(k)}={'sí' if k in base else 'no'}" for k in fps))

        def remember(h):  # tras una sync completa todos los participantes en línea tienen `h`
            if not dry_run:
                save_baseline(data_dir, game, {k: h for k in fps})

        d = decide(fps, base)
        if d["kind"] == "same":
            if all(fp.empty for fp in fps.values()):
                _set(status, "ok", "err.sync.nothing_to_sync")
                L("nada que sincronizar")
            else:
                _set(status, "ok", "err.sync.already_synced")
                L("ya sincronizado: nada que hacer")
            remember(next(iter(fps.values())).hash)
            return

        if d["kind"] == "conflict":
            sides = d["sides"]
            winner, why = None, None
            if resolution is not None:
                stale = [k for k, h in (expect or {}).items() if k in fps and fps[k].hash != h]
                if stale:
                    why = "stale"
                    L(f"los datos cambiaron desde que se mostró el conflicto ({dns(stale)}); elige de nuevo")
                else:
                    winner = pick_resolution(resolution, sides, fps, dn)
                    if winner is None:
                        why = "indeterminate"
                    else:
                        L(f"conflicto resuelto manualmente ({resolution_text(resolution)}): gana {dn(winner)}")
            elif conflict_policy == "newest":
                winner = pick_resolution("newest", sides, fps)
                if winner is None:
                    why = "indeterminate"
                else:
                    L(f"conflicto resuelto por política 'newest': gana {dn(winner)}")
            if winner is None:
                reason = why or d["reason"]
                status["conflict"] = {"reason": reason, "policy": conflict_policy,
                                      "sides": [_side(k, fps[k], dn(k)) for k in sides]}
                text = {"indeterminate": "los relojes difieren menos de "
                                         f"{CLOCK_TOLERANCE} s: no se puede saber cuál es más reciente",
                        "stale": "los datos cambiaron desde que se mostró el conflicto",
                        "no-baseline": "primera sincronización con contenidos distintos",
                        "inconsistent": "los contenidos difieren sin cambios registrados",
                        "both-changed": "ambos lados cambiaron desde la última sincronización"}[reason]
                cause = error_body("err.sync.conflict_" + reason.replace("-", "_"),
                                   **({"seconds": CLOCK_TOLERANCE} if reason == "indeterminate" else {}))
                _set(status, "conflict", "err.sync.conflict", sides=dns(sides), cause=cause)
                L(f"CONFLICTO: {text}")
                for k in sides:
                    L(f"  {dn(k)}: {_fmt(fps[k].mtime)}, {fps[k].size} bytes, {fps[k].files} ficheros")
                L("no se modifica nada" + (" (política: omitir)" if conflict_policy == "skip" else ""))
                return
        else:
            winner = d["winner"]

        wh = fps[winner].hash
        targets = [k for k in fps if fps[k].hash != wh]
        L(f"ganador: {dn(winner)}")
        for k in targets:
            extra = "" if fps[k].empty else " (versión anterior se guarda)"
            L(f"plan: {dn(winner)} -> {dn(k)}{extra}")
        status["winner"], status["targets"] = winner, targets
        if dry_run:
            _set(status, "dry-run", "err.sync.dry_run", winner=dn(winner), targets=dns(targets))
            L("simulación (dry-run): no se modifica nada")
            return

        # 4. Re-comprobar el proceso justo antes de escribir (puede haberse abierto durante la descarga).
        _check_process(g, tr, online, dn=dn)

        # 5. Guardar versiones perdedoras (siempre antes de sobrescribir).
        new_version = None
        if any(not fps[k].empty for k in targets):
            vdir = _new_version_dir(data_dir, game)
            new_version = vdir.name
            for k in targets:
                if not fps[k].empty:
                    shutil.copytree(dirs[k], vdir / k)
                    L(f"versión guardada: {vdir.name}/{dn(k)}")
        # 6. Escribir: primero el hub (local, atómico), luego los dispositivos. Un fallo en un dispositivo
        #    no impide intentar el otro; el resultado es 'partial' y NO se actualiza ningún baseline.
        src = dirs[winner]
        if "hub" in targets:
            _replace_dir(src, hub)
            L("hub actualizado")
        failed = {}
        for k in targets:
            if k == "hub":
                continue
            extras = relfiles(dirs[k]) - relfiles(src)
            L(f"{dn(k)}: enviando")
            try:
                tr[k].push(src, g.paths[k], extras)
            except TransportError as e:
                failed[k] = e.body()
                L(f"ERROR enviando a {dn(k)}: {e}")
        if failed:
            ok = [k for k in targets if k not in failed]
            _set(status, "partial", "err.sync.partial" if ok else "err.sync.partial_none", winner=dn(winner),
                 updated=dns(ok), failed=[{"path": dn(k), **b} for k, b in failed.items()])
            status["failed"] = sorted(failed)
            L("sincronización PARCIAL: baseline sin actualizar; se completará en la próxima ejecución")
            return
        remember(wh)
        # 7. Poda (solo tras éxito, no en dry-run; dentro del lock del juego).
        prune_versions(data_dir, game, cfg.versions_limit(game), L, protect=new_version)
        if offline:
            _set(status, "ok", "err.sync.done_pending", winner=dn(winner), updated=dns(targets), offline=dns(offline))
        else:
            _set(status, "ok", "err.sync.done", winner=dn(winner), updated=dns(targets))
        L("sincronización completada")


def restore_version(cfg: Config, game: str, version: str, source: str, data_dir: Path) -> dict:
    """Copia una versión al hub con mtime=ahora; el siguiente sync la propaga.
    La copia actual del hub se guarda antes como versión. Devuelve el cuerpo {code, params} del aviso de éxito."""
    data_dir = Path(data_dir)
    game = resolve_game(cfg, game)
    if VERSION_RE.match(version):
        source = _origin_id(cfg, game, source)
    if not VERSION_RE.match(version) or source not in {d for d in (*cfg.games[game].devices, "hub")}:
        raise SyncAbort("err.sync.version_invalid")
    gs = game
    with _game_lock(data_dir, gs):
        src = data_dir / "versions" / gs / version / source
        if not src.is_dir():
            raise SyncAbort("err.sync.version_unknown")
        hub = data_dir / "hub" / gs
        new_version = None
        if hub.is_dir() and any(hub.iterdir()):
            vdir = _new_version_dir(data_dir, game)
            new_version = vdir.name
            shutil.copytree(hub, vdir / "hub")
        tmp = hub.parent / f".restore-{gs}"
        if tmp.exists():
            shutil.rmtree(tmp)
        shutil.copytree(src, tmp)
        now = datetime.now().timestamp()
        for p in tmp.rglob("*"):
            if p.is_file():
                os.utime(p, (now, now))
        _replace_dir(tmp, hub)
        shutil.rmtree(tmp)
        prune_versions(data_dir, game, cfg.versions_limit(game), protect=new_version)
    src_name = source if source == "hub" else cfg.devices[source].name
    return error_body("err.sync.restored", version=version, source=src_name)
