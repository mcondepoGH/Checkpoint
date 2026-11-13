"""Subida sin el lock del juego, purga por antigüedad y tope del staging (`data/staging/<juego>/<dispositivo>/`)."""

import asyncio
import os
import time

import pytest
from fastapi.testclient import TestClient

from app.api.auth import Auth
from app.core import settings
from app.core.errors import ApiError
from app.main import create_app
from app.sync import engine as sync_engine
from app.sync import locking
from test_hook_files import anon, code, hdr, put, sha, stage
from test_hook_fingerprint import PW, Env, client, env  # noqa: F401 (fixtures)


def age(path, hours):
    t = time.time() - hours * 3600
    for p in [path, *path.rglob("*")]:
        os.utime(p, (t, t))


def plant(e, game, dev, rel="tree/a.sav", data=b"x"):
    f = e.data / "staging" / game / dev / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(data)
    return f.parents[len(rel.split("/")) - 1]


def hooks(c):
    return c.app.state.ctx.hooks


def upload(c, rel, stream, body_sha, size, offset=0):
    cfg = c.app.state.ctx.cfg()
    return hooks(c).upload(cfg, "g1", "deck", rel, size, body_sha, offset, stream, None)


# ---- 1. el lock del juego no se mantiene durante la subida ----
def test_slow_upload_does_not_hold_the_game_lock(client):
    seen = {}

    async def stream():
        yield b"ab"
        h = locking.acquire(client.env.data / "locks" / "g1.lock")  # subida a medias: el lock está libre
        h.release()
        try:
            with sync_engine._game_lock(client.env.data, "g1"):  # lo que toma la sync clásica
                seen["classic"] = True
        except Exception as e:  # pragma: no cover
            seen["classic"] = repr(e)
        yield b"cd"

    r = asyncio.run(upload(client, "a.sav", stream(), sha(b"abcd"), 4))
    assert seen == {"classic": True} and r["complete"] is True


def test_classic_sync_holding_the_lock_does_not_break_a_running_upload(client):
    async def stream():
        yield b"ab"
        h = locking.acquire(client.env.data / "locks" / "g1.lock")  # la sync clásica entra y sale mientras sube
        h.release()
        yield b"cd"

    assert asyncio.run(upload(client, "a.sav", stream(), sha(b"abcd"), 4))["received"] == 4


def test_concurrent_put_same_part_is_409_and_does_not_corrupt(client):
    body = b"0123456789"
    seen = {}

    async def stream():
        yield body[:5]
        with pytest.raises(ApiError) as e:  # segundo PUT al MISMO fichero mientras el primero escribe
            await upload(client, "a.sav", _one(body), sha(body), 10)
        seen["status"], seen["code"] = e.value.status_code, e.value.detail["code"]
        yield body[5:]

    async def _one(b):
        yield b

    r = asyncio.run(upload(client, "a.sav", stream(), sha(body), 10))
    assert seen == {"status": 409, "code": "err.hook.upload_busy"}
    assert r["complete"] is True and (stage(client.env) / "tree" / "a.sav").read_bytes() == body


def test_concurrent_put_other_file_is_fine(client):
    seen = {}

    async def other():
        yield b"zz"

    async def stream():
        yield b"a"
        seen["r"] = await upload(client, "b.sav", other(), sha(b"zz"), 2)
        yield b"b"

    assert asyncio.run(upload(client, "a.sav", stream(), sha(b"ab"), 2))["complete"] is True
    assert seen["r"]["complete"] is True


def test_part_lock_is_released_after_failure_and_success(client):
    assert put(client, "a.sav", b"abcd", size=4, digest=sha(b"xxxx")).status_code == 422  # sha mal
    assert put(client, "a.sav", b"abcd").status_code == 200
    assert put(client, "a.sav", b"abcd").status_code == 200  # reinicio con offset 0: el lock no quedó tomado


def test_upload_still_409_when_game_has_a_run(client):
    client.app.state.ctx.runs.create("g1", False, "Mi Juego")
    r = put(client, "a.sav", b"x")
    assert r.status_code == 409 and code(r) == "err.main.run_in_progress"


def test_commit_still_takes_the_game_lock(client):
    h = locking.acquire(client.env.data / "locks" / "g1.lock")
    try:
        r = anon(client).post(
            "/api/hook/g1/commit", params={"device": "deck"}, json={"expect": None, "manifest": []}, headers=hdr(client)
        )
        assert r.status_code == 409 and code(r) == "err.main.run_in_progress"
    finally:
        h.release()


