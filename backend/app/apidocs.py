"""Documentación OpenAPI de la API externa (la de la API key, `/api/hook/*`). SOLO documenta; no valida nada.

Alcance: únicamente las rutas del tag `TAG`. Todo lo demás de `/api/*` (login, perfil, config, sync...) es interno de
la web, queda fuera del esquema (`include_in_schema=False`, ver `install`) y no aparece en la documentación.
Acceso: `/api/openapi.json` y `/api/docs` exigen sesión web (misma dependencia que las rutas internas); la API key sola
no los abre. Los textos están en español; los códigos `err.*` van sin traducir (son el contrato)."""
from typing import Callable, Optional

from fastapi import Depends, FastAPI
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import FileResponse, JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field

from .core import settings
from .apierror import ApiError

TAG = "Avisos del lanzador (API key)"
SECURITY = "bearerAuth"
API_PREFIX = "/api/hook/"
DOCS_URL = "/api/docs"
OPENAPI_URL = "/api/openapi.json"
ASSETS_URL = "/api/docs-assets"
ASSETS_DIR = "docs-assets"  # dentro de STATIC_DIR; lo deja allí el build del frontend (vite.config.js, swagger-ui-dist fijado)
# Lista cerrada de ficheros servibles (sin rutas arbitrarias del disco).
ASSETS = {"swagger-ui-bundle.js": "swagger-ui-bundle.js", "swagger-ui.css": "swagger-ui.css",
          "favicon-32x32.png": "favicon-32x32.png"}

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


class Ping(BaseModel):
    ok: bool = Field(description="Siempre `true` si la key es válida.")
    user: str = Field(description="Usuario dueño de la API key.")


class WatchItem(BaseModel):
    game: str = Field(description="Id interno del juego.")
    device: str = Field(description="Id interno del dispositivo donde se vigila el proceso.")
    state: str = Field(description="`waiting`: aún no se vio el proceso; `running`: visto abierto; `settling`: cerrado, "
                                   "esperando unos segundos antes del checkpoint.", examples=["running"])
    since: str = Field(description="Inicio del estado actual (UTC, ISO 8601).")
    last_poll: str = Field(description="Último sondeo completado (latido, UTC ISO 8601).")
    poll: float = Field(description="Intervalo de sondeo, en segundos (15 por defecto).")


class OpenedResult(BaseModel):
    ok: bool = Field(description="`true` solo si `outcome` es `ok`.")
    outcome: str = Field(description="`ok`, `conflict`, `aborted` (dispositivo sin conexión, proceso del juego "
                                     "abierto...), `skipped` (juego de un dispositivo con la partida local ausente), `partial`, `error` o `timeout`.", examples=["ok"])
    game: str = Field(description="Id interno del juego.")
    device: str = Field(description="Id interno del dispositivo.")
    run_id: Optional[str] = Field(None, description="Id de la ejecución (la misma que verás en el historial). "
                                                    "Falta si el juego está desactivado (no hubo ejecución).")
    code: Optional[str] = Field(None, description="Qué pasó, como código `err.sync.*` (o `err.hook.timeout`). "
                                                  "Sin traducir. Puede faltar.")
    params: Optional[dict] = Field(None, description="Parámetros de `code`.")
    watching: bool = Field(description="`true` si se armó la vigilancia de cierre (el juego tiene `process`).")
    watch_reason: Optional[str] = Field(None, description="Si `watching` es `false`: `no_process` (el juego no tiene "
                                                          "`process` configurado) o `disabled` (el juego está desactivado).")


def _ok(model, description: str, *examples: tuple) -> dict:
    """Respuesta 200 solo para el esquema (no valida ni filtra la respuesta real). examples = (clave, resumen, valor)."""
    ex = {k: {"summary": s, "value": v} for k, s, v in examples}
    return {"model": model, "description": description, "content": {"application/json": {"examples": ex}}}


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


