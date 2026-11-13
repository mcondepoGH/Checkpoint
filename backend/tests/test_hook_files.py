"""Subida y bajada de saves fichero a fichero para dispositivos `http`: `GET manifest`, `PUT files`, `POST commit`,
`GET files`. La subida escribe en staging y solo el commit toca `data/hub/<juego>`."""

import hashlib
import os

import pytest
from fastapi.testclient import TestClient

from app.core import settings
from app.sync import locking
from app.sync.engine import fingerprint, list_versions, load_baseline, save_baseline
from app.users import history
from test_hook_fingerprint import Env, client, code, entry, env  # noqa: F401 (fixtures)


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def hdr(c):
    return {"Authorization": f"Bearer {c.key}"}


def anon(c):
    return TestClient(c.app)  # sin cookie de sesión


def put(c, path, body: bytes, size=None, digest=None, offset=0, device="deck", headers=None, game="g1"):
    q = {"path": path, "size": len(body) if size is None else size, "sha256": digest or sha(body), "offset": offset}
    if device:
        q["device"] = device
    return anon(c).put(
        f"/api/hook/{game}/files", params=q, content=body, headers=hdr(c) if headers is None else headers
    )


def commit(c, expect, manifest, device="deck", headers=None, game="g1"):
    p = {"device": device} if device else {}
    return anon(c).post(
        f"/api/hook/{game}/commit",
        params=p,
        json={"expect": expect, "manifest": manifest},
        headers=hdr(c) if headers is None else headers,
    )


def get_file(c, path, device="deck", headers=None, rng=None, game="g1"):
    h = dict(hdr(c) if headers is None else headers)
    if rng:
        h["Range"] = rng
    return anon(c).get(f"/api/hook/{game}/files", params={"path": path, "device": device}, headers=h)


def stage(e):
    return e.data / "staging" / "g1" / "deck"


def e_of(rel, b: bytes, mtime=1000):
    return {"path": rel, "sha256": sha(b), "size": len(b), "mtime": mtime}


# ---- subida: un fichero ----
def test_upload_complete_goes_to_staging_not_hub(client):
    e = client.env
    e.write_hub("base")
    r = put(client, "slot/s.sav", b"nuevo")
    assert r.status_code == 200, r.text
    assert r.json() == {
        "game": "g1",
        "device": "deck",
        "path": "slot/s.sav",
        "received": 5,
        "size": 5,
        "complete": True,
    }
    assert (stage(e) / "tree" / "slot" / "s.sav").read_bytes() == b"nuevo"
    assert (e.hub / "s.sav").read_text() == "base" and sorted(p.name for p in e.hub.iterdir()) == ["s.sav"]


def test_upload_resume_with_offset(client):
    body = b"0123456789"
    r = put(client, "a.sav", body[:4], size=10, digest=sha(body))
    assert r.status_code == 200 and r.json()["complete"] is False and r.json()["received"] == 4
    r = put(client, "a.sav", body[6:], size=10, digest=sha(body), offset=6)  # hueco: no se acepta
    assert r.status_code == 409 and code(r) == "err.hook.upload_offset_mismatch"
    assert r.json()["detail"]["params"]["received"] == 4
    r = put(client, "a.sav", body[4:], size=10, digest=sha(body), offset=4)
    assert r.status_code == 200 and r.json()["complete"] is True and r.json()["received"] == 10
    assert (stage(client.env) / "tree" / "a.sav").read_bytes() == body
    assert not list((stage(client.env) / "parts").glob("*"))


def test_upload_offset_zero_restarts_the_part(client):
    body = b"0123456789"
    put(client, "a.sav", b"xxxx", size=10, digest=sha(body))
    r = put(client, "a.sav", body, size=10, digest=sha(body), offset=0)
    assert r.status_code == 200 and r.json()["complete"] is True
    assert (stage(client.env) / "tree" / "a.sav").read_bytes() == body


