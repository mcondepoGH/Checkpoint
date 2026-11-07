import json

import pytest
from fastapi.testclient import TestClient

from app import settings, updates
from app.auth import Auth
from app.main import create_app

from test_api import PW, login


def rel(tag, **kw):
    return {"tag_name": tag, "draft": False, "prerelease": False, "body": f"notas {tag}",
            "html_url": f"https://github.com/o/r/releases/tag/{tag}", **kw}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    monkeypatch.setattr(updates, "installed_version", lambda: "0.4.2")
    t = [1_000_000.0]
    calls = []

    def make(releases=None, exc=None):
        def fetch(repo):
            calls.append(repo)
            if exc:
                raise exc
            return releases
        return updates.UpdateChecker(fetch=fetch, clock=lambda: t[0])
    return make, t, calls


def test_parse_version():
    assert updates.parse_version("v1.2.3") == (1, 2, 3)
    assert updates.parse_version("1.2") == (1, 2, 0)
    assert updates.parse_version("0.10.0") > updates.parse_version("0.9.9")
    for bad in ("1.0.0-rc1", "abc", "", None, "desconocida", "1.2.3.4", "v"):
        assert updates.parse_version(bad) is None


def test_stable_channel_ignores_prereleases_and_drafts(env):
    make, _, _ = env
    c = make([rel("v0.9.0", prerelease=True), rel("v0.8.0", draft=True), rel("v0.5.0"), rel("v0.4.9"), rel("v0.5.0-rc1")])
    s = c.state()
    assert s["ultima"] == "0.5.0" and s["hay_actualizacion"] is True and s["actual"] == "0.4.2"
    assert s["notas"] == "notas v0.5.0" and s["url"].endswith("/v0.5.0") and s["comprobado_en"]
    assert s["error"] is None


def test_no_update_when_same_or_older(env):
    make, _, _ = env
    assert make([rel("v0.4.2")]).state()["hay_actualizacion"] is False
    assert make([rel("v0.1.0")]).state()["hay_actualizacion"] is False


def test_unknown_installed_version_never_offers_update(env, monkeypatch):
    make, _, _ = env
    monkeypatch.setattr(updates, "installed_version", lambda: "desconocida")
    s = make([rel("v9.0.0")]).state()
    assert s["hay_actualizacion"] is False and s["actual"] == "desconocida"


def test_cache_memory_and_disk(env, monkeypatch):
    make, t, calls = env
    c = make([rel("v0.5.0")])
    c.state(); c.state()
    assert len(calls) == 1
    # otra instancia (reinicio) usa la caché en disco
    c2 = make([rel("v0.6.0")])
    assert c2.state()["ultima"] == "0.5.0" and len(calls) == 1
    # caduca a las 6 h
    t[0] += 6 * 3600 + 1
    assert c2.state()["ultima"] == "0.6.0" and len(calls) == 2


def test_cache_hours_configurable(env, monkeypatch):
    make, t, calls = env
    monkeypatch.setattr(settings, "UPDATE_CACHE_HOURS", 1.0)
    c = make([rel("v0.5.0")])
    c.state()
    t[0] += 3601
    c.state()
    assert len(calls) == 2


def test_network_error_is_silent_and_keeps_old_data(env):
    make, t, calls = env
    c = make([rel("v0.5.0")])
    c.state()
    t[0] += 7 * 3600
    c2 = make(exc=OSError("sin red"))
    s = c2.state()
    assert s["hay_actualizacion"] is True and s["ultima"] == "0.5.0"  # conserva lo último conocido
    # primer arranque sin red (sin caché): sin ultima, sin excepción
    (settings.DATA_DIR / updates.CACHE_FILE).unlink()
    s = updates.UpdateChecker(fetch=lambda r: (_ for _ in ()).throw(ValueError("x")), clock=lambda: t[0]).state()
    assert s["ultima"] is None and s["hay_actualizacion"] is False


def test_failure_not_retried_immediately(tmp_path, env):
    make, t, calls = env
    c = make(exc=OSError("x"))
    c.state(); c.state()
    assert len(calls) == 1
    t[0] += updates.RETRY_AFTER + 1
    c.state()
    assert len(calls) == 2


def test_disabled_makes_no_request(env):
    make, _, calls = env
    c = make([rel("v0.5.0")])
    c.set_enabled(False)
    s = c.state(refresh=True)
    assert calls == [] and s["habilitado"] is False and s["hay_actualizacion"] is False
    assert make([rel("v0.5.0")]).state()["habilitado"] is False  # persistido
    c.set_enabled(True)
    assert c.state()["habilitado"] is True and len(calls) == 1


