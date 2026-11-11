"""Juegos con un solo dispositivo («solo checkpoint»): el hub guarda versiones, no hay copia entre equipos."""

import os

import pytest

from app.config.models import parse_config
from app.sync.engine import decide, fingerprint, list_versions, load_baseline, restore_version, run_sync, save_baseline
from fakes import LocalTransport

CFG = parse_config(
    {
        "devices": {"pc": {"name": "pc", "host": "h1", "user": "u", "os": "windows"}},
        "games": {"g": {"name": "g", "devices": ["pc"], "paths": {"pc": "C:/Saves/g"}, "process": "g.exe"}},
    }
)


class Env:
    def __init__(self, tmp):
        self.data = tmp / "data"
        self.root = tmp / "pc"
        self.pc_dir = self.root / "C:/Saves/g"
        self.hub = self.data / "hub" / "g"
        self.logs = []

    def write(self, d, name, content, mtime):
        f = d / name
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(content)
        os.utime(f, (mtime, mtime))

    def sync(self, dry=False, opts=None, **kw):
        return run_sync(
            CFG, "g", dry, self.data, self.logs.append, {"pc": LocalTransport(self.root, **kw)}, **(opts or {})
        )

    def seed(self, content="base"):
        for d in (self.pc_dir, self.hub):
            self.write(d, "s.sav", content, 500)
        h = fingerprint(self.pc_dir).hash
        save_baseline(self.data, "g", {"pc": h, "hub": h})


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


def read(d, name):
    return (d / name).read_text()


def test_primera_vez_copia_al_hub_sin_version(env):
    env.write(env.pc_dir, "s.sav", "x", 1000)
    st = env.sync()
    assert st["result"] == "ok" and st["winner"] == "pc"
    assert read(env.hub, "s.sav") == "x" and list_versions(env.data, "g") == []
    assert any("en pc (checkpoint)" in line and "entre" not in line for line in env.logs)


def test_cambio_guarda_hub_antiguo_como_version(env):
    env.seed("old")
    env.write(env.pc_dir, "s.sav", "new", 2000)
    st = env.sync()
    assert st["result"] == "ok" and st["winner"] == "pc"
    assert read(env.hub, "s.sav") == "new"
    v = list_versions(env.data, "g")
    assert len(v) == 1 and {x["source"] for x in v[0]["sources"]} == {"hub"}
    assert read(env.data / "versions/g" / v[0]["version"] / "hub", "s.sav") == "old"


def test_sin_cambios_ya_sincronizado(env):
    env.seed("x")
    assert env.sync()["code"] == "err.sync.already_synced"
    assert list_versions(env.data, "g") == []


def test_restaurar_version_y_sincronizar(env):
    env.seed("old")
    env.write(env.pc_dir, "s.sav", "new", 2000)
    env.sync()
    ver = list_versions(env.data, "g")[0]["version"]
    assert restore_version(CFG, "g", ver, "hub", env.data)["code"] == "err.sync.restored"
    assert read(env.hub, "s.sav") == "old"
    st = env.sync()
    assert st["result"] == "ok" and st["winner"] == "hub"
    assert read(env.pc_dir, "s.sav") == "old"


def test_carpeta_vacia_no_gana_al_hub(env):
    env.seed("x")
    for f in env.pc_dir.iterdir():
        f.unlink()
    st = env.sync()
    assert st["result"] == "ok" and st["winner"] == "hub"
    assert read(env.pc_dir, "s.sav") == "x"


def test_sin_baseline_contenidos_distintos_es_conflicto(env):
    env.write(env.pc_dir, "s.sav", "a", 1000)
    env.write(env.hub, "s.sav", "b", 1000)
    st = env.sync()
    assert st["result"] == "conflict"
    assert read(env.pc_dir, "s.sav") == "a" and read(env.hub, "s.sav") == "b"


def test_dispositivo_offline_aborta_sin_tocar(env):
    env.seed("x")
    st = env.sync(down=True)
    assert st["result"] == "aborted" and "pc" in st["message"]
    assert read(env.hub, "s.sav") == "x"


def test_dry_run_no_toca_nada(env):
    env.seed("old")
    env.write(env.pc_dir, "s.sav", "new", 2000)
    before = load_baseline(env.data, "g")
    assert env.sync(dry=True)["result"] == "dry-run"
    assert read(env.hub, "s.sav") == "old" and load_baseline(env.data, "g") == before
    assert not (env.data / "versions").exists()


