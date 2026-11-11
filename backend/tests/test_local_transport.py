"""LocalDeviceTransport («Este equipo»): sistema de ficheros local sin SSH, rsync ni tar."""
import os
import subprocess
import sys
import time

import pytest

from app import transport as T
from app.config.models import parse_config
from app.sync import fingerprint, relfiles
from app.transport import LocalDeviceTransport, TransportError, get_transport, local_folder_status, local_path

root_only = pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root ignora permisos")


def put(d, rel, content="x", mtime=None):
    f = d / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(content if isinstance(content, bytes) else content.encode())
    if mtime is not None:
        os.utime(f, (mtime, mtime))
    return f


@pytest.fixture
def tr():
    return LocalDeviceTransport()


# ---- validación de rutas ----
@pytest.mark.parametrize("p", ["", "   ", "relativa/saves", "saves", "/a/../etc", "/a/\x00b", None, 5])
def test_ruta_invalida(tr, p):
    with pytest.raises(TransportError):
        tr.exists(p)


def test_local_path_ok(tmp_path):
    assert local_path(str(tmp_path / "a")) == tmp_path / "a"


def test_check_siempre_online(tr):
    assert tr.check() is None and tr.first_use is False


def test_get_transport_local_y_remoto():
    c = parse_config({"devices": {"a": {"name": "A", "local": True, "os": "linux"},
                                  "b": {"name": "B", "host": "192.0.2.1", "user": "u", "os": "linux"}}})
    assert isinstance(get_transport(c.devices["a"]), LocalDeviceTransport)
    assert type(get_transport(c.devices["b"])).__name__ == "PosixTransport"


def test_get_transport_local_en_docker_falla(monkeypatch):
    c = parse_config({"devices": {"a": {"name": "A", "local": True, "os": "linux"}}})
    monkeypatch.setenv("CHECKPOINT_RUNTIME", "docker")
    with pytest.raises(TransportError, match="err.config.local_docker"):
        get_transport(c.devices["a"])


# ---- exists ----
def test_exists(tr, tmp_path):
    assert not tr.exists(str(tmp_path / "no"))
    (tmp_path / "s").mkdir()
    assert tr.exists(str(tmp_path / "s"))
    put(tmp_path, "f.txt")
    with pytest.raises(TransportError, match="not_a_folder"):
        tr.exists(str(tmp_path / "f.txt"))


@root_only
def test_exists_sin_permiso(tr, tmp_path):
    d = tmp_path / "s"
    d.mkdir()
    d.chmod(0)
    try:
        with pytest.raises(TransportError, match="permiso"):
            tr.exists(str(d))
    finally:
        d.chmod(0o755)


@root_only
def test_exists_padre_sin_permiso(tr, tmp_path):
    p = tmp_path / "padre"
    (p / "s").mkdir(parents=True)
    p.chmod(0)
    try:
        with pytest.raises(TransportError):
            tr.exists(str(p / "s"))
    finally:
        p.chmod(0o755)


# ---- pull ----
def test_pull_copia_arbol_con_mtime(tr, tmp_path):
    s, d = tmp_path / "saves", tmp_path / "dest"
    put(s, "a.sav", "A", 1000)
    put(s, "sub/dir/b.sav", "B", 2000)
    put(s, "vacio.bin", b"", 3000)
    (s / "carpeta_vacia").mkdir()
    d.mkdir()
    tr.pull(str(s), d)
    assert (d / "a.sav").read_text() == "A" and (d / "sub/dir/b.sav").read_text() == "B"
    assert (d / "vacio.bin").read_bytes() == b""
    assert int((d / "sub/dir/b.sav").stat().st_mtime) == 2000 and int((d / "vacio.bin").stat().st_mtime) == 3000
    assert (d / "carpeta_vacia").is_dir()
    assert fingerprint(s).hash == fingerprint(d).hash