def test_env_default_disabled(env, monkeypatch):
    make, _, calls = env
    monkeypatch.setattr(settings, "UPDATE_CHECK", False)
    assert make([rel("v1.0.0")]).state()["habilitado"] is False and calls == []


def test_refresh_rate_limited(env):
    make, t, calls = env
    c = make([rel("v0.5.0")])
    c.state()
    t[0] += 10
    assert c.state(refresh=True)["limitado"] is True and len(calls) == 1
    t[0] += updates.MIN_REFRESH
    s = c.state(refresh=True)
    assert len(calls) == 2 and not s.get("limitado")


def test_repo_configurable_and_validated(env, monkeypatch):
    make, _, calls = env
    monkeypatch.setattr(settings, "UPDATE_REPO", "otro/repo")
    make([rel("v0.5.0")]).state()
    assert calls == ["otro/repo"]
    monkeypatch.setattr(settings, "UPDATE_REPO", "../../x")
    assert updates.repo_name() == updates.DEFAULT_REPO
    assert settings.UPDATE_REPO is not None


def test_url_and_notes_sanitised(env):
    make, _, _ = env
    s = make([rel("v0.5.0", html_url="javascript:alert(1)", body="x" * 20000)]).state()
    assert s["url"] is None and len(s["notas"]) <= updates.NOTES_MAX


def test_fetch_https_only_and_parses(monkeypatch):
    seen = {}

    class R:
        def __init__(self, data): self.data = data
        def read(self, n=-1): return self.data[:n] if n >= 0 else self.data
        def __enter__(self): return self
        def __exit__(self, *a): return False

    class O:
        def open(self, req, timeout=None):
            seen["url"], seen["timeout"] = req.full_url, timeout
            return R(json.dumps([rel("v1.0.0")]).encode())
    monkeypatch.setattr(updates, "_opener", lambda: O())
    out = updates.fetch_releases("o/r")
    assert seen["url"].startswith("https://api.github.com/repos/o/r/releases") and seen["timeout"] <= 10
    assert out[0]["tag_name"] == "v1.0.0"


def test_fetch_rejects_non_list(monkeypatch):
    class R:
        def read(self, n=-1): return b'{"message":"rate limit"}'
        def __enter__(self): return self
        def __exit__(self, *a): return False
    monkeypatch.setattr(updates, "_opener", lambda: type("O", (), {"open": lambda s, r, timeout=None: R()})())
    with pytest.raises(ValueError):
        updates.fetch_releases("o/r")


def test_redirect_to_http_refused():
    h = updates._HttpsOnly()
    import urllib.request
    with pytest.raises(Exception):
        h.redirect_request(urllib.request.Request("https://api.github.com/x"), None, 302, "x", {}, "http://evil/x")


def test_installed_version_file(tmp_path, monkeypatch):
    f = tmp_path / "VERSION"
    f.write_text("v1.2.3\n")
    monkeypatch.setenv("CHECKPOINT_VERSION_FILE", str(f))
    assert updates.installed_version() == "1.2.3"
    f.write_text("dev\n")
    assert updates.installed_version() == "desconocida"
    monkeypatch.setenv("CHECKPOINT_VERSION_FILE", str(tmp_path / "nada"))
    assert updates.installed_version() == "desconocida"


def test_repo_version_file_matches_semver():
    assert updates.parse_version(updates.installed_version()) is not None


# ---- endpoints ----
@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "CONFIG_PATH", tmp_path / "config" / "config.yaml")
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(settings, "STATIC_DIR", tmp_path / "static")
    monkeypatch.setattr(updates, "installed_version", lambda: "0.4.2")
    calls = []
    monkeypatch.setattr(updates, "fetch_releases", lambda repo: calls.append(repo) or [rel("v0.5.0")])
    t = [1000.0]
    c = TestClient(create_app(Auth("admin", PW, 1, clock=lambda: t[0], rounds=4)))
    c.calls = calls
    return c


def test_endpoints_require_session(api):
    assert api.get("/api/updates").status_code == 401
    assert api.get("/api/version").status_code == 401
    assert api.put("/api/updates", json={"enabled": False}).status_code == 401
    assert api.calls == []


def test_endpoints(api):
    login(api)
    assert api.get("/api/version").json() == {"version": "0.4.2"}
    s = api.get("/api/updates").json()
    assert s["hay_actualizacion"] is True and s["ultima"] == "0.5.0" and s["habilitado"] is True
    r = api.put("/api/updates", json={"enabled": False})
    assert r.status_code == 200 and r.json()["habilitado"] is False
    n = len(api.calls)
    assert api.get("/api/updates?refresh=1").json()["hay_actualizacion"] is False
    assert len(api.calls) == n
    assert api.put("/api/updates", json={"enabled": "si"}).status_code == 422
