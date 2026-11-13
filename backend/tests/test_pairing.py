"""Vinculación de dispositivos por solicitud y código: endpoint público (`POST /api/pairing/requests`), consulta con el
secreto de la solicitud, y listar/aceptar/rechazar con sesión. Solicitudes en memoria, reloj controlable."""

import copy
import logging
import re

import pytest
import yaml
from fastapi.testclient import TestClient

from app.api.auth import Auth
from app.config.models import validate_config
from app.core import settings
from app.main import create_app
from app.services import pairing
from app.users import apikey
from test_hook_fingerprint import PW, Env

CFG = {
    "devices": {
        "pc": {"name": "PC", "host": "192.0.2.10", "user": "u", "os": "linux"},
        "deck": {"name": "Steam Deck", "http": True, "os": "linux"},
    },
    "games": {"g1": {"name": "Mi Juego", "devices": ["deck", "pc"], "paths": {"deck": "/d", "pc": "/p"}}},
}
PAIRING_HDR = "X-Pairing-Secret"


class Hub:
    pass


@pytest.fixture
def hub(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "CONFIG_PATH", tmp_path / "config" / "config.yaml")
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(settings, "STATIC_DIR", tmp_path / "static")
    Env(tmp_path, copy.deepcopy(CFG))
    h = Hub()
    h.tmp = tmp_path
    h.clock = [1000.0]
    h.auth = Auth("admin", PW, 1, clock=lambda: h.clock[0], rounds=4)
    h.app = create_app(h.auth)
    h.session = TestClient(h.app)
    assert h.session.post("/api/login", json={"user": "admin", "password": PW}).status_code == 200
    h.anon = TestClient(h.app)  # sin cookie: el dispositivo
    return h


def ask(hub, name="Deck nueva", os_="linux", client=None, **kw):
    return (client or hub.anon).post("/api/pairing/requests", json={"name": name, "os": os_}, **kw)


def poll(hub, req, secret=None, client=None):
    s = req["secret"] if secret is None else secret
    return (client or hub.anon).get(f"/api/pairing/requests/{req['id']}", headers={PAIRING_HDR: s})


def code(r):
    return r.json()["detail"]["code"]


def accept(hub, req, c=None, **kw):
    body = {"code": req["code"]} if c is None else {"code": c}
    return hub.session.post(f"/api/pairing/pending/{req['id']}/accept", json=body, **kw)


def new(hub, **kw):
    r = ask(hub, **kw)
    assert r.status_code == 201, r.text
    return r.json()


# ---- crear solicitud (público) ----
def test_request_ok_shape_and_no_store(hub):
    r = ask(hub)
    assert r.status_code == 201
    assert r.headers["cache-control"] == "no-store"
    j = r.json()
    assert set(j) == {"id", "code", "secret", "expires_in"}
    assert re.fullmatch(r"\d{6}", j["code"])
    assert len(j["secret"]) >= 43  # >= 32 bytes en base64 urlsafe
    assert j["secret"] != j["id"] and j["expires_in"] == 600


def test_request_needs_no_session_nor_key_but_is_not_in_the_session_only_list(hub):
    assert ask(hub).status_code == 201  # `anon` no tiene cookie ni key


def test_codes_and_secrets_differ_and_use_secrets_module(hub, monkeypatch):
    a, b = new(hub, name="A"), new(hub, name="B")
    assert a["secret"] != b["secret"] and a["id"] != b["id"] and a["code"] != b["code"]
    calls = []
    real = pairing.secrets.randbelow
    monkeypatch.setattr(pairing.secrets, "randbelow", lambda n: calls.append(n) or real(n))
    new(hub, name="C")
    assert calls == [1_000_000]


@pytest.mark.parametrize(
    "body",
    [
        {"name": "", "os": "linux"},
        {"name": "  x", "os": "linux"},
        {"name": "x" * 65, "os": "linux"},
        {"name": "a/b", "os": "linux"},
        {"name": "a\x00b", "os": "linux"},
        {"name": "...", "os": "linux"},
        {"name": 5, "os": "linux"},
        {"os": "linux"},
    ],
)
def test_invalid_name_is_400(hub, body):
    r = hub.anon.post("/api/pairing/requests", json=body)
    assert r.status_code == 400 and code(r) == "err.pairing.name_invalid"
    assert "code" in r.json()["detail"]["params"]["cause"]