def test_pull_nombres_raros(tr, tmp_path):
    s, d = tmp_path / "saves", tmp_path / "dest"
    nombres = ["con espacios.sav", "ñandú-€-日本語.dat", "sím#bolos(1)[2]+3,@~=.x", "emoji 🎮.sav", ".oculto",
               "UPPER.SAV", "a b/c d/e f.sav"]
    for n in nombres:
        put(s, n, n)
    d.mkdir()
    tr.pull(str(s), d)
    assert relfiles(d) == set(nombres)
    for n in nombres:
        assert (d / n).read_text() == n


def test_pull_fichero_grande(tr, tmp_path):
    s, d = tmp_path / "saves", tmp_path / "dest"
    big = os.urandom(1024) * (6 * 1024)  # 6 MiB
    put(s, "big.bin", big)
    d.mkdir()
    tr.pull(str(s), d)
    assert (d / "big.bin").read_bytes() == big


def test_pull_ignora_symlinks_fuera_de_ruta(tr, tmp_path):
    fuera = tmp_path / "secreto"
    put(fuera, "pass.txt", "SECRETO")
    s, d = tmp_path / "saves", tmp_path / "dest"
    put(s, "ok.sav", "ok")
    os.symlink(fuera, s / "enlace_dir")
    os.symlink(fuera / "pass.txt", s / "enlace_fichero")
    os.symlink("/etc/hostname", s / "enlace_abs")
    os.symlink(s / "ok.sav", s / "enlace_interno")  # tampoco: nunca se siguen
    d.mkdir()
    tr.pull(str(s), d)
    assert relfiles(d) == {"ok.sav"}
    assert not any(p.is_symlink() for p in d.rglob("*"))
    assert "SECRETO" not in "".join(p.read_text() for p in d.rglob("*") if p.is_file())


def test_pull_carpeta_de_saves_es_symlink_se_resuelve(tr, tmp_path):
    real = tmp_path / "real"
    put(real, "a.sav", "A")
    os.symlink(real, tmp_path / "enlace")
    d = tmp_path / "dest"
    d.mkdir()
    assert tr.exists(str(tmp_path / "enlace"))
    tr.pull(str(tmp_path / "enlace"), d)
    assert (d / "a.sav").read_text() == "A"


@root_only
def test_pull_fichero_ilegible_error_claro(tr, tmp_path):
    s, d = tmp_path / "saves", tmp_path / "dest"
    f = put(s, "a.sav", "A")
    f.chmod(0)
    d.mkdir()
    try:
        with pytest.raises(TransportError, match="a.sav"):
            tr.pull(str(s), d)
    finally:
        f.chmod(0o644)


@root_only
def test_pull_subcarpeta_ilegible_error_claro(tr, tmp_path):
    s, d = tmp_path / "saves", tmp_path / "dest"
    put(s, "sub/a.sav", "A")
    (s / "sub").chmod(0)
    d.mkdir()
    try:
        with pytest.raises(TransportError, match="sub"):
            tr.pull(str(s), d)
    finally:
        (s / "sub").chmod(0o755)


def test_pull_inexistente_error(tr, tmp_path):
    with pytest.raises(TransportError, match="folder_missing"):
        tr.pull(str(tmp_path / "no"), tmp_path)


# ---- push ----
def test_push_crea_carpeta_y_padres(tr, tmp_path):
    src = tmp_path / "src"
    put(src, "a.sav", "A", 1234)
    put(src, "x/y/b.sav", "B", 4321)
    dst = tmp_path / "no" / "existe" / "saves"
    tr.push(src, str(dst))
    assert (dst / "a.sav").read_text() == "A" and (dst / "x/y/b.sav").read_text() == "B"
    assert int((dst / "a.sav").stat().st_mtime) == 1234 and int((dst / "x/y/b.sav").stat().st_mtime) == 4321
    assert fingerprint(src).hash == fingerprint(dst).hash


