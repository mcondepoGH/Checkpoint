"""Contrato i18n de sync/transport/bootstrap: errores y estados como {code, params}, sin texto en español."""

import json
import re
import subprocess
from pathlib import Path

import pytest

from app.core import bootstrap, settings
from app.config.models import Config
from app.sync.engine import SyncAbort, resolve_game, run_sync
from app.sync.transport import PosixTransport, TransportError, local_folder_status, local_path
from fakes import LocalTransport
from tests.test_api import client, login  # noqa: F401
from tests.test_sync import CFG, env  # noqa: F401

APP = Path(__file__).parents[1] / "app"
ES = json.loads((Path(__file__).parents[2] / "frontend/src/locales/es.json").read_text())


def has(code):
    v = ES
    for part in code.split("."):
        v = v.get(part) if isinstance(v, dict) else None
    return isinstance(v, str)


def test_codes_in_es_json():
    src = "".join(f.read_text() for f in [*sorted((APP / "sync").rglob("*.py")), APP / "core" / "bootstrap.py"])
    src += (APP / "main.py").read_text()
    codes = set(re.findall(r'"(err\.(?:sync|transport|bootstrap)\.[a-z_]+)"', src))
    codes.discard("err.sync.conflict_")  # prefijo: los cinco motivos se añaden a mano
    codes |= {
        "err.sync.conflict_" + r for r in ("indeterminate", "stale", "no_baseline", "inconsistent", "both_changed")
    }
    assert len(codes) > 50, len(codes)
    missing = sorted(c for c in codes if not has(c))
    assert not missing, missing
    assert has("err.bootstrap.first_use") and has("err.config.local_docker")


def test_syncabort_has_code_params_and_body():
    e = SyncAbort("err.sync.process_open", process="a.exe", device="PC")
    assert (e.code, e.params) == ("err.sync.process_open", {"process": "a.exe", "device": "PC"})
    assert e.body() == {"code": e.code, "params": e.params} and "process_open" in str(e)


def test_resolve_game_propagates_config_error_as_cause():
    class G:
        def __init__(self, n):
            self.name = n

    cfg = type("C", (), {"games": {"a": G("Dup"), "b": G("Dup")}})()
    with pytest.raises(SyncAbort) as e:
        resolve_game(cfg, "Dup")
    assert e.value.code == "err.sync.ref_invalid"
    assert e.value.params["cause"]["code"] == "err.config.ref_ambiguous"
    with pytest.raises(SyncAbort) as e:
        resolve_game(type("C", (), {"games": {}})(), "nada")
    assert (e.value.code, e.value.params) == ("err.sync.game_unknown", {"ref": "nada"})


def test_transport_error_stderr_goes_in_detail_not_in_code():
    e = TransportError("err.transport.rsync_pull_failed", detail="Permission denied")
    assert e.body() == {"code": "err.transport.rsync_pull_failed", "params": {"detail": "Permission denied"}}


def test_posix_ssh_failure_is_coded(monkeypatch):
    monkeypatch.setattr(bootstrap, "ensure_host_key", lambda h, p: False)
    monkeypatch.setattr(
        "app.sync.transport.base._run",
        lambda a, timeout=0, stdin=None: subprocess.CompletedProcess(a, 255, b"", b"boom"),
    )
    from app.config.models import Device

    with pytest.raises(TransportError) as e:
        PosixTransport(Device(name="E", host="10.0.0.5", user="u", os="linux")).check()
    assert e.value.body() == {"code": "err.transport.ssh_failed", "params": {"detail": "boom"}}


def test_bootstrap_error_is_coded_and_wrapped_by_transport(monkeypatch):
    with pytest.raises(bootstrap.BootstrapError) as e:
        bootstrap.ensure_host_key("a b", 22)
    assert e.value.body() == {"code": "err.bootstrap.host_invalid", "params": {}}
    from app.config.models import Device

    def boom(h, p):
        raise bootstrap.BootstrapError("err.bootstrap.hostkey_unavailable", host=h, port=p)

    monkeypatch.setattr(bootstrap, "ensure_host_key", boom)
    with pytest.raises(TransportError) as t:
        PosixTransport(Device(name="E", host="10.0.0.5", user="u", os="linux")).check()
    assert t.value.body() == {"code": "err.bootstrap.hostkey_unavailable", "params": {"host": "10.0.0.5", "port": 22}}


