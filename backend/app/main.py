"""API FastAPI. Motivo de FastAPI: pydantic ya valida la config y SSE/streaming vienen incluidos."""
import asyncio
import json
import threading
import time
import uuid
from contextlib import asynccontextmanager
from typing import Dict, List, Optional

from fastapi import Depends, FastAPI, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from . import avatar
from . import settings
from . import bootstrap
from . import history
from . import runtime
from . import updates
from .apierror import ApiError, describe_code, error_body, error_response
from .auth import Auth
from .config import Config, ConfigError, Device, pyd_body, describe, normalize_path, resolve_ref, validate_config
from .configstore import Conflict, ConfigStore, InvalidConfig, parse_text, config_events_gen, diff_configs, render_yaml
from .redact import redact
from .scheduler import Scheduler
from .sync import SyncAbort, count_versions, list_versions, restore_version, run_sync, valid_resolution
from .transport import TransportError, get_transport, local_folder_status

COOKIE = "checkpoint_session"
# index.html nunca se cachea: así un despliegue nuevo se ve al recargar (los assets con hash sí se cachean).
NO_CACHE = {"Cache-Control": "no-cache"}


class Run:
    def __init__(self, game, dry_run, name=None):
        self.id = uuid.uuid4().hex[:12]
        self.game, self.dry_run = game, dry_run  # `game` es el id interno del juego
        self.name = name or game
        self.lines: List[str] = []
        self.done = False
        self.status: Optional[dict] = None


