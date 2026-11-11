"""Motor real de sync con «Este equipo» (LocalDeviceTransport REAL sobre un tmpdir) + un remoto simulado
(LocalTransport de tests, que sustituye a SSH) y el hub. Cubre la tabla de casos de conflictos."""

import json
import os
import subprocess
import threading

import pytest

from app.config.models import parse_config
from app.sync.engine import (
    SyncAbort,
    count_versions,
    fingerprint,
    list_versions,
    load_baseline,
    relfiles,
    restore_version,
    run_sync,
    save_baseline,
)
from app.sync.transport import LocalDeviceTransport, TransportError
from fakes import LocalTransport


class LEnv:
    def __init__(self, tmp, keep=None, process="juego.bin"):
        self.tmp = tmp
        self.data = tmp / "data"
        self.pc_dir = tmp / "mi equipo" / "saves ñ"  # el equipo local: ruta real, con espacios/unicode
        self.laptop_root = tmp / "laptop"
        self.laptop_dir = self.laptop_root / "home/usuario/g"
        self.hub = self.data / "hub" / "g"
        self.logs = []
        game = {
            "name": "Juego",
            "devices": ["pc-1a2b3c4d", "laptop-5e6f7a8b"],
            "paths": {"pc-1a2b3c4d": str(self.pc_dir), "laptop-5e6f7a8b": "/home/usuario/g"},
        }
        if process:
            game["process"] = process
        if keep is not None:
            game["keep_versions"] = keep
        self.cfg = parse_config(
            {
                "devices": {
                    "pc-1a2b3c4d": {"name": "PC", "local": True, "os": "linux"},
                    "laptop-5e6f7a8b": {"name": "Laptop", "host": "192.0.2.10", "user": "usuario", "os": "linux"},
                },
                "games": {"g": game},
            }
        )
        self.pc, self.lap = "pc-1a2b3c4d", "laptop-5e6f7a8b"

    def tr(self, laptop=None, pc=None):
        t = {self.lap: laptop or LocalTransport(self.laptop_root)}
        if pc is not None:
            t[self.pc] = pc  # si no se da, el motor usa get_transport -> LocalDeviceTransport real
        return t

    def write(self, d, name, content, mtime):
        f = d / name
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(content)
        os.utime(f, (mtime, mtime))

    def sync(self, dry=False, laptop=None, pc=None, **kw):
        return run_sync(self.cfg, "g", dry, self.data, self.logs.append, self.tr(laptop, pc), **kw)

    def seed(self, content="base"):
        for d in (self.pc_dir, self.laptop_dir, self.hub):
            self.write(d, "s.sav", content, 500)
        h = fingerprint(self.pc_dir).hash
        save_baseline(self.data, "g", {self.pc: h, self.lap: h, "hub": h})

    def conflict(self):
        self.seed("base")
        self.write(self.pc_dir, "s.sav", "pc-change", 1000)
        self.write(self.laptop_dir, "s.sav", "laptop-change", 2000)


@pytest.fixture
def env(tmp_path):
    return LEnv(tmp_path)


def read(d, n="s.sav"):
    return (d / n).read_text()


def fake_run(running):
    def run(args, **kw):
        r = running()
        return subprocess.CompletedProcess(args, 0 if r else 1, b"4242\n" if r else b"", b"")

    return run


# ---- uno cambió ----
def test_local_cambio_gana_y_propaga_al_remoto_y_hub(env):
    env.seed()
    env.write(env.pc_dir, "s.sav", "pc-new", 3000)
    st = env.sync()
    assert st["result"] == "ok" and st["winner"] == env.pc and set(st["targets"]) == {env.lap, "hub"}
    assert read(env.laptop_dir) == read(env.hub) == "pc-new"
    assert {s["source"] for s in list_versions(env.data, "g")[0]["sources"]} == {
        env.lap,
        "hub",
    }  # perdedores versionados
    h = fingerprint(env.pc_dir).hash
    assert load_baseline(env.data, "g") == {env.pc: h, env.lap: h, "hub": h}


