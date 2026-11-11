"""API FastAPI. Motivo de FastAPI: pydantic ya valida la config y SSE/streaming vienen incluidos."""
import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import APIRouter, Depends, FastAPI, Path, Query, Request
from fastapi.responses import FileResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool

from .api import docs
from .api.routers import config, profile, session
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
from .sync.scheduler import iso, utcnow
from .sync.engine import SyncAbort, count_versions, list_versions, restore_version
from .services.context import AppContext
from .services.runs import start_manual_sync

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
    store, runs, scheduler, hooks = ctx.store, ctx.runs, ctx.scheduler, ctx.hooks
    app.include_router(session.router)
    app.include_router(profile.router)
    app.include_router(config.router)
    app.include_router(scheduler_router.router)
    app.include_router(updates_router.router)

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
        w = hooks.active_watches(cfg)
        api_log.debug("hook watches: %d vigilancias activas", len(w))
        return w

    # (el router se incluye tras definir `opened`, más abajo)

    # ---- sync ----
    @app.post("/api/sync/{game}", dependencies=[Depends(require)])
    async def start_sync(game: str, request: Request):
        cfg = ctx.cfg()
        game = ctx.game_id(game)
        try:
            body = await request.json()
        except Exception:
            body = {}
        run = start_manual_sync(runs, scheduler, cfg, game, body)
        return {"run_id": run.id}

    @hook.post("/{game}/opened", **docs.OPENED)
    async def hook_opened(game: str = Path(description="Id o nombre del juego.", examples=["Mi Juego"]),
                          device: Optional[str] = Query(None, description="Id o nombre del dispositivo donde se "
                                                        "vigila el proceso del juego. Obligatorio si el juego está en "
                                                        "más de un dispositivo.", examples=["PC uno"])):
        """Aviso «se va a abrir el juego»: sync previo bloqueante con política de conflictos siempre `skip` (ignora la del juego y la del scheduler).
        Tras el aviso (salvo 400/401/404/409) arma la vigilancia de cierre si el juego tiene `process` (`watching`). Un fallo de la sync no es un 5xx: 200 con `outcome` descriptivo."""
        cfg = ctx.cfg()
        game = ctx.game_id(game)  # el 401 ya lo dio hook_user: no se revela si el juego existe
        return await hooks.opened(cfg, game, device)

    app.include_router(hook)

    @app.get("/api/watches", dependencies=[Depends(require)])
    def watches_view():
        """Vigilancias de cierre activas para la UI (sesión): {now, watches: [{game, device, state, since, last_poll, poll}]}.
        `now` es la hora del servidor (UTC) para que el cliente mida el latido sin depender de su reloj. Sin datos sensibles."""
        cfg = ctx.cfg()
        w = hooks.active_watches(cfg)
        api_log.debug("watches: %d vigilancias activas", len(w))
        return {"now": iso(utcnow()), "watches": w}

    @app.get("/api/games/{game}/hook-status", dependencies=[Depends(require)])
    def hook_status(game: str):
        """Por dispositivo del juego: último evento de hook (`opened` = hook, cierre = hook_closed) y vigilancia activa.
        {devices: [{device, last: {trigger, at, outcome} | null, watching: {state, since} | null}]}. Solo lectura, sin datos sensibles."""
        cfg = ctx.cfg()
        game = ctx.game_id(game)
        return hooks.status(cfg, game)

    @app.get("/api/runs/{run_id}/stream", dependencies=[Depends(require)])
    def stream(run_id: str):
        run = runs.get(run_id)
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

    @app.get("/api/status", dependencies=[Depends(require)])
    def status():
        out = {}
        cfg = store.snapshot().cfg
        games = cfg.games if cfg else {}
        sd = settings.DATA_DIR / "status"
        if sd.is_dir():
            for f in sd.glob("*.json"):
                try:
                    st = json.loads(f.read_text())
                    # El fichero se llama como el id del juego: esa es la clave y el valor de "game".
                    st["game"] = f.stem
                    # La UI pinta `name`: siempre el nombre actual de la config (nunca el id).
                    if f.stem in games and games[f.stem].name:
                        st["name"] = games[f.stem].name
                    elif st.get("name") in (None, "", f.stem):
                        st.pop("name", None)
                    out[f.stem] = st
                except Exception as e:
                    api_log.debug("status: no se pudo leer %s: %s", f.name, type(e).__name__)
        api_log.debug("status: %d juegos con estado", len(out))
        return out

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
