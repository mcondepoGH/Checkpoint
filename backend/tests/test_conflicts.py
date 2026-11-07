"""Conflictos, baseline y resolución: casos de decisión de _do_sync."""
import asyncio
import json
import time
from datetime import datetime, timezone

import pytest
import yaml

from app import history, settings
from app.config import parse_config, validate_config
from app.scheduler import Scheduler, validate_settings
from app.sync import (SyncAbort, decide, fingerprint, list_versions, load_baseline, pick_resolution, run_sync,
                      save_baseline)
from app.transport import LocalTransport, TransportError
from test_sync import CFG, Env, read


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


def versions(env):
    return list_versions(env.data, "g")


def status_file(env):
    return json.loads((env.data / "status" / "g.json").read_text())


def conflict(env):
    """Ambos lados cambian desde una sync previa, con contenido distinto (laptop más reciente)."""
    env.seed("base")
    env.write(env.pc_dir, "s.sav", "pc-change", 1000)
    env.write(env.laptop_dir, "s.sav", "laptop-change", 2000)


# ---- dos dispositivos conectados ----
def test_only_changed_side_wins_and_hub_follows(env):
    env.seed()
    env.write(env.pc_dir, "s.sav", "pc-new", 3000)
    st = env.sync()
    assert st["result"] == "ok" and st["winner"] == "pc" and set(st["targets"]) == {"laptop", "hub"}
    assert read(env.laptop_dir, "s.sav") == read(env.hub, "s.sav") == "pc-new"
    h = fingerprint(env.pc_dir).hash
    assert load_baseline(env.data, "g") == {"pc": h, "laptop": h, "hub": h}


def test_changed_side_wins_even_with_older_clock(env):
    """Deriva de reloj: laptop cambió pero su mtime es anterior al del save viejo de pc."""
    env.seed()
    env.write(env.pc_dir, "s.sav", "base", 9_000_000)  # mismo contenido, mtime muy posterior: no es un cambio
    env.write(env.laptop_dir, "s.sav", "laptop-edit", 100)  # cambio real con reloj atrasado
    st = env.sync()
    assert st["result"] == "ok" and st["winner"] == "laptop"
    assert read(env.pc_dir, "s.sav") == "laptop-edit"


def test_loser_always_versioned(env):
    env.seed("base")
    env.write(env.laptop_dir, "s.sav", "new", 2000)
    env.sync()
    (v,) = versions(env)
    assert read(env.data / "versions/g" / v["version"] / "pc", "s.sav") == "base"


def test_idempotent(env):
    env.seed()
    env.write(env.pc_dir, "s.sav", "pc-new", 3000)
    env.sync()
    n = len(versions(env))
    st = env.sync()
    assert st["result"] == "ok" and st["message"] == "ya sincronizado"
    assert len(versions(env)) == n
    assert env.sync()["message"] == "ya sincronizado"


# ---- conflicto real ----
def test_conflict_manual_returns_structured_and_touches_nothing(env):
    conflict(env)
    st = env.sync()
    assert st["result"] == "conflict"
    sides = {s["name"]: s for s in st["conflict"]["sides"]}
    assert set(sides) == {"pc", "laptop"}
    assert sides["laptop"]["mtime"] == 2000 and sides["pc"]["mtime"] == 1000
    assert sides["pc"]["size"] == len("pc-change") and sides["pc"]["files"] == 1
    assert st["conflict"]["reason"] == "both-changed"
    assert read(env.pc_dir, "s.sav") == "pc-change" and read(env.laptop_dir, "s.sav") == "laptop-change"
    assert read(env.hub, "s.sav") == "base" and versions(env) == []
    assert status_file(env)["result"] == "conflict"  # queda visible para la UI


def test_conflict_policy_skip_keeps_everything(env):
    conflict(env)
    st = env.sync(opts={"conflict_policy": "skip"})
    assert st["result"] == "conflict" and st["conflict"]["policy"] == "skip"
    assert read(env.pc_dir, "s.sav") == "pc-change" and versions(env) == []


