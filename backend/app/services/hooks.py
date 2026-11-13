"""Hook de aviso de apertura y cierre automático: el checkpoint de cierre, el historial de eventos y la vigilancia
del proceso del juego. Sin FastAPI: `HookService` es testeable con un scheduler, un registro de runs y una config."""

import logging
import os
import re
import shutil
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import AsyncIterator, Callable, List, Optional, Tuple, Union

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, TypeAdapter, ValidationError
from starlette.concurrency import run_in_threadpool

from ..config.models import Config, ConfigError, resolve_ref
from ..core import settings
from ..core.errors import ApiError
from ..sync import engine as sync_engine
from ..sync import locking
from ..sync.baseline import load_baseline, save_baseline
from ..sync.decide import decide
from ..sync.engine import finish_hub_update, write_winner_to_hub
from ..sync.fingerprint import (
    SHA256_RE,
    Fingerprint,
    ManifestError,
    _manifest_rel,
    dir_manifest,
    fingerprint,
    fingerprint_from_manifest,
    fingerprint_with_manifest,
)
from ..sync.watcher import Watcher, _log_note
from ..users import history
from . import hookfiles
from .runs import RunRegistry, game_busy

api_log = logging.getLogger("checkpoint.api")  # DEBUG: detalle por endpoint (sin secretos)
hook_log = logging.getLogger("checkpoint.hook")

MANIFEST_MAX_FILES = 50_000  # ficheros máx. de un manifiesto (más = 422 `err.hook.manifest_too_large`)


class ManifestEntry(BaseModel):
    """Un fichero del manifiesto que envía un dispositivo `http`: ruta relativa, sha256 hexadecimal, tamaño (bytes) y
    mtime (segundos Unix). La ruta y el sha256 los valida `fingerprint_from_manifest`."""

    model_config = ConfigDict(extra="forbid")
    path: str = Field(max_length=1024)
    sha256: str = Field(max_length=64)
    size: StrictInt = Field(ge=0)
    mtime: Union[StrictInt, StrictFloat] = Field(ge=0, allow_inf_nan=False)


_MANIFEST = TypeAdapter(List[ManifestEntry])


def parse_manifest(raw: list) -> Fingerprint:
    """Huella del manifiesto recibido (lista ya decodificada de JSON). ApiError 422 con código estable si no vale."""
    if len(raw) > MANIFEST_MAX_FILES:
        raise ApiError(422, "err.hook.manifest_too_large", max=MANIFEST_MAX_FILES)
    try:
        entries = _MANIFEST.validate_python(raw)
    except ValidationError as e:  # solo ruta y tipo del fallo: nunca el valor recibido
        errs = [{"path": ".".join(str(x) for x in err["loc"]), "type": err["type"]} for err in e.errors()[:10]]
        raise ApiError(422, "err.hook.manifest_invalid", errors=errs) from e
    try:
        return fingerprint_from_manifest(x.model_dump() for x in entries)
    except ManifestError as e:
        raise ApiError(422, e.code, **e.params) from e


def parse_manifest_files(raw: list) -> Tuple[Fingerprint, dict]:
    """Como `parse_manifest`, y además {ruta normalizada: {path, sha256 (minúsculas), size, mtime}} de cada fichero."""
    fp = parse_manifest(raw)
    wanted = {}
    for x in raw:
        rel = _manifest_rel(x["path"])
        wanted[rel] = {"path": rel, "sha256": x["sha256"].lower(), "size": x["size"], "mtime": x["mtime"]}
    return fp, wanted


def _int_param(name: str, raw, lo: int = 0) -> int:
    """Entero >= `lo` de un parámetro de query; 422 `err.hook.param_invalid` (con `param`) si no lo es."""
    if isinstance(raw, int) and not isinstance(raw, bool) and 0 <= raw < 10**18 and raw >= lo:
        return raw
    if isinstance(raw, str) and re.fullmatch(r"\d{1,18}", raw.strip()) and int(raw) >= lo:
        return int(raw)
    raise ApiError(422, "err.hook.param_invalid", param=name)


def _fp_json(fp: Fingerprint) -> dict:
    return {"hash": fp.hash, "files": fp.files, "size": fp.size, "mtime": fp.mtime}


def _counts(fp: Fingerprint) -> dict:
    return {"files": fp.files, "size": fp.size}


