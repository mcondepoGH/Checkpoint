"""Vinculación de dispositivos por solicitud y código (sin FastAPI).

Flujo: el dispositivo pide acceso SIN key (`create`) y recibe un código de 6 dígitos (para enseñárselo al usuario) y un
secreto de solicitud (solo lo conoce él). El usuario, con sesión, compara el código y acepta (`accept`: crea el
dispositivo `http` en config.yaml si no existe) o rechaza (`reject`). El dispositivo consulta (`status`) con su secreto
y, aceptada, recibe UNA vez su key `ckd_` (se genera en ese momento, no antes) y la solicitud se borra.

Todo vive en memoria (se pierde al reiniciar; el dispositivo vuelve a pedir). Reloj inyectable para los tests.
Nada de aquí escribe secretos, keys ni códigos en logs."""

import hashlib
import hmac
import logging
import secrets
import threading
import time
import unicodedata
from typing import Callable, Dict, List, Optional

from ..config.models import RESERVED_SLUGS, Device, OSES, name_error, validate_config
from ..config.store import Conflict, ConfigStore, InvalidConfig
from ..core.errors import ApiError
from ..users import apikey

api_log = logging.getLogger("checkpoint.api")  # DEBUG: detalle por endpoint (sin secretos)

TTL_S = 600  # caducidad de una solicitud: 10 minutos
MAX_PENDING = 10  # solicitudes pendientes a la vez en todo el hub
MAX_PENDING_PER_IP = 3  # ... y por IP
MAX_REQUESTS_PER_IP = 5  # solicitudes que una IP puede crear por ventana (se cuentan aunque ya no estén pendientes)
WINDOW_S = 600  # ventana del límite anterior
MAX_CODE_TRIES = 3  # códigos equivocados al aceptar antes de anular la solicitud
SAVE_TRIES = 3  # reintentos si config.yaml cambia mientras se acepta
SECRET_BYTES = 32
_DUMMY = hashlib.sha256(b"pairing-dummy").digest()  # comparación señuelo: misma ruta con id desconocido


class _Req:
    __slots__ = ("id", "name", "os", "code", "secret_hash", "ip", "expires", "state", "device", "tries")

    def __init__(self, id, name, os, code, secret_hash, ip, expires):
        self.id, self.name, self.os, self.code, self.secret_hash = id, name, os, code, secret_hash
        self.ip, self.expires = ip, expires
        self.state = "pending"  # pending | accepted | rejected
        self.device: Optional[str] = None
        self.tries = 0


def id_prefix(name: str) -> str:
    """Prefijo legible del id (igual que `idPrefix` de `frontend/.../draft.js`): parte ASCII del nombre, minúsculas,
    `[a-z0-9_-]`, máx. 40, o `device`."""
    base = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    out, prev = [], False
    for ch in base:
        if ch.isalnum() and ch.isascii() or ch in "_-":
            out.append(ch)
            prev = False
        elif not prev:
            out.append("-")
            prev = True
    return "".join(out)[:40].strip("-_") or "device"


def _hash(secret: str) -> bytes:
    return hashlib.sha256(secret.encode()).digest()