def test_conflict_policy_newest_wins_and_loser_versioned(env):
    conflict(env)
    st = env.sync(opts={"conflict_policy": "newest"})
    assert st["result"] == "ok" and st["winner"] == "laptop"
    assert read(env.pc_dir, "s.sav") == read(env.hub, "s.sav") == "laptop-change"
    (v,) = versions(env)
    assert read(env.data / "versions/g" / v["version"] / "pc", "s.sav") == "pc-change"


def test_resolution_newest(env):
    conflict(env)
    st = env.sync(opts={"resolution": "newest"})
    assert st["result"] == "ok" and st["winner"] == "laptop"


def test_resolution_device_even_if_older(env):
    conflict(env)
    st = env.sync(opts={"resolution": "device:pc"})
    assert st["result"] == "ok" and st["winner"] == "pc"
    assert read(env.laptop_dir, "s.sav") == "pc-change"
    (v,) = versions(env)
    assert {x["source"] for x in v["sources"]} == {"laptop", "hub"}
    assert read(env.data / "versions/g" / v["version"] / "laptop", "s.sav") == "laptop-change"


def test_resolution_hub_and_invalid(env):
    conflict(env)
    assert env.sync(opts={"resolution": "hub"})["winner"] == "hub"
    assert read(env.pc_dir, "s.sav") == "base"
    for bad in ("", "oldest", "device:"):
        with pytest.raises(SyncAbort):
            env.sync(opts={"resolution": bad})
    conflict(env)
    st = env.sync(opts={"resolution": "device:nope"})
    assert st["result"] == "aborted" and "nope" in st["message"]


def test_resolution_without_conflict_is_ignored(env):
    env.seed()
    env.write(env.pc_dir, "s.sav", "pc-new", 3000)
    st = env.sync(opts={"resolution": "device:laptop"})  # no hay conflicto: gana quien cambió
    assert st["winner"] == "pc"


def test_dry_run_conflict_and_resolution_plan(env):
    conflict(env)
    before = load_baseline(env.data, "g")
    st = env.sync(dry=True)
    assert st["result"] == "conflict"
    st = env.sync(dry=True, opts={"resolution": "device:pc"})
    assert st["result"] == "dry-run" and st["winner"] == "pc"
    assert read(env.laptop_dir, "s.sav") == "laptop-change" and versions(env) == []
    assert load_baseline(env.data, "g") == before
    env.sync()  # deja la marca de conflicto
    env.sync(dry=True, opts={"resolution": "device:pc"})
    assert status_file(env)["result"] == "conflict"  # un dry-run no la borra


def test_clock_within_tolerance_is_indeterminate(env):
    conflict(env)
    env.write(env.pc_dir, "s.sav", "pc-change", 2001)  # 1 s de diferencia
    for opts in ({"conflict_policy": "newest"}, {"resolution": "newest"}):
        st = env.sync(opts=opts)
        assert st["result"] == "conflict" and st["conflict"]["reason"] == "indeterminate"
        assert read(env.laptop_dir, "s.sav") == "laptop-change"
    assert env.sync(opts={"resolution": "device:pc"})["result"] == "ok"  # elegir a mano sí vale


def test_stale_expect_returns_new_conflict(env):
    conflict(env)
    sides = {s["name"]: s["hash"] for s in env.sync()["conflict"]["sides"]}
    env.write(env.pc_dir, "s.sav", "pc-edited-again", 4000)  # cambia tras mostrar el popup
    st = env.sync(opts={"resolution": "device:laptop", "expect": sides})
    assert st["result"] == "conflict" and st["conflict"]["reason"] == "stale"
    assert read(env.pc_dir, "s.sav") == "pc-edited-again"
    new = {s["name"]: s["hash"] for s in st["conflict"]["sides"]}
    assert env.sync(opts={"resolution": "device:laptop", "expect": new})["result"] == "ok"


def test_both_changed_to_same_content_is_not_conflict(env):
    env.seed()
    env.write(env.pc_dir, "s.sav", "same", 1000)
    env.write(env.laptop_dir, "s.sav", "same", 2000)
    st = env.sync()
    assert st["result"] == "ok" and read(env.hub, "s.sav") == "same"


