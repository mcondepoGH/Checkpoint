"""Vinculación de dispositivos por solicitud y código. DOS superficies en el mismo prefijo `/api/pairing`:

- PÚBLICA, sin key ni sesión (`POST /requests`, `GET /requests/{id}`): es el ÚNICO endpoint de Checkpoint sin
  credencial previa. Mitigaciones en `services/pairing.py` (límites por IP y globales, caducidad, secretos largos) y
  aquí (fallos de secreto cuentan para el bloqueo por IP).
- CON SESIÓN (cookie + Origin en las escrituras, como `/api/devices/{id}/apikey`): listar, aceptar y rechazar.

El secreto de la solicitud viaja en la cabecera `X-Pairing-Secret` y NUNCA en la URL: las URL acaban en logs de
accesos, de proxies inversos, en el historial y en `Referer`; una cabecera no. Todas las respuestas llevan
`Cache-Control: no-store`. Documentación en `api/docs/pairing.py`."""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Header, Path, Request, Response
from starlette.concurrency import run_in_threadpool

from ...config.store import InvalidConfig
from ...core.errors import ApiError, error_response
from ...services.context import AppContext
from .. import docs
from ..deps import body_json, client_ip, get_ctx, require

api_log = logging.getLogger(
    "checkpoint.api"
)  # DEBUG: una línea por petición /api y detalle por endpoint (sin secretos)

NO_STORE = {"Cache-Control": "no-store"}
MAX_BODY = 2048  # el cuerpo de una solicitud pública son dos campos cortos


def _no_store(response: Response):
    response.headers.update(NO_STORE)


public = APIRouter(
    prefix="/api/pairing",
    tags=[docs.PAIRING_TAG],
    dependencies=[Depends(_no_store)],
    responses={429: docs.R429_PAIRING},
)
session = APIRouter(
    prefix="/api/pairing/pending",
    tags=[docs.PAIRING_SESSION_TAG],
    dependencies=[Depends(require), Depends(_no_store)],
    responses={401: docs.R401_SESSION, 403: docs.R403_ORIGIN},
)


async def _small_json(request: Request) -> dict:
    if len(await request.body()) > MAX_BODY:
        raise ApiError(413, "err.pairing.body_too_large", max=MAX_BODY)
    return await body_json(request)


def _blocked(ctx: AppContext, ip: str):
    wait = ctx.auth.pair_wait(ip)
    if wait > 0:
        api_log.debug("pairing: ip=%s bloqueada %ss (429)", ip, wait)
        raise ApiError(429, "err.main.too_many_attempts", headers={"Retry-After": str(wait)}, seconds=wait)


@public.post("/requests", status_code=201, **docs.PAIRING_CREATE)
async def create_request(request: Request, ctx: AppContext = Depends(get_ctx)):
    ip = client_ip(request)
    _blocked(ctx, ip)
    body = await _small_json(request)
    return ctx.pairing.create(body.get("name"), body.get("os"), ip)


@public.get("/requests/{request_id}", **docs.PAIRING_STATUS)
def request_status(
    request: Request,
    request_id: str = Path(max_length=64),
    secret: Optional[str] = Header(None, alias="X-Pairing-Secret", max_length=256, include_in_schema=False),
    ctx: AppContext = Depends(get_ctx),
):
    ip = client_ip(request)
    _blocked(ctx, ip)
    res = ctx.pairing.status(request_id, secret)
    if res is None:  # id desconocido, caducada, secreto ausente o erróneo: MISMA respuesta, y cuenta como fallo
        ctx.auth.pair_fail(ip)
        api_log.debug("pairing: consulta fallida ip=%s", ip)
        raise ApiError(404, "err.pairing.request_unknown")
    ctx.auth.pair_ok(ip)
    return res


@session.get("", **docs.PAIRING_LIST)
def list_pending(ctx: AppContext = Depends(get_ctx)):
    return ctx.pairing.pending()


@session.post("/{request_id}/accept", **docs.PAIRING_ACCEPT)
async def accept_request(request: Request, request_id: str = Path(max_length=64), ctx: AppContext = Depends(get_ctx)):
    body = await _small_json(request)
    try:
        return await run_in_threadpool(ctx.pairing.accept, request_id, body.get("code"))
    except InvalidConfig as e:  # mismo cuerpo que `PUT /api/config`
        return error_response(422, "err.main.config_invalid", extra={"errors": e.errors})


@session.post("/{request_id}/reject", **docs.PAIRING_REJECT)
def reject_request(request_id: str = Path(max_length=64), ctx: AppContext = Depends(get_ctx)):
    return ctx.pairing.reject(request_id)
