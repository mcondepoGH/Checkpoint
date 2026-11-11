"""Prueba de conexión de un dispositivo con los datos del formulario (aunque aún no estén guardados). Sin FastAPI."""

import logging
import time

from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from ..config.models import ConfigError, Device, normalize_path, pyd_body
from ..core import bootstrap, runtime
from ..core.errors import describe_code
from ..core.redact import redact
from ..sync.transport import TransportError, get_transport, local_folder_status

api_log = logging.getLogger("checkpoint.api")  # DEBUG: detalle por endpoint (sin secretos)


async def check_device(body: dict) -> dict:
    """Prueba la conexión con `body["device"]`; para «este equipo», las carpetas de `body["paths"]`."""
    raw = body.get("device")
    if isinstance(raw, dict) and "name" not in raw:
        raw = {**raw, "name": "prueba"}  # el nombre no influye en la conexión
    try:
        dev = Device.model_validate(raw)
    except ValidationError as e:
        causes = [{"path": ".".join(str(x) for x in err["loc"]), **pyd_body(err)} for err in e.errors()]
        return {
            "ok": False,
            "message": "err.main.device_invalid",
            "code": "err.main.device_invalid",
            "params": {"causes": causes},
        }
    t0 = time.monotonic()
    if dev.local:
        res = await run_in_threadpool(_check_local, dev, body)
        api_log.debug(
            "devices/test: local ok=%s code=%s en %.0f ms",
            res.get("ok"),
            res.get("code"),
            (time.monotonic() - t0) * 1000,
        )
        return res
    res = await run_in_threadpool(_check_connection, dev)
    api_log.debug(
        "devices/test: %s@%s:%s ok=%s code=%s en %.0f ms",
        dev.user,
        dev.host,
        dev.port,
        res.get("ok"),
        res.get("code"),
        (time.monotonic() - t0) * 1000,
    )
    return res


def _check_local(dev: Device, body: dict):
    """«Este equipo»: sin SSH. Comprueba las carpetas de saves que se indiquen (`paths`: lista de rutas)."""
    if runtime.running_in_docker():
        return {"ok": False, "message": "err.config.local_docker", "code": "err.config.local_docker", "params": {}}
    paths = body.get("paths", [])
    if not isinstance(paths, list) or len(paths) > 50 or not all(isinstance(p, str) for p in paths):
        return {
            "ok": False,
            "message": "paths debe ser una lista de rutas (máx. 50)",
            "code": "err.main.paths_invalid",
            "params": {"max": 50},
        }
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
    return {
        "ok": all(r["ok"] for _, r in results),
        "message": "\n".join(f"{p}: {r['message']}" for p, r in results),
        "results": [{"path": p, **r} for p, r in results],
    }


def _check_connection(dev: Device):
    first = False
    # `code`/`params` los traduce la UI; `first_use` = se guardó una host key nueva (la UI añade el aviso
    # `err.bootstrap.first_use`). `message` es solo respaldo técnico. El stderr de ssh va redactado en params.
    try:
        first = bootstrap.ensure_host_key(dev.host, dev.port)
        get_transport(dev).check()
        return {
            "ok": True,
            "message": "err.transport.connection_ok",
            "code": "err.transport.connection_ok",
            "params": {},
            "first_use": first,
        }
    except (TransportError, bootstrap.BootstrapError) as e:
        params = {k: redact(v) if isinstance(v, str) else v for k, v in e.params.items()}
        return {
            "ok": False,
            "message": describe_code(e.code, params),
            "code": e.code,
            "params": params,
            "first_use": first,
        }