# ---- un solo dispositivo conectado ----
def test_one_online_newer_than_hub_uploads_and_versions(env):
    env.seed()
    env.write(env.pc_dir, "s.sav", "pc-new", 3000)
    st = env.sync(laptop={"down": True})
    assert st["result"] == "ok" and st["winner"] == "pc" and st["targets"] == ["hub"] and st["offline"] == ["laptop"]
    assert read(env.hub, "s.sav") == "pc-new" and read(env.laptop_dir, "s.sav") == "base"
    (v,) = versions(env)
    assert [x["source"] for x in v["sources"]] == ["hub"]
    b = load_baseline(env.data, "g")
    assert b["laptop"] != b["pc"]  # la baseline del offline no se toca


def test_one_online_older_than_hub_updates_device_from_hub(env):
    env.seed()
    env.write(env.laptop_dir, "s.sav", "laptop-new", 3000)
    assert env.sync()["result"] == "ok"  # pc y hub = laptop-new
    env.write(env.laptop_dir, "s.sav", "laptop-newer", 4000)
    env.sync(pc={"down": True})  # hub = laptop-newer, pc offline
    assert read(env.hub, "s.sav") == "laptop-newer" and read(env.pc_dir, "s.sav") == "laptop-new"
    st = env.sync(laptop={"down": True})  # pc vuelve; laptop offline
    assert st["result"] == "ok" and st["winner"] == "hub" and st["targets"] == ["pc"]
    assert read(env.pc_dir, "s.sav") == "laptop-newer"


def test_one_online_conflict_against_hub(env):
    env.seed()
    env.write(env.laptop_dir, "s.sav", "laptop-new", 3000)
    env.sync(pc={"down": True})  # hub cambia por laptop mientras pc está offline
    env.write(env.pc_dir, "s.sav", "pc-edit", 4000)  # pc cambió a la vez, sin saberlo
    st = env.sync(laptop={"down": True})
    assert st["result"] == "conflict"
    assert {s["name"] for s in st["conflict"]["sides"]} == {"pc", "hub"}
    assert read(env.pc_dir, "s.sav") == "pc-edit" and read(env.hub, "s.sav") == "laptop-new"
    st = env.sync(laptop={"down": True}, opts={"conflict_policy": "newest"})
    assert st["result"] == "ok" and st["winner"] == "pc" and read(env.hub, "s.sav") == "pc-edit"


def test_one_online_unchanged_is_noop(env):
    env.seed()
    st = env.sync(laptop={"down": True})
    assert st["result"] == "ok" and st["message"] == "ya sincronizado" and versions(env) == []


def _lagging(env):
    """laptop sincronizó solo con el hub mientras pc estaba offline: pc queda rezagado y sin cambios."""
    env.seed()
    env.write(env.laptop_dir, "s.sav", "laptop-new", 3000)
    assert env.sync(pc={"down": True})["result"] == "ok"
    assert read(env.pc_dir, "s.sav") == "base"


def test_lagging_unchanged_device_is_updated_from_hub_when_both_online(env):
    _lagging(env)
    st = env.sync()
    assert st["result"] == "ok" and st["winner"] == "hub" and st["targets"] == ["pc"]
    assert read(env.pc_dir, "s.sav") == "laptop-new"


def test_changed_side_wins_while_other_device_lags(env):
    _lagging(env)
    env.write(env.laptop_dir, "s.sav", "laptop-newer", 4000)
    st = env.sync()
    assert st["result"] == "ok" and st["winner"] == "laptop" and read(env.pc_dir, "s.sav") == "laptop-newer"


def test_edit_on_stale_base_conflicts_with_hub_progress(env):
    _lagging(env)
    env.write(env.pc_dir, "s.sav", "pc-edit", 4000)  # pc editó sin ver lo que laptop subió al hub
    st = env.sync()
    assert st["result"] == "conflict" and {s["name"] for s in st["conflict"]["sides"]} == {"pc", "hub"}
    assert read(env.hub, "s.sav") == "laptop-new"


# ---- primera sync (sin baseline) ----
def test_first_sync_empty_side_nonempty_wins(env):
    env.write(env.laptop_dir, "s.sav", "only-here", 100)
    st = env.sync()
    assert st["result"] == "ok" and st["winner"] == "laptop"
    assert read(env.pc_dir, "s.sav") == read(env.hub, "s.sav") == "only-here" and versions(env) == []
    assert load_baseline(env.data, "g")["hub"] is not None


