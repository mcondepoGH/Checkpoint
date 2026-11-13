"""Transferencia de saves fichero a fichero para dispositivos `http` (sin FastAPI): staging de subidas reanudables,
lectura por rangos del hub y montaje del árbol del commit. Todo lo que escribe va a `data/staging/<juego>/<dispositivo>/`;
`data/hub/<juego>` solo lo toca `HookService.commit`, con el lock del juego.

Disposición del staging:
- `tree/<ruta>`: ficheros completos y verificados (sha256) de la subida en curso.
- `parts/<sha256 de la ruta>.part` + `.json`: subida a medias (el nombre sale de un hash, nunca de la ruta recibida)."""

import hashlib
import json
import os
import re
import shutil
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import AsyncIterator, Iterator, Optional, Tuple

from starlette.concurrency import run_in_threadpool

from ..core import settings
from ..core.errors import ApiError
from ..sync.safepath import UnsafePath, resolve_inside

CHUNK = 1 << 20
_RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")


def max_mb(max_bytes: int):
    """Límite en MiB para `params.max_mb` (entero si es exacto)."""
    mb = max_bytes / (1024 * 1024)
    return int(mb) if mb == int(mb) else mb


def too_large() -> ApiError:
    return ApiError(413, "err.hook.file_too_large", max_mb=max_mb(settings.HOOK_MAX_FILE_BYTES))


def staging_full() -> ApiError:
    return ApiError(413, "err.hook.staging_full", max_mb=max_mb(settings.HOOK_STAGING_MAX_BYTES))


def stage_dir(data_dir: Path, game: str, dev: str) -> Path:
    return Path(data_dir) / "staging" / game / dev


def safe_file(root: Path, rel) -> Path:
    """`resolve_inside` con el error de la API (400 `err.hook.file_path_invalid`)."""
    try:
        return resolve_inside(root, rel)
    except UnsafePath:
        raise ApiError(400, "err.hook.file_path_invalid") from None


def dir_bytes(root: Path) -> int:
    """Bytes de datos del staging de un juego (`<juego>/<dispositivo>/...`; 0 si no existe): ficheros de `tree/` y
    partes `.part`, sin los `.json` de metadatos. Tolera ficheros que desaparecen mientras se recorre."""
    total = 0
    root = Path(root)
    for p in root.rglob("*"):
        rel = p.relative_to(root).parts
        if len(rel) == 3 and rel[1] == "parts" and rel[2].endswith(".json"):
            continue
        try:
            if p.is_file() and not p.is_symlink():
                total += p.stat().st_size
        except OSError:
            continue
    return total


def newest_mtime(root: Path) -> float:
    """Última escritura (mtime más reciente) de `root` y todo lo que contiene."""
    newest = 0.0
    for p in [Path(root), *Path(root).rglob("*")]:
        try:
            newest = max(newest, p.lstat().st_mtime)
        except OSError:
            continue
    return newest


def clear_stage(data_dir: Path, game: str, dev: str) -> None:
    shutil.rmtree(stage_dir(data_dir, game, dev), ignore_errors=True)


# ---- bajada: rangos ----
def parse_range(header: Optional[str], size: int) -> Optional[Tuple[int, int]]:
    """(inicio, fin) inclusivos de un `Range: bytes=...` de un solo rango, o None si no hay cabecera. 416 si es
    inválido, de varios rangos o insatisfacible (`Content-Range: bytes */size`)."""
    if header is None:
        return None
    bad = ApiError(416, "err.hook.range_invalid", headers={"Content-Range": f"bytes */{size}"})
    m = _RANGE_RE.match(header.strip())
    if not m or (m.group(1) == "" and m.group(2) == ""):
        raise bad
    a, b = m.groups()
    if a == "":  # sufijo: los últimos n bytes
        n = int(b)
        if n == 0 or size == 0:
            raise bad
        return max(0, size - n), size - 1
    start = int(a)
    end = size - 1 if b == "" else min(int(b), size - 1)
    if start >= size or end < start:
        raise bad
    return start, end


def iter_file(fh, start: int, length: int) -> Iterator[bytes]:
    """Lee `length` bytes desde `start` en trozos y cierra el fichero al acabar."""
    try:
        fh.seek(start)
        left = length
        while left > 0:
            chunk = fh.read(min(CHUNK, left))
            if not chunk:
                break
            left -= len(chunk)
            yield chunk
    finally:
        fh.close()


# ---- subida ----
# Lock propio de cada parte (dispositivo + fichero): dos PUT simultáneos al mismo `.part` no se mezclan. No es el lock
# del juego: la subida no bloquea la sync ni a otros dispositivos. En memoria: la API corre en un solo proceso.
_busy_parts: set = set()
_committing: set = set()  # stages con un commit en curso (ver `stage_lock`)
_busy_guard = threading.Lock()


@contextmanager
def part_lock(stage: Path, rel: str):
    """Reserva la parte `rel` del staging `stage` mientras dura la subida; ocupada = 409 `err.hook.upload_busy`.
    También es 409 si ese stage tiene un commit en curso (`stage_lock`)."""
    key = (str(stage), rel)
    with _busy_guard:
        if key in _busy_parts or str(stage) in _committing:
            raise ApiError(409, "err.hook.upload_busy")
        _busy_parts.add(key)
    try:
        yield
    finally:
        with _busy_guard:
            _busy_parts.discard(key)


