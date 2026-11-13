"""Appid de Steam por juego (`steam_appid`): modelo, validación, duplicados, serialización y `GET /api/games`."""

import copy

import pytest
import yaml

from app.config.models import Config, parse_config, validate_config
from app.config.store import parse_text
from test_device_apikey import CFG, bearer, call, cl  # noqa: F401 (fixture cl)

DEV = {"name": "PC", "host": "h", "user": "u", "os": "linux"}


def cfg_with(**games):
    return {
        "devices": {"pc": DEV},
        "games": {
            gid: {"name": gid.upper(), "devices": ["pc"], "paths": {"pc": "/p/" + gid}, **g} for gid, g in games.items()
        },
    }


def test_default_is_none_and_valid_value_kept():
    c = parse_config(cfg_with(a={}, b={"steam_appid": 1245620}))
    assert c.games["a"].steam_appid is None and c.games["b"].steam_appid == 1245620


def test_none_is_not_written():
    c = parse_config(cfg_with(a={}, b={"steam_appid": 7}))
    d = c.model_dump(exclude_none=True)
    assert "steam_appid" not in d["games"]["a"] and d["games"]["b"]["steam_appid"] == 7


def test_explicit_null_is_same_as_absent():
    c = parse_config(cfg_with(a={"steam_appid": None}))
    assert c.games["a"].steam_appid is None
    assert "steam_appid" not in c.model_dump(exclude_none=True)["games"]["a"]


def test_yaml_round_trip(tmp_path):
    text = yaml.safe_dump(cfg_with(a={"steam_appid": 440}, b={}))
    c, err = parse_text(text)
    assert err is None
    again, err = parse_text(yaml.safe_dump(c.model_dump(exclude_none=True)))
    assert err is None
    assert again.games["a"].steam_appid == 440 and again.games["b"].steam_appid is None
    assert again.model_dump(exclude_none=True) == c.model_dump(exclude_none=True)


@pytest.mark.parametrize("bad", [0, -1, -440, "440", "", True, False, 1.5, 440.0, [1], {"a": 1}])
def test_invalid_values_rejected_with_code(bad):
    c, errs = validate_config(cfg_with(a={"steam_appid": bad}))
    assert c is None
    assert errs["games.a.steam_appid"] == {"code": "err.config.steam_appid_invalid", "params": {}}


def test_unknown_field_still_forbidden():
    _, errs = validate_config(cfg_with(a={"steam_id": 5}))
    assert errs["games.a.steam_id"]["code"] == "err.config.extra"


def test_duplicate_appid_names_the_other_game():
    c, errs = validate_config(cfg_with(a={"steam_appid": 440}, b={"steam_appid": 440}, c={"steam_appid": 441}))
    assert c is None
    assert errs == {"games.b.steam_appid": {"code": "err.config.steam_appid_duplicate", "params": {"other": "A"}}}


def test_duplicate_reported_even_if_other_field_fails():
    data = cfg_with(a={"steam_appid": 440}, b={"steam_appid": 440, "keep_versions": 5000})
    _, errs = validate_config(data)
    assert errs["games.b.steam_appid"]["code"] == "err.config.steam_appid_duplicate"
    assert errs["games.b.keep_versions"]["code"] == "err.config.versions_range"


def test_invalid_values_do_not_count_as_duplicates():
    _, errs = validate_config(
        cfg_with(a={"steam_appid": 0}, b={"steam_appid": 0}, c={"steam_appid": "5"}, d={"steam_appid": "5"})
    )
    assert {v["code"] for v in errs.values()} == {"err.config.steam_appid_invalid"}


def test_two_games_without_appid_are_fine():
    c, errs = validate_config(cfg_with(a={}, b={}))
    assert errs == {} and isinstance(c, Config)


# --- GET /api/games ---


def games(c, key):
    return call(c, key, "get", "/api/games")


def with_appids(c, appids):
    cfg = copy.deepcopy(CFG)
    for gid, a in appids.items():
        cfg["games"][gid]["steam_appid"] = a
    from app.core import settings

    settings.CONFIG_PATH.write_text(yaml.safe_dump(cfg, allow_unicode=True))


def test_user_key_sees_steam_appid_or_null(cl):
    with_appids(cl, {"g1": 1245620})
    j = games(cl, cl.user).json()
    by = {g["id"]: g for g in j}
    assert set(by["g1"]) == {"id", "name", "enabled", "status", "steam_appid"}
    assert by["g1"]["steam_appid"] == 1245620
    assert by["g2"]["steam_appid"] is None and "steam_appid" in by["g2"]


def test_device_key_sees_only_its_games_with_appid(cl):
    with_appids(cl, {"g1": 1245620, "g2": 220})
    j = games(cl, cl.deck).json()
    assert [(g["id"], g["steam_appid"]) for g in j] == [("g1", 1245620)]
    j = games(cl, cl.lap).json()
    assert [(g["id"], g["steam_appid"]) for g in j] == [("g2", 220)]


def test_device_key_cannot_write_config(cl):
    body = {"devices": {}, "games": {}}
    for m, p in (("put", "/api/config"), ("post", "/api/config/yaml"), ("post", "/api/config/validate")):
        r = getattr(cl.__class__(cl.app), m)(p, headers=bearer(cl.deck), json=body)
        assert r.status_code in (401, 403), (m, p, r.status_code)
