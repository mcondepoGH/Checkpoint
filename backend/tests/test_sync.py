import os
from pathlib import Path

import pytest

from app.config import parse_config
from app.sync import SyncAbort, fingerprint, list_versions, restore_version, run_sync
from app.transport import LocalTransport

CFG = parse_config({
    "devices": {"pc": {"host": "h1", "user": "u", "os": "windows"},
                "laptop": {"host": "h2", "user": "d", "os": "linux"}},
    "games": {"g": {"devices": ["pc", "laptop"],
                    "paths": {"pc": "C:/Saves/g", "laptop": "/home/usuario/g"},
                    "process": "g.exe", "keep_versions": 2}},
})


class Env:
    def __init__(self, tmp):
        self.data = tmp / "data"
        self.pc_root, self.laptop_root = tmp / "pc", tmp / "laptop"
        self.pc_dir = self.pc_root / "C:/Saves/g"
        self.laptop_dir = self.laptop_root / "home/usuario/g"
        self.hub = self.data / "hub" / "g"
        self.logs = []

    def tr(self, **kw):
        return {"pc": LocalTransport(self.pc_root, **kw.get("pc", {})),
                "laptop": LocalTransport(self.laptop_root, **kw.get("laptop", {}))}

    def write(self, d: Path, name, content, mtime):
        f = d / name
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(content)
        os.utime(f, (mtime, mtime))

    def sync(self, dry=False, **kw):
        return run_sync(CFG, "g", dry, self.data, self.logs.append, self.tr(**kw))


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


def read(d, name):
    return (d / name).read_text()


def test_newest_wins_and_loser_versioned(env):
    env.write(env.pc_dir, "s.sav", "old", 1000)
    env.write(env.laptop_dir, "s.sav", "new", 2000)
    st = env.sync()
    assert st["result"] == "ok" and st["winner"] == "laptop"
    assert read(env.pc_dir, "s.sav") == "new"
    assert read(env.hub, "s.sav") == "new"
    v = list_versions(env.data, "g")
    assert len(v) == 1 and v[0]["sources"][0]["source"] == "pc"
    assert read(env.data / "versions/g" / v[0]["version"] / "pc", "s.sav") == "old"


def test_dry_run_changes_nothing(env):
    env.write(env.pc_dir, "s.sav", "old", 1000)
    env.write(env.laptop_dir, "s.sav", "new", 2000)
    st = env.sync(dry=True)
    assert st["result"] == "dry-run"
    assert read(env.pc_dir, "s.sav") == "old"
    assert not env.hub.exists()
    assert not (env.data / "versions").exists()


def test_already_in_sync_is_noop(env):
    env.write(env.pc_dir, "s.sav", "x", 1000)
    env.write(env.laptop_dir, "s.sav", "x", 1500)
    env.sync()
    st = env.sync()
    assert st["message"] == "ya sincronizado"
    assert len(list_versions(env.data, "g")) == 0


def test_first_sync_to_missing_side_no_version(env):
    env.write(env.pc_dir, "a/b.sav", "x", 1000)
    st = env.sync()
    assert st["result"] == "ok"
    assert read(env.laptop_dir, "a/b.sav") == "x"
    assert list_versions(env.data, "g") == []


def test_extra_files_removed_on_loser(env):
    env.write(env.pc_dir, "keep.sav", "1", 3000)
    env.write(env.laptop_dir, "keep.sav", "0", 1000)
    env.write(env.laptop_dir, "stale.sav", "z", 1000)
    env.sync()
    assert not (env.laptop_dir / "stale.sav").exists()
    assert fingerprint(env.laptop_dir).hash == fingerprint(env.pc_dir).hash


def test_device_down_touches_nothing(env):
    env.write(env.pc_dir, "s.sav", "old", 1000)
    env.write(env.laptop_dir, "s.sav", "new", 2000)
    st = env.sync(laptop={"down": True})
    assert st["result"] == "aborted" and "laptop" in st["message"]
    assert read(env.pc_dir, "s.sav") == "old"
    assert not env.hub.exists()


