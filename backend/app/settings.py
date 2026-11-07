"""Ajustes desde variables de entorno."""
import os
from pathlib import Path

from .runtime import platform_name, running_in_docker


def env(suffix, default=None, environ=None):
    """Lee CHECKPOINT_<suffix>; si no existe, cae a SAVESYNC_<suffix> (nombre antiguo, deprecado)."""
    environ = os.environ if environ is None else environ
    for prefix in ("CHECKPOINT_", "SAVESYNC_"):
        v = environ.get(prefix + suffix)
        if v not in (None, ""):
            return v
    return default


def _env(suffix, default):
    return env(suffix, default)


def native_home(environ=None) -> Path:
    """Carpeta base de Checkpoint en modo nativo (sin Docker). CHECKPOINT_HOME_DIR la fija a mano; por defecto
    ~/.local/share/checkpoint (Linux, respeta XDG_DATA_HOME), ~/Library/Application Support/checkpoint (macOS)
    o %APPDATA%\\checkpoint (Windows). En Docker los valores por defecto son /config, /data y /keys."""
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
    """(config, data, ssh_key, known_hosts, static) por defecto según el entorno de ejecución."""
    if running_in_docker():
        return "/config/config.yaml", "/data", "/keys/id_ed25519", "/keys/known_hosts", _static_default()
    h = native_home()
    return (str(h / "config" / "config.yaml"), str(h / "data"), str(h / "keys" / "id_ed25519"),
            str(h / "keys" / "known_hosts"), _static_default())


_D_CONFIG, _D_DATA, _D_KEY, _D_KNOWN, _D_STATIC = _paths()
CONFIG_PATH = Path(_env("CONFIG", _D_CONFIG))
DATA_DIR = Path(_env("DATA", _D_DATA))
SSH_KEY = _env("SSH_KEY", _D_KEY)
KNOWN_HOSTS = _env("KNOWN_HOSTS", _D_KNOWN)
STATIC_DIR = Path(_env("STATIC", _D_STATIC))
SESSION_HOURS = float(_env("SESSION_HOURS", "12"))
COOKIE_SECURE = _env("COOKIE_SECURE", "0") == "1"
TRUST_PROXY = _env("TRUST_PROXY", "0") == "1"
SSH_TIMEOUT = int(_env("SSH_TIMEOUT", "8"))

# Sincronización automática: valores iniciales; lo guardado desde la UI prevalece.
AUTO_ENABLED = _env("AUTO_ENABLED", "0").strip().lower() in ("1", "true", "yes", "on")
AUTO_RUN_ON_START = _env("AUTO_RUN_ON_START", "0").strip().lower() in ("1", "true", "yes", "on")
AUTO_ON_CONFLICT = _env("AUTO_ON_CONFLICT", "skip").strip().lower()
if AUTO_ON_CONFLICT not in ("skip", "newest"):
    AUTO_ON_CONFLICT = "skip"
try:
    AUTO_INTERVAL_HOURS = float(_env("AUTO_INTERVAL_HOURS", "24"))
except ValueError:
    AUTO_INTERVAL_HOURS = 24.0

# Comprobación de nuevas versiones (solo lectura, GitHub Releases). UPDATE_CHECK y UPDATE_CHANNEL
# («stable» o «beta»; otro valor -> stable) son los valores iniciales; lo guardado desde la UI prevalece.
UPDATE_CHECK = _env("UPDATE_CHECK", "1").strip().lower() not in ("0", "false", "no", "off")


def update_check_forced(environ=None) -> bool:
    """True si CHECKPOINT_UPDATE_CHECK está definido EXPLÍCITAMENTE con valor verdadero (1/true/yes/on).
    «No definido» (o vacío) no cuenta: es lo que distingue el valor por defecto de un forzado. En Docker la
    comprobación de versiones solo se aplica si esto es True; en instalación nativa siempre se aplica."""
    v = env("UPDATE_CHECK", None, environ)
    return v is not None and v.strip().lower() in ("1", "true", "yes", "on")


UPDATE_CHANNEL = "beta" if _env("UPDATE_CHANNEL", "stable").strip().lower() == "beta" else "stable"
UPDATE_REPO = _env("UPDATE_REPO", "mcondepoGH/Checkpoint").strip()
try:
    UPDATE_CACHE_HOURS = max(0.25, float(_env("UPDATE_CACHE_HOURS", "6")))
except ValueError:
    UPDATE_CACHE_HOURS = 6.0
