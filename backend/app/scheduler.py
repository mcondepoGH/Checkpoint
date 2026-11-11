"""Sincronización automática periódica: una tarea asyncio que ejecuta todos los juegos cada X horas.

Ajustes persistentes en DATA_DIR/scheduler.json (se editan desde la UI; sin fichero, valores por defecto). Fechas internas en UTC, en ISO 8601."""
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

from . import history
from .core import settings
from .apierror import describe_code, error_body
from .config import ON_CONFLICT
from .sync import SyncAbort, run_sync

MIN_HOURS, MAX_HOURS = 0.25, 168.0
FILE = "scheduler.json"
log = logging.getLogger("checkpoint.scheduler")
_root = logging.getLogger("checkpoint")
if not _root.handlers and not logging.getLogger().handlers:  # uvicorn no configura loggers de la app: sin esto el INFO se pierde
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    _root.addHandler(_h)
    _lvl, _warn = settings.resolve_log_level()
    _root.setLevel(_lvl)
    if _warn:
        _root.warning(_warn)


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
    """Mezcla `body` sobre `current` y valida. Lanza ValueError con {campo: {code, params}} en args[0] (la UI traduce)."""
    out, errors = dict(current), {}
    for k in ("enabled", "run_on_start"):
        if k in body:
            if isinstance(body[k], bool):
                out[k] = body[k]
            else:
                errors[k] = error_body("err.scheduler.bool_required")
    if "interval_hours" in body:
        v = body["interval_hours"]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            errors["interval_hours"] = error_body("err.scheduler.interval_not_number")
        elif not MIN_HOURS <= v <= MAX_HOURS:
            errors["interval_hours"] = error_body("err.scheduler.interval_range", min=MIN_HOURS, max=MAX_HOURS)
        else:
            out["interval_hours"] = float(v)
    if "on_conflict" in body:
        if body["on_conflict"] in ON_CONFLICT:
            out["on_conflict"] = body["on_conflict"]
        else:
            errors["on_conflict"] = error_body("err.scheduler.conflict_policy_invalid")
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