@pytest.mark.parametrize("os_", ["macos", "", None, 3, "LINUX"])
def test_invalid_os_is_400(hub, os_):
    r = hub.anon.post("/api/pairing/requests", json={"name": "Deck", "os": os_})
    assert r.status_code == 400 and code(r) == "err.pairing.os_invalid"


def test_body_must_be_json_object_and_small(hub):
    r = hub.anon.post("/api/pairing/requests", content=b"no json")
    assert r.status_code == 400 and code(r) == "err.main.json_body_required"
    r = hub.anon.post("/api/pairing/requests", json=["x"])
    assert r.status_code == 400 and code(r) == "err.main.json_body_required"
    r = hub.anon.post("/api/pairing/requests", json={"name": "x", "os": "linux", "pad": "y" * 5000})
    assert r.status_code == 413 and code(r) == "err.pairing.body_too_large"


def test_no_pending_listed_for_failed_request(hub):
    hub.anon.post("/api/pairing/requests", json={"name": "", "os": "linux"})
    assert hub.session.get("/api/pairing/pending").json() == []


# ---- límites del endpoint público ----
def test_per_ip_request_rate_limit(hub, monkeypatch):
    monkeypatch.setattr(pairing, "MAX_PENDING_PER_IP", 100)
    monkeypatch.setattr(pairing, "MAX_PENDING", 100)
    for i in range(pairing.MAX_REQUESTS_PER_IP):
        assert ask(hub, name=f"D{i}").status_code == 201
    r = ask(hub, name="otra")
    assert r.status_code == 429 and code(r) == "err.pairing.too_many_requests"
    assert int(r.headers["retry-after"]) > 0 and r.json()["detail"]["params"]["seconds"] > 0
    hub.clock[0] += pairing.WINDOW_S + 1  # pasada la ventana, vuelve a admitir
    assert ask(hub, name="otra").status_code == 201


def test_pending_cap_per_ip(hub, monkeypatch):
    monkeypatch.setattr(pairing, "MAX_REQUESTS_PER_IP", 100)
    for i in range(pairing.MAX_PENDING_PER_IP):
        new(hub, name=f"D{i}")
    r = ask(hub, name="otra")
    assert r.status_code == 429 and code(r) == "err.pairing.too_many_pending"


def test_pending_cap_per_hub_is_503(hub, monkeypatch):
    monkeypatch.setattr(settings, "TRUST_PROXY", True)
    for i in range(pairing.MAX_PENDING):
        assert ask(hub, name=f"D{i}", headers={"X-Forwarded-For": f"10.0.0.{i}"}).status_code == 201
    r = ask(hub, name="otra", headers={"X-Forwarded-For": "10.0.1.1"})
    assert r.status_code == 503 and code(r) == "err.pairing.busy" and int(r.headers["retry-after"]) > 0


def test_expired_requests_free_their_slot(hub, monkeypatch):
    monkeypatch.setattr(pairing, "MAX_REQUESTS_PER_IP", 100)
    for i in range(pairing.MAX_PENDING_PER_IP):
        new(hub, name=f"D{i}")
    hub.clock[0] += 601
    assert ask(hub, name="otra").status_code == 201


def test_blocked_ip_gets_429_on_public_endpoints(hub):
    req = new(hub)
    for _ in range(3):
        assert poll(hub, req, secret="x" * 43).status_code == 404
    r = poll(hub, req)  # ni el secreto bueno pasa mientras dura el bloqueo
    assert r.status_code == 429 and code(r) == "err.main.too_many_attempts" and int(r.headers["retry-after"]) > 0
    assert ask(hub, name="otra").status_code == 429


# ---- caducidad ----
def test_expires_after_10_minutes(hub):
    req = new(hub)
    hub.clock[0] += 599
    assert poll(hub, req).json()["status"] == "pending"
    assert len(hub.session.get("/api/pairing/pending").json()) == 1
    hub.clock[0] += 2
    r = poll(hub, req)
    assert r.status_code == 404 and code(r) == "err.pairing.request_unknown"
    assert hub.session.get("/api/pairing/pending").json() == []
    assert accept(hub, req).status_code == 404


