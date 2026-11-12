"""Ejecuciones de sync en memoria: las manuales (`POST /api/sync/{juego}`) y las que lanza el hook. Sin FastAPI."""

import logging
import threading
import time
import uuid
from typing import Dict, List, Optional

from ..config.models import Config
from ..core.errors import ApiError
from ..core.redact import redact
from ..sync.engine import SyncAbort, run_sync, valid_resolution
from ..users import history

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


def record_manual(scheduler, game: str, name: str, status: dict, started, duration: float) -> bool:
    """Deja en el historial (trigger `manual`) el resultado de una sync manual real, con el mismo formato que el resto.
    Nunca lanza: un fallo al escribir el historial no rompe la sync. Devuelve si se guardó."""
    try:
        res = status.get("result") or "error"
        c = {"code": status["code"], "params": status.get("params") or {}} if status.get("code") else None
        m = status.get("message") or ""
        if not c and m:
            c = {"message": m}  # sin code: texto tal cual
        item, det = scheduler.game_detail(name, res, m, c)
        summary = scheduler.summarize({game: res}, [item] if item else [], {game: det})
        history.append(
            history.make_entry(
                started,
                duration,
                "manual",
                summary["result"],
                {game: det},
                summary["message"],
                summary.get("code"),
                summary.get("params"),
            ),
            now=scheduler.clock(),
        )
        return True
    except Exception as e:  # el registro nunca rompe la sync
        api_log.warning("sync %s: no se pudo guardar en el historial (%s)", game, type(e).__name__)
        return False


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
    if expect is not None and not (
        isinstance(expect, dict)
        and all(isinstance(k, str) and (v is None or isinstance(v, str)) for k, v in expect.items())
    ):
        raise ApiError(422, "err.main.expect_invalid")
    if game_busy(scheduler, registry, game):
        api_log.debug("sync %s: ya hay una ejecución en curso (409)", game)
        raise ApiError(409, "err.main.run_in_progress")
    run = registry.create(game, dry, cfg.games[game].name)
    api_log.debug(
        "sync %s: run=%s dry_run=%s resolution=%s expect=%s",
        game,
        run.id,
        dry,
        resolution,
        sorted(expect) if expect else None,
    )
    registry.prune()

    started, t0 = scheduler.clock(), time.monotonic()

    def work():
        try:
            run.status = run_sync(cfg, game, dry, log=run.lines.append, resolution=resolution, expect=expect)
        except SyncAbort as e:
            run.lines.append(redact(f"ABORTADO: {e}"))
            run.status = {
                "result": "aborted",
                "code": e.code,
                "params": e.params,
                "message": str(e),
                "game": game,
                "name": cfg.games[game].name,
            }
        except Exception as e:  # fallo inesperado: se registra igual (y el hilo no muere en silencio)
            run.lines.append(redact(f"ERROR: {type(e).__name__}: {e}"))
            run.status = {
                "result": "error",
                "code": "err.sync.unexpected",
                "params": {"type": type(e).__name__, "detail": str(e)},
                "message": f"{type(e).__name__}: {e}",
                "game": game,
                "name": cfg.games[game].name,
            }
        finally:
            st = run.status if isinstance(run.status, dict) else {}
            if not dry and st:  # las simulaciones no se registran
                record_manual(scheduler, game, cfg.games[game].name, st, started, time.monotonic() - t0)
            run.done = True
            api_log.debug(
                "sync %s: run=%s terminado resultado=%s código=%s", game, run.id, st.get("result"), st.get("code")
            )

    threading.Thread(target=work, daemon=True).start()
    return run