def test_first_sync_devices_equal_hub_stale_hub_follows(env):
    env.write(env.pc_dir, "s.sav", "same", 100)
    env.write(env.laptop_dir, "s.sav", "same", 100)
    env.write(env.hub, "s.sav", "old-hub", 50)
    st = env.sync()
    assert st["result"] == "ok" and read(env.hub, "s.sav") == "same"
    (v,) = versions(env)
    assert [x["source"] for x in v["sources"]] == ["hub"]


def test_first_sync_different_data_is_conflict_not_mtime(env):
    env.write(env.pc_dir, "s.sav", "a", 1000)
    env.write(env.laptop_dir, "s.sav", "b", 9000)
    st = env.sync()
    assert st["result"] == "conflict" and st["conflict"]["reason"] == "no-baseline"
    assert read(env.pc_dir, "s.sav") == "a" and read(env.laptop_dir, "s.sav") == "b"
    assert load_baseline(env.data, "g") == {}


def test_first_sync_one_online_differs_from_hub_is_conflict(env):
    env.write(env.pc_dir, "s.sav", "a", 1000)
    env.write(env.hub, "s.sav", "hub-data", 500)
    st = env.sync(laptop={"down": True})
    assert st["result"] == "conflict" and read(env.hub, "s.sav") == "hub-data"


def test_corrupt_baseline_is_ignored_safely(env):
    env.seed()
    (env.data / "state" / "g.json").write_text("{no json")
    env.write(env.pc_dir, "s.sav", "a", 1000)
    assert env.sync()["result"] == "conflict"


# ---- borrados ----
def test_deleted_file_propagates_without_resurrecting(env):
    for d in (env.pc_dir, env.laptop_dir, env.hub):
        env.write(d, "a.sav", "A", 500)
        env.write(d, "b.sav", "B", 500)
    h = fingerprint(env.pc_dir).hash
    save_baseline(env.data, "g", {"pc": h, "laptop": h, "hub": h})
    (env.pc_dir / "b.sav").unlink()
    st = env.sync()
    assert st["result"] == "ok" and st["winner"] == "pc"
    assert not (env.laptop_dir / "b.sav").exists() and not (env.hub / "b.sav").exists()
    assert env.sync()["message"] == "ya sincronizado"
    assert not (env.pc_dir / "b.sav").exists() and not (env.laptop_dir / "b.sav").exists()


def test_emptied_side_never_wins(env):
    env.seed()
    for p in env.pc_dir.iterdir():
        p.unlink()
    st = env.sync()
    assert st["result"] == "ok" and read(env.pc_dir, "s.sav") == "base"  # se restaura desde el otro lado


# ---- offline ----
def test_both_offline_aborts_and_keeps_baseline(env):
    env.seed()
    before = load_baseline(env.data, "g")
    st = env.sync(pc={"down": True}, laptop={"down": True})
    assert st["result"] == "aborted" and "pc" in st["message"] and "laptop" in st["message"]
    assert load_baseline(env.data, "g") == before


# ---- proceso abierto ----
def test_process_open_aborts_before_anything(env):
    env.seed()
    env.write(env.laptop_dir, "s.sav", "new", 2000)
    st = env.sync(laptop={"running": True})
    assert st["result"] == "aborted" and "abierto" in st["message"]
    assert read(env.pc_dir, "s.sav") == "base" and versions(env) == []


class Flip(LocalTransport):
    """El proceso aparece justo después de la primera comprobación (TOCTOU)."""
    calls = 0

    def process_running(self, name):
        self.calls += 1
        return self.calls > 1


def test_process_recheck_before_push(env):
    env.seed()
    env.write(env.pc_dir, "s.sav", "pc-new", 3000)
    tr = {"pc": LocalTransport(env.pc_root), "laptop": Flip(env.laptop_root)}
    st = run_sync(CFG, "g", False, env.data, env.logs.append, tr)
    assert st["result"] == "aborted" and "abierto en laptop" in st["message"]
    assert read(env.laptop_dir, "s.sav") == "base" and read(env.hub, "s.sav") == "base"
    assert versions(env) == []


