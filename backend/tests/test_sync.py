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
