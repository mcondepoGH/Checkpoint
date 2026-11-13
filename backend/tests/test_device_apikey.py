"""API key POR DISPOSITIVO http: formato y almacén, gestión por sesión (`/api/devices/{id}/apikey`), qué key acepta cada
endpoint de /api/hook/* y de /api/games, alcance a los juegos del dispositivo, ciclo de vida con la config y secretos."""

import copy
import logging

import pytest
import yaml
from fastapi.testclient import TestClient

from app.api.auth import Auth
from app.core import settings
from app.main import create_app
from app.users import apikey
from test_hook_fingerprint import PW, Env, code

CFG = {
    "devices": {
        "deck": {"name": "Steam Deck", "http": True, "os": "linux"},
        "lap": {"name": "Portátil", "http": True, "os": "linux"},
        "pc": {"name": "PC", "host": "192.0.2.10", "user": "u", "os": "linux"},
        "pc2": {"name": "PC dos", "host": "192.0.2.12", "user": "u", "os": "linux"},
    },
    "games": {
        "g1": {"name": "Mi Juego", "devices": ["deck", "pc"], "paths": {"deck": "/d", "pc": "/p"}},
        "g2": {"name": "Solo Portátil", "devices": ["lap", "pc"], "paths": {"lap": "/l2", "pc": "/p2"}},
        "g3": {"name": "Solo PC", "devices": ["pc", "pc2"], "paths": {"pc": "/p3", "pc2": "/p4"}},
    },
}


@pytest.fixture
def cl(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "CONFIG_PATH", tmp_path / "config" / "config.yaml")
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(settings, "STATIC_DIR", tmp_path / "static")
    Env(tmp_path, copy.deepcopy(CFG))
    c = TestClient(create_app(Auth("admin", PW, 1, rounds=4)))
    assert c.post("/api/login", json={"user": "admin", "password": PW}).status_code == 200
    c.deck = c.post("/api/devices/deck/apikey").json()["key"]
    c.lap = c.post("/api/devices/lap/apikey").json()["key"]
    c.user = c.post("/api/profile/apikey").json()["key"]
    return c


def bearer(key):
    return {"Authorization": f"Bearer {key}"}


def anon(c):
    return TestClient(c.app)  # sin cookie de sesión


def call(c, key, method, path, **kw):
    return getattr(anon(c), method)(path, headers=bearer(key) if key else {}, **kw)


# (método, ruta, kwargs): los endpoints http nuevos
DEVICE_ONLY = [
    ("post", "/api/hook/g1/fingerprint", {"json": []}),
    ("get", "/api/hook/g1/manifest", {}),
    ("get", "/api/hook/g1/files?path=a.sav", {}),
    ("put", "/api/hook/g1/files?path=a.sav&size=1&sha256=" + "0" * 64, {"content": b"x"}),
    ("post", "/api/hook/g1/commit", {"json": {"expect": None, "manifest": []}}),
    ("post", "/api/hook/g1/closed", {}),
]
USER_ONLY = [("get", "/api/hook/watches", {}), ("post", "/api/hook/g1/opened?device=pc", {})]


# ---- formato y almacén ----
def test_format_distinguishes_the_two_kinds(cl):
    assert cl.deck.startswith("ckd_") and len(cl.deck) == 4 + 43
    assert apikey.is_well_formed_device(cl.deck) and not apikey.is_well_formed(cl.deck)
    assert apikey.is_well_formed(cl.user) and not apikey.is_well_formed_device(cl.user)
    assert cl.deck != cl.lap


def test_stored_encrypted_0600_outside_plain(cl, tmp_path):
    files = list((tmp_path / "data" / "profile").rglob("devices/*.enc"))
    assert sorted(f.stem for f in files) == ["deck", "lap"]
    for f in files:
        assert (f.stat().st_mode & 0o777) == 0o600
        assert cl.deck.encode() not in f.read_bytes() and cl.lap.encode() not in f.read_bytes()


def test_file_copied_to_another_device_does_not_decrypt(cl, tmp_path):
    d = next((tmp_path / "data" / "profile").rglob("devices"))
    (d / "pc.enc").write_bytes((d / "deck.enc").read_bytes())
    assert apikey.device_get("admin", "pc") is None


def test_device_id_must_be_a_safe_name():
    for bad in ("", "../x", "a/b", "a.b", "x" * 65):
        with pytest.raises(ValueError):
            apikey.device_get("admin", bad)


