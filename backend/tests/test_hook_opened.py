"""POST /api/hook/{game}/opened: sync previo bloqueante con Bearer. Dispositivos «Este equipo» reales sobre tmpdirs."""
import json
import os
import threading
import time

import pytest
import yaml
from fastapi.testclient import TestClient

from app import history, settings
from app.auth import Auth
from app.main import create_app
from app.sync import fingerprint, save_baseline

PW = "correct horse"


class Env:
    """dev-1 = «Este equipo» (real, tmpdir); dev-2 = remoto simulado (LocalTransport sobre tmp/laptop)."""

    def __init__(self, tmp):
        self.tmp = tmp
        self.d1, self.hub = tmp / "pc1", tmp / "data" / "hub" / "g1"
        self.laptop = tmp / "laptop"
        self.d2 = self.laptop / "home/u/g"
        cfg = {"devices": {"dev-1": {"name": "PC uno", "local": True, "os": "linux"},
                           "dev-2": {"name": "Laptop", "host": "192.0.2.10", "user": "u", "os": "linux"}},
               "games": {"g1": {"name": "Mi Juego", "devices": ["dev-1", "dev-2"],
                                "paths": {"dev-1": str(self.d1), "dev-2": "/home/u/g"}}}}
        (tmp / "config").mkdir(parents=True, exist_ok=True)
        (tmp / "config" / "config.yaml").write_text(yaml.safe_dump(cfg, allow_unicode=True))

    def write(self, d, content, mtime, name="s.sav"):
        d.mkdir(parents=True, exist_ok=True)
        f = d / name
        f.write_text(content)
        os.utime(f, (mtime, mtime))

    def seed(self, content="base"):
        for d in (self.d1, self.d2, self.hub):
            self.write(d, content, 500)
        h = fingerprint(self.d1).hash
        save_baseline(self.tmp / "data", "g1", {"dev-1": h, "dev-2": h, "hub": h})

    def read(self, d):
        return (d / "s.sav").read_text()


@pytest.fixture
def env(tmp_path, monkeypatch):
    import app.sync as sync
    from fakes import LocalTransport
    real = sync.get_transport
    e = Env(tmp_path)
    monkeypatch.setattr(sync, "get_transport", lambda dev: real(dev) if dev.local else LocalTransport(e.laptop))
    monkeypatch.setattr(settings, "CONFIG_PATH", tmp_path / "config" / "config.yaml")
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(settings, "STATIC_DIR", tmp_path / "static")
    return e


@pytest.fixture
def client(env):
    c = TestClient(create_app(Auth("admin", PW, 1, rounds=4)))
    assert c.post("/api/login", json={"user": "admin", "password": PW}).status_code == 200
    c.key = c.post("/api/profile/apikey").json()["key"]
    c.hdr = {"Authorization": f"Bearer {c.key}"}
    c.env = env
    return c


def opened(c, game="g1", device="dev-1", headers=None, query=True):
    h = c.hdr if headers is None else headers
    url = f"/api/hook/{game}/opened" + (f"?device={device}" if device and query else "")
    return TestClient(c.app).post(url, headers=h)  # cliente aparte: sin la cookie de sesión


def code(r):
    return r.json()["detail"]["code"]


def test_newer_hub_save_is_copied_to_device(client):
    e = client.env
    e.seed()
    e.write(e.hub, "nuevo", 2000)  # solo el hub cambió
    r = opened(client)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["ok"] is True and j["outcome"] == "ok" and j["game"] == "g1" and j["device"] == "dev-1"
    assert j["run_id"] and j["code"] == "err.sync.done"
    assert e.read(e.d1) == "nuevo" and e.read(e.d2) == "nuevo"


def test_nothing_to_copy(client):
    e = client.env
    e.seed()
    r = opened(client)
    assert r.status_code == 200 and r.json()["outcome"] == "ok" and r.json()["code"] == "err.sync.already_synced"
    assert e.read(e.d1) == "base"


def test_conflict_touches_nothing_and_is_logged(client):
    e = client.env
    e.seed()
    e.write(e.d1, "pc1", 1000)
    e.write(e.d2, "pc2", 2000)
    r = opened(client)
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] is False and j["outcome"] == "conflict" and j["code"] == "err.sync.conflict"
    assert (e.read(e.d1), e.read(e.d2), e.read(e.hub)) == ("pc1", "pc2", "base")
    h = history.read()
    assert len(h) == 1 and h[0]["trigger"] == "hook" and h[0]["result"] == "conflict"
    assert h[0]["games"]["g1"]["result"] == "conflict" and h[0]["games"]["g1"]["name"] == "Mi Juego"


