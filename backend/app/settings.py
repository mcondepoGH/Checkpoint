"""Ajustes desde variables de entorno."""
import os
from pathlib import Path


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


CONFIG_PATH = Path(_env("CONFIG", "/config/config.yaml"))
DATA_DIR = Path(_env("DATA", "/data"))
SSH_KEY = _env("SSH_KEY", "/keys/id_ed25519")
KNOWN_HOSTS = _env("KNOWN_HOSTS", "/keys/known_hosts")
STATIC_DIR = Path(_env("STATIC", "/app/static"))
SESSION_HOURS = float(_env("SESSION_HOURS", "12"))
COOKIE_SECURE = _env("COOKIE_SECURE", "0") == "1"
TRUST_PROXY = _env("TRUST_PROXY", "0") == "1"
SSH_TIMEOUT = int(_env("SSH_TIMEOUT", "8"))

# Sincronización automática: valores iniciales; lo guardado desde la UI prevalece.
AUTO_ENABLED = _env("AUTO_ENABLED", "0").strip().lower() in ("1", "true", "yes", "on")
AUTO_RUN_ON_START = _env("AUTO_RUN_ON_START", "0").strip().lower() in ("1", "true", "yes", "on")
try:
    AUTO_INTERVAL_HOURS = float(_env("AUTO_INTERVAL_HOURS", "24"))
except ValueError:
    AUTO_INTERVAL_HOURS = 24.0
