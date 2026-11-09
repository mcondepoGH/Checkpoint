"""Vigilante de proceso: tras `opened`, vigila el proceso del juego en ese dispositivo y, al cerrarse, lanza el checkpoint.

Una tarea asyncio por juego, solo en memoria (si el hub se reinicia se pierde; lo cubre el cron). Las llamadas a
transport son bloqueantes y van al executor. Reloj, `sleep`, sondeo y checkpoint son inyectables para los tests."""
import asyncio
import logging
import time
from typing import Awaitable, Callable, Dict, List, Optional

from . import settings
from .scheduler import iso, utcnow

log = logging.getLogger("checkpoint.watcher")

WAITING, RUNNING, SETTLING = "waiting", "running", "settling"


def _log_note(kind: str, game: str, device: str, detail: str = ""):
    (log.error if kind == "checkpoint_error" else log.info)(
        "vigilante %s juego=%s dispositivo=%s%s", kind, game, device, f" ({detail})" if detail else "")


class Watch:
    def __init__(self, game: str, device: str):
        self.game, self.device, self.state, self.since = game, device, WAITING, utcnow()

    def set(self, state: str):
        self.state, self.since = state, utcnow()


class Watcher:
    def __init__(self, probe: Callable[[str, str], bool], checkpoint: Callable[[str, str], Awaitable],
                 clock: Callable[[], float] = time.monotonic, sleep: Callable = asyncio.sleep,
                 poll: Optional[float] = None, settle: Optional[float] = None, first_seen: Optional[float] = None,
                 note: Callable = _log_note):
        """`probe(game, device)` -> ¿proceso abierto? (bloqueante; lanza si el dispositivo no responde).
        `checkpoint(game, device)` corre una vez al detectar el cierre. Tiempos: por defecto, los de settings (leídos al armar)."""
        self.probe, self.checkpoint, self.clock, self.sleep, self.note = probe, checkpoint, clock, sleep, note
        self._times = (poll, settle, first_seen)
        self.tasks: Dict[str, asyncio.Task] = {}
        self.watches: Dict[str, Watch] = {}

    def arm(self, game: str, device: str):
        """Arma (o reemplaza) la vigilancia del juego. Debe llamarse con el event loop en marcha."""
        self._drop(game)
        poll, settle, first = (v if v is not None else d for v, d in zip(
            self._times, (settings.HOOK_POLL, settings.HOOK_SETTLE, settings.HOOK_FIRST_SEEN)))
        w = Watch(game, device)
        self.watches[game] = w
        self.tasks[game] = asyncio.create_task(self._run(w, poll, settle, first))

    def _drop(self, game: str):
        t = self.tasks.pop(game, None)
        self.watches.pop(game, None)
        if t:
            t.cancel()

    def list(self) -> List[dict]:
        return [{"game": w.game, "device": w.device, "state": w.state, "since": iso(w.since)}
                for w in self.watches.values()]

    async def cancel_all(self):
        tasks = list(self.tasks.values())
        self.tasks.clear()
        self.watches.clear()
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _seen(self, w: Watch) -> Optional[bool]:
        """True/False según el proceso; None si el dispositivo no responde."""
        try:
            return bool(await asyncio.get_running_loop().run_in_executor(None, self.probe, w.game, w.device))
        except Exception as e:
            self.note("probe_error", w.game, w.device, type(e).__name__)
            return None

    async def _run(self, w: Watch, poll: float, settle: float, first_seen: float):
        me = asyncio.current_task()
        try:
            start, seen = self.clock(), False
            while True:
                r = await self._seen(w)
                if r:
                    seen = True
                    if w.state != RUNNING:
                        w.set(RUNNING)
                elif seen:  # visto y ya no (o el dispositivo no responde: suspensión, SSH caído): cierre
                    w.set(SETTLING)
                    await self.sleep(settle)
                    try:
                        await self.checkpoint(w.game, w.device)
                    except Exception as e:  # sin reintentos
                        self.note("checkpoint_error", w.game, w.device, f"{type(e).__name__}: {e}")
                    return
                elif self.clock() - start >= first_seen:
                    self.note("never_seen", w.game, w.device, f"proceso no visto en {first_seen:g} s; vigilancia descartada")
                    return
                await self.sleep(poll)
        finally:
            if self.tasks.get(w.game) is me:
                self.tasks.pop(w.game, None)
                self.watches.pop(w.game, None)
