"""API externa (la de la API key, `/api/hook/*`): única parte que sale en el Swagger. Autenticación Bearer, sin cookie
ni Origin. Para añadir un endpoint público nuevo, cuélgalo de este router y documéntalo en `api/docs/examples.py`;
cualquier otro router sale oculto por defecto (`deps.internal_router`)."""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Path, Query

from ...services.context import AppContext
from .. import docs
from ..deps import get_ctx, hook_user

api_log = logging.getLogger(
    "checkpoint.api"
)  # DEBUG: una línea por petición /api y detalle por endpoint (sin secretos)

# Todo lo de /api/hook/* cuelga de este router y de su dependencia.
router = APIRouter(
    prefix="/api/hook", tags=[docs.TAG], dependencies=[Depends(hook_user)], responses={401: docs.R401, 429: docs.R429}
)


@router.get("/ping", **docs.PING)
def hook_ping(user: str = Depends(hook_user)):
    api_log.debug("hook ping: usuario=%s", user)
    return {"ok": True, "user": user}


@router.get("/watches", **docs.WATCHES)
def hook_watches(ctx: AppContext = Depends(get_ctx)):
    """Vigilancias de cierre activas (en memoria): [{game, device, state: waiting|running|settling, since}]. Sin los juegos desactivados."""
    cfg = ctx.cfg()
    w = ctx.hooks.active_watches(cfg)
    api_log.debug("hook watches: %d vigilancias activas", len(w))
    return w


@router.post("/{game}/opened", **docs.OPENED)
async def hook_opened(
    game: str = Path(description="Id o nombre del juego.", examples=["Mi Juego"]),
    device: Optional[str] = Query(
        None,
        description="Id o nombre del dispositivo donde se "
        "vigila el proceso del juego. Obligatorio si el juego está en "
        "más de un dispositivo.",
        examples=["PC uno"],
    ),
    ctx: AppContext = Depends(get_ctx),
):
    """Aviso «se va a abrir el juego»: sync previo bloqueante con política de conflictos siempre `skip` (ignora la del juego y la del scheduler).
    Tras el aviso (salvo 400/401/404/409) arma la vigilancia de cierre si el juego tiene `process` (`watching`). Un fallo de la sync no es un 5xx: 200 con `outcome` descriptivo."""
    cfg = ctx.cfg()
    game = ctx.game_id(game)  # el 401 ya lo dio hook_user: no se revela si el juego existe
    return await ctx.hooks.opened(cfg, game, device)
