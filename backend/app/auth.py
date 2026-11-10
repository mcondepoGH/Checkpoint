"""Login con bcrypt, sesiones en memoria y límite de intentos por IP."""
import hmac
import os
import secrets
import threading
import time
from typing import Dict, Optional, Tuple

import bcrypt

from . import settings


FAIL_FORGET = 3600  # s sin fallos (tras el fin del bloqueo) para olvidar los de una IP


class Auth:
    """Usuario y contraseña en claro (del entorno). La contraseña se hashea con bcrypt en
    memoria al construir; el claro no se guarda ni se escribe a disco ni se loguea."""

    def __init__(self, user: str, password: str, session_hours: float = None, clock=time.time,
                 rounds: int = 12):
        if not user or not password:
            raise RuntimeError("Faltan CHECKPOINT_USER / CHECKPOINT_PASSWORD")
        self.user = user
        self.pw_hash = bcrypt.hashpw(password.encode()[:72], bcrypt.gensalt(rounds))
        self.ttl = (session_hours if session_hours is not None else settings.SESSION_HOURS) * 3600
        self.clock = clock
        self.sessions: Dict[str, float] = {}
        self.fails: Dict[str, Tuple[int, float]] = {}  # ip -> (n, bloqueado hasta)
        # Misma mecánica para los fallos de API key (/api/hook/*), con contador propio: un lanzador mal configurado
        # no debe bloquear el login web de esa IP.
        self.hook_fails: Dict[str, Tuple[int, float]] = {}
        self.lock = threading.Lock()
        # hash señuelo para igualar tiempos con usuario inexistente
        self._dummy = bcrypt.hashpw(b"x", bcrypt.gensalt(rounds=4))

    @classmethod
    def from_env(cls, env=None, **kw) -> "Auth":
        env = os.environ if env is None else env
        return cls(settings.env("USER", "", env), settings.env("PASSWORD", "", env), **kw)

    def wait_time(self, ip: str, bucket: Optional[Dict[str, Tuple[int, float]]] = None) -> int:
        bucket = self.fails if bucket is None else bucket
        with self.lock:
            n, until = bucket.get(ip, (0, 0.0))
        return max(0, int(until - self.clock() + 0.999))

    def _register_fail(self, bucket: Dict[str, Tuple[int, float]], ip: str):
        with self.lock:
            # Poda: una IP sin fallos ni bloqueo en la última hora vuelve a empezar de cero (el mapa no crece sin fin).
            now = self.clock()
            for k in [k for k, (_n, until) in bucket.items() if until + FAIL_FORGET < now]:
                del bucket[k]
            n = bucket.get(ip, (0, 0.0))[0] + 1
            delay = 0 if n < 3 else min(2 ** (n - 3) * 5, 900)  # 5s,10s,20s... máx 15 min
            bucket[ip] = (n, self.clock() + delay)

    def hook_wait(self, ip: str) -> int:
        return self.wait_time(ip, self.hook_fails)

    def hook_fail(self, ip: str):
        self._register_fail(self.hook_fails, ip)

    def hook_ok(self, ip: str):
        with self.lock:
            self.hook_fails.pop(ip, None)

    def login(self, ip: str, user: str, password: str) -> Optional[str]:
        """Devuelve token o None. Lanza PermissionError(segundos) si está bloqueada la IP."""
        w = self.wait_time(ip)
        if w > 0:
            raise PermissionError(w)
        ok_user = hmac.compare_digest(user.encode(), self.user.encode())
        try:
            ok_pw = bcrypt.checkpw(password.encode()[:72], self.pw_hash if ok_user else self._dummy)
        except ValueError:
            ok_pw = False
        if ok_user and ok_pw:
            with self.lock:
                self.fails.pop(ip, None)
                tok = secrets.token_urlsafe(32)
                self.sessions[tok] = self.clock() + self.ttl
            return tok
        self._register_fail(self.fails, ip)
        return None

    def valid(self, token: Optional[str]) -> bool:
        if not token:
            return False
        with self.lock:
            exp = self.sessions.get(token)
            if exp is None:
                return False
            if exp < self.clock():
                del self.sessions[token]
                return False
            return True

    def logout(self, token: Optional[str]):
        with self.lock:
            self.sessions.pop(token or "", None)