def test_remoto_cambio_gana_y_actualiza_el_local(env):
    env.seed()
    env.write(env.laptop_dir, "s.sav", "lap-new", 3000)
    st = env.sync()
    assert st["result"] == "ok" and st["winner"] == env.lap
    assert read(env.pc_dir) == "lap-new" == read(env.hub)
    v = list_versions(env.data, "g")
    assert {s["source"] for s in v[0]["sources"]} == {env.pc, "hub"}
    assert read(env.data / "versions" / "g" / v[0]["version"] / env.pc) == "base"


def test_el_local_conserva_mtime_de_origen(env):
    env.seed()
    env.write(env.laptop_dir, "s.sav", "lap-new", 7777)
    env.sync()
    assert int((env.pc_dir / "s.sav").stat().st_mtime) == 7777


def test_ya_sincronizado_no_hace_nada(env):
    env.seed()
    before = (env.pc_dir / "s.sav").stat().st_mtime_ns
    st = env.sync()
    assert st["result"] == "ok" and st["code"] in ("err.sync.done", "err.sync.already_synced")
    assert (env.pc_dir / "s.sav").stat().st_mtime_ns == before and count_versions(env.data, "g") == 0


# ---- ambos cambiaron ----
def test_ambos_cambiaron_conflicto_no_toca_nada(env):
    env.conflict()
    st = env.sync()
    assert st["result"] == "conflict" and st["conflict"]["reason"] == "both-changed"
    assert {s["id"] for s in st["conflict"]["sides"]} == {env.pc, env.lap}
    assert {s["name"] for s in st["conflict"]["sides"]} == {"PC", "Laptop"}
    assert read(env.pc_dir) == "pc-change" and read(env.laptop_dir) == "laptop-change" and read(env.hub) == "base"
    assert count_versions(env.data, "g") == 0


def test_conflicto_politica_skip(env):
    env.conflict()
    st = env.sync(conflict_policy="skip")
    assert st["result"] == "conflict" and read(env.pc_dir) == "pc-change"


def test_conflicto_politica_newest(env):
    env.conflict()
    st = env.sync(conflict_policy="newest")
    assert st["result"] == "ok" and st["winner"] == env.lap
    assert read(env.pc_dir) == "laptop-change"
    v = list_versions(env.data, "g")
    assert read(env.data / "versions" / "g" / v[0]["version"] / env.pc) == "pc-change"


def test_conflicto_newest_con_relojes_juntos_es_indeterminado(env):
    env.seed()
    env.write(env.pc_dir, "s.sav", "a", 1000)
    env.write(env.laptop_dir, "s.sav", "b", 1001)
    st = env.sync(resolution="newest")
    assert st["result"] == "conflict" and st["conflict"]["reason"] == "indeterminate"


def test_resolucion_manual_por_id_nombre_hub_y_newest(env):
    env.conflict()
    st = env.sync(resolution=f"device:{env.pc}")
    assert st["result"] == "ok" and st["winner"] == env.pc and read(env.laptop_dir) == "pc-change"
    env.conflict()
    st = env.sync(resolution="device:PC")  # por nombre
    assert st["winner"] == env.pc
    env.conflict()
    assert env.sync(resolution="newest")["winner"] == env.lap
    env.conflict()
    st = env.sync(resolution="hub")
    assert st["winner"] == "hub" and read(env.pc_dir) == read(env.laptop_dir) == "base"


def test_resolucion_con_expect_obsoleto_devuelve_conflicto_nuevo(env):
    env.conflict()
    h = fingerprint(env.pc_dir).hash
    env.write(env.pc_dir, "s.sav", "otra-vez", 1500)
    st = env.sync(resolution=f"device:{env.pc}", expect={env.pc: h})
    assert st["result"] == "conflict" and st["conflict"]["reason"] == "stale"
    assert read(env.pc_dir) == "otra-vez"


def test_ambos_cambiaron_a_lo_mismo_no_es_conflicto(env):
    env.seed()
    env.write(env.pc_dir, "s.sav", "igual", 1000)
    env.write(env.laptop_dir, "s.sav", "igual", 2000)
    st = env.sync()
    assert st["result"] == "ok" and read(env.hub) == "igual"


