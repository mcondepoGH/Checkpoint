"""Dispositivo `local: true` ("Este equipo"): modelo, validación, YAML y diff."""

import pytest
import yaml

from app.config.models import load_yaml, parse_config, validate_config
from app.config.store import diff_configs, parse_text, render_yaml
from fakes import save_config

REMOTE = {"name": "Laptop", "host": "192.0.2.10", "user": "usuario", "os": "linux", "port": 2222}


def cfg_dict(**extra_dev):
    d = {
        "devices": {"pc-aaaa1111": {"name": "PC", "local": True, "os": "linux"}, "laptop-bbbb2222": dict(REMOTE)},
        "games": {
            "g-cccc3333": {
                "name": "Juego",
                "devices": ["pc-aaaa1111", "laptop-bbbb2222"],
                "paths": {"pc-aaaa1111": "/home/usuario/saves", "laptop-bbbb2222": "/home/usuario/g"},
            }
        },
    }
    d["devices"]["pc-aaaa1111"].update(extra_dev)
    return d


def test_local_valido_en_native():
    c = parse_config(cfg_dict())
    dev = c.devices["pc-aaaa1111"]
    assert dev.local and dev.host is None and dev.user is None and dev.port is None


def test_local_dump_sin_host_user_port():
    c = parse_config(cfg_dict())
    assert c.devices["pc-aaaa1111"].model_dump(exclude_none=True) == {"name": "PC", "local": True, "os": "linux"}


def test_remoto_dump_identico_a_antes_sin_campo_local():
    c = parse_config(cfg_dict())
    assert c.devices["laptop-bbbb2222"].model_dump(exclude_none=True) == REMOTE
    assert list(c.devices["laptop-bbbb2222"].model_dump()) == ["name", "host", "user", "os", "port"]


def test_remoto_sin_local_y_local_false_equivalentes():
    a = parse_config({"devices": {"x": {"name": "X", **{k: v for k, v in REMOTE.items() if k != "name"}}}})
    b = parse_config(
        {"devices": {"x": {"name": "X", "local": False, **{k: v for k, v in REMOTE.items() if k != "name"}}}}
    )
    assert a == b and a.devices["x"].local is False
    assert "local" not in a.devices["x"].model_dump()


def test_remoto_puerto_por_defecto_22():
    c = parse_config({"devices": {"x": {"name": "X", "host": "h", "user": "u", "os": "linux"}}})
    assert c.devices["x"].port == 22


@pytest.mark.parametrize("campo", ["host", "user", "port"])
def test_remoto_exige_host_user(campo):
    dev = dict(REMOTE)
    if campo != "port":
        del dev[campo]
        _, errs = validate_config({"devices": {"x": dev}})
        assert errs == {f"devices.x.{campo}": {"code": "err.config.required", "params": {}}}


@pytest.mark.parametrize("campo,valor", [("host", "192.0.2.5"), ("user", "usuario"), ("port", 22)])
def test_local_rechaza_host_user_port(campo, valor):
    _, errs = validate_config(cfg_dict(**{campo: valor}))
    assert errs == {f"devices.pc-aaaa1111.{campo}": {"code": "err.config.local_no_remote", "params": {}}}


def test_local_acepta_host_vacio_o_null():
    c, errs = validate_config(cfg_dict(host="", user=None))
    assert not errs and c.devices["pc-aaaa1111"].host is None


def test_local_no_bool_es_error():
    for v in ("yes", 1, "true"):
        _, errs = validate_config(cfg_dict(local=v))
        assert errs, v


def test_maximo_un_local():
    d = cfg_dict()
    d["devices"]["laptop-bbbb2222"] = {"name": "Otro", "local": True, "os": "linux"}
    _, errs = validate_config(d)
    assert errs == {"devices.laptop-bbbb2222.local": {"code": "err.config.local_one", "params": {}}}


def test_local_en_docker_es_error_claro(monkeypatch):
    monkeypatch.setenv("CHECKPOINT_RUNTIME", "docker")
    _, errs = validate_config(cfg_dict())
    assert errs == {"devices.pc-aaaa1111.local": {"code": "err.config.local_docker", "params": {}}}
    with pytest.raises(ValueError, match="local_docker"):
        parse_config(cfg_dict())