def test_resume_with_other_hash_is_rejected(client):
    body = b"0123456789"
    put(client, "a.sav", body[:4], size=10, digest=sha(body))
    r = put(client, "a.sav", b"456789", size=10, digest=sha(b"otro"), offset=4)
    assert r.status_code == 409 and code(r) == "err.hook.upload_offset_mismatch"
    assert r.json()["detail"]["params"]["received"] == 0


def test_wrong_sha_is_rejected_and_nothing_is_kept(client):
    r = put(client, "a.sav", b"hola", digest=sha(b"adios"))
    assert r.status_code == 422 and code(r) == "err.hook.sha_mismatch"
    st = stage(client.env)
    assert not (st / "tree" / "a.sav").exists() and not list((st / "parts").glob("*"))


def test_more_bytes_than_declared_size(client):
    r = put(client, "a.sav", b"0123456789", size=4)
    assert r.status_code == 422 and code(r) == "err.hook.upload_size_mismatch"
    assert not list((stage(client.env) / "parts").glob("*"))


def test_empty_file_is_a_valid_upload(client):
    r = put(client, "vacio.sav", b"")
    assert r.status_code == 200 and r.json()["complete"] is True
    assert (stage(client.env) / "tree" / "vacio.sav").read_bytes() == b""


@pytest.mark.parametrize("q", [{"size": "x"}, {"size": "-1"}, {"offset": "-1"}, {"sha256": "zz"}])
def test_bad_params_are_422(client, q):
    p = {"path": "a", "size": "1", "sha256": sha(b"a"), "offset": "0", "device": "deck", **q}
    r = anon(client).put("/api/hook/g1/files", params=p, content=b"a", headers=hdr(client))
    assert r.status_code == 422 and code(r) == "err.hook.param_invalid"


def test_odd_but_safe_names_are_accepted(client):
    for rel in ("a;b.sav", "it's.sav", "a&b.sav", "dir with space/x.sav"):
        assert put(client, rel, b"x").status_code == 200, rel
        assert (stage(client.env) / "tree" / rel).is_file()


# ---- 413 ----
def test_413_by_content_length(client, monkeypatch):
    monkeypatch.setattr(settings, "HOOK_MAX_FILE_BYTES", 10)
    r = put(client, "a.sav", b"x" * 20, size=5)  # `size` cabe; el Content-Length real no
    assert r.status_code == 413 and code(r) == "err.hook.file_too_large"
    assert r.json()["detail"]["params"] == {"max_mb": 10 / 1024 / 1024}
    assert not (stage(client.env) / "tree" / "a.sav").exists()


def test_413_by_declared_size(client, monkeypatch):
    monkeypatch.setattr(settings, "HOOK_MAX_FILE_BYTES", 10)
    r = put(client, "a.sav", b"x", size=11)
    assert r.status_code == 413 and code(r) == "err.hook.file_too_large"


def test_413_while_streaming_without_content_length(client, monkeypatch):
    monkeypatch.setattr(settings, "HOOK_MAX_FILE_BYTES", 10)

    def gen():  # chunked: no hay Content-Length
        for _ in range(5):
            yield b"abcd"

    r = anon(client).put(
        "/api/hook/g1/files",
        params={"path": "a.sav", "size": 5, "sha256": sha(b"x"), "device": "deck"},
        content=gen(),
        headers=hdr(client),
    )
    assert r.status_code == 413 and code(r) == "err.hook.file_too_large"
    st = stage(client.env)
    assert not (st / "tree" / "a.sav").exists() and not list((st / "parts").glob("*.part"))


def test_413_max_mb_is_a_whole_number_for_whole_mib(client, monkeypatch):
    monkeypatch.setattr(settings, "HOOK_MAX_FILE_BYTES", 2 * 1024 * 1024)
    r = put(client, "a.sav", b"x", size=2 * 1024 * 1024 + 1)
    assert r.json()["detail"]["params"] == {"max_mb": 2}


