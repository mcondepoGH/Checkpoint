"""Dependencias comunes de los routers: contexto de la app, sesión por cookie, Origin/CSRF, API key (Bearer) y cuerpo JSON."""

import logging

from fastapi import APIRouter, Depends, Request

from ..core import settings
from ..core.errors import ApiError
from ..services.context import AppContext
from ..users import apikey, avatar

api_log = logging.getLogger(
    "checkpoint.api"
)  # DEBUG: una línea por petición /api y detalle por endpoint (sin secretos)
COOKIE = "checkpoint_session"


def get_ctx(request: Request) -> AppContext:
    """Estado compartido de la app (`create_app` lo deja en `app.state.ctx`)."""
    return request.app.state.ctx


def client_ip(request: Request) -> str:
    if settings.TRUST_PROXY:
        xff = request.headers.get("x-forwarded-for")
        if xff:
            return xff.split(",")[-1].strip()
    return request.client.host if request.client else "?"


def require(request: Request):
    """Sesión web válida (cookie) y, en métodos que escriben, Origin igual al Host (CSRF)."""
    if not get_ctx(request).auth.valid(request.cookies.get(COOKIE)):
        api_log.debug("%s %s: sin sesión válida (401)", request.method, request.url.path)
        raise ApiError(401, "err.main.session_required")
    if request.method not in ("GET", "HEAD"):
        origin = request.headers.get("origin")
        host = request.headers.get("host")
        if origin and host and origin.split("://", 1)[-1] != host:
            api_log.debug(
                "%s %s: Origin %r no coincide con Host %r (403)", request.method, request.url.path, origin, host
            )
            raise ApiError(403, "err.main.origin_forbidden")


async def body_json(request: Request) -> dict:
    try:
        body = await request.json()
    except Exception:
        raise ApiError(400, "err.main.json_body_required") from None
    if not isinstance(body, dict):
        raise ApiError(400, "err.main.json_body_required")
    return body


def current_user(request: Request, _s=Depends(require)) -> str:
    """ÚNICO punto que dice quién es el usuario de la sesión. Hoy hay un solo usuario (CHECKPOINT_USER);
    con registro de usuarios se sustituye por la búsqueda del usuario ligado al token de sesión."""
    user = get_ctx(request).auth.user
    avatar.migrate_legacy(user)  # foto de antes de las carpetas por usuario, si queda alguna
    return user


def hook_user(request: Request) -> str:
    """Usuario dueño de la API key `Authorization: Bearer ck_...`. Es la contraparte de `current_user` para las
    rutas /api/hook/*: ignora la cookie de sesión y no comprueba Origin (lo llaman curl, lanzadores y plugins).
    Todo fallo (sin cabecera, mal formada, inválida, revocada, regenerada) es el mismo 401; los fallos cuentan
    por IP y, pasado el umbral, 429 (mismo mecanismo que el login, con contador propio). Con registro de
    usuarios, aquí se buscaría el dueño de la key en lugar de comparar con el único usuario."""
    auth = get_ctx(request).auth
    ip = client_ip(request)
    wait = auth.hook_wait(ip)
    if wait > 0:
        api_log.debug("hook auth: ip=%s bloqueada %ss (429)", ip, wait)
        raise ApiError(429, "err.main.too_many_attempts", headers={"Retry-After": str(wait)}, seconds=wait)
    parts = request.headers.get("authorization", "").split()
    token = parts[1] if len(parts) == 2 and parts[0].lower() == "bearer" else ""
    user = auth.user
    if apikey.is_well_formed(token) and apikey.verify(user, token):
        auth.hook_ok(ip)
        api_log.debug("hook auth: ip=%s correcta usuario=%s", ip, user)
        return user
    apikey.verify(user, token)  # mismo trabajo con entrada mal formada: sin diferencias de tiempo
    auth.hook_fail(ip)
    # Solo se registra el motivo grueso, nunca el token recibido.
    api_log.debug(
        "hook auth: ip=%s fallo (%s) (401)",
        ip,
        "sin Bearer o mal formada" if not apikey.is_well_formed(token) else "key no válida",
    )
    raise ApiError(401, "err.apikey.invalid", headers={"WWW-Authenticate": "Bearer"})


def public_router() -> APIRouter:
    """Router interno sin sesión (login, logout...): fuera del Swagger. Los routers nuevos salen ocultos por defecto."""
    return APIRouter(include_in_schema=False)


def internal_router() -> APIRouter:
    """Router interno de la web (con sesión): fuera del Swagger. Los routers nuevos salen ocultos por defecto.
    Solo el router `hook` se publica (ver `routers/hook.py`)."""
    return APIRouter(include_in_schema=False, dependencies=[Depends(require)])
