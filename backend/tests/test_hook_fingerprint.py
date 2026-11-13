"""POST /api/hook/{game}/fingerprint?device=: decisión (upload/download/none/conflict) para un dispositivo `http`,
que solo escribe la línea base cuando la huella es igual a la del hub. Más la exclusión de los `http` en `opened`, vigilancia y scheduler."""

import hashlib
import os

import pytest
import yaml
from fastapi.testclient import TestClient

from app.api.auth import Auth
from app.core import settings
from app.main import create_app
from app.sync import engine as sync
from app.sync import locking
from app.sync.baseline import load_baseline
from app.sync.engine import fingerprint, save_baseline
from app.sync.fingerprint import fingerprint_from_manifest

PW = "correct horse"


def entry(rel, content, mtime=1000):
    b = content.encode()
    return {"path": rel, "sha256": hashlib.sha256(b).hexdigest(), "size": len(b), "mtime": mtime}


def tree(d):
    return sorted(str(p.relative_to(d)) for p in d.rglob("*")) if d.exists() else []


class Env:
    def __init__(self, tmp, cfg=None):
        self.tmp, self.hub, self.data = tmp, tmp / "data" / "hub" / "g1", tmp / "data"
        cfg = cfg or {
            "devices": {
                "deck": {"name": "Steam Deck", "http": True, "os": "linux"},
                "pc": {"name": "PC", "host": "192.0.2.10", "user": "u", "os": "linux"},
            },
            "games": {
                "g1": {
                    "name": "Mi Juego",
                    "devices": ["deck", "pc"],
                    "paths": {"deck": "/home/deck/g", "pc": "/home/u/g"},
                }
            },
        }
        (tmp / "config").mkdir(parents=True, exist_ok=True)
        (tmp / "config" / "config.yaml").write_text(yaml.safe_dump(cfg, allow_unicode=True))

    def write_hub(self, content, mtime=500):
        self.hub.mkdir(parents=True, exist_ok=True)
        f = self.hub / "s.sav"
        f.write_text(content)
        os.utime(f, (mtime, mtime))

    def hash_of(self, content):
        return fingerprint_from_manifest([entry("s.sav", content)]).hash

    def baseline(self, content="base"):
        h = self.hash_of(content)
        save_baseline(self.data, "g1", {"deck": h, "pc": h, "hub": h})


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "CONFIG_PATH", tmp_path / "config" / "config.yaml")
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(settings, "STATIC_DIR", tmp_path / "static")
    return Env(tmp_path)


@pytest.fixture
def client(env):
    c = TestClient(create_app(Auth("admin", PW, 1, rounds=4)))
    assert c.post("/api/login", json={"user": "admin", "password": PW}).status_code == 200
    c.key = c.post("/api/devices/deck/apikey").json()["key"]  # key del dispositivo http `deck`
    c.ukey = c.post("/api/profile/apikey").json()["key"]  # key de usuario (opened, watches, games)
    c.env = env
    return c


def fp(c, manifest, game="g1", device="deck", headers=None):
    h = {"Authorization": f"Bearer {c.key}"} if headers is None else headers
    url = f"/api/hook/{game}/fingerprint" + (f"?device={device}" if device else "")
    return TestClient(c.app).post(url, json=manifest, headers=h)  # sin cookie de sesión


def code(r):
    return r.json()["detail"]["code"]


# ---- decisión ----
def test_upload_when_only_device_changed(client):
    e = client.env
    e.write_hub("base")
    e.baseline()
    r = fp(client, [entry("s.sav", "nuevo", 2000)])
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["action"] == "upload" and j["game"] == "g1" and j["device"] == "deck"
    assert j["hub"] == {"hash": fingerprint(e.hub).hash, "files": 1, "size": 4, "mtime": 500}
    assert j["device_state"] == {"hash": e.hash_of("nuevo"), "files": 1, "size": 5, "mtime": 2000}


def test_download_when_only_hub_changed(client):
    e = client.env
    e.write_hub("nuevo")
    e.baseline()
    assert fp(client, [entry("s.sav", "base")]).json()["action"] == "download"


