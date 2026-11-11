import sys
from pathlib import Path

import pytest

from app.core import runtime, settings


@pytest.fixture(autouse=True)
def limpio(monkeypatch):
    monkeypatch.delenv("CHECKPOINT_RUNTIME", raising=False)
    monkeypatch.setattr(runtime, "_CONTAINER_MARKERS", ())


def test_sin_pistas_es_nativo():
    assert runtime.runtime_name() == "native" and not runtime.running_in_docker()


def test_marcador_dockerenv_simulado(monkeypatch, tmp_path):
    m = tmp_path / ".dockerenv"
    monkeypatch.setattr(runtime, "_CONTAINER_MARKERS", (str(m),))
    assert not runtime.running_in_docker()
    m.write_text("")
    assert runtime.running_in_docker()


def test_override_explicito_gana_a_todo(monkeypatch, tmp_path):
    m = tmp_path / ".dockerenv"
    m.write_text("")
    monkeypatch.setattr(runtime, "_CONTAINER_MARKERS", (str(m),))
    monkeypatch.setenv("CHECKPOINT_RUNTIME", "native")
    assert runtime.runtime_name() == "native"
    monkeypatch.setenv("CHECKPOINT_RUNTIME", "DOCKER")
    assert runtime.runtime_name() == "docker"
    m.unlink()
    assert runtime.runtime_name() == "docker"  # el override manda aunque no haya pistas


def test_override_invalido_se_ignora(monkeypatch, tmp_path):
    monkeypatch.setenv("CHECKPOINT_RUNTIME", "kubernetes")
    assert runtime.runtime_name() == "native"
    m = tmp_path / ".dockerenv"
    m.write_text("")
    monkeypatch.setattr(runtime, "_CONTAINER_MARKERS", (str(m),))
    assert runtime.runtime_name() == "docker"


@pytest.mark.parametrize("plat,esperado", [("linux", "linux"), ("win32", "windows"), ("cygwin", "windows"),
                                           ("darwin", "macos"), ("freebsd13", "linux")])
def test_plataforma(monkeypatch, plat, esperado):
    monkeypatch.setattr(sys, "platform", plat)
    assert runtime.platform_name() == esperado


def test_info_solo_runtime_y_plataforma():
    assert set(runtime.info()) == {"runtime", "platform"}


# ---- rutas por defecto (settings) ----
def test_native_home_linux(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "linux")
    assert settings.native_home({"XDG_DATA_HOME": str(tmp_path)}) == tmp_path / "checkpoint"
    assert settings.native_home({}) == Path.home() / ".local" / "share" / "checkpoint"
    assert settings.native_home({"CHECKPOINT_HOME_DIR": str(tmp_path / "x")}) == tmp_path / "x"


def test_native_home_windows_y_macos(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    assert settings.native_home({"APPDATA": "/appdata"}) == Path("/appdata") / "checkpoint"
    monkeypatch.setattr(sys, "platform", "darwin")
    assert settings.native_home({}) == Path.home() / "Library" / "Application Support" / "checkpoint"


def test_rutas_por_defecto_docker_no_cambian(monkeypatch):
    monkeypatch.setenv("CHECKPOINT_RUNTIME", "docker")
    assert settings._paths() == ("/config/config.yaml", "/data", "/keys/id_ed25519", "/keys/known_hosts",
                                 "/app/static")


def test_rutas_por_defecto_nativo_sin_rutas_de_docker(monkeypatch, tmp_path):
    monkeypatch.setenv("CHECKPOINT_RUNTIME", "native")
    monkeypatch.setenv("CHECKPOINT_HOME_DIR", str(tmp_path))
    cfg, data, key, kh, static = settings._paths()
    assert cfg == str(tmp_path / "config" / "config.yaml") and data == str(tmp_path / "data")
    assert key == str(tmp_path / "keys" / "id_ed25519") and kh == str(tmp_path / "keys" / "known_hosts")
    assert not static.startswith("/app/")


def test_dockerfile_fija_runtime_docker():
    df = (Path(__file__).resolve().parents[2] / "Dockerfile").read_text()
    assert "CHECKPOINT_RUNTIME=docker" in df and "IN_DOCKER" not in df
