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
    v = updates.installed_version()
    assert updates.parse_semver(v) is not None and updates.format_semver(v) == v   # admite pre-release (1.0.0-rc.1)


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


# ---- canal de pruebas (beta) ----
def test_semver_prerelease_order():
    k = updates.parse_semver
    order = ["0.5.0-alpha", "0.5.0-alpha.1", "0.5.0-alpha.beta", "0.5.0-beta", "0.5.0-beta.2", "0.5.0-beta.11",
             "0.5.0-rc.1", "0.5.0-rc.2", "0.5.0", "0.5.1-rc.1", "0.5.1", "0.10.0"]
    keys = [k(v) for v in order]
    assert all(x is not None for x in keys)
    assert keys == sorted(keys) and len(set(keys)) == len(keys)
    assert k("0.5.0-rc.1") < k("0.5.0") and k("0.5.0-rc.2") > k("0.5.0-rc.1")
    assert k("0.5.0-rc.10") > k("0.5.0-rc.9")          # numéricos como número
    assert k("0.5.0-1") < k("0.5.0-a")                  # numérico < alfanumérico
    assert k("v0.5.0+build7") == k("0.5.0")             # la build se ignora
    for bad in ("0.5.0-", "0.5.0-rc..1", "0.5.0-01", "x", "", None, "1.2.3.4", "0.5.0-rc_1"):
        assert k(bad) is None
    assert updates.format_semver("v0.5.0-rc.1+b") == "0.5.0-rc.1" and updates.format_semver("1.2") == "1.2.0"


def test_pick_latest_channels():
    rels = [rel("v0.5.0-rc.2", prerelease=True), rel("v0.5.0-rc.1", prerelease=True), rel("v0.4.9"),
            rel("v0.9.0", draft=True), rel("v0.6.0-beta.1", prerelease=True)]
    assert updates.pick_latest(rels)["version"] == "0.4.9"
    assert updates.pick_latest(rels, "stable")["version"] == "0.4.9"
    b = updates.pick_latest(rels, "beta")
    assert b["version"] == "0.6.0-beta.1" and b["prerelease"] is True
    # la estable 0.5.0 gana a sus propios rc; borradores nunca
    b = updates.pick_latest(rels + [rel("v0.5.0")], "beta")
    assert b["version"] == "0.6.0-beta.1"
    b = updates.pick_latest([rel("v0.5.0"), rel("v0.5.0-rc.2", prerelease=True)], "beta")
    assert b["version"] == "0.5.0" and b["prerelease"] is False
    assert updates.pick_latest([rel("v0.9.0", draft=True)], "beta") is None
    # sufijo en el tag aunque GitHub no la marque como pre-release: no es estable
    assert updates.pick_latest([rel("v0.7.0-rc.1")], "stable") is None
    assert updates.pick_latest([rel("v0.7.0-rc.1")], "beta")["prerelease"] is True
    # desconocido -> stable
    assert updates.pick_latest(rels, "raro")["version"] == "0.4.9"


def test_beta_state_offers_prerelease(env):
    make, _, _ = env
    c = make([rel("v0.5.0-rc.1", prerelease=True), rel("v0.4.2")])
    assert c.state()["hay_actualizacion"] is False and c.state()["canal"] == "stable"
    c.set_channel("beta")
    s = c.state()
    assert s["canal"] == "beta" and s["ultima"] == "0.5.0-rc.1" and s["prerelease"] is True and s["hay_actualizacion"] is True


def test_channel_change_invalidates_cache(env):
    make, t, calls = env
    c = make([rel("v0.5.0-rc.1", prerelease=True), rel("v0.4.5")])
    assert c.state()["ultima"] == "0.4.5" and len(calls) == 1
    c.set_channel("beta")
    assert c.state()["ultima"] == "0.5.0-rc.1" and len(calls) == 2   # sin esperar al TTL
    c.set_channel("stable")
    assert c.state()["ultima"] == "0.4.5" and len(calls) == 3
    # tras un fallo de red en el cambio no se arrastra el resultado del otro canal
    c.set_channel("beta")
    c2 = make(exc=OSError("x"))
    t[0] += 1
    c2._cache = None
    assert c2.state()["ultima"] is None


def test_phase1_cache_without_channel_counts_as_stable(env):
    make, _, calls = env
    c = make([rel("v0.5.0")])
    c.state()
    p = settings.DATA_DIR / updates.CACHE_FILE
    d = json.loads(p.read_text()); d.pop("channel"); p.write_text(json.dumps(d))
    c2 = make([rel("v0.6.0")])
    assert c2.state()["ultima"] == "0.5.0" and len(calls) == 1      # válida para stable
    c2.set_channel("beta")
    assert c2.state()["ultima"] == "0.6.0" and len(calls) == 2


