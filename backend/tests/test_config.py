import pytest
from pydantic import ValidationError

from app.config import load_config, name_error, normalize_path, parse_config, save_config, slug_for

BASE = {
    "devices": {"pc": {"host": "192.0.2.10", "user": "u", "os": "windows"},
                "laptop": {"host": "192.0.2.11", "user": "laptop", "os": "linux"}},
    "games": {"g": {"devices": ["pc", "laptop"],
                    "paths": {"pc": "C:\\Users\\u\\Saves", "laptop": "/home/usuario/saves"},
                    "process": "game.exe"}},
}


def mod(**kw):
    import copy
    d = copy.deepcopy(BASE)
    for k, v in kw.items():
        cur = d
        *ks, last = k.split("__")
        for x in ks:
            cur = cur[x]
        cur[last] = v
    return d


def test_valid_and_normalizes():
    c = parse_config(BASE)
    assert c.games["g"].paths["pc"] == "C:/Users/u/Saves"
    assert c.games["g"].keep_versions is None and c.max_versions == 20
    assert c.versions_limit("g") == 20


@pytest.mark.parametrize("bad", [
    mod(games__g__devices=["pc", "pc"]),
    mod(games__g__devices=["pc"]),
    mod(games__g__devices=["pc", "nope"]),
    mod(games__g__paths={"pc": "C:/a", "other": "/x"}),
    mod(games__g__paths={"pc": "C:/a/../b", "laptop": "/x/y"}),
    mod(games__g__paths={"pc": "C:/a", "laptop": "rel/path"}),
    mod(games__g__paths={"pc": "C:/a", "laptop": "/x; rm -rf /"}),
    mod(games__g__paths={"pc": "C:/a", "laptop": "/x/$(id)"}),
    mod(games__g__paths={"pc": "C:/a&calc", "laptop": "/x/y"}),
    mod(games__g__paths={"pc": "relative", "laptop": "/x/y"}),
    mod(games__g__paths={"pc": "C:/", "laptop": "/x/y"}),
    mod(games__g__process="a;b"),
    mod(games__g__keep_versions=-1),
    mod(games__g__keep_versions=1001),
    mod(games__g__keep_versions=True),
    mod(games__g__keep_versions=2.5),
    mod(games__g__keep_versions="5"),
    mod(max_versions=-1),
    mod(max_versions=1001),
    mod(max_versions=False),
    mod(max_versions="x"),
    mod(max_versions=None),
    mod(devices__pc__host="-oProxyCommand=x"),
    mod(devices__pc__user="a b"),
    mod(devices__pc__os="plan9"),
    mod(devices__pc__port=70000),
])
def test_invalid(bad):
    with pytest.raises(ValidationError):
        parse_config(bad)


def test_legacy_os_alias_still_valid():
    c = parse_config(mod(devices__laptop__os="steamos"))
    assert c.devices["laptop"].os == "steamos"


def test_versions_limit_global_override_and_zero():
    assert parse_config(mod(max_versions=7)).versions_limit("g") == 7
    c = parse_config(mod(max_versions=7, games__g__keep_versions=3))
    assert c.versions_limit("g") == 3
    assert parse_config(mod(max_versions=0)).versions_limit("g") == 0
    assert parse_config(mod(max_versions=7, games__g__keep_versions=0)).versions_limit("g") == 0
    assert parse_config(mod(max_versions=1000, games__g__keep_versions=1000)).versions_limit("g") == 1000


def test_versions_limit_error_messages():
    from app.config import validate_config
    _, e = validate_config(mod(max_versions=-1, games__g__keep_versions=2000))
    assert "entre 0 y 1000" in e["max_versions"] and "entre 0 y 1000" in e["games.g.keep_versions"]
    _, e = validate_config(mod(max_versions=True, games__g__keep_versions=1.5))
    assert e["max_versions"] == "debe ser un número entero" and e["games.g.keep_versions"] == "debe ser un número entero"