# ---- primera sync / lados vacíos ----
def test_primera_sync_sin_baseline_contenidos_distintos_conflicto(env):
    env.write(env.pc_dir, "s.sav", "a", 1000)
    env.write(env.laptop_dir, "s.sav", "b", 9000)
    st = env.sync()
    assert st["result"] == "conflict" and st["conflict"]["reason"] == "no-baseline"


def test_primera_sync_local_inexistente_se_trata_como_vacia_y_se_rellena(env):
    env.write(env.laptop_dir, "s.sav", "lap", 1000)
    assert not env.pc_dir.exists()
    st = env.sync()
    assert st["result"] == "ok" and read(env.pc_dir) == "lap"
    assert count_versions(env.data, "g") == 0  # nada que versionar: estaba vacío
    assert any("no existe todavía" in l for l in env.logs)


def test_primera_sync_local_con_datos_remoto_vacio(env):
    env.write(env.pc_dir, "s.sav", "pc", 1000)
    st = env.sync()
    assert st["result"] == "ok" and read(env.laptop_dir) == read(env.hub) == "pc"


def test_local_vaciado_nunca_gana(env):
    env.seed()
    (env.pc_dir / "s.sav").unlink()
    st = env.sync()
    assert st["result"] == "ok" and st["winner"] != env.pc
    assert read(env.pc_dir) == "base"


def test_todo_vacio(env):
    st = env.sync()
    assert st["result"] == "ok" and st["code"] == "err.sync.nothing_to_sync"


# ---- ficheros, subcarpetas, borrados ----
def test_subcarpetas_nombres_raros_y_ficheros_vacios(env):
    nombres = ["a b/c d/e.sav", "ñ/日本.dat", "vacío.bin", "x(1)[2]+3.sav"]
    for i, n in enumerate(nombres):
        env.write(env.pc_dir, n, "" if n == "vacío.bin" else n, 1000 + i)
    st = env.sync()
    assert st["result"] == "ok"
    assert relfiles(env.laptop_dir) == relfiles(env.hub) == set(nombres)
    assert fingerprint(env.pc_dir).hash == fingerprint(env.laptop_dir).hash == fingerprint(env.hub).hash
    assert int((env.laptop_dir / "ñ/日本.dat").stat().st_mtime) == 1001


def test_borrado_de_fichero_en_local_se_propaga_sin_resucitar(env):
    env.seed()
    env.write(env.pc_dir, "extra.sav", "e", 600)
    env.write(env.laptop_dir, "extra.sav", "e", 600)
    env.write(env.hub, "extra.sav", "e", 600)
    h = fingerprint(env.pc_dir).hash
    save_baseline(env.data, "g", {env.pc: h, env.lap: h, "hub": h})
    (env.pc_dir / "extra.sav").unlink()
    st = env.sync()
    assert st["result"] == "ok" and st["winner"] == env.pc
    assert relfiles(env.laptop_dir) == relfiles(env.hub) == {"s.sav"}
    assert env.sync()["code"] == "err.sync.already_synced"


def test_borrado_en_remoto_se_propaga_al_local(env):
    env.seed()
    env.write(env.pc_dir, "extra.sav", "e", 600)
    env.write(env.laptop_dir, "extra.sav", "e", 600)
    env.write(env.hub, "extra.sav", "e", 600)
    h = fingerprint(env.pc_dir).hash
    save_baseline(env.data, "g", {env.pc: h, env.lap: h, "hub": h})
    (env.laptop_dir / "extra.sav").unlink()
    st = env.sync()
    assert st["winner"] == env.lap and relfiles(env.pc_dir) == {"s.sav"}


