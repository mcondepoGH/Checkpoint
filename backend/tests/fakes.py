"""Dobles de prueba."""
import shutil
from pathlib import Path

from app.transport import Transport, TransportError


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