def test_no_downgrade(env, monkeypatch):
    make0, _, _ = env

    def make(rels):
        (settings.DATA_DIR / updates.CACHE_FILE).unlink(missing_ok=True)   # cada caso parte sin caché
        return make0(rels)
    monkeypatch.setattr(updates, "installed_version", lambda: "0.5.0-rc.1")
    # en una pre-release y canal estable: la estable menor no se ofrece
    assert make([rel("v0.4.9")]).state()["hay_actualizacion"] is False
    # la estable mayor sí
    assert make([rel("v0.5.0")]).state()["hay_actualizacion"] is True
    # beta: el siguiente rc sí, el mismo no, el anterior no
    c = make([rel("v0.5.0-rc.2", prerelease=True)]); c.set_channel("beta")
    assert c.state()["hay_actualizacion"] is True
    c = make([rel("v0.5.0-rc.1", prerelease=True)]); c.set_channel("beta")
    assert c.state()["hay_actualizacion"] is False
    c = make([rel("v0.4.0", ), rel("v0.5.0-beta.3", prerelease=True)]); c.set_channel("beta")
    assert c.state()["hay_actualizacion"] is False
    # estable instalada 0.5.0 no baja a una pre-release menor
    monkeypatch.setattr(updates, "installed_version", lambda: "0.5.0")
    c = make([rel("v0.5.0-rc.9", prerelease=True)]); c.set_channel("beta")
    assert c.state()["hay_actualizacion"] is False


def test_installed_version_accepts_prerelease(tmp_path, monkeypatch):
    f = tmp_path / "VERSION"
    f.write_text("v0.5.0-rc.1\n")
    monkeypatch.setenv("CHECKPOINT_VERSION_FILE", str(f))
    assert updates.installed_version() == "0.5.0-rc.1"


def test_channel_persist_env_default_and_validation(env, monkeypatch):
    make, _, _ = env
    monkeypatch.setattr(settings, "UPDATE_CHANNEL", "beta")
    c = make([rel("v0.5.0")])
    assert c.channel() == "beta"                       # valor inicial por entorno
    c.set_channel("stable")
    assert make([]).channel() == "stable"              # lo guardado prevalece sobre el entorno
    assert json.loads((settings.DATA_DIR / updates.SETTINGS_FILE).read_text()) == {"channel": "stable"}
    with pytest.raises(ValueError):
        c.set_channel("nightly")
    monkeypatch.setattr(settings, "UPDATE_CHANNEL", "raro")
    (settings.DATA_DIR / updates.SETTINGS_FILE).unlink()
    assert make([]).channel() == "stable"              # entorno desconocido -> stable
    (settings.DATA_DIR / updates.SETTINGS_FILE).write_text('{"channel": 7}')
    assert make([]).channel() == "stable"              # fichero corrupto -> stable


def test_enabled_and_channel_do_not_clobber_each_other(env):
    make, _, _ = env
    c = make([rel("v0.5.0")])
    c.set_channel("beta"); c.set_enabled(False)
    c2 = make([])
    assert c2.channel() == "beta" and c2.enabled() is False
    c2.set_channel("stable")
    assert c2.enabled() is False


def test_settings_env_channel_parsing(monkeypatch):
    import importlib
    for raw, exp in (("beta", "beta"), (" BETA ", "beta"), ("stable", "stable"), ("xx", "stable"), ("", "stable")):
        monkeypatch.setenv("CHECKPOINT_UPDATE_CHANNEL", raw)
        importlib.reload(settings)
        assert settings.UPDATE_CHANNEL == exp
    monkeypatch.delenv("CHECKPOINT_UPDATE_CHANNEL")
    importlib.reload(settings)
    assert settings.UPDATE_CHANNEL == "stable"


def test_endpoints_channel(api, monkeypatch):
    monkeypatch.setattr(updates, "fetch_releases", lambda repo: [rel("v0.5.0"), rel("v0.6.0-rc.1", prerelease=True)])
    login(api)
    s = api.get("/api/updates").json()
    assert s["canal"] == "stable" and s["prerelease"] is False and s["ultima"] == "0.5.0"
    r = api.put("/api/updates", json={"channel": "beta"})            # parcial: no toca «enabled»
    assert r.status_code == 200
    j = r.json()
    assert j["canal"] == "beta" and j["habilitado"] is True and j["ultima"] == "0.6.0-rc.1" and j["prerelease"] is True
    r = api.put("/api/updates", json={"enabled": False})              # parcial: no toca «channel»
    assert r.json()["canal"] == "beta" and r.json()["habilitado"] is False
    r = api.put("/api/updates", json={"enabled": True, "channel": "stable"})
    assert r.json()["canal"] == "stable" and r.json()["habilitado"] is True and r.json()["prerelease"] is False


