"""Logs DEBUG de los endpoints: aparecen con DEBUG, no con INFO y nunca llevan secretos."""
import logging

import pytest
from fastapi.testclient import TestClient

from app import settings
from app.auth import Auth
from app.main import create_app

PW = "correct horse"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "CONFIG_PATH", tmp_path / "config" / "config.yaml")
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(settings, "STATIC_DIR", tmp_path / "static")
    return TestClient(create_app(Auth("admin", PW, 1, rounds=4)))


def login(c):
    assert c.post("/api/login", json={"user": "admin", "password": PW}).status_code == 200


def msgs(caplog):
    return [r.getMessage() for r in caplog.records if r.name.startswith("checkpoint.api")]


def test_debug_logs_each_request_and_endpoint_detail(client, caplog):
    caplog.set_level(logging.DEBUG, logger="checkpoint.api")
    login(client)
    client.get("/api/scheduler")
    m = msgs(caplog)
    assert any("POST /api/login" in x and "-> 200" in x for x in m)
    assert any("GET /api/scheduler" in x and "-> 200" in x and " ms" in x for x in m)
    assert any(x.startswith("login:") and "correcto" in x for x in m)


def test_info_level_emits_nothing(client, caplog):
    caplog.set_level(logging.INFO, logger="checkpoint.api")
    login(client)
    client.get("/api/scheduler")
    assert msgs(caplog) == []


def test_no_secrets_in_debug_logs(client, caplog):
    caplog.set_level(logging.DEBUG, logger="checkpoint")
    login(client)
    key = client.post("/api/profile/apikey").json()["key"]
    client.get("/api/profile/apikey")
    TestClient(client.app).get("/api/hook/ping", headers={"Authorization": f"Bearer {key}"})
    TestClient(client.app).get("/api/hook/ping", headers={"Authorization": "Bearer ck_malo"})
    TestClient(client.app).post("/api/login", json={"user": "admin", "password": "wrong-pass-123"})
    text = "\n".join(r.getMessage() for r in caplog.records)
    token = client.cookies.get("checkpoint_session")
    for secret in (key, PW, "wrong-pass-123", "ck_malo", token):
        assert secret and secret not in text
    assert "hook auth: ip=" in text and "(401)" in text


def test_log_level_setting():
    assert settings.log_level({}) == "INFO"
    assert settings.log_level({"CHECKPOINT_LOG_LEVEL": "debug"}) == "DEBUG"
    assert settings.log_level({"CHECKPOINT_LOG_LEVEL": "ruido"}) == "INFO"
    assert settings.resolve_log_level({"CHECKPOINT_LOG_LEVEL": "ruido"})[1]
    assert settings.resolve_log_level({"CHECKPOINT_LOG_LEVEL": "Debug"}) == ("DEBUG", None)
    assert settings.resolve_log_level({}) == ("INFO", None)
