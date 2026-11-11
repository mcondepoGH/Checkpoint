"""API key de usuario: gestión desde el perfil (cookie), cifrado en reposo, secreto del hub y /api/hook/ping (Bearer)."""
import os
import stat

import pytest
from fastapi.testclient import TestClient

from app.users import apikey, avatar
from app.core import settings
from app.api.auth import Auth
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
    assert blob.startswith(b"gAAAA")  # token Fernet
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
    from app.api import deps
    src = inspect.getsource(deps)
    assert "auth.user" in src and src.count("def current_user") == 1
    assert "Depends(current_user)" in inspect.getsource(main).split("def get_apikey")[1].split("\n")[0]
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


def test_user_id_is_bound_inside_the_payload(logged):
    key = logged.post("/api/profile/apikey").json()["key"]
    blob = enc_file(logged).read_bytes()
    uid = avatar.user_id("admin")
    # un token válido del mismo secreto pero con otro id dentro no vale para este usuario
    forged = apikey.encrypt(key.encode(), apikey.hub_secret(), avatar.user_id("otro"))
    assert apikey.decrypt(forged, apikey.hub_secret(), uid) is None
    enc_file(logged).write_bytes(forged)
    assert apikey.get("admin") is None
    enc_file(logged).write_bytes(blob)
    assert apikey.get("admin") == key


def test_garbage_files_give_no_key(logged):
    logged.post("/api/profile/apikey")
    for junk in (b"", b"gAAAA", b"\x00" * 200, b"CK1" + b"\x01" * 100):
        enc_file(logged).write_bytes(junk)
        assert logged.get("/api/profile/apikey").json() == {"exists": False, "key": None}


def _limited(tmp_path, monkeypatch, trust=False):
    monkeypatch.setattr(settings, "CONFIG_PATH", tmp_path / "config" / "config.yaml")
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(settings, "STATIC_DIR", tmp_path / "static")
    monkeypatch.setattr(settings, "TRUST_PROXY", trust)
    clock = [1000.0]
    auth = Auth("admin", PW, 1, clock=lambda: clock[0], rounds=4)
    c = TestClient(create_app(auth))
    assert c.post("/api/login", json={"user": "admin", "password": PW}).status_code == 200
    key = c.post("/api/profile/apikey").json()["key"]
    return TestClient(c.app), auth, clock, key


def xff(ip, **h):
    return {"X-Forwarded-For": ip, **h}


def test_rate_limit_schedule_and_no_escalation_while_blocked():
    """3 fallos gratis; el 3.º bloquea 5 s, el 4.º 10 s, el 5.º 20 s... (máx. 900 s). Bloqueado no suma fallos."""
    clock = [0.0]
    a = Auth("admin", PW, 1, clock=lambda: clock[0], rounds=4)
    waits = []
    for _ in range(6):
        a.hook_fail("1.2.3.4")
        waits.append(a.hook_wait("1.2.3.4"))
        clock[0] += waits[-1]
    assert waits == [0, 0, 5, 10, 20, 40]
    for _ in range(20):
        a.hook_fail("1.2.3.4")
        top = a.hook_wait("1.2.3.4")
        clock[0] += top
    assert top == 900  # tope de 15 min


def test_rate_limit_blocked_requests_do_not_escalate(tmp_path, monkeypatch):
    anon, auth, clock, key = _limited(tmp_path, monkeypatch)
    for _ in range(3):
        assert anon.get("/api/hook/ping", headers=bearer(apikey.new_key())).status_code == 401
    n = auth.hook_fails["testclient"][0]
    for _ in range(5):  # mientras dura el bloqueo, 429 sin sumar fallos (ni con key mala ni con la buena)
        assert anon.get("/api/hook/ping", headers=bearer(apikey.new_key())).status_code == 429
        assert anon.get("/api/hook/ping", headers=bearer(key)).status_code == 429
    assert auth.hook_fails["testclient"][0] == n


