import copy
import os
import stat
from datetime import datetime, timedelta

import pytest

from app import configstore, settings
from app.config import parse_config, validate_config
from app.configstore import Conflict, ConfigStore, InvalidConfig, config_events_gen, diff_configs, render_yaml

from test_api import CFG, client, login  # noqa: F401  (fixture)

SEED = """\
# mis dispositivos
devices:
  a: {host: 10.0.0.1, user: u, os: linux, port: 22}   # servidor
  b: {host: 10.0.0.2, user: u, os: windows}
games:
  g:
    devices: [a, b]        # exactamente dos
    paths:
      a: "/home/u/saves"
      b: "C:/Users/u/Saves"
    keep_versions: 5
"""


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "CONFIG_PATH", tmp_path / "config" / "config.yaml")
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path / "data")
    (tmp_path / "config").mkdir()
    settings.CONFIG_PATH.write_text(SEED)
    clock = [datetime(2026, 1, 1, 12, 0, 0)]
    monkeypatch.setattr(configstore, "_now", lambda: clock[0])
    return ConfigStore(), clock


def draft_of(store):
    return copy.deepcopy(store.snapshot().as_dict())


# ---------- validate: errores por ruta de campo ----------
def test_validate_ok():
    cfg, errs = validate_config(CFG)
    assert cfg is not None and errs == {}


def test_validate_errors_by_field_path():
    d = {"devices": {"pc": {"host": "x y", "user": "u", "os": "linux", "port": 70000},
                     "laptop": {"host": "h", "user": "u", "os": "linux"}},
         "games": {"ejemplo": {"devices": ["pc", "laptop"], "paths": {"pc": "rel", "laptop": "/x/y"},
                               "process": "a;b", "keep_versions": -1}}}
    cfg, errs = validate_config(d)
    assert cfg is None
    assert set(errs) >= {"devices.pc.host", "devices.pc.port", "games.ejemplo.process",
                         "games.ejemplo.keep_versions", "games.ejemplo.paths.pc"}
    assert "absoluta" in errs["games.ejemplo.paths.pc"]
    assert "games.ejemplo.paths.laptop" not in errs


def test_validate_incomplete_game_and_duplicates():
    d = copy.deepcopy(CFG)
    d["games"] = {"g": {"devices": ["a", "a"], "paths": {"a": "/x/y"}}}
    _, errs = validate_config(d)
    assert errs["games.g.devices.1"].startswith("debe ser distinto")
    d["games"]["g"] = {"devices": ["a", ""], "paths": {"a": "/x/y"}}
    _, errs = validate_config(d)
    assert errs == {"games.g.devices.1": "elige un dispositivo"}
    d["games"]["g"] = {"devices": ["a", "zz"], "paths": {"a": "/x/y"}}
    assert "games.g.devices.1" in validate_config(d)[1]
    d["games"]["g"] = {"devices": ["a", "b"], "paths": {"a": "/x/y"}}
    assert validate_config(d)[1] == {"games.g.paths.b": "falta la ruta del save"}
    d["games"]["g"] = {"keep_versions": "x"}
    errs = validate_config(d)[1]
    assert errs["games.g.devices"] == "campo obligatorio" and errs["games.g.paths"] == "campo obligatorio"
    assert "games.g.keep_versions" in errs


def test_validate_via_endpoint(client):
    login(client)
    r = client.post("/api/config/validate", json={"config": {"devices": {"a": {"host": "-x", "user": "u", "os": "linux"}}}})
    assert r.status_code == 200 and r.json()["ok"] is False and "devices.a.host" in r.json()["errors"]
    assert client.post("/api/config/validate", json={"config": CFG}).json() == {"ok": True, "errors": {}}
    assert client.post("/api/config/validate", json=[1]).status_code == 400


# ---------- guardado atómico, backup y poda ----------
def test_save_preserves_comments_and_backs_up(env):
    store, clock = env
    snap = store.snapshot()
    d = draft_of(store)
    d["devices"]["a"]["host"] = "10.0.0.9"
    d["devices"]["c"] = {"host": "10.0.0.3", "user": "u", "os": "linux", "port": 22}
    res = store.save(snap.version, validate_config(d)[0])
    assert res["changed"] and res["backup"] == "config.yaml.bak-2026-01-01_120000"
    text = settings.CONFIG_PATH.read_text()
    assert "# mis dispositivos" in text and "# servidor" in text and "# exactamente dos" in text
    assert "host: 10.0.0.9" in text and "c:" in text and '"/home/u/saves"' in text  # comillas conservadas
    assert (settings.DATA_DIR / "config-backups" / res["backup"]).read_text() == SEED
    assert parse_config(__import__("yaml").safe_load(text)).devices["c"].host == "10.0.0.3"
    assert [f.name for f in settings.CONFIG_PATH.parent.iterdir()] == ["config.yaml"]  # sin temporales
    assert store.snapshot().cfg.devices["a"].host == "10.0.0.9"  # recargado en memoria al instante


