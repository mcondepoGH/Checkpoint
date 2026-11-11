"""Cierre automático: `opened` arma el vigilante (proceso real del dispositivo vía transport falso) y el checkpoint
de cierre queda en el historial con trigger `hook_closed`. Servidor con lifespan (`with TestClient`), tiempos mínimos."""
import time

import pytest
import yaml
from fastapi.testclient import TestClient

from app import history, locking
from app.core import settings
from app.auth import Auth
from app.main import create_app
from test_hook_opened import Env, PW, code


class Proc:
    """Estado del «proceso del juego» y del dispositivo remoto, consultados por el transport falso."""
    running = False
    fail = False  # el sondeo del proceso lanza TransportError (SSH caído)
    down = False  # el dispositivo remoto no responde para la sync
    reopen = False  # tras la primera lectura «cerrado» (la del vigilante), el proceso vuelve a verse: la sync aborta
    reads = 0


@pytest.fixture
def mk(tmp_path, monkeypatch):
    import app.sync as sync
    from app.transport import TransportError
    from fakes import LocalTransport
    e = Env(tmp_path)
    cfg = yaml.safe_load((tmp_path / "config" / "config.yaml").read_text())
    cfg["games"]["g1"]["process"] = "game.exe"
    cfg["games"]["g2"] = {"name": "Sin Proceso", "devices": ["dev-1", "dev-2"],
                          "paths": {"dev-1": str(tmp_path / "p2"), "dev-2": "/home/u/g2"}}
    (tmp_path / "config" / "config.yaml").write_text(yaml.safe_dump(cfg, allow_unicode=True))
    p = Proc()

    class T(LocalTransport):
        def process_running(self, name):
            if p.fail:
                raise TransportError("down")
            if p.reopen and not p.running:
                p.reads += 1
                return p.reads > 1
            return p.running

    real = sync.get_transport

    def gt(dev):
        if not dev.local:
            return T(e.laptop, down=p.down)
        t = real(dev)  # «Este equipo» real sobre tmpdir; solo el sondeo del proceso es falso
        t.process_running = lambda name: T(e.laptop).process_running(name)
        return t

    monkeypatch.setattr(sync, "get_transport", gt)
    monkeypatch.setattr(settings, "CONFIG_PATH", tmp_path / "config" / "config.yaml")
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(settings, "STATIC_DIR", tmp_path / "static")
    monkeypatch.setattr(settings, "HOOK_POLL", 0.05)
    monkeypatch.setattr(settings, "HOOK_SETTLE", 0.1)
    monkeypatch.setattr(settings, "HOOK_FIRST_SEEN", 0.6)

    def make():
        c = TestClient(create_app(Auth("admin", PW, 1, rounds=4)))
        c.env, c.proc = e, p
        return c

    def login(c):
        assert c.post("/api/login", json={"user": "admin", "password": PW}).status_code == 200
        c.key = c.post("/api/profile/apikey").json()["key"]
        c.hdr = {"Authorization": f"Bearer {c.key}"}
        c.cookies.clear()  # sin cookie de sesión; el mismo cliente (`with`) mantiene un solo event loop para los vigilantes
        e.seed()

    make.login = login
    return make


@pytest.fixture
def cl(mk):
    with mk() as c:
        mk.login(c)
        yield c


def hopen(c, game="g1", device="dev-1"):
    return c.post(f"/api/hook/{game}/opened?device={device}", headers=c.hdr)


def watches(c):
    return c.get("/api/hook/watches", headers=c.hdr)


def wait_for(cond, secs=5):
    end = time.time() + secs
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def hist(trigger):
    return [x for x in history.read() if x["trigger"] == trigger]


def test_opened_arms_watch_and_reports_watching(cl):
    r = hopen(cl)
    j = r.json()
    assert r.status_code == 200 and j["watching"] is True and "watch_reason" not in j and j["outcome"] == "ok"
    w = watches(cl).json()
    assert len(w) == 1 and w[0]["game"] == "g1" and w[0]["device"] == "dev-1" and w[0]["state"] == "waiting" and w[0]["since"]
    assert set(w[0]) == {"game", "device", "state", "since", "last_poll", "poll"}


def test_no_process_configured_does_not_watch(cl):
    r = hopen(cl, "g2")
    assert r.status_code == 200 and r.json()["watching"] is False and r.json()["watch_reason"] == "no_process"
    assert watches(cl).json() == []