def test_ficheros_extra_del_perdedor_se_eliminan_y_quedan_versionados(env):
    env.seed()
    for d in (env.pc_dir, env.laptop_dir, env.hub):
        env.write(d, "solo-local.sav", "L", 600)
    h = fingerprint(env.pc_dir).hash
    save_baseline(env.data, "g", {env.pc: h, env.lap: h, "hub": h})
    (env.laptop_dir / "solo-local.sav").unlink()
    env.write(env.laptop_dir, "s.sav", "lap-new", 3000)
    st = env.sync()
    assert st["result"] == "ok" and st["winner"] == env.lap
    assert relfiles(env.pc_dir) == {"s.sav"}
    v = list_versions(env.data, "g")[0]
    assert relfiles(env.data / "versions" / "g" / v["version"] / env.pc) == {"s.sav", "solo-local.sav"}


def test_fichero_grande(env):
    big = os.urandom(1 << 20) * 5
    (env.pc_dir).mkdir(parents=True)
    (env.pc_dir / "big.bin").write_bytes(big)
    st = env.sync()
    assert st["result"] == "ok" and (env.laptop_dir / "big.bin").read_bytes() == big


# ---- dry-run ----
def test_dry_run_no_cambia_nada(env):
    env.seed()
    env.write(env.pc_dir, "s.sav", "pc-new", 3000)
    snap = (
        fingerprint(env.pc_dir).hash,
        fingerprint(env.laptop_dir).hash,
        fingerprint(env.hub).hash,
        load_baseline(env.data, "g"),
    )
    st = env.sync(dry=True)
    assert st["result"] == "dry-run" and st["winner"] == env.pc
    assert (
        fingerprint(env.pc_dir).hash,
        fingerprint(env.laptop_dir).hash,
        fingerprint(env.hub).hash,
        load_baseline(env.data, "g"),
    ) == snap
    assert count_versions(env.data, "g") == 0
    assert sorted(p.name for p in env.pc_dir.parent.iterdir()) == ["saves ñ"]


def test_dry_run_conflicto_conserva_marca_pendiente(env):
    env.conflict()
    assert env.sync()["result"] == "conflict"
    env.sync(dry=True)
    assert json.loads((env.data / "status" / "g.json").read_text())["result"] == "conflict"


# ---- proceso abierto (detección local con subprocess simulado) ----
def test_proceso_abierto_en_local_aborta_antes_de_tocar(env):
    env.seed()
    env.write(env.laptop_dir, "s.sav", "lap-new", 3000)
    st = env.sync(pc=LocalDeviceTransport(run=fake_run(lambda: True)))
    assert (
        st["result"] == "aborted"
        and st["code"] == "err.sync.process_open"
        and st["params"] == {"process": "juego.bin", "device": "PC"}
    )
    assert read(env.pc_dir) == "base" and read(env.hub) == "base" and count_versions(env.data, "g") == 0


def test_proceso_abierto_en_remoto_con_local_cerrado(env):
    env.seed()
    env.write(env.pc_dir, "s.sav", "pc-new", 3000)

    class Open(LocalTransport):
        def process_running(self, name):
            return True

    st = env.sync(laptop=Open(env.laptop_root), pc=LocalDeviceTransport(run=fake_run(lambda: False)))
    assert st["result"] == "aborted" and "Laptop" in st["message"] and read(env.laptop_dir) == "base"


def test_recheck_del_proceso_justo_antes_de_escribir_en_local(env):
    env.seed()
    env.write(env.laptop_dir, "s.sav", "lap-new", 3000)
    calls = {"n": 0}

    def running():
        calls["n"] += 1
        return calls["n"] >= 2  # cerrado en la 1ª comprobación, abierto en el re-chequeo

    st = env.sync(pc=LocalDeviceTransport(run=fake_run(running)))
    assert calls["n"] == 2
    assert st["result"] == "aborted"
    assert read(env.pc_dir) == "base" and read(env.hub) == "base" and count_versions(env.data, "g") == 0
    assert not any(p.name.startswith(".") for p in env.pc_dir.parent.iterdir())


def test_error_al_comprobar_proceso_aborta(env):
    env.seed()

    def run(args, **kw):
        return subprocess.CompletedProcess(args, 2, b"", b"boom")

    st = env.sync(pc=LocalDeviceTransport(run=run))
    assert (
        st["result"] == "aborted" and st["code"] == "err.sync.process_check_failed" and st["params"]["device"] == "PC"
    )


