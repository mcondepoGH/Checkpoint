"""API FastAPI. Motivo de FastAPI: pydantic ya valida la config y SSE/streaming vienen incluidos.

Solo monta la app: estado compartido (`services.context.AppContext`), middleware, routers por tema (`api/routers`),
documentación (`api/docs`) y SPA. Puntos de entrada estables: `app.main:app_factory` y `app.cli`."""
import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool

from .api import docs
from .api.auth import Auth
from .api.deps import require
from .api.middleware import RequestDebugLog
from .api.routers import config, hook, profile, session, spa, sync, versions
from .api.routers import scheduler as scheduler_router
from .api.routers import updates as updates_router
from .core import bootstrap, updates
from .services.context import AppContext
from .users import avatar

api_log = logging.getLogger("checkpoint.api")  # DEBUG: una línea por petición /api y detalle por endpoint (sin secretos)


def create_app(auth: Optional[Auth] = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app):
        await run_in_threadpool(avatar.migrate_legacy, ctx.auth.user)
        task = asyncio.create_task(ctx.scheduler.loop())
        try:
            yield
        finally:
            task.cancel()
            await ctx.watcher.cancel_all()

    # La documentación (/api/docs, /api/openapi.json) la monta `docs.install` con la dependencia de sesión.
    app = FastAPI(title=docs.TITLE, version=updates.installed_version(), description=docs.DESCRIPTION,
                  openapi_tags=[{"name": docs.TAG, "description": docs.TAG_DESCRIPTION}],
                  docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.add_middleware(RequestDebugLog, logger=api_log)
    if auth is None:
        auth = Auth.from_env()
    ctx = AppContext(auth)
    app.state.ctx = ctx
    app.state.watcher = ctx.watcher
    for router in (session.router, profile.router, config.router, scheduler_router.router, updates_router.router,
                   sync.router, versions.router, hook.router):
        app.include_router(router)
    # Documentación OpenAPI (solo la API de la API key; con sesión). Antes del catch-all SPA.
    docs.install(app, require)
    app.include_router(spa.router)  # catch-all: siempre el último
    return app


def app_factory():
    bootstrap.startup()
    return create_app()
