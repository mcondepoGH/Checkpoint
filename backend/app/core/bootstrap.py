"""Arranque automático: config vacío, clave SSH y known_hosts (TOFU).

Todo con listas de argumentos (sin shell local). Nunca se expone la clave privada.
"""

import logging
import os
import re
import subprocess
import threading
from pathlib import Path
from typing import Optional

from . import settings
from .errors import describe_code, error_body
from .hosts import HOST_RE

log = logging.getLogger("checkpoint")
_lock = threading.Lock()

EMPTY_CONFIG = "devices: {}\ngames: {}\n"
# Aviso de «primer uso» (host key guardada): solo para el log; la UI usa el código `err.bootstrap.first_use`.
FIRST_USE_LOG = "host key guardada (primer uso)"
HOST_KEY_CHANGED = "err.bootstrap.host_key_changed"


class BootstrapError(RuntimeError):
    """Contrato i18n: `code` (`err.bootstrap.<causa>`) + `params`; `str(e)` es técnico (logs)."""

    def __init__(self, code: str, **params):
        super().__init__(describe_code(code, params))
        self.code, self.params = code, params

    def body(self) -> dict:
        return error_body(self.code, **self.params)


# ---- config ----
def ensure_config(path: Path = None) -> bool:
    """Crea un config.yaml vacío y válido si falta. True si lo creó."""
    path = Path(path or settings.CONFIG_PATH)
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(EMPTY_CONFIG)
    log.warning("config.yaml no existía: creado vacío en %s", path)
    return True


# ---- clave SSH ----
def _pub_path(key: str) -> Path:
    return Path(str(key) + ".pub")


def ensure_ssh_key(key: str = None) -> bool:
    """Genera ed25519 sin passphrase (600) si falta. Idempotente. True si la generó."""
    key = Path(key or settings.SSH_KEY)
    with _lock:
        if key.exists():
            return False
        key.parent.mkdir(parents=True, exist_ok=True)
        _pub_path(key).unlink(missing_ok=True)  # .pub huérfana: ssh-keygen preguntaría si sobrescribir
        try:
            p = subprocess.run(
                ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "checkpoint", "-f", str(key)],
                capture_output=True,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            raise BootstrapError("err.bootstrap.keygen_failed", detail=str(e))
        if p.returncode != 0:
            raise BootstrapError(
                "err.bootstrap.keygen_error", detail=p.stderr.decode("utf-8", "replace").strip()[-200:]
            )
        os.chmod(key, 0o600)
        log.warning("clave SSH generada en %s (primer arranque)", key)
        return True


def public_key(key: str = None) -> Optional[str]:
    """Clave pública (una línea) o None. Si falta la .pub, se deriva con `ssh-keygen -y`."""
    key = Path(key or settings.SSH_KEY)
    pub = _pub_path(key)
    if pub.is_file():
        txt = pub.read_text(encoding="utf-8", errors="replace").strip()
        if txt.startswith("ssh-"):
            return txt
    if not key.is_file():
        return None
    try:
        p = subprocess.run(["ssh-keygen", "-y", "-f", str(key)], capture_output=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return None
    out = p.stdout.decode("utf-8", "replace").strip()
    return out if p.returncode == 0 and out.startswith("ssh-") else None


def startup() -> None:
    """Se llama al arrancar la app. Un fallo de escritura se registra, no tumba el servicio."""
    warning = settings.resolve_lang()[1]
    if warning:
        log.warning("arranque: %s", warning)
    for fn in (ensure_config, ensure_ssh_key):
        try:
            fn()
        except (OSError, BootstrapError) as e:
            log.error("arranque: %s: %s", fn.__name__, e)


# ---- known_hosts (TOFU) ----
def _check_target(host: str, port) -> int:
    if not isinstance(host, str) or not HOST_RE.match(host) or host.startswith("-"):
        raise BootstrapError("err.bootstrap.host_invalid")
    try:
        port = int(port)
    except (TypeError, ValueError):
        raise BootstrapError("err.bootstrap.port_invalid")
    if not 1 <= port <= 65535:
        raise BootstrapError("err.bootstrap.port_range")
    return port


def _kh_name(host: str, port: int) -> str:
    return host if port == 22 else f"[{host}]:{port}"


def has_host_entry(host: str, port: int, known_hosts: str = None) -> bool:
    kh = str(known_hosts or settings.KNOWN_HOSTS)
    if not Path(kh).is_file():
        return False
    try:
        p = subprocess.run(["ssh-keygen", "-F", _kh_name(host, port), "-f", kh], capture_output=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise BootstrapError("err.bootstrap.known_hosts_read", detail=str(e))
    return p.returncode == 0


def _keyscan(host: str, port: int) -> str:
    try:
        p = subprocess.run(
            ["ssh-keyscan", "-T", str(settings.SSH_TIMEOUT), "-p", str(port), "-t", "ed25519,ecdsa,rsa", host],
            capture_output=True,
            timeout=settings.SSH_TIMEOUT * 3 + 5,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        raise BootstrapError("err.bootstrap.keyscan_failed", detail=str(e))
    lines = [l for l in p.stdout.decode("utf-8", "replace").splitlines() if l.strip() and not l.startswith("#")]
    if not lines:
        raise BootstrapError("err.bootstrap.hostkey_unavailable", host=host, port=port)
    return "\n".join(lines) + "\n"


def ensure_host_key(host: str, port, known_hosts: str = None) -> bool:
    """TOFU: si el host no tiene entrada, la obtiene con ssh-keyscan y la guarda.

    Devuelve True si guardó una entrada nueva. Si ya hay entrada NO se vuelve a escanear
    ni se toca: si la clave cambió, `ssh` (StrictHostKeyChecking=yes) fallará.
    """
    port = _check_target(host, port)
    kh = Path(known_hosts or settings.KNOWN_HOSTS)
    with _lock:
        if has_host_entry(host, port, kh):
            return False
        entries = _keyscan(host, port)
        kh.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(kh, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as f:
            f.write(entries)
    log.warning("%s: %s:%s", FIRST_USE_LOG, host, port)
    return True


_CHANGED_RE = re.compile(r"HOST IDENTIFICATION HAS CHANGED|Host key verification failed", re.I)


def host_key_changed(stderr: str) -> bool:
    """True si el fallo de ssh es por cambio de host key (la UI lo explica con `err.bootstrap.host_key_changed`)."""
    return bool(_CHANGED_RE.search(stderr))
