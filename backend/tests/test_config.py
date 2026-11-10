import pytest
from pydantic import ValidationError

from app.config import load_config, name_error, normalize_path, parse_config, validate_config
from fakes import save_config

BASE = {
    "devices": {"pc": {"name": "Equipo A", "host": "192.0.2.10", "user": "u", "os": "windows"},
                "laptop": {"name": "Equipo B", "host": "192.0.2.11", "user": "laptop", "os": "linux"}},
    "games": {"g": {"name": "Juego de prueba", "devices": ["pc", "laptop"],
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
    mod(games__g__devices=["pc", "laptop", "pc"]),
    mod(games__g__devices=[]),
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


def test_steamos_is_no_longer_an_os():
    with pytest.raises(ValidationError):
        parse_config(mod(devices__laptop__os="steamos"))
    _, e = validate_config(mod(devices__laptop__os="steamos"))
    assert "devices.laptop.os" in e


@pytest.mark.parametrize("section,key", [("devices", "pc"), ("games", "g")])
def test_name_is_required_with_clear_error(section, key):
    d = mod()
    del d[section][key]["name"]
    with pytest.raises(ValidationError, match="name"):
        parse_config(d)
    cfg, e = validate_config(d)
    assert cfg is None and e[f"{section}.{key}.name"] == {"code": "err.config.name_missing", "params": {}}
    d[section][key]["name"] = None
    assert validate_config(d)[1][f"{section}.{key}.name"] == {"code": "err.config.name_missing", "params": {}}


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
    ok = {"code": "err.config.versions_range", "params": {"max": 1000}}
    assert e["max_versions"] == ok and e["games.g.keep_versions"] == ok
    _, e = validate_config(mod(max_versions=True, games__g__keep_versions=1.5))
    ok = {"code": "err.config.int", "params": {}}
    assert e["max_versions"] == ok and e["games.g.keep_versions"] == ok


def test_save_roundtrip_without_override(tmp_path):
    c = parse_config(mod(max_versions=9))
    save_config(tmp_path / "c.yaml", c)
    assert "keep_versions" not in (tmp_path / "c.yaml").read_text()
    assert load_config(tmp_path / "c.yaml").max_versions == 9


def test_bad_ids():
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
    d = mod(devices__pc__name=n, games__g__name=n + "!" if len(n) < 64 else "otro")
    c = parse_config(d)
    assert c.devices["pc"].name == n and "pc" in c.devices and "g" in c.games


@pytest.mark.parametrize("n", ["", "   ", " x", "x ", "a  b", "a/b", "a\\b", "../x", "..", "...", "a\nb", "a\x00b",
                              "a\tb", "a\u00a0b", "a\u2028b", "a" * 65, 5, None])
def test_bad_free_names(n):
    assert name_error(n)
    with pytest.raises(ValidationError):
        parse_config(mod(games__g__name=n))


def test_duplicate_names_rejected_case_insensitive():
    for dup in ("juego de prueba", "JUEGO DE PRUEBA"):
        d = mod()
        d["games"]["g2"] = {**d["games"]["g"], "name": dup}
        with pytest.raises(ValidationError):
            parse_config(d)
    d = mod()
    d["games"]["g2"] = {**d["games"]["g"], "name": "Juego de prueba 2"}
    assert set(parse_config(d).games) == {"g", "g2"}


def test_device_id_hub_reserved():
    d = mod()
    d["devices"]["hub"] = d["devices"].pop("pc")
    d["games"]["g"]["devices"] = ["hub", "laptop"]
    d["games"]["g"]["paths"] = {"hub": "C:/a", "laptop": "/x/y"}
    with pytest.raises(ValidationError):
        parse_config(d)


def test_yaml_roundtrip_special_names(tmp_path):
    d = mod(games__g__name="Mi Juego: Edición")
    d["games"]["123"] = {**d["games"]["g"], "name": "123"}
    p = tmp_path / "c.yaml"
    save_config(p, parse_config(d))
    assert {g.name for g in load_config(p).games.values()} == {"Mi Juego: Edición", "123"}


def test_un_dispositivo_es_valido_y_se_normaliza():
    c = parse_config(mod(games__g__devices=["pc"], games__g__paths={"pc": "C:\\Users\\u\\Saves"}))
    assert c.games["g"].devices == ["pc"] and c.games["g"].paths == {"pc": "C:/Users/u/Saves"}


@pytest.mark.parametrize("devs", [[], ["pc", "laptop", "pc"]])
def test_numero_de_dispositivos_fuera_de_1_o_2(devs):
    _, errs = validate_config(mod(games__g__devices=devs))
    assert errs["games.g.devices"]["code"] == "err.config.devices_count"


def test_un_dispositivo_sin_ruta_falla():
    _, errs = validate_config(mod(games__g__devices=["pc"], games__g__paths={}))
    assert errs["games.g.paths.pc"]["code"] == "err.config.path_missing"


# ---------- juego desactivado (enabled) ----------
def test_enabled_default_true_and_old_config():
    assert parse_config(BASE).games["g"].enabled is True


def test_enabled_false_loads():
    assert parse_config(mod(games__g__enabled=False)).games["g"].enabled is False


def test_enabled_serializer_only_writes_false():
    on = parse_config(BASE).model_dump(exclude_none=True)["games"]["g"]
    off = parse_config(mod(games__g__enabled=False)).model_dump(exclude_none=True)["games"]["g"]
    assert "enabled" not in on
    assert off["enabled"] is False


def test_enabled_not_bool_is_bool_required():
    from app.config import semantic_errors
    errs = dict(semantic_errors(BASE["devices"], mod(games__g__enabled="no")["games"]))
    assert errs["games.g.enabled"]["code"] == "err.config.bool_required"
    with pytest.raises(ValidationError):
        parse_config(mod(games__g__enabled="no"))
