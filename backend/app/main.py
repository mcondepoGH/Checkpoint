"""API FastAPI. Motivo de FastAPI: pydantic ya valida la config y SSE/streaming vienen incluidos."""
import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import APIRouter, Depends, FastAPI, Path, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool

from .api import docs
from .users import apikey
from .users import avatar
from .core import settings
from .core import bootstrap
from .users import history
from .core import runtime
from .core import updates
from .core.errors import ApiError, describe_code, error_body, error_response
from .api.auth import Auth
from .api.deps import COOKIE, body_json, client_ip, current_user, hook_user, require
from .api.middleware import RequestDebugLog
from .config.models import validate_config
from .config.store import Conflict, InvalidConfig, parse_text, config_events_gen, diff_configs, render_yaml
from .sync.scheduler import iso, utcnow
from .sync.engine import SyncAbort, count_versions, list_versions, restore_version
from .services.devices import check_device
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
    store, runs, scheduler, checker, hooks = ctx.store, ctx.runs, ctx.scheduler, ctx.checker, ctx.hooks

    # ---- sesión ----
    @app.post("/api/login")
    async def login(request: Request, response: Response):
        body = await body_json(request)
        ip = client_ip(request)
        try:
            tok = auth.login(ip, str(body.get("user", "")), str(body.get("password", "")))
        except PermissionError as e:
            api_log.debug("login: ip=%s bloqueada %ss por intentos fallidos", ip, e.args[0])
            return error_response(429, "err.main.too_many_attempts", headers={"Retry-After": str(e.args[0])},
                                  extra={"retry_after": e.args[0]}, seconds=e.args[0])
        if not tok:
            api_log.debug("login: ip=%s usuario=%r credenciales incorrectas", ip, str(body.get("user", "")))
            return error_response(401, "err.main.bad_credentials")
        api_log.debug("login: ip=%s usuario=%r correcto", ip, str(body.get("user", "")))
        r = JSONResponse({"ok": True})
        r.set_cookie(COOKIE, tok, max_age=int(auth.ttl), httponly=True, samesite="strict",
                     secure=settings.COOKIE_SECURE, path="/")
        return r

    @app.post("/api/logout")
    async def logout(request: Request):
        api_log.debug("logout: ip=%s", client_ip(request))
        auth.logout(request.cookies.get(COOKIE))
        r = JSONResponse({"ok": True})
        r.delete_cookie(COOKIE, path="/")
        return r

    @app.get("/api/session")
    async def session(request: Request):
        return {"authenticated": auth.valid(request.cookies.get(COOKIE))}

    @app.get("/api/public")
    async def public():
        """Ajustes que necesita la pantalla de login (sin sesión): hoy solo el idioma por defecto."""
        return {"default_lang": settings.default_lang()}

    # ---- perfil (nombre y foto) ----
    PHOTO_HEADERS = {"Cache-Control": "private, no-cache", "X-Content-Type-Options": "nosniff",
                     "Content-Security-Policy": "default-src 'none'; sandbox"}

    @app.get("/api/profile", dependencies=[Depends(require)])
    def profile(user: str = Depends(current_user)):
        """Nombre y versión de la foto, si hay, del usuario de la sesión."""
        v = avatar.version(user)
        return {"name": user, "photo": {"version": v} if v else None}

    @app.get("/api/profile/photo", dependencies=[Depends(require)])
    def get_photo(request: Request, user: str = Depends(current_user)):
        got = avatar.load(user)
        if not got:
            api_log.debug("foto de perfil: usuario=%s sin foto (404)", user)
            raise ApiError(404, "err.main.photo_unknown")
        data, mime, ver = got
        headers = {**PHOTO_HEADERS, "ETag": f'"{ver}"'}
        if request.headers.get("if-none-match", "").strip() == f'"{ver}"':
            return Response(status_code=304, headers=headers)
        return Response(content=data, media_type=mime, headers=headers)  # tipo fijado por nosotros, no por el cliente

    @app.put("/api/profile/photo", dependencies=[Depends(require)])
    async def put_photo(request: Request, user: str = Depends(current_user)):
        """Cuerpo = la imagen en bruto (JPEG, PNG o WebP, máx. 2 MB) con su Content-Type; se valida por los bytes."""
        declared = request.headers.get("content-type", "").split(";")[0].strip().lower()
        if declared not in avatar.EXT:
            raise ApiError(415, "err.main.photo_type")
        try:
            if int(request.headers.get("content-length", "0")) > avatar.MAX_BYTES:
                raise ApiError(413, "err.main.photo_too_large", max_mb=avatar.MAX_BYTES // (1024 * 1024))
        except ValueError:
            raise ApiError(400, "err.main.photo_empty")
        buf = bytearray()
        async for chunk in request.stream():
            buf += chunk
            if len(buf) > avatar.MAX_BYTES:
                raise ApiError(413, "err.main.photo_too_large", max_mb=avatar.MAX_BYTES // (1024 * 1024))
        if not buf:
            raise ApiError(400, "err.main.photo_empty")
        if avatar.sniff(bytes(buf)) != declared:
            raise ApiError(415, "err.main.photo_type")
        ver = await run_in_threadpool(avatar.save, bytes(buf), declared, user)
        api_log.debug("foto de perfil guardada: usuario=%s tipo=%s %d bytes version=%s", user, declared, len(buf), ver)
        return {"ok": True, "photo": {"version": ver}}

    @app.delete("/api/profile/photo", dependencies=[Depends(require)])
    def delete_photo(user: str = Depends(current_user)):
        avatar.delete(user)
        api_log.debug("foto de perfil borrada: usuario=%s", user)
        return {"ok": True, "photo": None}

    # ---- API key de usuario (gestión desde el perfil, con sesión de cookie) ----
    NO_STORE = {"Cache-Control": "no-store"}

    @app.get("/api/profile/apikey", dependencies=[Depends(require)])
    def get_apikey(response: Response, user: str = Depends(current_user)):
        """La key vigente en claro (se ve siempre en el perfil) o `exists: false`. Nunca se genera sola."""
        response.headers.update(NO_STORE)
        key = apikey.get(user)
        api_log.debug("API key: consulta usuario=%s existe=%s", user, key is not None)  # nunca la key
        return {"exists": key is not None, "key": key}

    @app.post("/api/profile/apikey", dependencies=[Depends(require)])
    def post_apikey(response: Response, user: str = Depends(current_user)):
        """Genera la key o, si ya había, la regenera (la anterior deja de valer al instante)."""
        response.headers.update(NO_STORE)
        key = apikey.create(user)
        api_log.debug("API key: generada/regenerada usuario=%s", user)
        return {"exists": True, "key": key}

    @app.delete("/api/profile/apikey", dependencies=[Depends(require)])
    def delete_apikey(response: Response, user: str = Depends(current_user)):
        response.headers.update(NO_STORE)
        apikey.revoke(user)
        api_log.debug("API key: revocada usuario=%s", user)
        return {"exists": False, "key": None}

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

    # ---- config ----
    def draft(body: dict):
        """Valida el borrador {config: ...}; devuelve Config o responde 422 con errores por campo."""
        cfg, errors = validate_config(body.get("config"))
        if errors:
            raise InvalidConfig(errors)
        return cfg

    def invalid_response(e: InvalidConfig):
        return error_response(422, "err.main.config_invalid", extra={"errors": e.errors})

    def conflict_response(e: Conflict):
        return error_response(409, "err.main.config_changed", extra={"current_version": e.current_version})

    @app.get("/api/config", dependencies=[Depends(require)])
    def get_config():
        snap = store.snapshot()
        api_log.debug("config: versión=%s error=%s", snap.version, bool(snap.error))
        # `runtime` (docker|native) y `platform` (linux|windows|macos): lo único del sistema que se expone.
        return {"version": snap.version, "config": snap.as_dict(), "error": snap.error, **runtime.info()}

    @app.get("/api/config/events", dependencies=[Depends(require)])
    def config_events():
        return StreamingResponse(config_events_gen(store), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.post("/api/config/validate", dependencies=[Depends(require)])
    async def validate(request: Request):
        cfg, errors = validate_config((await body_json(request)).get("config"))
        api_log.debug("config validate: ok=%s errores=%d", not errors, len(errors))
        return {"ok": not errors, "errors": errors}

    @app.post("/api/config/diff", dependencies=[Depends(require)])
    async def diff(request: Request):
        body = await body_json(request)
        snap = store.snapshot()
        if "backup" in body:
            try:
                text = store.read_backup(str(body["backup"]))
            except FileNotFoundError:
                raise ApiError(404, "err.main.backup_unknown")
            cfg, err = parse_text(text)
            if err:
                raise ApiError(422, "err.main.backup_invalid", cause=err)
        else:
            try:
                cfg = draft(body)
            except InvalidConfig as e:
                return invalid_response(e)
        d = diff_configs(snap.as_dict(), cfg.model_dump(exclude_none=True))
        api_log.debug("config diff: origen=%s versión=%s", "backup" if "backup" in body else "borrador", snap.version)
        return {"diff": d, "version": snap.version}

    @app.post("/api/config/yaml", dependencies=[Depends(require)])
    async def yaml_view(request: Request):
        try:
            cfg = draft(await body_json(request))
        except InvalidConfig as e:
            return invalid_response(e)
        return {"yaml": render_yaml(store.snapshot().text, cfg)}

    @app.put("/api/config", dependencies=[Depends(require)])
    async def put_config(request: Request):
        body = await body_json(request)
        base = body.get("base_version")
        if not isinstance(base, str) or not base:
            raise ApiError(428, "err.main.base_version_required")
        try:
            cfg = draft(body)
            res = store.save(base, cfg)
        except InvalidConfig as e:
            api_log.debug("config guardar: inválida (%d errores)", len(e.errors))
            return invalid_response(e)
        except Conflict as e:
            api_log.debug("config guardar: conflicto base=%s actual=%s", base, e.current_version)
            return conflict_response(e)
        api_log.debug("config guardada: base=%s", base)
        return {**res, "config": store.snapshot().as_dict()}

    @app.get("/api/config/backups", dependencies=[Depends(require)])
    def backups():
        b = store.list_backups()
        api_log.debug("config backups: %d", len(b))
        return b

    @app.post("/api/config/restore", dependencies=[Depends(require)])
    async def restore_config(request: Request):
        body = await body_json(request)
        base = body.get("base_version")
        if not isinstance(base, str) or not base:
            raise ApiError(428, "err.main.base_version_required")
        try:
            res = store.restore(base, str(body.get("name", "")))
        except FileNotFoundError:
            api_log.debug("config restaurar: backup %r desconocido (404)", body.get("name"))
            raise ApiError(404, "err.main.backup_unknown")
        except InvalidConfig as e:
            api_log.debug("config restaurar: backup inválido (%d errores)", len(e.errors))
            return invalid_response(e)
        except Conflict as e:
            api_log.debug("config restaurar: conflicto base=%s actual=%s", base, e.current_version)
            return conflict_response(e)
        api_log.debug("config restaurada: backup=%r base=%s", body.get("name"), base)
        return {**res, "config": store.snapshot().as_dict()}

    @app.post("/api/devices/test", dependencies=[Depends(require)])
    async def test_device(request: Request):
        """Prueba la conexión con los datos del formulario (aunque aún no estén guardados)."""
        return await check_device(await body_json(request))

    @app.get("/api/ssh/public-key", dependencies=[Depends(require)])
    def ssh_public_key():
        pub = bootstrap.public_key()
        api_log.debug("ssh public-key: disponible=%s", bool(pub))
        if not pub:
            raise ApiError(404, "err.main.ssh_key_missing")
        return {"public_key": pub}

    # ---- sync automática ----
    @app.get("/api/scheduler", dependencies=[Depends(require)])
    def get_scheduler():
        st = scheduler.state()
        api_log.debug("scheduler estado: %s", {k: v for k, v in st.items() if isinstance(v, (bool, int, float, str, type(None)))})
        return st

    @app.put("/api/scheduler", dependencies=[Depends(require)])
    async def put_scheduler(request: Request):
        body = await body_json(request)
        try:
            res = scheduler.update(body)
            api_log.debug("scheduler actualizado: campos=%s", sorted(body))
            return res
        except ValueError as e:
            api_log.debug("scheduler actualizar: inválido en %s", sorted(e.args[0]) if isinstance(e.args[0], dict) else e.args[0])
            return error_response(422, "err.main.settings_invalid", extra={"errors": e.args[0]})

    # ---- versión y actualizaciones (solo detección) ----
    @app.get("/api/updates", dependencies=[Depends(require)])
    def get_updates(refresh: bool = False):
        api_log.debug("updates: refresh=%s", refresh)
        return checker.state(refresh=refresh)

    @app.put("/api/updates", dependencies=[Depends(require)])
    async def put_updates(request: Request):
        if not updates.applicable():
            api_log.debug("updates actualizar: no aplicable (409)")
            return error_response(409, "err.main.updates_not_applicable", extra={"aplicable": False})
        body = await body_json(request)
        errors = {}
        if "enabled" in body and not isinstance(body["enabled"], bool):
            errors["enabled"] = error_body("err.main.updates.enabled_bool")
        if "channel" in body and body["channel"] not in updates.CHANNELS:
            errors["channel"] = error_body("err.main.updates.channel_invalid")
        if not errors and "enabled" not in body and "channel" not in body:
            errors["enabled"] = error_body("err.main.updates.field_required")
        if errors:
            api_log.debug("updates actualizar: inválido en %s", sorted(errors))
            return error_response(422, "err.main.settings_invalid", extra={"errors": errors})
        api_log.debug("updates actualizar: enabled=%s channel=%s", body.get("enabled"), body.get("channel"))
        if "enabled" in body:
            checker.set_enabled(body["enabled"])
        if "channel" in body:
            checker.set_channel(body["channel"])
        return await run_in_threadpool(checker.state)

    @app.get("/api/scheduler/history", dependencies=[Depends(require)])
    def get_scheduler_history(limit: int = Query(50, ge=1, le=50)):
        snap = store.snapshot()
        games = snap.cfg.games if snap.cfg else {}
        entries = history.annotate(history.read(limit), games)
        api_log.debug("scheduler history: limit=%d devueltas=%d", limit, len(entries))
        return {"entries": entries}

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
