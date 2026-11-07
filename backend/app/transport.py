"""Acceso a dispositivos por SSH. Siempre listas de argumentos (sin shell local).

En el extremo remoto, ssh entrega una cadena al shell del servidor: las rutas
ya vienen validadas por config.normalize_path (lista blanca) y además se
entrecomillan (shlex.quote en POSIX, comillas dobles en cmd.exe).
"""
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Iterable, List

from . import bootstrap, settings
from .config import LOCAL_DOCKER_MSG, PATH_CHARS_RE, PROC_RE, Device
from .runtime import running_in_docker


class TransportError(RuntimeError):
    pass


class Transport:
    """Interfaz. Rutas ya normalizadas."""

    def check(self) -> None: ...
    def exists(self, path: str) -> bool: ...
    def pull(self, path: str, dest: Path) -> None: ...
    def push(self, src: Path, path: str, extras: Iterable[str] = ()) -> None: ...
    def process_running(self, name: str) -> bool: ...


def _ssh_base(dev: Device) -> List[str]:
    return [
        "ssh", "-p", str(dev.port), "-i", settings.SSH_KEY,
        "-o", "BatchMode=yes",
        "-o", "IdentitiesOnly=yes",
        "-o", "StrictHostKeyChecking=yes",
        "-o", f"UserKnownHostsFile={settings.KNOWN_HOSTS}",
        "-o", f"ConnectTimeout={settings.SSH_TIMEOUT}",
        "-o", "ServerAliveInterval=15",
        f"{dev.user}@{dev.host}",
    ]