def test_save_roundtrip_without_override(tmp_path):
    c = parse_config(mod(max_versions=9))
    save_config(tmp_path / "c.yaml", c)
    assert "keep_versions" not in (tmp_path / "c.yaml").read_text()
    assert load_config(tmp_path / "c.yaml").max_versions == 9


def test_bad_names():
    d = mod()
    d["games"]["../x"] = d["games"].pop("g")
    with pytest.raises(ValidationError):
        parse_config(d)


def test_extra_keys_rejected():
    with pytest.raises(ValidationError):
        parse_config(mod(devices__pc__extra=1))


def test_normalize_posix():
    assert normalize_path("linux", "/a//b/./c/") == "/a/b/c"


def test_atomic_roundtrip(tmp_path):
    p = tmp_path / "config.yaml"
    save_config(p, parse_config(BASE))
    assert load_config(p) == parse_config(BASE)
    assert [f.name for f in tmp_path.iterdir()] == ["config.yaml"]  # sin temporales


FREE = ["Mi Juego: Edición", "Mi PC (salón)", "Nintendo Switch & Co", "It's \"x\"", "Pokémon 🎮",
        "Mi-Juego-VII", "A.B", "👩\u200d💻 Dev", "a" * 64]


@pytest.mark.parametrize("n", FREE)
def test_free_names_ok(n):
    assert name_error(n) is None
    d = mod()
    d["devices"][n] = d["devices"].pop("pc")
    d["games"]["g"]["devices"] = [n, "laptop"]
    d["games"]["g"]["paths"] = {n: "C:/a", "laptop": "/x/y"}
    d["games"][n] = d["games"].pop("g")
    c = parse_config(d)  # formato antiguo: el id es slug_for(clave) y el nombre la clave
    assert c.devices[slug_for(n)].name == n and c.games[slug_for(n)].name == n


@pytest.mark.parametrize("n", ["", "   ", " x", "x ", "a  b", "a/b", "a\\b", "../x", "..", "...", "a\nb", "a\x00b",
                              "a\tb", "a\u00a0b", "a\u2028b", "a" * 65, 5, None])
def test_bad_free_names(n):
    assert name_error(n)
    d = mod()
    d["games"][n] = d["games"].pop("g")
    with pytest.raises(ValidationError):
        parse_config(d)


def test_slug_legacy_identical_and_safe():
    for n in ["Mi-Juego-VII", "MiPC", "MiJuego", "a_b-1", "g"]:
        assert slug_for(n) == n
    import re
    for n in FREE[:5] + ["../x", "con", "🎮", "日本語"]:
        s = slug_for(n)
        assert re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", s), s
        assert slug_for(n) == s  # estable
    assert slug_for("A B") != slug_for("A-B") == "A-B"
    assert slug_for("🎮").startswith("item-")


def test_slug_collisions_and_dupes_rejected():
    for dup in ("mi juego", "MI JUEGO"):
        d = mod()
        d["games"]["Mi Juego"] = d["games"]["g"]
        d["games"][dup] = d["games"]["g"]
        with pytest.raises(ValidationError):
            parse_config(d)
    d = mod()
    d["games"]["A B"] = d["games"]["g"]
    d["games"]["A-B"] = d["games"]["g"]  # slugs distintos: válido
    c = parse_config(d)  # ids distintos aunque los nombres se parezcan
    assert {g.name for g in c.games.values()} >= {"A B", "A-B"} and slug_for("A B") in c.games


def test_device_named_hub_reserved():
    d = mod()
    d["devices"]["hub"] = d["devices"].pop("pc")
    d["games"]["g"]["devices"] = ["hub", "laptop"]
    d["games"]["g"]["paths"] = {"hub": "C:/a", "laptop": "/x/y"}
    with pytest.raises(ValidationError):
        parse_config(d)


def test_yaml_roundtrip_special_names(tmp_path):
    d = mod()
    d["games"]["Mi Juego: Edición"] = d["games"].pop("g")
    d["games"]["123"] = dict(d["games"]["Mi Juego: Edición"])
    p = tmp_path / "c.yaml"
    save_config(p, parse_config(d))
    assert {g.name for g in load_config(p).games.values()} == {"Mi Juego: Edición", "123"}
