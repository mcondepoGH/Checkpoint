"""Contrato de errores HTTP de main.py: detail = {"code": "err.main.<causa>", "params": {...}}. El backend no traduce."""
import threading

import pytest

from app.core import settings
from app.core.errors import ApiError, error_body
from tests.test_api import CFG, PW, client, login  # noqa: F401  (fixture client)


GAME = lambda n: {"name": n, "devices": ["a", "b"], "paths": {"a": "/x/y", "b": "C:\\x"}}


def det(r):
    d = r.json()["detail"]
    assert set(d) == {"code", "params"}
    return d["code"], d["params"]


def put_cfg(c, cfg=CFG):
    v = c.get("/api/config").json()["version"]
    return c.put("/api/config", json={"config": cfg, "base_version": v})


def test_helper_apierror():
    e = ApiError(404, "err.main.x", name="a")
    assert e.status_code == 404 and e.detail == {"code": "err.main.x", "params": {"name": "a"}}
    assert error_body("err.main.y") == {"code": "err.main.y", "params": {}}


def test_sesion_requerida(client):
    assert det(client.get("/api/config")) == ("err.main.session_required", {})


def test_origen_no_permitido(client):
    login(client)
    r = client.put("/api/config", json={}, headers={"origin": "http://evil.example"})
    assert r.status_code == 403 and det(r) == ("err.main.origin_forbidden", {})


def test_cuerpo_json_requerido(client):
    r = client.post("/api/login", content=b"no json", headers={"content-type": "application/json"})
    assert r.status_code == 400 and det(r) == ("err.main.json_body_required", {})
    r = client.post("/api/login", json=[1])
    assert r.status_code == 400 and det(r)[0] == "err.main.json_body_required"


def test_credenciales_y_demasiados_intentos(client):
    r = login(client, "no")
    assert r.status_code == 401 and det(r) == ("err.main.bad_credentials", {})
    for _ in range(10):
        r = login(client, "no")
        if r.status_code == 429:
            break
    assert r.status_code == 429
    code, params = det(r)
    assert code == "err.main.too_many_attempts" and params["seconds"] == r.json()["retry_after"] > 0
    assert r.headers["retry-after"] == str(params["seconds"])


def test_config_no_valida_con_errores_por_campo(client):
    login(client)
    bad = {"devices": {"a": {"name": "A", "host": "x y", "user": "u", "os": "linux"}}}
    r = put_cfg(client, bad)
    assert r.status_code == 422 and det(r) == ("err.main.config_invalid", {}) and "devices.a.host" in r.json()["errors"]
    r = client.post("/api/config/yaml", json={"config": bad})
    assert r.status_code == 422 and det(r)[0] == "err.main.config_invalid"


def test_base_version_requerida(client):
    login(client)
    for m, p in [("put", "/api/config"), ("post", "/api/config/restore")]:
        r = getattr(client, m)(p, json={"config": CFG})
        assert r.status_code == 428 and det(r) == ("err.main.base_version_required", {})


def test_conflicto_409(client):
    login(client)
    put_cfg(client)
    r = client.put("/api/config", json={"config": CFG, "base_version": "viejo"})
    assert r.status_code == 409 and det(r) == ("err.main.config_changed", {}) and r.json()["current_version"]


def test_copia_desconocida_y_no_valida(client):
    login(client)
    put_cfg(client)
    r = client.post("/api/config/diff", json={"backup": "nope"})
    assert r.status_code == 404 and det(r) == ("err.main.backup_unknown", {})
    cur = client.get("/api/config").json()["version"]
    r = client.post("/api/config/restore", json={"name": "nope", "base_version": cur})
    assert r.status_code == 404 and det(r) == ("err.main.backup_unknown", {})


def test_copia_no_valida(client, monkeypatch):
    login(client)
    from app.config import store as configstore
    monkeypatch.setattr(configstore.ConfigStore, "read_backup", lambda self, n: "devices: [")
    r = client.post("/api/config/diff", json={"backup": "x"})
    assert r.status_code == 422
    code, params = det(r)
    assert code == "err.main.backup_invalid" and params["cause"]["code"].startswith("err.config.yaml_")


def test_dispositivo_invalido_y_paths(client):
    login(client)
    r = client.post("/api/devices/test", json={"device": {"host": "x y"}}).json()
    assert r["ok"] is False and r["code"] == "err.main.device_invalid" and r["params"]["causes"] and r["message"]
    r = client.post("/api/devices/test", json={"device": {"name": "PC", "local": True, "os": "linux"}, "paths": "x"}).json()
    assert r["ok"] is False and r["code"] == "err.main.paths_invalid" and r["params"] == {"max": 50}