def test_push_borra_extras_y_reemplaza(tr, tmp_path):
    src, dst = tmp_path / "src", tmp_path / "saves"
    put(src, "nuevo.sav", "N")
    put(dst, "viejo.sav", "V")
    put(dst, "sub/otro.sav", "O")
    put(dst, "nuevo.sav", "antiguo")
    tr.push(src, str(dst), extras=["viejo.sav"])
    assert relfiles(dst) == {"nuevo.sav"} and (dst / "nuevo.sav").read_text() == "N"
    assert not (dst / "sub").exists()


def test_push_origen_vacio_vacia_destino(tr, tmp_path):
    src, dst = tmp_path / "src", tmp_path / "saves"
    src.mkdir()
    put(dst, "a.sav")
    tr.push(src, str(dst))
    assert dst.is_dir() and relfiles(dst) == set()


def test_push_no_deja_temporales(tr, tmp_path):
    src, dst = tmp_path / "src", tmp_path / "padre" / "saves"
    put(src, "a.sav")
    put(dst, "b.sav")
    tr.push(src, str(dst))
    assert sorted(p.name for p in dst.parent.iterdir()) == ["saves"]


def test_push_atomico_si_falla_la_copia_el_destino_queda_intacto(tr, tmp_path, monkeypatch):
    src, dst = tmp_path / "src", tmp_path / "padre" / "saves"
    put(src, "a.sav", "NUEVO")
    put(src, "b.sav", "NUEVO2")
    put(dst, "a.sav", "ORIGINAL")
    real = T.shutil.copy2
    n = {"c": 0}

    def flaky(a, b, *k, **kw):
        n["c"] += 1
        if n["c"] == 2:
            raise OSError(28, "No space left on device")
        return real(a, b, *k, **kw)
    monkeypatch.setattr(T.shutil, "copy2", flaky)
    with pytest.raises(TransportError, match="space"):
        tr.push(src, str(dst))
    assert relfiles(dst) == {"a.sav"} and (dst / "a.sav").read_text() == "ORIGINAL"
    assert sorted(p.name for p in dst.parent.iterdir()) == ["saves"]  # temporal retirado


def test_push_si_falla_el_rename_final_se_deshace(tr, tmp_path, monkeypatch):
    src, dst = tmp_path / "src", tmp_path / "padre" / "saves"
    put(src, "a.sav", "NUEVO")
    put(dst, "a.sav", "ORIGINAL")
    real = os.rename
    calls = []

    def rn(a, b):
        calls.append((str(a), str(b)))
        if len(calls) == 2:  # new -> target
            raise OSError(5, "Input/output error")
        return real(a, b)
    monkeypatch.setattr(T.os, "rename", rn)
    with pytest.raises(TransportError, match="Input/output"):
        tr.push(src, str(dst))
    assert (dst / "a.sav").read_text() == "ORIGINAL"
    assert sorted(p.name for p in dst.parent.iterdir()) == ["saves"]


@root_only
def test_push_padre_sin_escritura_usa_reemplazo_en_sitio(tr, tmp_path):
    src = tmp_path / "src"
    put(src, "a.sav", "NUEVO", 111)
    put(src, "sub/c.sav", "C", 222)
    padre = tmp_path / "padre"
    dst = padre / "saves"
    put(dst, "a.sav", "ORIGINAL")
    put(dst, "extra.sav", "E")
    put(dst, "dir_extra/z.sav", "Z")
    padre.chmod(0o555)  # no se puede crear la carpeta hermana
    try:
        tr.push(src, str(dst))
    finally:
        padre.chmod(0o755)
    assert relfiles(dst) == {"a.sav", "sub/c.sav"} and (dst / "a.sav").read_text() == "NUEVO"
    assert int((dst / "a.sav").stat().st_mtime) == 111
    assert not (dst / "dir_extra").exists()
    assert fingerprint(src).hash == fingerprint(dst).hash