def test_decide_un_dispositivo():
    from app.sync.engine import Fingerprint

    a, b, vacio = Fingerprint("A", 1, 1), Fingerprint("B", 1, 1), Fingerprint(None, 0, 0)
    assert decide({"pc": a, "hub": a}, {})["kind"] == "same"
    assert decide({"pc": a, "hub": vacio}, {})["winner"] == "pc"  # primera vez
    assert decide({"pc": a, "hub": b}, {"pc": "B", "hub": "B"})["winner"] == "pc"  # cambió el dispositivo
    assert decide({"pc": a, "hub": b}, {"pc": "A", "hub": "A"})["winner"] == "hub"  # hub restaurado
    assert decide({"pc": a, "hub": b}, {})["reason"] == "no-baseline"
    assert decide({"pc": vacio, "hub": b}, {"pc": "B", "hub": "B"})["winner"] == "hub"  # carpeta vacía


# ---------- protección: partida local ausente (ruta inexistente) con hub con datos ----------
import shutil

from app.sync.engine import run_sync as _rs


def _auto(env, **kw):
    return _rs(
        CFG,
        "g",
        kw.pop("dry", False),
        env.data,
        env.logs.append,
        {"pc": LocalTransport(env.root)},
        conflict_policy="skip",
        automatic=True,
    )


def _borrar_local(env):
    shutil.rmtree(env.pc_dir)
    assert not env.pc_dir.exists()


def test_automatico_omite_si_la_ruta_local_no_existe(env):
    env.seed("x")
    _borrar_local(env)
    before = load_baseline(env.data, "g")
    st = _auto(env)
    assert st["result"] == "skipped" and st["code"] == "err.sync.local_missing_manual_required"
    assert not env.pc_dir.exists()  # no recrea la carpeta
    assert read(env.hub, "s.sav") == "x" and load_baseline(env.data, "g") == before
    assert list_versions(env.data, "g") == []


def test_manual_restaura_desde_el_hub(env):
    env.seed("x")
    _borrar_local(env)
    st = env.sync()
    assert st["result"] == "ok" and st["winner"] == "hub"
    assert read(env.pc_dir, "s.sav") == "x"


def test_automatico_con_carpeta_existente_pero_vacia_se_trata_como_antes(env):
    env.seed("x")
    for f in env.pc_dir.iterdir():
        f.unlink()
    assert env.pc_dir.is_dir()
    st = _auto(env)
    assert st["result"] == "ok" and st["winner"] == "hub" and read(env.pc_dir, "s.sav") == "x"


def test_automatico_primera_vez_con_hub_vacio_no_se_omite(env):
    st = _auto(env)  # ruta inexistente pero el hub tampoco tiene datos: nada que proteger
    assert st["code"] == "err.sync.nothing_to_sync"


def test_automatico_dry_run_no_crea_nada(env):
    env.seed("x")
    _borrar_local(env)
    st = _auto(env, dry=True)
    assert st["result"] == "skipped" and not env.pc_dir.exists()


def test_dos_dispositivos_sin_cambios_automatico_repone_la_ruta_ausente(tmp_path):
    import test_sync as ts

    e = ts.Env(tmp_path)
    e.seed("x")
    shutil.rmtree(e.pc_dir)
    st = run_sync(ts.CFG, "g", False, e.data, e.logs.append, e.tr(), conflict_policy="skip", automatic=True)
    assert st["result"] == "ok" and (e.pc_dir / "s.sav").read_text() == "x"


def test_scheduler_ciclo_omite_y_queda_en_el_resumen(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from app.core import settings
    from app.sync.scheduler import Scheduler

    monkeypatch.setattr(settings, "DATA_DIR", tmp_path / "data")
    e = Env(tmp_path)
    e.seed("x")
    _borrar_local(e)
    s = Scheduler(
        lambda: CFG,
        lambda g: False,
        runner=lambda c, g, dry, log, **kw: _rs(c, g, dry, e.data, log, {"pc": LocalTransport(e.root)}, **kw),
    )
    res, m, c, st = s.run_game(CFG, "g")
    assert res == "skipped" and c["code"] == "err.sync.local_missing_manual_required"
    item, det = s.game_detail("g", res, m, c)
    assert det == {"result": "skipped", "name": "g", "code": "err.sync.local_missing_manual_required", "params": {}}
    assert not e.pc_dir.exists()


def test_juego_desactivado_aborta_incluso_en_dry_run(env):
    from app.sync.engine import SyncAbort

    cfg = parse_config(
        {
            "devices": {"pc": {"name": "pc", "host": "h1", "user": "u", "os": "windows"}},
            "games": {"g": {"name": "g", "devices": ["pc"], "paths": {"pc": "C:/Saves/g"}, "enabled": False}},
        }
    )
    env.write(env.pc_dir, "s.sav", "x", 1000)
    for dry in (False, True):
        with pytest.raises(SyncAbort) as e:
            run_sync(cfg, "g", dry, env.data, env.logs.append, {"pc": LocalTransport(env.root)})
        assert e.value.code == "err.sync.game_disabled"  # y no el de partida local ausente
    assert not env.hub.exists()
