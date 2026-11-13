"""Dependencias comunes de los routers: contexto de la app, sesión por cookie, Origin/CSRF, API key (Bearer) y cuerpo JSON."""

import logging
from typing import NamedTuple, Optional

from fastapi import APIRouter, Depends, Request

from ..config.models import describe
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


class Principal(NamedTuple):
    """Quién llama a /api/hook/*: el usuario dueño y, si la key es de dispositivo, el id de ese dispositivo."""

    user: str
    device: Optional[str] = None


def _hook_auth(request: Request, user_key: bool, device_key: bool) -> Principal:
    """Autentica `Authorization: Bearer ...` con la key de usuario (`ck_...`) y/o la de dispositivo (`ckd_...`) según
    lo que acepte el endpoint. Ignora la cookie de sesión y no comprueba Origin (lo llaman curl, lanzadores y
    plugins). Todo fallo (sin cabecera, mal formada, inválida, revocada, regenerada, de la clase que el endpoint no
    acepta, de un dispositivo borrado o que ya no es `http`) es el MISMO 401; los fallos cuentan por IP y, pasado el
    umbral, 429 (mismo mecanismo que el login, con contador propio). El prefijo dice qué comprobar; las dos
    comprobaciones hacen el mismo trabajo acierten o no. Con registro de usuarios, aquí se buscaría el dueño."""
    auth = get_ctx(request).auth
    ip = client_ip(request)
    wait = auth.hook_wait(ip)
    if wait > 0:
        api_log.debug("hook auth: ip=%s bloqueada %ss (429)", ip, wait)
        raise ApiError(429, "err.main.too_many_attempts", headers={"Retry-After": str(wait)}, seconds=wait)
    parts = request.headers.get("authorization", "").split()
    token = parts[1] if len(parts) == 2 and parts[0].lower() == "bearer" else ""
    user = auth.user
    principal = None
    if apikey.is_well_formed(token):
        if apikey.verify(user, token) and user_key:
            principal = Principal(user)
    elif apikey.is_well_formed_device(token):
        dev = _device_of(request, user, token)
        if dev is not None and device_key:
            principal = Principal(user, dev)
    else:
        apikey.verify(user, token)  # mismo trabajo con entrada mal formada: sin diferencias de tiempo
    if principal is not None:
        auth.hook_ok(ip)
        api_log.debug("hook auth: ip=%s correcta usuario=%s dispositivo=%s", ip, user, principal.device)
        return principal
    auth.hook_fail(ip)
    # Solo se registra el motivo grueso, nunca el token recibido.
    api_log.debug("hook auth: ip=%s fallo (401)", ip)
    raise ApiError(401, "err.apikey.invalid", headers={"WWW-Authenticate": "Bearer"})


def _device_of(request: Request, user: str, token: str) -> Optional[str]:
    """Id del dispositivo `http` actual de la config cuya key es `token` (un dispositivo borrado o que ya no es
    `http` no autentica, aunque su fichero siguiera en disco)."""
    try:
        cfg = get_ctx(request).cfg()
    except ApiError as e:
        # Config inválida: no se revela a quien no está autenticado; es el mismo 401 que una key inválida (y cuenta
        # como fallo). El error real queda en el log del hub (código y parámetros de la config, nunca la key).
        cause = e.detail.get("params", {}).get("cause") if isinstance(e.detail, dict) else None
        api_log.warning(
            "hook auth: config.yaml inválido, no se pueden listar los dispositivos http (%s)", describe(cause)
        )
        return None
    return apikey.device_match(user, [i for i, d in cfg.devices.items() if d.http], token)


def hook_user(request: Request) -> Principal:
    """Key de USUARIO (`ck_...`): ping, watches, opened. Devuelve `Principal(usuario, None)`. Una key de dispositivo
    es un 401 aquí (misma respuesta que una inválida)."""
    return _hook_auth(request, user_key=True, device_key=False)


def hook_device(request: Request) -> Principal:
    """Key de DISPOSITIVO http (`ckd_...`): fingerprint, manifest, files, commit, closed. Devuelve
    `Principal(usuario, id del dispositivo)`. Una key de usuario es un 401 aquí."""
    return _hook_auth(request, user_key=False, device_key=True)


def hook_any(request: Request) -> Principal:
    """Cualquiera de las dos keys: ping y `GET /api/games` (este último filtra por `principal.device`)."""
    return _hook_auth(request, user_key=True, device_key=True)


def public_router() -> APIRouter:
    """Router interno sin sesión (login, logout...): fuera del Swagger. Los routers nuevos salen ocultos por defecto."""
    return APIRouter(include_in_schema=False)


def internal_router() -> APIRouter:
    """Router interno de la web (con sesión): fuera del Swagger. Los routers nuevos salen ocultos por defecto.
    Solo el router `hook` se publica (ver `routers/hook.py`)."""
    return APIRouter(include_in_schema=False, dependencies=[Depends(require)])
