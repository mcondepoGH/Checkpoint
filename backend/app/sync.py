"""Lógica de sincronización de un juego entre dos dispositivos y el hub."""
import fcntl
import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional

from . import settings
from .config import NAME_RE, Config
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

    @property
    def empty(self) -> bool:
        return self.files == 0


def fingerprint(root: Path) -> Fingerprint:
    root = Path(root)
    if not root.is_dir():
        return Fingerprint(None, 0, 0)
    entries = []
    mt = 0
    for p in sorted(root.rglob("*")):
        if p.is_symlink() or not p.is_file():
            continue
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        entries.append(f"{p.relative_to(root).as_posix()}\0{h.hexdigest()}")
        mt = max(mt, int(p.stat().st_mtime))
    if not entries:
        return Fingerprint(None, 0, 0)
    return Fingerprint(hashlib.sha256("\n".join(entries).encode()).hexdigest(), mt, len(entries))


def relfiles(root: Path) -> set:
    root = Path(root)
    if not root.is_dir():
        return set()
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file() and not p.is_symlink()}


def _fmt(ts: int) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S") if ts else "-"


def list_versions(data_dir: Path, game: str) -> List[dict]:
    base = Path(data_dir) / "versions" / game
    out = []
    if base.is_dir():
        for d in sorted(base.iterdir(), reverse=True):
            if d.is_dir() and VERSION_RE.match(d.name):
                sources = []
                for s in sorted(d.iterdir()):
                    if s.is_dir():
                        fp = fingerprint(s)
                        sources.append({"source": s.name, "files": fp.files, "mtime": _fmt(fp.mtime)})
                out.append({"version": d.name, "sources": sources})
    return out


def prune_versions(data_dir: Path, game: str, keep: int, log=lambda m: None):
    base = Path(data_dir) / "versions" / game
    if not base.is_dir():
        return
    dirs = sorted(d for d in base.iterdir() if d.is_dir() and VERSION_RE.match(d.name))
    for d in dirs[: max(0, len(dirs) - keep)]:
        shutil.rmtree(d)
        log(f"versión antigua eliminada: {d.name}")


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


