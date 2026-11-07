"""Detección de nuevas versiones (solo lectura): consulta las Releases públicas de GitHub.
Canal «stable» (por defecto): solo Releases normales. Canal «beta»: también pre-releases (nunca borradores).

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
_SEMVER_RE = re.compile(r"^v?(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+[0-9A-Za-z.-]+)?$")
CHANNELS = ("stable", "beta")
DEFAULT_CHANNEL = "stable"


def normalize_channel(v) -> str:
    """Valor desconocido -> 'stable'."""
    v = v.strip().lower() if isinstance(v, str) else ""
    return v if v in CHANNELS else DEFAULT_CHANNEL


def parse_version(s) -> Optional[tuple]:
    """'v1.2.3' -> (1, 2, 3). Pre-releases ('-rc1'), etiquetas no numéricas o más de 3 partes -> None."""
    if not isinstance(s, str):
        return None
    m = _VER_RE.match(s.strip())
    return tuple(int(x or 0) for x in m.groups()) if m else None


def parse_semver(s) -> Optional[tuple]:
    """'v1.2.3-rc.1+meta' -> clave ordenable, o None. Orden semver 2.0: núcleo numérico; a igual núcleo, una
    pre-release es MENOR que la estable; entre pre-releases se comparan sus identificadores separados por
    punto (numéricos como número y menores que los alfanuméricos, que van en orden ASCII; menos campos es
    menor si el resto coincide). Los numéricos con ceros a la izquierda no son válidos. La build (+x) se ignora."""
    if not isinstance(s, str):
        return None
    m = _SEMVER_RE.match(s.strip())
    if not m:
        return None
    core = tuple(int(x or 0) for x in m.groups()[:3])
    pre = m.group(4)
    if pre is None:
        return core, 1, ()
    ids = []
    for i in pre.split("."):
        if i.isdigit():
            if len(i) > 1 and i[0] == "0":
                return None
            ids.append((0, int(i), ""))
        else:
            ids.append((1, 0, i))
    return core, 0, tuple(ids)


def format_semver(s) -> Optional[str]:
    """Versión canónica 'X.Y.Z[-pre]' (sin 'v' ni build), o None si no es válida."""
    key = parse_semver(s)
    if key is None:
        return None
    m = _SEMVER_RE.match(s.strip())
    out = ".".join(map(str, key[0]))
    return out + "-" + m.group(4) if m.group(4) else out


def _version_files():
    forced = os.environ.get("CHECKPOINT_VERSION_FILE")
    if forced:
        return [Path(forced)]
    here = Path(__file__).resolve()
    # Docker: /app/VERSION (junto a app/). Nativo: VERSION en la raíz del repo.
    return [here.parents[1] / "VERSION", here.parents[2] / "VERSION"]


def installed_version() -> str:
    """Única fuente de verdad: el fichero VERSION. Admite sufijo de pre-release (0.5.0-rc.1). Sin fichero o valor no válido (modo desarrollo) -> 'desconocida'."""
    for f in _version_files():
        try:
            raw = f.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        return format_semver(raw) or UNKNOWN
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


def pick_latest(releases, channel: str = DEFAULT_CHANNEL) -> Optional[dict]:
    """Versión más alta ofrecible. stable: sin borradores ni pre-releases (marcadas o por sufijo del tag).
    beta: también pre-releases; gana la más alta de todas (0.5.0 > 0.5.0-rc.2 > 0.5.0-rc.1)."""
    beta = normalize_channel(channel) == "beta"
    best, best_k = None, None
    for r in releases or []:
        if not isinstance(r, dict) or r.get("draft"):
            continue
        k = parse_semver(r.get("tag_name"))
        if k is None:
            continue
        pre = bool(r.get("prerelease")) or k[1] == 0
        if pre and not beta:
            continue
        if best_k is None or k > best_k:
            best, best_k = r, k
    if not best:
        return None
    url = best.get("html_url")
    return {"version": format_semver(best["tag_name"]),
            "prerelease": bool(best.get("prerelease")) or best_k[1] == 0,
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

    def channel(self) -> str:
        v = self._read(SETTINGS_FILE).get("channel")
        return v if v in CHANNELS else normalize_channel(settings.UPDATE_CHANNEL)

    def _merge_settings(self, **kv):
        cur = self._read(SETTINGS_FILE)
        cur.update(kv)
        self._write(SETTINGS_FILE, cur)

    def set_enabled(self, value: bool):
        self._merge_settings(enabled=bool(value))

    def set_channel(self, value: str):
        """Valor desconocido -> ValueError (la API responde 422). Cambiar de canal invalida la caché
        (la clave de la caché incluye el canal)."""
        if value not in CHANNELS:
            raise ValueError("canal no válido")
        self._merge_settings(channel=value)

    # ---- estado ----
    @staticmethod
    def _same(c, repo, channel) -> bool:
        # Una caché sin «channel» (fase 1) era del canal estable.
        return bool(c) and c.get("repo") == repo and c.get("channel", DEFAULT_CHANNEL) == channel

    def _do_fetch(self, repo, channel, now):
        old = self._cache if self._same(self._cache, repo, channel) else {}
        try:
            latest = pick_latest((self._fetch or fetch_releases)(repo), channel)
            self._cache = {"repo": repo, "channel": channel, "attempt_at": now, "checked_at": now, "ok": True, "latest": latest}
        except Exception:  # red caída, límite de GitHub, JSON roto...: silencioso, se conserva lo anterior
            self._cache = {"repo": repo, "channel": channel, "attempt_at": now, "checked_at": old.get("checked_at"), "ok": False,
                           "latest": old.get("latest")}
        self._write(CACHE_FILE, self._cache)

    def state(self, refresh: bool = False) -> dict:
        actual = installed_version()
        base = {"actual": actual, "ultima": None, "hay_actualizacion": False, "notas": "", "url": None,
                "comprobado_en": None, "error": None, "habilitado": self.enabled(), "repo": repo_name(),
                "canal": self.channel(), "prerelease": False}
        if not base["habilitado"]:
            return base
        with self._lock:
            repo, channel, now = base["repo"], base["canal"], self.clock()
            if self._cache is None:
                self._cache = self._read(CACHE_FILE) or {}
            c = self._cache
            known = self._same(c, repo, channel) and isinstance(c.get("attempt_at"), (int, float))
            age = now - c["attempt_at"] if known else None
            if refresh and known and age < MIN_REFRESH:
                base["limitado"] = True
            else:
                ttl = settings.UPDATE_CACHE_HOURS * 3600 if c.get("ok") else RETRY_AFTER
                if refresh or not known or age >= ttl or age < 0:
                    self._do_fetch(repo, channel, now)
            c = self._cache if self._same(self._cache, repo, channel) else {}
        latest = c.get("latest") or {}
        base["ultima"] = latest.get("version")
        base["notas"] = latest.get("notes") or ""
        base["url"] = latest.get("url")
        base["prerelease"] = bool(latest.get("prerelease"))
        base["comprobado_en"] = _iso(c.get("checked_at"))
        base["error"] = None if c.get("ok", True) else "no se pudo comprobar"
        a, u = parse_semver(actual), parse_semver(base["ultima"])
        base["hay_actualizacion"] = bool(a and u and u > a)
        return base