def test_upload_never_buffers_the_whole_body():
    import inspect

    from app.api.routers import hook

    src = inspect.getsource(hook.hook_upload)
    assert "request.stream()" in src and "request.body" not in src and "request.json" not in src


# ---- bloqueo, auth, dispositivo ----
def test_commit_manifest_download_with_game_lock_taken_is_409(client):
    """La subida ya no toma el lock del juego: solo lo toman el commit, el manifiesto y la descarga."""
    h = locking.acquire(client.env.data / "locks" / "g1.lock")
    try:
        assert put(client, "a.sav", b"x").status_code == 200
        assert code(commit(client, None, [e_of("a.sav", b"x")])) == "err.main.run_in_progress"
        assert code(anon(client).get("/api/hook/g1/manifest", params={"device": "deck"}, headers=hdr(client))) == (
            "err.main.run_in_progress"
        )
        assert code(get_file(client, "s.sav")) == "err.main.run_in_progress"
    finally:
        h.release()
    assert put(client, "a.sav", b"x").status_code == 200


def test_game_busy_guard_without_lock(client):
    client.app.state.ctx.runs.create("g1", False, "Mi Juego")
    assert code(put(client, "a.sav", b"x")) == "err.main.run_in_progress"
    assert code(commit(client, None, [])) == "err.main.run_in_progress"


def test_lock_is_released_after_each_upload(client):
    assert put(client, "a.sav", b"x").status_code == 200
    h = locking.acquire(client.env.data / "locks" / "g1.lock")  # si siguiera tomado, daría LockBusy
    h.release()


def _manifest(c, headers):
    return anon(c).get("/api/hook/g1/manifest", params={"device": "deck"}, headers=headers)


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer ck_nope"}])
@pytest.mark.parametrize(
    "call",
    [
        lambda c, h: put(c, "a.sav", b"x", headers=h),
        lambda c, h: commit(c, None, [], headers=h),
        lambda c, h: get_file(c, "a", headers=h),
        _manifest,
    ],
    ids=["upload", "commit", "download", "manifest"],
)
def test_401_everywhere(client, headers, call):
    r = call(client, headers)
    assert r.status_code == 401 and code(r) == "err.apikey.invalid"


def test_session_cookie_does_not_authorize(client):
    r = client.put(
        "/api/hook/g1/files", params={"path": "a", "size": 1, "sha256": sha(b"x"), "device": "deck"}, content=b"x"
    )
    assert r.status_code == 401


def test_other_device_is_403(client):
    assert code(put(client, "a.sav", b"x", device="pc")) == "err.apikey.device_mismatch"
    assert code(commit(client, None, [], device="pc")) == "err.apikey.device_mismatch"
    assert code(get_file(client, "a", device="pc")) == "err.apikey.device_mismatch"


def test_disabled_game_is_409(client):
    import yaml

    p = settings.CONFIG_PATH
    cfg = yaml.safe_load(p.read_text())
    cfg["games"]["g1"]["enabled"] = False
    p.write_text(yaml.safe_dump(cfg))
    assert put(client, "a.sav", b"x").status_code == 409
    assert code(put(client, "a.sav", b"x")) == "err.sync.game_disabled"


# ---- commit ----
def full_upload(c, files: dict):
    for rel, b in files.items():
        assert put(c, rel, b).status_code == 200
    return [e_of(rel, b, 2000) for rel, b in files.items()]


