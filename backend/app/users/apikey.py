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

from ..core import settings
from .avatar import user_dir, user_id

PREFIX = "ck_"
DEVICE_PREFIX = "ckd_"  # key de dispositivo http: el prefijo dice al hub qué comprobar (`ck_` no casa con `ckd_`)
DEVICE_DIR = "devices"  # dentro de la carpeta del usuario: <id-de-dispositivo>.enc
FILE = "apikey.enc"
SECRET_FILE = "hub.secret"
KEY_RE = re.compile(r"ck_[A-Za-z0-9_-]{43}")  # 32 bytes en base64 urlsafe sin relleno = 43 caracteres
DEVICE_KEY_RE = re.compile(r"ckd_[A-Za-z0-9_-]{43}")
DEVICE_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")  # mismo formato que los ids de config; nombre de fichero seguro


def is_well_formed(key) -> bool:
    return isinstance(key, str) and KEY_RE.fullmatch(key) is not None


def is_well_formed_device(key) -> bool:
    return isinstance(key, str) and DEVICE_KEY_RE.fullmatch(key) is not None


def new_key(prefix: str = PREFIX) -> str:
    return prefix + base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")


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
        if (
            not isinstance(data, dict)
            or not isinstance(data.get("k"), str)
            or not hmac.compare_digest(str(data.get("u", "")).encode(), uid.encode())
        ):
            return None
        return data["k"].encode("ascii")
    except (InvalidToken, ValueError, TypeError, UnicodeError):
        return None


# ---- almacén genérico (usuario y dispositivo comparten formato, cifrado y escritura atómica) ----
def _load(p: Path, subject: str, well_formed) -> Optional[str]:
    if not p.is_file() or p.is_symlink():
        return None
    plain = decrypt(p.read_bytes(), hub_secret(), subject)
    key = plain.decode("ascii", "replace") if plain is not None else None
    return key if well_formed(key) else None


def _store(p: Path, subject: str, key: str) -> None:
    d = p.parent
    d.mkdir(parents=True, exist_ok=True)
    blob = encrypt(key.encode("ascii"), hub_secret(), subject)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".apikey-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(blob)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, p)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _drop(p: Path) -> bool:
    if p.exists() or p.is_symlink():
        p.unlink()
        return True
    return False


def _same(candidate, stored: Optional[str], decoy: str) -> bool:
    """Tiempo constante; sin key guardada compara igualmente con un señuelo."""
    cand = candidate.encode("utf-8", "replace") if isinstance(candidate, str) else b""
    ok = hmac.compare_digest(cand, (stored or decoy).encode())
    return bool(stored) and ok


# ---- key del usuario ----
def _file(username: str) -> Path:
    return user_dir(username) / FILE


def get(username: str) -> Optional[str]:
    """La key en claro, o None si no hay o no se puede descifrar (fichero manipulado o secreto distinto)."""
    return _load(_file(username), user_id(username), is_well_formed)


def create(username: str) -> str:
    """Genera una key nueva (invalida la anterior, si la había) y la guarda cifrada de forma atómica, 0600."""
    key = new_key()
    _store(_file(username), user_id(username), key)
    return key


def revoke(username: str) -> bool:
    return _drop(_file(username))


def verify(username: str, candidate) -> bool:
    """¿Es `candidate` la key vigente de `username`? Tiempo constante; sin key hace igualmente una comparación
    (con un valor señuelo) para no distinguir «no hay key» de «key equivocada»."""
    return _same(candidate, get(username), PREFIX + "x" * 43)


# ---- key de dispositivo http (una por dispositivo, en <carpeta del usuario>/devices/<id>.enc) ----
# El sujeto cifrado es `<id de usuario>/<id de dispositivo>`: un fichero copiado a otro dispositivo o usuario no
# descifra. La key identifica al dispositivo (no hace falta `?device=`) y solo vale para él.
def _dev_file(username: str, device: str) -> Path:
    if not isinstance(device, str) or not DEVICE_ID_RE.fullmatch(device):
        raise ValueError("id de dispositivo inválido")
    return user_dir(username) / DEVICE_DIR / f"{device}.enc"


def _dev_subject(username: str, device: str) -> str:
    return f"{user_id(username)}/{device}"


def device_get(username: str, device: str) -> Optional[str]:
    return _load(_dev_file(username, device), _dev_subject(username, device), is_well_formed_device)


def device_create(username: str, device: str) -> str:
    """Key nueva para el dispositivo (invalida la anterior, si la había)."""
    key = new_key(DEVICE_PREFIX)
    _store(_dev_file(username, device), _dev_subject(username, device), key)
    return key


def device_revoke(username: str, device: str) -> bool:
    return _drop(_dev_file(username, device))


def device_match(username: str, devices, candidate) -> Optional[str]:
    """Id del dispositivo, de entre `devices`, cuya key es `candidate`; None si ninguna. Recorre SIEMPRE todos (sin
    salida temprana) con comparación en tiempo constante, y con una entrada mal formada hace el mismo trabajo."""
    found = None
    for dev in devices:
        try:
            stored = device_get(username, dev)
        except ValueError:
            stored = None
        if _same(candidate, stored, DEVICE_PREFIX + "x" * 43) and found is None:
            found = dev
    return found


def device_prune(username: str, keep) -> list:
    """Borra las keys de dispositivo cuyo id no está en `keep` (dispositivos borrados o que ya no son `http`).
    Devuelve los ids borrados."""
    d = user_dir(username) / DEVICE_DIR
    keep = set(keep)
    gone = []
    if d.is_dir():
        for f in d.iterdir():
            if f.suffix == ".enc" and f.stem not in keep:
                _drop(f)
                gone.append(f.stem)
    return sorted(gone)