class HookService:
    def __init__(self, scheduler, runs: RunRegistry, auto_cfg: Callable[[], Config]):
        self.scheduler, self.runs, self.auto_cfg = scheduler, runs, auto_cfg
        self.watcher = Watcher(self.watch_probe, self.close_checkpoint, note=self.watch_note)
        self._last_purge = 0.0  # time.time() de la última purga del staging (para la purga oportunista de `upload`)

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
        self,
        game: str,
        device: str,
        result: str,
        code: Optional[str],
        params: Optional[dict] = None,
        name: Optional[str] = None,
    ):
        """Deja en el historial (trigger `hook_closed`) por qué NO hubo checkpoint de cierre: `skipped` (vigilancia
        descartada u omitido sin reintento) o `error` (el checkpoint falló). Solo código estable y parámetros no
        sensibles; solo registra, no cambia el comportamiento. El registro nunca rompe el vigilante."""
        scheduler = self.scheduler
        saved = False
        try:
            d = {"result": result, "message": ""}
            if code:
                d.update(code=code, params=params or {})
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
        d = self.auto_cfg().devices.get(dev)
        if d is not None and d.http:  # el hub no puede sondear su proceso: no hay vigilancia
            return {"watching": False, "watch_reason": "push_only"}
        if not g.process:
            return {"watching": False, "watch_reason": "no_process"}
        self.watcher.arm(game, dev)
        return {"watching": True}

    def active_watches(self, cfg: Config) -> list:
        """Vigilancias activas (en memoria) sin las de juegos borrados o desactivados."""
        return [x for x in self.watcher.list() if x["game"] in cfg.games and cfg.games[x["game"]].enabled]

    def resolve_device(self, cfg: Config, g, device: Optional[str], http: bool) -> str:
        """Id del dispositivo del juego al que apunta `?device=` (id o nombre) entre los del tipo pedido: `http=False`
        = los que contacta el hub (SSH o «Este equipo»), `http=True` = los que llaman a la API. Sin `device`, se deduce
        si hay uno solo de ese tipo. 400 si falta, es ambiguo o es del otro tipo; 404 si no existe en el juego."""
        every = {d: cfg.devices[d] for d in g.devices if d in cfg.devices}
        pool = {i: d for i, d in every.items() if d.http == http}
        if not device:
            if len(pool) != 1:
                api_log.debug("hook: juego=%s sin ?device= y con %d dispositivos (400)", g.name, len(pool))
                raise ApiError(
                    400, "err.hook.device_required", devices=", ".join(f"{d.name} ({i})" for i, d in pool.items())
                )
            return next(iter(pool))
        try:
            dev = resolve_ref(every, device)
        except ConfigError as e:
            api_log.debug("hook: juego=%s dispositivo %r ambiguo (400)", g.name, device)
            raise ApiError(400, "err.hook.device_ambiguous", cause=e.body()) from e
        if dev is None:
            api_log.debug("hook: juego=%s dispositivo %r desconocido (404)", g.name, device)
            raise ApiError(404, "err.hook.device_unknown")
        if dev not in pool:
            api_log.debug("hook: juego=%s dispositivo=%s no es del tipo http=%s (400)", g.name, dev, http)
            raise ApiError(400, "err.hook.device_not_http" if http else "err.hook.device_push_only")
        return dev

    def scope(self, cfg: Config, game_ref: str, device_q: Optional[str], bound: str) -> Tuple[str, str]:
        """(id del juego, id del dispositivo) para una petición con KEY DE DISPOSITIVO `bound`. La key identifica al
        dispositivo: `?device=` es opcional y, si se pasa (id o nombre), debe ser el de la key (si no, 403
        `err.apikey.device_mismatch`; un dispositivo desconocido también, para no revelar cuáles existen). El juego
        solo se busca entre los que incluyen ese dispositivo: uno que no lo incluye (o no existe) es el mismo 404
        `err.main.game_unknown`, sin distinguir «no existe» de «no es tuyo»."""
        if device_q:
            try:
                same = resolve_ref({bound: cfg.devices[bound]}, device_q) == bound
            except (ConfigError, KeyError):
                same = False
            if not same:
                api_log.debug("hook: ?device= no coincide con el dispositivo de la key (403)")
                raise ApiError(403, "err.apikey.device_mismatch")
        mine = {i: g for i, g in cfg.games.items() if bound in g.devices}
        try:
            gid = resolve_ref(mine, game_ref)
        except ConfigError as e:
            raise ApiError(409, "err.main.game_ambiguous", cause=e.body()) from e
        if gid is None:
            api_log.debug("hook: juego %r no existe o no incluye el dispositivo de la key (404)", game_ref)
            raise ApiError(404, "err.main.game_unknown")
        return gid, bound

    # ---- `POST /api/hook/{game}/fingerprint` ----
    async def fingerprint(
        self, cfg: Config, game: str, device: Optional[str], raw_manifest: list, with_manifest: bool = False
    ) -> dict:
        """Compara el manifiesto de un dispositivo `http` con el hub y dice qué debe hacer: `upload` (gana el
        dispositivo), `download` (gana el hub), `none` (iguales) o `conflict` (no se decide nada). Usa `decide` con la
        línea base, igual que la sync clásica. No toca ficheros ni historial. Única escritura: con `none`/`same` (y
        huella no vacía) fija la línea base del dispositivo y del hub, con el lock del juego (ocupado = 409
        `err.main.run_in_progress`); si ya es esa, no reescribe. Con `upload`/`download`/`conflict` no escribe nada
        ni toma el lock. Con `with_manifest` y `download`, añade `hub_manifest` (la misma forma que `GET /manifest`), sacado
        de la MISMA lectura del hub que la decisión (una sola pasada)."""
        g = cfg.games[game]
        dev = self.resolve_device(cfg, g, device, http=True)
        if not g.enabled:
            raise ApiError(409, "err.sync.game_disabled")
        if game_busy(self.scheduler, self.runs, game):
            api_log.debug("hook fingerprint: juego=%s dispositivo=%s ejecución en curso (409)", g.name, dev)
            raise ApiError(409, "err.main.run_in_progress")
        dev_fp = parse_manifest(raw_manifest)
        data_dir = Path(settings.DATA_DIR)
        hub_entries = None
        if with_manifest:
            hub_fp, hub_entries = await run_in_threadpool(fingerprint_with_manifest, data_dir / "hub" / game)
        else:
            hub_fp = await run_in_threadpool(fingerprint, data_dir / "hub" / game)
        fps = {dev: dev_fp, "hub": hub_fp}
        raw = load_baseline(data_dir, game)
        d = decide(fps, {k: raw[k] for k in fps if k in raw})
        out = {"game": game, "device": dev, "reason": None, "hub": _fp_json(hub_fp), "device_state": _fp_json(dev_fp)}
        if d["kind"] == "same":
            out.update(action="none", reason="same")
            if hub_fp.hash is not None:
                await run_in_threadpool(self._remember_same, game, dev, hub_fp.hash)
        elif d["kind"] == "winner":
            out.update(action="download" if d["winner"] == "hub" else "upload")  # gana el hub = baja; él = sube
            if out["action"] == "download" and hub_entries is not None:
                out["hub_manifest"] = hub_entries
        else:
            out.update(action="conflict", reason=d["reason"])
        api_log.debug(
            "hook fingerprint: juego=%s dispositivo=%s hub=%d ficheros dispositivo=%d ficheros acción=%s",
            g.name,
            dev,
            hub_fp.files,
            dev_fp.files,
            out["action"],
        )
        return out

    def _remember_same(self, game: str, dev: str, digest: str):
        """Línea base `{dev, hub}` = `digest` (huella ya verificada igual en dispositivo y hub), con el lock del
        juego. Idempotente: si ya la tiene, no escribe."""
        data_dir = Path(settings.DATA_DIR)
        with self._lock(game):
            if fingerprint(data_dir / "hub" / game).hash != digest:
                return  # un commit cambió el hub tras calcular `digest`: no se fija nada, decidirá el siguiente fingerprint
            raw = load_baseline(data_dir, game)
            if raw.get(dev) == digest and raw.get("hub") == digest:
                return
            save_baseline(data_dir, game, {dev: digest, "hub": digest})

    # ---- subida y bajada de saves de dispositivos `http` ----
    def _http_guard(self, cfg: Config, game: str, device: Optional[str]) -> Tuple[object, str]:
        """(juego, id del dispositivo `http`) o el error: 400/404 de dispositivo, 409 juego desactivado o con una
        ejecución en curso (guarda rápida; el lock del juego es la definitiva)."""
        g = cfg.games[game]
        dev = self.resolve_device(cfg, g, device, http=True)
        if not g.enabled:
            raise ApiError(409, "err.sync.game_disabled")
        if game_busy(self.scheduler, self.runs, game):
            api_log.debug("hook ficheros: juego=%s dispositivo=%s ejecución en curso (409)", g.name, dev)
            raise ApiError(409, "err.main.run_in_progress")
        return g, dev

    @contextmanager
    def _lock(self, game: str):
        """Lock por juego no bloqueante (el mismo que la sync): ocupado = 409 `err.main.run_in_progress`."""
        try:
            h = locking.acquire(Path(settings.DATA_DIR) / "locks" / f"{game}.lock")
        except locking.LockBusy:
            raise ApiError(409, "err.main.run_in_progress") from None
        try:
            yield
        finally:
            h.release()

    def _record(self, game: str, g, dev: str, cfg: Config, started: datetime, t0: float, winner: str, updated: str):
        """Entrada `hook` del historial (con el dispositivo) de una subida o bajada completada. Nunca lanza."""
        code, params = "err.sync.done", {"winner": winner, "updated": updated}
        try:
            history.append(
                history.make_entry(
                    started,
                    time.monotonic() - t0,
                    "hook",
                    "ok",
                    {game: {"result": "ok", "message": "", "name": g.name, "code": code, "params": params}},
                    "",
                    code,
                    params,
                    device=dev,
                ),
                now=self.scheduler.clock(),
            )
        except Exception as e:
            hook_log.warning("hook juego=%s: no se pudo guardar en el historial (%s)", g.name, type(e).__name__)

    async def manifest(self, cfg: Config, game: str, device: Optional[str]) -> dict:
        """`GET /{game}/manifest`: manifiesto del hub (qué ficheros bajar). Solo lectura, con el lock del juego."""
        g, dev = self._http_guard(cfg, game, device)

        def work():
            with self._lock(game):
                return dir_manifest(Path(settings.DATA_DIR) / "hub" / game)

        entries = await run_in_threadpool(work)
        fp = fingerprint_from_manifest(entries)
        api_log.debug("hook manifest: juego=%s dispositivo=%s %d ficheros", g.name, dev, fp.files)
        return {"game": game, "device": dev, **_fp_json(fp), "manifest": entries}

    def open_download(self, cfg: Config, game: str, device: Optional[str], rel, range_header: Optional[str]):
        """`GET /{game}/files`: abre un fichero del hub (bajo el lock, solo para abrirlo: un commit posterior no
        corta una descarga en curso) y devuelve (estado, cabeceras, iterador de bytes)."""
        g, dev = self._http_guard(cfg, game, device)
        with self._lock(game):
            p = hookfiles.safe_file(Path(settings.DATA_DIR) / "hub" / game, rel)
            if not p.is_file():
                raise ApiError(404, "err.hook.file_unknown")
            try:
                fh = open(p, "rb")
            except OSError:
                raise ApiError(404, "err.hook.file_unknown") from None
        try:
            size = os.fstat(fh.fileno()).st_size  # del fichero ya abierto, no del path (un commit pudo reemplazarlo)
            rng = hookfiles.parse_range(range_header, size)
        except BaseException:
            fh.close()
            raise
        start, end = rng if rng else (0, size - 1)
        length = end - start + 1 if size else 0
        headers = {"Accept-Ranges": "bytes", "Content-Length": str(length)}
        if rng:
            headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        api_log.debug("hook download: juego=%s dispositivo=%s %d bytes desde %d", g.name, dev, length, start)
        return (206 if rng else 200), headers, hookfiles.iter_file(fh, start, length)

    async def upload(
        self,
        cfg: Config,
        game: str,
        device: Optional[str],
        rel,
        size,
        sha256,
        offset,
        stream: AsyncIterator[bytes],
        content_length: Optional[int],
    ) -> dict:
        """`PUT /{game}/files`: trozo de un fichero a staging (reanudable). No toca el hub. Ver `hookfiles.receive_file`."""
        g, dev = self._http_guard(cfg, game, device)
        size, offset = _int_param("size", size), _int_param("offset", offset)
        if not isinstance(sha256, str) or not SHA256_RE.match(sha256.lower()):
            raise ApiError(422, "err.hook.param_invalid", param="sha256")
        data_dir = Path(settings.DATA_DIR)
        stage = hookfiles.stage_dir(data_dir, game, dev)
        tree = stage / "tree"
        norm = hookfiles.safe_file(tree, rel).relative_to(tree.resolve()).as_posix()
        if offset > size:
            raise ApiError(422, "err.hook.param_invalid", param="offset")
        max_bytes = settings.HOOK_MAX_FILE_BYTES
        if size > max_bytes or (content_length is not None and content_length > max_bytes):
            raise hookfiles.too_large()  # el Content-Length es falsificable: receive_file también corta en streaming
        # Sin el lock del juego: el staging es de este dispositivo y la parte está reservada (`part_lock`). El lock del
        # juego solo lo toma `commit`, que es lo único que toca el hub.
        await run_in_threadpool(self.maybe_purge_staging)
        out = await hookfiles.receive_file(
            stage,
            norm,
            size,
            sha256.lower(),
            offset,
            stream,
            max_bytes,
            game_root=data_dir / "staging" / game,
            cap_bytes=settings.HOOK_STAGING_MAX_BYTES,
        )
        api_log.debug(
            "hook upload: juego=%s dispositivo=%s recibido=%d/%d completo=%s",
            g.name,
            dev,
            out["received"],
            size,
            out["complete"],
        )
        return {"game": game, "device": dev, "path": norm, **out}

    # ---- purga del staging ----
    PURGE_EVERY_S = 600  # purga oportunista al subir: como mucho una cada 10 min

    def purge_staging(self) -> int:
        """Borra el staging (`data/staging/<juego>/<dispositivo>`) sin escrituras en más de `HOOK_STAGING_TTL_S`.
        Nunca toca el de un juego con el lock tomado o con una ejecución en curso. Devuelve cuántos borró. Nunca
        lanza: un fallo de disco se registra y se sigue."""
        self._last_purge = time.time()
        root = Path(settings.DATA_DIR) / "staging"
        if not root.is_dir():
            return 0
        limit = self._last_purge - settings.HOOK_STAGING_TTL_S
        n = 0
        for gdir in sorted(p for p in root.iterdir() if p.is_dir()):
            for ddir in sorted(p for p in gdir.iterdir() if p.is_dir()):
                try:
                    if hookfiles.newest_mtime(ddir) >= limit:
                        continue
                    if game_busy(self.scheduler, self.runs, gdir.name):
                        break
                    try:
                        h = locking.acquire(Path(settings.DATA_DIR) / "locks" / f"{gdir.name}.lock")
                    except locking.LockBusy:
                        break  # un commit o una sync tiene el juego: no se toca
                    try:
                        shutil.rmtree(ddir)
                        n += 1
                    finally:
                        h.release()
                except OSError as e:
                    hook_log.warning(
                        "purga del staging: %s/%s no se pudo borrar (%s)", gdir.name, ddir.name, e.__class__.__name__
                    )
            try:
                gdir.rmdir()  # carpeta del juego vacía
            except OSError:
                pass
        if n:
            hook_log.info("purga del staging: %d subidas antiguas borradas", n)
        return n

    def maybe_purge_staging(self) -> None:
        if time.time() - self._last_purge >= self.PURGE_EVERY_S:
            self.purge_staging()

    async def commit(
        self, cfg: Config, game: str, device: Optional[str], expect: Optional[str], raw_manifest: list
    ) -> dict:
        """`POST /{game}/commit`: valida y aplica la subida. Con el lock del juego: el hub debe seguir igual que cuando
        el dispositivo decidió (`expect`), la decisión debe seguir siendo «sube el dispositivo» (política `skip`:
        un conflicto no se resuelve), el staging debe tener todos los ficheros del manifiesto y el conjunto debe dar
        su hash. Entonces guarda el hub actual como versión, lo reemplaza por el manifiesto, fija la línea base y deja
        la entrada de historial. El manifiesto es la verdad completa: lo que el hub tenga de más desaparece."""
        g, dev = self._http_guard(cfg, game, device)
        mfp, wanted = parse_manifest_files(raw_manifest)
        started, t0 = self.scheduler.clock(), time.monotonic()
        out = await run_in_threadpool(self._commit_locked, cfg, game, g, dev, expect, mfp, wanted)
        if out["outcome"] == "ok":
            self._record(game, g, dev, cfg, started, t0, cfg.devices[dev].name, "hub")
        api_log.debug("hook commit: juego=%s dispositivo=%s resultado=%s", g.name, dev, out["outcome"])
        return out

    def _commit_locked(self, cfg, game, g, dev, expect, mfp: Fingerprint, wanted: dict) -> dict:
        data_dir = Path(settings.DATA_DIR)
        hub = data_dir / "hub" / game
        stage = hookfiles.stage_dir(data_dir, game, dev)
        with self._lock(game):
            hub_fp = fingerprint(hub)
            if hub_fp.hash != expect:
                raise ApiError(409, "err.hook.hub_changed")
            fps = {dev: mfp, "hub": hub_fp}
            raw = load_baseline(data_dir, game)
            d = decide(fps, {k: raw[k] for k in fps if k in raw})
            if d["kind"] == "same":
                finish_hub_update(data_dir, game, cfg.versions_limit(game), None, {dev: mfp.hash, "hub": mfp.hash})
                hookfiles.clear_stage(data_dir, game, dev)
                return {"game": game, "device": dev, "outcome": "unchanged", "hash": mfp.hash, **_counts(mfp)}
            if d["kind"] == "conflict" or d["winner"] != dev:
                reason = d["reason"] if d["kind"] == "conflict" else "hub"
                raise ApiError(409, "err.hook.commit_rejected", reason=reason)
            # Stage reservado durante verificación + escritura al hub: un PUT concurrente del mismo dispositivo
            # no puede cambiar `tree/` entre medias (409 `err.hook.upload_busy`). Siempre juego primero, luego stage.
            with hookfiles.stage_lock(stage):
                tree = stage / "tree"
                missing = hookfiles.prepare_tree(tree, wanted)
                if missing:
                    raise ApiError(422, "err.hook.upload_incomplete", missing=len(missing), paths=missing[:10])
                if fingerprint(tree).hash != mfp.hash:
                    raise ApiError(422, "err.hook.set_mismatch")
                hookfiles.apply_mtimes(tree, wanted)
                version = write_winner_to_hub(data_dir, game, tree, {"hub": hub} if not hub_fp.empty else {})
                finish_hub_update(data_dir, game, cfg.versions_limit(game), version, {dev: mfp.hash, "hub": mfp.hash})
                hookfiles.clear_stage(data_dir, game, dev)
        return {"game": game, "device": dev, "outcome": "ok", "hash": mfp.hash, **_counts(mfp), "version": version}

    # ---- `POST /api/hook/{game}/closed` ----
    def closed(self, cfg: Config, game: str, device: Optional[str]) -> dict:
        """Aviso «ya se cerró el juego» de un dispositivo `http` (el hub no puede sondear su proceso). Solo registra el
        cierre en el historial (`hook_closed`): no hay pull ni push ni sync clásica; el dispositivo hará después
        `fingerprint` y subirá o bajará por su cuenta. Juego desactivado: 200 `outcome: skipped` (queda `skipped`
        en el historial, como en `opened`). Ejecución en curso: 409 (también queda `skipped`). Un dispositivo que no
        es `http` es 400 `err.hook.device_not_http` (a esos los vigila el hub)."""
        g = cfg.games[game]
        dev = self.resolve_device(cfg, g, device, http=True)
        out = {"game": game, "device": dev, "recorded": True}
        if not g.enabled:
            api_log.debug("hook closed: juego=%s dispositivo=%s desactivado, se omite", g.name, dev)
            code = "err.sync.game_disabled"
            self.record_event(game, dev, "skipped", code, name=g.name)
            return {**out, "outcome": "skipped", "code": code, "params": {}}
        if game_busy(self.scheduler, self.runs, game):
            api_log.debug("hook closed: juego=%s dispositivo=%s ejecución en curso (409)", g.name, dev)
            self.record_event(game, dev, "skipped", "err.hook.busy", name=g.name)
            raise ApiError(409, "err.main.run_in_progress")
        self.record_event(game, dev, "ok", None, name=g.name)
        api_log.debug("hook closed: juego=%s dispositivo=%s cierre registrado", g.name, dev)
        return {**out, "outcome": "ok"}

    # ---- `POST /api/hook/{game}/opened` ----
    async def opened(self, cfg: Config, game: str, device: Optional[str]) -> dict:
        """Aviso «se va a abrir el juego» (`game` ya es el id interno): sync previo bloqueante con política de conflictos
        siempre `skip` (ignora la del juego y la del scheduler). Tras el aviso (salvo 400/401/404/409) arma la vigilancia
        de cierre si el juego tiene `process` (`watching`). Un fallo de la sync no es un 5xx: 200 con `outcome`."""
        scheduler = self.scheduler
        g = cfg.games[game]
        dev = self.resolve_device(cfg, g, device, http=False)
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
