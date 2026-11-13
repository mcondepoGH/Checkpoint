"""API key de un dispositivo `http` (gestión desde la web, con la cookie de sesión; mismo estilo que
`/api/profile/apikey`). Esa key es la única que aceptan `fingerprint`, `manifest`, `files`, `commit` y `closed`.
La interfaz de estos endpoints está pendiente (tarjeta «UI de dispositivos http»)."""

import logging

from fastapi import Depends, Path, Response

from ...core.errors import ApiError
from ...services.context import AppContext
from ...users import apikey
from ..deps import current_user, get_ctx, internal_router

api_log = logging.getLogger(
    "checkpoint.api"
)  # DEBUG: una línea por petición /api y detalle por endpoint (sin secretos)
router = internal_router()

NO_STORE = {"Cache-Control": "no-store"}


def _http_device(ctx: AppContext, device: str) -> str:
    """El id (solo id, no nombre) de un dispositivo guardado con `http: true`; 404 si no existe, 400 si no es `http`."""
    d = ctx.cfg().devices.get(device)
    if d is None:
        raise ApiError(404, "err.hook.device_unknown")
    if not d.http:
        raise ApiError(400, "err.hook.device_not_http")
    return device


@router.get("/api/devices/{device}/apikey")
def get_device_apikey(
    response: Response,
    device: str = Path(),
    user: str = Depends(current_user),
    ctx: AppContext = Depends(get_ctx),
):
    """La key vigente del dispositivo en claro o `exists: false`. Nunca se genera sola."""
    response.headers.update(NO_STORE)
    dev = _http_device(ctx, device)
    key = apikey.device_get(user, dev)
    api_log.debug("API key de dispositivo: consulta usuario=%s dispositivo=%s existe=%s", user, dev, key is not None)
    return {"exists": key is not None, "key": key}


@router.post("/api/devices/{device}/apikey")
def post_device_apikey(
    response: Response,
    device: str = Path(),
    user: str = Depends(current_user),
    ctx: AppContext = Depends(get_ctx),
):
    """Genera la key o, si ya había, la regenera (la anterior deja de valer al instante)."""
    response.headers.update(NO_STORE)
    dev = _http_device(ctx, device)
    key = apikey.device_create(user, dev)
    api_log.debug("API key de dispositivo: generada/regenerada usuario=%s dispositivo=%s", user, dev)
    return {"exists": True, "key": key}


@router.delete("/api/devices/{device}/apikey")
def delete_device_apikey(
    response: Response,
    device: str = Path(),
    user: str = Depends(current_user),
    ctx: AppContext = Depends(get_ctx),
):
    """Revoca la key (idempotente)."""
    response.headers.update(NO_STORE)
    dev = _http_device(ctx, device)
    apikey.device_revoke(user, dev)
    api_log.debug("API key de dispositivo: revocada usuario=%s dispositivo=%s", user, dev)
    return {"exists": False, "key": None}
