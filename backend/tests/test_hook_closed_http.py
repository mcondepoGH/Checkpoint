"""POST /api/hook/{game}/closed?device=: un dispositivo `http` avisa de que cerró el juego. Solo deja constancia en el
historial (`hook_closed`); no hay pull/push ni sync clásica."""

import yaml
from fastapi.testclient import TestClient

from app.api.auth import Auth
from app.main import create_app
from app.users import history
from test_hook_fingerprint import PW, Env, client, code, env  # noqa: F401 (fixtures)


def closed(c, game="g1", device="deck", headers=None):
    h = {"Authorization": f"Bearer {c.key}"} if headers is None else headers
    url = f"/api/hook/{game}/closed" + (f"?device={device}" if device else "")
    return TestClient(c.app).post(url, headers=h)


def entries():
    return [e for e in history.read() if e["trigger"] == "hook_closed"]


def test_records_closure_and_returns_state(client):
    r = closed(client)
    assert r.status_code == 200, r.text
    assert r.json() == {"game": "g1", "device": "deck", "recorded": True, "outcome": "ok"}
    (e,) = entries()
    assert e["device"] == "deck" and e["result"] == "ok" and e["games"]["g1"]["name"] == "Mi Juego"


def test_does_not_sync_or_touch_files(client):
    e = client.env
    e.write_hub("base")
    e.baseline()
    before = sorted(str(p.relative_to(e.data)) for p in e.data.rglob("*") if "history" not in str(p))
    assert closed(client).status_code == 200
    after = sorted(str(p.relative_to(e.data)) for p in e.data.rglob("*") if "history" not in str(p))
    assert before == after and (e.hub / "s.sav").read_text() == "base"


def test_by_name_and_device_deduced(client):
    r = closed(client, game="Mi Juego", device="Steam Deck")
    assert r.status_code == 200 and r.json()["device"] == "deck"
    assert closed(client, device=None).json()["device"] == "deck"


def test_shows_in_hook_status(client):
    closed(client)
    s = client.get("/api/games/g1/hook-status").json()["devices"]
    deck = next(d for d in s if d["device"] == "deck")
    assert deck["last"]["trigger"] == "hook_closed" and deck["last"]["outcome"] == "ok"


def test_auth_401(client):
    for h in ({}, {"Authorization": "Bearer ck_" + "x" * 43}):
        r = closed(client, headers=h)
        assert r.status_code == 401 and code(r) == "err.apikey.invalid"
    assert client.post("/api/hook/g1/closed?device=deck").status_code == 401  # cookie sola no vale


def test_429_after_repeated_bad_keys(client):
    bad = {"Authorization": "Bearer ck_" + "y" * 43}
    for _ in range(3):
        closed(client, headers=bad)
    r = closed(client)
    assert r.status_code == 429 and int(r.headers["retry-after"]) > 0


def test_404_unknown_game_and_device(client):
    r = closed(client, game="nope")
    assert r.status_code == 404 and code(r) == "err.main.game_unknown"
    r = closed(client, device="nope")
    assert r.status_code == 403 and code(r) == "err.apikey.device_mismatch"
    assert entries() == []


def test_other_device_is_403(client):
    r = closed(client, device="pc")
    assert r.status_code == 403 and code(r) == "err.apikey.device_mismatch"
    assert entries() == []


def test_two_http_devices_device_comes_from_the_key(tmp_path, monkeypatch, env):
    cfg = {
        "devices": {"a": {"name": "A", "http": True, "os": "linux"}, "b": {"name": "B", "http": True, "os": "linux"}},
        "games": {"g1": {"name": "J", "devices": ["a", "b"], "paths": {"a": "/x", "b": "/y"}}},
    }
    Env(tmp_path, cfg)
    c = TestClient(create_app(Auth("admin", PW, 1, rounds=4)))
    c.post("/api/login", json={"user": "admin", "password": PW})
    c.key = c.post("/api/devices/a/apikey").json()["key"]
    r = closed(c, device=None)
    assert r.status_code == 200 and r.json()["device"] == "a"
    assert code(closed(c, device="b")) == "err.apikey.device_mismatch"


def test_409_busy_records_skipped(client):
    client.app.state.ctx.runs.create("g1", False, "Mi Juego")  # run sin terminar
    r = closed(client)
    assert r.status_code == 409 and code(r) == "err.main.run_in_progress"
    (e,) = entries()
    assert e["result"] == "skipped" and e["code"] == "err.hook.busy" and e["device"] == "deck"


def test_scheduler_current_is_busy(client):
    client.app.state.ctx.scheduler.current = "g1"
    assert code(closed(client)) == "err.main.run_in_progress"


def test_disabled_game_records_skipped(tmp_path, env):
    cfg = yaml.safe_load((tmp_path / "config" / "config.yaml").read_text())
    cfg["games"]["g1"]["enabled"] = False
    (tmp_path / "config" / "config.yaml").write_text(yaml.safe_dump(cfg))
    c = TestClient(create_app(Auth("admin", PW, 1, rounds=4)))
    c.post("/api/login", json={"user": "admin", "password": PW})
    c.key = c.post("/api/devices/deck/apikey").json()["key"]
    r = closed(c)
    assert r.status_code == 200
    assert r.json() == {
        "game": "g1",
        "device": "deck",
        "recorded": True,
        "outcome": "skipped",
        "code": "err.sync.game_disabled",
        "params": {},
    }
    (e,) = entries()
    assert e["result"] == "skipped" and e["code"] == "err.sync.game_disabled"
