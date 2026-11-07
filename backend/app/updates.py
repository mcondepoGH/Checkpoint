"""Detección de nuevas versiones (solo lectura): consulta las Releases públicas de GitHub, canal estable.

Nunca descarga ni instala nada. Un fallo de red no es un error para el usuario: se conserva lo último
conocido y se reintenta más tarde. Con la comprobación desactivada no se hace ninguna petición."""
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from . import settings

DEFAULT_REPO = "mcondepoGH/Checkpoint"
UNKNOWN = "desconocida"
TIMEOUT = 5            # s por petición
MIN_REFRESH = 60       # s mínimos entre comprobaciones forzadas
RETRY_AFTER = 900      # s antes de reintentar tras un fallo
NOTES_MAX = 6000       # caracteres de notas que se devuelven
MAX_BODY = 1_000_000   # bytes máximos de respuesta
SETTINGS_FILE = "updates.json"
CACHE_FILE = "update_cache.json"
_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")
_VER_RE = re.compile(r"^v?(\d+)(?:\.(\d+))?(?:\.(\d+))?$")


def parse_version(s) -> Optional[tuple]:
    """'v1.2.3' -> (1, 2, 3). Pre-releases ('-rc1'), etiquetas no numéricas o más de 3 partes -> None."""
    if not isinstance(s, str):
        return None
    m = _VER_RE.match(s.strip())
    return tuple(int(x or 0) for x in m.groups()) if m else None


def _version_files():
    forced = os.environ.get("CHECKPOINT_VERSION_FILE")
    if forced:
        return [Path(forced)]
    here = Path(__file__).resolve()
    # Docker: /app/VERSION (junto a app/). Nativo: VERSION en la raíz del repo.
    return [here.parents[1] / "VERSION", here.parents[2] / "VERSION"]


def installed_version() -> str:
    """Única fuente de verdad: el fichero VERSION. Sin fichero o valor no numérico (modo desarrollo) -> 'desconocida'."""
    for f in _version_files():
        try:
            raw = f.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        v = parse_version(raw)
        return ".".join(map(str, v)) if v else UNKNOWN
    return UNKNOWN


def repo_name() -> str:
    r = (settings.UPDATE_REPO or "").strip()
    return r if _REPO_RE.match(r) and ".." not in r else DEFAULT_REPO


class _HttpsOnly(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not newurl.lower().startswith("https://"):
            raise urllib.error.URLError("redirección no HTTPS rechazada")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _opener():
    return urllib.request.build_opener(_HttpsOnly())


def fetch_releases(repo: str) -> list:
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/releases?per_page=30",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "Checkpoint-update-check"})
    with _opener().open(req, timeout=TIMEOUT) as r:
        data = json.loads(r.read(MAX_BODY))
    if not isinstance(data, list):
        raise ValueError("respuesta inesperada")
    return data


def pick_latest(releases) -> Optional[dict]:
    best, best_v = None, None
    for r in releases or []:
        if not isinstance(r, dict) or r.get("draft") or r.get("prerelease"):
            continue
        v = parse_version(r.get("tag_name"))
        if v is not None and (best_v is None or v > best_v):
            best, best_v = r, v
    if not best:
        return None
    url = best.get("html_url")
    return {"version": ".".join(map(str, best_v)),
            "notes": str(best.get("body") or "")[:NOTES_MAX],
            "url": url if isinstance(url, str) and url.startswith("https://") else None}


def _iso(ts) -> Optional[str]:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds") if ts else None


class UpdateChecker:
    def __init__(self, fetch: Callable = None, clock: Callable[[], float] = time.time):
        self._fetch = fetch  # None -> fetch_releases (resuelto en cada llamada, para poder sustituirlo)
        self.clock = clock
        self._lock = threading.Lock()
        self._cache = None

    # ---- persistencia (todo tolerante a fallos de disco) ----
    def _read(self, name) -> dict:
        try:
            d = json.loads((settings.DATA_DIR / name).read_text())
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def _write(self, name, data):
        try:
            settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
            p = settings.DATA_DIR / name
            tmp = p.with_name(p.name + ".tmp")
            tmp.write_text(json.dumps(data))
            os.replace(tmp, p)
        except OSError:
            pass

    def enabled(self) -> bool:
        v = self._read(SETTINGS_FILE).get("enabled")
        return v if isinstance(v, bool) else bool(settings.UPDATE_CHECK)

    def set_enabled(self, value: bool):
        self._write(SETTINGS_FILE, {"enabled": bool(value)})

    # ---- estado ----
    def _do_fetch(self, repo, now):
        old = self._cache if self._cache and self._cache.get("repo") == repo else {}
        try:
            latest = pick_latest((self._fetch or fetch_releases)(repo))
            self._cache = {"repo": repo, "attempt_at": now, "checked_at": now, "ok": True, "latest": latest}
        except Exception:  # red caída, límite de GitHub, JSON roto...: silencioso, se conserva lo anterior
            self._cache = {"repo": repo, "attempt_at": now, "checked_at": old.get("checked_at"), "ok": False,
                           "latest": old.get("latest")}
        self._write(CACHE_FILE, self._cache)

    def state(self, refresh: bool = False) -> dict:
        actual = installed_version()
        base = {"actual": actual, "ultima": None, "hay_actualizacion": False, "notas": "", "url": None,
                "comprobado_en": None, "error": None, "habilitado": self.enabled(), "repo": repo_name()}
        if not base["habilitado"]:
            return base
        with self._lock:
            repo, now = base["repo"], self.clock()
            if self._cache is None:
                self._cache = self._read(CACHE_FILE) or {}
            c = self._cache
            known = c.get("repo") == repo and isinstance(c.get("attempt_at"), (int, float))
            age = now - c["attempt_at"] if known else None
            if refresh and known and age < MIN_REFRESH:
                base["limitado"] = True
            else:
                ttl = settings.UPDATE_CACHE_HOURS * 3600 if c.get("ok") else RETRY_AFTER
                if refresh or not known or age >= ttl or age < 0:
                    self._do_fetch(repo, now)
            c = self._cache if self._cache.get("repo") == repo else {}
        latest = c.get("latest") or {}
        base["ultima"] = latest.get("version")
        base["notas"] = latest.get("notes") or ""
        base["url"] = latest.get("url")
        base["comprobado_en"] = _iso(c.get("checked_at"))
        base["error"] = None if c.get("ok", True) else "no se pudo comprobar"
        a, u = parse_version(actual), parse_version(base["ultima"])
        base["hay_actualizacion"] = bool(a and u and u > a)
        return base