def test_process_running_aborts(env):
    env.write(env.pc_dir, "s.sav", "old", 1000)
    env.write(env.laptop_dir, "s.sav", "new", 2000)
    st = env.sync(pc={"running": True})
    assert st["result"] == "aborted" and "abierto" in st["message"]
    assert read(env.pc_dir, "s.sav") == "old"


def test_mtime_tie_different_content_aborts(env):
    env.write(env.pc_dir, "s.sav", "a", 1000)
    env.write(env.laptop_dir, "s.sav", "b", 1000)
    st = env.sync()
    assert st["result"] == "aborted" and "empate" in st["message"]


def test_keep_versions_prunes(env):
    t = 1000
    for i in range(4):
        t += 100
        env.write(env.pc_dir, "s.sav", f"pc{i}", t)
        env.write(env.laptop_dir, "s.sav", f"dk{i}", t + 50)
        env.sync()
        import time; time.sleep(1.1)  # nombres de versión por segundo
    assert len(list_versions(env.data, "g")) == 2


def _mkver(env, name, game="g", src="pc", content="x"):
    d = env.data / "versions" / game / name / src
    d.mkdir(parents=True)
    (d / "s.sav").write_text(content)
    return d.parent


def _names(env, game="g"):
    return [v["version"] for v in list_versions(env.data, game)]


def _cfg(max_versions=20, keep=None):
    g = {"devices": ["pc", "laptop"], "paths": {"pc": "C:/Saves/g", "laptop": "/home/usuario/g"}}
    if keep is not None:
        g["keep_versions"] = keep
    return parse_config({"max_versions": max_versions, "devices": {
        "pc": {"host": "h1", "user": "u", "os": "windows"},
        "laptop": {"host": "h2", "user": "d", "os": "linux"}}, "games": {"g": g}})


def _sync_with(env, cfg, dry=False, **kw):
    return run_sync(cfg, "g", dry, env.data, env.logs.append, env.tr(**kw))


def _conflict(env):
    env.write(env.pc_dir, "s.sav", "old", 1000)
    env.write(env.laptop_dir, "s.sav", "new", 2000)


OLD = [f"2026-01-0{i}_100000" for i in range(1, 6)]  # 01..05


def test_prune_global_limit_deletes_oldest_keeps_newest(env):
    for n in OLD:
        _mkver(env, n)
    _conflict(env)
    st = _sync_with(env, _cfg(max_versions=3))
    assert st["result"] == "ok"
    names = _names(env)
    assert len(names) == 3
    # la nueva (de hoy) y las 2 más recientes de las antiguas
    assert names[1:] == ["2026-01-05_100000", "2026-01-04_100000"]
    assert names[0] not in OLD
    assert any("poda" in m and "2026-01-01_100000" in m for m in env.logs)


def test_prune_per_game_override_beats_global(env):
    for n in OLD:
        _mkver(env, n)
    _conflict(env)
    _sync_with(env, _cfg(max_versions=100, keep=2))
    assert len(_names(env)) == 2


def test_zero_is_unlimited(env):
    for n in OLD:
        _mkver(env, n)
    _conflict(env)
    _sync_with(env, _cfg(max_versions=0))
    assert len(_names(env)) == 6
    _conflict(env)
    _sync_with(env, _cfg(max_versions=1, keep=0))  # override 0 gana al global 1
    assert len(_names(env)) >= 6


def test_no_prune_on_dry_run(env):
    for n in OLD:
        _mkver(env, n)
    _conflict(env)
    st = _sync_with(env, _cfg(max_versions=1), dry=True)
    assert st["result"] == "dry-run" and len(_names(env)) == 5


def test_no_prune_if_sync_fails(env):
    for n in OLD:
        _mkver(env, n)
    _conflict(env)
    assert _sync_with(env, _cfg(max_versions=1), laptop={"down": True})["result"] == "aborted"
    assert len(_names(env)) == 5


