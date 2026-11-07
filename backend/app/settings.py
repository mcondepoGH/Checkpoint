"""Ajustes desde variables de entorno (CHECKPOINT_*): USER, PASSWORD, PORT, HOST, HOME_DIR, SESSION_HOURS,
COOKIE_SECURE, TRUST_PROXY y RUNTIME. El resto de rutas y valores se derivan de ellas o son constantes."""
import os
from pathlib import Path

from .runtime import platform_name, running_in_docker

SSH_TIMEOUT = 8  # s de conexión SSH


def env(suffix, default=None, environ=None):
    """Lee CHECKPOINT_<suffix>; vacío o ausente = valor por defecto."""
    environ = os.environ if environ is None else environ
    v = environ.get("CHECKPOINT_" + suffix)
    return default if v in (None, "") else v


def native_home(environ=None) -> Path:
    """Carpeta base de Checkpoint en modo nativo (sin Docker). CHECKPOINT_HOME_DIR la fija a mano; por defecto
    ~/.local/share/checkpoint (Linux, respeta XDG_DATA_HOME), ~/Library/Application Support/checkpoint (macOS)
    o %APPDATA%\\checkpoint (Windows). En Docker las rutas son /config, /data y /keys."""
    environ = os.environ if environ is None else environ
    forced = env("HOME_DIR", None, environ)
    if forced:
        return Path(forced).expanduser()
    plat = platform_name()
    if plat == "windows":
        return Path(environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / "checkpoint"
    if plat == "macos":
        return Path.home() / "Library" / "Application Support" / "checkpoint"
    return Path(environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "checkpoint"


def _static_default() -> str:
    """Docker: /app/static. Nativo: static/ junto a app/ si existe; si no, frontend/dist del proyecto."""
    if running_in_docker():
        return "/app/static"
    backend = Path(__file__).resolve().parent.parent
    for cand in (backend / "static", backend.parent / "frontend" / "dist"):
        if cand.is_dir():
            return str(cand)
    return str(backend.parent / "frontend" / "dist")


def _paths():
    """(config, data, ssh_key, known_hosts, static) según el entorno de ejecución."""
    if running_in_docker():
        return "/config/config.yaml", "/data", "/keys/id_ed25519", "/keys/known_hosts", _static_default()
    h = native_home()
    return (str(h / "config" / "config.yaml"), str(h / "data"), str(h / "keys" / "id_ed25519"),
            str(h / "keys" / "known_hosts"), _static_default())


_CONFIG, _DATA, _KEY, _KNOWN, _STATIC = _paths()
CONFIG_PATH = Path(_CONFIG)
DATA_DIR = Path(_DATA)
SSH_KEY = _KEY
KNOWN_HOSTS = _KNOWN
STATIC_DIR = Path(_STATIC)


def _float_env(suffix, default):
    try:
        return float(env(suffix, default))
    except ValueError:
        raise SystemExit(f"CHECKPOINT_{suffix} debe ser un número (valor: {env(suffix)!r})")


SESSION_HOURS = _float_env("SESSION_HOURS", "12")
COOKIE_SECURE = env("COOKIE_SECURE", "0") == "1"
TRUST_PROXY = env("TRUST_PROXY", "0") == "1"