def test_expired_cannot_be_accepted(hub):
    req = new(hub)
    hub.clock[0] += 601
    r = accept(hub, req)
    assert r.status_code == 404 and code(r) == "err.pairing.request_unknown"
    assert sorted(yaml.safe_load((hub.tmp / "config" / "config.yaml").read_text())["devices"]) == ["deck", "pc"]


def test_scheduler_maintenance_purges_expired(hub):
    new(hub)
    hub.clock[0] += 601
    assert hub.app.state.ctx.pairing.purge in hub.app.state.ctx.scheduler.maintenance
    hub.app.state.ctx.pairing.purge()
    assert hub.app.state.ctx.pairing.count() == 0


# ---- listar / aceptar / rechazar: solo con sesión ----
def test_session_endpoints_need_session(hub):
    req = new(hub)
    for method, path, kw in [
        ("get", "/api/pairing/pending", {}),
        ("post", f"/api/pairing/pending/{req['id']}/accept", {"json": {"code": req["code"]}}),
        ("post", f"/api/pairing/pending/{req['id']}/reject", {}),
    ]:
        r = getattr(hub.anon, method)(path, **kw)
        assert r.status_code == 401 and code(r) == "err.main.session_required", path
    # una key no sustituye a la sesión
    key = hub.session.post("/api/profile/apikey").json()["key"]
    r = hub.anon.get("/api/pairing/pending", headers={"Authorization": f"Bearer {key}"})
    assert r.status_code == 401
    assert hub.session.get("/api/pairing/pending").json()  # sigue pendiente


def test_session_writes_check_origin(hub):
    req = new(hub)
    bad = {"Origin": "http://evil.example"}
    r = hub.session.post(f"/api/pairing/pending/{req['id']}/accept", json={"code": req["code"]}, headers=bad)
    assert r.status_code == 403 and code(r) == "err.main.origin_forbidden"
    assert hub.session.post(f"/api/pairing/pending/{req['id']}/reject", headers=bad).status_code == 403
    assert len(hub.session.get("/api/pairing/pending").json()) == 1


def test_list_pending_shape_no_secret_no_store(hub):
    req = new(hub, name="Deck uno", os_="windows")
    r = hub.session.get("/api/pairing/pending")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    (item,) = r.json()
    assert set(item) == {"id", "name", "os", "code", "ip", "expires_in", "existing"}
    assert item["id"] == req["id"] and item["name"] == "Deck uno" and item["os"] == "windows"
    assert item["code"] == req["code"] and item["existing"] == "none" and 0 < item["expires_in"] <= 600
    assert req["secret"] not in r.text


def test_list_flags_existing_device(hub):
    new(hub, name="steam deck")  # mismo nombre que un http existente (sin distinguir mayúsculas)
    new(hub, name="PC")  # existente no-http
    items = {i["name"]: i["existing"] for i in hub.session.get("/api/pairing/pending").json()}
    assert items == {"steam deck": "http", "PC": "other"}


def test_accept_creates_http_device_and_key_works(hub):
    req = new(hub, name="Deck nueva", os_="linux")
    r = accept(hub, req)
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    j = r.json()
    assert set(j) == {"id", "device", "name", "created"} and j["created"] is True and j["name"] == "Deck nueva"
    assert re.fullmatch(r"deck-nueva-[0-9a-f]{8}", j["device"])
    cfg = yaml.safe_load((hub.tmp / "config" / "config.yaml").read_text())
    assert cfg["devices"][j["device"]] == {"name": "Deck nueva", "http": True, "os": "linux"}
    assert validate_config(cfg)[1] == {}
    assert j["id"] == req["id"] and "key" not in j and req["secret"] not in r.text
    got = poll(hub, req)
    assert got.status_code == 200 and got.headers["cache-control"] == "no-store"
    g = got.json()
    assert g["status"] == "accepted" and g["device"] == j["device"]
    assert g["key"].startswith("ckd_") and apikey.is_well_formed_device(g["key"])
    # la key funciona en un endpoint http y solo ve los juegos del dispositivo (ninguno aún)
    r = hub.anon.get("/api/games", headers={"Authorization": f"Bearer {g['key']}"})
    assert r.status_code == 200 and r.json() == []
    assert (
        hub.anon.get("/api/hook/ping", headers={"Authorization": f"Bearer {g['key']}"}).json()["device"] == j["device"]
    )