# ---- 2. purga por antigüedad ----
def test_purge_removes_old_keeps_recent(client):
    e = client.env
    old = plant(e, "g1", "deck")
    new = plant(e, "g1", "pc")
    age(old, 25)
    n = hooks(client).purge_staging()
    assert n == 1 and not old.exists() and new.exists()
    assert not (e.data / "staging" / "g1" / "deck").exists()


def test_purge_uses_newest_file_of_the_stage(client):
    e = client.env
    d = plant(e, "g1", "deck")
    plant(e, "g1", "deck", "parts/x.part")
    age(d, 30)
    os.utime(d / "parts" / "x.part")  # una parte reciente salva todo el staging
    assert hooks(client).purge_staging() == 0 and d.exists()


def test_purge_skips_game_with_lock_or_run(client):
    e = client.env
    d = plant(e, "g1", "deck")
    age(d, 48)
    h = locking.acquire(e.data / "locks" / "g1.lock")
    try:
        assert hooks(client).purge_staging() == 0 and d.exists()
    finally:
        h.release()
    run = client.app.state.ctx.runs.create("g1", False, "Mi Juego")
    assert hooks(client).purge_staging() == 0 and d.exists()
    run.done = True
    assert hooks(client).purge_staging() == 1 and not d.exists()


def test_purge_respects_ttl_setting(client, monkeypatch):
    d = plant(client.env, "g1", "deck")
    age(d, 2)
    assert hooks(client).purge_staging() == 0
    monkeypatch.setattr(settings, "HOOK_STAGING_TTL_S", 3600)
    assert hooks(client).purge_staging() == 1 and not d.exists()


def test_purge_ignores_missing_staging_dir(client):
    assert hooks(client).purge_staging() == 0


def test_purge_runs_on_startup(env):
    d = plant(env, "g1", "deck")
    age(d, 48)
    with TestClient(create_app(Auth("admin", PW, 1, rounds=4))):
        pass
    assert not d.exists()


def test_purge_runs_opportunistically_on_upload_throttled(client):
    h = hooks(client)
    old = plant(client.env, "g1", "pc")
    age(old, 48)
    assert put(client, "a.sav", b"x").status_code == 200
    assert not old.exists()  # la primera subida purga
    old = plant(client.env, "g1", "pc")
    age(old, 48)
    assert put(client, "b.sav", b"x").status_code == 200
    assert old.exists()  # throttle: no vuelve a purgar enseguida
    h._last_purge = 0.0
    assert put(client, "c.sav", b"x").status_code == 200
    assert not old.exists()


# ---- 2. tope del staging por juego ----
def test_staging_cap_413_counts_all_devices(client, monkeypatch):
    monkeypatch.setattr(settings, "HOOK_STAGING_MAX_BYTES", 25)
    plant(client.env, "g1", "pc", data=b"y" * 10)  # otro dispositivo cuenta
    assert put(client, "a.sav", b"x" * 10).status_code == 200  # 20 <= 25
    r = put(client, "b.sav", b"x" * 10)  # 30 > 25
    assert r.status_code == 413 and code(r) == "err.hook.staging_full"
    assert r.json()["detail"]["params"] == {"max_mb": 25 / 1024 / 1024}
    assert not (stage(client.env) / "tree" / "b.sav").exists()
    assert not list((stage(client.env) / "parts").glob("*.part"))


def test_staging_cap_other_game_does_not_count(client, monkeypatch):
    monkeypatch.setattr(settings, "HOOK_STAGING_MAX_BYTES", 15)
    plant(client.env, "g2", "deck", data=b"y" * 100)
    assert put(client, "a.sav", b"x" * 10).status_code == 200


def test_staging_cap_while_streaming(client, monkeypatch):
    monkeypatch.setattr(settings, "HOOK_STAGING_MAX_BYTES", 10)

    def gen():  # chunked: sin Content-Length; declara 8 pero el tope se alcanza al sumar otro fichero
        yield b"a" * 4
        yield b"a" * 4

    plant(client.env, "g1", "pc", data=b"y" * 5)
    r = anon(client).put(
        "/api/hook/g1/files",
        params={"path": "a.sav", "size": 8, "sha256": sha(b"a" * 8), "offset": 0, "device": "deck"},
        content=gen(),
        headers=hdr(client),
    )
    assert r.status_code == 413 and code(r) == "err.hook.staging_full"


def test_staging_cap_restart_does_not_count_old_part(client, monkeypatch):
    monkeypatch.setattr(settings, "HOOK_STAGING_MAX_BYTES", 12)
    body = b"0123456789"
    assert put(client, "a.sav", body[:8], size=10, digest=sha(body)).status_code == 200
    assert put(client, "a.sav", body, offset=0).status_code == 200  # reinicia: la parte vieja no suma


