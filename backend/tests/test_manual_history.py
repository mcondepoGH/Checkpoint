"""Las sincronizaciones manuales reales se registran en el historial con trigger `manual`; las simulaciones no."""

import threading
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.core import settings
from app.services import runs
from app.sync.engine import SyncAbort
from app.sync.scheduler import Scheduler
from app.users import history

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    cfg = SimpleNamespace(games={"g": SimpleNamespace(enabled=True, name="Juego")})
    sched = SimpleNamespace(
        current=None, clock=lambda: NOW, game_detail=Scheduler.game_detail, summarize=Scheduler.summarize
    )
    return cfg, sched, runs.RunRegistry()


def go(env, body=None):
    cfg, sched, reg = env
    run = runs.start_manual_sync(reg, sched, cfg, "g", body or {})
    for t in threading.enumerate():
        if t is not threading.current_thread() and t.daemon:
            t.join(5)
    assert run.done
    return run


def test_manual_ok_is_recorded(env, monkeypatch):
    monkeypatch.setattr(runs, "run_sync", lambda *a, **k: {"result": "ok", "game": "g", "name": "Juego"})
    go(env)
    (e,) = history.read()
    assert e["trigger"] == "manual" and e["result"] == "ok"
    assert e["games"]["g"]["result"] == "ok" and e["games"]["g"]["name"] == "Juego"
    assert "device" not in e and e["duration"] >= 0


def test_manual_dry_run_not_recorded(env, monkeypatch):
    monkeypatch.setattr(runs, "run_sync", lambda *a, **k: {"result": "ok"})
    go(env, {"dry_run": True})
    assert history.read() == []


def test_manual_abort_and_error_recorded(env, monkeypatch):
    def abort(*a, **k):
        raise SyncAbort("err.sync.sync_in_progress")

    monkeypatch.setattr(runs, "run_sync", abort)
    go(env)
    e = history.read()[0]
    assert e["trigger"] == "manual" and e["result"] == "aborted"

    def boom(*a, **k):
        raise RuntimeError("token=SECRETO-1")

    monkeypatch.setattr(runs, "run_sync", boom)
    run = go(env)
    e = history.read()[0]
    assert e["trigger"] == "manual" and e["result"] == "error" and run.status["result"] == "error"
    assert "SECRETO-1" not in history.path().read_text()  # redactado


def test_manual_conflict_recorded_with_code(env, monkeypatch):
    st = {"result": "conflict", "code": "err.sync.conflict", "params": {"a": 1}, "message": "x"}
    monkeypatch.setattr(runs, "run_sync", lambda *a, **k: st)
    go(env)
    e = history.read()[0]
    assert e["result"] == "conflict" and e["games"]["g"]["code"] == "err.sync.conflict"


def test_history_failure_does_not_break_sync(env, monkeypatch):
    monkeypatch.setattr(runs, "run_sync", lambda *a, **k: {"result": "ok"})

    def fail(*a, **k):
        raise OSError("disco lleno")

    monkeypatch.setattr(history, "append", fail)
    run = go(env)
    assert run.done and run.status == {"result": "ok"}


def test_manual_trigger_known_and_cap_200(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    assert "manual" in history.TRIGGERS and history.MAX_ENTRIES == 200
    assert history.make_entry(NOW, 1, "manual", "ok", {})["trigger"] == "manual"
    assert history.make_entry(NOW, 1, "otro", "ok", {})["trigger"] == "scheduled"
    for i in range(210):
        history.append(history.make_entry(NOW, 1, "manual", "ok", {}, f"e{i}"), now=NOW)
    assert len(history.read()) == 200 and history.read()[0]["message"] == "e209"