def test_key_is_delivered_once_then_request_is_gone(hub):
    req = new(hub)
    accept(hub, req)
    assert poll(hub, req).json()["key"]
    r = poll(hub, req)
    assert r.status_code == 404 and code(r) == "err.pairing.request_unknown"
    assert hub.session.get("/api/pairing/pending").json() == []


def test_key_is_never_stored_in_pairing_memory(hub):
    req = new(hub)
    accept(hub, req)
    ctx = hub.app.state.ctx
    key = poll(hub, req).json()["key"]
    assert key not in repr(vars(ctx.pairing)) and req["secret"] not in repr(vars(ctx.pairing))


def test_pending_status_before_accept(hub):
    req = new(hub)
    j = poll(hub, req).json()
    assert j == {"status": "pending", "expires_in": 600}
    hub.clock[0] += 100
    assert poll(hub, req).json()["expires_in"] == 500


def test_wrong_secret_is_uniform_404_and_counts_failure(hub):
    req = new(hub)
    r_bad = poll(hub, req, secret="z" * 43)
    r_missing = hub.anon.get(f"/api/pairing/requests/{req['id']}")
    r_nonexistent = hub.anon.get("/api/pairing/requests/nope", headers={PAIRING_HDR: req["secret"]})
    for r in (r_bad, r_missing, r_nonexistent):
        assert r.status_code == 404 and code(r) == "err.pairing.request_unknown"
    assert r_bad.json() == r_missing.json() == r_nonexistent.json()
    assert hub.auth.pair_fails["testclient"][0] == 3
    assert poll(hub, req).status_code == 429  # bloqueado tras 3 fallos


def test_good_poll_resets_failures(hub):
    req = new(hub)
    poll(hub, req, secret="z" * 43)
    assert poll(hub, req).status_code == 200
    assert hub.auth.pair_fails == {}


def test_code_alone_cannot_collect_before_expiry(hub):
    req = new(hub)
    accept(hub, req)
    r = hub.anon.get(f"/api/pairing/requests/{req['id']}", headers={PAIRING_HDR: req["code"]})
    assert r.status_code == 404 and "key" not in r.text
    assert poll(hub, req).json()["key"]  # el dueño del secreto sí (si no está bloqueado)


def test_secret_not_accepted_in_query_or_authorization(hub):
    req = new(hub)
    r = hub.anon.get(f"/api/pairing/requests/{req['id']}?secret={req['secret']}")
    assert r.status_code == 404
    hub.clock[0] += 4000
    r = hub.anon.get(f"/api/pairing/requests/{req['id']}", headers={"Authorization": f"Bearer {req['secret']}"})
    assert r.status_code == 404


def test_reject(hub):
    req = new(hub)
    r = hub.session.post(f"/api/pairing/pending/{req['id']}/reject")
    assert r.status_code == 200 and r.json() == {"id": req["id"], "rejected": True}
    assert hub.session.get("/api/pairing/pending").json() == []
    g = poll(hub, req)
    assert g.status_code == 200 and g.json() == {"status": "rejected"} and "key" not in g.text
    assert poll(hub, req).status_code == 404  # se entrega una vez y se borra
    cfg = yaml.safe_load((hub.tmp / "config" / "config.yaml").read_text())
    assert sorted(cfg["devices"]) == ["deck", "pc"]  # nada creado


def test_reject_and_accept_unknown_request(hub):
    for path, kw in [("accept", {"json": {"code": "123456"}}), ("reject", {})]:
        r = hub.session.post(f"/api/pairing/pending/inexistente/{path}", **kw)
        assert r.status_code == 404 and code(r) == "err.pairing.request_unknown"