def default_settings() -> dict:
    """Ajustes de sync automática hasta que se guarden desde la UI."""
    return {"enabled": False, "interval_hours": 24.0, "run_on_start": False, "on_conflict": "skip"}


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
        base = default_settings()
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
    def policy_for(self, cfg, game: str) -> str:
        """Política ante conflictos de un juego: la suya, si no la global de la sync automática (por defecto `skip`)."""
        return cfg.games[game].on_conflict or self.cfg.get("on_conflict", "skip")

    def run_game(self, cfg, game: str, log: Callable = lambda m: None, policy: Optional[str] = None) -> tuple:
        """Ejecuta un juego (modo normal; política de conflictos `policy` o, si no, la del scheduler) y traduce el resultado.
        Devuelve (resultado, texto técnico para logs, {code, params} | {message} | None para UI e historial, estado
        crudo de run_sync o None si falló). Nunca lanza: lo comparten el ciclo y el aviso `opened` del hook."""
        m, c, st = "", None, None
        if not cfg.games[game].enabled:  # guarda de respaldo: un juego desactivado no se ejecuta
            code = "err.sync.game_disabled"
            return "skipped", code, {"code": code, "params": {}}, None
        try:
            st = self.runner(cfg, game, False, log=log, conflict_policy=policy or self.policy_for(cfg, game),
                             automatic=True)
            res = st["result"]
            sc = {"code": st["code"], "params": st.get("params") or {}} if st.get("code") else None
            if st["result"] == "conflict":
                m = "omitido por conflicto: " + st.get("message", "")
                c = ({"code": "err.scheduler.skipped_conflict", "params": {"cause": sc}} if sc else None)
            elif st["result"] != "ok":
                m, c = st.get("message", ""), sc
            if not c and m:
                c = {"message": m}  # sin code (runner ajeno): texto tal cual
        except SyncAbort as e:
            res, m, c = "aborted", str(e), {"code": e.code, "params": e.params}
        except Exception as e:  # un juego roto no frena a los demás
            res, m = "error", f"{type(e).__name__}: {e}"
            c = {"code": "err.sync.unexpected", "params": {"type": type(e).__name__, "detail": str(e)}}
        return res, m, c, st

    @staticmethod
    def game_detail(name: str, res: str, m: str, c: Optional[dict]) -> tuple:
        """(item de resumen | None, detalle del juego para el historial) a partir de run_game."""
        if c and "code" in c:
            return {"path": name, **c}, {"result": res, "name": name, **c}
        item = {"path": name, "message": c["message"]} if c else None
        return item, {"result": res, "message": history.short(m), "name": name}

    @staticmethod
    def summarize(res: dict, items: list, det: dict) -> dict:
        """Resultado global y mensaje/code del resumen a partir de {juego: resultado}, items y detalles."""
        vals = set(res.values())
        result = ("error" if "error" in vals else "aborted" if "aborted" in vals
                  else "partial" if "partial" in vals else "conflict" if "conflict" in vals
                  else "skipped" if vals == {"skipped"} else "ok")
        out = {"result": result, "games": res, "message": "", "details": det}
        coded = [i for i in items if "code" in i]
        if coded and len(coded) == len(items):
            out.update(code="err.scheduler.summary", params={"causes": items})
        elif items:  # alguno sin code (runner ajeno): texto técnico unido, como antes
            out["message"] = "; ".join(f"{i['path']}: {i.get('message') or describe_code(i['code'], i['params'])}" for i in items)
        return out

    def run_cycle(self) -> dict:
        """Sincroniza todos los juegos (modo normal), uno tras otro. Salta los que ya están en curso."""
        cfg = self.get_cfg()
        res, items, det = {}, [], {}
        for game in cfg.games:  # `game` es el id; en logs se muestra el nombre
            if not cfg.games[game].enabled:
                continue  # desactivado: se omite en silencio (ni registro, ni resumen)
            name = cfg.games[game].name
            if self.busy(game):
                res[game] = "skipped"
                items.append({"path": name, "code": "err.scheduler.skipped_busy", "params": {}})
                det[game] = {"result": "skipped", "code": "err.scheduler.busy", "params": {}, "name": name}
                log.info("auto-sync juego=%s resultado=skipped (ya en curso)", name)
                continue
            self.current = game
            try:
                res[game], m, c, _st = self.run_game(cfg, game)
            finally:
                self.current = None
            item, det[game] = self.game_detail(name, res[game], m, c)
            if item:
                items.append(item)
            (log.error if res[game] == "error" else log.info)(
                "auto-sync juego=%s resultado=%s%s", name, res[game], f" ({history.short(m, 120)})" if m else "")
        return self.summarize(res, items, det)

    async def _cycle(self, trigger: str = "scheduled"):
        if self.running:
            return
        self.running = True
        started, t0 = self.clock(), time.monotonic()
        log.info("auto-sync ciclo iniciado disparador=%s", trigger)
        try:
            status = await run_in_threadpool(self.run_cycle)
        except Exception as e:
            status = {"result": "error", "games": {}, "message": "", "code": "err.sync.unexpected",
                      "params": {"type": type(e).__name__, "detail": str(e)}}
        finally:
            self.running = False
        dur = time.monotonic() - t0
        if status.get("params"):
            status["params"] = history.clean_params(status["params"])  # last_status se persiste: sin secretos
        details = status.pop("details", None) or {g: {"result": r, "message": ""} for g, r in status["games"].items()}
        try:
            history.append(history.make_entry(started, dur, trigger, status["result"], details, status["message"],
                               status.get("code"), status.get("params")),
                           now=self.clock())
        except Exception as e:  # el registro nunca rompe el ciclo
            log.error("auto-sync no se pudo guardar el registro: %s", type(e).__name__)
        (log.error if status["result"] == "error" else log.info)(
            "auto-sync ciclo terminado resultado=%s duracion=%.1fs juegos=%s%s", status["result"], dur,
            ",".join(f"{g}={r}" for g, r in status["games"].items()),
            f" mensaje={history.short(status['message'] or describe_code(status['code'], status['params']), 200)}"
            if status["message"] or status.get("code") else "")
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
