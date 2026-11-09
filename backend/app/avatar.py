"""Foto de perfil: una sola imagen por usuario, en DATA_DIR/profile/<id-de-usuario>/photo.<ext> (nombre fijo, nunca el del cliente).
El id de carpeta se deriva del nombre de usuario con SHA-256 (ver user_id): el nombre en crudo jamás forma parte de una ruta.
El navegador ya la recorta y la reduce a 256x256; aquí solo se valida el tipo real (por los bytes, sin Pillow:
no hay decodificación, así que se comprueba firma y estructura mínima), el tamaño y se escribe de forma atómica."""
import hashlib
import os
import re
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


ID_LEN = 32  # hex: 128 bits del SHA-256; colisión inalcanzable y nombre de carpeta de longitud fija


def user_id(username: str) -> str:
    """Id estable y seguro como nombre de carpeta: hex de SHA-256(username UTF-8) truncado.
    Solo [0-9a-f], longitud fija, sin separadores ni '.', sea cual sea el nombre (`../`, `/`, unicode, mayúsculas).
    Un slug [a-z0-9_-] colisionaría (Ana/ana/ánã) y exigiría reglas de escape; el hash no."""
    if not isinstance(username, str) or not username.strip():
        raise ValueError("usuario vacío")
    try:
        raw = username.encode("utf-8")
    except UnicodeEncodeError:  # surrogates sueltos
        raw = username.encode("utf-8", "surrogatepass")
    return hashlib.sha256(raw).hexdigest()[:ID_LEN]


def user_dir(username: str) -> Path:
    """ÚNICO punto que resuelve la carpeta de un usuario; comprueba que queda dentro de DATA_DIR/profile."""
    base = _base()
    d = base / user_id(username)
    if d.parent != base or not _ID_RE.fullmatch(d.name):  # cinturón y tirantes
        raise ValueError("ruta de perfil fuera de la carpeta base")
    return d


def _base() -> Path:
    return settings.DATA_DIR / DIR


_ID_RE = re.compile(r"[0-9a-f]{%d}" % ID_LEN)


def _files(username: str):
    d = user_dir(username)
    return [d / f"{STEM}.{e}" for e in EXT.values()] if d.is_dir() else []


def migrate_legacy(username: str) -> bool:
    """Foto antigua DATA_DIR/profile/photo.<ext> (sin carpeta de usuario) -> carpeta del usuario dado (el admin).
    Si el usuario ya tiene foto, la antigua sobra y se borra. No deja ficheros huérfanos. True si había algo."""
    base = _base()
    if not base.is_dir():
        return False
    legacy = [p for e in EXT.values() if (p := base / f"{STEM}.{e}").exists() or p.is_symlink()]
    legacy += [p for p in base.glob(".photo-*.tmp") if p.is_file()]
    if not legacy:
        return False
    if load(username) is None:
        for mime, ext in EXT.items():
            p = base / f"{STEM}.{ext}"
            if p.is_file() and not p.is_symlink():
                data = p.read_bytes()
                if sniff(data) == mime:
                    save(data, mime, username)
                    break
    for p in legacy:
        p.unlink(missing_ok=True)
    return True


def load(username: str) -> Optional[Tuple[bytes, str, str]]:
    """(bytes, mime, versión) o None. La versión es un hash corto del contenido (sirve de ETag y de cache-busting)."""
    for mime, ext in EXT.items():
        p = user_dir(username) / f"{STEM}.{ext}"
        if p.is_file() and not p.is_symlink():
            data = p.read_bytes()
            if sniff(data) == mime:  # un fichero manipulado a mano que no cuadra se ignora
                return data, mime, hashlib.sha256(data).hexdigest()[:16]
    return None


def version(username: str) -> Optional[str]:
    got = load(username)
    return got[2] if got else None


def save(data: bytes, mime: str, username: str) -> str:
    """Guarda la foto (sustituye a la anterior) y devuelve su versión. `mime` ya debe estar validado."""
    d = user_dir(username)
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
    for p in _files(username):
        if p != target:
            p.unlink(missing_ok=True)
    return hashlib.sha256(data).hexdigest()[:16]


def delete(username: str) -> bool:
    gone = False
    for p in _files(username):
        if p.exists() or p.is_symlink():
            p.unlink()
            gone = True
    return gone
