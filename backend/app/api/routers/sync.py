"""Sync manual, ejecuciones (log en directo), estado por juego y vigilancias de cierre para la UI."""
import json
import logging
import time

from fastapi import Depends, Request
from fastapi.responses import StreamingResponse

from ...core.errors import ApiError
from ...services.context import AppContext
from ...services.runs import start_manual_sync
from ...services.status import read_statuses
from ...sync.scheduler import iso, utcnow
from ..deps import get_ctx, internal_router

api_log = logging.getLogger("checkpoint.api")  # DEBUG: una línea por petición /api y detalle por endpoint (sin secretos)
router = internal_router()


@router.post("/api/sync/{game}")
async def start_sync(game: str, request: Request, ctx: AppContext = Depends(get_ctx)):
    cfg = ctx.cfg()
    game = ctx.game_id(game)
    try:
        body = await request.json()
    except Exception:
        body = {}
    run = start_manual_sync(ctx.runs, ctx.scheduler, cfg, game, body)
    return {"run_id": run.id}


@router.get("/api/watches")
def watches_view(ctx: AppContext = Depends(get_ctx)):
    """Vigilancias de cierre activas para la UI (sesión): {now, watches: [{game, device, state, since, last_poll, poll}]}.
    `now` es la hora del servidor (UTC) para que el cliente mida el latido sin depender de su reloj. Sin datos sensibles."""
    cfg = ctx.cfg()
    w = ctx.hooks.active_watches(cfg)
    api_log.debug("watches: %d vigilancias activas", len(w))
    return {"now": iso(utcnow()), "watches": w}


@router.get("/api/games/{game}/hook-status")
def hook_status(game: str, ctx: AppContext = Depends(get_ctx)):
    """Por dispositivo del juego: último evento de hook (`opened` = hook, cierre = hook_closed) y vigilancia activa.
    {devices: [{device, last: {trigger, at, outcome} | null, watching: {state, since} | null}]}. Solo lectura, sin datos sensibles."""
    cfg = ctx.cfg()
    game = ctx.game_id(game)
    return ctx.hooks.status(cfg, game)


@router.get("/api/runs/{run_id}/stream")
def stream(run_id: str, ctx: AppContext = Depends(get_ctx)):
    run = ctx.runs.get(run_id)
    if not run:
        api_log.debug("stream: run %s desconocido (404)", run_id)
        raise ApiError(404, "err.main.run_unknown")
    api_log.debug("stream: run=%s juego=%s líneas ya disponibles=%d hecho=%s", run_id, run.game, len(run.lines),
                  run.done)

    def gen():
        i = 0
        while True:
            while i < len(run.lines):
                yield f"data: {json.dumps(run.lines[i])}\n\n"
                i += 1
            if run.done and i >= len(run.lines):
                api_log.debug("stream: run=%s cerrado tras %d líneas", run_id, i)
                yield f"event: done\ndata: {json.dumps(run.status)}\n\n"
                return
            time.sleep(0.3)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/api/status")
def status(ctx: AppContext = Depends(get_ctx)):
    cfg = ctx.store.snapshot().cfg
    return read_statuses(cfg.games if cfg else {})
