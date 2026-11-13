"""API externa de juegos (API key, `GET /api/games`): lista de juegos y su último estado, para dispositivos sin SSH.
Se publica en el Swagger (tag `docs.GAMES_TAG`); documentación en `api/docs/examples.py`. No choca con
`/api/games/{game}/hook-status` (sesión, `routers/sync.py`): otra ruta."""

import logging

from fastapi import APIRouter, Depends

from ...services.context import AppContext
from ...services.status import read_statuses
from .. import docs
from ..deps import get_ctx, hook_user

api_log = logging.getLogger(
    "checkpoint.api"
)  # DEBUG: una línea por petición /api y detalle por endpoint (sin secretos)

router = APIRouter(tags=[docs.GAMES_TAG], dependencies=[Depends(hook_user)], responses={401: docs.R401, 429: docs.R429})

STATUS_FIELDS = ("result", "code", "started", "finished")  # lista cerrada: sin mensaje, params, log ni conflicto


@router.get(docs.GAMES_PATH, **docs.GAMES)
def list_games(ctx: AppContext = Depends(get_ctx)):
    """[{id, name, enabled, status: {result, code, started, finished} | null}] de los juegos de la config."""
    cfg = ctx.cfg()
    statuses = read_statuses(cfg.games)
    out = [
        {
            "id": gid,
            "name": g.name,
            "enabled": g.enabled,
            "status": {k: st[k] for k in STATUS_FIELDS if k in st} if (st := statuses.get(gid)) else None,
        }
        for gid, g in cfg.games.items()
    ]
    api_log.debug("games (key): %d juegos", len(out))
    return out
