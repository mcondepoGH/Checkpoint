"""Transporte SSH + tar hacia Windows (OpenSSH Server, cmd.exe)."""

import subprocess

from ...core import settings
from ...config.models import PROC_RE, Device
from . import base
from .base import Transport, TransportError, _ensure_host_key, _fail, _safe_rel, _ssh_base, log


class WindowsTransport(Transport):
    """OpenSSH Server de Windows con shell por defecto cmd.exe y tar.exe (Win10+)."""

    def __init__(self, dev: Device):
        self.dev = dev

    def _ssh(self, remote_cmd: str, timeout=60):
        log.debug("ssh %s:%s ejecuta %r", self.dev.host, self.dev.port, remote_cmd)
        return base._run(_ssh_base(self.dev) + [remote_cmd], timeout=timeout)

    @staticmethod
    def _win(path: str) -> str:
        return path.replace("/", "\\")

    def check(self):
        self.first_use = _ensure_host_key(self.dev)
        p = self._ssh("echo ok", timeout=settings.SSH_TIMEOUT + 10)
        if p.returncode != 0 or b"ok" not in p.stdout:
            raise _fail("err.transport.ssh_failed", p, self.dev)

    def exists(self, path):
        p = self._ssh(f'if exist "{self._win(path)}\\" (exit 0) else (exit 1)')
        if p.returncode == 0:
            return True
        if p.returncode == 1:
            return False
        raise _fail("err.transport.ssh_failed", p, self.dev)

    def pull(self, path, dest):
        dest.mkdir(parents=True, exist_ok=True)
        a = subprocess.Popen(
            _ssh_base(self.dev) + [f'tar -cf - -C "{path}" .'], stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        b = subprocess.Popen(
            ["tar", "-xf", "-", "-C", str(dest)], stdin=a.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        a.stdout.close()
        try:
            _, berr = b.communicate(timeout=1800)
            _, aerr = a.communicate(timeout=60)
        except subprocess.TimeoutExpired:
            a.kill()
            b.kill()
            raise TransportError("err.transport.timeout")
        if a.returncode != 0 or b.returncode != 0:
            raise TransportError(
                "err.transport.tar_pull_failed", detail=(aerr or berr).decode("utf-8", "replace")[-300:]
            )

    def push(self, src, path, extras=()):
        # Limitación: tar extrae sobre la carpeta en uso (no hay equivalente sencillo a rsync --delay-updates),
        # así que un corte a mitad deja el destino a medias. Es seguro: el baseline no se actualiza, el
        # destino aparece como "cambiado" y la siguiente sync lo trata como conflicto en vez de pisarlo a ciegas.
        p = self._ssh(f'if not exist "{self._win(path)}\\" mkdir "{self._win(path)}"')
        if p.returncode != 0:
            raise _fail("err.transport.mkdir_failed", p, self.dev)
        for rel in extras:
            if not _safe_rel(rel):
                continue
            self._ssh(f'del /f /q "{self._win(path + "/" + rel)}"')
        a = subprocess.Popen(
            ["tar", "--format=pax", "-cf", "-", "-C", str(src), "."], stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        b = subprocess.Popen(
            _ssh_base(self.dev) + [f'tar -xf - -C "{path}"'],
            stdin=a.stdout,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        a.stdout.close()
        try:
            _, berr = b.communicate(timeout=1800)
            _, aerr = a.communicate(timeout=60)
        except subprocess.TimeoutExpired:
            a.kill()
            b.kill()
            raise TransportError("err.transport.timeout")
        if a.returncode != 0 or b.returncode != 0:
            raise TransportError(
                "err.transport.tar_push_failed", detail=(berr or aerr).decode("utf-8", "replace")[-300:]
            )

    def process_running(self, name):
        if not PROC_RE.match(name):
            raise TransportError("err.transport.process_invalid")
        p = self._ssh(f'tasklist /FI "IMAGENAME eq {name}" /NH')
        if p.returncode != 0:
            raise _fail("err.transport.tasklist_failed", p, self.dev)
        return name.lower() in p.stdout.decode("utf-8", "replace").lower()
