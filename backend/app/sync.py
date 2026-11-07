"""Lógica de sincronización de un juego entre dos dispositivos y el hub."""
import fcntl
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

from . import settings
from .config import Config, slug_for
from .redact import redact
from .transport import Transport, TransportError, get_transport

VERSION_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{6}(-\d+)?$")


class SyncAbort(Exception):
    """Fin controlado sin tocar nada (o error ya reportado)."""


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


def list_versions(data_dir: Path, game: str) -> List[dict]:
    base = Path(data_dir) / "versions" / slug_for(game)
    out = []
    if base.is_dir():
        for d in sorted(base.iterdir(), key=lambda d: _version_key(d.name), reverse=True):
            if d.is_dir() and VERSION_RE.match(d.name):
                sources = []
                for s in sorted(d.iterdir()):
                    if s.is_dir():
                        fp = fingerprint(s)
                        sources.append({"source": s.name, "files": fp.files, "mtime": _fmt(fp.mtime)})
                out.append({"version": d.name, "sources": sources})
    return out


def count_versions(data_dir: Path, game: str) -> int:
    base = Path(data_dir) / "versions" / slug_for(game)
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
    base = Path(data_dir) / "versions" / slug_for(game)
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
    locks = Path(data_dir) / "locks"
    locks.mkdir(parents=True, exist_ok=True)
    f = open(locks / f"{gs}.lock", "w")
    try:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SyncAbort("ya hay una operación de este juego en curso")
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)
    finally:
        f.close()


def _new_version_dir(data_dir: Path, game: str) -> Path:
    base = Path(data_dir) / "versions" / slug_for(game)
    base.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    d, i = base / stamp, 0
    while d.exists():
        i += 1
        d = base / f"{stamp}-{i}"
    d.mkdir()
    return d


def _src(k: str) -> str:
    """Carpeta de un origen (dispositivo o hub) dentro de una versión."""
    return k if k == "hub" else slug_for(k)


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


ON_CONFLICT = ("skip", "newest")
DEFAULT_ON_CONFLICT = "skip"
# Diferencia de mtime por debajo de la cual no se puede decir cuál es "el más reciente" (deriva de reloj).
CLOCK_TOLERANCE = 2