def test_no_prune_if_error_after_version_saved(env, monkeypatch):
    import app.sync as S
    for n in OLD:
        _mkver(env, n)
    _conflict(env)
    monkeypatch.setattr(S, "_replace_dir", lambda *a, **k: (_ for _ in ()).throw(OSError("boom")))
    st = _sync_with(env, _cfg(max_versions=1))
    assert st["result"] == "error" and len(_names(env)) == 6  # 5 + la recién guardada, sin podar


def test_prune_never_touches_other_games_or_hub(env):
    for n in OLD:
        _mkver(env, n)
        _mkver(env, n, game="otro")
    env.write(env.hub, "keep.sav", "h", 500)
    _conflict(env)
    _sync_with(env, _cfg(max_versions=1))
    assert len(_names(env)) == 1
    assert len(_names(env, "otro")) == 5
    assert (env.data / "versions" / "otro" / OLD[0] / "pc" / "s.sav").exists()


def test_prune_numeric_suffix_order(env):
    from app.sync import prune_versions
    for n in ["2026-01-01_100000", "2026-01-01_100000-2", "2026-01-01_100000-10", "2026-01-01_100000-1"]:
        _mkver(env, n)
    done = prune_versions(env.data, "g", 2)
    assert sorted(done) == ["2026-01-01_100000", "2026-01-01_100000-1"]
    assert _names(env) == ["2026-01-01_100000-10", "2026-01-01_100000-2"]


def test_prune_protects_new_version_and_min_one(env):
    from app.sync import prune_versions
    for n in OLD:
        _mkver(env, n)
    # aunque el reloj fuera atrás y la "nueva" fuese la más antigua, no se borra
    prune_versions(env.data, "g", 1, protect=OLD[0])
    assert OLD[0] in _names(env) and len(_names(env)) == 2
    prune_versions(env.data, "g", 1)
    assert len(_names(env)) == 1  # nunca 0 con max > 0
    assert prune_versions(env.data, "g", 0) == []


def test_prune_stays_inside_game_dir_ignores_symlinks(env, tmp_path):
    from app.sync import prune_versions
    outside = tmp_path / "outside" / "2026-01-01_100000"
    (outside / "pc").mkdir(parents=True)
    (outside / "pc" / "s.sav").write_text("precious")
    base = env.data / "versions" / "g"
    base.mkdir(parents=True)
    (base / "2025-12-31_100000").symlink_to(outside, target_is_directory=True)  # nombre de versión, pero symlink
    for n in OLD[:2]:
        _mkver(env, n)
    prune_versions(env.data, "g", 1)
    assert (outside / "pc" / "s.sav").read_text() == "precious"
    assert (base / "2025-12-31_100000").is_symlink()
    # carpeta del juego que es symlink fuera de data/versions: no se poda nada
    other = tmp_path / "elsewhere"
    for n in OLD:
        (other / n).mkdir(parents=True)
    (env.data / "versions" / "link").symlink_to(other, target_is_directory=True)
    assert prune_versions(env.data, "link", 1) == []
    assert len(list(other.iterdir())) == 5


def test_config_without_max_versions_uses_default(env):
    cfg = parse_config({"devices": {"pc": {"host": "h1", "user": "u", "os": "windows"},
                                    "laptop": {"host": "h2", "user": "d", "os": "linux"}},
                        "games": {"g": {"devices": ["pc", "laptop"],
                                        "paths": {"pc": "C:/Saves/g", "laptop": "/home/usuario/g"}}}})
    assert cfg.versions_limit("g") == 20
    for i in range(1, 26):
        _mkver(env, f"2026-01-{i:02d}_100000")
    _conflict(env)
    _sync_with(env, cfg)
    assert len(_names(env)) == 20  # primera poda con el defecto sobre histórico grande