def iter_api_routes(routes):
    """Todas las APIRoute, incluidas las de routers incluidos (FastAPI reciente los guarda anidados en `original_router`)."""
    for r in routes:
        if isinstance(r, APIRoute):
            yield r
        elif hasattr(r, "original_router"):
            yield from iter_api_routes(r.original_router.routes)


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
    2. Sirve `/api/openapi.json`, `/api/docs` y los assets de Swagger UI (empaquetada: sin CDN, sin internet) solo con
    sesión. Sin sesión, el 401 de `require`, como el resto de rutas protegidas."""
    for r in iter_api_routes(app.routes):
        if TAG not in (r.tags or []):
            r.include_in_schema = False

    def openapi() -> dict:
        if app.openapi_schema is None:
            patch_schema(FastAPI.openapi(app))
        return app.openapi_schema

    app.openapi = openapi

    @app.get(OPENAPI_URL, include_in_schema=False, dependencies=[Depends(require)])
    def openapi_json():
        return JSONResponse(app.openapi())

    @app.get(DOCS_URL, include_in_schema=False, dependencies=[Depends(require)])
    def docs():
        # La página lleva un script de inicio en línea (lo genera FastAPI): no añadas una CSP que lo bloquee.
        return get_swagger_ui_html(
            openapi_url=OPENAPI_URL, title=TITLE, swagger_js_url=f"{ASSETS_URL}/swagger-ui-bundle.js",
            swagger_css_url=f"{ASSETS_URL}/swagger-ui.css", swagger_favicon_url=f"{ASSETS_URL}/favicon-32x32.png",
            swagger_ui_parameters={"supportedSubmitMethods": ["get", "post"],
                                   "docExpansion": "list", "defaultModelsExpandDepth": -1})

    @app.get(ASSETS_URL + "/{name}", include_in_schema=False, dependencies=[Depends(require)])
    def docs_asset(name: str):
        f = ASSETS.get(name)
        path = settings.STATIC_DIR / ASSETS_DIR / f if f else None
        if path is None or not path.is_file():
            raise ApiError(404, "err.main.not_found")
        return FileResponse(path, headers={"Cache-Control": "no-cache"})


# ---- documentación de cada operación (se pasa tal cual al decorador: solo summary/description/responses) ----
PING = dict(
    summary="Comprobar la API key",
    description="Devuelve `200` si la API key es válida. Úsalo para probar la key y la conexión con el hub: no cambia "
                "nada ni toca ningún juego.",
    responses={200: _ok(Ping, "La key es válida.", ("ok", "Key válida", {"ok": True, "user": "admin"}))})

WATCHES = dict(
    summary="Listar las vigilancias de cierre activas",
    description="Vigilancias activas ahora mismo: tras un aviso `opened`, el hub vigila el proceso del juego en ese "
                "dispositivo y, al cerrarse, hace el checkpoint solo. Son en memoria (se pierden si el hub se "
                "reinicia). Lista vacía si no hay ninguna. Solo lectura, sin datos sensibles.",
    responses={200: _ok(list[WatchItem], "Lista de vigilancias (puede estar vacía).",
                        ("running", "Un juego en marcha", [{"game": "g1", "device": "dev-1", "state": "running",
                                                          "since": "2026-01-15T18:30:12Z",
                                                          "last_poll": "2026-01-15T18:45:12Z", "poll": 15.0}]),
                        ("empty", "Sin vigilancias", []))})

_OPENED_OK = {"ok": True, "outcome": "ok", "game": "g1", "device": "dev-1", "run_id": "3f9c1a7b2d4e",
              "code": "err.sync.done", "params": {}, "watching": True}
OPENED = dict(
    summary="Avisar de que se va a abrir un juego",
    description=(
        "> **Atención: Try it out ejecuta de verdad.** Esta operación hace una **sincronización previa real** del "
        "juego (puede copiar ficheros de save al dispositivo) y **arma el vigilante de cierre** del juego. No es una "
        "simulación: úsala solo con un juego y dispositivo reales y ten en cuenta que, al cerrarse el juego, el hub "
        "hará un checkpoint.\n\n"
        "Se llama justo antes de arrancar el juego. El hub sincroniza ese juego **antes de que arranque**: si tiene un "
        "save más nuevo, lo copia al dispositivo; si no, termina sin copiar. Usa **siempre** la política de conflictos "
        "`skip`: ante un conflicto no toca nada, lo indica en la respuesta y lo deja en el historial (disparador "
        "«Aviso del juego»).\n\n"
        "**Bloqueante.** La petición espera a que acabe la sincronización, hasta 55 s. Si se supera, responde `200` "
        "con `outcome: timeout` y la sincronización sigue en segundo plano. Usa en el cliente un tiempo máximo mayor "
        "(p. ej. `curl -m 60`).\n\n"
        "**Un fallo de la sincronización no es un 5xx.** Responde `200` con `ok: false`, `outcome` (`conflict`, "
        "`aborted`, `partial`, `error`, `timeout`) y `code`/`params` con el detalle. No se reintenta; el cron de la "
        "sincronización automática sigue como red de seguridad. Solo `ok: true` es éxito.\n\n"
        "**Vigilancia de cierre.** Con cualquier `200` (también `conflict`, `aborted` o `timeout`) se arma la "
        "vigilancia si el juego tiene `process` (`watching: true`); si no, `watching: false` con "
        "`watch_reason: no_process`. Nunca se arma con `400`, `401`, `404` ni `409`. La respuesta no incluye la "
        "duración: la sincronización dura hasta 55 s.\n\n"
        "**Juego desactivado** (`enabled: false` en la configuración). No se sincroniza ni se arma la vigilancia: "
        "responde `200` con `ok: false`, `outcome: skipped`, `code: err.sync.game_disabled`, `watching: false` y "
        "`watch_reason: disabled`, y lo deja en el historial (disparador «Aviso del juego», omitido). Antes se "
        "resuelven juego y dispositivo (los `400`/`404` no cambian).\n\n"
        "**Juego y dispositivo.** `game` es el id o el nombre del juego. `device` (id o nombre) debe pertenecer al "
        "juego; es obligatorio si el juego está en más de un dispositivo; si tiene uno solo se deduce y puede omitirse."),
    responses={
        200: _ok(OpenedResult, "La sincronización terminó (con éxito o no) o superó el tiempo máximo. Mira `outcome`.",
                 ("ok", "Éxito: se copió el save más nuevo", _OPENED_OK),
                 ("already_synced", "Éxito: no había nada que copiar",
                  {**_OPENED_OK, "code": "err.sync.already_synced"}),
                 ("conflict", "Conflicto: no se tocó nada",
                  {**_OPENED_OK, "ok": False, "outcome": "conflict", "code": "err.sync.conflict"}),
                 ("aborted", "Abortado (p. ej. dispositivo sin conexión)",
                  {**_OPENED_OK, "ok": False, "outcome": "aborted", "code": "err.sync.all_offline"}),
                 ("no_process", "Éxito, pero el juego no tiene `process`: sin vigilancia",
                  {**_OPENED_OK, "watching": False, "watch_reason": "no_process"}),
                 ("disabled", "Juego desactivado: no se sincroniza ni se vigila",
                  {"ok": False, "outcome": "skipped", "game": "g1", "device": "dev-1",
                   "code": "err.sync.game_disabled", "params": {}, "watching": False, "watch_reason": "disabled"}),
                 ("timeout", "Superó los 55 s: sigue en segundo plano",
                  {"ok": False, "outcome": "timeout", "game": "g1", "device": "dev-1", "run_id": "3f9c1a7b2d4e",
                   "code": "err.hook.timeout", "params": {"seconds": 55}, "watching": True})),
        400: R400, 404: R404, 409: R409})