@contextmanager
def stage_lock(stage: Path):
    """Reserva TODO el stage de un dispositivo para el commit, que verifica `tree/` y lo copia al hub: ningún PUT del
    mismo dispositivo puede cambiar un fichero entre ambas cosas. No bloquea: con un PUT en curso en ese stage, o
    con otro commit, es 409 `err.hook.upload_busy`; y mientras dure, los PUT de ese stage también lo son. Orden de
    locks: primero el del juego y luego este (`part_lock` nunca toma el del juego, y ninguno espera: sin interbloqueo)."""
    key = str(stage)
    with _busy_guard:
        if key in _committing or any(k[0] == key for k in _busy_parts):
            raise ApiError(409, "err.hook.upload_busy")
        _committing.add(key)
    try:
        yield
    finally:
        with _busy_guard:
            _committing.discard(key)


def _part_paths(stage: Path, rel_norm: str) -> Tuple[Path, Path]:
    h = hashlib.sha256(rel_norm.encode()).hexdigest()
    return stage / "parts" / f"{h}.part", stage / "parts" / f"{h}.json"


def _drop(*paths: Path) -> None:
    for p in paths:
        p.unlink(missing_ok=True)


def _sha_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def _prepare_part(stage: Path, rel: str, size: int, sha: str, offset: int) -> Tuple[Path, Path]:
    """Deja la parte lista para añadir desde `offset`: offset 0 la reinicia; con offset > 0 exige que sea la misma
    subida (misma ruta, sha256 y tamaño) y que ya tenga exactamente `offset` bytes (409 con `received` si no)."""
    part, meta = _part_paths(stage, rel)
    part.parent.mkdir(parents=True, exist_ok=True)
    want = {"path": rel, "sha256": sha, "size": size}
    if offset == 0:
        part.write_bytes(b"")
        meta.write_text(json.dumps(want))
        return part, meta
    try:
        same = json.loads(meta.read_text()) == want
        have = part.stat().st_size if same else 0
    except (OSError, ValueError):
        have = 0
    if have != offset:
        raise ApiError(409, "err.hook.upload_offset_mismatch", received=have)
    return part, meta


async def receive_file(
    stage: Path,
    rel: str,
    size: int,
    sha: str,
    offset: int,
    stream: AsyncIterator[bytes],
    max_bytes: int,
    game_root: Optional[Path] = None,
    cap_bytes: Optional[int] = None,
) -> dict:
    """Recibe un trozo (`stream`) de la subida de `rel` y lo añade a su parte en staging; con el último trozo
    verifica el sha256 y publica el fichero en `tree/`. `rel` ya es una ruta normalizada y segura. Corta la subida en
    cuanto supera `max_bytes` (413) o el `size` declarado (422); la parte a medias se conserva si el cliente se cae
    (así se puede reanudar) y se borra si el fichero se rechaza. Nunca se lee el cuerpo entero a memoria.
    Con `game_root` y `cap_bytes`, el staging de todo el juego (todos sus dispositivos) no puede pasar de `cap_bytes`:
    413 `err.hook.staging_full`. La parte se reserva con `part_lock` (409 `err.hook.upload_busy`)."""
    with part_lock(stage, rel):
        return await _receive(stage, rel, size, sha, offset, stream, max_bytes, game_root, cap_bytes)


async def _receive(stage, rel, size, sha, offset, stream, max_bytes, game_root, cap_bytes) -> dict:
    part, meta = await run_in_threadpool(_prepare_part, stage, rel, size, sha, offset)
    received = offset
    try:
        # Ocupado ya (con la parte a `offset` bytes: un reinicio ya la vació) + lo que falta por llegar.
        used = await run_in_threadpool(dir_bytes, game_root) if game_root is not None and cap_bytes else 0
        if cap_bytes and used + (size - offset) > cap_bytes:
            raise staging_full()
        with open(part, "ab") as f:
            async for chunk in stream:
                if not chunk:
                    continue
                received += len(chunk)
                if received > max_bytes:
                    raise too_large()
                if cap_bytes and used + (received - offset) > cap_bytes:
                    raise staging_full()
                if received > size:
                    raise ApiError(422, "err.hook.upload_size_mismatch")
                await run_in_threadpool(f.write, chunk)
    except ApiError:
        _drop(part, meta)
        raise
    out = {"received": received, "size": size, "complete": False}
    if received < size:
        return out
    if await run_in_threadpool(_sha_of, part) != sha:
        _drop(part, meta)
        raise ApiError(422, "err.hook.sha_mismatch")
    dest = safe_file(stage / "tree", rel)  # se revalida justo antes de escribir (el árbol pudo cambiar)
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        os.replace(part, dest)
    except OSError:  # un fichero donde ya hay una carpeta o al revés
        _drop(part, meta)
        raise ApiError(400, "err.hook.file_path_invalid") from None
    _drop(meta)
    out["complete"] = True
    return out


# ---- commit ----
def prepare_tree(tree: Path, wanted: dict) -> list:
    """Deja en `tree` solo los ficheros del manifiesto (`wanted`: {ruta: entrada}): borra enlaces simbólicos, sobrantes
    y carpetas vacías. Devuelve las rutas del manifiesto que faltan o tienen otro tamaño."""
    if tree.is_dir():
        for p in sorted(tree.rglob("*"), reverse=True):
            if p.is_symlink():
                p.unlink()  # nunca se copia a través de un enlace
            elif p.is_file():
                if p.relative_to(tree).as_posix() not in wanted:
                    p.unlink()
            elif p.is_dir() and not any(p.iterdir()):
                p.rmdir()
    missing = []
    for rel, e in wanted.items():
        p = tree / rel
        if p.is_symlink() or not p.is_file() or p.stat().st_size != e["size"]:
            missing.append(rel)
    return missing


def apply_mtimes(tree: Path, wanted: dict) -> None:
    for rel, e in wanted.items():
        mt = int(e["mtime"])
        os.utime(tree / rel, (mt, mt))
