"""Contrato de error HTTP: `detail = {"code": "err.<modulo>.<causa>", "params": {...}}`.
El backend NO traduce: la UI traduce `code` con `params`. Las respuestas con datos extra
(`errors`, `retry_after`, `current_version`...) los llevan al nivel superior, junto a `detail`.
`errors` por campo = {ruta: {code, params}}.

Causas anidadas (la excepción de origen sube tal cual, sin texto): un param puede ser un cuerpo
{code, params} (`params.cause`, uno) o una lista [{path, code, params}] (`params.causes`, varios; `path`
opcional). La UI traduce el anidado primero y lo inserta en `{cause}`/`{causes}` del mensaje padre."""
from fastapi import HTTPException
from fastapi.responses import JSONResponse


def error_body(code: str, **params) -> dict:
    return {"code": code, "params": params}


def describe_code(code: str, params: dict) -> str:
    """Texto técnico (no traducido) de code+params: para logs, CLI y campos internos de respaldo."""
    return code + "".join(f" {k}={v!r}" for k, v in params.items())


class ApiError(HTTPException):
    def __init__(self, status_code: int, code: str, headers=None, **params):
        super().__init__(status_code, error_body(code, **params), headers=headers)


def error_response(status_code: int, code: str, *, headers=None, extra=None, **params) -> JSONResponse:
    return JSONResponse({"detail": error_body(code, **params), **(extra or {})},
                        status_code=status_code, headers=headers)
