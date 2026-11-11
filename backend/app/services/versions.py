"""Versiones (copias) de los saves de un juego: listado, límite y restauración. Sin FastAPI."""
import logging

from ..config.models import Config
from ..core import settings
from ..core.errors import ApiError, describe_code
from ..sync.engine import SyncAbort, count_versions, list_versions, restore_version

api_log = logging.getLogger("checkpoint.api")  # DEBUG: detalle por endpoint (sin secretos)


def versions_of(cfg: Config, game: str):
    """Versiones del juego (`game` ya es el id interno)."""
    res = list_versions(settings.DATA_DIR, game, {k: d.name for k, d in cfg.devices.items()})
    api_log.debug("versions: juego=%s entradas=%d", game, len(res) if hasattr(res, "__len__") else -1)
    return res


def limit_of(cfg: Config, game: str) -> dict:
    out = {"max": cfg.versions_limit(game), "count": count_versions(settings.DATA_DIR, game),
           "override": cfg.games[game].keep_versions is not None}
    api_log.debug("versions limit: juego=%s %s", game, out)
    return out


def restore(cfg: Config, game: str, body: dict) -> dict:
    """Restaura la versión `body["version"]` en `body["source"]`. 400 `err.main.restore_failed` si el motor aborta."""
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
