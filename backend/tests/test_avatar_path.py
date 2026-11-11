"""Resolución de la carpeta de foto por usuario: id seguro para cualquier nombre."""

import re

import pytest

from app.users import avatar
from app.core import settings

HOSTILE = [
    "../../etc/passwd",
    "..",
    ".",
    "a/b",
    "a\\b",
    "/abs",
    "..\\..",
    "ñandú",
    "管理员",
    "A\x00B",
    "x" * 5000,
    " admin ",
    "Admin",
    "admin\n",
    "\ud800",
    "%2e%2e%2f",
    "con:aux",
    "-rf",
]


@pytest.fixture(autouse=True)
def data(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path / "data")
    return tmp_path / "data"


@pytest.mark.parametrize("name", HOSTILE + ["admin"])
def test_id_is_safe_fixed_charset(name):
    uid = avatar.user_id(name)
    assert re.fullmatch(r"[0-9a-f]{32}", uid)


@pytest.mark.parametrize("name", HOSTILE + ["admin"])
def test_dir_is_direct_child_of_profile(name, data):
    d = avatar.user_dir(name)
    assert d.parent == data / "profile" and d.name == avatar.user_id(name)
    assert d.resolve().parent == (data / "profile").resolve()


def test_stable_and_distinct():
    assert avatar.user_id("admin") == avatar.user_id("admin")
    assert len({avatar.user_id(n) for n in HOSTILE + ["admin"]}) == len(HOSTILE) + 1
    assert avatar.user_id("Admin") != avatar.user_id("admin")


@pytest.mark.parametrize("bad", ["", "   ", "\t\n", None, 5, b"admin"])
def test_empty_or_non_string_rejected(bad):
    with pytest.raises(ValueError):
        avatar.user_id(bad)
    with pytest.raises(ValueError):
        avatar.user_dir(bad)


def test_save_with_hostile_name_stays_inside(data):
    jpg = b"\xff\xd8\xff\xe0" + b"\x00" * 20 + b"\xff\xd9"
    avatar.save(jpg, "image/jpeg", "../../evil")
    assert [p.name for p in (data / "profile").iterdir()] == [avatar.user_id("../../evil")]
    assert not (data.parent / "evil").exists() and not (data / "evil").exists()
    assert avatar.load("../../evil")[0] == jpg and avatar.load("admin") is None
