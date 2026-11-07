import asyncio
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone

import pytest

from app import settings
from app.scheduler import Scheduler, compute_next_run, iso, validate_settings
from app.sync import SyncAbort

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
CUR = {"enabled": False, "interval_hours": 24.0, "run_on_start": False}


def test_validation_ranges():
    assert validate_settings({"interval_hours": 0.25}, CUR)["interval_hours"] == 0.25
    assert validate_settings({"interval_hours": 168}, CUR)["interval_hours"] == 168.0
    for bad in (0.24, 0, -1, 169, "6", None, True, float("nan"), float("inf")):
        with pytest.raises(ValueError) as e:
            validate_settings({"interval_hours": bad}, CUR)
        assert "interval_hours" in e.value.args[0]
    with pytest.raises(ValueError):
        validate_settings({"enabled": "yes"}, CUR)
    assert validate_settings({"enabled": True}, CUR) == {**CUR, "enabled": True}  # parcial


def test_next_run():
    assert compute_next_run(False, 6, None, NOW) is None
    assert compute_next_run(True, 6, None, NOW) == NOW + timedelta(hours=6)
    assert compute_next_run(True, 0.5, None, NOW) == NOW + timedelta(minutes=30)
    # arranque
    assert compute_next_run(True, 6, None, NOW, run_on_start=True, starting=True) == NOW
    assert compute_next_run(True, 6, NOW - timedelta(hours=2), NOW, starting=True) == NOW + timedelta(hours=4)
    assert compute_next_run(True, 6, NOW - timedelta(hours=9), NOW, starting=True) == NOW + timedelta(hours=6)


@pytest.fixture
def sched(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    t = [NOW]
    calls = []

    class Cfg:
        games = {k: SimpleNamespace(name=k.upper(), on_conflict=None) for k in "abc"}

    def runner(cfg, game, dry, log, **kw):  # kw: conflict_policy
        calls.append((game, dry))
        if game == "b":
            raise SyncAbort("lock")
        return {"result": "ok", "message": ""}

    s = Scheduler(lambda: Cfg(), lambda g: g == "c", clock=lambda: t[0], runner=runner)
    s.t, s.calls = t, calls
    return s


def test_update_reschedules_and_persists(sched, tmp_path):
    assert sched.state()["next_run"] is None
    st = sched.update({"enabled": True, "interval_hours": 0.5})
    assert st["next_run"] == iso(NOW + timedelta(minutes=30))
    sched.t[0] = NOW + timedelta(minutes=10)
    st = sched.update({"interval_hours": 2})
    assert st["next_run"] == iso(NOW + timedelta(minutes=10, hours=2))
    with pytest.raises(ValueError):
        sched.update({"interval_hours": 500})
    assert sched.state()["interval_hours"] == 2.0
    again = Scheduler(sched.get_cfg, sched.busy, clock=lambda: sched.t[0])
    assert again.state()["enabled"] is True and again.state()["interval_hours"] == 2.0


def test_cycle_skips_busy_never_dry_and_survives_errors(sched):
    st = sched.run_cycle()
    assert sched.calls == [("a", False), ("b", False)]  # c ocupado, omitido; nunca dry-run
    assert st["games"] == {"a": "ok", "b": "aborted", "c": "skipped"} and st["result"] == "aborted"
    asyncio.run(sched._cycle())
    assert sched.last_status["result"] == "aborted" and sched.last_run == NOW


def test_env_defaults_lose_to_saved(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    monkeypatch.setattr(settings, "AUTO_ENABLED", True)
    monkeypatch.setattr(settings, "AUTO_INTERVAL_HOURS", 999.0)  # fuera de rango => 24
    s = Scheduler(lambda: None, lambda g: False, clock=lambda: NOW)
    assert s.state()["enabled"] is True and s.state()["interval_hours"] == 24.0
    s.update({"enabled": False, "interval_hours": 3})
    monkeypatch.setattr(settings, "AUTO_ENABLED", True)
    s2 = Scheduler(lambda: None, lambda g: False, clock=lambda: NOW)
    assert s2.state()["enabled"] is False and s2.state()["interval_hours"] == 3.0


# ---- registro de ejecuciones ----
import json  # noqa: E402

from app import history  # noqa: E402


def _entry(i, started=NOW, result="ok"):
    return history.make_entry(started, 1.234, "scheduled", result, {"g": {"result": result, "message": f"m{i}"}}, f"e{i}")


def test_history_write_read_order(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    assert history.read() == []
    for i in range(3):
        history.append(_entry(i), now=NOW)
    r = history.read()
    assert [e["message"] for e in r] == ["e2", "e1", "e0"]  # más reciente primero
    assert len(history.read(2)) == 2
    e = r[0]
    assert e["trigger"] == "scheduled" and e["duration"] == 1.2 and e["started"] == iso(NOW)
    assert e["games"] == {"g": {"result": "ok", "message": "m2"}}


def test_history_retention_count_and_age(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    monkeypatch.setattr(history, "MAX_ENTRIES", 5)
    for i in range(8):
        history.append(_entry(i), now=NOW)
    assert [e["message"] for e in history.read(200)] == ["e7", "e6", "e5", "e4", "e3"]
    old = _entry(99, started=NOW - timedelta(days=history.MAX_DAYS + 1))
    history.append(old, now=NOW)  # ya caducada: se descarta
    assert all(e["message"] != "e99" for e in history.read(200))


def test_history_corrupt_lines_ignored(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    history.append(_entry(1), now=NOW)
    with open(history.path(), "a") as f:
        f.write("{no json\n[1,2]\n\n" + json.dumps({"id": 1}) + "\n")
    assert [e["message"] for e in history.read()] == ["e1"]
    history.append(_entry(2), now=NOW)  # reescribe sin las malas
    assert len(history.path().read_text().splitlines()) == 2
    history.path().write_bytes(b"\xff\xfe\x00garbage")
    assert history.read() == []


def test_history_no_secrets_and_truncation(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    e = history.make_entry(NOW, 0, "x", "weird", {"g": {"result": "ok", "message": "password=hunter22 " + "z" * 999}}, "token: abc")
    assert "hunter22" not in e["games"]["g"]["message"] and len(e["games"]["g"]["message"]) <= history.MSG_LEN
    assert "abc" not in e["message"] and e["trigger"] == "scheduled" and e["result"] == "error"


def test_cycle_records_history_and_triggers(sched):
    sched.update({"enabled": True, "run_on_start": True})
    asyncio.run(sched._cycle("startup"))
    (e,) = history.read()
    assert e["trigger"] == "startup" and e["result"] == "aborted"
    assert {g: d["result"] for g, d in e["games"].items()} == {"a": "ok", "b": "aborted", "c": "skipped"}
    assert e["games"]["b"]["message"] == "lock" and "lock" in e["message"]
    assert "details" not in sched.last_status
    asyncio.run(sched._cycle())
    assert [x["trigger"] for x in history.read()] == ["scheduled", "startup"]


def test_history_failure_does_not_break_cycle(sched, monkeypatch):
    def boom(*a, **k):
        raise OSError("disk")
    monkeypatch.setattr(history, "append", boom)
    asyncio.run(sched._cycle())
    assert sched.last_status["result"] == "aborted"
