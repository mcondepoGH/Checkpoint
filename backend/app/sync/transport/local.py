"""Transporte de «Este equipo» (solo fuera de Docker): Python puro, sin SSH."""

import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Iterable

from ...core.errors import describe_code
from ...config.models import PROC_RE, Device
from .base import Transport, TransportError, _err


# ---------------------------------------------------------------------------------------------------------
# «Este equipo»: el dispositivo es la propia máquina donde corre Checkpoint (solo fuera de Docker).
# Sin SSH, sin rsync, sin tar, sin shell: Python puro (os/shutil) y listas de argumentos para pgrep/tasklist.
# Garantías equivalentes a las del remoto: pull a una carpeta temporal, push atómico (carpeta nueva al lado +
# rename; si no es posible, reemplazo fichero a fichero atómico), mtime preservado, la carpeta de saves
# inexistente cuenta como vacía y nada se lee ni escribe fuera de ella (los symlinks nunca se siguen).
# ---------------------------------------------------------------------------------------------------------
def _oserr(e: OSError) -> str:
    return e.strerror or type(e).__name__


def local_path(path) -> Path:
    """Valida una ruta de saves local: texto, sin NUL, absoluta en este sistema y sin '..'."""
    if not isinstance(path, str) or not path.strip():
        raise TransportError("err.transport.path_empty")
    if "\x00" in path:
        raise TransportError("err.transport.path_null")
    if ".." in path.replace("\\", "/").split("/"):
        raise TransportError("err.transport.path_dotdot")
    if not os.path.isabs(path):
        raise TransportError("err.transport.path_not_absolute", path=path)
    return Path(os.path.abspath(path))


def _resolve(p: Path) -> Path:
    """Ruta real (resuelve symlinks de la propia carpeta de saves, que es decisión del usuario)."""
    try:
        return Path(os.path.realpath(p))
    except (OSError, RuntimeError, ValueError) as e:
        raise TransportError("err.transport.path_unresolvable", detail=str(e))


def _walk_files(root: Path):
    """(rutas relativas de ficheros regulares, de carpetas, de symlinks) bajo root sin seguir symlinks."""
    files, dirs, links = [], [], []
    for cur, dnames, fnames in os.walk(root, followlinks=False, onerror=_walk_err):
        rel = os.path.relpath(cur, root)
        rel = "" if rel == "." else rel
        for d in list(dnames):
            full = os.path.join(cur, d)
            if os.path.islink(full):
                links.append(os.path.join(rel, d))
                dnames.remove(d)
            else:
                dirs.append(os.path.join(rel, d))
        for f in fnames:
            full = os.path.join(cur, f)
            if os.path.islink(full):
                links.append(os.path.join(rel, f))
            elif os.path.isfile(full):
                files.append(os.path.join(rel, f))
    return files, dirs, links


def _walk_err(e):
    raise TransportError("err.transport.read_failed", path=e.filename, detail=_oserr(e))


def _copy_tree(src: Path, dst: Path):
    """Copia ficheros y carpetas (con mtime) ignorando symlinks y ficheros especiales."""
    files, dirs, _ = _walk_files(src)
    dst.mkdir(parents=True, exist_ok=True)
    for d in dirs:
        (dst / d).mkdir(parents=True, exist_ok=True)
    for f in files:
        try:
            shutil.copy2(src / f, dst / f)
        except OSError as e:
            raise TransportError("err.transport.copy_failed", file=f, detail=_oserr(e))


def _tmp_name(base: Path, tag: str) -> Path:
    return base.with_name(f".{base.name}.checkpoint-{tag}-{uuid.uuid4().hex[:8]}")


