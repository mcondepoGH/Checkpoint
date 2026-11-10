"""`GET /api/games/{game}/hook-status` (sesión) y campo `device` en el historial de hook / hook_closed."""
from datetime import datetime, timezone

from app import history
from test_hook_close import cl, hist, hopen, mk, wait_for, watches  # noqa: F401 (fixtures)
from test_hook_opened import PW


def status(c, game="g1"):
    return c.get(f"/api/games/{game}/hook-status")


def session(c):
    assert c.post("/api/login", json={"user": "admin", "password": PW}).status_code == 200


def test_requires_session(cl):
    assert status(cl).status_code == 401
    assert cl.get("/api/games/g1/hook-status", headers=cl.hdr).status_code == 401  # la key no vale


def test_unknown_game_404(cl):
    session(cl)
    assert status(cl, "nope").status_code == 404


def test_no_events_lists_both_devices_empty(cl):
    session(cl)
    j = status(cl).json()
    assert [d["device"] for d in j["devices"]] == ["dev-1", "dev-2"]
    assert all(d["last"] is None and d["watching"] is None for d in j["devices"])


def test_opened_records_device_and_status_shows_watching(cl):
    hopen(cl)
    h = hist("hook")
    assert len(h) == 1 and h[0]["device"] == "dev-1"
    session(cl)
    d1, d2 = status(cl).json()["devices"]
    assert d1["last"]["trigger"] == "hook" and d1["last"]["outcome"] == "ok" and d1["last"]["at"]
    assert set(d1["last"]) == {"trigger", "at", "outcome"}
    assert d1["watching"]["state"] == "waiting" and d1["watching"]["since"]
    assert d2["last"] is None and d2["watching"] is None


def test_closed_records_device_and_becomes_last(cl):
    hopen(cl)
    cl.proc.running = True
    assert wait_for(lambda: watches(cl).json() and watches(cl).json()[0]["state"] == "running")
    session(cl)
    assert status(cl).json()["devices"][0]["watching"]["state"] == "running"
    cl.proc.running = False
    assert wait_for(lambda: hist("hook_closed"))
    assert hist("hook_closed")[0]["device"] == "dev-1"
    assert wait_for(lambda: watches(cl).json() == [])
    d1 = status(cl).json()["devices"][0]
    assert d1["last"]["trigger"] == "hook_closed" and d1["watching"] is None


def test_no_secrets_in_response(cl):
    hopen(cl)
    session(cl)
    assert cl.key not in status(cl).text


def test_old_entries_without_device_are_valid_and_ignored(cl):
    old = history.make_entry(datetime.now(timezone.utc), 1, "hook", "ok", {"g1": {"result": "ok"}})
    assert "device" not in old
    history.append(old)
    assert history.read()[0]["id"] == old["id"]
    session(cl)
    assert all(d["last"] is None for d in status(cl).json()["devices"])


def test_make_entry_device_field():
    e = history.make_entry(datetime.now(timezone.utc), 1, "hook", "ok", {}, device="dev-1")
    assert e["device"] == "dev-1"
    assert "device" not in history.make_entry(datetime.now(timezone.utc), 1, "scheduled", "ok", {})


def test_watches_view_requires_session_and_exposes_heartbeat(cl):
    assert cl.get("/api/watches").status_code == 401
    assert cl.get("/api/watches", headers=cl.hdr).status_code == 401  # la key no vale
    session(cl)
    j = cl.get("/api/watches").json()
    assert j["watches"] == [] and j["now"]
    hopen(cl)
    j = cl.get("/api/watches").json()
    assert len(j["watches"]) == 1
    w = j["watches"][0]
    assert w["game"] == "g1" and w["device"] == "dev-1" and w["state"] == "waiting"
    assert w["since"] and w["last_poll"] and w["poll"] > 0
    assert "key" not in str(j).lower()


def test_disabled_opened_shows_skipped_with_reason(cl):
    from test_hook_opened import set_enabled
    set_enabled(cl.env, "g1", False)
    hopen(cl)
    session(cl)
    d1, d2 = status(cl).json()["devices"]
    assert d1["last"]["trigger"] == "hook" and d1["last"]["outcome"] == "skipped"
    assert d1["last"]["code"] == "err.sync.game_disabled" and d1["watching"] is None and d2["last"] is None
