"""Swagger/OpenAPI de la API externa (la de la API key). `install` monta los endpoints de la documentación;
`models` y `examples` solo describen el contrato (ver el docstring de `install`)."""

from .examples import OPENED, PING, R400, R401, R404, R409, R429, WATCHES, error_response
from .install import (
    API_PREFIX,
    ASSETS,
    ASSETS_DIR,
    ASSETS_URL,
    DESCRIPTION,
    DOCS_URL,
    OPENAPI_URL,
    SECURITY,
    TAG,
    TAG_DESCRIPTION,
    TITLE,
    install,
    iter_api_routes,
    patch_schema,
)

__all__ = [
    "OPENED",
    "PING",
    "R400",
    "R401",
    "R404",
    "R409",
    "R429",
    "WATCHES",
    "error_response",
    "API_PREFIX",
    "ASSETS",
    "ASSETS_DIR",
    "ASSETS_URL",
    "DESCRIPTION",
    "DOCS_URL",
    "OPENAPI_URL",
    "SECURITY",
    "TAG",
    "TAG_DESCRIPTION",
    "TITLE",
    "install",
    "iter_api_routes",
    "patch_schema",
]
