"""Resolución del juego de una ruta (id o nombre). Sin FastAPI."""

import logging

from ..config.models import Config, ConfigError, resolve_ref
from ..core.errors import ApiError

api_log = logging.getLogger("checkpoint.api")  # DEBUG: detalle por endpoint (sin secretos)


def resolve_game_id(cfg: Config, ref: str) -> str:
    """Id del juego a partir de la ruta (id o nombre). 404 si no existe, 409 si es ambiguo."""
    try:
        gid = resolve_ref(cfg.games, ref)
    except ConfigError as e:
        api_log.debug("juego %r ambiguo (409)", ref)
        raise ApiError(409, "err.main.game_ambiguous", cause=e.body()) from e
    if gid is None:
        api_log.debug("juego %r desconocido (404)", ref)
        raise ApiError(404, "err.main.game_unknown")
    api_log.debug("juego %r -> id=%s", ref, gid)
    return gid