def run_sync(cfg: Config, game: str, dry_run: bool = False, data_dir: Optional[Path] = None,
             log: Callable[[str], None] = print,
             transports: Optional[Dict[str, Transport]] = None) -> dict:
    """Devuelve dict de estado. Lanza SyncAbort si no se pudo ejecutar."""
    data_dir = Path(data_dir or settings.DATA_DIR)
    if not NAME_RE.match(game) or game not in cfg.games:
        raise SyncAbort(f"juego desconocido: {game}")
    g = cfg.games[game]
    started = datetime.now()
    logdir = data_dir / "logs" / game
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
    lockf = open(locks / f"{game}.lock", "w")
    try:
        try:
            fcntl.flock(lockf, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SyncAbort("ya hay una sincronización de este juego en curso")
        try:
            _do_sync(cfg, game, g, dry_run, data_dir, L, transports, status)
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
    tmp = sd / f".{game}.tmp"
    tmp.write_text(json.dumps(status))
    os.replace(tmp, sd / f"{game}.json")
    return status


def _do_sync(cfg, game, g, dry_run, data_dir, L, transports, status):
    labels = list(g.devices)
    tr = {n: (transports or {}).get(n) or get_transport(cfg.devices[n]) for n in labels}
    L(f"sync {game} {'(dry-run) ' if dry_run else ''}entre {labels[0]} y {labels[1]}")

    # 1. Conectividad: si alguno no responde, no se toca nada.
    for n in labels:
        try:
            tr[n].check()
            if getattr(tr[n], "first_use", False):
                L(f"{n}: host key guardada (primer uso)")
            L(f"{n}: conexión OK")
        except TransportError as e:
            raise SyncAbort(f"{n} no responde ({e}); no se toca nada")

    # 2. Proceso abierto.
    if g.process:
        for n in labels:
            try:
                running = tr[n].process_running(g.process)
            except TransportError as e:
                raise SyncAbort(f"no se pudo comprobar el proceso en {n}: {e}")
            if running:
                raise SyncAbort(f"{g.process} está abierto en {n}")
        L(f"{g.process} no está abierto")

    with tempfile.TemporaryDirectory(prefix="savesync-") as td:
        tmp = Path(td)
        dirs: Dict[str, Path] = {}
        # 3. Descarga a temporal.
        for n in labels:
            d = tmp / n
            d.mkdir()
            if tr[n].exists(g.paths[n]):
                L(f"{n}: descargando {g.paths[n]}")
                tr[n].pull(g.paths[n], d)
            else:
                L(f"{n}: la ruta no existe todavía (se trata como vacía)")
            dirs[n] = d
        hub = data_dir / "hub" / game
        dirs["hub"] = hub

        fps = {k: fingerprint(v) for k, v in dirs.items()}
        for k, fp in fps.items():
            L(f"{k}: {fp.files} ficheros, hash {(fp.hash or '-')[:12]}, mtime máx {_fmt(fp.mtime)}")

        cands = [k for k, fp in fps.items() if not fp.empty]
        if not cands:
            status.update(result="ok", message="nada que sincronizar (todo vacío)")
            L("nada que sincronizar")
            return
        top = max(fps[k].mtime for k in cands)
        newest = [k for k in cands if fps[k].mtime == top]
        if len({fps[k].hash for k in newest}) > 1:
            raise SyncAbort("empate de mtime con contenido distinto entre " + ", ".join(newest)
                            + "; resuelve a mano")
        winner = newest[0]
        for k in newest:  # preferir un dispositivo sobre el hub si son iguales
            if k != "hub":
                winner = k
                break
        wh = fps[winner].hash
        targets = [k for k in dirs if fps[k].hash != wh]
        if not targets:
            status.update(result="ok", message="ya sincronizado")
            L("ya sincronizado: nada que hacer")
            return

        L(f"ganador: {winner}")
        for k in targets:
            extra = "" if fps[k].empty else " (versión anterior se guarda)"
            L(f"plan: {winner} -> {k}{extra}")
        status["winner"], status["targets"] = winner, targets
        if dry_run:
            status.update(result="dry-run", message=f"ganador {winner}; destinos {', '.join(targets)}")
            L("dry-run: no se modifica nada")
            return

        # 4. Guardar versiones perdedoras.
        if any(not fps[k].empty for k in targets):
            vdir = _new_version_dir(data_dir, game)
            for k in targets:
                if not fps[k].empty:
                    shutil.copytree(dirs[k], vdir / k)
                    L(f"versión guardada: {vdir.name}/{k}")
        # 5. Enviar el ganador.
        src = dirs[winner]
        for k in targets:
            if k == "hub":
                continue
            extras = relfiles(dirs[k]) - relfiles(src)
            L(f"{k}: enviando")
            tr[k].push(src, g.paths[k], extras)
        if "hub" in targets:
            _replace_dir(src, hub)
            L("hub actualizado")
        prune_versions(data_dir, game, g.keep_versions, L)
        status.update(result="ok", message=f"ganador {winner}; actualizados {', '.join(targets)}")
        L("sincronización completada")


def restore_version(cfg: Config, game: str, version: str, source: str, data_dir: Path) -> str:
    """Copia una versión al hub con mtime=ahora; el siguiente sync la propaga.
    La copia actual del hub se guarda antes como versión."""
    data_dir = Path(data_dir)
    if game not in cfg.games or not VERSION_RE.match(version) or source not in (*cfg.games[game].devices, "hub"):
        raise SyncAbort("versión/origen inválido")
    src = data_dir / "versions" / game / version / source
    if not src.is_dir():
        raise SyncAbort("no existe esa versión")
    hub = data_dir / "hub" / game
    if hub.is_dir() and any(hub.iterdir()):
        vdir = _new_version_dir(data_dir, game)
        shutil.copytree(hub, vdir / "hub")
    tmp = hub.parent / f".restore-{game}"
    if tmp.exists():
        shutil.rmtree(tmp)
    shutil.copytree(src, tmp)
    now = datetime.now().timestamp()
    for p in tmp.rglob("*"):
        if p.is_file():
            os.utime(p, (now, now))
    _replace_dir(tmp, hub)
    shutil.rmtree(tmp)
    prune_versions(data_dir, game, cfg.games[game].keep_versions)
    return f"hub restaurado desde {version}/{source}; ejecuta Sincronizar para propagarlo"