def test_none_when_equal(client):
    e = client.env
    e.write_hub("base")
    e.baseline()
    r = fp(client, [entry("s.sav", "base")])
    assert r.json()["action"] == "none" and r.json()["reason"] == "same"


def test_conflict_when_both_changed(client):
    e = client.env
    e.write_hub("hub nuevo")
    e.baseline()
    j = fp(client, [entry("s.sav", "dev nuevo")]).json()
    assert j["action"] == "conflict" and j["reason"] == "both-changed"


def test_conflict_without_baseline_when_both_have_data(client):
    client.env.write_hub("a")
    j = fp(client, [entry("s.sav", "b")]).json()
    assert j["action"] == "conflict" and j["reason"] == "no-baseline"


def test_empty_side_never_wins(client):
    e = client.env
    assert fp(client, [entry("s.sav", "x")]).json()["action"] == "upload"  # hub vacío
    e.write_hub("y")
    assert fp(client, []).json()["action"] == "download"  # dispositivo vacío
    assert fp(client, []).status_code == 200


def test_both_empty_is_none(client):
    j = fp(client, []).json()
    assert j["action"] == "none" and j["hub"]["hash"] is None and j["device_state"]["files"] == 0


def test_game_and_device_by_name(client):
    client.env.write_hub("a")
    r = fp(client, [entry("s.sav", "a")], game="Mi Juego", device="Steam Deck")
    assert r.status_code == 200 and r.json()["device"] == "deck"


def test_device_deduced_when_game_has_one_http_device(client):
    client.env.write_hub("a")
    r = fp(client, [entry("s.sav", "a")], device=None)  # el otro dispositivo es ssh: no cuenta
    assert r.status_code == 200 and r.json()["device"] == "deck"


def test_non_same_writes_nothing(client):
    e = client.env
    for hub, dev in (("base", "nuevo"), ("nuevo", "base"), ("hub nuevo", "dev nuevo")):  # upload, download, conflict
        e.write_hub(hub)
        e.baseline()
        before = tree(e.tmp / "data")
        bl = load_baseline(e.data, "g1")
        mtime = (e.hub / "s.sav").stat().st_mtime
        assert fp(client, [entry("s.sav", dev)]).status_code == 200
        assert tree(e.tmp / "data") == before and (e.hub / "s.sav").stat().st_mtime == mtime
        assert load_baseline(e.data, "g1") == bl


def test_same_writes_device_baseline(client):
    e = client.env
    e.write_hub("nuevo")  # sin línea base previa
    h = e.hash_of("nuevo")
    j = fp(client, [entry("s.sav", "nuevo")]).json()
    assert j["action"] == "none" and j["reason"] == "same"
    assert load_baseline(e.data, "g1") == {"deck": h, "hub": h}


def test_same_is_idempotent_and_does_not_rewrite(client, monkeypatch):
    e = client.env
    e.write_hub("nuevo")
    assert fp(client, [entry("s.sav", "nuevo")]).status_code == 200
    from app.services import hooks

    def boom(*a, **k):
        raise AssertionError("no debe reescribir")

    monkeypatch.setattr(hooks, "save_baseline", boom)
    assert fp(client, [entry("s.sav", "nuevo")]).json()["action"] == "none"


def test_same_with_busy_lock_is_409(client):
    e = client.env
    e.write_hub("nuevo")
    h = locking.acquire(e.data / "locks" / "g1.lock")
    try:
        r = fp(client, [entry("s.sav", "nuevo")])
    finally:
        h.release()
    assert r.status_code == 409 and code(r) == "err.main.run_in_progress"
    assert load_baseline(e.data, "g1") == {}


def test_non_same_ignores_busy_lock(client):
    e = client.env
    e.write_hub("base")
    e.baseline()
    h = locking.acquire(e.data / "locks" / "g1.lock")
    try:
        assert fp(client, [entry("s.sav", "nuevo")]).json()["action"] == "upload"
    finally:
        h.release()


