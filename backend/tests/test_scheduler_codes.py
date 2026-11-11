"""Contrato i18n de scheduler e historial: errores y estados como {code, params}; historial antiguo se lee tal cual."""
import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.users import history
from app.core import settings
from app.sync.scheduler import Scheduler, validate_settings
from app.sync.engine import SyncAbort

APP = Path(__file__).parents[1] / "app"
ES = json.loads((Path(__file__).parents[2] / "frontend/src/locales/es.json").read_text())
NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
CUR = {"enabled": False, "interval_hours": 24.0, "run_on_start": False}


def has(code):
    v = ES
    for part in code.split("."):
        v = v.get(part) if isinstance(v, dict) else None
    return isinstance(v, str)


def test_codes_in_es_json():
    src = (APP / "sync/scheduler.py").read_text() + (APP / "users/history.py").read_text()
    codes = set(re.findall(r'"(err\.scheduler\.[a-z_]+)"', src))
    assert len(codes) >= 6, codes
    assert not sorted(c for c in codes if not has(c))


def test_validation_errors_are_code_params():
    def err(body):
        with pytest.raises(ValueError) as e:
            validate_settings(body, CUR)
        return e.value.args[0]
    assert err({"enabled": "yes"})["enabled"] == {"code": "err.scheduler.bool_required", "params": {}}
    assert err({"interval_hours": "6"})["interval_hours"]["code"] == "err.scheduler.interval_not_number"
    r = err({"interval_hours": 500})["interval_hours"]
    assert r == {"code": "err.scheduler.interval_range", "params": {"min": 0.25, "max": 168.0}}
    assert err({"on_conflict": "x"})["on_conflict"]["code"] == "err.scheduler.conflict_policy_invalid"


def _sched(tmp_path, monkeypatch, runner):
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)

    class Cfg:
        games = {k: SimpleNamespace(name=k.upper(), on_conflict=None, enabled=True) for k in "abcde"}
    return Scheduler(lambda: Cfg(), lambda g: g == "c", clock=lambda: NOW, runner=runner)


def runner(cfg, game, dry, log, **kw):
    if game == "a":
        return {"result": "ok", "message": ""}
    if game == "b":
        raise SyncAbort("err.sync.process_open", process="x.exe", device="PC")
    if game == "d":
        return {"result": "conflict", "code": "err.sync.conflict_stale", "params": {}, "message": "tecnico"}
    raise RuntimeError("boom")


def test_cycle_status_and_history_have_code_params(tmp_path, monkeypatch):
    s = _sched(tmp_path, monkeypatch, runner)
    asyncio.run(s._cycle())
    ls = s.last_status
    assert ls["code"] == "err.scheduler.summary" and ls["message"] == ""
    items = {c["path"]: c for c in ls["params"]["causes"]}
    assert items["B"] == {"path": "B", "code": "err.sync.process_open", "params": {"process": "x.exe", "device": "PC"}}
    assert items["C"]["code"] == "err.scheduler.skipped_busy"
    assert items["D"]["code"] == "err.scheduler.skipped_conflict"
    assert items["D"]["params"]["cause"] == {"code": "err.sync.conflict_stale", "params": {}}
    assert items["E"] == {"path": "E", "code": "err.sync.unexpected", "params": {"type": "RuntimeError", "detail": "boom"}}
    (e,) = history.read()
    g = e["games"]
    assert g["c"]["code"] == "err.scheduler.busy" and g["c"]["message"] == ""
    assert g["b"]["code"] == "err.sync.process_open" and g["b"]["message"] == ""
    assert g["d"]["code"] == "err.scheduler.skipped_conflict"
    assert g["a"] == {"result": "ok", "message": "", "name": "A"}
    assert e["code"] == "err.scheduler.summary" and e["message"] == ""


def test_cycle_crash_has_code(tmp_path, monkeypatch):
    s = _sched(tmp_path, monkeypatch, runner)
    s.run_cycle = lambda: (_ for _ in ()).throw(ValueError("x"))
    asyncio.run(s._cycle())
    assert s.last_status["code"] == "err.sync.unexpected" and s.last_status["params"]["type"] == "ValueError"


def test_history_params_redacted():
    e = history.make_entry(NOW, 1, "scheduled", "error",
                           {"g": {"result": "error", "code": "err.sync.unexpected",
                                  "params": {"type": "X", "detail": "password=hunter22"}}})
    assert "hunter22" not in json.dumps(e)


def test_old_entries_read_as_is(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    old = {"id": "old1", "started": NOW.isoformat(), "duration": 1.0, "trigger": "scheduled", "result": "error",
           "games": {"g": {"result": "error", "message": "no se pudo"}}, "message": "g: no se pudo"}
    raw = json.dumps(old, ensure_ascii=False) + "\n"
    history.path().write_text(raw)
    assert history.read()[0] == old
    history.append(history.make_entry(NOW, 1, "scheduled", "ok", {}), now=NOW)
    assert [e["id"] for e in history.read()][-1] == "old1" and history.read()[-1] == old