def test_errors_do_not_arm(cl):
    assert hopen(cl, "nope").status_code == 404
    assert hopen(cl, "g1", "ghost").status_code == 404
    assert watches(cl).json() == []


def test_never_seen_is_discarded(cl):
    hopen(cl)
    assert wait_for(lambda: watches(cl).json() == [])
    h = hist("hook_closed")  # el descarte queda en el historial como omitido, con código estable
    assert len(h) == 1 and h[0]["result"] == "skipped" and h[0]["code"] == "err.hook.never_seen"
    assert h[0]["params"] == {"seconds": settings.HOOK_FIRST_SEEN} and h[0]["device"] == "dev-1"
    g = h[0]["games"]["g1"]
    assert g["result"] == "skipped" and g["code"] == "err.hook.never_seen" and g["name"]


def test_seen_then_closed_makes_one_hook_closed_checkpoint_with_skip(cl):
    e = cl.env
    hopen(cl)
    cl.proc.running = True
    assert wait_for(lambda: watches(cl).json() and watches(cl).json()[0]["state"] == "running")
    e.write(e.d1, "jugado", 3000)  # el dispositivo guarda partida mientras juega
    cl.proc.running = False
    assert wait_for(lambda: hist("hook_closed"))
    time.sleep(0.4)
    h = history.read()
    assert [x["trigger"] for x in h].count("hook_closed") == 1 and h[0]["result"] == "ok"
    assert e.read(e.hub) == "jugado" and e.read(e.d2) == "jugado"
    assert watches(cl).json() == []


def test_closed_with_conflict_skips_never_resolves(cl):
    e = cl.env
    hopen(cl)
    cl.proc.running = True
    assert wait_for(lambda: watches(cl).json() and watches(cl).json()[0]["state"] == "running")
    e.write(e.d1, "pc1", 1000)
    e.write(e.d2, "pc2", 2000)
    cfg = yaml.safe_load(settings.CONFIG_PATH.read_text())
    cfg["games"]["g1"]["on_conflict"] = "newest"  # la política del juego se ignora
    settings.CONFIG_PATH.write_text(yaml.safe_dump(cfg, allow_unicode=True))
    cl.proc.running = False
    assert wait_for(lambda: hist("hook_closed"))
    assert hist("hook_closed")[0]["result"] == "conflict"
    assert (e.read(e.d1), e.read(e.d2), e.read(e.hub)) == ("pc1", "pc2", "base")


def test_transport_error_after_seen_counts_as_closed(cl):
    hopen(cl)
    cl.proc.running = True
    assert wait_for(lambda: watches(cl).json() and watches(cl).json()[0]["state"] == "running")
    cl.proc.fail = True
    cl.proc.running = False
    assert wait_for(lambda: watches(cl).json() == [])
    assert wait_for(lambda: hist("hook_closed")) or True  # el checkpoint corre con el dispositivo caído: aborta
    time.sleep(0.3)
    assert len(hist("hook_closed")) == 1 and hist("hook_closed")[0]["result"] == "aborted"


def test_second_opened_replaces_watch_single_checkpoint(cl):
    hopen(cl, device="dev-1")
    hopen(cl, device="dev-2")
    w = watches(cl).json()
    assert len(w) == 1 and w[0]["device"] == "dev-2"
    cl.proc.running = True
    assert wait_for(lambda: watches(cl).json()[0]["state"] == "running")
    cl.proc.running = False
    assert wait_for(lambda: hist("hook_closed"))
    time.sleep(0.4)
    assert len(hist("hook_closed")) == 1


def test_locked_checkpoint_not_retried_and_logged(cl, caplog):
    import logging
    caplog.set_level(logging.INFO)
    hopen(cl)
    cl.proc.running = True
    assert wait_for(lambda: watches(cl).json() and watches(cl).json()[0]["state"] == "running")
    h = locking.acquire(settings.DATA_DIR / "locks" / "g1.lock")
    try:
        cl.proc.running = False
        assert wait_for(lambda: watches(cl).json() == [])
        time.sleep(0.4)
    finally:
        h.release()
    time.sleep(0.4)
    h = hist("hook_closed")  # una sola entrada «omitido: ocupado», sin reintento y sin checkpoint
    assert len(h) == 1 and h[0]["result"] == "skipped" and h[0]["code"] == "err.hook.busy" and h[0]["device"] == "dev-1"
    assert any("sync_in_progress" in r.getMessage() or "ocupado" in r.getMessage() for r in caplog.records)


