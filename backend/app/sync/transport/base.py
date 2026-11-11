"""Acceso a dispositivos por SSH. Siempre listas de argumentos (sin shell local).

En el extremo remoto, ssh entrega una cadena al shell del servidor: las rutas
ya vienen validadas por config.normalize_path (lista blanca) y además se
entrecomillan (shlex.quote en POSIX, comillas dobles en cmd.exe).

Aquí: errores, interfaz `Transport` y utilidades compartidas por los transportes.
"""
import logging
import subprocess
import time
from pathlib import Path
from typing import Iterable, List

from ...core import bootstrap, settings
from ...core.errors import describe_code, error_body
from ...config.models import PATH_CHARS_RE, Device

log = logging.getLogger("checkpoint.transport")  # DEBUG: duración de cada comando ssh/rsync (nunca args, claves ni contenidos)


class TransportError(RuntimeError):
    """Contrato i18n: `code` (`err.transport.<causa>` o `err.bootstrap.<causa>`) + `params`. El stderr de
    ssh/rsync/tar no se traduce: va en el param `detail`. `str(e)` es técnico (logs)."""

    def __init__(self, code: str, **params):
        super().__init__(describe_code(code, params))
        self.code, self.params = code, params

    def body(self) -> dict:
        return error_body(self.code, **self.params)


class Transport:
    """Interfaz. Rutas ya normalizadas."""

    def check(self) -> None: ...
    def exists(self, path: str) -> bool: ...
    def pull(self, path: str, dest: Path) -> None: ...
    def push(self, src: Path, path: str, extras: Iterable[str] = ()) -> None: ...
    def process_running(self, name: str) -> bool: ...


def _ssh_base(dev: Device) -> List[str]:
    return [
        "ssh", "-p", str(dev.port), "-i", settings.SSH_KEY,
        "-o", "BatchMode=yes",
        "-o", "IdentitiesOnly=yes",
        "-o", "StrictHostKeyChecking=yes",
        "-o", f"UserKnownHostsFile={settings.KNOWN_HOSTS}",
        "-o", f"ConnectTimeout={settings.SSH_TIMEOUT}",
        "-o", "ServerAliveInterval=15",
        f"{dev.user}@{dev.host}",
    ]


def _run(args: List[str], timeout=600, stdin=None) -> subprocess.CompletedProcess:
    t0 = time.monotonic()
    try:
        p = subprocess.run(args, capture_output=True, timeout=timeout, stdin=stdin)
        log.debug("%s: rc=%s en %.0f ms", args[0], p.returncode, (time.monotonic() - t0) * 1000)
        return p
    except subprocess.TimeoutExpired:
        log.debug("%s: timeout tras %.0f ms (límite %ss)", args[0], (time.monotonic() - t0) * 1000, timeout)
        raise TransportError("err.transport.timeout")
    except FileNotFoundError as e:
        raise TransportError("err.transport.missing_binary", binary=e.filename)


def _err(p: subprocess.CompletedProcess) -> str:
    return (p.stderr or b"").decode("utf-8", "replace").strip()[-300:]


def _fail(code: str, p: subprocess.CompletedProcess, dev: Device = None) -> TransportError:
    """Error de un comando ssh/rsync: stderr como `detail`; si es un cambio de host key, su propio código."""
    txt = _err(p)
    if dev and bootstrap.host_key_changed(txt):
        return TransportError(bootstrap.HOST_KEY_CHANGED, host=dev.host, port=dev.port)
    return TransportError(code, detail=txt)


def _ensure_host_key(dev: Device) -> bool:
    """TOFU antes de conectar; el fallo se reporta como TransportError. True si guardó una huella nueva."""
    try:
        return bootstrap.ensure_host_key(dev.host, dev.port)
    except bootstrap.BootstrapError as e:
        raise TransportError(e.code, **e.params)


def _safe_rel(rel: str) -> bool:
    return bool(PATH_CHARS_RE.match(rel)) and ".." not in rel.split("/") and not rel.startswith("/")
