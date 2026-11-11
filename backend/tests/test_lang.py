"""Idioma por defecto (CHECKPOINT_LANG): opcional, español si falta o no es válido; endpoint público."""
import logging

import pytest
from fastapi.testclient import TestClient

from app.core import bootstrap, settings
from app.auth import Auth
from app.main import create_app


def test_default_is_spanish():
    assert settings.resolve_lang({}) == ("es", None)
    assert settings.resolve_lang({"CHECKPOINT_LANG": ""}) == ("es", None)
    assert settings.resolve_lang({"CHECKPOINT_LANG": "  "}) == ("es", None)


@pytest.mark.parametrize("raw,expected", [("en", "en"), ("EN", "en"), (" es ", "es"), ("en-US", "en"), ("en_GB", "en")])
def test_supported_values(raw, expected):
    assert settings.resolve_lang({"CHECKPOINT_LANG": raw}) == (expected, None)


def test_unsupported_falls_back_with_warning():
    lang, warn = settings.resolve_lang({"CHECKPOINT_LANG": "fr"})
    assert lang == "es" and "fr" in warn and "CHECKPOINT_LANG" in warn


def test_startup_logs_warning(monkeypatch, caplog):
    monkeypatch.setenv("CHECKPOINT_LANG", "xx")
    monkeypatch.setattr(bootstrap, "ensure_config", lambda: None)
    monkeypatch.setattr(bootstrap, "ensure_ssh_key", lambda: None)
    with caplog.at_level(logging.WARNING):
        bootstrap.startup()
    assert any("CHECKPOINT_LANG" in r.getMessage() for r in caplog.records)


def test_startup_silent_when_valid(monkeypatch, caplog):
    monkeypatch.setenv("CHECKPOINT_LANG", "en")
    monkeypatch.setattr(bootstrap, "ensure_config", lambda: None)
    monkeypatch.setattr(bootstrap, "ensure_ssh_key", lambda: None)
    with caplog.at_level(logging.WARNING):
        bootstrap.startup()
    assert not any("CHECKPOINT_LANG" in r.getMessage() for r in caplog.records)


def _client():
    return TestClient(create_app(Auth("u", "p")))


def test_public_endpoint_without_session(monkeypatch):
    monkeypatch.delenv("CHECKPOINT_LANG", raising=False)
    r = _client().get("/api/public")
    assert r.status_code == 200 and r.json() == {"default_lang": "es"}
    monkeypatch.setenv("CHECKPOINT_LANG", "en")
    assert _client().get("/api/public").json() == {"default_lang": "en"}
    monkeypatch.setenv("CHECKPOINT_LANG", "zz")
    assert _client().get("/api/public").json() == {"default_lang": "es"}
