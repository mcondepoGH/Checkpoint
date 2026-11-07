"""Sincronización automática periódica: una tarea asyncio que ejecuta todos los juegos cada X horas.

Ajustes persistentes en DATA_DIR/scheduler.json (prevalecen sobre las variables de entorno, que solo
dan los valores iniciales). Fechas internas en UTC, en ISO 8601."""
import asyncio
import json
import logging
import math
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from starlette.concurrency import run_in_threadpool

from . import history, settings
from .sync import ON_CONFLICT, SyncAbort, run_sync

MIN_HOURS, MAX_HOURS = 0.25, 168.0
FILE = "scheduler.json"
log = logging.getLogger("checkpoint.scheduler")
_root = logging.getLogger("checkpoint")
if not _root.handlers and not logging.getLogger().handlers:  # uvicorn no configura loggers de la app: sin esto el INFO se pierde
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    _root.addHandler(_h)
    _root.setLevel(logging.INFO)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds") if dt else None


def parse_iso(s) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(s)
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def validate_settings(body: dict, current: dict) -> dict:
    """Mezcla `body` sobre `current` y valida. Lanza ValueError con {campo: mensaje} en args[0]."""
    out, errors = dict(current), {}
    for k in ("enabled", "run_on_start"):
        if k in body:
            if isinstance(body[k], bool):
                out[k] = body[k]
            else:
                errors[k] = "debe ser verdadero o falso"
    if "interval_hours" in body:
        v = body["interval_hours"]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            errors["interval_hours"] = "debe ser un número"
        elif not MIN_HOURS <= v <= MAX_HOURS:
            errors["interval_hours"] = f"debe estar entre {MIN_HOURS:g} y {MAX_HOURS:g} horas"
        else:
            out["interval_hours"] = float(v)
    if "on_conflict" in body:
        if body["on_conflict"] in ON_CONFLICT:
            out["on_conflict"] = body["on_conflict"]
        else:
            errors["on_conflict"] = "debe ser 'skip' (omitir) o 'newest' (gana el más reciente)"
    if errors:
        raise ValueError(errors)
    return out


def compute_next_run(enabled: bool, interval_hours: float, last_run: Optional[datetime], now: datetime,
                     run_on_start: bool = False, starting: bool = False) -> Optional[datetime]:
    """Próxima ejecución. Al arrancar: ahora si run_on_start; si no, last_run+intervalo si aún no pasó,
    o ahora+intervalo. Fuera del arranque (cambio de ajustes, fin de ciclo): ahora+intervalo."""
    if not enabled:
        return None
    step = timedelta(hours=interval_hours)
    if starting:
        if run_on_start:
            return now
        if last_run and last_run + step > now:
            return last_run + step
    return now + step


def env_defaults() -> dict:
    h = settings.AUTO_INTERVAL_HOURS
    if not (math.isfinite(h) and MIN_HOURS <= h <= MAX_HOURS):
        h = 24.0
    return {"enabled": settings.AUTO_ENABLED, "interval_hours": h, "run_on_start": settings.AUTO_RUN_ON_START,
            "on_conflict": settings.AUTO_ON_CONFLICT if settings.AUTO_ON_CONFLICT in ON_CONFLICT else "skip"}


