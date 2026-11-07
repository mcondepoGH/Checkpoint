"""Acceso a dispositivos por SSH. Siempre listas de argumentos (sin shell local).

En el extremo remoto, ssh entrega una cadena al shell del servidor: las rutas
ya vienen validadas por config.normalize_path (lista blanca) y además se
entrecomillan (shlex.quote en POSIX, comillas dobles en cmd.exe).
"""
import re
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Iterable, List

from . import bootstrap, settings
from .config import PATH_CHARS_RE, PROC_RE, Device


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
        p = _run(["rsync", "-a", "--delete", "-s", "-e", self._rsh(),
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
    return WindowsTransport(dev) if dev.os == "windows" else PosixTransport(dev)


class LocalTransport(Transport):
    """Simula un dispositivo con un directorio local (tests)."""

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
