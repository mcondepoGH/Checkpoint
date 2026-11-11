"""Historial del cierre automático, extremo a extremo (HTTP real + vigilante real) con reloj y esperas del vigilante
simulados: `sleep` solo avanza un reloj falso, así que los umbrales (2 min sin ver el proceso, 10 s de asentamiento)
se cumplen al instante y no dependen del tiempo real. Las esperas de los tests son sondeos acotados de una condición."""
import asyncio
import threading

import pytest
import yaml

from app.users import history
from app import locking
from app.core import settings
from test_hook_close import cl, hist, hopen, mk, wait_for, watches  # noqa: F401 (fixtures)
from test_hook_opened import PW

SENSITIVE = "token=SECRETO-12345 /home/usuario/privado"


class Sim:
    """Reloj falso del vigilante: `sleep(s)` suma `s` al reloj y cede el control un instante."""

    def __init__(self):
        self.t = 0.0

    def clock(self):
        return self.t

    async def sleep(self, s):
        self.t += s
        await asyncio.sleep(0.002)


@pytest.fixture
def sim(cl, monkeypatch):
    monkeypatch.setattr(settings, "HOOK_POLL", 15.0)
    monkeypatch.setattr(settings, "HOOK_SETTLE", 10.0)
    monkeypatch.setattr(settings, "HOOK_FIRST_SEEN", 120.0)
    s = Sim()
    w = cl.app.state.watcher
    w.clock, w.sleep = s.clock, s.sleep
    cl.sim = s
    return s


def session(c):
    assert c.post("/api/login", json={"user": "admin", "password": PW}).status_code == 200


def last(c, game="g1"):
    return c.get(f"/api/games/{game}/hook-status").json()["devices"][0]["last"]


def seen_running(c):
    hopen(c)
    c.proc.running = True
    assert wait_for(lambda: watches(c).json() and watches(c).json()[0]["state"] == "running")


def only_closed():
    """Una sola entrada `hook_closed`, esperada tras el cierre, y nada más (sin reintentos)."""
    assert wait_for(lambda: hist("hook_closed"))
    h = hist("hook_closed")
    assert len(h) == 1, h
    return h[0]


# ---- a. nunca visto ----
def test_never_seen_one_entry_and_hook_status_last(cl, sim):
    hopen(cl)
    assert wait_for(lambda: watches(cl).json() == [])
    e = only_closed()
    assert sim.t == 120.0  # 8 sondeos de 15 s simulados, ni uno más
    assert e["trigger"] == "hook_closed" and e["result"] == "skipped" and e["device"] == "dev-1"
    assert e["code"] == "err.hook.never_seen" and e["params"] == {"seconds": 120.0}
    g = e["games"]["g1"]
    assert g["result"] == "skipped" and g["code"] == "err.hook.never_seen" and g["name"] == "Mi Juego"
    assert g["params"] == {"seconds": 120.0}
    assert [x["trigger"] for x in history.read()] == ["hook_closed", "hook"]  # más reciente primero: el descarte y el `opened`
    session(cl)
    assert last(cl) == {"trigger": "hook_closed", "at": e["started"], "outcome": "skipped",
                        "code": "err.hook.never_seen", "params": {"seconds": 120.0}}
    assert cl.app.state.watcher.tasks == {}  # sin reintento: la tarea terminó


# ---- b. ocupado ----
def test_closed_while_run_in_progress_is_skipped_busy_and_run_untouched(cl, sim, monkeypatch):
    import app.main as m
    seen_running(cl)  # `opened` con 409 si ya hay un run: primero se arma la vigilancia y luego arranca el run manual
    session(cl)
    gate, entered, calls = threading.Event(), threading.Event(), []
    real = m.run_sync

    def blocked(*a, **k):
        calls.append(1)
        entered.set()
        gate.wait(10)
        return real(*a, **k)

    monkeypatch.setattr(m, "run_sync", blocked)
    run_id = cl.post("/api/sync/g1", json={}).json()["run_id"]  # ejecución en curso del mismo juego
    assert entered.wait(5)
    cl.proc.running = False
    try:
        e = only_closed()
        assert e["result"] == "skipped" and e["code"] == "err.hook.busy" and e["device"] == "dev-1"
        assert e["games"]["g1"]["code"] == "err.hook.busy" and e["games"]["g1"]["name"] == "Mi Juego"
        assert wait_for(lambda: watches(cl).json() == [])
        assert calls == [1]  # el cierre no lanzó otro run ni tocó el que estaba en curso
        assert cl.app.state.watcher.tasks == {}
    finally:
        gate.set()
    session(cl)
    cl.get(f"/api/runs/{run_id}/stream")  # espera a que termine el run original
    assert calls == [1] and len(hist("hook_closed")) == 1  # sigue sin reintento tras acabar el run
    assert last(cl)["code"] == "err.hook.busy" and last(cl)["outcome"] == "skipped"


