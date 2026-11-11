"""Transporte SSH + rsync hacia dispositivos POSIX."""

import re
import shlex

from ...core import settings
from ...config.models import PROC_RE, Device
from . import base
from .base import Transport, TransportError, _ensure_host_key, _fail, _ssh_base, log


class PosixTransport(Transport):
    def __init__(self, dev: Device):
        self.dev = dev

    def _ssh(self, remote_cmd: str, timeout=60):
        log.debug("ssh %s:%s ejecuta %r", self.dev.host, self.dev.port, remote_cmd)
        return base._run(_ssh_base(self.dev) + [remote_cmd], timeout=timeout)

    def check(self):
        self.first_use = _ensure_host_key(self.dev)
        p = self._ssh("true", timeout=settings.SSH_TIMEOUT + 10)
        if p.returncode != 0:
            raise _fail("err.transport.ssh_failed", p, self.dev)

    def exists(self, path):
        p = self._ssh(f"test -d {shlex.quote(path)}")
        if p.returncode == 0:
            return True
        if p.returncode == 1:
            return False
        raise _fail("err.transport.ssh_failed", p, self.dev)

    def _rsh(self) -> str:
        return " ".join(shlex.quote(a) for a in _ssh_base(self.dev)[:-1])

    def pull(self, path, dest):
        dest.mkdir(parents=True, exist_ok=True)
        p = base._run(
            ["rsync", "-a", "--delete", "-s", "-e", self._rsh(), f"{self.dev.user}@{self.dev.host}:{path}/", f"{dest}/"]
        )
        if p.returncode != 0:
            raise _fail("err.transport.rsync_pull_failed", p, self.dev)

    def push(self, src, path, extras=()):
        p = self._ssh(f"mkdir -p {shlex.quote(path)}")
        if p.returncode != 0:
            raise _fail("err.transport.mkdir_failed", p, self.dev)
        # --delay-updates/--delete-delay: los ficheros se colocan al final de la transferencia (casi atómico).
        p = base._run(
            [
                "rsync",
                "-a",
                "--delete-delay",
                "--delay-updates",
                "-s",
                "-e",
                self._rsh(),
                f"{src}/",
                f"{self.dev.user}@{self.dev.host}:{path}/",
            ]
        )
        if p.returncode != 0:
            raise _fail("err.transport.rsync_push_failed", p, self.dev)

    def process_running(self, name):
        if not PROC_RE.match(name):
            raise TransportError("err.transport.process_invalid")
        # [x]yz evita que pgrep -f coincida con su propia línea de comandos.
        pat = "[" + re.escape(name[0]) + "]" + re.escape(name[1:])
        p = self._ssh(f"pgrep -f -- {shlex.quote(pat)}")
        if p.returncode == 0:
            return True
        if p.returncode == 1:
            return False
        raise _fail("err.transport.pgrep_failed", p, self.dev)
