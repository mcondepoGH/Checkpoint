"""API key de usuario: gestión desde el perfil (cookie), cifrado en reposo, secreto del hub y /api/hook/ping (Bearer)."""
import os
import stat

import pytest
from fastapi.testclient import TestClient

from app import apikey, avatar, settings
from app.auth import Auth
from app.main import create_app

PW = "correct horse"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "CONFIG_PATH", tmp_path / "config" / "config.yaml")
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(settings, "STATIC_DIR", tmp_path / "static")
    c = TestClient(create_app(Auth("admin", PW, 1, rounds=4)))
    c.tmp = tmp_path
    return c


@pytest.fixture
def logged(client):
    assert client.post("/api/login", json={"user": "admin", "password": PW}).status_code == 200
    return client


def bearer(key):
    return {"Authorization": f"Bearer {key}"}


def ping(c, headers=None):
    # Cliente aparte, sin la cookie de sesión que guarda el TestClient de la fixture.
    return TestClient(c.app).get("/api/hook/ping", headers=headers or {})


def enc_file(c):
    return c.tmp / "data" / "profile" / avatar.user_id("admin") / "apikey.enc"


# ---- gestión desde el perfil ----
def test_apikey_requires_session(client):
    for m in ("get", "post", "delete"):
        assert getattr(client, m)("/api/profile/apikey").status_code == 401, m


def test_get_without_key_does_not_generate(logged):
    r = logged.get("/api/profile/apikey")
    assert r.json() == {"exists": False, "key": None}
    assert not enc_file(logged).exists()


def test_generate_view_regenerate_revoke(logged):
    k1 = logged.post("/api/profile/apikey").json()
    assert k1["exists"] and apikey.is_well_formed(k1["key"]) and k1["key"].startswith("ck_") and len(k1["key"]) == 46
    assert logged.get("/api/profile/apikey").json() == k1  # se ve siempre
    k2 = logged.post("/api/profile/apikey").json()
    assert k2["key"] != k1["key"] and logged.get("/api/profile/apikey").json() == k2
    assert logged.delete("/api/profile/apikey").json() == {"exists": False, "key": None}
    assert logged.get("/api/profile/apikey").json() == {"exists": False, "key": None}
    assert logged.delete("/api/profile/apikey").status_code == 200  # idempotente


def test_responses_are_not_cacheable(logged):
    for r in (logged.get("/api/profile/apikey"), logged.post("/api/profile/apikey"), logged.delete("/api/profile/apikey")):
        assert r.headers["cache-control"] == "no-store"


def test_write_methods_check_origin(logged):
    for m in ("post", "delete"):
        r = getattr(logged, m)("/api/profile/apikey", headers={"Origin": "http://evil.example"})
        assert r.status_code == 403 and r.json()["detail"]["code"] == "err.main.origin_forbidden", m
    assert not enc_file(logged).exists()


# ---- cifrado en reposo y secreto ----
def test_file_is_encrypted_and_private(logged):
    key = logged.post("/api/profile/apikey").json()["key"]
    blob = enc_file(logged).read_bytes()
    assert key.encode() not in blob and key[3:].encode() not in blob
    assert stat.S_IMODE(enc_file(logged).stat().st_mode) == 0o600


def test_secret_outside_data_with_0600(logged):
    logged.post("/api/profile/apikey")
    sec = logged.tmp / "config" / "hub.secret"
    assert sec.is_file() and stat.S_IMODE(sec.stat().st_mode) == 0o600
    assert not str(sec).startswith(str(settings.DATA_DIR))
    assert not list(settings.DATA_DIR.rglob("hub.secret"))
    assert sec.read_bytes() not in enc_file(logged).read_bytes()


def test_secret_is_created_once_and_fixed_if_loose(logged):
    s1 = apikey.hub_secret()
    sec = apikey.secret_path()
    os.chmod(sec, 0o644)
    assert apikey.hub_secret() == s1 and stat.S_IMODE(sec.stat().st_mode) == 0o600