class Scheduler:
    def __init__(self, get_cfg: Callable, busy: Callable[[str], bool], clock: Callable[[], datetime] = utcnow,
                 runner: Callable = run_sync):
        self.get_cfg, self.busy, self.clock, self.runner = get_cfg, busy, clock, runner
        self._lock = threading.Lock()
        self.cfg = self._load()
        self.last_run = parse_iso(self.cfg.pop("last_run", None))
        self.last_status = self.cfg.pop("last_status", None)
        self.running = False
        self.current: Optional[str] = None
        self.next_run = compute_next_run(self.cfg["enabled"], self.cfg["interval_hours"], self.last_run,
                                         self.clock(), self.cfg["run_on_start"], starting=True)
        self._wake: Optional[asyncio.Event] = None
        self._booting = True  # el primer ciclo tras arrancar (sin cambios de ajustes) es 'startup' si run_on_start

    # ---- persistencia ----
    def _path(self):
        return settings.DATA_DIR / FILE

    def _load(self) -> dict:
        base = env_defaults()
        try:
            saved = json.loads(self._path().read_text())
            merged = validate_settings(saved, base)
            merged["last_run"], merged["last_status"] = saved.get("last_run"), saved.get("last_status")
            return merged
        except (OSError, ValueError, TypeError, AttributeError):
            return base

    def _save(self):
        p = self._path()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(f".{p.name}.tmp")
        tmp.write_text(json.dumps({**self.cfg, "last_run": iso(self.last_run), "last_status": self.last_status}))
        os.replace(tmp, p)

    # ---- API ----
    def state(self) -> dict:
        return {**self.cfg, "next_run": iso(self.next_run) if self.cfg["enabled"] else None,
                "last_run": iso(self.last_run), "last_status": self.last_status, "running": self.running,
                "min_hours": MIN_HOURS, "max_hours": MAX_HOURS}

    def update(self, body: dict) -> dict:
        with self._lock:
            self.cfg = validate_settings(body, self.cfg)
            self._booting = False
            self.next_run = compute_next_run(self.cfg["enabled"], self.cfg["interval_hours"], self.last_run,
                                             self.clock())
            self._save()
        if self._wake:
            self._wake.set()  # reprograma ya
        return self.state()

    # ---- ciclo ----
    def run_cycle(self) -> dict:
        """Sincroniza todos los juegos (modo normal), uno tras otro. Salta los que ya están en curso."""
        cfg = self.get_cfg()
        res, msgs, det = {}, [], {}
        for game in cfg.games:  # `game` es el id; en mensajes y logs se muestra el nombre
            name = cfg.games[game].name
            if self.busy(game):
                res[game] = "skipped"
                msgs.append(f"{name}: omitido (ya en curso)")
                det[game] = {"result": "skipped", "message": "ya en curso", "name": name}
                log.info("auto-sync juego=%s resultado=skipped (ya en curso)", name)
                continue
            self.current = game
            m = ""
            policy = getattr(cfg.games[game], "on_conflict", None) or self.cfg.get("on_conflict", "skip")
            try:
                st = self.runner(cfg, game, False, log=lambda m: None, conflict_policy=policy)
                res[game] = st["result"]
                if st["result"] == "conflict":
                    m = "omitido por conflicto: " + st.get("message", "")
                    msgs.append(f"{name}: {m}")
                elif st["result"] != "ok":
                    m = st.get("message", "")
                    msgs.append(f"{name}: {m}")
            except SyncAbort as e:
                res[game], m = "aborted", str(e)
                msgs.append(f"{name}: {e}")
            except Exception as e:  # un juego roto no frena a los demás
                res[game], m = "error", f"{type(e).__name__}: {e}"
                msgs.append(f"{name}: {m}")
            finally:
                self.current = None
            det[game] = {"result": res[game], "message": history.short(m), "name": name}
            (log.error if res[game] == "error" else log.info)(
                "auto-sync juego=%s resultado=%s%s", name, res[game], f" ({history.short(m, 120)})" if m else "")
        vals = set(res.values())
        result = ("error" if "error" in vals else "aborted" if "aborted" in vals
                  else "partial" if "partial" in vals else "conflict" if "conflict" in vals
                  else "skipped" if vals == {"skipped"} else "ok")
        return {"result": result, "games": res, "message": "; ".join(msgs), "details": det}

    async def _cycle(self, trigger: str = "scheduled"):
        if self.running:
            return
        self.running = True
        started, t0 = self.clock(), time.monotonic()
        log.info("auto-sync ciclo iniciado disparador=%s", trigger)
        try:
            status = await run_in_threadpool(self.run_cycle)
        except Exception as e:
            status = {"result": "error", "games": {}, "message": f"{type(e).__name__}: {e}"}
        finally:
            self.running = False
        dur = time.monotonic() - t0
        details = status.pop("details", None) or {g: {"result": r, "message": ""} for g, r in status["games"].items()}
        try:
            history.append(history.make_entry(started, dur, trigger, status["result"], details, status["message"]),
                           now=self.clock())
        except Exception as e:  # el registro nunca rompe el ciclo
            log.error("auto-sync no se pudo guardar el registro: %s", type(e).__name__)
        (log.error if status["result"] == "error" else log.info)(
            "auto-sync ciclo terminado resultado=%s duracion=%.1fs juegos=%s%s", status["result"], dur,
            ",".join(f"{g}={r}" for g, r in status["games"].items()),
            f" mensaje={history.short(status['message'], 200)}" if status["message"] else "")
        with self._lock:
            self.last_run = self.clock()
            self.last_status = status
            self.next_run = compute_next_run(self.cfg["enabled"], self.cfg["interval_hours"], self.last_run,
                                             self.clock())
            try:
                self._save()
            except OSError:
                pass

    async def loop(self):
        self._wake = asyncio.Event()
        while True:
            try:
                nxt = self.next_run if self.cfg["enabled"] else None
                timeout = None if nxt is None else max(0.0, (nxt - self.clock()).total_seconds())
                try:
                    await asyncio.wait_for(self._wake.wait(), timeout)
                    self._wake.clear()
                    continue
                except asyncio.TimeoutError:
                    pass
                trig = "startup" if self._booting and self.cfg["run_on_start"] else "scheduled"
                self._booting = False
                await self._cycle(trig)
            except asyncio.CancelledError:
                raise
            except Exception:  # el scheduler nunca muere
                await asyncio.sleep(5)