def test_save_noop_makes_no_backup(env):
    store, _ = env
    snap = store.snapshot()
    res = store.save(snap.version, snap.cfg)
    assert res["changed"] is False and store.list_backups() == []
    assert settings.CONFIG_PATH.read_text() == SEED


def test_permissions(env):
    store, _ = env
    os.chmod(settings.CONFIG_PATH, 0o640)
    d = draft_of(store)
    d["devices"]["a"]["port"] = 2222
    res = store.save(store.snapshot().version, validate_config(d)[0])
    assert stat.S_IMODE(settings.CONFIG_PATH.stat().st_mode) == 0o640
    bdir = settings.DATA_DIR / "config-backups"
    assert stat.S_IMODE(bdir.stat().st_mode) == 0o700
    assert stat.S_IMODE((bdir / res["backup"]).stat().st_mode) == 0o600


def test_backup_prune_max_10_and_same_second(env):
    store, clock = env  # reloj parado: cada copia choca en el mismo segundo y avanza uno
    for i in range(13):
        d = draft_of(store)
        d["devices"]["a"]["port"] = 3000 + i
        store.save(store.snapshot().version, validate_config(d)[0])
    names = [b["name"] for b in store.list_backups()]
    assert len(names) == 10
    assert names == sorted(names, reverse=True)
    assert names[-1] == "config.yaml.bak-2026-01-01_120003"  # las 3 más antiguas podadas
    assert len(set(names)) == 10


def test_non_backup_files_ignored(env):
    store, _ = env
    bdir = settings.DATA_DIR / "config-backups"
    bdir.mkdir(parents=True)
    (bdir / "otro.txt").write_text("x")
    assert store.list_backups() == []
    with pytest.raises(FileNotFoundError):
        store.read_backup("../../etc/passwd")


def test_invalid_rejected_file_untouched(env):
    store, _ = env
    d = draft_of(store)
    d["devices"]["a"]["host"] = "x y"
    cfg, errs = validate_config(d)
    assert cfg is None and "devices.a.host" in errs
    assert settings.CONFIG_PATH.read_text() == SEED


# ---------- conflicto por cambio externo / recarga en vivo ----------
def test_conflict_on_external_change(env):
    store, _ = env
    base = store.snapshot().version
    settings.CONFIG_PATH.write_text(SEED.replace("10.0.0.1", "10.0.0.77"))  # edición a mano
    d = draft_of(store)
    d["devices"]["a"]["port"] = 2222
    with pytest.raises(Conflict) as e:
        store.save(base, validate_config(d)[0])
    assert e.value.current_version != base
    assert "10.0.0.77" in settings.CONFIG_PATH.read_text()  # no se pisó
    assert store.list_backups() == []


def test_live_reload_and_events(env):
    store, _ = env
    s1 = store.snapshot()
    assert store.snapshot() is s1  # en caché mientras no cambie
    ticks = []
    gen = config_events_gen(store, interval=0, keepalive=0, max_ticks=3, sleep=lambda s: ticks.append(1))
    first = next(gen)
    assert first.startswith("event: config") and s1.version in first
    settings.CONFIG_PATH.write_text(SEED.replace("10.0.0.1", "10.0.0.55"))
    rest = list(gen)
    assert any(r.startswith("event: config") for r in rest)  # el cambio externo se anuncia
    assert store.snapshot().cfg.devices["a"].host == "10.0.0.55"


def test_invalid_external_edit_reported_not_crashing(env):
    store, _ = env
    settings.CONFIG_PATH.write_text("devices: [\n")
    snap = store.snapshot()
    assert snap.error and snap.cfg is None
    settings.CONFIG_PATH.write_text("devices:\n  a: {host: 'x y', user: u, os: linux}\n")
    assert "devices.a.host" in store.snapshot().error


