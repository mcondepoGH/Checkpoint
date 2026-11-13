"""Huella de un directorio (hash, mtime, nº de ficheros, tamaño) y listado de ficheros."""

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional


SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass
class Fingerprint:
    hash: Optional[str]
    mtime: int
    files: int
    size: int = 0

    @property
    def empty(self) -> bool:
        return self.files == 0


class ManifestError(ValueError):
    """Manifiesto inválido. Contrato i18n: `code` (`err.hook.manifest_*`) + `params` (sin datos sensibles)."""

    def __init__(self, code: str, **params):
        super().__init__(code + "".join(f" {k}={v!r}" for k, v in params.items()))
        self.code, self.params = code, params


def _combine(entries: List[str]) -> str:
    """sha256 de las líneas `ruta\0sha256_fichero` ya ordenadas, unidas por `\n`. Lo comparten `fingerprint` y
    `fingerprint_from_manifest`: es lo que hace que ambas den el mismo hash para el mismo contenido."""
    return hashlib.sha256("\n".join(entries).encode()).hexdigest()


def fingerprint(root: Path) -> Fingerprint:
    root = Path(root)
    if not root.is_dir():
        return Fingerprint(None, 0, 0)
    entries = []
    mt = size = 0
    for p in sorted(root.rglob("*")):
        if p.is_symlink() or not p.is_file():
            continue
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        entries.append(f"{p.relative_to(root).as_posix()}\0{h.hexdigest()}")
        st = p.stat()
        mt = max(mt, int(st.st_mtime))
        size += st.st_size
    if not entries:
        return Fingerprint(None, 0, 0)
    return Fingerprint(_combine(entries), mt, len(entries), size)


def _manifest_rel(path) -> str:
    """Ruta relativa en formato `/` sin `.`, `..` ni absoluta; ManifestError si no es segura. Solo rechaza lo que
    escapa de la carpeta del juego (`..`, `/` inicial, NUL, vacía): NO filtra caracteres (`PATH_CHARS_RE` es para
    rutas de dispositivo), porque un save con `'`, `&` o `:` debe poder igualar al hub, como `fingerprint()`."""
    if not isinstance(path, str) or not path or "\0" in path:
        raise ManifestError("err.hook.manifest_path_invalid")
    rel = path.replace("\\", "/")
    parts = [x for x in rel.split("/") if x not in ("", ".")]
    if not parts or rel.startswith("/") or rel.endswith("/") or ".." in parts:
        raise ManifestError("err.hook.manifest_path_invalid")
    return "/".join(parts)


def fingerprint_from_manifest(entries: Iterable) -> Fingerprint:
    """Huella de un manifiesto [{path, sha256, size, mtime}] sin tocar disco: mismo hash que `fingerprint` del
    directorio con esos ficheros (orden por componentes de ruta, como `sorted(rglob)`). Función pura.
    ManifestError si una ruta no es segura, se repite tras normalizarla o el sha256 no es hexadecimal de 64."""
    items = {}
    mt = size = 0
    for e in entries:
        rel = _manifest_rel(e["path"])
        sha = e["sha256"].lower() if isinstance(e["sha256"], str) else ""
        if not SHA256_RE.match(sha):
            raise ManifestError("err.hook.manifest_sha_invalid")
        if rel in items:
            raise ManifestError("err.hook.manifest_duplicate")
        items[rel] = sha
        mt = max(mt, int(e["mtime"]))
        size += int(e["size"])
    if not items:
        return Fingerprint(None, 0, 0)
    lines = [f"{rel}\0{items[rel]}" for rel in sorted(items, key=lambda r: r.split("/"))]
    return Fingerprint(_combine(lines), mt, len(lines), size)


def dir_manifest(root: Path) -> List[dict]:
    """Manifiesto [{path, sha256, size, mtime}] de un directorio (ficheros regulares, sin enlaces simbólicos), ordenado
    como `fingerprint`. `fingerprint_from_manifest(dir_manifest(d))` da la misma huella que `fingerprint(d)`."""
    root = Path(root)
    out = []
    if not root.is_dir():
        return out
    for p in sorted(root.rglob("*")):
        if p.is_symlink() or not p.is_file():
            continue
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        st = p.stat()
        out.append(
            {
                "path": p.relative_to(root).as_posix(),
                "sha256": h.hexdigest(),
                "size": st.st_size,
                "mtime": int(st.st_mtime),
            }
        )
    return out


def fingerprint_with_manifest(root: Path):
    """(huella, manifiesto) de un directorio en una sola lectura de disco: la huella sale del manifiesto, así que
    ambos describen exactamente los mismos bytes. Misma huella que `fingerprint(root)`."""
    entries = dir_manifest(root)
    return fingerprint_from_manifest(entries), entries


def relfiles(root: Path) -> set:
    root = Path(root)
    if not root.is_dir():
        return set()
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file() and not p.is_symlink()}