def test_push_en_sitio_directo(tr, tmp_path, monkeypatch):
    """Fuerza el camino de reemplazo fichero a fichero (_swap no disponible)."""
    monkeypatch.setattr(LocalDeviceTransport, "_swap", lambda self, s, t: False)
    src, dst = tmp_path / "src", tmp_path / "saves"
    put(src, "a.sav", "NUEVO", 111)
    put(src, "d1/d2/c.sav", "C", 222)
    (src / "vacia").mkdir()
    put(dst, "a.sav", "ORIGINAL")
    put(dst, "d1/viejo.sav", "V")
    put(dst, "d3/x.sav", "X")
    tr.push(src, str(dst))
    assert relfiles(dst) == {"a.sav", "d1/d2/c.sav"}
    assert (dst / "vacia").is_dir() and not (dst / "d3").exists()
    assert fingerprint(src).hash == fingerprint(dst).hash
    assert [p.name for p in dst.rglob(".*checkpoint*")] == []


def test_push_en_sitio_fichero_por_carpeta(tr, tmp_path, monkeypatch):
    monkeypatch.setattr(LocalDeviceTransport, "_swap", lambda self, s, t: False)
    src, dst = tmp_path / "src", tmp_path / "saves"
    put(src, "x/f.sav", "F")  # en destino 'x' es un fichero
    put(src, "y", "fichero")  # en destino 'y' es carpeta
    put(dst, "x", "fichero")
    put(dst, "y/z.sav", "Z")
    tr.push(src, str(dst))
    assert relfiles(dst) == {"x/f.sav", "y"}


def test_push_no_sigue_symlinks_del_destino(tr, tmp_path, monkeypatch):
    """Un symlink dentro del destino que apunta fuera nunca se escribe a través de él."""
    for swap in (True, False):
        if not swap:
            monkeypatch.setattr(LocalDeviceTransport, "_swap", lambda self, s, t: False)
        fuera = tmp_path / f"fuera{swap}"
        fuera.mkdir()
        (fuera / "intacto.txt").write_text("INTACTO")
        src, dst = tmp_path / f"src{swap}", tmp_path / f"saves{swap}"
        put(src, "enlace/a.sav", "A")
        put(dst, "base.sav", "B")
        os.symlink(fuera, dst / "enlace")
        tr.push(src, str(dst))
        assert sorted(p.name for p in fuera.iterdir()) == ["intacto.txt"]
        assert (fuera / "intacto.txt").read_text() == "INTACTO"
        assert (dst / "enlace" / "a.sav").read_text() == "A"
        assert not (dst / "enlace").is_symlink()


def test_push_conserva_symlinks_ajenos_al_contenido(tr, tmp_path):
    fuera = tmp_path / "fuera"
    put(fuera, "d.txt")
    src, dst = tmp_path / "src", tmp_path / "saves"
    put(src, "a.sav", "A")
    put(dst, "viejo.sav")
    os.symlink(fuera, dst / "enlace")
    tr.push(src, str(dst))
    assert (dst / "enlace").is_symlink() and os.readlink(dst / "enlace") == str(fuera)
    assert relfiles(dst) == {"a.sav"} and (fuera / "d.txt").exists()


def test_push_destino_es_symlink_a_carpeta_actualiza_el_real(tr, tmp_path):
    real = tmp_path / "real"
    put(real, "viejo.sav")
    os.symlink(real, tmp_path / "enlace")
    src = tmp_path / "src"
    put(src, "a.sav", "A")
    tr.push(src, str(tmp_path / "enlace"))
    assert (tmp_path / "enlace").is_symlink()  # el enlace del usuario se conserva
    assert relfiles(real) == {"a.sav"}


def test_push_origen_con_symlinks_no_los_copia(tr, tmp_path):
    fuera = tmp_path / "fuera"
    put(fuera, "pass.txt", "SECRETO")
    src, dst = tmp_path / "src", tmp_path / "saves"
    put(src, "a.sav", "A")
    os.symlink(fuera, src / "enlace")
    tr.push(src, str(dst))
    assert relfiles(dst) == {"a.sav"} and not (dst / "enlace").exists()


def test_push_ruta_es_fichero_error(tr, tmp_path):
    src = tmp_path / "src"
    put(src, "a.sav")
    f = put(tmp_path, "esfichero")
    with pytest.raises(TransportError, match="not_a_folder"):
        tr.push(src, str(f))


