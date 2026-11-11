"""API key de usuario para las rutas /api/hook/*: una por usuario, visible siempre en el perfil y regenerable.

Como se muestra de nuevo, no se puede guardar solo el hash: se guarda recuperable, CIFRADA EN REPOSO, en
DATA_DIR/profile/<id>/apikey.enc (misma carpeta por usuario que la foto; ver avatar.user_dir). La clave de cifrado
sale de un secreto del hub (`hub.secret`, 32 bytes aleatorios, permisos 0600) que vive en la carpeta de CONFIG, fuera
de data/: una copia de seguridad solo de data/ no expone la key.

Cifrado: Fernet de la librería `cryptography` (AES-128-CBC + HMAC-SHA256, con marca de tiempo). La clave Fernet
(32 bytes en base64 urlsafe) se deriva del secreto con HMAC-SHA256. Fernet no tiene datos asociados (AAD): el id de
usuario va DENTRO del payload cifrado y se verifica al descifrar. Un fichero manipulado, de otro usuario o cifrado con
otro secreto no descifra (se trata como «sin key»)."""
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import tempfile
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from .core import settings
from .avatar import user_dir, user_id

PREFIX = "ck_"
FILE = "apikey.enc"
SECRET_FILE = "hub.secret"
KEY_RE = re.compile(r"ck_[A-Za-z0-9_-]{43}")  # 32 bytes en base64 urlsafe sin relleno = 43 caracteres


def is_well_formed(key) -> bool:
    return isinstance(key, str) and KEY_RE.fullmatch(key) is not None


def new_key() -> str:
    return PREFIX + base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")


# ---- secreto del hub ----
def secret_path() -> Path:
    return settings.CONFIG_PATH.parent / SECRET_FILE


def hub_secret() -> bytes:
    """Lee el secreto del hub; la primera vez lo genera (O_EXCL, 0600). Falla si existe pero es ilegible o corto."""
    p = secret_path()
    try:
        data = p.read_bytes()
    except FileNotFoundError:
        p.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:  # otro hilo/proceso lo acaba de crear
            data = p.read_bytes()
        else:
            with os.fdopen(fd, "wb") as f:
                f.write(secrets.token_hex(32).encode())
            data = p.read_bytes()
    if len(data) < 32:
        raise RuntimeError(f"secreto del hub inválido: {p}")
    try:
        if (p.stat().st_mode & 0o077) and os.name == "posix":
            os.chmod(p, 0o600)
    except OSError:
        pass
    return data


def _fernet(secret: bytes) -> Fernet:
    raw = hmac.new(secret, b"checkpoint/apikey/fernet", hashlib.sha256).digest()  # 32 bytes
    return Fernet(base64.urlsafe_b64encode(raw))


def encrypt(plain: bytes, secret: bytes, uid: str) -> bytes:
    payload = json.dumps({"u": uid, "k": plain.decode("ascii")}).encode()
    return _fernet(secret).encrypt(payload)


def decrypt(blob: bytes, secret: bytes, uid: str) -> Optional[bytes]:
    """El texto en claro, o None si el token no es válido, no es de este secreto o el id de usuario no coincide."""
    try:
        data = json.loads(_fernet(secret).decrypt(blob))
        if not isinstance(data, dict) or not isinstance(data.get("k"), str) or not hmac.compare_digest(
                str(data.get("u", "")).encode(), uid.encode()):
            return None
        return data["k"].encode("ascii")
    except (InvalidToken, ValueError, TypeError, UnicodeError):
        return None


# ---- key del usuario ----
def _file(username: str) -> Path:
    return user_dir(username) / FILE


def get(username: str) -> Optional[str]:
    """La key en claro, o None si no hay o no se puede descifrar (fichero manipulado o secreto distinto)."""
    p = _file(username)
    if not p.is_file() or p.is_symlink():
        return None
    plain = decrypt(p.read_bytes(), hub_secret(), user_id(username))
    key = plain.decode("ascii", "replace") if plain is not None else None
    return key if is_well_formed(key) else None


def create(username: str) -> str:
    """Genera una key nueva (invalida la anterior, si la había) y la guarda cifrada de forma atómica, 0600."""
    key = new_key()
    d = user_dir(username)
    d.mkdir(parents=True, exist_ok=True)
    blob = encrypt(key.encode("ascii"), hub_secret(), user_id(username))
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".apikey-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(blob)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, _file(username))
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return key


def revoke(username: str) -> bool:
    p = _file(username)
    if p.exists() or p.is_symlink():
        p.unlink()
        return True
    return False


def verify(username: str, candidate) -> bool:
    """¿Es `candidate` la key vigente de `username`? Tiempo constante; sin key hace igualmente una comparación
    (con un valor señuelo) para no distinguir «no hay key» de «key equivocada»."""
    stored = get(username)
    cand = candidate.encode("utf-8", "replace") if isinstance(candidate, str) else b""
    ok = hmac.compare_digest(cand, (stored or PREFIX + "x" * 43).encode())
    return bool(stored) and ok
