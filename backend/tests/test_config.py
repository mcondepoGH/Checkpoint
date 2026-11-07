import pytest
from pydantic import ValidationError

from app.config import load_config, normalize_path, parse_config, save_config

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
    assert c.games["g"].keep_versions == 5


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
    mod(games__g__keep_versions=0),
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