def test_download_then_same_fingerprint_then_local_change_is_upload(client):
    e = client.env
    e.write_hub("base")
    e.baseline()
    e.write_hub("hub nuevo")
    assert fp(client, [entry("s.sav", "base")]).json()["action"] == "download"
    assert fp(client, [entry("s.sav", "hub nuevo")]).json()["action"] == "none"  # el dispositivo ya bajó
    j = fp(client, [entry("s.sav", "cambio local")]).json()
    assert j["action"] == "upload", j


# ---- errores ----
def test_auth_401_without_key_session_only_and_invalid(client):
    for h in ({}, {"Authorization": "Bearer ck_" + "x" * 43}):
        r = fp(client, [], headers=h)
        assert r.status_code == 401 and code(r) == "err.apikey.invalid"
    assert client.post("/api/hook/g1/fingerprint?device=deck", json=[]).status_code == 401  # cookie sola no vale


def test_401_before_404_and_422(client):
    r = fp(client, [{"path": "../x"}], game="nope", headers={})
    assert r.status_code == 401


def test_429_after_repeated_bad_keys(client):
    bad = {"Authorization": "Bearer ck_" + "y" * 43}
    for _ in range(3):
        fp(client, [], headers=bad)
    r = fp(client, [])
    assert r.status_code == 429 and int(r.headers["retry-after"]) > 0


def test_404_unknown_game_and_device(client):
    r = fp(client, [], game="nope")
    assert r.status_code == 404 and code(r) == "err.main.game_unknown"
    r = fp(client, [], device="nope")  # la key ya dice cuál es el dispositivo: otro distinto es 403
    assert r.status_code == 403 and code(r) == "err.apikey.device_mismatch"


def test_other_device_is_403(client):
    r = fp(client, [], device="pc")
    assert r.status_code == 403 and code(r) == "err.apikey.device_mismatch"


def test_two_http_devices_device_comes_from_the_key(tmp_path, monkeypatch):
    cfg = {
        "devices": {"a": {"name": "A", "http": True, "os": "linux"}, "b": {"name": "B", "http": True, "os": "linux"}},
        "games": {"g1": {"name": "J", "devices": ["a", "b"], "paths": {"a": "/x", "b": "/y"}}},
    }
    monkeypatch.setattr(settings, "CONFIG_PATH", tmp_path / "config" / "config.yaml")
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(settings, "STATIC_DIR", tmp_path / "static")
    Env(tmp_path, cfg)
    c = TestClient(create_app(Auth("admin", PW, 1, rounds=4)))
    c.post("/api/login", json={"user": "admin", "password": PW})
    c.key = c.post("/api/devices/a/apikey").json()["key"]
    r = fp(c, [], device=None)
    assert r.status_code == 200 and r.json()["device"] == "a"
    assert code(fp(c, [], device="b")) == "err.apikey.device_mismatch"


def test_409_run_in_progress(client):
    client.app.state.ctx.runs.create("g1", False, "Mi Juego")  # run sin terminar
    r = fp(client, [])
    assert r.status_code == 409 and code(r) == "err.main.run_in_progress"


def test_409_scheduler_current(client):
    client.app.state.ctx.scheduler.current = "g1"
    assert code(fp(client, [])) == "err.main.run_in_progress"


def test_409_game_disabled(tmp_path, monkeypatch, env):
    cfg = yaml.safe_load((tmp_path / "config" / "config.yaml").read_text())
    cfg["games"]["g1"]["enabled"] = False
    (tmp_path / "config" / "config.yaml").write_text(yaml.safe_dump(cfg))
    c = TestClient(create_app(Auth("admin", PW, 1, rounds=4)))
    c.post("/api/login", json={"user": "admin", "password": PW})
    c.key = c.post("/api/devices/deck/apikey").json()["key"]
    r = fp(c, [])
    assert r.status_code == 409 and code(r) == "err.sync.game_disabled"


@pytest.mark.parametrize("ok", ["it's.sav", "a&b.sav", "slot:1/x.sav", "Mi Partida/s 1.sav"])
def test_special_chars_in_names_accepted(client, ok):
    r = fp(client, [{**entry("s.sav", "a"), "path": ok}])
    assert r.status_code == 200, r.text


