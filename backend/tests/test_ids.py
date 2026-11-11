"""Ids estables: el id interno no depende del nombre; renombrar no mueve nada en disco."""
import copy
import json
import os
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
import yaml

from app import cli
from app.users import history
from app.core import settings
from app.config.models import ConfigError, load_config, parse_config, resolve_ref, validate_config
from app.config.store import diff_configs, render_yaml
from app.sync.scheduler import Scheduler
from app.sync.engine import (SyncAbort, count_versions, fingerprint, list_versions, load_baseline, resolve_game,
                      restore_version, run_sync, save_baseline)
from fakes import LocalTransport

from test_api import client, login  # noqa: F401  (fixture)

GAME = "Juego de prueba"
GID = "juego-de-prueba-28d4413f"  # id interno estable: es la carpeta de data/ del juego
PC, LAPTOP = "pc", "laptop"

BASE = {
    "devices": {PC: {"name": PC, "host": "h1", "user": "u", "os": "windows"},
                LAPTOP: {"name": LAPTOP, "host": "h2", "user": "d", "os": "linux"}},
    "games": {GID: {"name": GAME, "devices": [PC, LAPTOP], "paths": {PC: "C:/Saves/dq", LAPTOP: "/home/usuario/dq"},
                    "process": "dq.exe", "keep_versions": 3}},
}
NEW = {
    "devices": {"pc-1a2b3c4d": {"name": "Mi PC", "host": "h1", "user": "u", "os": "windows"},
                "laptop-5e6f7a8b": {"name": "Portátil", "host": "h2", "user": "d", "os": "linux"}},
    "games": {"zelda-0a1b2c3d": {"name": "Zelda", "devices": ["pc-1a2b3c4d", "laptop-5e6f7a8b"],
                                 "paths": {"pc-1a2b3c4d": "C:/Saves/z", "laptop-5e6f7a8b": "/home/usuario/z"}}},
}


def mod(base, path, value):
    d = copy.deepcopy(base)
    *ks, last = path.split("/")
    cur = d
    for k in ks:
        cur = cur[k]
    cur[last] = value
    return d


# ---------- carga ----------
def test_new_format_loads_as_is():
    c = parse_config(NEW)
    assert c.games["zelda-0a1b2c3d"].name == "Zelda" and c.devices["pc-1a2b3c4d"].name == "Mi PC"
    assert c.games["zelda-0a1b2c3d"].paths["pc-1a2b3c4d"] == "C:/Saves/z"


def test_loading_never_rewrites_file_but_saving_does(client, tmp_path):  # noqa: F811
    login(client)
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    f = tmp_path / "config" / "config.yaml"
    text = "# mi config\n" + yaml.safe_dump(BASE, allow_unicode=True)
    f.write_text(text)
    got = client.get("/api/config").json()
    assert f.read_text() == text  # leer/arrancar no toca el fichero
    assert got["config"]["games"][GID]["name"] == GAME and got["error"] is None
    same = client.put("/api/config", json={"config": got["config"], "base_version": got["version"]})
    assert same.json()["changed"] is False and f.read_text() == text  # sin cambios no se escribe nada
    cfg = copy.deepcopy(got["config"])
    cfg["devices"][PC]["name"] = "Torre"
    r = client.put("/api/config", json={"config": cfg, "base_version": got["version"]})
    assert r.status_code == 200 and r.json()["changed"] is True and r.json()["backup"]
    raw = yaml.safe_load(f.read_text())
    assert raw["devices"][PC]["name"] == "Torre" and raw["games"][GID]["devices"] == [PC, LAPTOP]
    assert raw["games"][GID]["name"] == GAME and raw["games"][GID]["paths"][PC] == "C:/Saves/dq"
    assert (tmp_path / "data" / "config-backups" / r.json()["backup"]).read_text() == text


# ---------- validación ----------
def errs(d):
    return validate_config(d)[1]