def test_restore_after_prune_still_works(env):
    for n in OLD:
        _mkver(env, n, content=n)
    _conflict(env)
    cfg = _cfg(max_versions=2)
    _sync_with(env, cfg)
    ver = _names(env)[1]  # la antigua que sobrevive
    msg = restore_version(cfg, "g", ver, "pc", env.data)
    assert "restaurado" in msg and read(env.hub, "s.sav") == ver
    assert len(_names(env)) <= 2


def test_restore_blocked_while_game_locked(env):
    import fcntl
    from app.config import slug_for
    _mkver(env, OLD[0])
    (env.data / "locks").mkdir(parents=True, exist_ok=True)
    with open(env.data / "locks" / f"{slug_for('g')}.lock", "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        with pytest.raises(SyncAbort):
            restore_version(_cfg(), "g", OLD[0], "pc", env.data)
    assert _names(env) == [OLD[0]]


def test_restore_then_sync_propagates(env):
    env.write(env.pc_dir, "s.sav", "old", 1000)
    env.write(env.laptop_dir, "s.sav", "new", 2000)
    env.sync()
    ver = list_versions(env.data, "g")[0]["version"]
    msg = restore_version(CFG, "g", ver, "pc", env.data)
    assert "restaurado" in msg and read(env.hub, "s.sav") == "old"
    env.sync()
    assert read(env.pc_dir, "s.sav") == "old" and read(env.laptop_dir, "s.sav") == "old"


def test_restore_rejects_bad_input(env):
    for v, s in [("../x", "pc"), ("2020-01-01_000000", "evil")]:
        with pytest.raises(SyncAbort):
            restore_version(CFG, "g", v, s, env.data)


def test_unknown_game(env):
    with pytest.raises(SyncAbort):
        run_sync(CFG, "../x", False, env.data, lambda m: None, env.tr())


def test_lock_prevents_overlap(env):
    import fcntl
    (env.data / "locks").mkdir(parents=True)
    f = open(env.data / "locks/g.lock", "w")
    fcntl.flock(f, fcntl.LOCK_EX)
    with pytest.raises(SyncAbort, match="en curso"):
        env.sync()
    f.close()


def test_free_names_use_slug_paths_only(tmp_path):
    from app.config import slug_for
    g, a, b = "Dragon Quest VII: Dimensión", "Mi PC (salón)", "Switch & Co"
    cfg = parse_config({
        "devices": {a: {"host": "h1", "user": "u", "os": "windows"}, b: {"host": "h2", "user": "d", "os": "linux"}},
        "games": {g: {"devices": [a, b], "paths": {a: "C:/S/g", b: "/home/d/g"}, "keep_versions": 2}},
    })
    pc, laptop, data = tmp_path / "pc", tmp_path / "laptop", tmp_path / "data"
    (pc / "C:/S/g").mkdir(parents=True)
    (laptop / "home/d/g").mkdir(parents=True)
    for d, c, t in [(pc / "C:/S/g", "old", 1000), (laptop / "home/d/g", "new", 2000)]:
        (d / "s.sav").write_text(c)
        os.utime(d / "s.sav", (t, t))
    tr = {a: LocalTransport(pc), b: LocalTransport(laptop)}
    st = run_sync(cfg, g, False, data, lambda m: None, tr)
    assert st["result"] == "ok"
    slug = slug_for(g)
    assert (data / "hub" / slug / "s.sav").read_text() == "new"
    assert (data / "status" / f"{slug}.json").exists() and (data / "locks" / f"{slug}.lock").exists()
    # nada con el nombre crudo en disco
    for sub in data.rglob("*"):
        assert not any(c in sub.relative_to(data).as_posix().replace("/", "") for c in ":() &")
    v = list_versions(data, g)
    assert len(v) == 1 and v[0]["sources"][0]["source"] == slug_for(a)
    msg = restore_version(cfg, g, v[0]["version"], v[0]["sources"][0]["source"], data)
    assert "hub restaurado" in msg
    assert (data / "hub" / slug / "s.sav").read_text() == "old"
    with pytest.raises(SyncAbort):
        restore_version(cfg, g, v[0]["version"], "../x", data)
