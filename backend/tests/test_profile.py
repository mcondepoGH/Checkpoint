"""Perfil: nombre y foto (subida, tipo, tamaño, borrado, caché y sesión obligatoria)."""
import re
import struct

import pytest
from fastapi.testclient import TestClient

from app.users import avatar
from app.core import settings
from app.users.avatar import user_dir
from app.auth import Auth
from app.main import create_app

PW = "correct horse"
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 20 + b"\xff\xd9"
PNG = b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + b"\x00" * 17 + b"\x00\x00\x00\x00IEND\xaeB`\x82"
_body = b"WEBPVP8 " + b"\x00" * 20
WEBP = b"RIFF" + struct.pack("<I", len(_body)) + _body


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "CONFIG_PATH", tmp_path / "config" / "config.yaml")
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(settings, "STATIC_DIR", tmp_path / "static")
    c = TestClient(create_app(Auth("admin", PW, 1, rounds=4)))
    c.tmp = tmp_path
    return c


@pytest.fixture
def logged(client):
    assert client.post("/api/login", json={"user": "admin", "password": PW}).status_code == 200
    return client


def UD(c):
    """Carpeta de foto del admin (id derivado del nombre de usuario)."""
    return c.tmp / "data" / "profile" / avatar.user_id("admin")


def put(c, data, ctype="image/jpeg"):
    return c.put("/api/profile/photo", content=data, headers={"Content-Type": ctype})


def test_profile_requires_session(client):
    for m, p in [("get", "/api/profile"), ("get", "/api/profile/photo"), ("put", "/api/profile/photo"),
                 ("delete", "/api/profile/photo")]:
        assert getattr(client, m)(p).status_code == 401, p


def test_profile_name_and_no_photo(logged):
    assert logged.get("/api/profile").json() == {"name": "admin", "photo": None}
    r = logged.get("/api/profile/photo")
    assert r.status_code == 404 and r.json()["detail"]["code"] == "err.main.photo_unknown"


@pytest.mark.parametrize("data,ctype,ext", [(JPG, "image/jpeg", "jpg"), (PNG, "image/png", "png"), (WEBP, "image/webp", "webp")])
def test_upload_valid_roundtrip(logged, data, ctype, ext):
    r = put(logged, data, ctype)
    assert r.status_code == 200
    ver = r.json()["photo"]["version"]
    assert logged.get("/api/profile").json()["photo"] == {"version": ver}
    g = logged.get("/api/profile/photo")
    assert g.status_code == 200 and g.content == data and g.headers["content-type"] == ctype
    assert g.headers["x-content-type-options"] == "nosniff" and g.headers["etag"] == f'"{ver}"'
    assert g.headers["cache-control"] == "private, no-cache" and "sandbox" in g.headers["content-security-policy"]
    # nombre fijo en disco, sin nombre del cliente
    assert [p.name for p in UD(logged).iterdir()] == [f"photo.{ext}"]
    assert logged.get("/api/profile/photo", headers={"If-None-Match": f'"{ver}"'}).status_code == 304


def test_replace_removes_previous_format_and_changes_version(logged):
    v1 = put(logged, JPG).json()["photo"]["version"]
    v2 = put(logged, PNG, "image/png").json()["photo"]["version"]
    assert v1 != v2
    assert [p.name for p in UD(logged).iterdir()] == ["photo.png"]


def test_invalid_type(logged):
    for data, ctype in [(b"GIF89a....", "image/gif"), (b"<svg/>", "image/svg+xml"), (b"x", "text/plain"), (JPG, "")]:
        r = put(logged, data, ctype)
        assert r.status_code == 415 and r.json()["detail"]["code"] == "err.main.photo_type", ctype
    # el Content-Type declarado no basta: los bytes deben ser de ese tipo
    for data, ctype in [(b"not an image", "image/jpeg"), (PNG, "image/jpeg"), (b"\xff\xd8\xff truncado", "image/jpeg"),
                        (b"RIFF\x00\x00\x00\x00WEBP", "image/webp")]:
        r = put(logged, data, ctype)
        assert r.status_code == 415, (data, ctype)
    assert not (logged.tmp / "data" / "profile").exists()