def test_commit_replaces_hub_and_records_everything(client):
    e = client.env
    e.write_hub("base")
    e.baseline()
    old_hash = fingerprint(e.hub).hash
    man = full_upload(client, {"s.sav": b"nuevo", "slot/x.dat": b"xx"})
    r = commit(client, old_hash, man)
    assert r.status_code == 200, r.text
    new = fingerprint(e.hub)
    assert (e.hub / "s.sav").read_bytes() == b"nuevo" and (e.hub / "slot" / "x.dat").read_bytes() == b"xx"
    assert r.json() == {
        "game": "g1",
        "device": "deck",
        "outcome": "ok",
        "hash": new.hash,
        "files": 2,
        "size": 7,
        "version": r.json()["version"],
    }
    assert int(os.stat(e.hub / "s.sav").st_mtime) == 2000  # mtime del manifiesto
    (v,) = list_versions(e.data, "g1")
    assert v["version"] == r.json()["version"] and v["sources"][0]["source"] == "hub"
    assert (e.data / "versions" / "g1" / v["version"] / "hub" / "s.sav").read_text() == "base"
    base = load_baseline(e.data, "g1")
    assert base["deck"] == new.hash and base["hub"] == new.hash
    (h,) = [x for x in history.read() if x["trigger"] == "hook"]
    assert h["device"] == "deck" and h["result"] == "ok" and h["games"]["g1"]["name"] == "Mi Juego"
    assert not stage(e).exists()
    # el hash resultante es el del manifiesto
    from app.sync.fingerprint import fingerprint_from_manifest

    assert new.hash == fingerprint_from_manifest(man).hash


def test_commit_first_upload_to_empty_hub(client):
    man = full_upload(client, {"s.sav": b"uno"})
    r = commit(client, None, man)
    assert r.status_code == 200 and "version" not in r.json()
    assert (client.env.hub / "s.sav").read_bytes() == b"uno" and list_versions(client.env.data, "g1") == []


def test_commit_removes_hub_files_not_in_manifest(client):
    e = client.env
    e.write_hub("base")
    e.baseline()
    (e.hub / "viejo.dat").write_text("v")
    h = fingerprint(e.hub).hash
    save_baseline(e.data, "g1", {"deck": h, "pc": h, "hub": h})
    man = full_upload(client, {"s.sav": b"nuevo"})
    assert commit(client, h, man).status_code == 200
    assert sorted(p.name for p in e.hub.iterdir()) == ["s.sav"]


def test_commit_ignores_staged_extras(client):
    man = full_upload(client, {"s.sav": b"a", "extra.dat": b"zz"})
    r = commit(client, None, man[:1])
    assert r.status_code == 200 and sorted(p.name for p in client.env.hub.iterdir()) == ["s.sav"]


def test_commit_with_stale_expect_is_409_and_hub_untouched(client):
    e = client.env
    e.write_hub("base")
    e.baseline()
    man = full_upload(client, {"s.sav": b"nuevo"})
    r = commit(client, "0" * 64, man)
    assert r.status_code == 409 and code(r) == "err.hook.hub_changed"
    assert (e.hub / "s.sav").read_text() == "base" and list_versions(e.data, "g1") == []
    assert (stage(e) / "tree" / "s.sav").exists()  # la subida sigue en staging


def test_commit_expect_null_but_hub_has_data_is_409(client):
    client.env.write_hub("base")
    man = full_upload(client, {"s.sav": b"nuevo"})
    assert code(commit(client, None, man)) == "err.hook.hub_changed"


def test_commit_incomplete_set_is_422(client):
    e = client.env
    e.write_hub("base")
    e.baseline()
    h = fingerprint(e.hub).hash
    man = full_upload(client, {"a.sav": b"a"})
    man.append(e_of("falta.sav", b"zz"))
    r = commit(client, h, man)
    assert r.status_code == 422 and code(r) == "err.hook.upload_incomplete"
    assert r.json()["detail"]["params"] == {"missing": 1, "paths": ["falta.sav"]}
    assert (e.hub / "s.sav").read_text() == "base"


def test_commit_staged_size_differs_from_manifest_is_incomplete(client):
    man = full_upload(client, {"a.sav": b"abc"})
    man[0]["size"] = 99
    assert code(commit(client, None, man)) == "err.hook.upload_incomplete"


def test_commit_set_hash_must_match_manifest(client):
    man = full_upload(client, {"a.sav": b"abc"})
    man[0]["sha256"] = sha(b"otra cosa")  # mismo tamaño, otro sha: el conjunto no cuadra
    r = commit(client, None, man)
    assert r.status_code == 422 and code(r) == "err.hook.set_mismatch"
    assert not client.env.hub.exists()


