"""API FastAPI. Motivo de FastAPI: pydantic ya valida la config y SSE/streaming vienen incluidos."""
import asyncio
import json
import queue
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Dict, List, Optional

import os
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from . import settings
from . import bootstrap
from . import history
from .auth import Auth
from .config import Config, Device, validate_config
from .configstore import Conflict, ConfigStore, InvalidConfig, parse_text, config_events_gen, diff_configs, render_yaml
from .redact import redact
from .scheduler import Scheduler
from .sync import SyncAbort, list_versions, restore_version, run_sync
from .transport import TransportError, get_transport

COOKIE = "checkpoint_session"


class Run:
    def __init__(self, game, dry_run):
        self.id = uuid.uuid4().hex[:12]
        self.game, self.dry_run = game, dry_run
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
            raise HTTPException(401, "sesión requerida")
        if request.method not in ("GET", "HEAD"):
            origin = request.headers.get("origin")
            host = request.headers.get("host")
            if origin and host and origin.split("://", 1)[-1] != host:
                raise HTTPException(403, "origen no permitido")

    # ---- sesión ----
    @app.post("/api/login")
    async def login(request: Request, response: Response):
        body = await request.json()
        ip = client_ip(request)
        try:
            tok = auth.login(ip, str(body.get("user", "")), str(body.get("password", "")))
        except PermissionError as e:
            return JSONResponse({"detail": f"demasiados intentos; espera {e.args[0]} s",
                                 "retry_after": e.args[0]}, status_code=429,
                                headers={"Retry-After": str(e.args[0])})
        if not tok:
            return JSONResponse({"detail": "credenciales incorrectas"}, status_code=401)
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

    # ---- config ----
    async def body_json(request: Request) -> dict:
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(400, "cuerpo JSON requerido")
        if not isinstance(body, dict):
            raise HTTPException(400, "cuerpo JSON requerido")
        return body

    def draft(body: dict):
        """Valida el borrador {config: ...}; devuelve Config o responde 422 con errores por campo."""
        cfg, errors = validate_config(body.get("config"))
        if errors:
            raise InvalidConfig(errors)
        return cfg

    def invalid_response(e: InvalidConfig):
        return JSONResponse({"detail": "config no válida", "errors": e.errors}, status_code=422)

    def conflict_response(e: Conflict):
        return JSONResponse({"detail": str(e), "current_version": e.current_version}, status_code=409)

    @app.get("/api/config", dependencies=[Depends(require)])
    def get_config():
        snap = store.snapshot()
        return {"version": snap.version, "config": snap.as_dict(), "error": snap.error}

    @app.get("/api/config/status", dependencies=[Depends(require)])
    def config_status():
        snap = store.snapshot()
        return {"version": snap.version, "error": snap.error}

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
                raise HTTPException(404, "copia desconocida")
            cfg, err = parse_text(text)
            if err:
                raise HTTPException(422, f"la copia no es válida: {err}")
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
            raise HTTPException(428, "falta base_version (recarga la configuración)")
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
            raise HTTPException(428, "falta base_version (recarga la configuración)")
        try:
            res = store.restore(base, str(body.get("name", "")))
        except FileNotFoundError:
            raise HTTPException(404, "copia desconocida")
        except InvalidConfig as e:
            return invalid_response(e)
        except Conflict as e:
            return conflict_response(e)
        return {**res, "config": store.snapshot().as_dict()}

    @app.post("/api/devices/test", dependencies=[Depends(require)])
    async def test_device(request: Request):
        """Prueba la conexión con los datos del formulario (aunque aún no estén guardados)."""
        body = await body_json(request)
        try:
            dev = Device.model_validate(body.get("device"))
        except ValidationError as e:
            return {"ok": False, "message": "datos del dispositivo inválidos: " + _errs(e)}
        return await run_in_threadpool(_test_conn, dev)

    def _test_conn(dev: Device):
        first = False
        try:
            first = bootstrap.ensure_host_key(dev.host, dev.port)
            get_transport(dev).check()
            return {"ok": True, "message": "conexión OK" + (f" ({bootstrap.FIRST_USE_MSG})" if first else "")}
        except (TransportError, bootstrap.BootstrapError) as e:
            msg = redact(str(e))
            return {"ok": False, "message": msg + (f" [{bootstrap.FIRST_USE_MSG}]" if first else "")}

    @app.get("/api/ssh/public-key", dependencies=[Depends(require)])
    def ssh_public_key():
        pub = bootstrap.public_key()
        if not pub:
            raise HTTPException(404, "clave SSH aún no generada")
        return {"public_key": pub}

    def _cfg() -> Config:
        snap = store.snapshot()  # recarga si el fichero cambió; cada ejecución conserva la Config con la que empezó
        if snap.error:
            raise HTTPException(500, f"config.yaml inválido: {snap.error}")
        return snap.cfg

    # ---- sync automática ----
    def _auto_cfg() -> Config:
        snap = store.snapshot()
        if snap.error:
            raise RuntimeError(f"config.yaml inválido: {snap.error}")
        return snap.cfg

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
            return JSONResponse({"detail": "ajustes no válidos", "errors": e.args[0]}, status_code=422)

    @app.get("/api/scheduler/history", dependencies=[Depends(require)])
    def get_scheduler_history(limit: int = Query(50, ge=1, le=200)):
        return {"entries": history.read(limit)}

    # ---- sync ----
    @app.post("/api/sync/{game}", dependencies=[Depends(require)])
    async def start_sync(game: str, request: Request):
        cfg = _cfg()
        if game not in cfg.games:
            raise HTTPException(404, "juego desconocido")
        try:
            body = await request.json()
        except Exception:
            body = {}
        dry = bool(body.get("dry_run", False))
        if scheduler.current == game or any(r.game == game and not r.done for r in runs.values()):
            raise HTTPException(409, "ya hay una ejecución en curso de este juego")
        run = Run(game, dry)
        runs[run.id] = run
        for old in [k for k, v in runs.items() if v.done][:-20]:
            runs.pop(old, None)

        def work():
            try:
                run.status = run_sync(cfg, game, dry, log=run.lines.append)
            except SyncAbort as e:
                run.lines.append(redact(f"ABORTADO: {e}"))
                run.status = {"result": "aborted", "message": str(e)}
            finally:
                run.done = True

        threading.Thread(target=work, daemon=True).start()
        return {"run_id": run.id}

    @app.get("/api/runs/{run_id}/stream", dependencies=[Depends(require)])
    def stream(run_id: str):
        run = runs.get(run_id)
        if not run:
            raise HTTPException(404, "ejecución desconocida")

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
        sd = settings.DATA_DIR / "status"
        if sd.is_dir():
            for f in sd.glob("*.json"):
                try:
                    out[f.stem] = json.loads(f.read_text())
                except Exception:
                    pass
        return out

    # ---- versiones ----
    @app.get("/api/versions/{game}", dependencies=[Depends(require)])
    def versions(game: str):
        if game not in _cfg().games:
            raise HTTPException(404, "juego desconocido")
        return list_versions(settings.DATA_DIR, game)

    @app.post("/api/versions/{game}/restore", dependencies=[Depends(require)])
    async def restore(game: str, request: Request):
        body = await request.json()
        cfg = _cfg()
        try:
            msg = restore_version(cfg, game, str(body.get("version", "")), str(body.get("source", "")),
                                  settings.DATA_DIR)
        except SyncAbort as e:
            raise HTTPException(400, str(e))
        return {"ok": True, "message": msg}

    # ---- web (SPA) ----
    # Los estáticos no contienen secretos; solo así se puede pintar la pantalla de login.
    @app.get("/{path:path}")
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404)
        root = settings.STATIC_DIR.resolve()
        f = (root / path).resolve()
        if path and f.is_file() and root in f.parents:
            return FileResponse(f)
        idx = root / "index.html"
        if idx.is_file():
            return FileResponse(idx)
        raise HTTPException(404, "frontend no construido")

    return app


def _errs(e) -> str:
    if isinstance(e, ValidationError):
        return "; ".join(f"{'.'.join(str(x) for x in err['loc'])}: {err['msg'].removeprefix('Value error, ')}"
                         for err in e.errors())
    return str(e)


def app_factory():
    bootstrap.startup()
    return create_app()