# ---- baseline: huella que cada participante tenía tras la última sync completa ----
def _state_path(data_dir: Path, game: str) -> Path:
    return Path(data_dir) / "state" / f"{slug_for(game)}.json"


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
    - Un lado cambió si su hash actual != su baseline; si solo cambió uno (o varios con contenido idéntico), gana.
    - Cambiaron varios con contenido distinto -> conflicto. Sin baseline para alguno y contenidos distintos -> conflicto.
    - Sin baseline y los dos dispositivos coinciden entre sí: el hub (almacén pasivo) se considera desfasado.
    - Un lado vacío nunca gana a uno con datos (se rellena); no depende del reloj.
    """
    if len({fp.hash for fp in fps.values()}) == 1:
        return {"kind": "same"}
    nonempty = [k for k, fp in fps.items() if not fp.empty]
    if len({fps[k].hash for k in nonempty}) == 1:
        return {"kind": "winner", "winner": _prefer_device(nonempty)}
    if all(k in base for k in fps):
        changed = [k for k in nonempty if fps[k].hash != base[k]]
        if len({fps[k].hash for k in changed}) == 1:
            return {"kind": "winner", "winner": _prefer_device(changed)}
        if changed:
            return {"kind": "conflict", "sides": changed, "reason": "both-changed"}
        return {"kind": "conflict", "sides": nonempty, "reason": "inconsistent"}
    devs = [k for k in nonempty if k != "hub"]
    if len(devs) > 1 and len({fps[k].hash for k in devs}) == 1:  # los dos dispositivos coinciden: el hub está desfasado
        return {"kind": "winner", "winner": devs[0]}
    return {"kind": "conflict", "sides": nonempty, "reason": "no-baseline"}


def pick_resolution(resolution: str, sides: List[str], fps: Dict[str, Fingerprint]) -> Optional[str]:
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
        raise SyncAbort(f"resolución inválida: {resolution!r}")
    if name not in fps:
        raise SyncAbort(f"{name} no está disponible para resolver (offline o desconocido)")
    if fps[name].empty:
        raise SyncAbort(f"{name} no tiene datos: no puede ganar")
    return name


def valid_resolution(value) -> bool:
    return isinstance(value, str) and (value in ("newest", "hub") or
                                       (value.startswith("device:") and len(value) > 7))


def _side(k: str, fp: Fingerprint) -> dict:
    return {"name": k, "hub": k == "hub", "mtime": fp.mtime, "size": fp.size, "files": fp.files, "hash": fp.hash}


def run_sync(cfg: Config, game: str, dry_run: bool = False, data_dir: Optional[Path] = None,
             log: Callable[[str], None] = print,
             transports: Optional[Dict[str, Transport]] = None,
             resolution: Optional[str] = None, expect: Optional[Dict[str, str]] = None,
             conflict_policy: Optional[str] = None) -> dict:
    """Devuelve dict de estado. Lanza SyncAbort si no se pudo ejecutar.

    resolution: 'newest' | 'hub' | 'device:<nombre>' (sync manual, resuelve un conflicto).
    expect: {origen: hash} que el usuario vio al elegir; si ya no coincide se devuelve el conflicto nuevo.
    conflict_policy: 'skip' | 'newest' (sync automática); sin ninguno de los dos, un conflicto se devuelve sin tocar nada."""
    data_dir = Path(data_dir or settings.DATA_DIR)
    if not isinstance(game, str) or game not in cfg.games:
        raise SyncAbort(f"juego desconocido: {game}")
    if resolution is not None and not valid_resolution(resolution):
        raise SyncAbort(f"resolución inválida: {resolution!r}")
    if conflict_policy is not None and conflict_policy not in ON_CONFLICT:
        raise SyncAbort(f"política de conflicto inválida: {conflict_policy!r}")
    g = cfg.games[game]
    started = datetime.now()
    gs = slug_for(game)  # el nombre visible nunca se usa como ruta de disco
    logdir = data_dir / "logs" / gs
    logdir.mkdir(parents=True, exist_ok=True)
    logfile = logdir / (started.strftime("%Y-%m-%d_%H%M%S") + ".log")

    def L(msg):
        line = redact(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
        with open(logfile, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        log(line)

    status = {"game": game, "dry_run": dry_run, "started": started.isoformat(timespec="seconds"),
              "result": "error", "message": "", "log": logfile.name}

    locks = data_dir / "locks"
    locks.mkdir(parents=True, exist_ok=True)
    lockf = open(locks / f"{gs}.lock", "w")
    try:
        try:
            fcntl.flock(lockf, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SyncAbort("ya hay una sincronización de este juego en curso")
        try:
            _do_sync(cfg, game, g, dry_run, data_dir, L, transports, status, resolution, expect, conflict_policy)
        except SyncAbort as e:
            status["result"], status["message"] = "aborted", str(e)
            L(f"ABORTADO: {e}")
        except TransportError as e:
            status["result"], status["message"] = "error", str(e)
            L(f"ERROR: {e}")
        except Exception as e:  # nunca dejar la excepción sin registrar
            status["result"], status["message"] = "error", f"{type(e).__name__}: {e}"
            L(f"ERROR inesperado: {type(e).__name__}: {e}")
    finally:
        fcntl.flock(lockf, fcntl.LOCK_UN)
        lockf.close()
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


def _check_process(g, tr, online, L=None):
    if not g.process:
        return
    for n in online:
        try:
            running = tr[n].process_running(g.process)
        except TransportError as e:
            raise SyncAbort(f"no se pudo comprobar el proceso en {n}: {e}")
        if running:
            raise SyncAbort(f"{g.process} está abierto en {n}")
    if L:
        L(f"{g.process} no está abierto")


def _do_sync(cfg, game, g, dry_run, data_dir, L, transports, status, resolution=None, expect=None,
             conflict_policy=None):
    labels = list(g.devices)
    tr = {n: (transports or {}).get(n) or get_transport(cfg.devices[n]) for n in labels}
    L(f"sync {game} {'(dry-run) ' if dry_run else ''}entre {labels[0]} y {labels[1]}")

    # 1. Conectividad: un dispositivo offline se compara solo con el hub; si no responde ninguno, no se toca nada.
    online, offline = [], []
    for n in labels:
        try:
            tr[n].check()
            if getattr(tr[n], "first_use", False):
                L(f"{n}: host key guardada (primer uso)")
            L(f"{n}: conexión OK")
            online.append(n)
        except TransportError as e:
            L(f"{n}: no responde ({e})")
            offline.append(n)
    status["offline"] = offline
    if not online:
        raise SyncAbort(f"{' y '.join(offline)} no responden; no se toca nada")
    if offline:
        L(f"{', '.join(offline)} offline: se compara {online[0]} solo con el hub")

    # 2. Proceso abierto.
    _check_process(g, tr, online, L)

    with tempfile.TemporaryDirectory(prefix="checkpoint-") as td:
        tmp = Path(td)
        dirs: Dict[str, Path] = {}
        # 3. Descarga a temporal.
        for n in online:
            d = tmp / slug_for(n)
            d.mkdir()
            if tr[n].exists(g.paths[n]):
                L(f"{n}: descargando {g.paths[n]}")
                tr[n].pull(g.paths[n], d)
            else:
                L(f"{n}: la ruta no existe todavía (se trata como vacía)")
            dirs[n] = d
        hub = data_dir / "hub" / slug_for(game)
        dirs["hub"] = hub

        fps = {k: fingerprint(v) for k, v in dirs.items()}
        for k, fp in fps.items():
            L(f"{k}: {fp.files} ficheros, hash {(fp.hash or '-')[:12]}, mtime máx {_fmt(fp.mtime)}")

        raw = load_baseline(data_dir, game)
        base = {k: raw[_src(k)] for k in fps if _src(k) in raw}
        L("baseline: " + ", ".join(f"{k}={'sí' if k in base else 'no'}" for k in fps))

        def remember(h):  # tras una sync completa todos los participantes en línea tienen `h`
            if not dry_run:
                save_baseline(data_dir, game, {_src(k): h for k in fps})

        d = decide(fps, base)
        if d["kind"] == "same":
            if all(fp.empty for fp in fps.values()):
                status.update(result="ok", message="nada que sincronizar (todo vacío)")
                L("nada que sincronizar")
            else:
                status.update(result="ok", message="ya sincronizado")
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
                    L(f"los datos cambiaron desde que se mostró el conflicto ({', '.join(stale)}); elige de nuevo")
                else:
                    winner = pick_resolution(resolution, sides, fps)
                    if winner is None:
                        why = "indeterminate"
                    else:
                        L(f"conflicto resuelto manualmente ({resolution}): gana {winner}")
            elif conflict_policy == "newest":
                winner = pick_resolution("newest", sides, fps)
                if winner is None:
                    why = "indeterminate"
                else:
                    L(f"conflicto resuelto por política 'newest': gana {winner}")
            if winner is None:
                reason = why or d["reason"]
                status["conflict"] = {"reason": reason, "policy": conflict_policy,
                                      "sides": [_side(k, fps[k]) for k in sides]}
                text = {"indeterminate": "los relojes difieren menos de "
                                         f"{CLOCK_TOLERANCE} s: no se puede saber cuál es más reciente",
                        "stale": "los datos cambiaron desde que se mostró el conflicto",
                        "no-baseline": "primera sincronización con contenidos distintos",
                        "inconsistent": "los contenidos difieren sin cambios registrados",
                        "both-changed": "ambos lados cambiaron desde la última sincronización"}[reason]
                status.update(result="conflict", message=f"conflicto en {', '.join(sides)}: {text}")
                L(f"CONFLICTO: {text}")
                for k in sides:
                    L(f"  {k}: {_fmt(fps[k].mtime)}, {fps[k].size} bytes, {fps[k].files} ficheros")
                L("no se modifica nada" + (" (política: omitir)" if conflict_policy == "skip" else ""))
                return
        else:
            winner = d["winner"]

        wh = fps[winner].hash
        targets = [k for k in fps if fps[k].hash != wh]
        L(f"ganador: {winner}")
        for k in targets:
            extra = "" if fps[k].empty else " (versión anterior se guarda)"
            L(f"plan: {winner} -> {k}{extra}")
        status["winner"], status["targets"] = winner, targets
        if dry_run:
            status.update(result="dry-run", message=f"ganador {winner}; destinos {', '.join(targets)}")
            L("dry-run: no se modifica nada")
            return

        # 4. Re-comprobar el proceso justo antes de escribir (puede haberse abierto durante la descarga).
        _check_process(g, tr, online)

        # 5. Guardar versiones perdedoras (siempre antes de sobrescribir).
        new_version = None
        if any(not fps[k].empty for k in targets):
            vdir = _new_version_dir(data_dir, game)
            new_version = vdir.name
            for k in targets:
                if not fps[k].empty:
                    shutil.copytree(dirs[k], vdir / _src(k))
                    L(f"versión guardada: {vdir.name}/{_src(k)}")
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
            L(f"{k}: enviando")
            try:
                tr[k].push(src, g.paths[k], extras)
            except TransportError as e:
                failed[k] = str(e)
                L(f"ERROR enviando a {k}: {e}")
        if failed:
            ok = [k for k in targets if k not in failed]
            status.update(result="partial", failed=sorted(failed),
                          message=f"ganador {winner}; actualizados {', '.join(ok) or 'ninguno'}; "
                                  f"fallaron {', '.join(f'{k} ({m})' for k, m in failed.items())}")
            L("sincronización PARCIAL: baseline sin actualizar; se completará en la próxima ejecución")
            return
        remember(wh)
        # 7. Poda (solo tras éxito, no en dry-run; dentro del lock del juego).
        prune_versions(data_dir, game, cfg.versions_limit(game), L, protect=new_version)
        note = f" ({', '.join(offline)} offline: pendiente)" if offline else ""
        status.update(result="ok", message=f"ganador {winner}; actualizados {', '.join(targets)}{note}")
        L("sincronización completada")


def restore_version(cfg: Config, game: str, version: str, source: str, data_dir: Path) -> str:
    """Copia una versión al hub con mtime=ahora; el siguiente sync la propaga.
    La copia actual del hub se guarda antes como versión."""
    data_dir = Path(data_dir)
    if game not in cfg.games or not VERSION_RE.match(version) \
            or source not in {_src(d) for d in (*cfg.games[game].devices, "hub")}:
        raise SyncAbort("versión/origen inválido")
    gs = slug_for(game)
    with _game_lock(data_dir, gs):
        src = data_dir / "versions" / gs / version / source
        if not src.is_dir():
            raise SyncAbort("no existe esa versión")
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
    return f"hub restaurado desde {version}/{source}; ejecuta Sincronizar para propagarlo"
