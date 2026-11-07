"""Entorno de ejecución: Docker o nativo, y plataforma del sistema.

La app no usa nada más del sistema que esto: es lo único que se expone a la UI.
"""
import os
import sys
from pathlib import Path

RUNTIMES = ("docker", "native")


def _flag(value) -> bool:
    return str(value or "").strip().lower() in ("1", "true", "yes", "on")


def runtime_name() -> str:
    """'docker' o 'native'. Orden: CHECKPOINT_RUNTIME (override explícito) > CHECKPOINT_IN_DOCKER (lo fija
    el Dockerfile) > ficheros marcadores del contenedor (/.dockerenv, /run/.containerenv) > native."""
    forced = (os.environ.get("CHECKPOINT_RUNTIME") or "").strip().lower()
    if forced in RUNTIMES:
        return forced
    if _flag(os.environ.get("CHECKPOINT_IN_DOCKER")):
        return "docker"
    for marker in _CONTAINER_MARKERS:
        if Path(marker).exists():
            return "docker"
    return "native"


_CONTAINER_MARKERS = ("/.dockerenv", "/run/.containerenv")


def running_in_docker() -> bool:
    return runtime_name() == "docker"


def platform_name() -> str:
    """'linux' | 'windows' | 'macos' (otros sistemas se tratan como linux: rutas POSIX)."""
    p = sys.platform
    if p.startswith("win") or p == "cygwin":
        return "windows"
    if p == "darwin":
        return "macos"
    return "linux"


def info() -> dict:
    return {"runtime": runtime_name(), "platform": platform_name()}
