"""Juego de un solo dispositivo («solo checkpoint»): aviso `opened` sin ?device=, cierre y ciclo del scheduler."""
import os
import time

import pytest
import yaml
from fastapi.testclient import TestClient

from app.users import history
from app.core import settings
from app.auth import Auth
from app.main import create_app
from app.sync.scheduler import Scheduler
from app.sync.engine import fingerprint, save_baseline
from app.config.models import parse_config

PW = "correct horse"


class Env:
    def __init__(self, tmp):
        self.tmp = tmp
        self.d1, self.hub = tmp / "pc1", tmp / "data" / "hub" / "g1"
        cfg = {"devices": {"dev-1": {"name": "PC uno", "local": True, "os": "linux"}},
               "games": {"g1": {"name": "Mi Juego", "devices": ["dev-1"], "paths": {"dev-1": str(self.d1)},
                                "process": "game.exe"}}}
        (tmp / "config").mkdir(parents=True, exist_ok=True)
        (tmp / "config" / "config.yaml").write_text(yaml.safe_dump(cfg, allow_unicode=True))
        self.running = False

    def write(self, d, content, mtime, name="s.sav"):
        d.mkdir(parents=True, exist_ok=True)
        f = d / name
        f.write_text(content)
        os.utime(f, (mtime, mtime))

    def seed(self, content="base"):
        for d in (self.d1, self.hub):
            self.write(d, content, 500)
        h = fingerprint(self.d1).hash
        save_baseline(self.tmp / "data", "g1", {"dev-1": h, "hub": h})

    def read(self, d):
        return (d / "s.sav").read_text()


@pytest.fixture
def cl(tmp_path, monkeypatch):
    from app.sync import engine as sync
    e = Env(tmp_path)
    real = sync.get_transport

    def gt(dev):
        t = real(dev)
        t.process_running = lambda name: e.running
        return t

    monkeypatch.setattr(sync, "get_transport", gt)
    monkeypatch.setattr(settings, "CONFIG_PATH", tmp_path / "config" / "config.yaml")
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(settings, "STATIC_DIR", tmp_path / "static")
    monkeypatch.setattr(settings, "HOOK_POLL", 0.05)
    monkeypatch.setattr(settings, "HOOK_SETTLE", 0.1)
    monkeypatch.setattr(settings, "HOOK_FIRST_SEEN", 0.6)
    with TestClient(create_app(Auth("admin", PW, 1, rounds=4))) as c:
        assert c.post("/api/login", json={"user": "admin", "password": PW}).status_code == 200
        c.key = c.post("/api/profile/apikey").json()["key"]
        c.hdr = {"Authorization": f"Bearer {c.key}"}
        c.cookies.clear()
        c.env = e
        e.seed()
        yield c


def wait_for(cond, secs=5):
    end = time.time() + secs
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_opened_sin_device_acepta_un_dispositivo(cl):
    e = cl.env
    e.write(e.hub, "restaurado", 2000)  # el hub cambió por fuera (versión restaurada)
    r = cl.post("/api/hook/g1/opened", headers=cl.hdr)
    j = r.json()
    assert r.status_code == 200 and j["outcome"] == "ok" and j["device"] == "dev-1" and j["watching"] is True
    assert e.read(e.d1) == "restaurado"


def test_opened_con_device_tambien(cl):
    assert cl.post("/api/hook/g1/opened?device=dev-1", headers=cl.hdr).json()["device"] == "dev-1"
    assert cl.post("/api/hook/g1/opened?device=PC uno", headers=cl.hdr).status_code == 200
    assert cl.post("/api/hook/g1/opened?device=otro", headers=cl.hdr).status_code == 404


def test_cierre_guarda_checkpoint_en_el_hub(cl):
    e = cl.env
    cl.post("/api/hook/g1/opened", headers=cl.hdr)
    e.running = True
    assert wait_for(lambda: (cl.get("/api/hook/watches", headers=cl.hdr).json() or [{}])[0].get("state") == "running")
    e.write(e.d1, "jugado", 3000)
    e.running = False
    assert wait_for(lambda: [x for x in history.read() if x["trigger"] == "hook_closed"])
    time.sleep(0.3)
    h = [x for x in history.read() if x["trigger"] == "hook_closed"]
    assert len(h) == 1 and h[0]["result"] == "ok"
    assert e.read(e.hub) == "jugado"


def test_ciclo_del_scheduler_con_un_dispositivo(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path / "data")
    from app.sync.engine import run_sync, list_versions
    e = Env(tmp_path)
    e.seed("old")
    e.write(e.d1, "new", 2000)
    cfg = parse_config(yaml.safe_load((tmp_path / "config" / "config.yaml").read_text()))
    data = tmp_path / "data"
    s = Scheduler(lambda: cfg, lambda g: False,
                  runner=lambda c, g, dry, log, **kw: run_sync(c, g, dry, data, log, **kw))
    res, m, c, st = s.run_game(cfg, "g1")
    assert res == "ok" and e.read(e.hub) == "new" and len(list_versions(data, "g1")) == 1


def test_opened_omite_si_la_ruta_local_no_existe(cl):
    import shutil
    e = cl.env
    shutil.rmtree(e.d1)
    r = cl.post("/api/hook/g1/opened", headers=cl.hdr)
    j = r.json()
    assert r.status_code == 200 and j["outcome"] == "skipped" and j["ok"] is False
    assert j["code"] == "err.sync.local_missing_manual_required"
    assert not e.d1.exists() and e.read(e.hub) == "base"
    h = [x for x in history.read() if x["trigger"] == "hook"]
    assert len(h) == 1 and h[0]["result"] == "skipped" and h[0]["games"]["g1"]["code"] == "err.sync.local_missing_manual_required"


def test_sync_manual_api_restaura_la_ruta_local(cl):
    import shutil
    e = cl.env
    shutil.rmtree(e.d1)
    cl.cookies.clear()
    assert cl.post("/api/login", json={"user": "admin", "password": PW}).status_code == 200
    assert cl.post("/api/sync/g1", json={}).status_code == 200
    assert wait_for(lambda: (e.d1 / "s.sav").exists())
    assert e.read(e.d1) == "base"