def test_docker_sin_local_sigue_funcionando(monkeypatch):
    monkeypatch.setenv("CHECKPOINT_RUNTIME", "docker")
    d = cfg_dict()
    d["devices"]["pc-aaaa1111"] = {"name": "PC", "host": "192.0.2.4", "user": "usuario", "os": "windows"}
    d["games"]["g-cccc3333"]["paths"]["pc-aaaa1111"] = "C:/Users/usuario/saves"
    c, errs = validate_config(d)
    assert not errs and c


def test_ruta_del_local_se_normaliza_segun_su_os():
    d = cfg_dict(os="windows")
    d["games"]["g-cccc3333"]["paths"]["pc-aaaa1111"] = "C:\\Users\\usuario\\saves"
    c = parse_config(d)
    assert c.games["g-cccc3333"].paths["pc-aaaa1111"] == "C:/Users/usuario/saves"
    d["games"]["g-cccc3333"]["paths"]["pc-aaaa1111"] = "relativa/saves"
    _, errs = validate_config(d)
    assert "games.g-cccc3333.paths.pc-aaaa1111" in errs
    d["games"]["g-cccc3333"]["paths"]["pc-aaaa1111"] = "/home/usuario/../etc"
    _, errs = validate_config(cfg_dict() | {"games": d["games"]})
    assert "games.g-cccc3333.paths.pc-aaaa1111" in errs


def test_round_trip_yaml(tmp_path):
    c = parse_config(cfg_dict())
    p = tmp_path / "config.yaml"
    save_config(p, c)
    txt = p.read_text()
    assert "local: true" in txt and "host" not in txt.split("laptop-bbbb2222")[0]
    c2, err = parse_text(txt)
    assert err is None and c2 == c
    out = render_yaml(txt, c2)
    assert parse_text(out)[0] == c and render_yaml(out, c2) == out  # idempotente, sin cambios fantasma


def test_render_yaml_conserva_comentarios_con_local():
    txt = (
        "devices:\n  pc-aaaa1111:\n    name: PC\n    local: true  # este equipo\n    os: linux\n"
        "games: {}\nmax_versions: 20\n"
    )
    c, err = parse_text(txt)
    assert err is None
    assert render_yaml(txt, c) == txt


def test_ids_estables_al_renombrar_local():
    d = cfg_dict()
    c1 = parse_config(d)
    d["devices"]["pc-aaaa1111"]["name"] = "Sobremesa"
    c2 = parse_config(d)
    assert list(c1.devices) == list(c2.devices)
    assert c2.games["g-cccc3333"].devices == c1.games["g-cccc3333"].devices
    assert c2.games["g-cccc3333"].paths == c1.games["g-cccc3333"].paths


def test_diff_marcar_y_desmarcar_local():
    remoto = parse_config(
        {"devices": {"pc-aaaa1111": {"name": "PC", "host": "192.0.2.4", "user": "usuario", "os": "linux"}}}
    )
    local = parse_config({"devices": {"pc-aaaa1111": {"name": "PC", "local": True, "os": "linux"}}})
    d = diff_configs(remoto.model_dump(exclude_none=True), local.model_dump(exclude_none=True))
    ch = d["devices"]["changed"]["pc-aaaa1111"]
    assert ch["local"] == {"old": None, "new": True}
    assert ch["host"] == {"old": "192.0.2.4", "new": None} and ch["port"] == {"old": 22, "new": None}
    assert not d["empty"]
    d2 = diff_configs(local.model_dump(exclude_none=True), local.model_dump(exclude_none=True))
    assert d2["empty"]


def test_yaml_con_local_y_clave_repetida_sigue_detectando():
    with pytest.raises(yaml.YAMLError):
        load_yaml("devices:\n  a: {local: true}\n  a: {local: true}\n")


def test_sin_local_los_dispositivos_son_remotos():
    d = {
        "devices": {
            "pc": {"name": "A", "host": "h1", "user": "u", "os": "windows"},
            "laptop": {"name": "B", "host": "h2", "user": "d", "os": "linux", "port": 2200},
        },
        "games": {"g": {"name": "G", "devices": ["pc", "laptop"], "paths": {"pc": "C:/S/g", "laptop": "/h/g"}}},
    }
    c = parse_config(d)
    assert all(not dv.local for dv in c.devices.values())
    assert c.devices["laptop"].port == 2200 and c.devices["pc"].port == 22
