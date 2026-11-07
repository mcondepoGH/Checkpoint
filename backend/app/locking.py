"""Lock por juego portable: no bloqueante, se libera al cerrar o si el proceso muere.

- POSIX: fcntl.flock (igual que siempre).
- Windows: msvcrt.locking sobre 1 byte.
- Sin ninguno de los dos: fichero `<lock>.excl` creado con O_EXCL que contiene el PID; un PID muerto
  (solo comprobable en POSIX) se considera lock huérfano.
"""
import os
import sys
import uuid
from contextlib import contextmanager
from pathlib import Path

try:  # POSIX
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None
try:  # Windows
    import msvcrt
except ImportError:
    msvcrt = None


class LockBusy(Exception):
    """El lock lo tiene otro."""


def _pid_alive(pid: int) -> bool:
    if sys.platform.startswith("win"):
        return True  # no se puede comprobar sin riesgo (os.kill termina procesos en Windows)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


class _Handle:
    def __init__(self, release):
        self.release = release


def acquire(path: Path, backend: str = None) -> _Handle:
    """Toma el lock en `path` o lanza LockBusy. `backend`: 'flock' | 'msvcrt' | 'excl' (tests)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    backend = backend or ("flock" if fcntl else "msvcrt" if msvcrt else "excl")
    if backend == "excl":
        return _acquire_excl(path)
    f = open(path, "a+b")
    try:
        if backend == "flock":
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except (BlockingIOError, PermissionError):
                raise LockBusy()

            def release():
                try:
                    fcntl.flock(f, fcntl.LOCK_UN)
                finally:
                    f.close()
        else:
            try:
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                raise LockBusy()

            def release():
                try:
                    f.seek(0)
                    msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
                finally:
                    f.close()
    except BaseException:
        f.close()
        raise
    return _Handle(release)


def _acquire_excl(path: Path) -> _Handle:
    lock = path.with_name(path.name + ".excl")
    for _ in range(2):
        # El PID se escribe en un temporal y se publica con os.link (atómico, falla si ya existe): nadie
        # puede ver nunca un fichero de lock a medias.
        tmp = lock.with_name(f"{lock.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")
        tmp.write_text(str(os.getpid()))
        try:
            os.link(tmp, lock)
        except FileExistsError:
            try:
                pid = int(lock.read_text().strip() or 0)
            except (OSError, ValueError):
                pid = 0
            tmp.unlink(missing_ok=True)
            if pid and _pid_alive(pid):
                raise LockBusy()
            try:  # huérfano (proceso muerto o fichero ilegible): se retira y se reintenta una vez
                lock.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                raise LockBusy()
            continue
        except OSError:  # el sistema de ficheros no admite enlaces duros: creación exclusiva directa
            tmp.unlink(missing_ok=True)
            try:
                fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
            except OSError:
                raise LockBusy()
            with os.fdopen(fd, "w") as f:
                f.write(str(os.getpid()))
        else:
            tmp.unlink(missing_ok=True)

        def release():
            try:
                lock.unlink()
            except FileNotFoundError:
                pass
        return _Handle(release)
    raise LockBusy()


@contextmanager
def locked(path: Path, backend: str = None):
    h = acquire(path, backend)
    try:
        yield
    finally:
        h.release()
