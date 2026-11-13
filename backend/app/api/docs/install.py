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
from .pairing import COOKIE_NAME, SECURITY_PAIRING, SECURITY_SESSION

TAG = "Avisos del lanzador (API key)"
SECURITY = "bearerAuth"  # key de USUARIO (`ck_...`)
SECURITY_DEVICE = "deviceKeyAuth"  # key de DISPOSITIVO http (`ckd_...`)
# Qué key acepta cada ruta publicada (debe coincidir con la dependencia de `routers/hook.py` y `routers/games.py`):
# "user" = solo `ck_`, "device" = solo `ckd_`, "any" = las dos. `patch_schema` falla con una ruta sin clasificar.
KEY_KINDS = {
    "/api/hook/ping": "any",
    "/api/hook/watches": "user",
    "/api/hook/{game}/opened": "user",
    "/api/hook/{game}/closed": "device",
    "/api/hook/{game}/fingerprint": "device",
    "/api/hook/{game}/manifest": "device",
    "/api/hook/{game}/files": "device",
    "/api/hook/{game}/commit": "device",
    "/api/games": "any",
    # Vinculación de dispositivos (`routers/pairing.py`): "public" = sin credencial (único caso), "pairing_secret" =
    # secreto de la solicitud en `X-Pairing-Secret`, "session" = cookie de sesión web.
    "/api/pairing/requests": "public",
    "/api/pairing/requests/{request_id}": "pairing_secret",
    "/api/pairing/pending": "session",
    "/api/pairing/pending/{request_id}/accept": "session",
    "/api/pairing/pending/{request_id}/reject": "session",
}
KEY_NOTES = {
    "user": "**Key aceptada:** solo la de **usuario** (`ck_...`, Mi perfil → API key). La de dispositivo (`ckd_...`) da `401`.",
    "device": "**Key aceptada:** solo la de **dispositivo** `http` (`ckd_...`), que identifica al dispositivo y solo "
    "ve sus juegos (`?device=` opcional: otro dispositivo, `403`; juego que no lo incluye, `404`). La de usuario "
    "(`ck_...`) da `401`.",
    "any": "**Key aceptada:** la de usuario (`ck_...`) o la de dispositivo (`ckd_...`).",
    "public": "**Sin credencial:** es el único endpoint de Checkpoint sin key ni sesión previas. Límites por IP, tope "
    "de solicitudes pendientes y caducidad de 10 min (ver «Vinculación de dispositivos» arriba).",
    "pairing_secret": "**Credencial:** el secreto de la solicitud, en la cabecera `X-Pairing-Secret` (nunca en la URL). "
    "No vale una key ni la sesión, y el código de 6 dígitos tampoco.",
    "session": "**Credencial:** la sesión web (cookie `checkpoint_session`; las escrituras comprueban `Origin`). Una API "
    "key no vale aquí.",
}
API_PREFIX = "/api/hook/"
PAIRING_PREFIX = "/api/pairing/"
GAMES_TAG = "Juegos (API key)"
GAMES_PATH = "/api/games"  # ruta pública exacta; `/api/games/{game}/...` sigue siendo interna (sesión)
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
    "**Autenticación.** Todas las rutas piden `Authorization: Bearer <key>`. Hay **dos clases de key**, que no se "
    "intercambian (la clase equivocada es el mismo `401` que una inválida):\n\n"
    "- **Key de usuario** (`ck_...`): la de **Mi perfil → API key**. Vale en `GET /api/hook/ping`, "
    "`GET /api/hook/watches`, `POST /api/hook/{game}/opened` y `GET /api/games` (todos los juegos).\n"
    "- **Key de dispositivo** `http` (`ckd_...`): una por dispositivo con `http: true`, que se genera en la web "
    "(`/api/devices/{id}/apikey`, con sesión). Vale en `fingerprint`, `manifest`, `files`, `commit` y `closed`, y "
    "también en `ping` y `GET /api/games` (este último solo con los juegos de ese dispositivo). Identifica al "
    "dispositivo: `?device=` es opcional y, si se pasa y no es el suyo, `403`. Un juego que no incluye el "
    "dispositivo da el mismo `404` que uno inexistente.\n\n"
    "La cookie de sesión de la web **no** vale aquí. En «Authorize» pega solo la key (Swagger añade `Bearer`). Trata "
    "las keys como contraseñas: dan acceso a los saves; regenera la que se filtre.\n\n"
    '**Errores.** Todos tienen la forma `{"detail": {"code": "err.<módulo>.<causa>", "params": {...}}}`. '
    "Los códigos `err.*` no se traducen: son el contrato estable.\n\n"
    "**Vinculación de dispositivos (`/api/pairing/*`).** Un dispositivo (el plugin de la Steam Deck) se vincula sin "
    "key previa: pide acceso con su nombre y sistema operativo (`POST /api/pairing/requests`), recibe un código de 6 "
    "dígitos que enseña al usuario y un secreto que solo conoce él; el usuario, **con sesión web**, acepta en el hub "
    "solo si el código coincide (`/api/pairing/pending*`); el dispositivo consulta su solicitud con el secreto "
    "(cabecera `X-Pairing-Secret`) y recibe **una sola vez** su key `ckd_...`. **Es el único endpoint sin credencial "
    "previa.** Mitigaciones: límite de solicitudes y de pendientes por IP, tope de 10 pendientes en el hub, caducidad "
    "de 10 min (solo en memoria), código y secreto aleatorios criptográficos (secreto de 32 bytes, comparación en "
    "tiempo constante), el código no recoge la key, `404` uniforme con secreto erróneo (cuenta para el bloqueo por "
    "IP) y nada de secretos en logs.\n\n"
    "**Solo se documenta la API de la API key y la vinculación.** El resto de rutas `/api/*` son internas de la web "
    "y pueden cambiar sin aviso."
)
TAG_DESCRIPTION = (
    "Rutas `/api/hook/*`: se autentican solo con una API key (Bearer; de usuario o de dispositivo según la ruta, ver "
    "cada operación), sin cookie ni comprobación de Origin."
)
GAMES_TAG_DESCRIPTION = (
    "Ruta `GET /api/games`: lista de juegos y su estado, con la API key de usuario (todos los juegos) o de "
    "dispositivo (solo los suyos)."
)


