"""Documentación OpenAPI de la API externa (la de la API key, `/api/hook/*`). SOLO documenta; no valida nada.

Alcance: únicamente las rutas del tag `TAG`. Todo lo demás de `/api/*` (login, perfil, config, sync...) es interno de
la web, queda fuera del esquema (`include_in_schema=False`, ver `install`) y no aparece en la documentación.
Acceso: `/api/openapi.json` y `/api/docs` exigen sesión web (misma dependencia que las rutas internas); la API key sola
no los abre. Los textos están en español; los códigos `err.*` van sin traducir (son el contrato)."""
from typing import Callable

from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field

TAG = "Avisos del lanzador (API key)"
SECURITY = "bearerAuth"
API_PREFIX = "/api/hook/"

TITLE = "API de Checkpoint (avisos del lanzador)"
DESCRIPTION = (
    "API externa de Checkpoint para que un lanzador (Steam, Lutris, un script...) avise al hub y consulte sus "
    "vigilancias de cierre.\n\n"
    "**Autenticación.** Todas las rutas piden `Authorization: Bearer ck_...` con tu API key. Se genera en la web, en "
    "**Mi perfil → API key**. La cookie de sesión de la web **no** vale aquí. En «Authorize» pega solo la key "
    "(Swagger añade `Bearer`).\n\n"
    "**Errores.** Todos tienen la forma `{\"detail\": {\"code\": \"err.<módulo>.<causa>\", \"params\": {...}}}`. "
    "Los códigos `err.*` no se traducen: son el contrato estable.\n\n"
    "**Solo se documenta la API de la API key.** El resto de rutas `/api/*` son internas de la web y pueden cambiar "
    "sin aviso."
)
TAG_DESCRIPTION = "Rutas `/api/hook/*`: se autentican solo con la API key (Bearer), sin cookie ni comprobación de Origin."


class ErrorDetail(BaseModel):
    code: str = Field(description="Código estable `err.<módulo>.<causa>` (no traducido).", examples=["err.apikey.invalid"])
    params: dict = Field(default_factory=dict, description="Parámetros del código (según el caso; puede estar vacío).")


class ErrorBody(BaseModel):
    """Solo para el esquema de documentación: las respuestas reales las construye `apierror`."""
    detail: ErrorDetail


def _err(code: str, params: dict = None) -> dict:
    return {"detail": {"code": code, "params": params or {}}}


def error_response(description: str, *examples: tuple, headers: dict = None) -> dict:
    """Respuesta de error documentada: `examples` = (clave, resumen, código, params)."""
    ex = {k: {"summary": s, "value": _err(c, p)} for k, s, c, p in examples}
    out = {"model": ErrorBody, "description": description, "content": {"application/json": {"examples": ex}}}
    if headers:
        out["headers"] = headers
    return out


R401 = error_response(
    "API key ausente, mal formada, inválida, revocada o regenerada (todo es el mismo 401), o se usó la cookie de "
    "sesión. Se comprueba antes que nada: no revela si el juego existe. Cada fallo cuenta para el límite por IP.",
    ("invalid", "Sin key, key inválida o revocada", "err.apikey.invalid", None),
    headers={"WWW-Authenticate": {"description": "Siempre `Bearer`.", "schema": {"type": "string", "example": "Bearer"}}})

R429 = error_response(
    "Demasiados fallos de key seguidos desde esta IP. Tras 3 fallos bloquea 5 s y cada fallo posterior duplica la "
    "espera (10, 20, 40 s...) hasta 900 s (15 min). Mientras dura, responde 429 incluso con una key válida. Es en "
    "memoria y por IP: un acierto reinicia el contador.",
    ("blocked", "IP bloqueada temporalmente", "err.main.too_many_attempts", {"seconds": 5}),
    headers={"Retry-After": {"description": "Segundos hasta poder reintentar (5 a 900).",
                             "schema": {"type": "integer", "example": 5}}})

R400 = error_response(
    "Falta `device` (y el juego está en más de un dispositivo) o la referencia es ambigua.",
    ("required", "Falta `?device=`", "err.hook.device_required", {"devices": "PC uno (dev-1), Laptop (dev-2)"}),
    ("ambiguous", "El nombre coincide con varios dispositivos", "err.hook.device_ambiguous",
     {"cause": {"code": "err.config.ref_ambiguous", "params": {"ref": "PC", "matches": "'PC uno' (dev-1), 'pc' (dev-2)"}}}))

R404 = error_response(
    "El juego o el dispositivo no existen (o el dispositivo no pertenece al juego).",
    ("game", "Juego desconocido", "err.main.game_unknown", {}),
    ("device", "Dispositivo desconocido", "err.hook.device_unknown", {}))

R409 = error_response(
    "Ya hay una ejecución de ese juego en curso (cron, manual u otro aviso), o la referencia al juego es ambigua. No se "
    "arma vigilancia.",
    ("busy", "Ejecución en curso", "err.main.run_in_progress", {}),
    ("ambiguous", "El nombre coincide con varios juegos", "err.main.game_ambiguous",
     {"cause": {"code": "err.config.ref_ambiguous", "params": {"ref": "Juego", "matches": "'Juego' (g1), 'juego' (g2)"}}}))


def patch_schema(schema: dict) -> None:
    """Esquema de seguridad único, sin los 422 de validación (la API no los devuelve) y con la seguridad en cada operación."""
    comps = schema.setdefault("components", {})
    comps.setdefault("securitySchemes", {})[SECURITY] = {
        "type": "http", "scheme": "bearer", "bearerFormat": "ck_<43 caracteres base64 urlsafe>",
        "description": "API key de usuario (`ck_...`) de **Mi perfil → API key**. Pégala sin el prefijo `Bearer`. "
                       "La cookie de sesión no vale en estas rutas."}
    for item in schema.get("paths", {}).values():
        for op in item.values():
            if isinstance(op, dict):
                op.setdefault("security", [{SECURITY: []}])
                op.get("responses", {}).pop("422", None)
    for name in ("HTTPValidationError", "ValidationError"):
        comps.get("schemas", {}).pop(name, None)


def install(app: FastAPI, require: Callable) -> None:
    """Llamar DESPUÉS de registrar todas las rutas de la API y ANTES del catch-all SPA.
    1. Oculta del esquema toda ruta que no sea del tag público (por defecto, una ruta nueva queda oculta).
    2. Sirve `/api/openapi.json` solo con sesión."""
    for r in app.routes:
        if isinstance(r, APIRoute) and TAG not in (r.tags or []):
            r.include_in_schema = False

    def openapi() -> dict:
        if app.openapi_schema is None:
            patch_schema(FastAPI.openapi(app))
        return app.openapi_schema

    app.openapi = openapi

    @app.get("/api/openapi.json", include_in_schema=False, dependencies=[Depends(require)])
    def openapi_json():
        return JSONResponse(app.openapi())