def test_commit_conflict_is_skipped(client):
    e = client.env
    e.write_hub("hub nuevo")
    e.baseline()
    h = fingerprint(e.hub).hash
    man = full_upload(client, {"s.sav": b"dev nuevo"})
    r = commit(client, h, man)
    assert r.status_code == 409 and code(r) == "err.hook.commit_rejected"
    assert r.json()["detail"]["params"] == {"reason": "both-changed"}
    assert (e.hub / "s.sav").read_text() == "hub nuevo" and list_versions(e.data, "g1") == []
    assert load_baseline(e.data, "g1")["deck"] != fingerprint(e.hub).hash


def test_commit_no_baseline_with_different_content_is_conflict(client):
    e = client.env
    e.write_hub("hub")
    man = full_upload(client, {"s.sav": b"dev"})
    r = commit(client, fingerprint(e.hub).hash, man)
    assert r.json()["detail"]["params"] == {"reason": "no-baseline"} and r.status_code == 409


def test_commit_when_hub_wins_is_rejected(client):
    e = client.env
    e.write_hub("hub nuevo")
    e.baseline()
    h = fingerprint(e.hub).hash
    man = full_upload(client, {"s.sav": b"base"})  # el dispositivo no cambió: debe BAJAR, no subir
    r = commit(client, h, man)
    assert r.status_code == 409 and r.json()["detail"]["params"] == {"reason": "hub"}
    assert (e.hub / "s.sav").read_text() == "hub nuevo"


def test_commit_identical_content_is_unchanged_and_remembers(client):
    e = client.env
    e.write_hub("igual")
    h = fingerprint(e.hub).hash
    man = full_upload(client, {"s.sav": b"igual"})
    r = commit(client, h, man)
    assert r.status_code == 200 and r.json()["outcome"] == "unchanged" and list_versions(e.data, "g1") == []
    assert load_baseline(e.data, "g1")["deck"] == h and not stage(e).exists()


def test_commit_body_shape(client):
    c = anon(client)
    for body in ([], {"manifest": []}, {"expect": 5, "manifest": []}, {"expect": None, "manifest": "x"}):
        r = c.post("/api/hook/g1/commit", params={"device": "deck"}, json=body, headers=hdr(client))
        assert r.status_code == 400 and code(r) == "err.main.json_body_required", body
    r = c.post("/api/hook/g1/commit", params={"device": "deck"}, content=b"no json", headers=hdr(client))
    assert code(r) == "err.main.json_body_required"
    assert code(commit(client, None, [{"path": "../x", "sha256": "0" * 64, "size": 0, "mtime": 0}])) == (
        "err.hook.manifest_path_invalid"
    )


def test_commit_prunes_versions(client):
    import yaml

    p = settings.CONFIG_PATH
    cfg = yaml.safe_load(p.read_text())
    cfg["max_versions"] = 1
    p.write_text(yaml.safe_dump(cfg))
    e = client.env
    e.write_hub("v0")
    e.baseline("v0")
    h = fingerprint(e.hub).hash
    names = []
    for i in range(1, 4):
        full_upload(client, {"s.sav": f"v{i}".encode()})
        r = commit(client, h, [e_of("s.sav", f"v{i}".encode(), 2000 + i)])
        assert r.status_code == 200, r.text
        h = r.json()["hash"]
        names.append(r.json()["version"])
    assert [v["version"] for v in list_versions(e.data, "g1")] == [names[-1]]  # solo queda la última


# ---- path traversal ----
BAD = ["../x", "a/../../x", "/etc/x", "a\\..\\..\\x", "..", "a/..", "", "a\0b"]