def test_accept_wrong_code_is_refused_and_locks_after_3(hub):
    req = new(hub)
    wrong = "000000" if req["code"] != "000000" else "111111"
    for left in (2, 1):
        r = accept(hub, req, c=wrong)
        assert r.status_code == 400 and code(r) == "err.pairing.code_mismatch"
        assert r.json()["detail"]["params"] == {"remaining": left}
    r = accept(hub, req, c=wrong)
    assert r.status_code == 400 and r.json()["detail"]["params"] == {"remaining": 0}
    assert hub.session.get("/api/pairing/pending").json() == []  # solicitud anulada
    assert accept(hub, req).status_code == 409  # anulada: ya no está pendiente
    assert poll(hub, req).json() == {"status": "rejected"}
    cfg = yaml.safe_load((hub.tmp / "config" / "config.yaml").read_text())
    assert sorted(cfg["devices"]) == ["deck", "pc"]


@pytest.mark.parametrize("body", [{}, {"code": 123456}, {"code": None}, {"code": ""}])
def test_accept_requires_code_in_body(hub, body):
    req = new(hub)
    r = hub.session.post(f"/api/pairing/pending/{req['id']}/accept", json=body)
    assert r.status_code == 400 and code(r) == "err.pairing.code_mismatch"


def test_accept_twice_is_409(hub):
    req = new(hub)
    assert accept(hub, req).status_code == 200
    r = accept(hub, req)
    assert r.status_code == 409 and code(r) == "err.pairing.not_pending"
    assert hub.session.post(f"/api/pairing/pending/{req['id']}/reject").status_code == 409


def test_accept_existing_non_http_name_is_409(hub):
    req = new(hub, name="pc")
    r = accept(hub, req)
    assert r.status_code == 409 and code(r) == "err.pairing.device_not_http"
    assert r.json()["detail"]["params"] == {"name": "pc"}
    cfg = yaml.safe_load((hub.tmp / "config" / "config.yaml").read_text())
    assert sorted(cfg["devices"]) == ["deck", "pc"] and cfg["devices"]["pc"]["user"] == "u"
    assert len(hub.session.get("/api/pairing/pending").json()) == 1  # sigue pendiente: se puede rechazar


def test_accept_existing_http_device_is_reused_and_key_regenerated_on_pickup(hub):
    old = hub.session.post("/api/devices/deck/apikey").json()["key"]
    req = new(hub, name="STEAM DECK", os_="windows")
    j = accept(hub, req).json()
    assert j["device"] == "deck" and j["created"] is False and j["name"] == "Steam Deck"
    cfg = yaml.safe_load((hub.tmp / "config" / "config.yaml").read_text())
    assert cfg["devices"]["deck"] == {"name": "Steam Deck", "http": True, "os": "linux"}  # config intacta
    assert sorted(cfg["devices"]) == ["deck", "pc"]
    # hasta que el dispositivo recoge, la key vieja sigue valiendo
    assert hub.anon.get("/api/games", headers={"Authorization": f"Bearer {old}"}).status_code == 200
    new_key = poll(hub, req).json()["key"]
    assert new_key != old
    anon2 = TestClient(hub.app)
    assert anon2.get("/api/games", headers={"Authorization": f"Bearer {new_key}"}).status_code == 200
    assert anon2.get("/api/games", headers={"Authorization": f"Bearer {old}"}).status_code == 401


def test_pickup_after_device_removed_from_config_is_404(hub):
    req = new(hub)
    dev = accept(hub, req).json()["device"]
    snap = hub.app.state.ctx.store.snapshot()
    cfg = snap.cfg.model_copy(deep=True)
    del cfg.devices[dev]
    hub.app.state.ctx.store.save(snap.version, cfg)
    r = poll(hub, req)
    assert r.status_code == 404 and not list((hub.tmp / "data" / "profile").rglob(f"devices/{dev}.enc"))


def test_two_requests_same_new_name_second_accept_reuses(hub):
    a, b = new(hub, name="Nueva"), new(hub, name="nueva")
    ja = accept(hub, a).json()
    jb = accept(hub, b).json()
    assert ja["created"] is True and jb["created"] is False and jb["device"] == ja["device"]