# ---------- restauración ----------
def test_restore_backup_roundtrip(env):
    store, clock = env
    d = draft_of(store)
    d["devices"]["a"]["port"] = 2222
    store.save(store.snapshot().version, validate_config(d)[0])
    [b] = store.list_backups()
    clock[0] += timedelta(minutes=1)
    res = store.restore(store.snapshot().version, b["name"])
    assert res["changed"] and settings.CONFIG_PATH.read_text() == SEED  # exacto, con comentarios
    assert len(store.list_backups()) == 2  # la versión previa a restaurar también se respalda


def test_restore_conflict_and_invalid(env):
    store, _ = env
    bdir = settings.DATA_DIR / "config-backups"
    bdir.mkdir(parents=True)
    name = "config.yaml.bak-2025-01-01_000000"
    (bdir / name).write_text("devices:\n  a: {host: 'x y', user: u, os: linux}\n")
    with pytest.raises(InvalidConfig):
        store.restore(store.snapshot().version, name)
    (bdir / name).write_text(SEED)
    with pytest.raises(Conflict):
        store.restore("0000", name)


# ---------- diff ----------
def test_diff():
    old = parse_config({"devices": {"a": {"host": "h1", "user": "u", "os": "linux"},
                                    "b": {"host": "h2", "user": "u", "os": "linux"}}}).model_dump()
    new = copy.deepcopy(old)
    new["devices"]["a"]["port"] = 2200
    del new["devices"]["b"]
    new["devices"]["c"] = {"host": "h3", "user": "u", "os": "linux", "port": 22}
    d = diff_configs(old, new)
    assert d["devices"]["added"] == ["c"] and d["devices"]["removed"] == ["b"]
    assert d["devices"]["changed"] == {"a": {"port": {"old": 22, "new": 2200}}}
    assert d["empty"] is False and diff_configs(old, old)["empty"] is True


# ---------- API ----------
def test_api_flow(client):
    login(client)
    st = client.get("/api/config").json()
    v0 = st["version"]
    r = client.put("/api/config", json={"config": CFG, "base_version": v0})
    assert r.status_code == 200
    v1 = r.json()["version"]
    # sin base_version
    assert client.put("/api/config", json={"config": CFG}).status_code == 428
    # diff del borrador
    d2 = copy.deepcopy(CFG)
    d2["devices"]["a"]["port"] = 2222
    dd = client.post("/api/config/diff", json={"config": d2}).json()
    assert dd["diff"]["devices"]["changed"]["a"]["port"] == {"old": 22, "new": 2222} and dd["version"] == v1
    # yaml de solo lectura
    y = client.post("/api/config/yaml", json={"config": d2}).json()["yaml"]
    assert "port: 2222" in y
    assert client.post("/api/config/yaml", json={"config": {"devices": {"a": {}}}}).status_code == 422
    # edición externa -> 409 con versión actual
    settings.CONFIG_PATH.write_text(settings.CONFIG_PATH.read_text() + "\n# a mano\n")
    r = client.put("/api/config", json={"config": d2, "base_version": v1})
    assert r.status_code == 409 and r.json()["current_version"] != v1
    assert client.get("/api/config/status").json()["version"] == r.json()["current_version"]
    # guardar bien, listar copias, restaurar
    v2 = r.json()["current_version"]
    assert client.put("/api/config", json={"config": d2, "base_version": v2}).status_code == 200
    bl = client.get("/api/config/backups").json()
    assert len(bl) >= 1 and set(bl[0]) == {"name", "created", "size"}
    dr = client.post("/api/config/diff", json={"backup": bl[0]["name"]})
    assert dr.status_code == 200
    assert client.post("/api/config/diff", json={"backup": "../x"}).status_code == 404
    cur = client.get("/api/config").json()["version"]
    rr = client.post("/api/config/restore", json={"name": bl[0]["name"], "base_version": cur})
    assert rr.status_code == 200 and rr.json()["config"]["devices"]["a"].get("port", 22) == 22
    assert client.post("/api/config/restore", json={"name": bl[0]["name"], "base_version": "no"}).status_code == 409
    assert client.post("/api/config/restore", json={"name": "nope", "base_version": cur}).status_code == 404


def test_device_test_endpoint_validates(client):
    login(client)
    r = client.post("/api/devices/test", json={"device": {"host": "-oProxyCommand=x", "user": "u", "os": "linux"}})
    assert r.json()["ok"] is False


def test_no_secrets_in_config_responses(client, monkeypatch):
    login(client)
    monkeypatch.setenv("CHECKPOINT_PASSWORD", "supersecretvalue")
    body = client.get("/api/config").text + client.get("/api/config/backups").text
    assert "supersecretvalue" not in body and "PRIVATE KEY" not in body