def test_local_path_and_folder_status_codes(tmp_path):
    with pytest.raises(TransportError) as e:
        local_path("rel/x")
    assert e.value.body() == {"code": "err.transport.path_not_absolute", "params": {"path": "rel/x"}}
    r = local_folder_status("rel/x")
    assert (r["ok"], r["code"]) == (False, "err.transport.path_not_absolute")
    assert local_folder_status(str(tmp_path))["code"] == "err.transport.folder_ok"


def test_test_connection_codes(client, monkeypatch):
    login(client)
    body = {"device": {"name": "E", "host": "10.0.0.5", "user": "u", "os": "linux"}}
    monkeypatch.setattr("app.core.bootstrap.ensure_host_key", lambda h, p: True)
    monkeypatch.setattr("app.services.devices.get_transport", lambda d: type("T", (), {"check": lambda s: None})())
    r = client.post("/api/devices/test", json=body).json()
    assert (r["ok"], r["code"], r["params"], r["first_use"]) == (True, "err.transport.connection_ok", {}, True)

    def bad():
        raise TransportError("err.transport.ssh_failed", detail="password=hunter22 denied")

    monkeypatch.setattr("app.services.devices.get_transport", lambda d: type("T", (), {"check": lambda s: bad()})())
    r = client.post("/api/devices/test", json=body).json()
    assert (r["ok"], r["code"], r["first_use"]) == (False, "err.transport.ssh_failed", True)
    assert "hunter22" not in json.dumps(r)


def _no_spanish(x):
    assert not any(ord(ch) > 127 for ch in json.dumps(x, ensure_ascii=False)), x


def test_status_codes_for_every_outcome(env):
    st = env.sync()
    assert (st["code"], st["params"]) == ("err.sync.nothing_to_sync", {}) and st["message"].startswith("err.sync.")
    env.seed()
    assert env.sync()["code"] == "err.sync.already_synced"
    env.write(env.pc_dir, "s.sav", "pc-new", 3000)
    st = env.sync(dry=True)
    assert (st["result"], st["code"]) == ("dry-run", "err.sync.dry_run") and st["params"]["winner"] == "pc"
    st = env.sync()
    assert (st["result"], st["code"]) == ("ok", "err.sync.done") and st["params"] == {
        "winner": "pc",
        "updated": "laptop, hub",
    }


def test_status_conflict_carries_nested_reason(env):
    env.seed()
    env.write(env.pc_dir, "s.sav", "a", 3000)
    env.write(env.laptop_dir, "s.sav", "b", 4000)
    st = env.sync()
    assert (st["result"], st["code"]) == ("conflict", "err.sync.conflict")
    assert st["params"]["cause"] == {"code": "err.sync.conflict_both_changed", "params": {}}
    assert st["params"]["sides"]


def test_status_abort_and_partial_and_unexpected(env):
    env.write(env.pc_dir, "s.sav", "old", 1000)
    env.write(env.laptop_dir, "s.sav", "new", 2000)
    st = env.sync(pc={"down": True}, laptop={"down": True})
    assert (st["code"], st["params"]) == ("err.sync.all_offline", {"devices": "pc, laptop"})

    class Boom(LocalTransport):
        def push(self, *a, **k):
            raise TransportError("err.transport.rsync_push_failed", detail="Permission denied")

    env.seed()
    env.write(env.laptop_dir, "s.sav", "lap-new", 3000)
    tr = env.tr()
    tr["pc"] = Boom(env.pc_root)
    st = run_sync(CFG, "g", False, env.data, env.logs.append, tr)
    assert (st["result"], st["code"], st["failed"]) == ("partial", "err.sync.partial", ["pc"])
    assert st["params"]["failed"] == [
        {"path": "pc", "code": "err.transport.rsync_push_failed", "params": {"detail": "Permission denied"}}
    ]
    tr["pc"].check = lambda: (_ for _ in ()).throw(ValueError("x"))
    st = run_sync(CFG, "g", False, env.data, env.logs.append, tr)
    assert (st["result"], st["code"]) == ("error", "err.sync.unexpected") and st["params"] == {
        "type": "ValueError",
        "detail": "x",
    }


def test_status_json_has_no_spanish_text(env):
    env.seed()
    env.write(env.pc_dir, "s.sav", "pc-new", 3000)
    st = env.sync()
    _no_spanish({k: st[k] for k in ("code", "params", "message")})
    saved = json.loads((env.data / "status" / "g.json").read_text())
    assert saved["code"] == st["code"] and saved["params"] == st["params"]