@pytest.mark.parametrize("rel", BAD)
def test_upload_rejects_unsafe_paths(client, rel):
    r = put(client, rel, b"x")
    assert r.status_code in (400, 422), (rel, r.status_code)
    assert code(r) in ("err.hook.file_path_invalid", "err.hook.param_invalid")
    assert not (client.env.data / "x").exists() and not (client.env.tmp / "x").exists()
    assert not list((client.env.data / "staging").rglob("x")) if (client.env.data / "staging").exists() else True


def test_upload_drive_path_stays_inside_staging(client):
    assert put(client, "C:/x", b"x").status_code == 200
    assert (stage(client.env) / "tree" / "C:" / "x").read_bytes() == b"x"


def test_upload_backslash_is_normalized(client):
    assert put(client, "a\\b.sav", b"x").status_code == 200
    assert (stage(client.env) / "tree" / "a" / "b.sav").is_file()


def test_upload_through_planted_symlink_is_rejected(client, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    tree = stage(client.env) / "tree"
    tree.mkdir(parents=True)
    (tree / "link").symlink_to(outside, target_is_directory=True)
    r = put(client, "link/x", b"x")
    assert r.status_code == 400 and code(r) == "err.hook.file_path_invalid"
    assert not (outside / "x").exists() and list(outside.iterdir()) == []


def test_upload_over_planted_symlink_file_is_rejected(client, tmp_path):
    target = tmp_path / "secret.txt"
    target.write_text("keep")
    tree = stage(client.env) / "tree"
    tree.mkdir(parents=True)
    (tree / "f").symlink_to(target)
    assert put(client, "f", b"pwned").status_code == 400
    assert target.read_text() == "keep"


def test_commit_never_copies_through_symlinks(client, tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("secreto")
    man = full_upload(client, {"a.sav": b"a"})
    (stage(client.env) / "tree" / "leak").symlink_to(secret)
    assert commit(client, None, man).status_code == 200
    assert sorted(p.name for p in client.env.hub.iterdir()) == ["a.sav"]


# ---- bajada ----
def test_manifest_matches_hub_fingerprint(client):
    e = client.env
    e.write_hub("base")
    (e.hub / "sub").mkdir()
    (e.hub / "sub" / "b.dat").write_bytes(b"bb")
    r = anon(client).get("/api/hook/g1/manifest", params={"device": "deck"}, headers=hdr(client))
    assert r.status_code == 200, r.text
    j, fp = r.json(), fingerprint(e.hub)
    assert (j["game"], j["device"], j["hash"], j["files"], j["size"]) == ("g1", "deck", fp.hash, 2, 6)
    assert {m["path"]: m["sha256"] for m in j["manifest"]} == {"s.sav": sha(b"base"), "sub/b.dat": sha(b"bb")}
    assert set(j["manifest"][0]) == {"path", "sha256", "size", "mtime"}


def test_manifest_of_empty_hub(client):
    r = anon(client).get("/api/hook/g1/manifest", params={"device": "deck"}, headers=hdr(client))
    assert r.status_code == 200 and r.json()["hash"] is None and r.json()["manifest"] == []


def test_download_full_and_ranges(client):
    e = client.env
    e.write_hub("0123456789")
    r = get_file(client, "s.sav")
    assert r.status_code == 200 and r.content == b"0123456789"
    assert r.headers["accept-ranges"] == "bytes" and r.headers["content-length"] == "10"
    r = get_file(client, "s.sav", rng="bytes=4-")
    assert r.status_code == 206 and r.content == b"456789" and r.headers["content-range"] == "bytes 4-9/10"
    r = get_file(client, "s.sav", rng="bytes=2-4")
    assert r.status_code == 206 and r.content == b"234" and r.headers["content-range"] == "bytes 2-4/10"
    r = get_file(client, "s.sav", rng="bytes=-3")
    assert r.status_code == 206 and r.content == b"789"
    r = get_file(client, "s.sav", rng="bytes=8-99")
    assert r.status_code == 206 and r.content == b"89" and r.headers["content-range"] == "bytes 8-9/10"


@pytest.mark.parametrize("rng", ["bytes=10-", "bytes=5-2", "bytes=0-1,3-4", "items=0-1", "bytes=a-b", "bytes=-0"])
def test_download_bad_range_is_416(client, rng):
    client.env.write_hub("0123456789")
    r = get_file(client, "s.sav", rng=rng)
    assert r.status_code == 416 and code(r) == "err.hook.range_invalid"
    assert r.headers["content-range"] == "bytes */10"


def test_download_unknown_file_and_directory_are_404(client):
    client.env.write_hub("x")
    (client.env.hub / "d").mkdir()
    assert get_file(client, "nope").status_code == 404 and code(get_file(client, "nope")) == "err.hook.file_unknown"
    assert get_file(client, "d").status_code == 404


@pytest.mark.parametrize("rel", ["../x", "a/../../x", "/etc/passwd", "a\\..\\..\\x", "..", "a\0b"])
def test_download_rejects_unsafe_paths(client, rel):
    client.env.write_hub("x")
    (client.env.data / "x").write_text("fuera del hub")
    r = get_file(client, rel)
    assert r.status_code in (400, 422) and code(r) in ("err.hook.file_path_invalid", "err.hook.param_invalid")


def test_download_through_symlinks_is_rejected(client, tmp_path):
    e = client.env
    e.write_hub("x")
    secret = tmp_path / "outside"
    secret.mkdir()
    (secret / "secret.txt").write_text("secreto")
    (e.hub / "dirlink").symlink_to(secret, target_is_directory=True)
    (e.hub / "filelink").symlink_to(secret / "secret.txt")
    for rel in ("dirlink/secret.txt", "filelink"):
        r = get_file(client, rel)
        assert r.status_code == 400 and code(r) == "err.hook.file_path_invalid", rel
        assert b"secreto" not in r.content


def test_download_drive_like_name_is_just_a_name(client):
    e = client.env
    e.write_hub("x")
    (e.hub / "C:").mkdir()
    (e.hub / "C:" / "x").write_text("ok")
    assert get_file(client, "C:/x").content == b"ok"


def test_full_round_trip_upload_then_other_device_state(client):
    """Subir, y después `fingerprint` del mismo contenido dice `none`: el baseline quedó puesto."""
    man = full_upload(client, {"s.sav": b"uno"})
    assert commit(client, None, man).status_code == 200
    r = anon(client).post("/api/hook/g1/fingerprint", params={"device": "deck"}, json=man, headers=hdr(client))
    assert r.json()["action"] == "none"
    man2 = [entry("s.sav", "dos", 3000)]
    assert (
        anon(client)
        .post("/api/hook/g1/fingerprint", params={"device": "deck"}, json=man2, headers=hdr(client))
        .json()["action"]
        == "upload"
    )


def test_download_through_symlink_that_stays_inside_is_also_rejected(client):
    e = client.env
    e.write_hub("x")
    (e.hub / "alias").symlink_to(e.hub / "s.sav")
    r = get_file(client, "alias")
    assert r.status_code == 400 and code(r) == "err.hook.file_path_invalid"


def test_download_size_comes_from_the_open_file_not_the_path(client):
    """Un commit reemplaza el fichero justo tras soltar el lock: Content-Length y cuerpo son los del fichero abierto."""
    from contextlib import contextmanager

    e = client.env
    (e.hub / "s.sav").parent.mkdir(parents=True, exist_ok=True)
    (e.hub / "s.sav").write_bytes(b"viejo")
    svc = client.app.state.ctx.hooks
    real = svc._lock

    @contextmanager
    def swapping(game):
        with real(game):
            yield
        tmp = e.hub / "s.new"
        tmp.write_bytes(b"muchisimo mas largo")
        os.replace(tmp, e.hub / "s.sav")  # el commit gana la carrera tras soltar el lock

    svc._lock = swapping
    r = get_file(client, "s.sav")
    assert r.status_code == 200 and r.content == b"viejo"
    assert r.headers["content-length"] == "5"
