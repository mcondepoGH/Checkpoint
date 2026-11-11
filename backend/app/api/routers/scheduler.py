"""Sync automática: estado y ajustes del scheduler, e historial de ejecuciones."""

import logging

from fastapi import Depends, Query, Request

from ...core.errors import error_response
from ...services.context import AppContext
from ...users import history
from ..deps import body_json, get_ctx, internal_router

api_log = logging.getLogger(
    "checkpoint.api"
)  # DEBUG: una línea por petición /api y detalle por endpoint (sin secretos)
router = internal_router()


@router.get("/api/scheduler")
def get_scheduler(ctx: AppContext = Depends(get_ctx)):
    st = ctx.scheduler.state()
    api_log.debug(
        "scheduler estado: %s", {k: v for k, v in st.items() if isinstance(v, (bool, int, float, str, type(None)))}
    )
    return st


@router.put("/api/scheduler")
async def put_scheduler(request: Request, ctx: AppContext = Depends(get_ctx)):
    body = await body_json(request)
    try:
        res = ctx.scheduler.update(body)
        api_log.debug("scheduler actualizado: campos=%s", sorted(body))
        return res
    except ValueError as e:
        api_log.debug(
            "scheduler actualizar: inválido en %s", sorted(e.args[0]) if isinstance(e.args[0], dict) else e.args[0]
        )
        return error_response(422, "err.main.settings_invalid", extra={"errors": e.args[0]})


@router.get("/api/scheduler/history")
def get_scheduler_history(limit: int = Query(50, ge=1, le=50), ctx: AppContext = Depends(get_ctx)):
    snap = ctx.store.snapshot()
    games = snap.cfg.games if snap.cfg else {}
    entries = history.annotate(history.read(limit), games)
    api_log.debug("scheduler history: limit=%d devueltas=%d", limit, len(entries))
    return {"entries": entries}
