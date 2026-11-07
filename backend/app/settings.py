"""Ajustes desde variables de entorno."""
import os
from pathlib import Path


def _env(name, default):
    return os.environ.get(name, default)


CONFIG_PATH = Path(_env("SAVESYNC_CONFIG", "/config/config.yaml"))
DATA_DIR = Path(_env("SAVESYNC_DATA", "/data"))
SSH_KEY = _env("SAVESYNC_SSH_KEY", "/keys/id_ed25519")
KNOWN_HOSTS = _env("SAVESYNC_KNOWN_HOSTS", "/keys/known_hosts")
STATIC_DIR = Path(_env("SAVESYNC_STATIC", "/app/static"))
SESSION_HOURS = float(_env("SAVESYNC_SESSION_HOURS", "12"))
COOKIE_SECURE = _env("SAVESYNC_COOKIE_SECURE", "0") == "1"
TRUST_PROXY = _env("SAVESYNC_TRUST_PROXY", "0") == "1"
SSH_TIMEOUT = int(_env("SAVESYNC_SSH_TIMEOUT", "8"))

# Sincronización automática: valores iniciales; lo guardado desde la UI prevalece.
AUTO_ENABLED = _env("SAVESYNC_AUTO_ENABLED", "0").strip().lower() in ("1", "true", "yes", "on")
AUTO_RUN_ON_START = _env("SAVESYNC_AUTO_RUN_ON_START", "0").strip().lower() in ("1", "true", "yes", "on")
try:
    AUTO_INTERVAL_HOURS = float(_env("SAVESYNC_AUTO_INTERVAL_HOURS", "24"))
except ValueError:
    AUTO_INTERVAL_HOURS = 24.0