def iter_api_routes(routes):
    """Todas las APIRoute, incluidas las de routers incluidos (FastAPI reciente los guarda anidados en `original_router`)."""
    for r in routes:
        if isinstance(r, APIRoute):
            yield r
        elif hasattr(r, "original_router"):
            yield from iter_api_routes(r.original_router.routes)


def patch_schema(schema: dict) -> None:
    """Esquema de seguridad único, sin los 422 genéricos de FastAPI (los documentados a mano se conservan) y con la seguridad en cada operación."""
    comps = schema.setdefault("components", {})
    schemes = comps.setdefault("securitySchemes", {})
    schemes[SECURITY] = {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "ck_<43 caracteres base64 urlsafe>",
        "description": "API key de **usuario** (`ck_...`) de **Mi perfil → API key**. Pégala sin el prefijo `Bearer`. "
        "Solo vale en las rutas que la aceptan (ver cada operación). La cookie de sesión no vale en estas rutas.",
    }
    schemes[SECURITY_DEVICE] = {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "ckd_<43 caracteres base64 urlsafe>",
        "description": "API key de **dispositivo** `http` (`ckd_...`), una por dispositivo (`/api/devices/{id}/apikey`, "
        "con sesión). Pégala sin el prefijo `Bearer`. Identifica al dispositivo y solo ve sus juegos. Solo vale en las "
        "rutas que la aceptan (ver cada operación).",
    }
    schemes[SECURITY_PAIRING] = {
        "type": "apiKey",
        "in": "header",
        "name": "X-Pairing-Secret",
        "description": "Secreto de la solicitud de vinculación (`secret` de `POST /api/pairing/requests`). Solo vale en "
        "la consulta de esa solicitud; va en cabecera y nunca en la URL.",
    }
    schemes[SECURITY_SESSION] = {
        "type": "apiKey",
        "in": "cookie",
        "name": COOKIE_NAME,
        "description": "Sesión web (cookie del login). Swagger UI la envía sola si estás en la web con sesión.",
    }
    security = {
        "public": [],
        "pairing_secret": [{SECURITY_PAIRING: []}],
        "session": [{SECURITY_SESSION: []}],
        "user": [{SECURITY: []}],
        "device": [{SECURITY_DEVICE: []}],
        "any": [{SECURITY: []}, {SECURITY_DEVICE: []}],  # una u otra
    }
    for path, item in schema.get("paths", {}).items():
        kind = KEY_KINDS[path]  # KeyError = ruta pública nueva sin clasificar: añádela a KEY_KINDS
        for op in item.values():
            if isinstance(op, dict):
                op["security"] = security[kind]
                op["description"] = (op.get("description", "") + "\n\n" + KEY_NOTES[kind]).strip()
                r = op.get("responses", {})
                if r.get("422", {}).get("description") == "Validation Error":  # el de FastAPI; los propios se quedan
                    r.pop("422")
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
