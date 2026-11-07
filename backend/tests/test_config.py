import pytest
from pydantic import ValidationError

from app.config import load_config, normalize_path, parse_config, save_config

BASE = {
    "devices": {"pc": {"host": "192.0.2.10", "user": "u", "os": "windows"},
                "deck": {"host": "192.0.2.11", "user": "deck", "os": "steamos"}},
    "games": {"g": {"devices": ["pc", "deck"],
                    "paths": {"pc": "C:\\Users\\u\\Saves", "deck": "/home/deck/saves"},
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
    mod(games__g__paths={"pc": "C:/a/../b", "deck": "/x/y"}),
    mod(games__g__paths={"pc": "C:/a", "deck": "rel/path"}),
    mod(games__g__paths={"pc": "C:/a", "deck": "/x; rm -rf /"}),
    mod(games__g__paths={"pc": "C:/a", "deck": "/x/$(id)"}),
    mod(games__g__paths={"pc": "C:/a&calc", "deck": "/x/y"}),
    mod(games__g__paths={"pc": "relative", "deck": "/x/y"}),
    mod(games__g__paths={"pc": "C:/", "deck": "/x/y"}),
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


def test_bad_names():
    d = mod()
    d["games"]["../x"] = d["games"].pop("g")
    with pytest.raises(ValidationError):
        parse_config(d)


def test_extra_keys_rejected():
    with pytest.raises(ValidationError):
        parse_config(mod(devices__pc__extra=1))


def test_normalize_posix():
    assert normalize_path("steamos", "/a//b/./c/") == "/a/b/c"


def test_atomic_roundtrip(tmp_path):
    p = tmp_path / "config.yaml"
    save_config(p, parse_config(BASE))
    assert load_config(p) == parse_config(BASE)
    assert [f.name for f in tmp_path.iterdir()] == ["config.yaml"]  # sin temporales