def test_rate_limit_is_per_ip_and_ignores_xff_without_proxy(tmp_path, monkeypatch):
    anon, auth, clock, key = _limited(tmp_path, monkeypatch, trust=False)
    for _ in range(3):  # sin TRUST_PROXY el X-Forwarded-For se ignora: no se puede evadir ni acusar a otra IP
        anon.get("/api/hook/ping", headers=xff(f"9.9.9.{_}", **bearer(apikey.new_key())))
    assert list(auth.hook_fails) == ["testclient"]
    assert anon.get("/api/hook/ping", headers=xff("8.8.8.8", **bearer(key))).status_code == 429


def test_rate_limit_with_trust_proxy_uses_last_xff_entry(tmp_path, monkeypatch):
    """Tras un proxy de confianza cuenta la IP que añadió el proxy (última entrada): lo que ponga el cliente delante no sirve."""
    anon, auth, clock, key = _limited(tmp_path, monkeypatch, trust=True)
    for i in range(3):
        anon.get("/api/hook/ping", headers=xff(f"6.6.6.{i}, 10.0.0.5", **bearer(apikey.new_key())))
    assert list(auth.hook_fails) == ["10.0.0.5"]
    assert anon.get("/api/hook/ping", headers=xff("1.1.1.1, 10.0.0.5", **bearer(key))).status_code == 429
    assert anon.get("/api/hook/ping", headers=xff("1.1.1.1, 10.0.0.6", **bearer(key))).status_code == 200  # otro cliente tras el proxy


def test_rate_limit_shared_ip_behind_proxy_without_trust(tmp_path, monkeypatch):
    """Sin TRUST_PROXY tras un proxy, todos los clientes comparten IP: uno que falla bloquea a los demás (se documenta)."""
    anon, auth, clock, key = _limited(tmp_path, monkeypatch, trust=False)
    for _ in range(3):
        anon.get("/api/hook/ping", headers=xff("10.0.0.7", **bearer(apikey.new_key())))
    assert anon.get("/api/hook/ping", headers=xff("10.0.0.8", **bearer(key))).status_code == 429


def test_rate_limit_old_failures_are_forgotten():
    clock = [0.0]
    a = Auth("admin", PW, 1, clock=lambda: clock[0], rounds=4)
    a.hook_fail("1.1.1.1")
    a.hook_fail("2.2.2.2")
    clock[0] += 4000
    a.hook_fail("3.3.3.3")
    assert list(a.hook_fails) == ["3.3.3.3"]  # el mapa no crece sin fin
    a.hook_fail("3.3.3.3")
    a.hook_fail("3.3.3.3")
    clock[0] += 1
    assert a.hook_wait("3.3.3.3") > 0


# ---- flujo HTTP completo del límite de frecuencia (reloj simulado, sin esperas reales) ----
def _ping(anon, key, **h):
    return anon.get("/api/hook/ping", headers={**bearer(key), **h})


def test_rate_limit_http_flow_escalation_block_and_reset(tmp_path, monkeypatch):
    """Falsa: 401, 401, 401 (el 3.º ya bloquea 5 s) y luego 429 con Retry-After 5. Bloqueado, ni la key válida pasa y esos
    intentos no escalan. Pasado el tiempo, la falsa vuelve a dar 401 y la espera sube a 10 s; la válida da 200 y reinicia."""
    anon, auth, clock, key = _limited(tmp_path, monkeypatch)
    bad = apikey.new_key()
    assert [_ping(anon, bad).status_code for _ in range(3)] == [401, 401, 401]
    r = _ping(anon, bad)
    assert r.status_code == 429 and r.headers["retry-after"] == "5" and r.json()["detail"]["params"] == {"seconds": 5}
    assert r.json()["detail"]["code"] == "err.main.too_many_attempts"
    for _ in range(4):  # bloqueada: falsa y válida reciben 429 y no suman fallos ni alargan el bloqueo
        assert _ping(anon, bad).status_code == 429
        assert _ping(anon, key).status_code == 429
    assert auth.hook_fails["testclient"] == (3, 1005.0)
    clock[0] += 2
    assert _ping(anon, key).headers["retry-after"] == "3"  # la cuenta atrás avanza con el reloj, sin reiniciarse
    clock[0] += 3  # fin del bloqueo de 5 s
    assert _ping(anon, bad).status_code == 401  # 4.º fallo: escala a 10 s
    r = _ping(anon, bad)
    assert r.status_code == 429 and r.headers["retry-after"] == "10"
    clock[0] += 10
    ok = _ping(anon, key)
    assert ok.status_code == 200 and ok.json()["ok"] is True
    assert auth.hook_fails == {}  # el acierto reinicia el contador
    assert [_ping(anon, bad).status_code for _ in range(3)] == [401, 401, 401]  # vuelve a empezar en 5 s
    assert _ping(anon, bad).headers["retry-after"] == "5"