def test_put_validation_is_atomic(api):
    login(api)
    for body in ({"channel": "nightly"}, {"channel": 3}, {"channel": None}, {}, {"enabled": "si", "channel": "beta"},
                 {"enabled": False, "channel": "x"}):
        r = api.put("/api/updates", json=body)
        assert r.status_code == 422, body
    s = api.get("/api/updates").json()
    assert s["canal"] == "stable" and s["habilitado"] is True     # nada se aplicó a medias



# ---- solo instalación nativa (en Docker, inactiva salvo forzado) ----
def _boom(*a, **k):
    raise AssertionError("no debe haber red")


def test_native_is_applicable(env):
    make, _, calls = env
    s = make([rel("v0.5.0")]).state()
    assert s["aplicable"] is True and s["hay_actualizacion"] is True and len(calls) == 1


def test_docker_not_forced_no_network_no_cache(env, monkeypatch, tmp_path):
    make, _, calls = env
    monkeypatch.setenv("CHECKPOINT_RUNTIME", "docker")
    monkeypatch.delenv("CHECKPOINT_UPDATE_CHECK", raising=False)
    monkeypatch.setattr(updates, "fetch_releases", _boom)
    c = make([rel("v0.5.0")])
    for refresh in (False, True):
        s = c.state(refresh=refresh)
        assert s["aplicable"] is False and s["error"] is None and s["hay_actualizacion"] is False
        assert s["habilitado"] is False and s["ultima"] is None and s["comprobado_en"] is None
    assert calls == [] and list(tmp_path.iterdir()) == []   # ni red ni caché escrita


def test_docker_explicit_zero_or_empty_is_not_forced(env, monkeypatch):
    make, _, calls = env
    monkeypatch.setenv("CHECKPOINT_RUNTIME", "docker")
    for v in ("0", "", "no", "off"):
        monkeypatch.setenv("CHECKPOINT_UPDATE_CHECK", v)
        assert make([rel("v0.5.0")]).state()["aplicable"] is False
    assert calls == []


def test_docker_forced_checks(env, monkeypatch):
    make, _, calls = env
    monkeypatch.setenv("CHECKPOINT_RUNTIME", "docker")
    monkeypatch.setenv("CHECKPOINT_UPDATE_CHECK", "1")
    s = make([rel("v0.5.0")]).state()
    assert s["aplicable"] is True and s["hay_actualizacion"] is True and len(calls) == 1


def test_update_check_forced_values():
    f = settings.update_check_forced
    assert f({}) is False and f({"CHECKPOINT_UPDATE_CHECK": ""}) is False
    assert f({"CHECKPOINT_UPDATE_CHECK": "0"}) is False
    assert all(f({"CHECKPOINT_UPDATE_CHECK": v}) for v in ("1", "true", "YES", "on"))


def test_endpoints_docker_not_forced(api, monkeypatch):
    monkeypatch.setenv("CHECKPOINT_RUNTIME", "docker")
    monkeypatch.delenv("CHECKPOINT_UPDATE_CHECK", raising=False)
    monkeypatch.setattr(updates, "fetch_releases", _boom)
    login(api)
    s = api.get("/api/updates").json()
    assert s["aplicable"] is False and s["error"] is None
    assert api.get("/api/updates?refresh=1").json()["aplicable"] is False
    r = api.put("/api/updates", json={"enabled": True})
    assert r.status_code == 409 and r.json()["aplicable"] is False
    assert api.put("/api/updates", json={"channel": "beta"}).status_code == 409
    assert api.get("/api/version").json() == {"version": "0.4.2"}   # la versión sigue disponible
    assert api.calls == [] and not (settings.DATA_DIR / "updates.json").exists()


def test_endpoints_docker_forced(api, monkeypatch):
    monkeypatch.setenv("CHECKPOINT_RUNTIME", "docker")
    monkeypatch.setenv("CHECKPOINT_UPDATE_CHECK", "1")
    login(api)
    s = api.get("/api/updates").json()
    assert s["aplicable"] is True and s["ultima"] == "0.5.0"
    assert api.put("/api/updates", json={"enabled": False}).json()["habilitado"] is False


def test_endpoints_native_has_aplicable(api):
    login(api)
    assert api.get("/api/updates").json()["aplicable"] is True
    assert api.put("/api/updates", json={"channel": "beta"}).status_code == 200