def test_success_is_logged_with_trigger_hook(client):
    client.env.seed()
    opened(client)
    assert [x["trigger"] for x in history.read()] == ["hook"]


def test_conflict_uses_scheduler_policy(client):
    e = client.env
    e.seed()
    e.write(e.d1, "pc1", 1000)
    e.write(e.d2, "pc2", 2000)
    client.put("/api/scheduler", json={"on_conflict": "newest"})
    assert opened(client).json()["outcome"] == "ok"  # misma política que el ciclo automático
    assert e.read(e.d1) == "pc2"


def test_resolves_by_id_and_by_name_and_device_by_name(client):
    client.env.seed()
    for game, dev in (("g1", "dev-2"), ("Mi Juego", "PC uno"), ("mi juego", "laptop")):
        r = opened(client, game, dev)
        assert r.status_code == 200 and r.json()["game"] == "g1", (game, dev)
    assert opened(client, "Mi Juego", "PC uno").json()["device"] == "dev-1"


def test_run_in_progress_409(client):
    client.env.seed()
    from app import locking
    h = locking.acquire(settings.DATA_DIR / "locks" / "g1.lock")  # otro proceso con el lock del juego
    try:
        r = opened(client)
    finally:
        h.release()
    assert r.status_code == 409 and code(r) == "err.main.run_in_progress"
    assert history.read() == []  # un 409 no deja entrada


def test_run_in_progress_with_manual_run(client):
    client.env.seed()
    gate = threading.Event()
    import app.main as m
    real = m.run_sync
    m.run_sync = lambda *a, **k: (gate.wait(5), real(*a, **k))[1]
    try:
        r1 = client.post("/api/sync/g1", json={})
        assert r1.status_code == 200
        r = opened(client)
        assert r.status_code == 409 and code(r) == "err.main.run_in_progress"
    finally:
        gate.set()
        m.run_sync = real


def test_unknown_game_and_device_404(client):
    client.env.seed()
    r = opened(client, "nope")
    assert r.status_code == 404 and code(r) == "err.main.game_unknown"
    r = opened(client, "g1", "ghost")
    assert r.status_code == 404 and code(r) == "err.hook.device_unknown"


def test_missing_device_is_400_when_ambiguous(client):
    client.env.seed()
    r = opened(client, device=None)
    assert r.status_code == 400 and code(r) == "err.hook.device_required"
    assert r.json()["detail"]["params"]["devices"]


def test_auth_401_before_404_and_no_cookie(client):
    client.env.seed()
    bad = {"Authorization": "Bearer ck_" + "x" * 43}
    r = opened(client, "g1", headers=bad)
    assert r.status_code == 401 and code(r) == "err.apikey.invalid"
    r = opened(client, "nope", headers=bad)  # no revela si el juego existe
    assert r.status_code == 401 and code(r) == "err.apikey.invalid"
    # cookie de sesión sin key (el TestClient de la fixture conserva la cookie): 401
    assert client.post("/api/hook/g1/opened?device=dev-1").status_code == 401


def test_offline_device_aborts_with_200(client, monkeypatch):
    client.env.seed()
    from fakes import LocalTransport
    import app.sync as sync
    monkeypatch.setattr(sync, "get_transport", lambda dev: LocalTransport(client.env.laptop, down=True))
    r = opened(client)
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] is False and j["outcome"] == "aborted" and j["code"] == "err.sync.all_offline"
    assert history.read()[0]["trigger"] == "hook"


def test_unexpected_error_is_200(client, monkeypatch):
    client.env.seed()
    import app.sync as sync
    monkeypatch.setattr(sync, "get_transport", lambda dev: 1 / 0)
    r = opened(client)
    assert r.status_code == 200 and r.json()["outcome"] == "error"


def test_server_timeout_returns_200_and_run_continues(client, monkeypatch):
    client.env.seed()
    monkeypatch.setattr(settings, "HOOK_WAIT", 0.2)
    gate = threading.Event()
    from fakes import LocalTransport
    real = LocalTransport.check
    monkeypatch.setattr(LocalTransport, "check", lambda self: (gate.wait(5), real(self))[1])
    try:
        r = opened(client)
        assert r.status_code == 200 and r.json()["outcome"] == "timeout" and r.json()["ok"] is False
        assert opened(client).status_code == 409  # sigue en curso
    finally:
        gate.set()
    for _ in range(50):
        if history.read():
            break
        time.sleep(0.1)
    assert history.read()[0]["trigger"] == "hook"


def test_scheduler_untouched_by_hook(client):
    client.env.seed()
    opened(client)
    assert client.get("/api/scheduler").json()["last_run"] is None