def test_file_cap_unchanged(client, monkeypatch):
    monkeypatch.setattr(settings, "HOOK_MAX_FILE_BYTES", 10)
    assert code(put(client, "a.sav", b"x", size=11)) == "err.hook.file_too_large"


# ---- 2. límites de entorno ----
def _run(code_, **env_):
    from test_settings import _run as run

    return run(code_, **env_)


def test_staging_defaults():
    r = _run("from app.core import settings\nprint(settings.HOOK_STAGING_TTL_S, settings.HOOK_STAGING_MAX_BYTES)")
    assert r.returncode == 0, r.stderr
    assert r.stdout.split() == [str(24 * 3600), str(2048 * 1024 * 1024)] or r.stdout.split() == [
        str(24 * 3600.0),
        str(2048 * 1024 * 1024),
    ]


def test_staging_from_env():
    r = _run(
        "from app.core import settings\nprint(settings.HOOK_STAGING_TTL_S, settings.HOOK_STAGING_MAX_BYTES)",
        CHECKPOINT_HOOK_STAGING_TTL_H="1",
        CHECKPOINT_HOOK_STAGING_MAX_MB="1",
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout.split() == ["3600.0", str(1024 * 1024)]


@pytest.mark.parametrize(
    "var,vals",
    [
        ("CHECKPOINT_HOOK_STAGING_TTL_H", ("0", "0.5", "721", "-3", "abc", "nan", "inf")),
        ("CHECKPOINT_HOOK_STAGING_MAX_MB", ("0", "0.5", "1048577", "-3", "abc", "nan", "inf")),
    ],
)
def test_staging_env_out_of_range_is_system_exit(var, vals):
    for v in vals:
        r = _run("from app.core import settings", **{var: v})
        assert r.returncode != 0 and var in r.stderr, (var, v)


# ---- 3. commit y PUT del mismo dispositivo: el commit toma también el lock del stage ----
def test_put_during_commit_is_409_upload_busy_and_hub_gets_what_was_verified(client, monkeypatch):
    from app.services import hooks as hooks_mod
    from test_hook_files import commit, e_of, full_upload

    e = client.env
    man = full_upload(client, {"s.sav": b"nuevo"})
    seen = {}
    real = hooks_mod.write_winner_to_hub

    def spy(*a, **k):
        r = put(client, "s.sav", b"OTRO!")  # PUT concurrente del MISMO dispositivo, ya con el hub en escritura
        seen["status"], seen["code"] = r.status_code, code(r)
        return real(*a, **k)

    monkeypatch.setattr(hooks_mod, "write_winner_to_hub", spy)
    r = commit(client, None, man)
    assert r.status_code == 200, r.text
    assert seen == {"status": 409, "code": "err.hook.upload_busy"}
    assert (e.hub / "s.sav").read_bytes() == b"nuevo"
    assert man == [e_of("s.sav", b"nuevo", 2000)]


def test_commit_with_upload_in_progress_is_409_upload_busy_and_no_deadlock(client):
    from test_hook_files import commit, full_upload

    man = full_upload(client, {"s.sav": b"nuevo"})
    seen = {}

    async def stream():
        yield b"a"
        r = commit(client, None, man)  # el commit llega con un PUT del mismo dispositivo a medias
        seen["status"], seen["code"] = r.status_code, code(r)
        yield b"b"

    r = asyncio.run(upload(client, "t.sav", stream(), sha(b"ab"), 2))
    assert r["complete"] is True
    assert seen == {"status": 409, "code": "err.hook.upload_busy"}
    assert not (client.env.hub / "s.sav").exists()  # no se aplicó nada
    assert commit(client, None, man).status_code in (200, 422)  # ya sin PUT: no queda ningún lock tomado


def test_stage_lock_released_after_commit_failure_and_other_device_not_blocked(client):
    from test_hook_files import commit

    assert commit(client, "x" * 64, []).status_code == 409  # hub_changed
    assert put(client, "a.sav", b"abcd").status_code == 200  # el stage quedó libre


def test_stage_lock_is_per_device_stage(client):
    from app.services import hookfiles

    with hookfiles.stage_lock(stage(client.env)):
        with hookfiles.part_lock(stage(client.env).parent / "otro", "a.sav"):
            pass
        with pytest.raises(ApiError) as ex:
            with hookfiles.part_lock(stage(client.env), "a.sav"):
                pass
        assert ex.value.detail["code"] == "err.hook.upload_busy"