class PairingService:
    def __init__(self, store: ConfigStore, cfg: Callable, user: str, clock: Callable[[], float] = time.time):
        self._store, self._cfg, self._user, self._clock = store, cfg, user, clock
        self._lock = threading.Lock()
        self._reqs: Dict[str, _Req] = {}
        self._hits: Dict[str, List[float]] = {}  # ip -> instantes de sus solicitudes recientes

    # ---- mantenimiento ----
    def purge(self):
        """Quita las caducadas y poda el contador por IP. Lo llama el scheduler y cada operación."""
        with self._lock:
            self._purge()

    def _purge(self):
        now = self._clock()
        for k in [k for k, r in self._reqs.items() if r.expires <= now]:
            del self._reqs[k]
        for ip in list(self._hits):
            self._hits[ip] = [t for t in self._hits[ip] if t + WINDOW_S > now]
            if not self._hits[ip]:
                del self._hits[ip]

    def count(self) -> int:
        with self._lock:
            self._purge()
            return len(self._reqs)

    # ---- dispositivo (público) ----
    def create(self, name, os_, ip: str) -> dict:
        err = name_error(name)
        if err:
            raise ApiError(400, "err.pairing.name_invalid", cause=err)
        if os_ not in OSES or not isinstance(os_, str):
            raise ApiError(400, "err.pairing.os_invalid", options=", ".join(OSES))
        with self._lock:
            self._purge()
            now = self._clock()
            hits = self._hits.get(ip, [])
            if len(hits) >= MAX_REQUESTS_PER_IP:
                wait = max(1, int(hits[0] + WINDOW_S - now + 0.999))
                raise ApiError(429, "err.pairing.too_many_requests", headers={"Retry-After": str(wait)}, seconds=wait)
            mine = sum(1 for r in self._reqs.values() if r.ip == ip and r.state == "pending")
            if mine >= MAX_PENDING_PER_IP:
                raise ApiError(429, "err.pairing.too_many_pending")
            pending = [r for r in self._reqs.values() if r.state == "pending"]
            if len(pending) >= MAX_PENDING:
                wait = max(1, int(min(r.expires for r in pending) - now + 0.999))
                raise ApiError(503, "err.pairing.busy", headers={"Retry-After": str(wait)}, seconds=wait)
            used = {r.code for r in pending}
            while True:
                code = f"{secrets.randbelow(1_000_000):06d}"
                if code not in used:
                    break
            rid = secrets.token_urlsafe(12)
            secret = secrets.token_urlsafe(SECRET_BYTES)
            self._reqs[rid] = _Req(rid, name, os_, code, _hash(secret), ip, now + TTL_S)
            self._hits[ip] = hits + [now]
        api_log.debug("pairing: solicitud %s creada ip=%s", rid, ip)
        return {"id": rid, "code": code, "secret": secret, "expires_in": TTL_S}

    def status(self, rid: str, secret: Optional[str]) -> Optional[dict]:
        """Estado de la solicitud, o None si el id o el secreto no valen (el llamador responde un 404 uniforme y cuenta
        el fallo). Con `accepted` entrega la key una sola vez y borra la solicitud; `rejected` también se borra."""
        with self._lock:
            self._purge()
            r = self._reqs.get(rid)
            given = _hash(secret if isinstance(secret, str) else "")
            ok = hmac.compare_digest(given, r.secret_hash if r else _DUMMY)
            if r is None or not ok:
                return None
            if r.state == "pending":
                return {"status": "pending", "expires_in": max(0, int(r.expires - self._clock() + 0.999))}
            del self._reqs[rid]  # una sola entrega
            if r.state == "rejected":
                return {"status": "rejected"}
            device = r.device
        # Fuera del lock de solicitudes: el disco. Si el dispositivo ya no es `http`, es como si no existiera.
        try:
            http_ids = [i for i, d in self._cfg().devices.items() if d.http]
        except ApiError:
            http_ids = []
        if device not in http_ids:
            return None
        key = apikey.device_create(self._user, device)  # regenera si había: la anterior deja de valer aquí
        api_log.debug("pairing: solicitud %s entregada dispositivo=%s", rid, device)
        return {"status": "accepted", "device": device, "key": key}

    # ---- usuario (sesión) ----
    def pending(self) -> List[dict]:
        try:
            devices = self._cfg().devices
        except ApiError:
            devices = {}
        by_name = {d.name.casefold(): d for d in devices.values()}
        with self._lock:
            self._purge()
            now = self._clock()
            out = []
            for r in sorted((r for r in self._reqs.values() if r.state == "pending"), key=lambda r: r.expires):
                d = by_name.get(r.name.casefold())
                out.append(
                    {
                        "id": r.id,
                        "name": r.name,
                        "os": r.os,
                        "code": r.code,
                        "ip": r.ip,
                        "expires_in": max(0, int(r.expires - now + 0.999)),
                        "existing": "none" if d is None else ("http" if d.http else "other"),
                    }
                )
            return out

    def _pending_req(self, rid: str) -> _Req:
        r = self._reqs.get(rid)
        if r is None:
            raise ApiError(404, "err.pairing.request_unknown")
        if r.state != "pending":
            raise ApiError(409, "err.pairing.not_pending")
        return r

    def reject(self, rid: str) -> dict:
        with self._lock:
            self._purge()
            self._pending_req(rid).state = "rejected"
        api_log.debug("pairing: solicitud %s rechazada", rid)
        return {"id": rid, "rejected": True}

    def accept(self, rid: str, code) -> dict:
        with self._lock:
            self._purge()
            r = self._pending_req(rid)
            if not (isinstance(code, str) and hmac.compare_digest(code.encode(), r.code.encode())):
                r.tries += 1
                left = max(0, MAX_CODE_TRIES - r.tries)
                if left == 0:
                    r.state = "rejected"  # demasiados intentos: la solicitud queda anulada
                raise ApiError(400, "err.pairing.code_mismatch", remaining=left)
            device, created = self._ensure_device(r)
            r.state, r.device = "accepted", device
        api_log.debug("pairing: solicitud %s aceptada dispositivo=%s creado=%s", rid, device, created)
        return {"id": rid, "device": device, "name": self._cfg().devices[device].name, "created": created}

    def _ensure_device(self, r: _Req):
        """(id, creado). Reutiliza un dispositivo `http` con ese nombre; uno no-http con ese nombre es 409.
        El alta pasa por `ConfigStore.save` (versión base, validación completa, copia de seguridad, YAML con
        comentarios), igual que `PUT /api/config`; si el fichero cambia a mitad, reintenta."""
        for _ in range(SAVE_TRIES):
            snap_cfg = self._cfg()  # 500 err.main.config_file_invalid si el fichero es inválido
            version = self._store.snapshot().version
            for did, d in snap_cfg.devices.items():
                if d.name.casefold() == r.name.casefold():
                    if not d.http:
                        raise ApiError(409, "err.pairing.device_not_http", name=r.name)
                    return did, False
            did = self._new_id(snap_cfg, r.name)
            data = snap_cfg.model_dump(exclude_none=True)
            data.setdefault("devices", {})[did] = Device(name=r.name, http=True, os=r.os).model_dump(exclude_none=True)
            cfg, errors = validate_config(data)
            if errors:
                raise InvalidConfig(errors)
            try:
                self._store.save(version, cfg)
            except Conflict:
                continue
            return did, True
        raise ApiError(409, "err.main.config_changed")

    @staticmethod
    def _new_id(cfg, name: str) -> str:
        taken = {i.casefold() for i in cfg.devices} | set(RESERVED_SLUGS)
        while True:
            did = f"{id_prefix(name)}-{secrets.token_hex(4)}"
            if did.casefold() not in taken:
                return did
