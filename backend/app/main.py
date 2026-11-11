"""API FastAPI. Motivo de FastAPI: pydantic ya valida la config y SSE/streaming vienen incluidos."""
import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import APIRouter, Depends, FastAPI, Path, Query, Request
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from .api import docs
from .api.routers import config, profile, session, sync
from .api.routers import scheduler as scheduler_router
from .api.routers import updates as updates_router
from .users import avatar
from .core import settings
from .core import bootstrap
from .core import updates
from .core.errors import ApiError, describe_code
from .api.auth import Auth
from .api.deps import body_json, hook_user, require
from .api.middleware import RequestDebugLog
from .sync.engine import SyncAbort, count_versions, list_versions, restore_version
from .services.context import AppContext

api_log = logging.getLogger("checkpoint.api")  # DEBUG: una línea por petición /api y detalle por endpoint (sin secretos)
# index.html nunca se cachea: así un despliegue nuevo se ve al recargar (los assets con hash sí se cachean).
NO_CACHE = {"Cache-Control": "no-cache"}


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
    app.include_router(session.router)
    app.include_router(profile.router)
    app.include_router(config.router)
    app.include_router(scheduler_router.router)
    app.include_router(updates_router.router)
    app.include_router(sync.router)

    # Todo lo de /api/hook/* cuelga de este router y de su dependencia (aquí irá `POST /api/hook/{game}/opened`).
    hook = APIRouter(prefix="/api/hook", tags=[docs.TAG], dependencies=[Depends(hook_user)],
                     responses={401: docs.R401, 429: docs.R429})

    @hook.get("/ping", **docs.PING)
    def hook_ping(user: str = Depends(hook_user)):
        api_log.debug("hook ping: usuario=%s", user)
        return {"ok": True, "user": user}

    @hook.get("/watches", **docs.WATCHES)
    def hook_watches():
        """Vigilancias de cierre activas (en memoria): [{game, device, state: waiting|running|settling, since}]. Sin los juegos desactivados."""
        cfg = ctx.cfg()
        w = ctx.hooks.active_watches(cfg)
        api_log.debug("hook watches: %d vigilancias activas", len(w))
        return w

    # (el router se incluye tras definir `opened`, más abajo)

    @hook.post("/{game}/opened", **docs.OPENED)
    async def hook_opened(game: str = Path(description="Id o nombre del juego.", examples=["Mi Juego"]),
                          device: Optional[str] = Query(None, description="Id o nombre del dispositivo donde se "
                                                        "vigila el proceso del juego. Obligatorio si el juego está en "
                                                        "más de un dispositivo.", examples=["PC uno"])):
        """Aviso «se va a abrir el juego»: sync previo bloqueante con política de conflictos siempre `skip` (ignora la del juego y la del scheduler).
        Tras el aviso (salvo 400/401/404/409) arma la vigilancia de cierre si el juego tiene `process` (`watching`). Un fallo de la sync no es un 5xx: 200 con `outcome` descriptivo."""
        cfg = ctx.cfg()
        game = ctx.game_id(game)  # el 401 ya lo dio hook_user: no se revela si el juego existe
        return await ctx.hooks.opened(cfg, game, device)

    app.include_router(hook)

    # ---- versiones ----
    @app.get("/api/versions/{game}", dependencies=[Depends(require)])
    def versions(game: str):
        cfg = ctx.cfg()
        game = ctx.game_id(game)
        res = list_versions(settings.DATA_DIR, game, {k: d.name for k, d in cfg.devices.items()})
        api_log.debug("versions: juego=%s entradas=%d", game, len(res) if hasattr(res, "__len__") else -1)
        return res

    @app.get("/api/versions/{game}/limit", dependencies=[Depends(require)])
    def versions_limit(game: str):
        cfg = ctx.cfg()
        game = ctx.game_id(game)
        out = {"max": cfg.versions_limit(game), "count": count_versions(settings.DATA_DIR, game),
               "override": cfg.games[game].keep_versions is not None}
        api_log.debug("versions limit: juego=%s %s", game, out)
        return out

    @app.post("/api/versions/{game}/restore", dependencies=[Depends(require)])
    async def restore(game: str, request: Request):
        body = await body_json(request)
        cfg = ctx.cfg()
        try:
            res = restore_version(cfg, game, str(body.get("version", "")), str(body.get("source", "")),
                                  settings.DATA_DIR)
        except SyncAbort as e:
            api_log.debug("restaurar versión: juego=%s versión=%r origen=%r falló código=%s", game, body.get("version"),
                          body.get("source"), e.code)
            raise ApiError(400, "err.main.restore_failed", cause=e.body())
        api_log.debug("restaurar versión: juego=%s versión=%r origen=%r correcto", game, body.get("version"),
                      body.get("source"))
        return {"ok": True, "message": describe_code(res["code"], res["params"]), **res}

    # ---- documentación OpenAPI (solo la API de la API key; con sesión). Antes del catch-all SPA. ----
    docs.install(app, require)

    # ---- web (SPA) ----
    # Los estáticos no contienen secretos; solo así se puede pintar la pantalla de login.
    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            raise ApiError(404, "err.main.not_found")
        root = settings.STATIC_DIR.resolve()
        f = (root / path).resolve()
        if path and f.is_file() and root in f.parents:
            # Los assets de Vite llevan hash en el nombre: cacheables para siempre. El resto, a revalidar.
            if "assets" in f.relative_to(root).parts[:1]:
                return FileResponse(f, headers={"Cache-Control": "public, max-age=31536000, immutable"})
            return FileResponse(f, headers=NO_CACHE)
        idx = root / "index.html"
        if idx.is_file():
            return FileResponse(idx, headers=NO_CACHE)
        raise ApiError(404, "err.main.frontend_not_built")

    return app


def app_factory():
    bootstrap.startup()
    return create_app()
