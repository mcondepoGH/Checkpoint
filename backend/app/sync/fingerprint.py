"""Huella de un directorio (hash, mtime, nº de ficheros, tamaño) y listado de ficheros."""
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class Fingerprint:
    hash: Optional[str]
    mtime: int
    files: int
    size: int = 0

    @property
    def empty(self) -> bool:
        return self.files == 0


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
    return Fingerprint(hashlib.sha256("\n".join(entries).encode()).hexdigest(), mt, len(entries), size)


def relfiles(root: Path) -> set:
    root = Path(root)
    if not root.is_dir():
        return set()
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file() and not p.is_symlink()}