def test_not_decryptable_without_the_secret(logged):
    key = logged.post("/api/profile/apikey").json()["key"]
    blob = enc_file(logged).read_bytes()
    uid = avatar.user_id("admin")
    assert apikey.decrypt(blob, apikey.hub_secret(), uid) == key.encode()
    assert apikey.decrypt(blob, b"x" * 64, uid) is None
    apikey.secret_path().write_bytes(b"otro-secreto-distinto-" + b"0" * 40)  # backup de data/ + secreto distinto
    assert logged.get("/api/profile/apikey").json() == {"exists": False, "key": None}
    assert ping(logged, bearer(key)).status_code == 401


def test_tampered_or_foreign_file_is_rejected(logged):
    key = logged.post("/api/profile/apikey").json()["key"]
    p = enc_file(logged)
    good = p.read_bytes()
    p.write_bytes(good[:10] + bytes([good[10] ^ 1]) + good[11:])
    assert apikey.get("admin") is None
    p.write_bytes(good)
    assert apikey.get("admin") == key
    assert apikey.decrypt(good, apikey.hub_secret(), avatar.user_id("otro")) is None  # no vale en otra carpeta


def test_ciphertext_differs_each_time(logged):
    s = apikey.hub_secret()
    a, b = apikey.encrypt(b"x" * 46, s, "u"), apikey.encrypt(b"x" * 46, s, "u")
    assert a != b


@pytest.mark.parametrize("name", ["../../etc/passwd", "..", "a/b", "ñandú", "x\x00y", " ../ "])
def test_hostile_usernames_stay_inside_profile(tmp_path, monkeypatch, name):
    monkeypatch.setattr(settings, "CONFIG_PATH", tmp_path / "config" / "config.yaml")
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path / "data")
    key = apikey.create(name)
    assert apikey.get(name) == key
    files = [p for p in tmp_path.rglob("apikey.enc")]
    assert len(files) == 1
    base = (tmp_path / "data" / "profile").resolve()
    assert files[0].resolve().parent.parent == base and files[0].parent.name == avatar.user_id(name)
    assert apikey.revoke(name) and apikey.get(name) is None


def test_current_user_is_the_single_point(logged, monkeypatch):
    """La gestión de la key resuelve el usuario por `current_user`: sustituirlo cambia de qué usuario es la key."""
    import inspect
    from app import main
    src = inspect.getsource(main)
    assert "auth.user" in src and src.count("def current_user") == 1
    assert "Depends(current_user)" in src.split("def get_apikey")[1].split("\n")[0]
    key = logged.post("/api/profile/apikey").json()["key"]
    assert apikey.get("admin") == key and apikey.get("otro") is None


# ---- /api/hook/ping (Bearer) ----
def test_ping_with_valid_key(logged):
    key = logged.post("/api/profile/apikey").json()["key"]
    r = ping(logged, bearer(key))
    assert r.status_code == 200 and r.json() == {"ok": True, "user": "admin"}
    assert ping(logged, {"Authorization": f"bearer {key}"}).status_code == 200  # esquema sin distinguir mayúsculas


def test_ping_valid_key_ignores_origin(logged):
    key = logged.post("/api/profile/apikey").json()["key"]
    r = TestClient(logged.app).get("/api/hook/ping", headers={**bearer(key), "Origin": "http://otro.example"})
    assert r.status_code == 200


@pytest.mark.parametrize("hdr", [
    None, "", "Bearer", "Bearer ", "ck_abc", "Basic Zm9v", "Bearer ck_corta", "Bearer ck_" + "A" * 44,
    "Bearer ck_" + "A" * 42 + "!", "Token ck_" + "A" * 43, "Bearer x y",
])
def test_ping_missing_or_malformed(logged, hdr):
    logged.post("/api/profile/apikey")
    r = ping(logged, {"Authorization": hdr} if hdr is not None else {})
    assert r.status_code == 401 and r.json()["detail"]["code"] == "err.apikey.invalid"
    assert r.headers["www-authenticate"] == "Bearer"


def test_ping_wrong_key_and_no_key_are_indistinguishable(logged):
    wrong = bearer(apikey.new_key())
    r1 = ping(logged, wrong)  # aún sin key creada
    logged.post("/api/profile/apikey")
    r2 = ping(logged, wrong)  # con key creada, otra distinta
    assert r1.status_code == r2.status_code == 401 and r1.json() == r2.json()