@pytest.mark.parametrize(
    "bad",
    ["../x", "a/../b", "/etc/passwd", "", "a\0b"],
)
def test_422_path_traversal(client, bad):
    r = fp(client, [{**entry("s.sav", "a"), "path": bad}])
    assert r.status_code == 422 and code(r) == "err.hook.manifest_path_invalid"


def test_422_bad_sha_duplicate_and_types(client):
    r = fp(client, [{**entry("s.sav", "a"), "sha256": "zz"}])
    assert r.status_code == 422 and code(r) == "err.hook.manifest_sha_invalid"
    r = fp(client, [entry("a", "1"), entry("a", "2")])
    assert r.status_code == 422 and code(r) == "err.hook.manifest_duplicate"
    for bad in (
        {**entry("a", "1"), "size": "mucho"},
        {**entry("a", "1"), "size": -1},
        {"path": "a"},
        {**entry("a", "1"), "extra": 1},
        "texto",
    ):
        r = fp(client, [bad])
        assert r.status_code == 422 and code(r) == "err.hook.manifest_invalid", bad


def test_400_body_not_a_json_list(client):
    h = {"Authorization": f"Bearer {client.key}"}
    t = TestClient(client.app)
    r = t.post("/api/hook/g1/fingerprint?device=deck", content=b"no json", headers=h)
    assert r.status_code == 400 and code(r) == "err.main.json_body_required"
    r = t.post("/api/hook/g1/fingerprint?device=deck", json={"a": 1}, headers=h)
    assert r.status_code == 400 and code(r) == "err.main.json_body_required"


def test_too_many_entries_422(client, monkeypatch):
    from app.services import hooks

    monkeypatch.setattr(hooks, "MANIFEST_MAX_FILES", 2)
    r = fp(client, [entry("a", "1"), entry("b", "2"), entry("c", "3")])
    assert r.status_code == 422 and code(r) == "err.hook.manifest_too_large"


# ---- los http no entran en el flujo clásico ----
def opened(c, device=None):
    h = {"Authorization": f"Bearer {c.ukey}"}
    return TestClient(c.app).post("/api/hook/g1/opened" + (f"?device={device}" if device else ""), headers=h)


def test_opened_rejects_http_device(client):
    r = opened(client, "deck")
    assert r.status_code == 400 and code(r) == "err.hook.device_push_only"


def test_opened_without_device_picks_the_ssh_one(client, monkeypatch):
    from fakes import LocalTransport

    e = client.env
    asked = []

    def fake(dev):
        asked.append(dev.name)
        assert not dev.http
        return LocalTransport(e.tmp / "pcroot")

    (e.tmp / "pcroot/home/u/g").mkdir(parents=True)
    (e.tmp / "pcroot/home/u/g/s.sav").write_text("pc")
    monkeypatch.setattr(sync, "get_transport", fake)
    r = opened(client)
    assert r.status_code == 200, r.text
    assert r.json()["device"] == "pc" and r.json()["outcome"] == "ok" and asked == ["PC"]


def test_arm_watch_is_noop_for_http(client):
    ctx = client.app.state.ctx
    cfg = ctx.cfg()
    out = ctx.hooks.arm_watch(cfg.games["g1"], "g1", "deck")
    assert out == {"watching": False, "watch_reason": "push_only"} and ctx.hooks.watcher.list() == []


def test_scheduler_cycle_skips_games_with_only_http(tmp_path, monkeypatch):
    cfg = {
        "devices": {"a": {"name": "A", "http": True, "os": "linux"}},
        "games": {"g1": {"name": "J", "devices": ["a"], "paths": {"a": "/x"}}},
    }
    monkeypatch.setattr(settings, "CONFIG_PATH", tmp_path / "config" / "config.yaml")
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(settings, "STATIC_DIR", tmp_path / "static")
    Env(tmp_path, cfg)
    ctx = create_app(Auth("admin", PW, 1, rounds=4)).state.ctx
    res = ctx.scheduler.run_cycle()
    assert res["games"] == {} and res["result"] == "ok"


