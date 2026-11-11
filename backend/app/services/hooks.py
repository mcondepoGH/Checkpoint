"""Hook de aviso de apertura y cierre automático: el checkpoint de cierre, el historial de eventos y la vigilancia
del proceso del juego. Sin FastAPI: `HookService` es testeable con un scheduler, un registro de runs y una config."""

import logging
import threading
import time
from typing import Callable, Optional

from starlette.concurrency import run_in_threadpool

from ..config.models import Config, ConfigError, resolve_ref
from ..core import settings
from ..core.errors import ApiError
from ..sync import engine as sync_engine
from ..sync.watcher import Watcher, _log_note
from ..users import history
from .runs import RunRegistry, game_busy

api_log = logging.getLogger("checkpoint.api")  # DEBUG: detalle por endpoint (sin secretos)
hook_log = logging.getLogger("checkpoint.hook")


class HookService:
    def __init__(self, scheduler, runs: RunRegistry, auto_cfg: Callable[[], Config]):
        self.scheduler, self.runs, self.auto_cfg = scheduler, runs, auto_cfg
        self.watcher = Watcher(self.watch_probe, self.close_checkpoint, note=self.watch_note)

    # ---- ejecución del checkpoint del hook ----
    def start_run(self, cfg, game: str, trigger: str, device: Optional[str] = None):
        """Lanza en un hilo el checkpoint de un juego para el hook (`opened`: trigger `hook`; cierre: `hook_closed`):
        política de conflictos siempre `skip`, deja su entrada en el historial. Devuelve (run, finished, box)."""
        scheduler = self.scheduler
        g = cfg.games[game]
        run = self.runs.create(game, False, g.name)
        finished = threading.Event()
        started, t0 = scheduler.clock(), time.monotonic()
        box: dict = {}
        hook_log.debug("hook %s juego=%s dispositivo=%s: inicio run=%s", trigger, g.name, device, run.id)

        def work():
            try:
                res, m, c, st = scheduler.run_game(cfg, game, log=run.lines.append, policy="skip")
                box.update(res=res, m=m, c=c, st=st or {})
                run.status = st or {
                    "result": res,
                    "game": game,
                    "name": g.name,
                    "message": m,
                    **(c if c and "code" in c else {}),
                }
                if (
                    c and c.get("code") == "err.sync.sync_in_progress"
                ):  # lock tomado por otro proceso: no cuenta como run
                    box["busy"] = True
                    hook_log.info(
                        "hook %s juego=%s omitido: lock ocupado (sync_in_progress), sin reintento", trigger, g.name
                    )
                    hook_log.debug(
                        "hook %s run=%s: omitido por lock ocupado tras %.1f s", trigger, run.id, time.monotonic() - t0
                    )
                    if trigger == "hook_closed":  # en `opened` el lanzador ya recibe el 409
                        self.record_event(game, device or "", "skipped", "err.hook.busy", name=g.name)
                    return
                item, det = scheduler.game_detail(g.name, res, m, c)
                summary = scheduler.summarize({game: res}, [item] if item else [], {game: det})
                saved = False
                try:
                    history.append(
                        history.make_entry(
                            started,
                            time.monotonic() - t0,
                            trigger,
                            summary["result"],
                            {game: det},
                            summary["message"],
                            summary.get("code"),
                            summary.get("params"),
                            device=device,
                        ),
                        now=scheduler.clock(),
                    )
                    saved = True
                except Exception as e:  # el registro nunca rompe el aviso
                    hook_log.warning(
                        "hook %s juego=%s: no se pudo guardar en el historial (%s)", trigger, g.name, type(e).__name__
                    )
                dur, code = time.monotonic() - t0, summary.get("code")
                hook_log.info(
                    "hook %s juego=%s resultado=%s code=%s duración=%.1f s", trigger, g.name, res, code or "-", dur
                )
                hook_log.debug(
                    "hook %s run=%s: fin duración=%.1f s juego=%s dispositivo=%s resultado=%s code=%s "
                    "historial_guardado=%s",
                    trigger,
                    run.id,
                    dur,
                    g.name,
                    device,
                    res,
                    code,
                    saved,
                )
            finally:
                run.done = True
                finished.set()

        threading.Thread(target=work, daemon=True).start()
        self.runs.prune()
        return run, finished, box

    def record_event(
        self, game: str, device: str, result: str, code: str, params: Optional[dict] = None, name: Optional[str] = None
    ):
        """Deja en el historial (trigger `hook_closed`) por qué NO hubo checkpoint de cierre: `skipped` (vigilancia
        descartada u omitido sin reintento) o `error` (el checkpoint falló). Solo código estable y parámetros no
        sensibles; solo registra, no cambia el comportamiento. El registro nunca rompe el vigilante."""
        scheduler = self.scheduler
        saved = False
        try:
            d = {"result": result, "message": "", "code": code, "params": params or {}}
            if name:
                d["name"] = name
            history.append(
                history.make_entry(
                    scheduler.clock(), 0.0, "hook_closed", result, {game: d}, "", code, params or {}, device=device
                ),
                now=scheduler.clock(),
            )
            saved = True
        except Exception as e:
            hook_log.warning(
                "hook hook_closed juego=%s dispositivo=%s: no se pudo guardar en el historial (%s)",
                game,
                device,
                type(e).__name__,
            )
        hook_log.debug(
            "hook hook_closed juego=%s dispositivo=%s: entrada de historial resultado=%s code=%s historial_guardado=%s",
            name or game,
            device,
            result,
            code,
            saved,
        )

    # ---- vigilancia de cierre (callbacks del Watcher) ----
    def watch_note(self, kind: str, game: str, device: str, detail: str = ""):
        """Nota del vigilante: además del log, los descartes y el error del checkpoint van al historial."""
        _log_note(kind, game, device, detail)
        try:
            name = self.auto_cfg().games[game].name
        except Exception:  # config ilegible o juego borrado: se registra sin nombre
            name = None
        if kind == "never_seen":
            self.record_event(
                game, device, "skipped", "err.hook.never_seen", {"seconds": settings.HOOK_FIRST_SEEN}, name
            )
        elif kind == "checkpoint_error":
            self.record_event(
                game, device, "error", "err.hook.checkpoint_failed", {"error": detail.split(":", 1)[0]}, name
            )  # solo el tipo de excepción, nunca su mensaje

    def watch_probe(self, game: str, device: str) -> bool:
        cfg = self.auto_cfg()
        return sync_engine.get_transport(cfg.devices[device]).process_running(cfg.games[game].process)

    async def close_checkpoint(self, game: str, device: str):
        """Checkpoint al cerrarse el juego: mismo lock y lógica que `opened`, política `skip`, sin reintentos."""
        cfg = self.auto_cfg()
        hook_log.debug("hook hook_closed juego=%s dispositivo=%s: cierre detectado, lanzando checkpoint", game, device)
        if game not in cfg.games:
            hook_log.debug(
                "hook hook_closed juego=%s dispositivo=%s: juego ya no está en la configuración, se omite", game, device
            )
            self.record_event(game, device, "skipped", "err.hook.game_removed")
            return
        if not cfg.games[game].enabled:
            hook_log.debug("hook hook_closed juego=%s dispositivo=%s: juego desactivado, se omite", game, device)
            self.record_event(game, device, "skipped", "err.sync.game_disabled", name=cfg.games[game].name)
            return
        if game_busy(self.scheduler, self.runs, game):
            hook_log.info("hook hook_closed juego=%s omitido: ejecución en curso, sin reintento", cfg.games[game].name)
            hook_log.debug("hook hook_closed juego=%s dispositivo=%s: game_busy, sin reintento", game, device)
            self.record_event(game, device, "skipped", "err.hook.busy", name=cfg.games[game].name)
            return
        self.start_run(cfg, game, "hook_closed", device)

    def arm_watch(self, g, game: str, dev: str) -> dict:
        if not g.process:
            return {"watching": False, "watch_reason": "no_process"}
        self.watcher.arm(game, dev)
        return {"watching": True}

    def active_watches(self, cfg: Config) -> list:
        """Vigilancias activas (en memoria) sin las de juegos borrados o desactivados."""
        return [x for x in self.watcher.list() if x["game"] in cfg.games and cfg.games[x["game"]].enabled]

    # ---- `POST /api/hook/{game}/opened` ----
    async def opened(self, cfg: Config, game: str, device: Optional[str]) -> dict:
        """Aviso «se va a abrir el juego» (`game` ya es el id interno): sync previo bloqueante con política de conflictos
        siempre `skip` (ignora la del juego y la del scheduler). Tras el aviso (salvo 400/401/404/409) arma la vigilancia
        de cierre si el juego tiene `process` (`watching`). Un fallo de la sync no es un 5xx: 200 con `outcome`."""
        scheduler = self.scheduler
        g = cfg.games[game]
        devs = {d: cfg.devices[d] for d in g.devices if d in cfg.devices}
        if not device:
            if len(devs) != 1:
                api_log.debug("hook opened: juego=%s sin ?device= y con %d dispositivos (400)", g.name, len(devs))
                raise ApiError(
                    400, "err.hook.device_required", devices=", ".join(f"{d.name} ({i})" for i, d in devs.items())
                )
            dev = next(iter(devs))
        else:
            try:
                dev = resolve_ref(devs, device)
            except ConfigError as e:
                api_log.debug("hook opened: juego=%s dispositivo %r ambiguo (400)", g.name, device)
                raise ApiError(400, "err.hook.device_ambiguous", cause=e.body())
            if dev is None:
                api_log.debug("hook opened: juego=%s dispositivo %r desconocido (404)", g.name, device)
                raise ApiError(404, "err.hook.device_unknown")
        if not g.enabled:  # sin sincronizar ni vigilar; queda constancia en el historial
            api_log.debug("hook opened: juego=%s dispositivo=%s desactivado, se omite", g.name, dev)
            code = "err.sync.game_disabled"
            try:
                d = {"result": "skipped", "message": "", "code": code, "params": {}, "name": g.name}
                history.append(
                    history.make_entry(scheduler.clock(), 0.0, "hook", "skipped", {game: d}, "", code, {}, device=dev),
                    now=scheduler.clock(),
                )
            except Exception as e:  # el registro nunca rompe el aviso
                hook_log.warning(
                    "hook hook juego=%s: no se pudo guardar en el historial (%s)", g.name, type(e).__name__
                )
            return {
                "ok": False,
                "outcome": "skipped",
                "game": game,
                "device": dev,
                "code": code,
                "params": {},
                "watching": False,
                "watch_reason": "disabled",
            }
        if game_busy(scheduler, self.runs, game):
            api_log.debug("hook opened: juego=%s dispositivo=%s ejecución en curso (409)", g.name, dev)
            raise ApiError(409, "err.main.run_in_progress")
        t0 = time.monotonic()
        api_log.debug(
            "hook opened: juego=%s dispositivo=%s lanzando sync previo (espera máx. %ss)",
            g.name,
            dev,
            settings.HOOK_WAIT,
        )
        run, finished, box = self.start_run(cfg, game, "hook", dev)
        if not await run_in_threadpool(finished.wait, settings.HOOK_WAIT):
            api_log.debug(
                "hook opened: juego=%s dispositivo=%s timeout tras %.1f s, el sync sigue run=%s",
                g.name,
                dev,
                time.monotonic() - t0,
                run.id,
            )
            # El SSH sigue colgado: se responde ya (el cliente tiene su propio -m) y la sync termina por su cuenta.
            out = {
                "ok": False,
                "outcome": "timeout",
                "game": game,
                "device": dev,
                "run_id": run.id,
                "code": "err.hook.timeout",
                "params": {"seconds": settings.HOOK_WAIT},
            }
            out.update(self.arm_watch(g, game, dev))
            return out
        if box.get("busy"):
            api_log.debug("hook opened: juego=%s dispositivo=%s lock ocupado (409)", g.name, dev)
            raise ApiError(409, "err.main.run_in_progress")
        out = {"ok": box["res"] == "ok", "outcome": box["res"], "game": game, "device": dev, "run_id": run.id}
        st = box["st"]
        if st.get("code"):
            out.update(code=st["code"], params=history.clean_params(st.get("params") or {}))
        elif box["c"] and "code" in box["c"]:
            out.update(code=box["c"]["code"], params=history.clean_params(box["c"].get("params") or {}))
        out.update(self.arm_watch(g, game, dev))
        api_log.debug(
            "hook opened: juego=%s dispositivo=%s outcome=%s code=%s watching=%s en %.1f s",
            g.name,
            dev,
            out["outcome"],
            out.get("code"),
            out.get("watching"),
            time.monotonic() - t0,
        )
        return out

    # ---- `GET /api/games/{game}/hook-status` ----
    def status(self, cfg: Config, game: str) -> dict:
        """Por dispositivo del juego: último evento de hook (`opened` = hook, cierre = hook_closed) y vigilancia activa.
        {devices: [{device, last: {trigger, at, outcome} | null, watching: {state, since} | null}]}. Solo lectura, sin datos sensibles."""
        entries = [e for e in history.read() if e.get("trigger") in ("hook", "hook_closed")]  # más reciente primero
        watching = {w["device"]: w for w in self.watcher.list() if w["game"] == game}
        out = []
        for dev in cfg.games[game].devices:
            e = next((x for x in entries if x.get("device") == dev and game in x["games"]), None)
            w = watching.get(dev)
            out.append(
                {
                    "device": dev,
                    "last": (
                        {
                            "trigger": e["trigger"],
                            "at": e["started"],
                            "outcome": e["games"][game].get("result"),
                            **(
                                {"code": e["games"][game]["code"], "params": e["games"][game].get("params") or {}}
                                if e["games"][game].get("code")
                                else {}
                            ),
                        }
                        if e
                        else None
                    ),
                    "watching": {"state": w["state"], "since": w["since"]} if w else None,
                }
            )
        api_log.debug("hook-status: juego=%s dispositivos=%d vigilando=%d", game, len(out), len(watching))
        return {"devices": out}