# ---- fallo parcial ----
class FailPush(LocalTransport):
    def push(self, src, path, extras=()):
        raise TransportError("rsync push falló")


def test_partial_failure_keeps_baseline_and_recovers(env):
    env.seed()
    env.write(env.pc_dir, "s.sav", "pc-new", 3000)
    before = load_baseline(env.data, "g")
    tr = {"pc": LocalTransport(env.pc_root), "laptop": FailPush(env.laptop_root)}
    st = run_sync(CFG, "g", False, env.data, env.logs.append, tr)
    assert st["result"] == "partial" and st["failed"] == ["laptop"] and "laptop" in st["message"]
    assert read(env.hub, "s.sav") == "pc-new" and read(env.laptop_dir, "s.sav") == "base"
    assert load_baseline(env.data, "g") == before
    st = env.sync()  # reintento: no es conflicto, completa el envío pendiente
    assert st["result"] == "ok" and read(env.laptop_dir, "s.sav") == "pc-new"
    assert env.sync()["message"] == "ya sincronizado"


# ---- decide / pick_resolution (puro) ----
def test_decide_pure():
    from app.sync import Fingerprint
    fp = lambda h, m=1: Fingerprint(h, m, 1 if h else 0, 1)  # noqa: E731
    assert decide({"a": fp("x"), "hub": fp("x")}, {})["kind"] == "same"
    assert decide({"a": fp("y"), "hub": fp("x")}, {"a": "x", "hub": "x"}) == {"kind": "winner", "winner": "a"}
    assert decide({"a": fp("y"), "hub": fp("z")}, {"a": "x", "hub": "x"})["kind"] == "conflict"
    assert pick_resolution("newest", ["a", "hub"], {"a": fp("y", 10), "hub": fp("z", 5)}) == "a"
    assert pick_resolution("newest", ["a", "hub"], {"a": fp("y", 10), "hub": fp("z", 9)}) is None


# ---- config / scheduler ----
def test_game_on_conflict_validation():
    base = {"devices": {"pc": {"host": "h", "user": "u", "os": "linux"}, "l": {"host": "h2", "user": "u", "os": "linux"}},
            "games": {"g": {"devices": ["pc", "l"], "paths": {"pc": "/a", "l": "/b"}}}}
    assert parse_config(base).games["g"].on_conflict is None  # config antigua: sin override
    base["games"]["g"]["on_conflict"] = "newest"
    assert parse_config(base).games["g"].on_conflict == "newest"
    base["games"]["g"]["on_conflict"] = "random"
    cfg, errs = validate_config(base)
    assert cfg is None and "games.g.on_conflict" in errs


def test_scheduler_on_conflict_validation_and_default(tmp_path, monkeypatch):
    cur = {"enabled": False, "interval_hours": 24.0, "run_on_start": False}
    assert validate_settings({"on_conflict": "newest"}, cur)["on_conflict"] == "newest"
    for bad in ("", "NEWEST", None, 1, "both"):
        with pytest.raises(ValueError) as e:
            validate_settings({"on_conflict": bad}, cur)
        assert "on_conflict" in e.value.args[0]
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    (tmp_path / "scheduler.json").write_text(json.dumps(cur))  # scheduler.json antiguo, sin on_conflict
    s = Scheduler(lambda: None, lambda g: False)
    assert s.state()["on_conflict"] == "skip"
    s.update({"on_conflict": "newest"})
    assert Scheduler(lambda: None, lambda g: False).state()["on_conflict"] == "newest"


def _sched(env, monkeypatch, **cfg_extra):
    monkeypatch.setattr(settings, "DATA_DIR", env.data)
    cfg = parse_config({
        "devices": {"pc": {"host": "h1", "user": "u", "os": "windows"},
                    "laptop": {"host": "h2", "user": "d", "os": "linux"}},
        "games": {"g": {"devices": ["pc", "laptop"], "paths": {"pc": "C:/Saves/g", "laptop": "/home/usuario/g"},
                        **cfg_extra}}})

    def runner(cfg_, game, dry, log, **kw):
        return run_sync(cfg_, game, dry, env.data, log, env.tr(), **kw)

    return Scheduler(lambda: cfg, lambda g: False, runner=runner)


