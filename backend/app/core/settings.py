"""Ajustes desde variables de entorno (CHECKPOINT_*): USER, PASSWORD, PORT, HOST, HOME_DIR, SESSION_HOURS,
COOKIE_SECURE, TRUST_PROXY, RUNTIME, LANG, LOG_LEVEL y HOOK_POLL/HOOK_SETTLE/HOOK_FIRST_SEEN (vigilante de cierre). El resto de rutas y valores se derivan de ellas o son constantes."""

import os
from pathlib import Path

from .runtime import platform_name, running_in_docker

SSH_TIMEOUT = 8  # s de conexión SSH
HOOK_WAIT = 55  # s máx. que `POST /api/hook/{game}/opened` espera a la sync (el cliente suele usar curl -m 60)


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
    backend = Path(__file__).resolve().parents[2]
    for cand in (backend / "static", backend.parent / "frontend" / "dist"):
        if cand.is_dir():
            return str(cand)
    return str(backend.parent / "frontend" / "dist")


def _paths():
    """(config, data, ssh_key, known_hosts, static) según el entorno de ejecución."""
    if running_in_docker():
        return "/config/config.yaml", "/data", "/keys/id_ed25519", "/keys/known_hosts", _static_default()
    h = native_home()
    return (
        str(h / "config" / "config.yaml"),
        str(h / "data"),
        str(h / "keys" / "id_ed25519"),
        str(h / "keys" / "known_hosts"),
        _static_default(),
    )


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
        raise SystemExit(f"CHECKPOINT_{suffix} debe ser un número (valor: {env(suffix)!r})") from None


SESSION_HOURS = _float_env("SESSION_HOURS", "12")
COOKIE_SECURE = env("COOKIE_SECURE", "0") == "1"
TRUST_PROXY = env("TRUST_PROXY", "0") == "1"


# Idioma por defecto de la interfaz (CHECKPOINT_LANG, opcional). El backend no traduce nada: solo lo informa al
# frontend, que lo usa si el usuario no ha elegido idioma en su navegador. Sin valor o no soportado = español.
SUPPORTED_LANGS = ("es", "en")
DEFAULT_LANG = "es"


def resolve_lang(environ=None):
    """(idioma, aviso). Acepta 'en', 'EN', 'en-US', 'en_GB'. Valor no soportado: español y un aviso para el log."""
    raw = env("LANG", None, environ)
    if raw is None or not raw.strip():
        return DEFAULT_LANG, None
    short = raw.strip().lower().replace("_", "-").split("-")[0]
    if short in SUPPORTED_LANGS:
        return short, None
    return DEFAULT_LANG, (
        f"CHECKPOINT_LANG={raw!r} no es un idioma soportado ({', '.join(SUPPORTED_LANGS)}); se usa '{DEFAULT_LANG}'"
    )


def default_lang(environ=None) -> str:
    return resolve_lang(environ)[0]


LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")


def resolve_log_level(environ=None):
    """(nivel, aviso): aviso es None salvo que CHECKPOINT_LOG_LEVEL tenga un valor no válido (entonces INFO)."""
    raw = str(env("LOG_LEVEL", "INFO", environ)).strip()
    v = raw.upper()
    if v in LOG_LEVELS:
        return v, None
    return "INFO", f"CHECKPOINT_LOG_LEVEL={raw!r} no es válido ({', '.join(LOG_LEVELS)}); se usa 'INFO'"


def log_level(environ=None) -> str:
    """Nivel de log de la app (CHECKPOINT_LOG_LEVEL: DEBUG, INFO, WARNING o ERROR). Vacío o no válido = INFO."""
    return resolve_log_level(environ)[0]


def _secs(suffix, default, environ=None):
    """Segundos desde CHECKPOINT_<suffix>; vacío, no numérico o <= 0 = valor por defecto."""
    try:
        v = float(env(suffix, default, environ))
    except (TypeError, ValueError):
        return float(default)
    return v if v > 0 and v == v and v != float("inf") else float(default)


# Vigilante de cierre (tras `opened`): cada cuánto se sondea el proceso del juego, cuánto se espera tras dejar de
# verlo (para que se liberen los ficheros) y cuánto se espera a verlo abierto la primera vez antes de descartar.
HOOK_POLL = _secs("HOOK_POLL", 15)
HOOK_SETTLE = _secs("HOOK_SETTLE", 10)
HOOK_FIRST_SEEN = _secs("HOOK_FIRST_SEEN", 120)
