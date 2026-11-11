"""Versiones guardadas en data/versions/<juego>/ y reemplazo casi atómico de directorios."""

import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from .fingerprint import fingerprint

VERSION_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{6}(-\d+)?$")


def _fmt(ts: int) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S") if ts else "-"


def _version_key(name: str):
    """Orden cronológico por el nombre (AAAA-MM-DD_HHMMSS[-n]); el sufijo -n se compara como número."""
    stamp, _, n = name[:17], name[17:18], name[18:]
    return (stamp, int(n) if n.isdigit() else 0)


def list_versions(data_dir: Path, game: str, names: Optional[Dict[str, str]] = None) -> List[dict]:
    """Versiones guardadas de `game` (id). `names` ({id de origen: nombre}) añade el nombre visible a cada origen."""
    names = names or {}
    base = Path(data_dir) / "versions" / game
    out = []
    if base.is_dir():
        for d in sorted(base.iterdir(), key=lambda d: _version_key(d.name), reverse=True):
            if d.is_dir() and VERSION_RE.match(d.name):
                sources = []
                for s in sorted(d.iterdir()):
                    if s.is_dir():
                        fp = fingerprint(s)
                        sources.append(
                            {
                                "source": s.name,
                                "name": names.get(s.name, s.name),
                                "files": fp.files,
                                "mtime": _fmt(fp.mtime),
                            }
                        )
                out.append({"version": d.name, "sources": sources})
    return out


def count_versions(data_dir: Path, game: str) -> int:
    base = Path(data_dir) / "versions" / game
    if not base.is_dir():
        return 0
    return sum(1 for d in base.iterdir() if d.is_dir() and not d.is_symlink() and VERSION_RE.match(d.name))


def prune_versions(
    data_dir: Path, game: str, keep: int, log=lambda m: None, protect: Optional[str] = None
) -> List[str]:
    """Borra las versiones MÁS ANTIGUAS de `game` hasta dejar `keep` (0 = sin límite: no borra nada).

    Orden por el nombre de la versión (no por mtime). Nunca borra `protect` (la recién creada) ni deja
    menos de 1. Solo toca directorios reales dentro de data/versions/<slug>/ (symlinks se ignoran).
    Devuelve los nombres borrados. El llamador debe tener el lock del juego.
    """
    if keep <= 0:
        return []
    base = Path(data_dir) / "versions" / game
    root = (Path(data_dir) / "versions").resolve()
    if base.is_symlink() or not base.is_dir() or base.resolve().parent != root:
        return []
    base = base.resolve()
    dirs = sorted(
        (d for d in base.iterdir() if d.is_dir() and not d.is_symlink() and VERSION_RE.match(d.name)),
        key=lambda d: _version_key(d.name),
    )
    done: List[str] = []
    for d in dirs[: max(0, len(dirs) - keep)]:
        if d.name == protect or d.resolve().parent != base:
            continue
        try:
            shutil.rmtree(d)
        except OSError as e:
            log(f"no se pudo eliminar la versión {d.name}: {e}")
            continue
        done.append(d.name)
    if done:
        log(f"poda (máx. {keep}): eliminadas {len(done)} versiones antiguas: {', '.join(done)}")
    return done


def _new_version_dir(data_dir: Path, game: str) -> Path:
    base = Path(data_dir) / "versions" / game
    base.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    d, i = base / stamp, 0
    while d.exists():
        i += 1
        d = base / f"{stamp}-{i}"
    d.mkdir()
    return d


def _replace_dir(src: Path, dst: Path):
    """Sustituye dst por copia de src de forma casi atómica."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    new = dst.with_name(dst.name + ".new")
    old = dst.with_name(dst.name + ".old")
    for t in (new, old):
        if t.exists():
            shutil.rmtree(t)
    shutil.copytree(src, new)
    if dst.exists():
        os.rename(dst, old)
    os.rename(new, dst)
    if old.exists():
        shutil.rmtree(old)
