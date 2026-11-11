"""Contrato i18n de config/configstore: errores como {code, params}, sin texto en español."""
import re
from pathlib import Path

import pytest

from app.config import models as C
from app.config.models import ConfigError, name_error, normalize_path, resolve_ref, validate_config
from app.config.store import Conflict, InvalidConfig, parse_text

DEV = {"name": "PC", "host": "h", "user": "u", "os": "linux"}


def code(e):
    return e["code"], e["params"]


def test_name_error_codes():
    assert code(name_error(None)) == ("err.config.name_missing", {})
    assert code(name_error(5)) == ("err.config.name_not_text", {})
    assert code(name_error("  ")) == ("err.config.name_empty", {})
    assert code(name_error(" a")) == ("err.config.name_spaces", {})
    assert code(name_error("a" * 65)) == ("err.config.name_too_long", {"max": 64})
    assert code(name_error("a/b")) == ("err.config.name_slash", {})
    assert code(name_error("a\x01")) == ("err.config.name_control", {})
    assert code(name_error("..")) == ("err.config.name_dots", {})
    assert name_error("Zelda") is None


def test_normalize_path_raises_config_error_with_code():
    for os_name, p, c in [("linux", "rel", "err.config.path_absolute"), ("windows", "/x", "err.config.path_windows"),
                          ("linux", "/a/../b", "err.config.path_dotdot"), ("linux", "/", "err.config.path_root"),
                          ("linux", "/a;b", "err.config.path_chars"), ("linux", 5, "err.config.path_text")]:
        with pytest.raises(ConfigError) as e:
            normalize_path(os_name, p)
        assert e.value.code == c


def test_resolve_ref_ambiguous_has_code_and_matches():
    class It:
        def __init__(self, n): self.name = n
    with pytest.raises(ConfigError) as e:
        resolve_ref({"a": It("Dup"), "b": It("Dup")}, "Dup")
    assert e.value.code == "err.config.ref_ambiguous" and e.value.params["ref"] == "Dup"
    assert "(a)" in e.value.params["matches"] and "(b)" in e.value.params["matches"]
    assert e.value.body() == {"code": e.value.code, "params": e.value.params}


def test_validate_config_errors_are_bodies():
    _, errs = validate_config({"devices": {"a": {**DEV, "host": "bad host!"}, "b": {**DEV, "name": "B", "port": 70000}}})
    assert code(errs["devices.a.host"]) == ("err.config.host_invalid", {})
    assert code(errs["devices.b.port"]) == ("err.config.port_range", {})
    _, errs = validate_config({"max_versions": 5000, "devices": {"a": {"os": "mac"}}, "x": 1})
    assert code(errs["max_versions"]) == ("err.config.versions_range", {"max": 1000})
    assert code(errs["devices.a.os"]) == ("err.config.os_invalid", {"options": "windows, linux"})
    assert code(errs["devices.a.name"])[0] == "err.config.name_missing"
    assert code(errs["x"]) == ("err.config.extra", {})
    assert code(validate_config([])[1][""]) == ("err.config.not_map", {})


def test_semantic_codes():
    d = {"a": {**DEV}, "b": {**DEV, "name": "B"}}
    _, errs = validate_config({"devices": d, "games": {"g": {"name": "G", "devices": ["a", "a"], "paths": {"a": "/x"}}}})
    assert code(errs["games.g.devices.1"]) == ("err.config.device_same", {})
    _, errs = validate_config({"devices": d, "games": {"g": {"name": "G", "devices": ["a", "zz"], "paths": {"a": "/x", "q": "/y"}}}})
    assert code(errs["games.g.devices.1"]) == ("err.config.device_unknown", {"id": "zz"})
    assert code(errs["games.g.paths.q"]) == ("err.config.path_device_unknown", {})
    _, errs = validate_config({"devices": {"a": {**DEV}, "b": {**DEV}}})
    assert code(errs["devices.b.name"]) == ("err.config.name_duplicate", {"other": "PC"})


def test_parse_text_error_bodies():
    cfg, err = parse_text("a: [")
    assert cfg is None and err["code"] in ("err.config.yaml_syntax", "err.config.yaml_malformed")
    cfg, err = parse_text("devices:\n  a: {}\n  a: {}\n")
    assert err["code"] == "err.config.yaml_duplicate_key" and err["params"]["key"] == "a"
    cfg, err = parse_text("devices:\n  a: {name: X, os: linux, host: 'bad host', user: u}\n")
    assert err["code"] == "err.configstore.invalid"
    assert {"path": "devices.a.host", "code": "err.config.host_invalid", "params": {}} in err["params"]["causes"]
    assert parse_text("")[1] is None


def test_configstore_exceptions_carry_code():
    assert Conflict("v").code == "err.configstore.conflict" and Conflict("v").params == {}
    e = InvalidConfig({"x": {"code": "err.config.required", "params": {}}})
    assert e.code == "err.configstore.invalid" and e.errors["x"]["code"] == "err.config.required"


def test_no_spanish_in_emitted_errors():
    _, errs = validate_config({"devices": {"a": {"os": "mac", "host": 1}}, "games": {"g": 1}, "max_versions": "x"})
    for e in errs.values():
        assert re.fullmatch(r"err\.config\.[a-z_]+", e["code"]), e
        assert not any(ord(ch) > 127 for ch in str(e["params"])), e


def test_codes_in_es_json():
    import json
    es = json.loads((Path(__file__).parents[2] / "frontend/src/locales/es.json").read_text())
    src = "".join((Path(C.__file__).parent / f).read_text() for f in ("models.py", "store.py"))
    codes = set(re.findall(r'"(err\.(?:config|configstore)\.[a-z_]+)"', src))
    assert len(codes) > 30
    for c in codes:
        v = es
        for part in c.split("."):
            v = v.get(part) if isinstance(v, dict) else None
        assert isinstance(v, str), c