# ---- gestión por sesión ----
def test_manage_requires_session(cl):
    for m in ("get", "post", "delete"):
        r = getattr(anon(cl), m)("/api/devices/deck/apikey")
        assert r.status_code == 401 and code(r) == "err.main.session_required"
    r = call(cl, cl.deck, "get", "/api/devices/deck/apikey")  # la key de dispositivo no abre la gestión
    assert r.status_code == 401 and code(r) == "err.main.session_required"


def test_manage_lifecycle(cl):
    r = cl.get("/api/devices/deck/apikey")
    assert r.json() == {"exists": True, "key": cl.deck} and r.headers["cache-control"] == "no-store"
    old = cl.deck
    new = cl.post("/api/devices/deck/apikey").json()["key"]  # regenerar
    assert new != old and cl.get("/api/devices/deck/apikey").json()["key"] == new
    assert call(cl, old, "post", "/api/hook/g1/closed").status_code == 401  # la anterior ya no vale
    assert call(cl, new, "post", "/api/hook/g1/closed").status_code == 200
    assert cl.delete("/api/devices/deck/apikey").json() == {"exists": False, "key": None}
    assert cl.get("/api/devices/deck/apikey").json() == {"exists": False, "key": None}
    assert cl.delete("/api/devices/deck/apikey").status_code == 200  # idempotente
    assert call(cl, new, "post", "/api/hook/g1/closed").status_code == 401  # revocada
    assert call(cl, cl.lap, "post", "/api/hook/g2/closed").status_code == 200  # la del otro sigue


def test_manage_unknown_and_not_http(cl):
    for m in ("get", "post", "delete"):
        r = getattr(cl, m)("/api/devices/nope/apikey")
        assert r.status_code == 404 and code(r) == "err.hook.device_unknown"
        r = getattr(cl, m)("/api/devices/pc/apikey")
        assert r.status_code == 400 and code(r) == "err.hook.device_not_http"


def test_manage_csrf_origin(cl):
    r = cl.post("/api/devices/deck/apikey", headers={"Origin": "http://evil.example"})
    assert r.status_code == 403 and code(r) == "err.main.origin_forbidden"


# ---- qué key acepta cada endpoint ----
@pytest.mark.parametrize("method,path,kw", DEVICE_ONLY)
def test_device_endpoints_accept_only_device_key(cl, method, path, kw):
    assert call(cl, cl.deck, method, path, **kw).status_code != 401
    for bad in (cl.user, "ckd_" + "x" * 43, "ck_" + "x" * 43, "basura", None):
        cl.app.state.ctx.auth.hook_fails.clear()  # que el límite por IP no tape el 401
        r = call(cl, bad, method, path, **kw)
        assert r.status_code == 401 and code(r) == "err.apikey.invalid", (path, bad)
        assert r.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize("method,path,kw", USER_ONLY)
def test_user_endpoints_reject_device_key(cl, method, path, kw):
    assert call(cl, cl.user, method, path, **kw).status_code != 401
    r = call(cl, cl.deck, method, path, **kw)
    assert r.status_code == 401 and code(r) == "err.apikey.invalid"


def test_ping_and_games_accept_both(cl):
    assert call(cl, cl.user, "get", "/api/hook/ping").json() == {"ok": True, "user": "admin"}
    assert call(cl, cl.deck, "get", "/api/hook/ping").json() == {"ok": True, "user": "admin", "device": "deck"}
    for k in (cl.user, cl.deck):
        assert call(cl, k, "get", "/api/games").status_code == 200
    assert call(cl, None, "get", "/api/hook/ping").status_code == 401


def test_games_scope(cl):
    ids = lambda k: [g["id"] for g in call(cl, k, "get", "/api/games").json()]  # noqa: E731
    assert ids(cl.user) == ["g1", "g2", "g3"]  # key de usuario: todos
    assert ids(cl.deck) == ["g1"]
    assert ids(cl.lap) == ["g2"]


def test_every_hook_route_requires_a_key(cl):
    from app.api.docs import iter_api_routes

    paths = []
    for r in iter_api_routes(cl.app.routes):
        if r.path.startswith("/api/hook/") or r.path == "/api/games":
            path = r.path.replace("{game}", "g1")
            for m in r.methods - {"HEAD", "OPTIONS"}:
                paths.append((m.lower(), path))
    assert len(paths) >= 9
    for m, p in paths:
        for h in ({}, bearer("ck_" + "z" * 43), bearer("ckd_" + "z" * 43)):
            assert getattr(anon(cl), m)(p, headers=h).status_code in (401, 429), (m, p)


# ---- alcance: dispositivo y juego ----
def test_other_device_param_is_403(cl):
    for q in ("device=lap", "device=Portátil", "device=pc", "device=nope"):
        r = call(cl, cl.deck, "post", f"/api/hook/g1/closed?{q}")
        assert r.status_code == 403 and code(r) == "err.apikey.device_mismatch", q