def test_clave_ssh_no_generada(client, monkeypatch):
    login(client)
    from app.core import bootstrap
    monkeypatch.setattr(bootstrap, "public_key", lambda: None)
    r = client.get("/api/ssh/public-key")
    assert r.status_code == 404 and det(r) == ("err.main.ssh_key_missing", {})


def test_config_yaml_invalido_500(client):
    login(client)
    settings.CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    settings.CONFIG_PATH.write_text("devices: [")
    r = client.get("/api/versions/g")
    assert r.status_code == 500
    code, params = det(r)
    assert code == "err.main.config_file_invalid" and params["cause"]["code"].startswith("err.")


def test_ajustes_no_validos_scheduler(client):
    login(client)
    r = client.put("/api/scheduler", json={"interval_hours": "x"})
    assert r.status_code == 422 and det(r) == ("err.main.settings_invalid", {}) and r.json()["errors"]


def test_updates_errores(client, monkeypatch):
    login(client)
    monkeypatch.setenv("CHECKPOINT_RUNTIME", "docker")
    r = client.put("/api/updates", json={"enabled": True})
    assert r.status_code == 409 and det(r) == ("err.main.updates_not_applicable", {}) and r.json()["aplicable"] is False
    monkeypatch.setenv("CHECKPOINT_RUNTIME", "native")
    r = client.put("/api/updates", json={"enabled": "si", "channel": "x"})
    assert r.status_code == 422 and det(r) == ("err.main.settings_invalid", {})
    errs = r.json()["errors"]
    assert errs["enabled"] == {"code": "err.main.updates.enabled_bool", "params": {}}
    assert errs["channel"] == {"code": "err.main.updates.channel_invalid", "params": {}}
    r = client.put("/api/updates", json={})
    assert r.json()["errors"]["enabled"]["code"] == "err.main.updates.field_required"


def test_juego_desconocido_y_ambiguo(client):
    login(client)
    put_cfg(client)
    for m, p in [("get", "/api/versions/zzz"), ("get", "/api/versions/zzz/limit"), ("post", "/api/sync/zzz")]:
        r = getattr(client, m)(p)
        assert r.status_code == 404 and det(r) == ("err.main.game_unknown", {}), p


def test_juego_ambiguo(client, monkeypatch):
    from app.config.models import ConfigError
    login(client)
    put_cfg(client)

    def amb(items, ref):
        raise ConfigError("err.config.ref_ambiguous", ref="Dup", matches="a, b")
    monkeypatch.setattr("app.main.resolve_ref", amb)
    r = client.get("/api/versions/Dup")
    assert r.status_code == 409 and det(r) == ("err.main.game_ambiguous", {"cause": {"code": "err.config.ref_ambiguous", "params": {"ref": "Dup", "matches": "a, b"}}})


def test_sync_422_y_409_y_run_desconocido(client):
    login(client)
    cfg = {**CFG, "games": {"g": GAME("G")}}
    assert put_cfg(client, cfg).status_code == 200
    r = client.post("/api/sync/g", json={"resolution": "mal"})
    assert r.status_code == 422 and det(r) == ("err.main.resolution_invalid", {})
    r = client.post("/api/sync/g", json={"expect": [1]})
    assert r.status_code == 422 and det(r) == ("err.main.expect_invalid", {})
    r = client.get("/api/runs/nada/stream")
    assert r.status_code == 404 and det(r) == ("err.main.run_unknown", {})


def test_ejecucion_en_curso_409(client, monkeypatch):
    login(client)
    cfg = {**CFG, "games": {"g": GAME("G")}}
    assert put_cfg(client, cfg).status_code == 200
    gate = threading.Event()
    monkeypatch.setattr("app.services.runs.run_sync", lambda *a, **k: gate.wait(5) or {"result": "ok"})
    try:
        assert client.post("/api/sync/g", json={}).status_code == 200
        r = client.post("/api/sync/g", json={})
        assert r.status_code == 409 and det(r) == ("err.main.run_in_progress", {})
    finally:
        gate.set()


def test_restaurar_version_falla_400(client, monkeypatch):
    from app.sync.engine import SyncAbort
    login(client)
    cfg = {**CFG, "games": {"g": GAME("G")}}
    put_cfg(client, cfg)

    def boom(*a, **k):
        raise SyncAbort("err.sync.version_unknown")
    monkeypatch.setattr("app.main.restore_version", boom)
    r = client.post("/api/versions/g/restore", json={"version": "v", "source": "a"})
    assert r.status_code == 400
    assert det(r) == ("err.main.restore_failed", {"cause": {"code": "err.sync.version_unknown", "params": {}}})


def test_spa_404(client):
    login(client)
    r = client.get("/api/nada")
    assert r.status_code == 404 and det(r) == ("err.main.not_found", {})
    settings.STATIC_DIR.joinpath("index.html").unlink()
    r = client.get("/algo")
    assert r.status_code == 404 and det(r) == ("err.main.frontend_not_built", {})
