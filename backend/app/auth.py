"""Login con bcrypt, sesiones en memoria y límite de intentos por IP."""
import hmac
import os
import secrets
import threading
import time
from typing import Dict, Optional, Tuple

import bcrypt

from . import settings


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
        self.lock = threading.Lock()
        # hash señuelo para igualar tiempos con usuario inexistente
        self._dummy = bcrypt.hashpw(b"x", bcrypt.gensalt(rounds=4))

    @classmethod
    def from_env(cls, env=None, **kw) -> "Auth":
        env = os.environ if env is None else env
        return cls(settings.env("USER", "", env), settings.env("PASSWORD", "", env), **kw)

    def wait_time(self, ip: str) -> int:
        with self.lock:
            n, until = self.fails.get(ip, (0, 0.0))
        return max(0, int(until - self.clock() + 0.999))

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
        with self.lock:
            n = self.fails.get(ip, (0, 0.0))[0] + 1
            delay = 0 if n < 3 else min(2 ** (n - 3) * 5, 900)  # 5s,10s,20s... máx 15 min
            self.fails[ip] = (n, self.clock() + delay)
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
