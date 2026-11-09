"""Foto de perfil: una sola imagen, guardada en DATA_DIR/profile con nombre fijo (nunca el del cliente).
El navegador ya la recorta y la reduce a 256x256; aquí solo se valida el tipo real (por los bytes, sin Pillow:
no hay decodificación, así que se comprueba firma y estructura mínima), el tamaño y se escribe de forma atómica."""
import hashlib
import os
import tempfile
from pathlib import Path
from typing import Optional, Tuple

from . import settings

MAX_BYTES = 2 * 1024 * 1024  # misma cota que la entrada en el navegador
DIR = "profile"
STEM = "photo"
EXT = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}


def sniff(data: bytes) -> Optional[str]:
    """Tipo MIME según firma y estructura mínima (JPEG, PNG o WebP); None si no es una de las tres."""
    if data[:3] == b"\xff\xd8\xff" and data.rstrip(b"\x00")[-2:] == b"\xff\xd9":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR" and b"IEND" in data[-16:]:
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP" and data[12:16] in (b"VP8 ", b"VP8L", b"VP8X") \
            and 12 <= int.from_bytes(data[4:8], "little") + 8 <= len(data):
        return "image/webp"
    return None


def _dir() -> Path:
    return settings.DATA_DIR / DIR


def _files():
    d = _dir()
    return [d / f"{STEM}.{e}" for e in EXT.values()] if d.is_dir() else []


def load() -> Optional[Tuple[bytes, str, str]]:
    """(bytes, mime, versión) o None. La versión es un hash corto del contenido (sirve de ETag y de cache-busting)."""
    for mime, ext in EXT.items():
        p = _dir() / f"{STEM}.{ext}"
        if p.is_file() and not p.is_symlink():
            data = p.read_bytes()
            if sniff(data) == mime:  # un fichero manipulado a mano que no cuadra se ignora
                return data, mime, hashlib.sha256(data).hexdigest()[:16]
    return None


def version() -> Optional[str]:
    got = load()
    return got[2] if got else None


def save(data: bytes, mime: str) -> str:
    """Guarda la foto (sustituye a la anterior) y devuelve su versión. `mime` ya debe estar validado."""
    d = _dir()
    d.mkdir(parents=True, exist_ok=True)
    target = d / f"{STEM}.{EXT[mime]}"
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".photo-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o644)
        os.replace(tmp, target)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    for p in _files():
        if p != target:
            p.unlink(missing_ok=True)
    return hashlib.sha256(data).hexdigest()[:16]


def delete() -> bool:
    gone = False
    for p in _files():
        if p.exists() or p.is_symlink():
            p.unlink()
            gone = True
    return gone
