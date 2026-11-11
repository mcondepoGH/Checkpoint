"""Lógica de sincronización de un juego entre dos dispositivos y el hub."""

import json
import logging
import os
import shutil
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, Optional

from . import locking
from ..core import settings
from ..core.errors import describe_code, error_body
from ..config.models import ON_CONFLICT, Config, ConfigError, resolve_ref
from ..core.redact import redact

# Reexportados (API pública de sync.engine): baseline, decide, fingerprint y versions viven en sus módulos.
from .baseline import load_baseline, save_baseline
from .decide import CLOCK_TOLERANCE, decide, pick_resolution, valid_resolution
from .errors import SyncAbort
from .fingerprint import Fingerprint, fingerprint, relfiles
from .transport import Transport, TransportError, get_transport
from .versions import VERSION_RE, _fmt, _new_version_dir, _replace_dir, count_versions, list_versions, prune_versions

slog = logging.getLogger(
    "checkpoint.sync"
)  # DEBUG: trazas de run_sync (rutas y nº de ficheros, nunca contenidos ni secretos)


def _set(status: dict, result: str, code: str, **params):
    """Resultado con mensaje estructurado: `code`/`params` (la UI los traduce). `message` es solo el respaldo
    técnico que leen scheduler, historial y CLI (code + params, no traducido)."""
    status.update(result=result, code=code, params=params, message=describe_code(code, params))


@contextmanager
def _game_lock(data_dir: Path, gs: str):
    """Mismo lock por juego que run_sync; falla si hay otra operación en curso."""
    try:
        with locking.locked(Path(data_dir) / "locks" / f"{gs}.lock"):
            yield
    except locking.LockBusy:
        raise SyncAbort("err.sync.op_in_progress")


def _side(k: str, fp: Fingerprint, name: Optional[str] = None) -> dict:
    """Un lado de un conflicto: `id` es el origen (id de dispositivo o 'hub'), `name` lo que se muestra."""
    return {
        "id": k,
        "name": name or k,
        "hub": k == "hub",
        "mtime": fp.mtime,
        "size": fp.size,
        "files": fp.files,
        "hash": fp.hash,
    }


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