@root_only
def test_push_sin_permiso_error_claro_y_sin_cambios(tr, tmp_path):
    src = tmp_path / "src"
    put(src, "a.sav", "NUEVO")
    padre = tmp_path / "padre"
    dst = padre / "saves"
    put(dst, "a.sav", "ORIGINAL")
    dst.chmod(0o555)
    padre.chmod(0o555)
    try:
        with pytest.raises(TransportError, match="a.sav|permiso|Permission"):
            tr.push(src, str(dst))
    finally:
        padre.chmod(0o755)
        dst.chmod(0o755)
    assert (dst / "a.sav").read_text() == "ORIGINAL"


@root_only
def test_push_a_raiz_sin_permiso_no_crea_nada(tr, tmp_path):
    src = tmp_path / "src"
    put(src, "a.sav")
    ro = tmp_path / "ro"
    ro.mkdir()
    ro.chmod(0o555)
    try:
        with pytest.raises(TransportError):
            tr.push(src, str(ro / "a" / "b"))
    finally:
        ro.chmod(0o755)
    assert list(ro.iterdir()) == []


def test_push_idempotente_y_ciclo_pull_push(tr, tmp_path):
    a, b, c = tmp_path / "a", tmp_path / "b", tmp_path / "c"
    put(a, "x.sav", "1", 10)
    put(a, "s/y.sav", "2", 20)
    c.mkdir()
    tr.pull(str(a), c)
    tr.push(c, str(b))
    tr.push(c, str(b))
    assert fingerprint(a).hash == fingerprint(b).hash
    assert int((b / "s/y.sav").stat().st_mtime) == 20


# ---- procesos ----
def cp(code, out=b"", err=b""):
    return subprocess.CompletedProcess([], code, out, err)


def run_with(monkeypatch, plat, results, calls):
    monkeypatch.setattr(sys, "platform", plat)

    def run(args, **kw):
        calls.append(args)
        r = results.pop(0)
        if isinstance(r, Exception):
            raise r
        return r
    return LocalDeviceTransport(run=run)


def test_proceso_linux_corriendo(monkeypatch):
    calls = []
    t = run_with(monkeypatch, "linux", [cp(0, b"4242\n")], calls)
    assert t.process_running("juego") is True
    assert calls[0] == ["pgrep", "-f", "--", "[j]uego"]


def test_proceso_linux_no_corriendo(monkeypatch):
    assert run_with(monkeypatch, "linux", [cp(1)], []).process_running("juego") is False


def test_proceso_ignora_a_checkpoint_mismo(monkeypatch):
    t = run_with(monkeypatch, "linux", [cp(0, f"{os.getpid()}\n".encode())], [])
    assert t.process_running("python") is False


def test_proceso_macos(monkeypatch):
    calls = []
    t = run_with(monkeypatch, "darwin", [cp(0, b"1\n")], calls)
    assert t.process_running("Game") is True and calls[0][0] == "pgrep"


def test_proceso_pgrep_error(monkeypatch):
    with pytest.raises(TransportError, match="pgrep"):
        run_with(monkeypatch, "linux", [cp(2, b"", b"boom")], []).process_running("juego")


def test_proceso_timeout(monkeypatch):
    with pytest.raises(TransportError, match="process_timeout"):
        run_with(monkeypatch, "linux", [subprocess.TimeoutExpired("pgrep", 15)], []).process_running("juego")


def test_proceso_sin_pgrep_usa_proc(monkeypatch):
    t = run_with(monkeypatch, "linux", [FileNotFoundError("pgrep")], [])
    monkeypatch.setattr(LocalDeviceTransport, "_proc_scan", staticmethod(lambda n: n == "juego"))
    assert t.process_running("juego") is True