class LocalDeviceTransport(Transport):
    first_use = False

    def __init__(self, dev: Device = None, run=subprocess.run):
        self.dev = dev
        self._run = run

    # el equipo local siempre está «online»
    def check(self) -> None:
        return None

    def exists(self, path: str) -> bool:
        root = _resolve(local_path(path))
        try:
            if not root.exists():
                return False
            if not root.is_dir():
                raise TransportError("err.transport.not_a_folder", path=path)
            if not os.access(root, os.R_OK | os.X_OK):
                raise TransportError("err.transport.no_read_permission", path=path)
        except PermissionError as e:
            raise TransportError("err.transport.access_denied", path=path, detail=_oserr(e))
        except OSError as e:
            raise TransportError("err.transport.access_failed", path=path, detail=_oserr(e))
        return True

    def pull(self, path: str, dest: Path) -> None:
        root = _resolve(local_path(path))
        if not root.is_dir():
            raise TransportError("err.transport.folder_missing", path=path)
        _copy_tree(root, Path(dest))

    def push(self, src: Path, path: str, extras: Iterable[str] = ()) -> None:
        src = Path(src)
        target = _resolve(local_path(path))
        if target.exists() and not target.is_dir():
            raise TransportError("err.transport.not_a_folder", path=path)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise TransportError("err.transport.mkdir_local_failed", path=str(target.parent), detail=_oserr(e))
        try:
            if not self._swap(src, target):
                self._in_place(src, target)
        except TransportError:
            raise
        except OSError as e:
            raise TransportError("err.transport.write_failed", path=path, detail=_oserr(e))

    # -- escritura --
    def _swap(self, src: Path, target: Path) -> bool:
        """Carpeta nueva junto a la de saves + rename. False si no es posible sin tocar nada (se usa _in_place)."""
        new = _tmp_name(target, "new")
        try:
            new.mkdir()
        except OSError:
            return False  # el directorio padre no admite escritura
        old = None
        try:
            _copy_tree(src, new)
            if target.exists():
                try:
                    shutil.copystat(target, new)
                except OSError:
                    pass
                self._keep_links(target, new)
                old = _tmp_name(target, "old")
                try:
                    os.rename(target, old)
                except OSError:
                    old = None
                    shutil.rmtree(new, ignore_errors=True)
                    return False  # p. ej. carpeta en uso (Windows): nada ha cambiado
            try:
                os.rename(new, target)
            except OSError as e:
                if old is not None:
                    os.rename(old, target)  # deshacer
                    old = None
                raise TransportError("err.transport.place_failed", detail=_oserr(e))
        except BaseException:
            shutil.rmtree(new, ignore_errors=True)
            raise
        if old is not None:
            shutil.rmtree(old, ignore_errors=True)
        return True

    @staticmethod
    def _keep_links(old: Path, new: Path):
        """Los symlinks de la carpeta de saves no se sincronizan, pero tampoco se pierden al reemplazarla."""
        _, _, links = _walk_files(old)
        for rel in links:
            dst = new / rel
            if os.path.lexists(dst):
                continue
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                os.symlink(os.readlink(old / rel), dst)
            except (OSError, NotImplementedError):
                pass

    def _in_place(self, src: Path, target: Path):
        """Reemplazo fichero a fichero (cada uno atómico con os.replace) cuando no se puede intercambiar la carpeta."""
        target.mkdir(exist_ok=True)
        s_files, s_dirs, _ = _walk_files(src)
        wanted = set(s_files)
        for rel in s_dirs:
            d = target / rel
            if os.path.islink(d) or (d.exists() and not d.is_dir()):
                d.unlink()
            d.mkdir(parents=True, exist_ok=True)
        for rel in s_files:
            dst = target / rel
            if dst.is_dir() and not dst.is_symlink():
                shutil.rmtree(dst)
            tmp = dst.with_name(f".{dst.name}.checkpoint-tmp-{uuid.uuid4().hex[:8]}")
            try:
                shutil.copy2(src / rel, tmp)
                os.replace(tmp, dst)
            except OSError as e:
                try:
                    tmp.unlink()
                except OSError:
                    pass
                raise TransportError("err.transport.write_file_failed", file=rel, detail=_oserr(e))
        t_files, t_dirs, _ = _walk_files(target)
        for rel in t_files:
            if rel not in wanted:
                try:
                    os.unlink(target / rel)
                except OSError as e:
                    raise TransportError("err.transport.delete_failed", file=rel, detail=_oserr(e))
        keep = {os.path.dirname(f) for f in wanted} | set(s_dirs)
        keep = {k for r in keep for k in _parents(r)}
        for rel in sorted(t_dirs, key=len, reverse=True):
            if rel not in keep:
                try:
                    os.rmdir(target / rel)
                except OSError:
                    pass  # no vacía (contiene symlinks propios): se deja

    # -- procesos --
    def process_running(self, name: str) -> bool:
        if not PROC_RE.match(name):
            raise TransportError("err.transport.process_invalid")
        if sys.platform.startswith("win"):
            p = self._exec(["tasklist", "/FI", f"IMAGENAME eq {name}", "/NH"])
            if p.returncode != 0:
                raise TransportError("err.transport.tasklist_failed", detail=_err(p))
            return name.lower() in p.stdout.decode("utf-8", "replace").lower()
        pat = "[" + re.escape(name[0]) + "]" + re.escape(name[1:])
        try:
            p = self._exec(["pgrep", "-f", "--", pat])
        except FileNotFoundError:
            return self._proc_scan(name)
        if p.returncode == 1:
            return False
        if p.returncode != 0:
            raise TransportError("err.transport.pgrep_failed", detail=_err(p))
        pids = {int(x) for x in p.stdout.decode().split() if x.isdigit()}
        return bool(pids - {os.getpid()})  # Checkpoint no cuenta como el juego abierto

    def _exec(self, args):
        try:
            return self._run(args, capture_output=True, timeout=15)
        except subprocess.TimeoutExpired:
            raise TransportError("err.transport.process_timeout")

    @staticmethod
    def _proc_scan(name: str) -> bool:
        """Sin pgrep: lee /proc (Linux). Si tampoco existe, error claro."""
        proc = Path("/proc")
        if not proc.is_dir():
            raise TransportError("err.transport.pgrep_missing")
        me = str(os.getpid())
        for d in proc.iterdir():
            if not d.name.isdigit() or d.name == me:
                continue
            try:
                cmd = (d / "cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "replace")
            except OSError:
                continue
            if name in cmd:
                return True
        return False


def _parents(rel: str):
    """'a/b/c' -> '', 'a', 'a/b', 'a/b/c' (como rutas del SO)."""
    out, cur = [""], ""
    for part in [p for p in rel.split(os.sep) if p]:
        cur = os.path.join(cur, part)
        out.append(cur)
    return out


def _status(ok: bool, code: str, **params) -> dict:
    """Resultado de una comprobación: `code`/`params` (la UI los traduce); `message` es solo respaldo técnico."""
    return {"ok": ok, "message": describe_code(code, params), "code": code, "params": params}


def local_folder_status(path) -> dict:
    """Comprobación de la carpeta de saves de «Este equipo» (botón «Comprobar carpeta»). Sin SSH."""
    if path in (None, ""):
        return _status(True, "err.transport.local_info")
    try:
        p = _resolve(local_path(path))
    except TransportError as e:
        return _status(False, e.code, **e.params)
    try:
        if p.exists():
            if not p.is_dir():
                return _status(False, "err.transport.not_a_folder_short")
            if not os.access(p, os.R_OK | os.X_OK):
                return _status(False, "err.transport.unreadable")
            if not _can_write(p):
                return _status(False, "err.transport.not_writable")
            return _status(True, "err.transport.folder_ok")
        anc = p
        while not anc.exists() and anc != anc.parent:
            anc = anc.parent
        if not anc.is_dir():
            return _status(False, "err.transport.cannot_create_not_folder", path=str(anc))
        if not _can_write(anc):
            return _status(False, "err.transport.cannot_create_no_permission", path=str(anc))
        return _status(True, "err.transport.folder_will_be_created")
    except OSError as e:
        return _status(False, "err.transport.check_failed", detail=_oserr(e))


def _can_write(d: Path) -> bool:
    """Escribe y borra un fichero temporal: más fiable que os.access (solo lectura, ACLs, Windows)."""
    try:
        fd, name = tempfile.mkstemp(prefix=".checkpoint-test-", dir=d)
    except OSError:
        return False
    os.close(fd)
    try:
        os.unlink(name)
    except OSError:
        pass
    return True