def test_empty_and_too_large(logged):
    r = put(logged, b"")
    assert r.status_code == 400 and r.json()["detail"]["code"] == "err.main.photo_empty"
    big = JPG[:-2] + b"\x00" * avatar.MAX_BYTES + b"\xff\xd9"
    r = put(logged, big)
    assert r.status_code == 413 and r.json()["detail"]["code"] == "err.main.photo_too_large"
    # límite exacto: cabe
    ok = JPG[:-2] + b"\x00" * (avatar.MAX_BYTES - len(JPG)) + b"\xff\xd9"
    assert len(ok) == avatar.MAX_BYTES and put(logged, ok).status_code == 200


def test_too_large_without_content_length(logged):
    def gen():
        yield JPG[:-2]
        for _ in range(3):
            yield b"\x00" * (avatar.MAX_BYTES // 2)
    r = logged.put("/api/profile/photo", content=gen(), headers={"Content-Type": "image/jpeg"})
    assert r.status_code == 413


def test_delete(logged):
    assert logged.delete("/api/profile/photo").json() == {"ok": True, "photo": None}  # sin foto: idempotente
    put(logged, JPG)
    assert logged.delete("/api/profile/photo").status_code == 200
    assert logged.get("/api/profile").json()["photo"] is None
    assert logged.get("/api/profile/photo").status_code == 404


def test_foreign_origin_blocked_on_write(logged):
    r = logged.put("/api/profile/photo", content=JPG, headers={"Content-Type": "image/jpeg", "Origin": "http://evil.example"})
    assert r.status_code == 403
    r = logged.delete("/api/profile/photo", headers={"Origin": "http://evil.example"})
    assert r.status_code == 403


def test_tampered_file_on_disk_is_ignored(logged):
    d = UD(logged)
    d.mkdir(parents=True)
    (d / "photo.png").write_bytes(b"no soy un png")
    assert logged.get("/api/profile").json()["photo"] is None


def test_storage_under_user_id_folder(logged):
    put(logged, JPG)
    uid = avatar.user_id("admin")
    assert re.fullmatch(r"[0-9a-f]{32}", uid) and "admin" not in uid
    assert [p.name for p in (logged.tmp / "data" / "profile").iterdir()] == [uid]


def test_legacy_photo_migrated_on_first_access(logged):
    base = logged.tmp / "data" / "profile"
    base.mkdir(parents=True)
    (base / "photo.png").write_bytes(PNG)
    (base / ".photo-abc.tmp").write_bytes(b"x")
    ver = logged.get("/api/profile").json()["photo"]["version"]
    g = logged.get("/api/profile/photo")
    assert g.content == PNG and g.headers["etag"] == f'"{ver}"'
    assert sorted(p.name for p in base.iterdir()) == [avatar.user_id("admin")]
    assert [p.name for p in UD(logged).iterdir()] == ["photo.png"]


def test_legacy_photo_migrated_at_startup(logged):
    base = logged.tmp / "data" / "profile"
    base.mkdir(parents=True)
    (base / "photo.jpg").write_bytes(JPG)
    assert avatar.migrate_legacy("admin") is True
    assert not (base / "photo.jpg").exists() and (UD(logged) / "photo.jpg").read_bytes() == JPG
    assert avatar.migrate_legacy("admin") is False  # idempotente


def test_legacy_does_not_overwrite_existing_and_leaves_no_orphans(logged):
    put(logged, PNG, "image/png")
    base = logged.tmp / "data" / "profile"
    (base / "photo.jpg").write_bytes(JPG)
    assert logged.get("/api/profile/photo").content == PNG
    assert [p.name for p in base.iterdir()] == [avatar.user_id("admin")]


def test_legacy_invalid_is_removed(logged):
    base = logged.tmp / "data" / "profile"
    base.mkdir(parents=True)
    (base / "photo.png").write_bytes(b"basura")
    assert logged.get("/api/profile").json()["photo"] is None
    assert list(base.iterdir()) == []


def test_lifespan_runs_migration(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "CONFIG_PATH", tmp_path / "config" / "config.yaml")
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(settings, "STATIC_DIR", tmp_path / "static")
    (tmp_path / "data" / "profile").mkdir(parents=True)
    (tmp_path / "data" / "profile" / "photo.jpg").write_bytes(JPG)
    with TestClient(create_app(Auth("admin", PW, 1, rounds=4))):
        assert (user_dir("admin") / "photo.jpg").is_file()
        assert not (tmp_path / "data" / "profile" / "photo.jpg").exists()