def test_aborted_checkpoint_not_retried(cl):
    hopen(cl)
    cl.proc.running = True
    assert wait_for(lambda: watches(cl).json() and watches(cl).json()[0]["state"] == "running")
    cl.proc.reopen = True  # el vigilante lo ve cerrado; al sincronizar el proceso figura abierto: aborta (process_open)
    cl.proc.running = False
    assert wait_for(lambda: hist("hook_closed"))
    time.sleep(0.5)
    assert len(hist("hook_closed")) == 1 and hist("hook_closed")[0]["result"] == "aborted"


def test_watches_endpoint_auth(cl):
    assert cl.get("/api/hook/watches").status_code == 401
    bad = {"Authorization": "Bearer ck_" + "x" * 43}
    assert cl.get("/api/hook/watches", headers=bad).status_code == 401
    assert cl.post("/api/login", json={"user": "admin", "password": PW}).status_code == 200
    assert cl.get("/api/hook/watches").status_code == 401  # cookie de sesión sin key


def test_shutdown_cancels_watches(mk):
    c = mk()
    with c:
        mk.login(c)
        hopen(c)
        watcher = c.app.state.watcher
        tasks = list(watcher.tasks.values())
        assert tasks
    assert all(t.done() for t in tasks) and watcher.tasks == {}


def _seen_running(cl):
    hopen(cl)
    cl.proc.running = True
    assert wait_for(lambda: watches(cl).json() and watches(cl).json()[0]["state"] == "running")


def test_skipped_close_shows_reason_in_hook_status(cl):
    _seen_running(cl)
    h = locking.acquire(settings.DATA_DIR / "locks" / "g1.lock")  # lock ajeno: el checkpoint no corre
    try:
        cl.proc.running = False
        assert wait_for(lambda: hist("hook_closed"))
    finally:
        h.release()
    e = hist("hook_closed")
    assert len(e) == 1 and e[0]["result"] == "skipped" and e[0]["code"] == "err.hook.busy"
    assert cl.post("/api/login", json={"user": "admin", "password": PW}).status_code == 200
    st = cl.get("/api/games/g1/hook-status").json()["devices"][0]["last"]
    assert st["outcome"] == "skipped" and st["code"] == "err.hook.busy"


def test_game_removed_before_close_is_logged(cl):
    _seen_running(cl)
    cfg = yaml.safe_load(settings.CONFIG_PATH.read_text())
    del cfg["games"]["g1"]
    settings.CONFIG_PATH.write_text(yaml.safe_dump(cfg, allow_unicode=True))
    cl.proc.running = False
    assert wait_for(lambda: hist("hook_closed"))
    e = hist("hook_closed")[0]
    assert e["result"] == "skipped" and e["code"] == "err.hook.game_removed" and "g1" in e["games"]


def test_checkpoint_error_is_logged_without_message(cl):
    _seen_running(cl)
    settings.CONFIG_PATH.write_text("games: [no es un mapa\n  secreto-xyz")  # config ilegible: el checkpoint lanza
    cl.proc.running = False
    assert wait_for(lambda: hist("hook_closed"))
    e = hist("hook_closed")[0]
    assert e["result"] == "error" and e["code"] == "err.hook.checkpoint_failed"
    assert set(e["params"]) == {"error"} and "secreto-xyz" not in str(e)


def test_history_failure_never_breaks_watcher(cl, monkeypatch):
    def boom(*a, **k):
        raise OSError("disco lleno")
    monkeypatch.setattr(history, "append", boom)
    hopen(cl)
    assert wait_for(lambda: watches(cl).json() == [])  # el descarte ocurre aunque el historial falle


def test_disabled_game_not_watched_and_close_is_skipped(cl):
    from test_hook_opened import set_enabled
    cl.proc.running = True
    r = hopen(cl)
    assert r.json()["watching"] is True and len(watches(cl).json()) == 1
    set_enabled(cl.env, "g1", False)
    assert watches(cl).json() == []  # el chip desaparece
    cl.proc.running = False
    assert wait_for(lambda: hist("hook_closed"))
    h = hist("hook_closed")
    assert len(h) == 1 and h[0]["result"] == "skipped" and h[0]["code"] == "err.sync.game_disabled"
    assert h[0]["games"]["g1"]["code"] == "err.sync.game_disabled"
    assert len(hist("hook")) == 1  # solo el aviso de apertura: sin checkpoint de cierre
