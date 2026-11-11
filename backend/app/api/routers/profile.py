"""Perfil del usuario de la sesión: nombre, foto y API key (se gestionan con la cookie de sesión)."""

import logging

from fastapi import Depends, Request, Response
from starlette.concurrency import run_in_threadpool

from ...core.errors import ApiError
from ...users import apikey, avatar
from ..deps import current_user, internal_router

api_log = logging.getLogger(
    "checkpoint.api"
)  # DEBUG: una línea por petición /api y detalle por endpoint (sin secretos)
router = internal_router()

PHOTO_HEADERS = {
    "Cache-Control": "private, no-cache",
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "default-src 'none'; sandbox",
}
NO_STORE = {"Cache-Control": "no-store"}


@router.get("/api/profile")
def profile(user: str = Depends(current_user)):
    """Nombre y versión de la foto, si hay, del usuario de la sesión."""
    v = avatar.version(user)
    return {"name": user, "photo": {"version": v} if v else None}


@router.get("/api/profile/photo")
def get_photo(request: Request, user: str = Depends(current_user)):
    got = avatar.load(user)
    if not got:
        api_log.debug("foto de perfil: usuario=%s sin foto (404)", user)
        raise ApiError(404, "err.main.photo_unknown")
    data, mime, ver = got
    headers = {**PHOTO_HEADERS, "ETag": f'"{ver}"'}
    if request.headers.get("if-none-match", "").strip() == f'"{ver}"':
        return Response(status_code=304, headers=headers)
    return Response(content=data, media_type=mime, headers=headers)  # tipo fijado por nosotros, no por el cliente


@router.put("/api/profile/photo")
async def put_photo(request: Request, user: str = Depends(current_user)):
    """Cuerpo = la imagen en bruto (JPEG, PNG o WebP, máx. 2 MB) con su Content-Type; se valida por los bytes."""
    declared = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if declared not in avatar.EXT:
        raise ApiError(415, "err.main.photo_type")
    try:
        if int(request.headers.get("content-length", "0")) > avatar.MAX_BYTES:
            raise ApiError(413, "err.main.photo_too_large", max_mb=avatar.MAX_BYTES // (1024 * 1024))
    except ValueError:
        raise ApiError(400, "err.main.photo_empty")
    buf = bytearray()
    async for chunk in request.stream():
        buf += chunk
        if len(buf) > avatar.MAX_BYTES:
            raise ApiError(413, "err.main.photo_too_large", max_mb=avatar.MAX_BYTES // (1024 * 1024))
    if not buf:
        raise ApiError(400, "err.main.photo_empty")
    if avatar.sniff(bytes(buf)) != declared:
        raise ApiError(415, "err.main.photo_type")
    ver = await run_in_threadpool(avatar.save, bytes(buf), declared, user)
    api_log.debug("foto de perfil guardada: usuario=%s tipo=%s %d bytes version=%s", user, declared, len(buf), ver)
    return {"ok": True, "photo": {"version": ver}}


@router.delete("/api/profile/photo")
def delete_photo(user: str = Depends(current_user)):
    avatar.delete(user)
    api_log.debug("foto de perfil borrada: usuario=%s", user)
    return {"ok": True, "photo": None}


# ---- API key de usuario (gestión desde el perfil, con sesión de cookie) ----
@router.get("/api/profile/apikey")
def get_apikey(response: Response, user: str = Depends(current_user)):
    """La key vigente en claro (se ve siempre en el perfil) o `exists: false`. Nunca se genera sola."""
    response.headers.update(NO_STORE)
    key = apikey.get(user)
    api_log.debug("API key: consulta usuario=%s existe=%s", user, key is not None)  # nunca la key
    return {"exists": key is not None, "key": key}


@router.post("/api/profile/apikey")
def post_apikey(response: Response, user: str = Depends(current_user)):
    """Genera la key o, si ya había, la regenera (la anterior deja de valer al instante)."""
    response.headers.update(NO_STORE)
    key = apikey.create(user)
    api_log.debug("API key: generada/regenerada usuario=%s", user)
    return {"exists": True, "key": key}


@router.delete("/api/profile/apikey")
def delete_apikey(response: Response, user: str = Depends(current_user)):
    response.headers.update(NO_STORE)
    apikey.revoke(user)
    api_log.debug("API key: revocada usuario=%s", user)
    return {"exists": False, "key": None}