def test_pending_codes_are_unique(hub, monkeypatch):
    seq = iter([5, 5, 5, 7])
    monkeypatch.setattr(pairing.secrets, "randbelow", lambda n: next(seq))
    a = new(hub, name="A")
    b = new(hub, name="B")
    assert a["code"] == "000005" and b["code"] == "000007"


def test_id_is_ascii_prefix_plus_salt_and_not_reserved(hub):
    req = new(hub, name="Cubierta de Vapor ñandú")
    dev = accept(hub, req).json()["device"]
    assert re.fullmatch(r"cubierta-de-vapor-nandu-[0-9a-f]{8}", dev)
    req = new(hub, name="日本語")
    dev = accept(hub, req).json()["device"]
    assert re.fullmatch(r"device-[0-9a-f]{8}", dev)


def test_accept_keeps_comments_and_other_edits_work(hub):
    path = hub.tmp / "config" / "config.yaml"
    path.write_text("# mi config\n" + path.read_text())
    ctx = hub.app.state.ctx
    base = ctx.store.snapshot().version
    req = new(hub)
    accept(hub, req)
    text = path.read_text()
    assert text.startswith("# mi config") and "Deck nueva" in text
    snap = hub.session.get("/api/config").json()
    assert snap["version"] != base and any(d["name"] == "Deck nueva" for d in snap["config"]["devices"].values())
    # la edición con la versión antigua choca (409 normal); con la nueva pasa
    cfg = snap["config"]
    r = hub.session.put("/api/config", json={"base_version": base, "config": cfg})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "err.main.config_changed"
    cfg["max_versions"] = 7
    r = hub.session.put("/api/config", json={"base_version": snap["version"], "config": cfg})
    assert r.status_code == 200
    assert "Deck nueva" in path.read_text() and yaml.safe_load(path.read_text())["max_versions"] == 7
    assert list(ctx.store.list_backups())  # se hizo copia de seguridad antes de escribir


def test_accept_with_invalid_config_file_is_500(hub):
    req = new(hub)
    (hub.tmp / "config" / "config.yaml").write_text("devices: [")
    r = accept(hub, req)
    assert r.status_code == 500 and code(r) == "err.main.config_file_invalid"
    assert len(hub.session.get("/api/pairing/pending").json()) == 1


def test_accept_retries_on_concurrent_config_change(hub, monkeypatch):
    from app.config.store import Conflict, ConfigStore

    real = ConfigStore.save
    n = [0]

    def flaky(self, base, cfg):
        n[0] += 1
        if n[0] == 1:
            raise Conflict("otra")
        return real(self, base, cfg)

    monkeypatch.setattr(ConfigStore, "save", flaky)
    assert accept(hub, new(hub)).status_code == 200 and n[0] == 2


def test_accept_gives_409_if_config_keeps_changing(hub, monkeypatch):
    from app.config.store import Conflict, ConfigStore

    def always(self, base, cfg):
        raise Conflict("otra")

    monkeypatch.setattr(ConfigStore, "save", always)
    r = accept(hub, new(hub))
    assert r.status_code == 409 and code(r) == "err.main.config_changed"


# ---- secretos fuera de logs y errores ----
def test_no_secrets_in_logs_or_error_bodies(hub, caplog):
    caplog.set_level(logging.DEBUG)
    req = new(hub)
    bad = poll(hub, req, secret="s" * 43)
    accept(hub, req, c="000000" if req["code"] != "000000" else "111111")
    acc = accept(hub, req)
    key = poll(hub, req).json()["key"]
    poll(hub, req)
    hub.session.get("/api/pairing/pending")
    logs = "\n".join(r.getMessage() for r in caplog.records)
    for secret in (req["secret"], key, "s" * 43):
        assert secret not in logs
    assert req["secret"] not in bad.text and req["secret"] not in acc.text and key not in acc.text


def test_no_secrets_in_validation_errors(hub):
    r = hub.anon.post("/api/pairing/requests", json={"name": "", "os": "linux", "secret": "abc123"})
    assert "abc123" not in r.text