def test_sin_proceso_configurado_no_se_comprueba(tmp_path):
    e = LEnv(tmp_path, process=None)
    e.seed()
    e.write(e.laptop_dir, "s.sav", "lap-new", 3000)

    def run(*a, **k):
        raise AssertionError("no debe llamarse")

    assert e.sync(pc=LocalDeviceTransport(run=run))["result"] == "ok"


# ---- fallo parcial / idempotencia ----
def test_fallo_parcial_en_el_remoto_no_actualiza_baseline_y_se_recupera(env):
    env.seed()
    env.write(env.pc_dir, "s.sav", "pc-new", 3000)
    old = load_baseline(env.data, "g")

    class FailPush(LocalTransport):
        def push(self, src, path, extras=()):
            raise TransportError("disco lleno")

    st = env.sync(laptop=FailPush(env.laptop_root))
    assert st["result"] == "partial" and st["failed"] == [env.lap]
    assert read(env.hub) == "pc-new" and read(env.laptop_dir) == "base"
    assert load_baseline(env.data, "g") == old
    st = env.sync()
    assert st["result"] == "ok" and read(env.laptop_dir) == "pc-new"


def test_fallo_parcial_en_el_local_se_reporta_y_se_recupera(env, monkeypatch):
    env.seed()
    env.write(env.laptop_dir, "s.sav", "lap-new", 3000)
    old = load_baseline(env.data, "g")
    orig = LocalDeviceTransport.push

    def boom(self, src, path, extras=()):
        raise TransportError("sin permiso para escribir")

    monkeypatch.setattr(LocalDeviceTransport, "push", boom)
    st = env.sync()
    assert st["result"] == "partial" and st["failed"] == [env.pc] and "sin permiso" in st["message"]
    assert read(env.pc_dir) == "base" and load_baseline(env.data, "g") == old
    monkeypatch.setattr(LocalDeviceTransport, "push", orig)
    st = env.sync()
    assert st["result"] == "ok" and read(env.pc_dir) == "lap-new"


def test_idempotente_varias_syncs(env):
    env.seed()
    env.write(env.pc_dir, "s.sav", "pc-new", 3000)
    env.sync()
    n = count_versions(env.data, "g")
    for _ in range(3):
        st = env.sync()
        assert st["result"] == "ok" and st["code"] == "err.sync.already_synced"
    assert count_versions(env.data, "g") == n


# ---- concurrencia ----
def test_lock_impide_solapamiento(env):
    env.seed()
    from app.sync.engine import _game_lock

    with _game_lock(env.data, "g"):
        with pytest.raises(SyncAbort, match="in_progress"):
            env.sync()
    assert env.sync()["result"] == "ok"


def test_dos_syncs_concurrentes_solo_una_corre(env):
    env.seed()
    env.write(env.pc_dir, "s.sav", "pc-new", 3000)
    gate, entered = threading.Event(), threading.Event()

    class Slow(LocalTransport):
        def pull(self, path, dest):
            entered.set()
            gate.wait(10)
            return super().pull(path, dest)

    res = {}

    def a():
        res["a"] = env.sync(laptop=Slow(env.laptop_root))

    t = threading.Thread(target=a)
    t.start()
    assert entered.wait(10)
    with pytest.raises(SyncAbort, match="in_progress"):
        env.sync()
    gate.set()
    t.join(20)
    assert res["a"]["result"] == "ok"


# ---- remoto offline, local online ----
def test_remoto_offline_local_online_sube_al_hub_y_versiona(env):
    env.seed()
    env.write(env.pc_dir, "s.sav", "pc-new", 3000)
    st = env.sync(laptop=LocalTransport(env.laptop_root, down=True))
    assert st["result"] == "ok" and st["offline"] == [env.lap] and st["winner"] == env.pc
    assert read(env.hub) == "pc-new" and read(env.laptop_dir) == "base"
    assert st["code"] == "err.sync.done_pending" and st["params"]["offline"]
    v = list_versions(env.data, "g")
    assert [s["source"] for s in v[0]["sources"]] == ["hub"]  # el hub anterior queda versionado


