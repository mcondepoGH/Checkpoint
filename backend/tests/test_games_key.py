"""GET /api/games (API key, Bearer): lista de juegos y su último estado de sync, para dispositivos sin SSH."""

import json

from app.core import settings
from test_hook_close import cl, hopen, mk  # noqa: F401 (fixtures)

KEYS = {"id", "name", "enabled", "status"}
STATUS_KEYS = {"result", "code", "started", "finished"}


def games(c, headers=None):
    return c.get("/api/games", headers=c.hdr if headers is None else headers)


def test_lists_games_without_status(cl):
    r = games(cl)
    assert r.status_code == 200
    j = r.json()
    assert [g["id"] for g in j] == ["g1", "g2"]
    assert all(set(g) == KEYS for g in j)
    assert j[0]["name"] == "Mi Juego" and j[0]["enabled"] is True and j[0]["status"] is None


def test_status_after_sync(cl):
    assert hopen(cl).status_code == 200
    g1 = next(g for g in games(cl).json() if g["id"] == "g1")
    assert set(g1["status"]) == STATUS_KEYS
    assert g1["status"]["result"] == "ok" and g1["status"]["started"] and g1["status"]["finished"]


def test_status_leaks_nothing_internal(cl):
    sd = settings.DATA_DIR / "status"
    sd.mkdir(parents=True, exist_ok=True)
    (sd / "g2.json").write_text(
        json.dumps(
            {
                "result": "conflict",
                "code": "err.sync.conflict",
                "message": "ruta /secreta",
                "log": "x.log",
                "conflict": {"a": 1},
                "params": {"path": "/secreta"},
                "started": "s",
                "finished": "f",
            }
        )
    )
    g2 = next(g for g in games(cl).json() if g["id"] == "g2")
    assert g2["status"] == {"result": "conflict", "code": "err.sync.conflict", "started": "s", "finished": "f"}
    assert "/secreta" not in games(cl).text


def test_status_of_removed_game_is_ignored(cl):
    sd = settings.DATA_DIR / "status"
    sd.mkdir(parents=True, exist_ok=True)
    (sd / "fantasma.json").write_text(json.dumps({"result": "ok"}))
    assert [g["id"] for g in games(cl).json()] == ["g1", "g2"]


def test_invalid_key_is_401(cl):
    for h in ({}, {"Authorization": "Bearer ck_nope"}, {"Authorization": "Basic x"}):
        r = games(cl, h)
        assert r.status_code == 401 and r.json()["detail"]["code"] == "err.apikey.invalid", h
        assert r.headers["www-authenticate"] == "Bearer"


def test_session_cookie_does_not_open_it(cl):
    from test_hook_opened import PW

    assert cl.post("/api/login", json={"user": "admin", "password": PW}).status_code == 200
    assert games(cl, {}).status_code == 401


def test_rate_limit_429(cl):
    for _ in range(3):
        assert games(cl, {"Authorization": "Bearer ck_nope"}).status_code == 401
    r = games(cl)  # bloqueada incluso con key válida
    assert r.status_code == 429 and r.headers["retry-after"]


def test_hook_status_route_still_session_only(cl):
    assert cl.get("/api/games/g1/hook-status", headers=cl.hdr).status_code == 401
