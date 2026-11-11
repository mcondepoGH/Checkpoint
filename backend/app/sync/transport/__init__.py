"""Transportes de acceso a dispositivos (SSH POSIX, SSH Windows, «Este equipo»)."""

from ...core.runtime import running_in_docker
from ...config.models import Device
from .base import Transport, TransportError
from .local import LocalDeviceTransport, local_folder_status, local_path
from .posix import PosixTransport
from .windows import WindowsTransport

__all__ = [
    "Transport",
    "TransportError",
    "PosixTransport",
    "WindowsTransport",
    "LocalDeviceTransport",
    "get_transport",
    "local_folder_status",
    "local_path",
]


def get_transport(dev: Device) -> Transport:
    if dev.local:
        if running_in_docker():
            raise TransportError("err.config.local_docker")
        return LocalDeviceTransport(dev)
    return WindowsTransport(dev) if dev.os == "windows" else PosixTransport(dev)