@pytest.mark.skipif(not os.path.isdir("/proc"), reason="solo Linux")
def test_proc_scan_real():
    marcador = "checkpoint-test-marker-" + os.urandom(4).hex()
    p = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(30)", marcador])
    try:
        # /proc/<pid>/cmdline puede tardar un instante en reflejar el exec en algunos kernels: se reintenta, sin dormir fijo.
        end = time.monotonic() + 5
        while not LocalDeviceTransport._proc_scan(marcador) and time.monotonic() < end:
            time.sleep(0.02)
        assert LocalDeviceTransport._proc_scan(marcador) is True
        assert LocalDeviceTransport._proc_scan("no-existe-" + os.urandom(6).hex()) is False
    finally:
        p.terminate()
        p.wait()


@pytest.mark.skipif(not os.path.isdir("/proc") or not __import__("shutil").which("pgrep"), reason="necesita pgrep")
def test_pgrep_real():
    marcador = "checkpoint_marker_" + os.urandom(4).hex()
    p = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(30)", marcador])
    try:
        t = LocalDeviceTransport()
        assert t.process_running(marcador) is True
        assert t.process_running("nadie_" + os.urandom(6).hex()) is False
    finally:
        p.terminate()
        p.wait()


def test_proceso_windows_tasklist(monkeypatch):
    calls = []
    out = b"Image Name  PID\ngame.exe  12  Console\n"
    t = run_with(monkeypatch, "win32", [cp(0, out), cp(0, b"INFO: No tasks are running which match.")], calls)
    assert t.process_running("game.exe") is True
    assert calls[0] == ["tasklist", "/FI", "IMAGENAME eq game.exe", "/NH"]
    assert t.process_running("game.exe") is False
    with pytest.raises(TransportError, match="tasklist"):
        run_with(monkeypatch, "win32", [cp(1, b"", b"x")], []).process_running("game.exe")


@pytest.mark.parametrize("n", ["", "-x", "a;b", "a|b", "$(id)", "a`b`", "x" * 70])
def test_proceso_nombre_invalido(tr, n):
    with pytest.raises(TransportError, match="process_invalid"):
        tr.process_running(n)


def test_sin_shell():
    import inspect
    assert "shell=True" not in inspect.getsource(T)


# ---- comprobación de carpeta (botón «Comprobar carpeta») ----
def test_folder_status_sin_ruta():
    r = local_folder_status(None)
    assert r["ok"] and r["code"] == "err.transport.local_info"


def test_folder_status_ok(tmp_path):
    r = local_folder_status(str(tmp_path))
    assert r["ok"] and r["code"] == "err.transport.folder_ok" and r["params"] == {}
    assert list(tmp_path.iterdir()) == []  # el fichero de prueba se borra


def test_folder_status_no_existe_pero_creable(tmp_path):
    r = local_folder_status(str(tmp_path / "a" / "b"))
    assert r["ok"] and r["code"] == "err.transport.folder_will_be_created"
    assert not (tmp_path / "a").exists()


def test_folder_status_es_fichero(tmp_path):
    f = put(tmp_path, "f")
    assert not local_folder_status(str(f))["ok"]


def test_folder_status_rutas_invalidas():
    for p in ("relativa", "/a/../b", "/a\x00b"):
        assert local_folder_status(p)["ok"] is False


@root_only
def test_folder_status_ilegible(tmp_path):
    d = tmp_path / "s"
    d.mkdir()
    d.chmod(0)
    try:
        r = local_folder_status(str(d))
    finally:
        d.chmod(0o755)
    assert not r["ok"] and r["code"] == "err.transport.unreadable"


@root_only
def test_folder_status_solo_lectura(tmp_path):
    d = tmp_path / "s"
    d.mkdir()
    d.chmod(0o555)
    try:
        r = local_folder_status(str(d))
    finally:
        d.chmod(0o755)
    assert not r["ok"] and r["code"] == "err.transport.not_writable"


@root_only
def test_folder_status_inexistente_sin_permiso_de_creacion(tmp_path):
    d = tmp_path / "ro"
    d.mkdir()
    d.chmod(0o555)
    try:
        r = local_folder_status(str(d / "nueva"))
    finally:
        d.chmod(0o755)
    assert not r["ok"] and r["code"] == "err.transport.cannot_create_no_permission"
