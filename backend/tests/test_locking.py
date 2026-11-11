"""Lock por juego portable: flock (POSIX), msvcrt (simulado) y fallback O_EXCL + PID."""

import os
import subprocess
import sys
import threading

import pytest

from app.sync import locking
from app.sync.locking import LockBusy, acquire, locked


@pytest.mark.parametrize("backend", [None, "flock", "excl"])
def test_exclusion_y_liberacion(tmp_path, backend):
    p = tmp_path / "locks" / "g.lock"
    h = acquire(p, backend)
    with pytest.raises(LockBusy):
        acquire(p, backend)
    h.release()
    h2 = acquire(p, backend)  # se puede volver a tomar
    h2.release()


@pytest.mark.parametrize("backend", ["flock", "excl"])
def test_context_manager_libera_con_excepcion(tmp_path, backend):
    p = tmp_path / "g.lock"
    with pytest.raises(RuntimeError):
        with locked(p, backend):
            raise RuntimeError("x")
    acquire(p, backend).release()


def test_flock_compatible_con_fcntl_directo(tmp_path):
    """Los tests históricos y otros procesos toman el mismo fichero con fcntl.flock."""
    import fcntl

    p = tmp_path / "g.lock"
    f = open(p, "w")
    fcntl.flock(f, fcntl.LOCK_EX)
    with pytest.raises(LockBusy):
        acquire(p, "flock")
    fcntl.flock(f, fcntl.LOCK_UN)
    f.close()
    acquire(p, "flock").release()


def test_flock_entre_procesos(tmp_path):
    p = tmp_path / "g.lock"
    code = (
        "import sys,time;sys.path.insert(0,%r);from app.sync.locking import acquire;"
        "h=acquire(%r,'flock');print('ok',flush=True);time.sleep(30)"
        % (os.path.dirname(os.path.dirname(os.path.dirname(locking.__file__))), str(p))
    )
    c = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE)
    try:
        assert c.stdout.readline().strip() == b"ok"
        with pytest.raises(LockBusy):
            acquire(p, "flock")
        c.kill()
        c.wait()  # al morir el proceso, el SO libera el lock
        acquire(p, "flock").release()
    finally:
        if c.poll() is None:
            c.kill()
            c.wait()


def test_excl_pid_muerto_es_huerfano(tmp_path):
    p = tmp_path / "g.lock"
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    (tmp_path / "g.lock.excl").write_text(str(dead.pid))
    acquire(p, "excl").release()


def test_excl_pid_vivo_bloquea(tmp_path):
    p = tmp_path / "g.lock"
    live = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(30)"])
    try:
        (tmp_path / "g.lock.excl").write_text(str(live.pid))
        with pytest.raises(LockBusy):
            acquire(p, "excl")
    finally:
        live.kill()
        live.wait()


def test_excl_fichero_basura_se_retira(tmp_path):
    (tmp_path / "g.lock.excl").write_text("no-es-un-pid")
    acquire(tmp_path / "g.lock", "excl").release()


def test_excl_release_idempotente(tmp_path):
    h = acquire(tmp_path / "g.lock", "excl")
    h.release()
    h.release()  # no falla aunque ya no exista


def test_excl_concurrencia_solo_uno_gana(tmp_path):
    p = tmp_path / "g.lock"
    winners, barrier = [], threading.Barrier(8)

    def w():
        barrier.wait()
        try:
            h = acquire(p, "excl")
            winners.append(h)
        except LockBusy:
            pass

    ts = [threading.Thread(target=w) for _ in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    # mismo PID: el fallback trata el lock propio como ocupado, así que exactamente uno lo toma
    assert len(winners) == 1
    winners[0].release()


def test_sin_fcntl_ni_msvcrt_elige_excl(monkeypatch, tmp_path):
    monkeypatch.setattr(locking, "fcntl", None)
    monkeypatch.setattr(locking, "msvcrt", None)
    h = acquire(tmp_path / "g.lock")
    assert (tmp_path / "g.lock.excl").exists()
    h.release()


def test_pid_alive_windows_no_mata(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    called = []
    monkeypatch.setattr(os, "kill", lambda *a: called.append(a))
    assert locking._pid_alive(12345) is True and not called


class FakeMsvcrt:
    LK_NBLCK, LK_UNLCK = 2, 0
    held = set()

    @classmethod
    def locking(cls, fd, mode, n):
        key = os.fstat(fd).st_ino
        if mode == cls.LK_NBLCK:
            if key in cls.held:
                raise OSError(13, "Permission denied")
            cls.held.add(key)
        else:
            cls.held.discard(key)


def test_backend_msvcrt_simulado(monkeypatch, tmp_path):
    FakeMsvcrt.held = set()
    monkeypatch.setattr(locking, "msvcrt", FakeMsvcrt)
    p = tmp_path / "g.lock"
    h = acquire(p, "msvcrt")
    with pytest.raises(LockBusy):
        acquire(p, "msvcrt")
    h.release()
    acquire(p, "msvcrt").release()


def test_sync_usa_el_lock_portable_y_aborta_si_ocupado(tmp_path):
    from app.sync.engine import SyncAbort, _game_lock

    with _game_lock(tmp_path, "g"):
        with pytest.raises(SyncAbort, match="in_progress"):
            with _game_lock(tmp_path, "g"):
                pass
    with _game_lock(tmp_path, "g"):
        pass


def test_excl_sin_enlaces_duros_usa_creacion_exclusiva(monkeypatch, tmp_path):
    def nolink(a, b):
        raise OSError(1, "Operation not permitted")

    monkeypatch.setattr(os, "link", nolink)
    p = tmp_path / "g.lock"
    h = acquire(p, "excl")
    with pytest.raises(LockBusy):
        acquire(p, "excl")
    h.release()
    acquire(p, "excl").release()
    assert [x.name for x in tmp_path.iterdir()] == []


def test_excl_no_deja_temporales(tmp_path):
    h = acquire(tmp_path / "g.lock", "excl")
    with pytest.raises(LockBusy):
        acquire(tmp_path / "g.lock", "excl")
    assert [x.name for x in tmp_path.iterdir()] == ["g.lock.excl"]
    h.release()
