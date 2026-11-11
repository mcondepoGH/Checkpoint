"""Ejecuciones de sync en memoria: las manuales (`POST /api/sync/{juego}`) y las que lanza el hook. Sin FastAPI."""
import logging
import threading
import uuid
from typing import Dict, List, Optional

from ..config.models import Config
from ..core.errors import ApiError
from ..core.redact import redact
from ..sync.engine import SyncAbort, run_sync, valid_resolution

api_log = logging.getLogger("checkpoint.api")  # DEBUG: detalle por endpoint (sin secretos)
KEEP_DONE = 20  # ejecuciones terminadas que se conservan (para ver su log); las demás se olvidan


class Run:
    def __init__(self, game, dry_run, name=None):
        self.id = uuid.uuid4().hex[:12]
        self.game, self.dry_run = game, dry_run  # `game` es el id interno del juego
        self.name = name or game
        self.lines: List[str] = []
        self.done = False
        self.status: Optional[dict] = None


class RunRegistry:
    def __init__(self):
        self._runs: Dict[str, Run] = {}

    def create(self, game, dry_run, name=None) -> Run:
        run = Run(game, dry_run, name)
        self._runs[run.id] = run
        return run

    def get(self, run_id: str) -> Optional[Run]:
        return self._runs.get(run_id)

    def active(self, game: str) -> bool:
        """¿Hay una ejecución de ese juego sin terminar?"""
        return any(r.game == game and not r.done for r in self._runs.values())

    def prune(self):
        for old in [k for k, v in self._runs.items() if v.done][:-KEEP_DONE]:
            self._runs.pop(old, None)


def game_busy(scheduler, registry: RunRegistry, game: str) -> bool:
    """Ejecución en curso del juego: la sync automática lo tiene en marcha o hay un run (manual o de hook) sin terminar."""
    return scheduler.current == game or registry.active(game)


def start_manual_sync(registry: RunRegistry, scheduler, cfg: Config, game: str, body) -> Run:
    """Valida el cuerpo de `POST /api/sync/{juego}` y lanza la sync en un hilo. `game` ya es el id interno.
    Errores como ApiError: 409 juego desactivado / ejecución en curso, 422 resolución o `expect` inválidos."""
    if not cfg.games[game].enabled:  # también con dry_run: para sincronizarlo hay que reactivarlo
        api_log.debug("sync %s: juego desactivado (409)", game)
        raise ApiError(409, "err.sync.game_disabled")
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
    if game_busy(scheduler, registry, game):
        api_log.debug("sync %s: ya hay una ejecución en curso (409)", game)
        raise ApiError(409, "err.main.run_in_progress")
    run = registry.create(game, dry, cfg.games[game].name)
    api_log.debug("sync %s: run=%s dry_run=%s resolution=%s expect=%s", game, run.id, dry, resolution,
                  sorted(expect) if expect else None)
    registry.prune()

    def work():
        try:
            run.status = run_sync(cfg, game, dry, log=run.lines.append, resolution=resolution, expect=expect)
        except SyncAbort as e:
            run.lines.append(redact(f"ABORTADO: {e}"))
            run.status = {"result": "aborted", "code": e.code, "params": e.params, "message": str(e),
                          "game": game, "name": cfg.games[game].name}
        finally:
            run.done = True
            st = run.status if isinstance(run.status, dict) else {}
            api_log.debug("sync %s: run=%s terminado resultado=%s código=%s", game, run.id, st.get("result"),
                          st.get("code"))

    threading.Thread(target=work, daemon=True).start()
    return run