# ---- `?manifest=1` aditivo: hub_manifest con la misma lectura del hub ----
def fpm(c, manifest, qs="&manifest=1", device="deck"):
    h = {"Authorization": f"Bearer {c.key}"}
    return TestClient(c.app).post(f"/api/hook/g1/fingerprint?device={device}{qs}", json=manifest, headers=h)


def test_manifest_param_adds_hub_manifest_on_download(client):
    e = client.env
    e.write_hub("nuevo")
    e.baseline()
    r = fpm(client, [entry("s.sav", "base")])
    j = r.json()
    assert r.status_code == 200 and j["action"] == "download"
    got = (
        TestClient(client.app)
        .get("/api/hook/g1/manifest", params={"device": "deck"}, headers={"Authorization": f"Bearer {client.key}"})
        .json()["manifest"]
    )
    assert j["hub_manifest"] == got and j["hub_manifest"][0]["path"] == "s.sav"
    assert set(j["hub_manifest"][0]) == {"path", "sha256", "size", "mtime"}
    assert fingerprint_from_manifest(j["hub_manifest"]).hash == j["hub"]["hash"]


def test_manifest_param_does_not_change_response_without_it(client):
    e = client.env
    e.write_hub("nuevo")
    e.baseline()
    plain = fp(client, [entry("s.sav", "base")]).json()
    assert "hub_manifest" not in plain
    assert fpm(client, [entry("s.sav", "base")], qs="").json() == plain
    with_m = fpm(client, [entry("s.sav", "base")]).json()
    assert {k: v for k, v in with_m.items() if k != "hub_manifest"} == plain


@pytest.mark.parametrize("hub,dev,base", [("base", "nuevo", "base"), ("a", "b", "c"), ("x", "x", "x")])
def test_manifest_param_only_with_download(client, hub, dev, base):
    e = client.env
    e.write_hub(hub)
    e.baseline(base)
    j = fpm(client, [entry("s.sav", dev)]).json()
    assert j["action"] != "download" and "hub_manifest" not in j


@pytest.mark.parametrize("v", ["0", "", "true", "2"])
def test_manifest_param_other_values_are_ignored(client, v):
    client.env.write_hub("nuevo")
    client.env.baseline()
    j = fpm(client, [entry("s.sav", "base")], qs=f"&manifest={v}").json()
    assert j["action"] == "download" and "hub_manifest" not in j


def test_manifest_param_reads_the_hub_once(client, monkeypatch):
    from app.services import hooks as hooks_mod

    client.env.write_hub("nuevo")
    client.env.baseline()
    calls = []
    real_fp, real_dm = hooks_mod.fingerprint, hooks_mod.dir_manifest
    monkeypatch.setattr(hooks_mod, "fingerprint", lambda p: calls.append("fp") or real_fp(p))
    monkeypatch.setattr(hooks_mod, "dir_manifest", lambda p: calls.append("dm") or real_dm(p))
    j = fpm(client, [entry("s.sav", "base")]).json()
    assert j["action"] == "download" and j["hub_manifest"]
    assert calls == []  # una sola pasada propia (fingerprint_with_manifest): ni fingerprint ni dir_manifest sueltos


def test_manifest_param_empty_hub(client):
    j = fpm(client, [entry("s.sav", "base")]).json()
    assert j["action"] == "upload" and "hub_manifest" not in j


def test_same_does_not_write_baseline_if_hub_changed_in_between(client, monkeypatch):
    """Un commit cambia el hub entre `fingerprint(hub)` y el lock de `_remember_same`: no se guarda la línea base."""
    e = client.env
    e.write_hub("nuevo")
    stale = e.hash_of("nuevo")
    svc = client.app.state.ctx.hooks
    e.write_hub("cambiado")  # el hub ya no es el que dio `stale`
    svc._remember_same("g1", "deck", stale)
    assert load_baseline(e.data, "g1") == {}
    svc._remember_same("g1", "deck", e.hash_of("cambiado"))  # digest vigente: sí
    h = e.hash_of("cambiado")
    assert load_baseline(e.data, "g1") == {"deck": h, "hub": h}