def test_device_param_optional_and_matching_ok(cl):
    for q in ("", "?device=deck", "?device=Steam Deck", "?device=steam deck"):
        r = call(cl, cl.deck, "post", f"/api/hook/g1/closed{q}")
        assert r.status_code == 200 and r.json()["device"] == "deck", q


def test_game_without_the_device_is_404_like_unknown(cl):
    for g in ("g2", "g3", "nope"):  # g2 existe pero no incluye deck; g3 tampoco
        for method, path, kw in DEVICE_ONLY:
            r = call(cl, cl.deck, method, path.replace("/g1/", f"/{g}/"), **kw)
            assert r.status_code == 404 and code(r) == "err.main.game_unknown", (g, path)
    assert call(cl, cl.lap, "post", "/api/hook/g2/closed").status_code == 200
    assert call(cl, cl.lap, "post", "/api/hook/Solo Portátil/closed").json()["device"] == "lap"
    r = call(cl, cl.lap, "post", "/api/hook/g1/closed")  # la key de OTRO dispositivo en un juego que no es suyo
    assert r.status_code == 404 and code(r) == "err.main.game_unknown"


def test_device_key_works_in_its_own_flow(cl):
    fp = call(cl, cl.deck, "post", "/api/hook/g1/fingerprint", json=[])
    assert fp.status_code == 200 and fp.json()["device"] == "deck"
    assert call(cl, cl.deck, "get", "/api/hook/g1/manifest").json()["device"] == "deck"


# ---- ciclo de vida con la config ----
def put_cfg(c, mutate):
    got = c.get("/api/config").json()
    cfg = copy.deepcopy(got["config"])
    mutate(cfg)
    r = c.put("/api/config", json={"config": cfg, "base_version": got["version"]})
    assert r.status_code == 200, r.text


def key_files(tmp_path):
    return sorted(f.stem for f in (tmp_path / "data" / "profile").rglob("devices/*.enc"))


def test_deleting_device_deletes_its_key(cl, tmp_path):
    def rm(cfg):
        cfg["devices"].pop("lap")
        cfg["games"].pop("g2")

    put_cfg(cl, rm)
    assert key_files(tmp_path) == ["deck"]
    assert call(cl, cl.lap, "post", "/api/hook/g2/closed").status_code == 401
    assert call(cl, cl.deck, "post", "/api/hook/g1/closed").status_code == 200


def test_recreated_device_with_same_id_does_not_revive_old_key(cl, tmp_path):
    def rm(cfg):
        cfg["devices"].pop("lap")
        cfg["games"].pop("g2")

    put_cfg(cl, rm)
    put_cfg(cl, lambda cfg: cfg["devices"].update(lap={"name": "Otro", "http": True, "os": "linux"}))
    assert cl.get("/api/devices/lap/apikey").json() == {"exists": False, "key": None}
    assert call(cl, cl.lap, "get", "/api/hook/ping").status_code == 401


def test_dropping_http_flag_deletes_key(cl, tmp_path):
    def host(cfg):
        cfg["devices"]["lap"] = {"name": "Portátil", "host": "192.0.2.11", "user": "u", "os": "linux"}

    put_cfg(cl, host)
    assert key_files(tmp_path) == ["deck"]
    assert call(cl, cl.lap, "get", "/api/hook/ping").status_code == 401


def test_rename_keeps_key(cl, tmp_path):
    put_cfg(cl, lambda cfg: cfg["devices"]["deck"].update(name="Deck del salón"))
    assert key_files(tmp_path) == ["deck", "lap"]
    r = call(cl, cl.deck, "post", "/api/hook/g1/closed?device=Deck del salón")
    assert r.status_code == 200 and r.json()["device"] == "deck"
    assert call(cl, cl.deck, "post", "/api/hook/g1/closed?device=Steam Deck").status_code == 403  # nombre viejo


def test_device_key_dies_with_config_even_if_file_remains(cl, tmp_path):
    """Config editada a mano (sin pasar por la API): el fichero sobrevive, pero no autentica a un dispositivo que ya
    no es `http`; y el arranque lo limpia."""
    path = tmp_path / "config" / "config.yaml"
    data = yaml.safe_load(path.read_text())
    data["devices"]["lap"] = {"name": "Portátil", "host": "192.0.2.11", "user": "u", "os": "linux"}
    path.write_text(yaml.safe_dump(data, allow_unicode=True))
    assert call(cl, cl.lap, "get", "/api/hook/ping").status_code == 401
    assert "lap" in key_files(tmp_path)
    with TestClient(create_app(Auth("admin", PW, 1, rounds=4))):  # arranque: lifespan
        pass
    assert key_files(tmp_path) == ["deck"]


