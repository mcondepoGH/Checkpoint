"""Contrato JSON de la API que consume el frontend (claves exactas) y cuerpos mal formados."""
import json

import pytest
from fastapi.testclient import TestClient

from app.core import settings, updates
from app.api.auth import Auth
from app.main import create_app

PW = "correct horse"
GID = "g1"
DEV_A, DEV_B = "equipo-a", "equipo-b"
CFG = {"devices": {DEV_A: {"name": "Equipo A", "host": "192.0.2.1", "user": "u", "os": "linux"},
                   DEV_B: {"name": "Equipo B", "host": "192.0.2.2", "user": "u", "os": "windows"}},
       "games": {GID: {"name": "Juego de prueba", "devices": [DEV_A, DEV_B],
                       "paths": {DEV_A: "/x/y", DEV_B: "C:/z"}}}}


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "CONFIG_PATH", tmp_path / "config" / "config.yaml")
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(settings, "STATIC_DIR", tmp_path / "static")
    monkeypatch.setattr(updates, "installed_version", lambda: "1.0.0")
    monkeypatch.setattr(updates, "fetch_releases", lambda repo: [])
    c = TestClient(create_app(Auth("admin", PW, 1, rounds=4)), raise_server_exceptions=False)
    assert c.post("/api/login", json={"user": "admin", "password": PW}).status_code == 200
    v = c.get("/api/config").json()["version"]
    assert c.put("/api/config", json={"config": CFG, "base_version": v}).status_code == 200
    c.tmp = tmp_path
    return c


def test_contract_config(api):
    j = api.get("/api/config").json()
    assert set(j) == {"version", "config", "error", "runtime", "platform"}
    assert set(j["config"]) >= {"devices", "games"}
    assert set(j["config"]["games"][GID]) >= {"name", "devices", "paths"}
    assert j["config"]["devices"][DEV_A]["name"] == "Equipo A"


def test_contract_scheduler(api):
    assert set(api.get("/api/scheduler").json()) >= {
        "enabled", "interval_hours", "run_on_start", "on_conflict", "next_run", "last_run"}


def test_contract_updates(api):
    j = api.get("/api/updates").json()
    assert set(j) >= {"aplicable", "habilitado", "canal", "actual", "ultima", "hay_actualizacion"}


def test_contract_status_keyed_by_game_id(api):
    sd = api.tmp / "data" / "status"
    sd.mkdir(parents=True)
    (sd / f"{GID}.json").write_text(json.dumps({"game": GID, "result": "ok", "message": "m"}))
    got = api.get("/api/status").json()
    assert list(got) == [GID]
    assert set(got[GID]) >= {"game", "name", "result", "message"}
    assert got[GID]["game"] == GID and got[GID]["name"] == "Juego de prueba"


def test_contract_versions_limit(api):
    assert set(api.get(f"/api/versions/{GID}/limit").json()) == {"max", "count", "override"}


def test_contract_history_entries(api):
    assert api.get("/api/scheduler/history").json() == {"entries": []}


@pytest.mark.parametrize("path", ["/api/login", f"/api/versions/{GID}/restore"])
@pytest.mark.parametrize("body", ["[]", "5", "null", "no-json"])
def test_non_dict_body_is_400_not_500(api, path, body):
    r = api.post(path, content=body, headers={"content-type": "application/json"})
    assert r.status_code == 400, (path, body, r.status_code)


def test_removed_endpoints_are_gone(api):
    for p in ("/api/version", "/api/config/status"):
        assert api.get(p).status_code == 404, p
