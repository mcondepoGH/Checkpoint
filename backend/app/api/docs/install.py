"""Documentación OpenAPI de la API externa (la de la API key, `/api/hook/*`). SOLO documenta; no valida nada.

Alcance: únicamente las rutas del tag `TAG`. Todo lo demás de `/api/*` (login, perfil, config, sync...) es interno de
la web, queda fuera del esquema (`include_in_schema=False` por router, ver `api/deps.py`) y no aparece en la documentación.
Acceso: `/api/openapi.json` y `/api/docs` exigen sesión web (misma dependencia que las rutas internas); la API key sola
no los abre. Los textos están en español; los códigos `err.*` van sin traducir (son el contrato)."""

from typing import Callable

from fastapi import Depends, FastAPI
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import FileResponse, JSONResponse
from fastapi.routing import APIRoute

from ...core import settings
from ...core.errors import ApiError

TAG = "Avisos del lanzador (API key)"
SECURITY = "bearerAuth"
API_PREFIX = "/api/hook/"
DOCS_URL = "/api/docs"
OPENAPI_URL = "/api/openapi.json"
ASSETS_URL = "/api/docs-assets"
ASSETS_DIR = (
    "docs-assets"  # dentro de STATIC_DIR; lo deja allí el build del frontend (vite.config.js, swagger-ui-dist fijado)
)
# Lista cerrada de ficheros servibles (sin rutas arbitrarias del disco).
ASSETS = {
    "swagger-ui-bundle.js": "swagger-ui-bundle.js",
    "swagger-ui.css": "swagger-ui.css",
    "favicon-32x32.png": "favicon-32x32.png",
}

TITLE = "API de Checkpoint (avisos del lanzador)"
DESCRIPTION = (
    "API externa de Checkpoint para que un lanzador (Steam, Lutris, un script...) avise al hub y consulte sus "
    "vigilancias de cierre.\n\n"
    "**Autenticación.** Todas las rutas piden `Authorization: Bearer ck_...` con tu API key. Se genera en la web, en "
    "**Mi perfil → API key**. La cookie de sesión de la web **no** vale aquí. En «Authorize» pega solo la key "
    "(Swagger añade `Bearer`).\n\n"
    '**Errores.** Todos tienen la forma `{"detail": {"code": "err.<módulo>.<causa>", "params": {...}}}`. '
    "Los códigos `err.*` no se traducen: son el contrato estable.\n\n"
    "**Solo se documenta la API de la API key.** El resto de rutas `/api/*` son internas de la web y pueden cambiar "
    "sin aviso."
)
TAG_DESCRIPTION = (
    "Rutas `/api/hook/*`: se autentican solo con la API key (Bearer), sin cookie ni comprobación de Origin."
)


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
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "ck_<43 caracteres base64 urlsafe>",
        "description": "API key de usuario (`ck_...`) de **Mi perfil → API key**. Pégala sin el prefijo `Bearer`. "
        "La cookie de sesión no vale en estas rutas.",
    }
    for item in schema.get("paths", {}).values():
        for op in item.values():
            if isinstance(op, dict):
                op.setdefault("security", [{SECURITY: []}])
                op.get("responses", {}).pop("422", None)
    for name in ("HTTPValidationError", "ValidationError"):
        comps.get("schemas", {}).pop(name, None)


def install(app: FastAPI, require: Callable) -> None:
    """Llamar DESPUÉS de registrar todas las rutas de la API y ANTES del catch-all SPA.
    Sirve `/api/openapi.json`, `/api/docs` y los assets de Swagger UI (empaquetada: sin CDN, sin internet) solo con
    sesión. Sin sesión, el 401 de `require`, como el resto de rutas protegidas.
    NO oculta nada: cada router interno nace con `include_in_schema=False` (`deps.internal_router`/`public_router`) y
    solo el router `hook` se publica, así que una ruta o router nuevo sale oculto por defecto."""

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
            openapi_url=OPENAPI_URL,
            title=TITLE,
            swagger_js_url=f"{ASSETS_URL}/swagger-ui-bundle.js",
            swagger_css_url=f"{ASSETS_URL}/swagger-ui.css",
            swagger_favicon_url=f"{ASSETS_URL}/favicon-32x32.png",
            swagger_ui_parameters={
                "supportedSubmitMethods": ["get", "post"],
                "docExpansion": "list",
                "defaultModelsExpandDepth": -1,
            },
        )

    @app.get(ASSETS_URL + "/{name}", include_in_schema=False, dependencies=[Depends(require)])
    def docs_asset(name: str):
        f = ASSETS.get(name)
        path = settings.STATIC_DIR / ASSETS_DIR / f if f else None
        if path is None or not path.is_file():
            raise ApiError(404, "err.main.not_found")
        return FileResponse(path, headers={"Cache-Control": "no-cache"})