def test_remoto_offline_local_desactualizado_se_actualiza_desde_el_hub(env):
    env.seed()
    env.write(env.hub, "s.sav", "hub-new", 3000)  # p. ej. versión restaurada
    st = env.sync(laptop=LocalTransport(env.laptop_root, down=True))
    assert st["result"] == "ok" and st["winner"] == "hub" and read(env.pc_dir) == "hub-new"
    v = list_versions(env.data, "g")
    assert read(env.data / "versions" / "g" / v[0]["version"] / env.pc) == "base"


def test_remoto_offline_conflicto_contra_hub(env):
    env.seed()
    env.write(env.pc_dir, "s.sav", "pc-new", 3000)
    env.write(env.hub, "s.sav", "hub-new", 4000)
    st = env.sync(laptop=LocalTransport(env.laptop_root, down=True))
    assert st["result"] == "conflict" and {s["id"] for s in st["conflict"]["sides"]} == {env.pc, "hub"}
    assert read(env.pc_dir) == "pc-new"


def test_remoto_offline_local_sin_cambios_no_hace_nada(env):
    env.seed()
    st = env.sync(laptop=LocalTransport(env.laptop_root, down=True))
    assert st["result"] == "ok" and st["code"] == "err.sync.already_synced"


def test_local_sin_remoto_ni_hub_primer_arranque_un_solo_dispositivo(env):
    env.write(env.pc_dir, "s.sav", "pc", 1000)
    st = env.sync(laptop=LocalTransport(env.laptop_root, down=True))
    assert st["result"] == "ok" and read(env.hub) == "pc"


def test_remoto_offline_y_baseline_posterior_el_remoto_vuelve_y_recibe(env):
    env.seed()
    env.write(env.pc_dir, "s.sav", "pc-new", 3000)
    env.sync(laptop=LocalTransport(env.laptop_root, down=True))
    st = env.sync()  # vuelve el remoto
    assert st["result"] == "ok" and read(env.laptop_dir) == "pc-new"


def test_el_local_es_siempre_online(env):
    env.seed()
    st = env.sync()
    assert st["offline"] == []


# ---- ids estables ----
def test_renombrar_dispositivo_local_y_juego_no_cambia_rutas(env):
    env.seed()
    env.write(env.pc_dir, "s.sav", "pc-new", 3000)
    env.sync()
    data = env.cfg.model_dump(exclude_none=True)
    data["devices"][env.pc]["name"] = "Sobremesa"
    data["games"]["g"]["name"] = "Juego renombrado"
    cfg2 = parse_config(data)
    env.write(env.pc_dir, "s.sav", "pc-newer", 4000)
    st = run_sync(cfg2, "g", False, env.data, env.logs.append, env.tr())
    assert st["result"] == "ok" and st["winner"] == env.pc and read(env.hub) == "pc-newer"
    assert sorted(p.name for p in (env.data / "hub").iterdir()) == ["g"]
    assert sorted(p.name for p in (env.data / "versions").iterdir()) == ["g"]
    srcs = {
        x["source"]: x["name"]
        for x in list_versions(env.data, "g", {k: d.name for k, d in cfg2.devices.items()})[0]["sources"]
    }
    assert srcs[env.lap] == "Laptop"


def test_resolver_por_nombre_nuevo_tras_renombrar(env):
    env.conflict()
    data = env.cfg.model_dump(exclude_none=True)
    data["devices"][env.pc]["name"] = "Sobremesa"
    cfg2 = parse_config(data)
    st = run_sync(cfg2, "Juego", False, env.data, env.logs.append, env.tr(), resolution="device:Sobremesa")
    assert st["result"] == "ok" and st["winner"] == env.pc


