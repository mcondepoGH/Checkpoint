"""Configuración: lectura, validación, diff, YAML, guardado con versión base, copias, prueba de dispositivos y clave SSH."""
import logging

from fastapi import Depends, Request
from fastapi.responses import StreamingResponse

from ...config.models import validate_config
from ...config.store import Conflict, InvalidConfig, config_events_gen, diff_configs, parse_text, render_yaml
from ...core import bootstrap, runtime
from ...core.errors import ApiError, error_response
from ...services.context import AppContext
from ...services.devices import check_device
from ..deps import body_json, get_ctx, internal_router

api_log = logging.getLogger("checkpoint.api")  # DEBUG: una línea por petición /api y detalle por endpoint (sin secretos)
router = internal_router()


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


@router.get("/api/config")
def get_config(ctx: AppContext = Depends(get_ctx)):
    snap = ctx.store.snapshot()
    api_log.debug("config: versión=%s error=%s", snap.version, bool(snap.error))
    # `runtime` (docker|native) y `platform` (linux|windows|macos): lo único del sistema que se expone.
    return {"version": snap.version, "config": snap.as_dict(), "error": snap.error, **runtime.info()}


@router.get("/api/config/events")
def config_events(ctx: AppContext = Depends(get_ctx)):
    return StreamingResponse(config_events_gen(ctx.store), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/api/config/validate")
async def validate(request: Request):
    cfg, errors = validate_config((await body_json(request)).get("config"))
    api_log.debug("config validate: ok=%s errores=%d", not errors, len(errors))
    return {"ok": not errors, "errors": errors}


@router.post("/api/config/diff")
async def diff(request: Request, ctx: AppContext = Depends(get_ctx)):
    store = ctx.store
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


@router.post("/api/config/yaml")
async def yaml_view(request: Request, ctx: AppContext = Depends(get_ctx)):
    try:
        cfg = draft(await body_json(request))
    except InvalidConfig as e:
        return invalid_response(e)
    return {"yaml": render_yaml(ctx.store.snapshot().text, cfg)}


@router.put("/api/config")
async def put_config(request: Request, ctx: AppContext = Depends(get_ctx)):
    store = ctx.store
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


@router.get("/api/config/backups")
def backups(ctx: AppContext = Depends(get_ctx)):
    b = ctx.store.list_backups()
    api_log.debug("config backups: %d", len(b))
    return b


@router.post("/api/config/restore")
async def restore_config(request: Request, ctx: AppContext = Depends(get_ctx)):
    store = ctx.store
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


@router.post("/api/devices/test")
async def test_device(request: Request):
    """Prueba la conexión con los datos del formulario (aunque aún no estén guardados)."""
    return await check_device(await body_json(request))


@router.get("/api/ssh/public-key")
def ssh_public_key():
    pub = bootstrap.public_key()
    api_log.debug("ssh public-key: disponible=%s", bool(pub))
    if not pub:
        raise ApiError(404, "err.main.ssh_key_missing")
    return {"public_key": pub}
