"""Dispositivo `http: true` (transporte sin SSH): modelo, serialización y exclusión del motor clásico."""

import pytest

from app.config.models import classic_devices, parse_config, validate_config
from app.config.store import parse_text, render_yaml
from app.sync import engine as sync
from app.sync.engine import fingerprint, run_sync
from app.sync.transport import TransportError, get_transport
from fakes import LocalTransport, save_config

HTTP = {"name": "Deck", "http": True, "os": "linux"}
REMOTE = {"name": "Laptop", "host": "192.0.2.10", "user": "usuario", "os": "linux", "port": 2222}


def cfg_dict(**extra_dev):
    d = {
        "devices": {"deck-aaaa1111": dict(HTTP), "laptop-bbbb2222": dict(REMOTE)},
        "games": {
            "g-cccc3333": {
                "name": "Juego",
                "devices": ["deck-aaaa1111", "laptop-bbbb2222"],
                "paths": {"deck-aaaa1111": "/home/deck/saves", "laptop-bbbb2222": "/home/usuario/g"},
            }
        },
    }
    d["devices"]["deck-aaaa1111"].update(extra_dev)
    return d


def test_http_valido():
    dev = parse_config(cfg_dict()).devices["deck-aaaa1111"]
    assert dev.http and not dev.local and dev.host is None and dev.user is None and dev.port is None


def test_http_dump_sin_host_user_port_ni_local():
    c = parse_config(cfg_dict())
    assert c.devices["deck-aaaa1111"].model_dump(exclude_none=True) == {"name": "Deck", "http": True, "os": "linux"}


def test_remoto_y_local_no_escriben_http():
    c = parse_config(cfg_dict())
    assert list(c.devices["laptop-bbbb2222"].model_dump()) == ["name", "host", "user", "os", "port"]
    c2 = parse_config({"devices": {"p": {"name": "PC", "local": True, "os": "linux"}}})
    assert c2.devices["p"].model_dump(exclude_none=True) == {"name": "PC", "local": True, "os": "linux"}


@pytest.mark.parametrize("campo,valor", [("host", "192.0.2.5"), ("user", "usuario"), ("port", 22)])
def test_http_rechaza_host_user_port(campo, valor):
    _, errs = validate_config(cfg_dict(**{campo: valor}))
    assert errs == {f"devices.deck-aaaa1111.{campo}": {"code": "err.config.http_no_remote", "params": {}}}


def test_http_y_local_son_excluyentes():
    _, errs = validate_config(cfg_dict(local=True))
    assert errs == {"devices.deck-aaaa1111": {"code": "err.config.http_local_exclusive", "params": {}}}


def test_http_no_bool_es_error():
    for v in ("yes", 1, "true"):
        _, errs = validate_config(cfg_dict(http=v))
        assert errs, v


def test_http_exige_os():
    d = cfg_dict()
    del d["devices"]["deck-aaaa1111"]["os"]
    _, errs = validate_config(d)
    assert errs == {"devices.deck-aaaa1111.os": {"code": "err.config.required", "params": {}}}


def test_http_funciona_en_docker(monkeypatch):
    monkeypatch.setenv("CHECKPOINT_RUNTIME", "docker")
    c, errs = validate_config(cfg_dict())
    assert not errs and c


def test_http_extra_forbid():
    _, errs = validate_config(cfg_dict(foo=1))
    assert errs


def test_round_trip_yaml(tmp_path):
    c = parse_config(cfg_dict())
    p = tmp_path / "config.yaml"
    save_config(p, c)
    txt = p.read_text()
    assert "http: true" in txt and "local" not in txt
    c2, err = parse_text(txt)
    assert err is None and c2 == c
    assert render_yaml(txt, c2)


def test_classic_devices_excluye_http():
    c = parse_config(cfg_dict())
    assert classic_devices(c, "g-cccc3333") == ["laptop-bbbb2222"]


# ---- motor: nunca se intenta SSH al dispositivo http ----
def test_get_transport_rechaza_http():
    dev = parse_config(cfg_dict()).devices["deck-aaaa1111"]
    with pytest.raises(TransportError) as e:
        get_transport(dev)
    assert e.value.code == "err.transport.push_only"


def _mixed(tmp_path, monkeypatch, both_http=False):
    c = parse_config(cfg_dict())
    if both_http:
        d = cfg_dict()
        d["devices"]["laptop-bbbb2222"] = {"name": "Otro", "http": True, "os": "linux"}
        c = parse_config(d)
    laptop = tmp_path / "laptop"
    (laptop / "home/usuario/g").mkdir(parents=True)
    (laptop / "home/usuario/g/s.sav").write_text("laptop")
    asked = []

    def fake(dev):
        asked.append(dev.name)
        if dev.http:
            raise AssertionError("se pidió un transporte para un dispositivo http")
        return LocalTransport(laptop)

    monkeypatch.setattr(sync, "get_transport", fake)
    return c, asked


def test_sync_mixto_ignora_el_http(tmp_path, monkeypatch):
    c, asked = _mixed(tmp_path, monkeypatch)
    st = run_sync(c, "g-cccc3333", data_dir=tmp_path / "data", log=lambda m: None)
    assert st["result"] == "ok", st
    assert asked == ["Laptop"]
    assert (tmp_path / "data/hub/g-cccc3333/s.sav").read_text() == "laptop"


def test_sync_solo_http_aborta_con_codigo(tmp_path, monkeypatch):
    c, asked = _mixed(tmp_path, monkeypatch, both_http=True)
    st = run_sync(c, "g-cccc3333", data_dir=tmp_path / "data", log=lambda m: None)
    assert st["result"] == "aborted" and st["code"] == "err.sync.push_only"
    assert asked == []
    assert not (tmp_path / "data/hub/g-cccc3333").exists()


def test_sync_ssh_sigue_igual_sin_http(tmp_path, monkeypatch):
    d = cfg_dict()
    d["devices"]["deck-aaaa1111"] = {"name": "Deck", "host": "192.0.2.4", "user": "u", "os": "linux"}
    c = parse_config(d)
    root = tmp_path / "r"
    for p in ("home/deck/saves", "home/usuario/g"):
        (root / p).mkdir(parents=True)
        (root / p / "s.sav").write_text("x")
    monkeypatch.setattr(sync, "get_transport", lambda dev: LocalTransport(root))
    st = run_sync(c, "g-cccc3333", data_dir=tmp_path / "data", log=lambda m: None)
    assert st["result"] == "ok"
    assert fingerprint(tmp_path / "data/hub/g-cccc3333").files == 1


def test_devices_test_http_no_intenta_ssh(monkeypatch):
    """`/api/devices/test` con un dispositivo http: respuesta controlada, sin SSH ni host key."""
    import asyncio

    from app.core import bootstrap
    from app.services.devices import check_device

    def boom(*a, **k):
        raise AssertionError("no debe intentar SSH")

    monkeypatch.setattr(bootstrap, "ensure_host_key", boom)
    r = asyncio.run(check_device({"device": {"http": True, "os": "linux"}}))
    assert r["ok"] is False and r["code"] == "err.transport.push_only" and r["params"] == {}