def _run(args: List[str], timeout=600, stdin=None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(args, capture_output=True, timeout=timeout, stdin=stdin)
    except subprocess.TimeoutExpired:
        raise TransportError("tiempo agotado")
    except FileNotFoundError as e:
        raise TransportError(f"falta binario: {e.filename}")


def _err(p: subprocess.CompletedProcess, dev: Device = None) -> str:
    txt = (p.stderr or b"").decode("utf-8", "replace").strip()[-300:]
    return bootstrap.explain_ssh_error(txt, dev.host, dev.port) if dev else txt


def _ensure_host_key(dev: Device) -> bool:
    """TOFU antes de conectar; el fallo se reporta como TransportError. True si guardó una huella nueva."""
    try:
        return bootstrap.ensure_host_key(dev.host, dev.port)
    except bootstrap.BootstrapError as e:
        raise TransportError(str(e))


def _safe_rel(rel: str) -> bool:
    return bool(PATH_CHARS_RE.match(rel)) and ".." not in rel.split("/") and not rel.startswith("/")


class PosixTransport(Transport):
    def __init__(self, dev: Device):
        self.dev = dev

    def _ssh(self, remote_cmd: str, timeout=60):
        return _run(_ssh_base(self.dev) + [remote_cmd], timeout=timeout)

    def check(self):
        self.first_use = _ensure_host_key(self.dev)
        p = self._ssh("true", timeout=settings.SSH_TIMEOUT + 10)
        if p.returncode != 0:
            raise TransportError(f"SSH falló: {_err(p, self.dev)}")

    def exists(self, path):
        p = self._ssh(f"test -d {shlex.quote(path)}")
        if p.returncode == 0:
            return True
        if p.returncode == 1:
            return False
        raise TransportError(f"SSH falló: {_err(p, self.dev)}")

    def _rsh(self) -> str:
        return " ".join(shlex.quote(a) for a in _ssh_base(self.dev)[:-1])

    def pull(self, path, dest):
        dest.mkdir(parents=True, exist_ok=True)
        p = _run(["rsync", "-a", "--delete", "-s", "-e", self._rsh(),
                  f"{self.dev.user}@{self.dev.host}:{path}/", f"{dest}/"])
        if p.returncode != 0:
            raise TransportError(f"rsync pull falló: {_err(p, self.dev)}")

    def push(self, src, path, extras=()):
        p = self._ssh(f"mkdir -p {shlex.quote(path)}")
        if p.returncode != 0:
            raise TransportError(f"mkdir remoto falló: {_err(p, self.dev)}")
        # --delay-updates/--delete-delay: los ficheros se colocan al final de la transferencia (casi atómico).
        p = _run(["rsync", "-a", "--delete-delay", "--delay-updates", "-s", "-e", self._rsh(),
                  f"{src}/", f"{self.dev.user}@{self.dev.host}:{path}/"])
        if p.returncode != 0:
            raise TransportError(f"rsync push falló: {_err(p, self.dev)}")

    def process_running(self, name):
        if not PROC_RE.match(name):
            raise TransportError("nombre de proceso inválido")
        # [x]yz evita que pgrep -f coincida con su propia línea de comandos.
        pat = "[" + re.escape(name[0]) + "]" + re.escape(name[1:])
        p = self._ssh(f"pgrep -f -- {shlex.quote(pat)}")
        if p.returncode == 0:
            return True
        if p.returncode == 1:
            return False
        raise TransportError(f"pgrep falló: {_err(p, self.dev)}")


class WindowsTransport(Transport):
    """OpenSSH Server de Windows con shell por defecto cmd.exe y tar.exe (Win10+)."""

    def __init__(self, dev: Device):
        self.dev = dev

    def _ssh(self, remote_cmd: str, timeout=60):
        return _run(_ssh_base(self.dev) + [remote_cmd], timeout=timeout)

    @staticmethod
    def _win(path: str) -> str:
        return path.replace("/", "\\")

    def check(self):
        self.first_use = _ensure_host_key(self.dev)
        p = self._ssh("echo ok", timeout=settings.SSH_TIMEOUT + 10)
        if p.returncode != 0 or b"ok" not in p.stdout:
            raise TransportError(f"SSH falló: {_err(p, self.dev)}")

    def exists(self, path):
        p = self._ssh(f'if exist "{self._win(path)}\\" (exit 0) else (exit 1)')
        if p.returncode == 0:
            return True
        if p.returncode == 1:
            return False
        raise TransportError(f"SSH falló: {_err(p, self.dev)}")

    def pull(self, path, dest):
        dest.mkdir(parents=True, exist_ok=True)
        a = subprocess.Popen(_ssh_base(self.dev) + [f'tar -cf - -C "{path}" .'],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        b = subprocess.Popen(["tar", "-xf", "-", "-C", str(dest)], stdin=a.stdout,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        a.stdout.close()
        try:
            _, berr = b.communicate(timeout=1800)
            _, aerr = a.communicate(timeout=60)
        except subprocess.TimeoutExpired:
            a.kill(); b.kill()
            raise TransportError("tiempo agotado")
        if a.returncode != 0 or b.returncode != 0:
            raise TransportError(f"tar pull falló: {(aerr or berr).decode('utf-8','replace')[-300:]}")

    def push(self, src, path, extras=()):
        # Limitación: tar extrae sobre la carpeta en uso (no hay equivalente sencillo a rsync --delay-updates),
        # así que un corte a mitad deja el destino a medias. Es seguro: el baseline no se actualiza, el
        # destino aparece como "cambiado" y la siguiente sync lo trata como conflicto en vez de pisarlo a ciegas.
        p = self._ssh(f'if not exist "{self._win(path)}\\" mkdir "{self._win(path)}"')
        if p.returncode != 0:
            raise TransportError(f"mkdir remoto falló: {_err(p, self.dev)}")
        for rel in extras:
            if not _safe_rel(rel):
                continue
            self._ssh(f'del /f /q "{self._win(path + "/" + rel)}"')
        a = subprocess.Popen(["tar", "--format=pax", "-cf", "-", "-C", str(src), "."],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        b = subprocess.Popen(_ssh_base(self.dev) + [f'tar -xf - -C "{path}"'], stdin=a.stdout,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        a.stdout.close()
        try:
            _, berr = b.communicate(timeout=1800)
            _, aerr = a.communicate(timeout=60)
        except subprocess.TimeoutExpired:
            a.kill(); b.kill()
            raise TransportError("tiempo agotado")
        if a.returncode != 0 or b.returncode != 0:
            raise TransportError(f"tar push falló: {(berr or aerr).decode('utf-8','replace')[-300:]}")

    def process_running(self, name):
        if not PROC_RE.match(name):
            raise TransportError("nombre de proceso inválido")
        p = self._ssh(f'tasklist /FI "IMAGENAME eq {name}" /NH')
        if p.returncode != 0:
            raise TransportError(f"tasklist falló: {_err(p, self.dev)}")
        return name.lower() in p.stdout.decode("utf-8", "replace").lower()


def get_transport(dev: Device) -> Transport:
    if dev.local:
        if running_in_docker():
            raise TransportError(LOCAL_DOCKER_MSG)
        return LocalDeviceTransport(dev)
    return WindowsTransport(dev) if dev.os == "windows" else PosixTransport(dev)


class LocalTransport(Transport):
    """Simula un dispositivo remoto con un directorio local (solo tests; el dispositivo «Este equipo» real
    es LocalDeviceTransport)."""

    def __init__(self, root: Path, running: bool = False, down: bool = False):
        self.root, self.running, self.down = Path(root), running, down

    def _p(self, path):
        return self.root / path.lstrip("/")

    def check(self):
        if self.down:
            raise TransportError("dispositivo no responde")

    def exists(self, path):
        self.check()
        return self._p(path).is_dir()

    def pull(self, path, dest):
        self.check()
        shutil.copytree(self._p(path), dest, dirs_exist_ok=True)

    def push(self, src, path, extras=()):
        self.check()
        t = self._p(path)
        if t.exists():
            shutil.rmtree(t)
        shutil.copytree(src, t)

    def process_running(self, name):
        self.check()
        return self.running


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
        raise TransportError("ruta vacía")
    if "\x00" in path:
        raise TransportError("ruta inválida (carácter nulo)")
    if ".." in path.replace("\\", "/").split("/"):
        raise TransportError("'..' no permitido en rutas")
    if not os.path.isabs(path):
        raise TransportError(f"la ruta no es absoluta en este sistema: {path}")
    return Path(os.path.abspath(path))


def _resolve(p: Path) -> Path:
    """Ruta real (resuelve symlinks de la propia carpeta de saves, que es decisión del usuario)."""
    try:
        return Path(os.path.realpath(p))
    except (OSError, RuntimeError, ValueError) as e:
        raise TransportError(f"ruta no resoluble: {e}")


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
    raise TransportError(f"no se pudo leer {e.filename}: {_oserr(e)}")


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
            raise TransportError(f"no se pudo copiar {f}: {_oserr(e)}")


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
                raise TransportError(f"la ruta existe pero no es una carpeta: {path}")
            if not os.access(root, os.R_OK | os.X_OK):
                raise TransportError(f"sin permiso de lectura en {path}")
        except PermissionError as e:
            raise TransportError(f"sin permiso para acceder a {path}: {_oserr(e)}")
        except OSError as e:
            raise TransportError(f"no se pudo acceder a {path}: {_oserr(e)}")
        return True

    def pull(self, path: str, dest: Path) -> None:
        root = _resolve(local_path(path))
        if not root.is_dir():
            raise TransportError(f"la carpeta no existe: {path}")
        _copy_tree(root, Path(dest))

    def push(self, src: Path, path: str, extras: Iterable[str] = ()) -> None:
        src = Path(src)
        target = _resolve(local_path(path))
        if target.exists() and not target.is_dir():
            raise TransportError(f"la ruta existe pero no es una carpeta: {path}")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise TransportError(f"no se pudo crear {target.parent}: {_oserr(e)}")
        try:
            if not self._swap(src, target):
                self._in_place(src, target)
        except TransportError:
            raise
        except OSError as e:
            raise TransportError(f"no se pudo escribir en {path}: {_oserr(e)}")

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
                raise TransportError(f"no se pudo colocar la carpeta nueva: {_oserr(e)}")
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
                raise TransportError(f"no se pudo escribir {rel}: {_oserr(e)}")
        t_files, t_dirs, _ = _walk_files(target)
        for rel in t_files:
            if rel not in wanted:
                try:
                    os.unlink(target / rel)
                except OSError as e:
                    raise TransportError(f"no se pudo borrar {rel}: {_oserr(e)}")
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
            raise TransportError("nombre de proceso inválido")
        if sys.platform.startswith("win"):
            p = self._exec(["tasklist", "/FI", f"IMAGENAME eq {name}", "/NH"])
            if p.returncode != 0:
                raise TransportError("tasklist falló: " + _err(p))
            return name.lower() in p.stdout.decode("utf-8", "replace").lower()
        pat = "[" + re.escape(name[0]) + "]" + re.escape(name[1:])
        try:
            p = self._exec(["pgrep", "-f", "--", pat])
        except FileNotFoundError:
            return self._proc_scan(name)
        if p.returncode == 1:
            return False
        if p.returncode != 0:
            raise TransportError("pgrep falló: " + _err(p))
        pids = {int(x) for x in p.stdout.decode().split() if x.isdigit()}
        return bool(pids - {os.getpid()})  # Checkpoint no cuenta como el juego abierto

    def _exec(self, args):
        try:
            return self._run(args, capture_output=True, timeout=15)
        except subprocess.TimeoutExpired:
            raise TransportError("tiempo agotado comprobando procesos")

    @staticmethod
    def _proc_scan(name: str) -> bool:
        """Sin pgrep: lee /proc (Linux). Si tampoco existe, error claro."""
        proc = Path("/proc")
        if not proc.is_dir():
            raise TransportError("no se puede comprobar el proceso: falta pgrep")
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


def local_folder_status(path) -> dict:
    """Comprobación de la carpeta de saves de «Este equipo» (botón «Comprobar carpeta»). Sin SSH."""
    if path in (None, ""):
        return {"ok": True, "message": "Este equipo: acceso local directo, sin SSH. "
                                       "Indica la ruta de los saves en cada juego."}
    try:
        p = _resolve(local_path(path))
    except TransportError as e:
        return {"ok": False, "message": str(e)}
    try:
        if p.exists():
            if not p.is_dir():
                return {"ok": False, "message": "la ruta existe pero no es una carpeta"}
            if not os.access(p, os.R_OK | os.X_OK):
                return {"ok": False, "message": "la carpeta existe pero no se puede leer (sin permiso)"}
            if not _can_write(p):
                return {"ok": False, "message": "la carpeta se puede leer pero no escribir (sin permiso o solo lectura)"}
            return {"ok": True, "message": "carpeta OK: existe, es legible y escribible"}
        anc = p
        while not anc.exists() and anc != anc.parent:
            anc = anc.parent
        if not anc.is_dir():
            return {"ok": False, "message": f"no se puede crear la carpeta: {anc} no es una carpeta"}
        if not _can_write(anc):
            return {"ok": False, "message": f"la carpeta no existe y no se puede crear: sin permiso de escritura en {anc}"}
        return {"ok": True, "message": "la carpeta no existe todavía; se creará al sincronizar (se trata como vacía)"}
    except OSError as e:
        return {"ok": False, "message": f"no se pudo comprobar la carpeta: {_oserr(e)}"}


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