def test_ping_regenerated_and_revoked(logged):
    k1 = logged.post("/api/profile/apikey").json()["key"]
    assert ping(logged, bearer(k1)).status_code == 200
    k2 = logged.post("/api/profile/apikey").json()["key"]
    assert ping(logged, bearer(k1)).status_code == 401
    assert ping(logged, bearer(k2)).status_code == 200
    logged.delete("/api/profile/apikey")
    assert ping(logged, bearer(k2)).status_code == 401


def test_session_cookie_does_not_work_on_ping(logged):
    assert logged.get("/api/hook/ping").status_code == 401  # el cliente lleva la cookie de sesión válida
    assert logged.get("/api/hook/ping", headers={"Authorization": "Bearer " + logged.cookies.get("checkpoint_session", "")}).status_code == 401


def test_key_does_not_open_other_routes(logged):
    key = logged.post("/api/profile/apikey").json()["key"]
    anon = TestClient(logged.app)
    h = bearer(key)
    for m, p in [("get", "/api/profile"), ("get", "/api/profile/apikey"), ("post", "/api/profile/apikey"),
                 ("get", "/api/config"), ("get", "/api/scheduler/history"), ("get", "/api/session")]:
        r = getattr(anon, m)(p, headers=h)
        assert r.status_code == 401 or (p == "/api/session" and r.json() == {"authenticated": False}), (m, p, r.status_code)


def test_hook_router_is_extensible_and_guarded(logged):
    """Cualquier ruta futura bajo /api/hook/* hereda la dependencia Bearer (también las desconocidas, nunca la SPA)."""
    r = TestClient(logged.app).get("/api/hook/nada")
    assert r.status_code in (401, 404) and "html" not in r.headers.get("content-type", "")


def test_rate_limit_per_ip_and_reset(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "CONFIG_PATH", tmp_path / "config" / "config.yaml")
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(settings, "STATIC_DIR", tmp_path / "static")
    clock = [1000.0]
    auth = Auth("admin", PW, 1, clock=lambda: clock[0], rounds=4)
    c = TestClient(create_app(auth))
    assert c.post("/api/login", json={"user": "admin", "password": PW}).status_code == 200
    key = c.post("/api/profile/apikey").json()["key"]
    anon = TestClient(c.app)
    bad = bearer(apikey.new_key())
    assert [anon.get("/api/hook/ping", headers=bad).status_code for _ in range(3)] == [401, 401, 401]
    r = anon.get("/api/hook/ping", headers=bearer(key))  # bloqueada: ni la key válida pasa mientras dura
    assert r.status_code == 429 and int(r.headers["retry-after"]) > 0
    assert r.json()["detail"]["code"] == "err.main.too_many_attempts"
    assert anon.post("/api/login", json={"user": "admin", "password": PW}).status_code == 200  # contador propio
    clock[0] += 3600
    assert anon.get("/api/hook/ping", headers=bearer(key)).status_code == 200
    assert auth.hook_fails == {}  # el acierto limpia el contador


def test_compare_digest_is_used(logged, monkeypatch):
    key = logged.post("/api/profile/apikey").json()["key"]
    calls = []
    real = apikey.hmac.compare_digest
    monkeypatch.setattr(apikey.hmac, "compare_digest", lambda a, b: calls.append(1) or real(a, b))
    assert ping(logged, bearer(key)).status_code == 200
    assert calls
    calls.clear()
    assert ping(logged, bearer(apikey.new_key())).status_code == 401
    assert calls  # también con key equivocada
    calls.clear()
    assert ping(logged, {"Authorization": "Bearer nope"}).status_code == 401
    assert calls  # y con entrada mal formada (mismo trabajo)


def test_key_format():
    ks = {apikey.new_key() for _ in range(50)}
    assert len(ks) == 50 and all(apikey.is_well_formed(k) for k in ks)
    assert not apikey.is_well_formed("ck_" + "A" * 42) and not apikey.is_well_formed(None)