def create_app(auth: Optional[Auth] = None) -> FastAPI:
    holder: dict = {}

    @asynccontextmanager
    async def lifespan(_app):
        task = asyncio.create_task(holder["scheduler"].loop())
        try:
            yield
        finally:
            task.cancel()

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    if auth is None:
        auth = Auth.from_env()
    runs: Dict[str, Run] = {}
    store = ConfigStore()

    def client_ip(request: Request) -> str:
        if settings.TRUST_PROXY:
            xff = request.headers.get("x-forwarded-for")
            if xff:
                return xff.split(",")[-1].strip()
        return request.client.host if request.client else "?"

    def require(request: Request):
        if not auth.valid(request.cookies.get(COOKIE)):
            raise ApiError(401, "err.main.session_required")
        if request.method not in ("GET", "HEAD"):
            origin = request.headers.get("origin")
            host = request.headers.get("host")
            if origin and host and origin.split("://", 1)[-1] != host:
                raise ApiError(403, "err.main.origin_forbidden")

    async def body_json(request: Request) -> dict:
        try:
            body = await request.json()
        except Exception:
            raise ApiError(400, "err.main.json_body_required")
        if not isinstance(body, dict):
            raise ApiError(400, "err.main.json_body_required")
        return body

    # ---- sesión ----
    @app.post("/api/login")
    async def login(request: Request, response: Response):
        body = await body_json(request)
        ip = client_ip(request)
        try:
            tok = auth.login(ip, str(body.get("user", "")), str(body.get("password", "")))
        except PermissionError as e:
            return error_response(429, "err.main.too_many_attempts", headers={"Retry-After": str(e.args[0])},
                                  extra={"retry_after": e.args[0]}, seconds=e.args[0])
        if not tok:
            return error_response(401, "err.main.bad_credentials")
        r = JSONResponse({"ok": True})
        r.set_cookie(COOKIE, tok, max_age=int(auth.ttl), httponly=True, samesite="strict",
                     secure=settings.COOKIE_SECURE, path="/")
        return r

    @app.post("/api/logout")
    async def logout(request: Request):
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
    def profile():
        """Nombre (el usuario del login: hay un único usuario, el de CHECKPOINT_USER) y versión de la foto, si hay."""
        v = avatar.version()
        return {"name": auth.user, "photo": {"version": v} if v else None}

    @app.get("/api/profile/photo", dependencies=[Depends(require)])
    def get_photo(request: Request):
        got = avatar.load()
        if not got:
            raise ApiError(404, "err.main.photo_unknown")
        data, mime, ver = got
        headers = {**PHOTO_HEADERS, "ETag": f'"{ver}"'}
        if request.headers.get("if-none-match", "").strip() == f'"{ver}"':
            return Response(status_code=304, headers=headers)
        return Response(content=data, media_type=mime, headers=headers)  # tipo fijado por nosotros, no por el cliente

    @app.put("/api/profile/photo", dependencies=[Depends(require)])
    async def put_photo(request: Request):
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
        ver = await run_in_threadpool(avatar.save, bytes(buf), declared)
        return {"ok": True, "photo": {"version": ver}}

    @app.delete("/api/profile/photo", dependencies=[Depends(require)])
    def delete_photo():
        avatar.delete()
        return {"ok": True, "photo": None}

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
        # `runtime` (docker|native) y `platform` (linux|windows|macos): lo único del sistema que se expone.
        return {"version": snap.version, "config": snap.as_dict(), "error": snap.error, **runtime.info()}

    @app.get("/api/config/events", dependencies=[Depends(require)])
    def config_events():
        return StreamingResponse(config_events_gen(store), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.post("/api/config/validate", dependencies=[Depends(require)])
    async def validate(request: Request):
        cfg, errors = validate_config((await body_json(request)).get("config"))
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
        return {"diff": diff_configs(snap.as_dict(), cfg.model_dump(exclude_none=True)), "version": snap.version}

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
            return invalid_response(e)
        except Conflict as e:
            return conflict_response(e)
        return {**res, "config": store.snapshot().as_dict()}

    @app.get("/api/config/backups", dependencies=[Depends(require)])
    def backups():
        return store.list_backups()

    @app.post("/api/config/restore", dependencies=[Depends(require)])
    async def restore_config(request: Request):
        body = await body_json(request)
        base = body.get("base_version")
        if not isinstance(base, str) or not base:
            raise ApiError(428, "err.main.base_version_required")
        try:
            res = store.restore(base, str(body.get("name", "")))
        except FileNotFoundError:
            raise ApiError(404, "err.main.backup_unknown")
        except InvalidConfig as e:
            return invalid_response(e)
        except Conflict as e:
            return conflict_response(e)
        return {**res, "config": store.snapshot().as_dict()}

    @app.post("/api/devices/test", dependencies=[Depends(require)])
    async def test_device(request: Request):
        """Prueba la conexión con los datos del formulario (aunque aún no estén guardados)."""
        body = await body_json(request)
        raw = body.get("device")
        if isinstance(raw, dict) and "name" not in raw:
            raw = {**raw, "name": "prueba"}  # el nombre no influye en la conexión
        try:
            dev = Device.model_validate(raw)
        except ValidationError as e:
            causes = [{"path": ".".join(str(x) for x in err["loc"]), **pyd_body(err)} for err in e.errors()]
            return {"ok": False, "message": "err.main.device_invalid",
                    "code": "err.main.device_invalid", "params": {"causes": causes}}
        if dev.local:
            return await run_in_threadpool(_test_local, dev, body)
        return await run_in_threadpool(_test_conn, dev)

    def _test_local(dev: Device, body: dict):
        """«Este equipo»: sin SSH. Comprueba las carpetas de saves que se indiquen (`paths`: lista de rutas)."""
        if runtime.running_in_docker():
            return {"ok": False, "message": "err.config.local_docker", "code": "err.config.local_docker", "params": {}}
        paths = body.get("paths", [])
        if not isinstance(paths, list) or len(paths) > 50 or not all(isinstance(p, str) for p in paths):
            return {"ok": False, "message": "paths debe ser una lista de rutas (máx. 50)",
                    "code": "err.main.paths_invalid", "params": {"max": 50}}
        if not paths:
            return local_folder_status(None)
        results = []
        for raw_path in paths:
            try:
                norm = normalize_path(dev.os, raw_path)
            except ConfigError as e:
                results.append((raw_path, {"ok": False, "message": describe_code(e.code, e.params), **e.body()}))
                continue
            results.append((norm, local_folder_status(norm)))
        if len(results) == 1:
            return results[0][1]
        # `message`: respaldo técnico (sin traducir); `results`: por ruta, con code/params (la UI los traduce).
        return {"ok": all(r["ok"] for _, r in results),
                "message": "\n".join(f"{p}: {r['message']}" for p, r in results),
                "results": [{"path": p, **r} for p, r in results]}

    def _test_conn(dev: Device):
        first = False
        # `code`/`params` los traduce la UI; `first_use` = se guardó una host key nueva (la UI añade el aviso
        # `err.bootstrap.first_use`). `message` es solo respaldo técnico. El stderr de ssh va redactado en params.
        try:
            first = bootstrap.ensure_host_key(dev.host, dev.port)
            get_transport(dev).check()
            return {"ok": True, "message": "err.transport.connection_ok", "code": "err.transport.connection_ok",
                    "params": {}, "first_use": first}
        except (TransportError, bootstrap.BootstrapError) as e:
            params = {k: redact(v) if isinstance(v, str) else v for k, v in e.params.items()}
            return {"ok": False, "message": describe_code(e.code, params), "code": e.code, "params": params,
                    "first_use": first}

    @app.get("/api/ssh/public-key", dependencies=[Depends(require)])
    def ssh_public_key():
        pub = bootstrap.public_key()
        if not pub:
            raise ApiError(404, "err.main.ssh_key_missing")
        return {"public_key": pub}

    def _config(error) -> Config:
        snap = store.snapshot()  # recarga si el fichero cambió; cada ejecución conserva la Config con la que empezó
        if snap.error:
            raise error(snap.error)
        return snap.cfg

    def _cfg() -> Config:
        return _config(lambda cause: ApiError(500, "err.main.config_file_invalid", cause=cause))

    # ---- sync automática ----
    def _auto_cfg() -> Config:
        return _config(lambda cause: RuntimeError(f"config.yaml inválido: {describe(cause)}"))

    scheduler = Scheduler(_auto_cfg, lambda g: any(r.game == g and not r.done for r in runs.values()))
    holder["scheduler"] = scheduler

    @app.get("/api/scheduler", dependencies=[Depends(require)])
    def get_scheduler():
        return scheduler.state()

    @app.put("/api/scheduler", dependencies=[Depends(require)])
    async def put_scheduler(request: Request):
        body = await body_json(request)
        try:
            return scheduler.update(body)
        except ValueError as e:
            return error_response(422, "err.main.settings_invalid", extra={"errors": e.args[0]})

    # ---- versión y actualizaciones (solo detección) ----
    checker = updates.UpdateChecker()

    @app.get("/api/updates", dependencies=[Depends(require)])
    def get_updates(refresh: bool = False):
        return checker.state(refresh=refresh)

    @app.put("/api/updates", dependencies=[Depends(require)])
    async def put_updates(request: Request):
        if not updates.applicable():
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
            return error_response(422, "err.main.settings_invalid", extra={"errors": errors})
        if "enabled" in body:
            checker.set_enabled(body["enabled"])
        if "channel" in body:
            checker.set_channel(body["channel"])
        return await run_in_threadpool(checker.state)

    @app.get("/api/scheduler/history", dependencies=[Depends(require)])
    def get_scheduler_history(limit: int = Query(50, ge=1, le=200)):
        snap = store.snapshot()
        games = snap.cfg.games if snap.cfg else {}
        return {"entries": history.annotate(history.read(limit), games)}

    def game_id(ref: str) -> str:
        """Id del juego a partir de la ruta (id o nombre). 404 si no existe, 409 si es ambiguo."""
        cfg = _cfg()
        try:
            gid = resolve_ref(cfg.games, ref)
        except ConfigError as e:
            raise ApiError(409, "err.main.game_ambiguous", cause=e.body())
        if gid is None:
            raise ApiError(404, "err.main.game_unknown")
        return gid

    # ---- sync ----
    @app.post("/api/sync/{game}", dependencies=[Depends(require)])
    async def start_sync(game: str, request: Request):
        cfg = _cfg()
        game = game_id(game)
        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            body = {}
        dry = bool(body.get("dry_run", False))
        resolution = body.get("resolution")
        if resolution is not None and not valid_resolution(resolution):
            raise ApiError(422, "err.main.resolution_invalid")
        expect = body.get("expect")
        if expect is not None and not (isinstance(expect, dict) and all(
                isinstance(k, str) and (v is None or isinstance(v, str)) for k, v in expect.items())):
            raise ApiError(422, "err.main.expect_invalid")
        if scheduler.current == game or any(r.game == game and not r.done for r in runs.values()):
            raise ApiError(409, "err.main.run_in_progress")
        run = Run(game, dry, cfg.games[game].name)
        runs[run.id] = run
        for old in [k for k, v in runs.items() if v.done][:-20]:
            runs.pop(old, None)

        def work():
            try:
                run.status = run_sync(cfg, game, dry, log=run.lines.append, resolution=resolution, expect=expect)
            except SyncAbort as e:
                run.lines.append(redact(f"ABORTADO: {e}"))
                run.status = {"result": "aborted", "code": e.code, "params": e.params, "message": str(e),
                              "game": game, "name": cfg.games[game].name}
            finally:
                run.done = True

        threading.Thread(target=work, daemon=True).start()
        return {"run_id": run.id}

    @app.get("/api/runs/{run_id}/stream", dependencies=[Depends(require)])
    def stream(run_id: str):
        run = runs.get(run_id)
        if not run:
            raise ApiError(404, "err.main.run_unknown")

        def gen():
            i = 0
            while True:
                while i < len(run.lines):
                    yield f"data: {json.dumps(run.lines[i])}\n\n"
                    i += 1
                if run.done and i >= len(run.lines):
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
                except Exception:
                    pass
        return out

    # ---- versiones ----
    @app.get("/api/versions/{game}", dependencies=[Depends(require)])
    def versions(game: str):
        cfg = _cfg()
        game = game_id(game)
        return list_versions(settings.DATA_DIR, game, {k: d.name for k, d in cfg.devices.items()})

    @app.get("/api/versions/{game}/limit", dependencies=[Depends(require)])
    def versions_limit(game: str):
        cfg = _cfg()
        game = game_id(game)
        return {"max": cfg.versions_limit(game), "count": count_versions(settings.DATA_DIR, game),
                "override": cfg.games[game].keep_versions is not None}

    @app.post("/api/versions/{game}/restore", dependencies=[Depends(require)])
    async def restore(game: str, request: Request):
        body = await body_json(request)
        cfg = _cfg()
        try:
            res = restore_version(cfg, game, str(body.get("version", "")), str(body.get("source", "")),
                                  settings.DATA_DIR)
        except SyncAbort as e:
            raise ApiError(400, "err.main.restore_failed", cause=e.body())
        return {"ok": True, "message": describe_code(res["code"], res["params"]), **res}

    # ---- web (SPA) ----
    # Los estáticos no contienen secretos; solo así se puede pintar la pantalla de login.
    @app.get("/{path:path}")
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