def test_duplicate_yaml_ids_are_a_clear_error(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("devices:\n  a: {name: A, host: h, user: u, os: linux}\n  a: {name: B, host: h, user: u, os: linux}\n")
    with pytest.raises(ConfigError, match="yaml_duplicate_key"):
        load_config(p)
    from app.config.store import parse_text
    cfg, err = parse_text(p.read_text())
    assert cfg is None and err["code"] == "err.config.yaml_duplicate_key"


def test_broken_references_are_errors():
    e = errs(mod(NEW, "games/zelda-0a1b2c3d/devices", ["pc-1a2b3c4d", "nope-00000000"]))
    assert e["games.zelda-0a1b2c3d.devices.1"]["code"] == "err.config.device_unknown"
    d = mod(NEW, "games/zelda-0a1b2c3d/paths", {"pc-1a2b3c4d": "C:/a", "laptop-5e6f7a8b": "/x/y", "ghost": "/z"})
    assert errs(d)["games.zelda-0a1b2c3d.paths.ghost"]["code"] == "err.config.path_device_unknown"


@pytest.mark.parametrize("bad", ["hub", "HUB", "con espacio", "a/b", "", "x" * 65, "ñ", "a.b"])
def test_bad_device_ids(bad):
    d = copy.deepcopy(NEW)
    d["devices"][bad] = d["devices"].pop("pc-1a2b3c4d")
    d["games"]["zelda-0a1b2c3d"]["devices"][0] = bad
    d["games"]["zelda-0a1b2c3d"]["paths"] = {bad: "C:/a", "laptop-5e6f7a8b": "/x/y"}
    assert errs(d)
    with pytest.raises(ValueError):
        parse_config(d)


def test_ids_case_insensitive_duplicate_and_non_string():
    d = copy.deepcopy(NEW)
    d["devices"]["PC-1A2B3C4D"] = {**d["devices"]["pc-1a2b3c4d"], "name": "Otro"}
    assert any(m["code"] == "err.config.id_duplicate" for m in errs(d).values())
    d = copy.deepcopy(NEW)
    d["games"][5] = d["games"]["zelda-0a1b2c3d"]
    assert any(k.startswith("games.5") for k in errs(d))


def test_duplicate_names_are_errors_case_insensitive():
    d = copy.deepcopy(NEW)
    d["devices"]["other-00000000"] = {**d["devices"]["pc-1a2b3c4d"], "name": "mi pc"}
    assert errs(d)["devices.other-00000000.name"]["code"] == "err.config.name_duplicate"
    d = copy.deepcopy(NEW)
    d["games"]["z2-00000000"] = {**d["games"]["zelda-0a1b2c3d"], "name": "ZELDA"}
    assert errs(d)["games.z2-00000000.name"]["code"] == "err.config.name_duplicate"
    # dos ids distintos con el mismo nombre en secciones distintas: permitido
    d = mod(NEW, "games/zelda-0a1b2c3d/name", "Mi PC")
    assert errs(d) == {}


def test_free_names_do_not_need_unique_ids_and_bad_names_fail():
    assert errs(mod(NEW, "games/zelda-0a1b2c3d/name", "Pokémon 🎮 (edición)")) == {}
    for bad in ("", " x", "a  b", "a/b", "a" * 65):
        assert "games.zelda-0a1b2c3d.name" in errs(mod(NEW, "games/zelda-0a1b2c3d/name", bad)), bad


def test_game_id_hub_is_allowed_only_where_it_cannot_clash():
    # un juego con id "hub" conserva su carpeta data/hub/hub; un dispositivo no puede llamarse hub
    d = copy.deepcopy(BASE)
    d["games"]["hub"] = d["games"].pop(GID)
    assert "hub" in parse_config(d).games


# ---------- el id no depende del nombre ----------
def test_id_is_stable_when_renaming():
    c = parse_config(NEW)
    gid = next(iter(c.games))
    c.games[gid].name = "Otro nombre"
    assert next(iter(c.games)) == gid  # el id es la clave; el nombre no la afecta
    out = yaml.safe_load(render_yaml("", c))
    assert gid in out["games"] and out["games"][gid]["name"] == "Otro nombre"


def test_resolve_ref_by_id_name_and_ambiguity():
    items = {"a-1": SimpleNamespace(name="Zelda"), "b-2": SimpleNamespace(name="Mario"),
             "Zelda": SimpleNamespace(name="Otro")}
    assert resolve_ref(items, "b-2") == "b-2" and resolve_ref(items, "Mario") == "b-2"
    assert resolve_ref(items, "mario") == "b-2"  # sin mayúsculas si es único
    assert resolve_ref(items, "nope") is None and resolve_ref(items, "") is None and resolve_ref(items, 3) is None
    with pytest.raises(ConfigError, match="ref_ambiguous"):
        resolve_ref(items, "Zelda")  # id de uno y nombre de otro


# ---------- disco: renombrar no mueve nada ----------
class Disk:
    """Disposición real: juego legado con id slug y datos ya existentes en data/."""

    def __init__(self, tmp):
        self.tmp, self.data = tmp, tmp / "data"
        self.roots = {PC: tmp / "pc", LAPTOP: tmp / "laptop"}
        self.pc_dir, self.lap_dir = self.roots[PC] / "C:/Saves/dq", self.roots[LAPTOP] / "home/usuario/dq"
        self.hub = self.data / "hub" / GID
        self.cfg = parse_config(BASE)
        for d in (self.pc_dir, self.lap_dir, self.hub):
            d.mkdir(parents=True)
            (d / "s.sav").write_text("v1")
            os.utime(d / "s.sav", (500, 500))
        (self.data / "versions" / GID / "2026-01-01_100000" / PC).mkdir(parents=True)
        (self.data / "versions" / GID / "2026-01-01_100000" / PC / "s.sav").write_text("old")
        (self.data / "logs" / GID).mkdir(parents=True)
        (self.data / "logs" / GID / "2026-01-01_100000.log").write_text("x")
        h = fingerprint(self.pc_dir).hash
        save_baseline(self.data, GID, {PC: h, LAPTOP: h, "hub": h})

    def tr(self):
        return {k: LocalTransport(v) for k, v in self.roots.items()}

    def sync(self, cfg=None, game=GID, **kw):
        return run_sync(cfg or self.cfg, game, False, self.data, lambda m: None, self.tr(), **kw)

    def tree(self):
        return sorted(p.relative_to(self.data).as_posix() for p in self.data.rglob("*") if p.is_dir())


@pytest.fixture
def disk(tmp_path):
    return Disk(tmp_path)


def test_rename_game_and_device_changes_no_disk_path_and_keeps_data(disk):
    assert disk.sync()["result"] == "ok"
    before = disk.tree()
    c = disk.cfg
    c.games[GID].name = "DQ7 (renombrado)"
    c.devices[PC].name = "Ordenador de mesa"
    # los datos existentes siguen accesibles con el mismo id
    assert list_versions(disk.data, GID)[0]["sources"][0]["source"] == PC
    assert count_versions(disk.data, GID) == 1 and load_baseline(disk.data, GID).keys() == {PC, LAPTOP, "hub"}
    # cambiar un save en el portátil y sincronizar tras renombrar: sin falsos conflictos, mismas carpetas
    (disk.lap_dir / "s.sav").write_text("v2")
    os.utime(disk.lap_dir / "s.sav", (900, 900))
    st = disk.sync(c)
    assert st["result"] == "ok" and st["winner"] == LAPTOP and st["game"] == GID and st["name"] == "DQ7 (renombrado)"
    assert (disk.hub / "s.sav").read_text() == "v2" and (disk.pc_dir / "s.sav").read_text() == "v2"
    after = disk.tree()
    new_dirs = set(after) - set(before)
    assert all(d.startswith(f"versions/{GID}/") for d in new_dirs), new_dirs  # solo una versión nueva, bajo el mismo id
    assert not any("Ordenador" in d or "renombrado" in d or "DQ7" in d for d in after)
    assert (disk.data / "state" / f"{GID}.json").exists() and (disk.data / "status" / f"{GID}.json").exists()
    assert (disk.data / "locks" / f"{GID}.lock").exists()
    v = list_versions(disk.data, GID, {k: d.name for k, d in c.devices.items()})
    assert {s["source"] for s in v[0]["sources"]} <= {PC, "hub"} and "Ordenador de mesa" in {s["name"] for v_ in v for s in v_["sources"]}


def test_logs_and_messages_show_names_not_ids(disk):
    disk.cfg.games[GID].name = "Mi juego"
    disk.cfg.devices[PC].name = "Ordenador de mesa"
    (disk.lap_dir / "s.sav").write_text("v2")
    os.utime(disk.lap_dir / "s.sav", (900, 900))
    lines = []
    st = run_sync(disk.cfg, "Mi juego", False, disk.data, lines.append, disk.tr())
    text = "\n".join(lines) + st["message"]
    assert "Mi juego" in text and "Ordenador de mesa" in text
    assert GID not in text and st["params"]["winner"] == "laptop" and "Ordenador de mesa" in st["params"]["updated"]
    log = (disk.data / "logs" / GID / st["log"]).read_text()
    assert "Ordenador de mesa" in log and GID not in log


def test_renamed_baseline_no_false_conflict_for_either_rename_order(disk):
    c = disk.cfg
    c.games[GID].name = "Nuevo"
    assert disk.sync(c)["code"] == "err.sync.already_synced"
    c.devices[LAPTOP].name = "Otro portátil"
    assert disk.sync(c)["code"] == "err.sync.already_synced"


def test_game_resolution_by_id_name_and_unknown(disk):
    assert resolve_game(disk.cfg, GID) == GID and resolve_game(disk.cfg, GAME) == GID
    with pytest.raises(SyncAbort, match="game_unknown"):
        resolve_game(disk.cfg, "nada")
    assert disk.sync(game=GAME)["game"] == GID  # run_sync acepta el nombre y trabaja con el id


def test_conflict_with_ids_and_resolution_by_id_or_name(disk):
    for d, content, t in [(disk.pc_dir, "pc", 1000), (disk.lap_dir, "laptop", 2000)]:
        (d / "s.sav").write_text(content)
        os.utime(d / "s.sav", (t, t))
    st = disk.sync()
    assert st["result"] == "conflict"
    sides = {s["id"]: s for s in st["conflict"]["sides"]}
    assert set(sides) == {PC, LAPTOP} and sides[PC]["name"] == PC
    disk.cfg.devices[PC].name = "Ordenador de mesa"
    st = disk.sync(resolution=f"device:{PC}")
    assert st["result"] == "ok" and st["winner"] == PC
    # por nombre, con expect por nombre
    for d, content, t in [(disk.pc_dir, "pc2", 3000), (disk.lap_dir, "laptop2", 4000)]:
        (d / "s.sav").write_text(content)
        os.utime(d / "s.sav", (t, t))
    fps = {s["id"]: s["hash"] for s in disk.sync()["conflict"]["sides"]}
    st = disk.sync(resolution="device:Ordenador de mesa", expect={"Ordenador de mesa": fps[PC], LAPTOP: fps[LAPTOP]})
    assert st["result"] == "ok" and st["winner"] == PC
    for d, content, t in [(disk.pc_dir, "pc3", 5000), (disk.lap_dir, "laptop3", 6000)]:
        (d / "s.sav").write_text(content)
        os.utime(d / "s.sav", (t, t))
    st = disk.sync(resolution="device:fantasma")
    assert st["result"] == "aborted" and "fantasma" in st["message"]


def test_restore_version_by_source_id_or_name(disk):
    disk.cfg.devices[PC].name = "Ordenador de mesa"
    msg = restore_version(disk.cfg, GAME, "2026-01-01_100000", "Ordenador de mesa", disk.data)
    assert msg["params"]["source"] == "Ordenador de mesa" and (disk.hub / "s.sav").read_text() == "old"
    with pytest.raises(SyncAbort):
        restore_version(disk.cfg, GID, "2026-01-01_100000", "../x", disk.data)


# ---------- scheduler e historial ----------
def test_scheduler_cycle_uses_ids_and_records_names(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    cfg = parse_config(NEW)
    gid = "zelda-0a1b2c3d"
    seen = []

    def runner(cfg, game, dry, log, **kw):
        seen.append(game)
        return {"result": "conflict", "message": "ambos lados cambiaron"}

    s = Scheduler(lambda: cfg, lambda g: False, runner=runner)
    out = s.run_cycle()
    assert seen == [gid] and out["games"] == {gid: "conflict"}
    assert out["details"][gid]["name"] == "Zelda" and out["message"].startswith("Zelda:")
    e = history.make_entry(datetime.now(timezone.utc), 1, "scheduled", "conflict", out["details"], out["message"])
    assert e["games"][gid]["name"] == "Zelda"
    busy = Scheduler(lambda: cfg, lambda g: g == gid, runner=runner).run_cycle()
    assert busy["games"] == {gid: "skipped"} and busy["code"] == "err.scheduler.summary"
    assert busy["params"]["causes"] == [{"path": "Zelda", "code": "err.scheduler.skipped_busy", "params": {}}]


def test_history_annotate_current_and_deleted():
    cfg = parse_config(NEW)
    gid = "zelda-0a1b2c3d"
    mk = lambda games: {"id": "e", "started": "2026-01-01T00:00:00+00:00", "games": games}  # noqa: E731
    new_e = mk({gid: {"result": "ok", "message": "", "name": "Nombre viejo"}})
    deleted_new = mk({"gone-00000000": {"result": "ok", "message": "", "name": "Era este"}})
    no_name = mk({"Zelda": {"result": "ok", "message": ""}})   # clave que no es un id actual: no se mapea por nombre
    a = history.annotate([new_e, deleted_new, no_name], cfg.games)
    assert a[0]["games"][gid]["name"] == "Zelda" and a[0]["games"][gid]["id"] == gid  # nombre actual
    assert a[1]["games"]["gone-00000000"]["name"] == "Era este" and a[1]["games"]["gone-00000000"]["id"] is None
    assert a[2]["games"]["Zelda"] == {"result": "ok", "message": "", "id": None, "name": "Zelda"}
    assert new_e["games"][gid]["name"] == "Nombre viejo"  # no muta la entrada original


# ---------- diff ----------
def test_diff_rename_is_a_name_change_not_add_remove():
    old = parse_config(NEW).model_dump(exclude_none=True)
    c = parse_config(NEW)
    c.games["zelda-0a1b2c3d"].name = "Zelda BOTW"
    c.devices["pc-1a2b3c4d"].name = "Torre"
    d = diff_configs(old, c.model_dump(exclude_none=True))
    assert d["games"]["added"] == [] and d["games"]["removed"] == []
    assert d["games"]["changed"] == {"zelda-0a1b2c3d": {"name": {"old": "Zelda", "new": "Zelda BOTW"}}}
    assert d["devices"]["changed"] == {"pc-1a2b3c4d": {"name": {"old": "Mi PC", "new": "Torre"}}}
    assert d["names"]["games"]["zelda-0a1b2c3d"] == "Zelda BOTW" and d["names"]["devices"]["laptop-5e6f7a8b"] == "Portátil"
    assert d["empty"] is False
    assert diff_configs(old, old)["empty"] is True


# ---------- CLI ----------
@pytest.fixture
def cli_env(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(settings, "CONFIG_PATH", tmp_path / "config.yaml")
    d = copy.deepcopy(NEW)
    d["games"]["x"] = {"name": "Mario", "devices": ["pc-1a2b3c4d", "laptop-5e6f7a8b"],
                       "paths": {"pc-1a2b3c4d": "C:/m", "laptop-5e6f7a8b": "/home/usuario/m"}}
    d["games"]["mario-00000000"] = {**d["games"]["x"], "name": "x"}  # el nombre "x" es el id de otro juego
    settings.CONFIG_PATH.write_text(yaml.safe_dump(d, allow_unicode=True))
    roots = {"h1": tmp_path / "pc", "h2": tmp_path / "laptop"}
    monkeypatch.setattr("app.sync.engine.get_transport", lambda dev: LocalTransport(roots[dev.host]))
    (roots["h1"] / "C:/Saves/z").mkdir(parents=True)
    (roots["h1"] / "C:/Saves/z/s.sav").write_text("a")
    (roots["h2"] / "home/usuario/z").mkdir(parents=True)
    return tmp_path


def test_cli_accepts_id_and_name_and_shows_names(cli_env, capsys):
    assert cli.main(["list"]) == 0
    out = capsys.readouterr().out
    assert "Zelda: Mi PC <-> Portátil" in out and "zelda-0a1b2c3d" not in out
    assert cli.main(["sync", "zelda-0a1b2c3d", "--dry-run"]) == 0
    assert cli.main(["sync", "Zelda", "--dry-run"]) == 0
    assert cli.main(["sync", "nada", "--dry-run"]) == 2
    assert "game_unknown" in capsys.readouterr().err


def test_cli_ambiguous_name_is_clear_error(cli_env, capsys):
    capsys.readouterr()
    assert cli.main(["sync", "x", "--dry-run"]) == 2
    err = capsys.readouterr().err
    assert "ref_ambiguous" in err and "Mario" in err
    assert cli.main(["versions", "x"]) == 2


def test_cli_versions_by_name(cli_env, capsys):
    v = settings.DATA_DIR / "versions" / "zelda-0a1b2c3d" / "2026-01-01_100000" / "pc-1a2b3c4d"
    v.mkdir(parents=True)
    (v / "s.sav").write_text("o")
    capsys.readouterr()
    assert cli.main(["versions", "Zelda"]) == 0
    assert "Mi PC(1)" in capsys.readouterr().out


# ---------- API ----------
@pytest.fixture
def api(client, tmp_path, monkeypatch):  # noqa: F811
    login(client)
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config" / "config.yaml").write_text(yaml.safe_dump(NEW, allow_unicode=True))
    roots = {"h1": tmp_path / "pc", "h2": tmp_path / "laptop"}
    monkeypatch.setattr("app.sync.engine.get_transport", lambda dev: LocalTransport(roots[dev.host]))
    (roots["h1"] / "C:/Saves/z").mkdir(parents=True)
    (roots["h1"] / "C:/Saves/z/s.sav").write_text("a")
    (roots["h2"] / "home/usuario/z").mkdir(parents=True)
    return client


def wait_run(c, run_id):
    r = c.get(f"/api/runs/{run_id}/stream")
    done = [ln for ln in r.text.split("\n\n") if ln.startswith("event: done")]
    return json.loads(done[0].split("data: ", 1)[1])


def test_api_sync_by_id_and_by_name_and_status_keys(api):
    gid = "zelda-0a1b2c3d"
    for ref in (gid, "Zelda", "zelda"):
        r = api.post(f"/api/sync/{ref}", json={})
        assert r.status_code == 200, ref
        st = wait_run(api, r.json()["run_id"])
        assert st["result"] == "ok" and st["game"] == gid and st["name"] == "Zelda"
    assert api.post("/api/sync/nada", json={}).status_code == 404
    status = api.get("/api/status").json()
    assert list(status) == [gid] and status[gid]["name"] == "Zelda"
    assert (api.get("/api/versions/Zelda").json() == api.get(f"/api/versions/{gid}").json())
    assert api.get("/api/versions/nada").status_code == 404
    assert api.get("/api/versions/Zelda/limit").json()["max"] == 20


def test_api_rename_keeps_data_reachable(api, tmp_path):
    gid = "zelda-0a1b2c3d"
    wait_run(api, api.post(f"/api/sync/{gid}", json={}).json()["run_id"])
    cur = api.get("/api/config").json()
    cfg = copy.deepcopy(cur["config"])
    cfg["games"][gid]["name"] = "The Legend"
    r = api.put("/api/config", json={"config": cfg, "base_version": cur["version"]})
    assert r.status_code == 200
    raw = yaml.safe_load((tmp_path / "config" / "config.yaml").read_text())
    assert list(raw["games"]) == [gid] and raw["games"][gid]["name"] == "The Legend"
    assert (tmp_path / "data" / "hub" / gid / "s.sav").read_text() == "a"
    assert api.post("/api/sync/The Legend", json={}).status_code == 200
    assert api.post("/api/sync/Zelda", json={}).status_code == 404  # el nombre viejo ya no existe
    d = api.post("/api/config/diff", json={"config": cfg}).json()["diff"]
    assert d["empty"] is True  # ya guardado


def test_api_conflict_resolution_device_by_name(api, tmp_path):
    gid = "zelda-0a1b2c3d"
    roots = {"pc": tmp_path / "pc/C:/Saves/z", "lap": tmp_path / "laptop/home/usuario/z"}
    wait_run(api, api.post(f"/api/sync/{gid}", json={}).json()["run_id"])
    for d, c, t in [(roots["pc"], "pc", 1000), (roots["lap"], "lap", 2000)]:
        (d / "s.sav").write_text(c)
        os.utime(d / "s.sav", (t, t))
    st = wait_run(api, api.post(f"/api/sync/{gid}", json={}).json()["run_id"])
    assert st["result"] == "conflict" and {s["name"] for s in st["conflict"]["sides"]} == {"Mi PC", "Portátil"}
    st = wait_run(api, api.post("/api/sync/Zelda", json={"resolution": "device:Mi PC"}).json()["run_id"])
    assert st["result"] == "ok" and st["winner"] == "pc-1a2b3c4d"
    assert api.post("/api/sync/Zelda", json={"resolution": "device:"}).status_code == 422


def test_api_history_annotated_with_names(api):
    now = datetime.now(timezone.utc)
    history.append(history.make_entry(now, 1, "scheduled", "ok",
                                      {"zelda-0a1b2c3d": {"result": "ok", "message": "", "name": "Nombre viejo"}}, ""), now=now)
    es = api.get("/api/scheduler/history").json()["entries"]
    g = es[0]["games"]["zelda-0a1b2c3d"]
    assert g["name"] == "Zelda" and g["id"] == "zelda-0a1b2c3d"   # nombre actual de la config


def test_api_validate_reports_id_paths_and_test_device_without_name(api):
    bad = mod(NEW, "games/zelda-0a1b2c3d/devices", ["pc-1a2b3c4d", "nope-1"])
    r = api.post("/api/config/validate", json={"config": bad}).json()
    assert r["ok"] is False and "games.zelda-0a1b2c3d.devices.1" in r["errors"]
    r = api.post("/api/devices/test", json={"device": {"host": "-x", "user": "u", "os": "linux"}}).json()
    assert r["ok"] is False and r["code"] == "err.main.device_invalid" and r["params"]["causes"][0]["path"] == "host"


def _legacy_api(client, tmp_path):
    login(client)
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config" / "config.yaml").write_text(yaml.safe_dump(BASE, allow_unicode=True))
    return client


def test_api_config_legacy_exposes_name_and_id(client, tmp_path):
    api = _legacy_api(client, tmp_path)
    games = api.get("/api/config").json()["config"]["games"]
    assert list(games) == [GID] and games[GID]["name"] == GAME


def test_api_status_name_is_current_config_name_not_id(client, tmp_path):
    api = _legacy_api(client, tmp_path)
    sd = tmp_path / "data" / "status"
    sd.mkdir(parents=True)
    # estado guardado con el id (o sin nombre) en lugar del nombre: la UI no debe verlo como título
    (sd / f"{GID}.json").write_text(json.dumps({"game": GID, "name": GID, "result": "ok", "message": "m"}))
    got = api.get("/api/status").json()[GID]
    assert got["game"] == GID and got["name"] == GAME
    (sd / f"{GID}.json").write_text(json.dumps({"result": "ok", "message": "m"}))
    assert api.get("/api/status").json()[GID]["name"] == GAME
