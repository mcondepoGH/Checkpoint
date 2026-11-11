"""Sesión web: login, logout, estado de la sesión y ajustes públicos de la pantalla de login (sin sesión)."""
import logging

from fastapi import Depends, Request, Response
from fastapi.responses import JSONResponse

from ...core import settings
from ...core.errors import error_response
from ...services.context import AppContext
from ..deps import COOKIE, body_json, client_ip, get_ctx, public_router

api_log = logging.getLogger("checkpoint.api")  # DEBUG: una línea por petición /api y detalle por endpoint (sin secretos)
router = public_router()


@router.post("/api/login")
async def login(request: Request, response: Response, ctx: AppContext = Depends(get_ctx)):
    auth = ctx.auth
    body = await body_json(request)
    ip = client_ip(request)
    try:
        tok = auth.login(ip, str(body.get("user", "")), str(body.get("password", "")))
    except PermissionError as e:
        api_log.debug("login: ip=%s bloqueada %ss por intentos fallidos", ip, e.args[0])
        return error_response(429, "err.main.too_many_attempts", headers={"Retry-After": str(e.args[0])},
                              extra={"retry_after": e.args[0]}, seconds=e.args[0])
    if not tok:
        api_log.debug("login: ip=%s usuario=%r credenciales incorrectas", ip, str(body.get("user", "")))
        return error_response(401, "err.main.bad_credentials")
    api_log.debug("login: ip=%s usuario=%r correcto", ip, str(body.get("user", "")))
    r = JSONResponse({"ok": True})
    r.set_cookie(COOKIE, tok, max_age=int(auth.ttl), httponly=True, samesite="strict",
                 secure=settings.COOKIE_SECURE, path="/")
    return r


@router.post("/api/logout")
async def logout(request: Request, ctx: AppContext = Depends(get_ctx)):
    api_log.debug("logout: ip=%s", client_ip(request))
    ctx.auth.logout(request.cookies.get(COOKIE))
    r = JSONResponse({"ok": True})
    r.delete_cookie(COOKIE, path="/")
    return r


@router.get("/api/session")
async def session(request: Request, ctx: AppContext = Depends(get_ctx)):
    return {"authenticated": ctx.auth.valid(request.cookies.get(COOKIE))}


@router.get("/api/public")
async def public():
    """Ajustes que necesita la pantalla de login (sin sesión): hoy solo el idioma por defecto."""
    return {"default_lang": settings.default_lang()}
