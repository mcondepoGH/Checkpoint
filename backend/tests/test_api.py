import bcrypt
import pytest
from fastapi.testclient import TestClient

from app import settings
from app.auth import Auth
from app.main import create_app
from app.redact import redact

PW = "correct horse"
CFG = {"devices": {"a": {"host": "10.0.0.1", "user": "u", "os": "linux"},
                   "b": {"host": "10.0.0.2", "user": "u", "os": "windows"}},
       "games": {}}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "CONFIG_PATH", tmp_path / "config" / "config.yaml")
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(settings, "STATIC_DIR", tmp_path / "static")
    (tmp_path / "static").mkdir()
    (tmp_path / "static/index.html").write_text("<html>app</html>")
    t = [1000.0]
    a = Auth("admin", PW, 1, clock=lambda: t[0], rounds=4)
    c = TestClient(create_app(a))
    c.clock, c.sauth = t, a
    return c


def login(c, pw=PW, user="admin"):
    return c.post("/api/login", json={"user": user, "password": pw})


def test_api_requires_session(client):
    for m, p in [("get", "/api/config"), ("put", "/api/config"), ("get", "/api/status"),
                 ("post", "/api/sync/x"), ("get", "/api/versions/x"), ("get", "/api/runs/x/stream"),
                 ("post", "/api/devices/test"), ("post", "/api/config/validate"),
                 ("post", "/api/config/diff"), ("post", "/api/config/yaml"),
                 ("get", "/api/config/status"), ("get", "/api/config/events"),
                 ("get", "/api/config/backups"), ("post", "/api/config/restore")]:
        assert getattr(client, m)(p).status_code == 401, p
    assert client.get("/").status_code == 200  # solo shell de login


def test_login_cookie_flags_and_config_roundtrip(client):
    r = login(client)
    assert r.status_code == 200
    sc = r.headers["set-cookie"].lower()
    assert "httponly" in sc and "samesite=strict" in sc and "max-age=3600" in sc
    v0 = client.get("/api/config").json()["version"]
    r = client.put("/api/config", json={"config": CFG, "base_version": v0})
    assert r.status_code == 200 and r.json()["changed"] is True
    got = client.get("/api/config").json()
    assert got["config"]["devices"]["a"]["host"] == "10.0.0.1" and got["error"] is None
    bad = {"devices": {"a": {"host": "x y", "user": "u", "os": "linux"}}}
    r = client.put("/api/config", json={"config": bad, "base_version": got["version"]})
    assert r.status_code == 422 and "devices.a.host" in r.json()["errors"]
    assert client.get("/api/config").json()["config"]["devices"]["a"]["host"] == "10.0.0.1"  # intacto


def test_session_expires(client):
    login(client)
    client.clock[0] += 3601
    assert client.get("/api/config").status_code == 401


def test_bad_password_and_backoff(client):
    assert login(client, "no").status_code == 401
    assert login(client, "no").status_code == 401
    assert login(client, "no").status_code == 401  # 3er fallo => bloqueo 5 s
    r = login(client)  # correcta pero bloqueada
    assert r.status_code == 429 and int(r.headers["retry-after"]) >= 1
    client.clock[0] += 6
    assert login(client).status_code == 200
    # tras éxito se resetea
    assert client.sauth.wait_time("testclient") == 0


def test_backoff_grows(client):
    waits = []
    for _ in range(5):
        login(client, "no")
        waits.append(client.sauth.wait_time("testclient"))
        client.clock[0] += waits[-1]
    assert waits[2] < waits[3] < waits[4]


def test_foreign_origin_blocked(client):
    login(client)
    r = client.put("/api/config", json={"config": CFG, "base_version": "x"}, headers={"origin": "http://evil.example"})
    assert r.status_code == 403


def test_redact():
    assert "REDACTED" in redact("password=hunter2")
    assert "hunter2" not in redact("token: hunter2")
    assert "REDACTED" in redact("x " + bcrypt.hashpw(PW.encode(), bcrypt.gensalt(4)).decode())


def test_scheduler_endpoints(client):
    assert client.get("/api/scheduler").status_code == 401
    assert client.put("/api/scheduler", json={}).status_code == 401
    login(client)
    g = client.get("/api/scheduler").json()
    assert g["enabled"] is False and g["next_run"] is None and g["last_run"] is None
    r = client.put("/api/scheduler", json={"enabled": True, "interval_hours": 6})
    assert r.status_code == 200 and r.json()["next_run"] and r.json()["interval_hours"] == 6.0
    r = client.put("/api/scheduler", json={"interval_hours": 0.1})
    assert r.status_code == 422 and "interval_hours" in r.json()["errors"]
    assert client.get("/api/scheduler").json()["interval_hours"] == 6.0


def test_scheduler_history_endpoint(client):
    from datetime import datetime, timezone
    from app import history
    assert client.get("/api/scheduler/history").status_code == 401
    login(client)
    assert client.get("/api/scheduler/history").json() == {"entries": []}
    now = datetime.now(timezone.utc)
    for i in range(205):
        history.append(history.make_entry(now, 0.5, "scheduled", "ok", {"g": {"result": "ok", "message": ""}}, f"e{i}"), now=now)
    assert len(client.get("/api/scheduler/history").json()["entries"]) == 50
    r = client.get("/api/scheduler/history?limit=200").json()["entries"]
    assert len(r) == 200 and r[0]["message"] == "e204"
    assert client.get("/api/scheduler/history?limit=3").json()["entries"][2]["message"] == "e202"
    for bad in ("0", "201", "-1", "abc"):
        assert client.get(f"/api/scheduler/history?limit={bad}").status_code == 422, bad