def test_closed_with_lock_taken_is_skipped_busy_without_retry(cl, sim):
    seen_running(cl)
    h = locking.acquire(settings.DATA_DIR / "locks" / "g1.lock")  # lock de otro proceso
    try:
        cl.proc.running = False
        e = only_closed()
        assert wait_for(lambda: watches(cl).json() == [])
    finally:
        h.release()
    assert e["result"] == "skipped" and e["code"] == "err.hook.busy" and e["device"] == "dev-1"
    t = sim.t
    cl.proc.running = True  # aunque el juego «vuelva», no hay vigilancia ni reintento
    assert cl.app.state.watcher.tasks == {} and sim.t == t and len(hist("hook_closed")) == 1


# ---- c. juego borrado ----
def test_game_removed_from_config_logs_game_removed(cl, sim):
    seen_running(cl)
    cfg = yaml.safe_load(settings.CONFIG_PATH.read_text())
    del cfg["games"]["g1"]
    settings.CONFIG_PATH.write_text(yaml.safe_dump(cfg, allow_unicode=True))
    cl.proc.running = False
    e = only_closed()
    assert e["result"] == "skipped" and e["code"] == "err.hook.game_removed" and e["device"] == "dev-1"
    assert list(e["games"]) == ["g1"] and e["games"]["g1"]["code"] == "err.hook.game_removed"


# ---- d. fallo del checkpoint ----
def test_checkpoint_exception_logs_only_the_type_never_the_message(cl, sim, monkeypatch, caplog):
    import app.main as m
    seen_running(cl)

    def boom(*a, **k):
        raise RuntimeError(SENSITIVE)

    monkeypatch.setattr(m, "Run", boom)  # lanza al preparar el checkpoint de cierre
    cl.proc.running = False
    e = only_closed()
    assert e["result"] == "error" and e["code"] == "err.hook.checkpoint_failed" and e["device"] == "dev-1"
    assert e["params"] == {"error": "RuntimeError"} and e["games"]["g1"]["params"] == {"error": "RuntimeError"}
    for frag in ("SECRETO", "12345", "usuario", "privado", SENSITIVE):
        assert frag not in str(history.read()), frag
    session(cl)
    st = last(cl)
    assert st["outcome"] == "error" and st["code"] == "err.hook.checkpoint_failed" and st["params"] == {"error": "RuntimeError"}
    assert "SECRETO" not in str(st)
    assert cl.app.state.watcher.tasks == {}  # no se reintenta


# ---- e. caso normal (regresión) ----
def test_normal_open_seen_and_closed_makes_one_ok_checkpoint_and_no_skip_entries(cl, sim):
    e = cl.env
    seen_running(cl)
    e.write(e.d1, "jugado", 3000)
    cl.proc.running = False
    c = only_closed()
    assert c["result"] == "ok" and c["device"] == "dev-1" and not c.get("code", "").startswith("err.hook.")
    assert wait_for(lambda: watches(cl).json() == [])
    assert [x["trigger"] for x in history.read()].count("hook_closed") == 1
    for x in history.read():
        assert x["result"] != "skipped" and not str(x.get("code") or "").startswith("err.hook.")
        assert not any(str(g.get("code") or "").startswith("err.hook.") for g in x["games"].values())
    assert (e.read(e.hub), e.read(e.d2)) == ("jugado", "jugado")
    session(cl)
    st = last(cl)
    assert st["trigger"] == "hook_closed" and st["outcome"] == "ok" and not str(st.get("code") or "").startswith("err.hook.")


# ---- f. fallo del historial ----
def test_history_write_failure_never_breaks_watcher_nor_leaks(cl, sim, monkeypatch, caplog):
    import logging
    caplog.set_level(logging.WARNING)

    def boom(*a, **k):
        raise OSError(SENSITIVE)

    real = history.append
    monkeypatch.setattr(history, "append", boom)
    hopen(cl)
    assert wait_for(lambda: watches(cl).json() == [])  # el descarte ocurre aunque el historial falle
    assert cl.app.state.watcher.tasks == {}
    assert wait_for(lambda: any("no se pudo guardar en el historial" in r.getMessage() for r in caplog.records))
    assert all("SECRETO" not in r.getMessage() for r in caplog.records)  # solo el tipo de excepción
    monkeypatch.setattr(history, "append", real)
    hopen(cl)  # el vigilante sigue vivo: una nueva apertura se arma y se descarta de nuevo
    assert wait_for(lambda: hist("hook_closed"))