def test_rate_limit_http_other_ip_is_not_blocked_without_proxy(tmp_path, monkeypatch):
    """Sin proxy cuenta la IP del socket: otro cliente (otra IP) no se ve afectado por el bloqueo del primero."""
    anon, auth, clock, key = _limited(tmp_path, monkeypatch, trust=False)
    other = TestClient(anon.app, client=("203.0.113.9", 50000))
    for _ in range(3):
        _ping(anon, apikey.new_key())
    assert _ping(anon, key).status_code == 429
    assert _ping(other, key).status_code == 200
    assert set(auth.hook_fails) == {"testclient"}


def test_rate_limit_http_forget_inactive_ips_after_one_hour(tmp_path, monkeypatch):
    """Los fallos de una IP sin actividad desde 1 h tras acabar su bloqueo se olvidan (FAIL_FORGET) al registrar otro fallo."""
    from app.api import auth as auth_mod
    anon, auth, clock, key = _limited(tmp_path, monkeypatch, trust=True)
    for _ in range(3):
        _ping(anon, apikey.new_key(), **xff("10.0.0.5"))
    assert _ping(anon, key, **xff("10.0.0.5")).status_code == 429
    clock[0] += 5 + auth_mod.FAIL_FORGET - 1  # aún dentro de la hora: no se olvida
    assert _ping(anon, apikey.new_key(), **xff("10.0.0.6")).status_code == 401
    assert set(auth.hook_fails) == {"10.0.0.5", "10.0.0.6"}
    clock[0] += 2  # pasada la hora desde el fin del bloqueo
    assert _ping(anon, apikey.new_key(), **xff("10.0.0.6")).status_code == 401
    assert set(auth.hook_fails) == {"10.0.0.6"}  # 10.0.0.5 olvidada
    assert [_ping(anon, apikey.new_key(), **xff("10.0.0.5")).status_code for _ in range(2)] == [401, 401]
    assert _ping(anon, key, **xff("10.0.0.5")).status_code == 200  # vuelve a empezar de cero, sin bloqueo


def test_rate_limit_login_and_hook_counters_are_separate(tmp_path, monkeypatch):
    anon, auth, clock, key = _limited(tmp_path, monkeypatch)
    for _ in range(3):  # login bloqueado por fallos de login...
        assert anon.post("/api/login", json={"user": "admin", "password": "mala"}).status_code == 401
    assert anon.post("/api/login", json={"user": "admin", "password": PW}).status_code == 429
    assert _ping(anon, key).status_code == 200  # ...no bloquea los hooks
    assert auth.fails["testclient"][0] == 3 and auth.hook_fails == {}
    for _ in range(3):  # y al revés: hooks bloqueados, el contador de login no se mueve
        _ping(anon, apikey.new_key())
    assert _ping(anon, key).status_code == 429
    assert auth.hook_fails["testclient"][0] == 3 and auth.fails["testclient"][0] == 3
    clock[0] += 5
    assert anon.post("/api/login", json={"user": "admin", "password": PW}).status_code == 200  # login libre; tras 5 s
