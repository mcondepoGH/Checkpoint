"""Versiones (copias) de los saves de un juego."""
from fastapi import Depends, Request

from ...services import versions as versions_svc
from ...services.context import AppContext
from ..deps import body_json, get_ctx, internal_router

router = internal_router()


@router.get("/api/versions/{game}")
def versions(game: str, ctx: AppContext = Depends(get_ctx)):
    cfg = ctx.cfg()
    game = ctx.game_id(game)
    return versions_svc.versions_of(cfg, game)


@router.get("/api/versions/{game}/limit")
def versions_limit(game: str, ctx: AppContext = Depends(get_ctx)):
    cfg = ctx.cfg()
    game = ctx.game_id(game)
    return versions_svc.limit_of(cfg, game)


@router.post("/api/versions/{game}/restore")
async def restore(game: str, request: Request, ctx: AppContext = Depends(get_ctx)):
    body = await body_json(request)
    cfg = ctx.cfg()
    return versions_svc.restore(cfg, game, body)