def run_sync(
    cfg: Config,
    game: str,
    dry_run: bool = False,
    data_dir: Optional[Path] = None,
    log: Callable[[str], None] = print,
    transports: Optional[Dict[str, Transport]] = None,
    resolution: Optional[str] = None,
    expect: Optional[Dict[str, str]] = None,
    conflict_policy: Optional[str] = None,
    automatic: bool = False,
) -> dict:
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
        resolution = "device:" + _origin_id(cfg, game, resolution[len("device:") :])
    if expect:
        expect = {_origin_id(cfg, game, k): v for k, v in expect.items()}
    if conflict_policy is not None and conflict_policy not in ON_CONFLICT:
        raise SyncAbort("err.sync.policy_invalid", value=conflict_policy)
    g = cfg.games[game]
    if not g.enabled:  # guarda central: cubre CLI, API, ciclo, aviso de apertura/cierre y simulación
        raise SyncAbort("err.sync.game_disabled")
    started, t_run = datetime.now(), time.monotonic()
    slog.debug(
        "run_sync inicio: juego=%s dry_run=%s resolution=%s política=%s", game, dry_run, resolution, conflict_policy
    )
    gs = game  # el id interno es la única clave de rutas de disco; el nombre es solo la etiqueta
    logdir = data_dir / "logs" / gs
    logdir.mkdir(parents=True, exist_ok=True)
    logfile = logdir / (started.strftime("%Y-%m-%d_%H%M%S") + ".log")

    def L(msg):
        line = redact(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
        with open(logfile, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        log(line)

    status = {
        "game": game,
        "name": g.name,
        "dry_run": dry_run,
        "started": started.isoformat(timespec="seconds"),
        "result": "error",
        "message": "",
        "log": logfile.name,
    }

    try:
        handle = locking.acquire(data_dir / "locks" / f"{gs}.lock")
    except locking.LockBusy:
        slog.debug("run_sync: juego=%s lock ocupado tras %.0f ms", game, (time.monotonic() - t_run) * 1000)
        raise SyncAbort("err.sync.sync_in_progress")
    try:
        try:
            _do_sync(
                cfg, game, g, dry_run, data_dir, L, transports, status, resolution, expect, conflict_policy, automatic
            )
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
    slog.debug(
        "run_sync fin: juego=%s resultado=%s code=%s duración=%.2f s",
        game,
        status.get("result"),
        status.get("code"),
        time.monotonic() - t_run,
    )
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


def _do_sync(
    cfg,
    game,
    g,
    dry_run,
    data_dir,
    L,
    transports,
    status,
    resolution=None,
    expect=None,
    conflict_policy=None,
    automatic=False,
):
    def resolution_text(r):  # 'device:<id>' -> 'device:<nombre>' para los logs
        return "device:" + dn(r[7:]) if isinstance(r, str) and r.startswith("device:") else r

    labels = list(g.devices)  # ids de dispositivo; en mensajes se muestra siempre el nombre

    def dn(k):
        return k if k == "hub" else (cfg.devices[k].name if k in cfg.devices else k)

    def dns(ks):
        return ", ".join(dn(k) for k in ks)

    tr = {n: (transports or {}).get(n) or get_transport(cfg.devices[n]) for n in labels}
    where = f"entre {dn(labels[0])} y {dn(labels[1])}" if len(labels) > 1 else f"en {dn(labels[0])} (checkpoint)"
    L(f"sync {g.name} {'(simulación (dry-run)) ' if dry_run else ''}{where}")

    # 1. Conectividad: un dispositivo offline se compara solo con el hub; si no responde ninguno, no se toca nada.
    online, offline = [], []
    for n in labels:
        t_c = time.monotonic()
        try:
            tr[n].check()
            slog.debug("juego=%s %s: conexión OK en %.0f ms", game, dn(n), (time.monotonic() - t_c) * 1000)
            if getattr(tr[n], "first_use", False):
                L(f"{dn(n)}: host key guardada (primer uso)")
            L(f"{dn(n)}: conexión OK")
            online.append(n)
        except TransportError as e:
            slog.debug(
                "juego=%s %s: sin conexión (%s) tras %.0f ms", game, dn(n), e.code, (time.monotonic() - t_c) * 1000
            )
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
        missing = []  # dispositivos cuya ruta de guardado no existe (distinto de existir vacía)
        # 3. Descarga a temporal.
        for n in online:
            d = tmp / n
            d.mkdir()
            if tr[n].exists(g.paths[n]):
                L(f"{dn(n)}: descargando {g.paths[n]}")
                t_p = time.monotonic()
                tr[n].pull(g.paths[n], d)
                slog.debug("juego=%s %s: pull de %s en %.2f s", game, dn(n), g.paths[n], time.monotonic() - t_p)
            else:
                L(f"{dn(n)}: la ruta no existe todavía (se trata como vacía)")
                missing.append(n)
            dirs[n] = d
        hub = data_dir / "hub" / game
        dirs["hub"] = hub

        fps = {k: fingerprint(v) for k, v in dirs.items()}
        for k, fp in fps.items():
            slog.debug(
                "juego=%s %s: huella ficheros=%d bytes=%d hash=%s",
                game,
                dn(k),
                fp.files,
                fp.size,
                (fp.hash or "-")[:12],
            )
            L(f"{dn(k)}: {fp.files} ficheros, hash {(fp.hash or '-')[:12]}, mtime máx {_fmt(fp.mtime)}")

        # Juego de un dispositivo: si la partida local no existe (juego desinstalado, carpeta borrada) y el hub
        # tiene datos, solo un sync manual restaura; el automático no recrea la carpeta ni toca nada.
        if automatic and len(g.devices) == 1 and missing and not fps["hub"].empty:
            _set(status, "skipped", "err.sync.local_missing_manual_required")
            L(
                "la partida local no existe y el hub tiene datos: el sync automático no restaura; "
                "haz un sync manual para recuperarla"
            )
            return

        raw = load_baseline(data_dir, game)
        base = {k: raw[k] for k in fps if k in raw}
        L("baseline: " + ", ".join(f"{dn(k)}={'sí' if k in base else 'no'}" for k in fps))

        def remember(h):  # tras una sync completa todos los participantes en línea tienen `h`
            if not dry_run:
                save_baseline(data_dir, game, {k: h for k in fps})

        d = decide(fps, base)
        slog.debug("juego=%s decisión: %s%s", game, d["kind"], f" ganador={dn(d['winner'])}" if d.get("winner") else "")
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
                status["conflict"] = {
                    "reason": reason,
                    "policy": conflict_policy,
                    "sides": [_side(k, fps[k], dn(k)) for k in sides],
                }
                text = {
                    "indeterminate": "los relojes difieren menos de "
                    f"{CLOCK_TOLERANCE} s: no se puede saber cuál es más reciente",
                    "stale": "los datos cambiaron desde que se mostró el conflicto",
                    "no-baseline": "primera sincronización con contenidos distintos",
                    "inconsistent": "los contenidos difieren sin cambios registrados",
                    "both-changed": "ambos lados cambiaron desde la última sincronización",
                }[reason]
                cause = error_body(
                    "err.sync.conflict_" + reason.replace("-", "_"),
                    **({"seconds": CLOCK_TOLERANCE} if reason == "indeterminate" else {}),
                )
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
            t_s = time.monotonic()
            try:
                tr[k].push(src, g.paths[k], extras)
                slog.debug(
                    "juego=%s %s: push a %s en %.2f s (%d ficheros a borrar)",
                    game,
                    dn(k),
                    g.paths[k],
                    time.monotonic() - t_s,
                    len(extras),
                )
            except TransportError as e:
                failed[k] = e.body()
                L(f"ERROR enviando a {dn(k)}: {e}")
        if failed:
            ok = [k for k in targets if k not in failed]
            _set(
                status,
                "partial",
                "err.sync.partial" if ok else "err.sync.partial_none",
                winner=dn(winner),
                updated=dns(ok),
                failed=[{"path": dn(k), **b} for k, b in failed.items()],
            )
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
