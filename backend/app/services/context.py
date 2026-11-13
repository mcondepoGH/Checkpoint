"""Estado compartido de la app (una instancia por `create_app`): sesión, config, ejecuciones, scheduler, hook y
comprobador de actualizaciones. Los routers lo reciben con `Depends(get_ctx)` (ver `api/deps.py`); no hay globales."""

from typing import Callable, Optional

from ..config.models import Config, describe
from ..config.store import ConfigStore
from ..core import updates
from ..core.errors import ApiError
from ..sync.scheduler import Scheduler
from .games import resolve_game_id
from .hooks import HookService
from .runs import RunRegistry


class AppContext:
    def __init__(self, auth):
        self.auth = auth
        self.store = ConfigStore()
        self.runs = RunRegistry()
        self.scheduler = Scheduler(self.auto_cfg, self.runs.active)
        self.checker = updates.UpdateChecker()
        self.hooks = HookService(self.scheduler, self.runs, self.auto_cfg)
        self.scheduler.maintenance.append(self.hooks.purge_staging)  # purga horaria del staging de subidas HTTP

    @property
    def watcher(self):
        return self.hooks.watcher

    def _config(self, error: Callable[[Optional[dict]], Exception]) -> Config:
        snap = (
            self.store.snapshot()
        )  # recarga si el fichero cambió; cada ejecución conserva la Config con la que empezó
        if snap.error:
            raise error(snap.error)
        return snap.cfg

    def cfg(self) -> Config:
        """Config vigente para las peticiones: si el fichero es inválido, 500 `err.main.config_file_invalid`."""
        return self._config(lambda cause: ApiError(500, "err.main.config_file_invalid", cause=cause))

    def auto_cfg(self) -> Config:
        """Config para las tareas en segundo plano (scheduler, vigilante): si es inválida, RuntimeError."""
        return self._config(lambda cause: RuntimeError(f"config.yaml inválido: {describe(cause)}"))

    def game_id(self, ref: str) -> str:
        """Id del juego a partir de la ruta (id o nombre). 404 si no existe, 409 si es ambiguo."""
        return resolve_game_id(self.cfg(), ref)