# ---- versiones y poda ----
def test_limite_de_versiones_y_poda_con_local(tmp_path):
    e = LEnv(tmp_path, keep=2)
    e.seed("v0")
    for i in range(1, 6):
        side = e.pc_dir if i % 2 else e.laptop_dir
        e.write(side, "s.sav", f"v{i}", 1000 + i * 10)
        st = e.sync()
        assert st["result"] == "ok", st
    assert count_versions(e.data, "g") == 2
    names = sorted(p.name for p in (e.data / "versions" / "g").iterdir())
    assert len(names) == 2
    from app.sync.versions import _version_key

    assert list_versions(e.data, "g")[0]["version"] == max(names, key=_version_key)


def test_poda_no_se_hace_en_dry_run_ni_si_falla(tmp_path):
    e = LEnv(tmp_path, keep=1)
    e.seed("v0")
    for i in (1, 2):
        e.write(e.laptop_dir if i == 1 else e.pc_dir, "s.sav", f"n{i}", 2000 + i)
        e.sync()
    assert count_versions(e.data, "g") == 1
    e.write(e.pc_dir, "s.sav", "n3", 5000)
    e.sync(dry=True)
    assert count_versions(e.data, "g") == 1


def test_restaurar_version_y_sincronizar_propaga_al_local(env):
    env.seed()
    env.write(env.laptop_dir, "s.sav", "lap-new", 3000)
    env.sync()
    v = list_versions(env.data, "g")[0]
    msg = restore_version(env.cfg, "g", v["version"], env.pc, env.data)
    assert msg["code"] == "err.sync.restored" and read(env.hub) == "base"
    st = env.sync()
    assert st["result"] == "ok" and st["winner"] == "hub"
    assert read(env.pc_dir) == read(env.laptop_dir) == "base"


# ---- seguridad ----
def test_symlink_en_saves_locales_no_filtra_ni_se_escribe_fuera(env):
    fuera = env.tmp / "fuera"
    fuera.mkdir()
    (fuera / "secreto.txt").write_text("SECRETO")
    env.write(env.pc_dir, "s.sav", "pc", 1000)
    os.symlink(fuera, env.pc_dir / "enlace")
    st = env.sync()
    assert st["result"] == "ok"
    assert not (env.laptop_dir / "enlace").exists() and not (env.hub / "enlace").exists()
    assert sorted(p.name for p in fuera.iterdir()) == ["secreto.txt"]
    assert (env.pc_dir / "enlace").is_symlink()  # el enlace del usuario sigue ahí
    env.write(env.laptop_dir, "s.sav", "lap-new", 3000)
    assert env.sync()["result"] == "ok"
    assert (
        sorted(p.name for p in fuera.iterdir()) == ["secreto.txt"] and (fuera / "secreto.txt").read_text() == "SECRETO"
    )


def test_ruta_local_inexistente_sin_permiso_error_claro_y_nada_cambia(env):
    if os.geteuid() == 0:
        pytest.skip("root")
    env.seed()
    env.write(env.laptop_dir, "s.sav", "lap-new", 3000)
    env.pc_dir.chmod(0)
    try:
        st = env.sync()
    finally:
        env.pc_dir.chmod(0o755)
    assert st["result"] in ("error", "aborted") and st["code"] == "err.transport.no_read_permission"
    assert read(env.hub) == "base" and read(env.laptop_dir) == "lap-new"


def test_el_log_no_filtra_nada_sensible(env):
    env.seed()
    env.write(env.pc_dir, "s.sav", "pc-new", 3000)
    env.sync()
    txt = "\n".join(env.logs)
    assert "SSH" not in txt and "known_hosts" not in txt and "id_ed25519" not in txt


def test_el_motor_usa_LocalDeviceTransport_real_para_el_local(env, monkeypatch):
    usados = []
    from app.sync import engine as sync_mod

    orig = sync_mod.get_transport

    def spy(dev):
        t = orig(dev)
        usados.append((dev.name, type(t).__name__))
        return t

    monkeypatch.setattr(sync_mod, "get_transport", spy)
    env.seed()
    env.write(env.pc_dir, "s.sav", "pc-new", 3000)
    assert env.sync()["result"] == "ok"
    assert usados == [("PC", "LocalDeviceTransport")]  # el remoto se inyectó; el local NO