# ---- límite de intentos, tiempo constante, secretos ----
def test_rate_limit_shared_with_user_key(cl):
    for _ in range(3):
        assert call(cl, "ckd_" + "x" * 43, "get", "/api/hook/ping").status_code == 401
    r = call(cl, cl.deck, "get", "/api/hook/ping")  # bloqueada incluso con una key válida
    assert r.status_code == 429 and int(r.headers["retry-after"]) > 0
    assert call(cl, cl.user, "get", "/api/hook/ping").status_code == 429


def test_wrong_kind_counts_as_failure(cl):
    for _ in range(3):
        assert call(cl, cl.user, "post", "/api/hook/g1/closed").status_code == 401
    assert call(cl, cl.deck, "post", "/api/hook/g1/closed").status_code == 429


def test_mismatch_and_404_do_not_count_as_auth_failures(cl):
    for _ in range(5):
        call(cl, cl.deck, "post", "/api/hook/g1/closed?device=lap")
        call(cl, cl.deck, "post", "/api/hook/g2/closed")
    assert call(cl, cl.deck, "post", "/api/hook/g1/closed").status_code == 200


def test_constant_time_compare_runs_for_every_http_device(cl, monkeypatch):
    calls = []
    real = apikey._same  # la comparación en tiempo constante (hmac.compare_digest) de una key con la guardada
    monkeypatch.setattr(apikey, "_same", lambda *a: calls.append(1) or real(*a))
    for key in (cl.deck, cl.lap, "ckd_" + "x" * 43):  # acierta (1.º), acierta (último), falla
        calls.clear()
        cl.app.state.ctx.auth.hook_fails.clear()
        call(cl, key, "get", "/api/hook/ping")
        assert len(calls) == 2, key  # una comparación por dispositivo http (deck, lap), sin salida temprana
    assert "compare_digest" in __import__("inspect").getsource(real)


def test_keys_never_leak_to_logs_or_errors(cl, caplog):
    caplog.set_level(logging.DEBUG)
    bad = "ckd_" + "q" * 43
    rs = [
        call(cl, bad, "get", "/api/hook/ping"),
        call(cl, cl.user, "post", "/api/hook/g1/closed"),
        call(cl, cl.deck, "post", "/api/hook/g1/closed?device=lap"),
        call(cl, cl.deck, "post", "/api/hook/g2/closed"),
        call(cl, cl.deck, "post", "/api/hook/g1/closed"),
    ]
    cl.get("/api/devices/deck/apikey")
    cl.post("/api/devices/deck/apikey")
    text = caplog.text + "".join(r.text for r in rs[:4])
    for secret in (bad, cl.deck, cl.lap, cl.user):
        assert secret not in text
    assert "Bearer" not in caplog.text


# ---- config.yaml inválido: no se revela a quien no está autenticado ----
def break_cfg(tmp_path):
    (tmp_path / "config" / "config.yaml").write_text("devices: [")


@pytest.mark.parametrize("path", ["/api/hook/ping", "/api/games", "/api/hook/g1/manifest"])
def test_invalid_config_device_key_is_plain_401(cl, tmp_path, caplog, path):
    """Con config inválida una key `ckd_` bien formada da el mismo 401 que una inválida (no el 500 de la config) y el
    error real queda en el log del hub, sin la key."""
    break_cfg(tmp_path)
    with caplog.at_level(logging.WARNING, logger="checkpoint"):
        r = call(cl, cl.deck, "get", path)
    assert r.status_code == 401 and code(r) == "err.apikey.invalid"
    assert r.headers["www-authenticate"] == "Bearer"
    assert "config" in caplog.text and cl.deck not in caplog.text
    same = call(cl, "ckd_" + "x" * 43, "get", path)
    assert (same.status_code, same.json()) == (r.status_code, r.json())


def test_invalid_config_device_key_counts_as_hook_fail(cl, tmp_path):
    break_cfg(tmp_path)
    for _ in range(3):
        assert call(cl, cl.deck, "get", "/api/hook/ping").status_code == 401
    r = call(cl, cl.deck, "get", "/api/hook/ping")
    assert r.status_code == 429 and int(r.headers["retry-after"]) > 0


def test_invalid_config_user_key_unchanged(cl, tmp_path):
    """La key de usuario no lee la config para autenticar: ping sigue 200."""
    break_cfg(tmp_path)
    assert call(cl, cl.user, "get", "/api/hook/ping").status_code == 200