def test_scheduler_skip_logs_conflict_in_history(env, monkeypatch):
    conflict(env)
    s = _sched(env, monkeypatch)
    asyncio.run(s._cycle())
    (e,) = history.read()
    assert e["result"] == "conflict" and e["games"]["g"]["result"] == "conflict"
    assert "omitido por conflicto" in e["games"]["g"]["message"]
    assert read(env.pc_dir, "s.sav") == "pc-change" and versions(env) == []


def test_scheduler_newest_resolves_and_game_override_wins(env, monkeypatch):
    conflict(env)
    s = _sched(env, monkeypatch)
    s.update({"on_conflict": "newest"})
    asyncio.run(s._cycle())
    assert history.read()[0]["result"] == "ok" and read(env.pc_dir, "s.sav") == "laptop-change"
    # override por juego: 'skip' en el juego gana al global 'newest'
    conflict(env)
    env.write(env.pc_dir, "s.sav", "pc-2", 5000)
    env.write(env.laptop_dir, "s.sav", "laptop-2", 6000)
    s2 = _sched(env, monkeypatch, on_conflict="skip")
    s2.update({"on_conflict": "newest"})
    asyncio.run(s2._cycle())
    assert history.read()[0]["result"] == "conflict" and read(env.pc_dir, "s.sav") == "pc-2"


# ---- API ----
def test_api_resolution_passthrough_and_validation(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import app.main as M
    from app.auth import Auth
    monkeypatch.setattr(settings, "CONFIG_PATH", tmp_path / "config" / "config.yaml")
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(settings, "STATIC_DIR", tmp_path / "static")
    (tmp_path / "static").mkdir()
    (tmp_path / "static/index.html").write_text("x")
    (tmp_path / "config").mkdir()
    (tmp_path / "config/config.yaml").write_text(yaml.safe_dump({
        "devices": {"pc": {"host": "h", "user": "u", "os": "linux"}, "l": {"host": "h2", "user": "u", "os": "linux"}},
        "games": {"g": {"devices": ["pc", "l"], "paths": {"pc": "/a", "l": "/b"}}}}))
    seen = {}

    def fake(cfg, game, dry, log=None, **kw):
        seen.update(kw, dry=dry)
        return {"result": "conflict", "message": "x", "conflict": {"sides": []}}

    monkeypatch.setattr(M, "run_sync", fake)
    c = TestClient(M.create_app(Auth("admin", "pw", 1, rounds=4)))
    assert c.post("/api/login", json={"user": "admin", "password": "pw"}).status_code == 200
    for bad in ("oldest", "device:", 5):
        assert c.post("/api/sync/g", json={"resolution": bad}).status_code == 422
    assert c.post("/api/sync/g", json={"resolution": "device:pc", "expect": 3}).status_code == 422
    r = c.post("/api/sync/g", json={"resolution": "device:pc", "expect": {"pc": "abc"}, "dry_run": True})
    assert r.status_code == 200
    for _ in range(50):
        if seen:
            break
        time.sleep(0.1)
    assert seen["resolution"] == "device:pc" and seen["expect"] == {"pc": "abc"} and seen["dry"] is True
    r = c.post("/api/sync/g", json={})  # compatible: sin cuerpo útil
    assert r.status_code in (200, 409)


def test_cli_conflict_exit_code(env, monkeypatch, capsys):
    import app.cli as C
    conflict(env)
    monkeypatch.setattr(C, "load_config", lambda p: CFG)
    monkeypatch.setattr(settings, "DATA_DIR", env.data)
    import app.sync as S
    monkeypatch.setattr(S, "get_transport", lambda dev: env.tr()["pc" if dev.host == "h1" else "laptop"])
    assert C.main(["sync", "g"]) == 3
    err = capsys.readouterr().err
    assert "CONFLICTO" in err and "pc:" in err and "laptop:" in err and "--resolve" in err
    assert C.main(["sync", "g", "--resolve", "newest"]) == 0
    assert C.main(["sync", "g", "--resolve", "bogus"]) == 2
