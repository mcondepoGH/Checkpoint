"""Config en vivo: carga en memoria con detección de cambios externos, guardado con
control de versión optimista, copias de seguridad, diff y serialización (ruamel conserva comentarios)."""
import hashlib
import io
import os
import re
import threading
import time
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import yaml
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from . import settings
from .config import DEFAULT_MAX_VERSIONS, Config, atomic_write, load_yaml, validate_config

MAX_BACKUPS = 10
BACKUP_PREFIX = "config.yaml.bak-"
BACKUP_RE = re.compile(r"^config\.yaml\.bak-(\d{4})-(\d{2})-(\d{2})_(\d{2})(\d{2})(\d{2})$")


class Conflict(Exception):
    """El fichero cambió desde la versión base que envió la UI."""

    def __init__(self, current_version):
        super().__init__("config.yaml cambió desde que lo cargaste")
        self.current_version = current_version


class InvalidConfig(ValueError):
    def __init__(self, errors: Dict[str, str]):
        super().__init__("; ".join(f"{k}: {v}" if k else v for k, v in errors.items()))
        self.errors = errors


def version_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def _now() -> datetime:  # sustituible en tests
    return datetime.now()


@dataclass
class Snapshot:
    version: str
    text: str
    cfg: Optional[Config]
    error: Optional[str]

    def as_dict(self) -> dict:
        return (self.cfg or Config()).model_dump(exclude_none=True)


def parse_text(text: str):
    try:
        data = load_yaml(text)
    except yaml.YAMLError as e:
        return None, f"YAML mal formado: {getattr(e, 'problem', None) or 'error de sintaxis'}"
    cfg, errors = validate_config(data)
    if errors:
        return None, "; ".join(f"{k}: {v}" if k else v for k, v in errors.items())
    return cfg, None


# ---------- serialización (ruamel: conserva comentarios y estilo del fichero actual) ----------
def _yaml() -> YAML:
    y = YAML(typ="rt")
    y.preserve_quotes = True
    y.width = 4096  # rutas largas sin partir
    y.indent(mapping=2, sequence=4, offset=2)
    return y


def _merge(old: Any, new: Any) -> Any:
    if isinstance(new, dict):
        if not isinstance(old, CommentedMap):
            old = CommentedMap()
        for k in [k for k in old if k not in new]:
            del old[k]
        for k, v in new.items():
            if k in old:
                m = _merge(old[k], v)
                if m is not old[k]:
                    old[k] = m
            else:
                old[k] = _merge(None, v)
        return old
    if isinstance(new, list):
        if isinstance(old, CommentedSeq) and len(old) == len(new):
            for i, v in enumerate(new):
                m = _merge(old[i], v)
                if m is not old[i]:
                    old[i] = m
            return old
        seq = CommentedSeq(_merge(None, v) for v in new)
        if all(not isinstance(v, (dict, list)) for v in new):
            seq.fa.set_flow_style()
        return seq
    if old is not None and old == new and isinstance(old, bool) == isinstance(new, bool):
        return old  # conserva el estilo del original (comillas, etc.)
    return new


def render_yaml(current_text: str, cfg: Config) -> str:
    data = cfg.model_dump(exclude_none=True)
    y = _yaml()
    try:
        root = y.load(current_text) if current_text.strip() else None
    except Exception:
        root = None
    if not isinstance(root, CommentedMap):
        root = None
    out = _merge(root, data)
    buf = io.StringIO()
    y.dump(out, buf)
    return buf.getvalue()


# ---------- diff ----------
def _section_diff(old: dict, new: dict) -> dict:
    changed = {}
    for name in old.keys() & new.keys():
        fields = {}
        for k in sorted(old[name].keys() | new[name].keys()):
            a, b = old[name].get(k), new[name].get(k)
            if a != b:
                fields[k] = {"old": a, "new": b}
        if fields:
            changed[name] = fields
    return {"added": sorted(new.keys() - old.keys()), "removed": sorted(old.keys() - new.keys()),
            "changed": changed}


def diff_configs(old: dict, new: dict) -> dict:
    d = {s: _section_diff(old.get(s) or {}, new.get(s) or {}) for s in ("devices", "games")}
    # Ajustes generales (valores sueltos): misma forma que las secciones para reutilizar la vista previa.
    ov, nv = old.get("max_versions", DEFAULT_MAX_VERSIONS), new.get("max_versions", DEFAULT_MAX_VERSIONS)
    # Las secciones van por id (un renombrado es un cambio de `name`, no una baja y un alta); `names` da el
    # nombre visible de cada id (el nuevo si existe; si no, el que tenía).
    d["names"] = {s: {i: (v.get("name") if isinstance(v, dict) and v.get("name") else i)
                      for i, v in {**(old.get(s) or {}), **(new.get(s) or {})}.items()}
                  for s in ("devices", "games")}
    d["general"] = {"added": [], "removed": [],
                    "changed": {"General": {"max_versions": {"old": ov, "new": nv}}} if ov != nv else {}}
    d["empty"] = not any(v["added"] or v["removed"] or v["changed"]
                         for k, v in d.items() if isinstance(v, dict) and k != "names")
    return d


# ---------- store ----------
class ConfigStore:
    def __init__(self):
        self._lock = threading.RLock()
        self._sig = None
        self._snap: Optional[Snapshot] = None

    # rutas leídas al vuelo (los tests cambian settings)
    @property
    def path(self):
        return settings.CONFIG_PATH

    @property
    def backup_dir(self):
        return settings.DATA_DIR / "config-backups"

    def snapshot(self) -> Snapshot:
        """Versión en memoria; recarga solo si el fichero cambió (inodo, tamaño o mtime)."""
        with self._lock:
            try:
                st = self.path.stat()
                sig = (self.path, st.st_ino, st.st_size, st.st_mtime_ns)
            except FileNotFoundError:
                sig = (self.path, None)
            if self._snap is not None and sig == self._sig:
                return self._snap
            try:
                raw = self.path.read_bytes()
            except FileNotFoundError:
                raw = b""
            text = raw.decode("utf-8", errors="replace")
            cfg, err = parse_text(text)
            if err is None and cfg is None:
                cfg = Config()
            self._snap, self._sig = Snapshot(version_of(raw), text, cfg, err), sig
            return self._snap

    def _fresh_version(self) -> str:
        try:
            return version_of(self.path.read_bytes())
        except FileNotFoundError:
            return version_of(b"")

    # ---- guardado ----
    def save(self, base_version: str, cfg: Config) -> dict:
        with self._lock:
            snap = self.snapshot()
            if snap.cfg is not None and snap.version == base_version and snap.cfg == cfg:
                return {"changed": False, "backup": None, "version": snap.version}  # nada que escribir
            return self._write(base_version, render_yaml(snap.text, cfg))

    def _write(self, base_version: str, new_text: str) -> dict:
        snap = self.snapshot()
        if snap.version != base_version or self._fresh_version() != base_version:
            raise Conflict(self._fresh_version())
        if new_text == snap.text:
            return {"changed": False, "backup": None, "version": snap.version}
        backup = self._backup() if self.path.exists() else None
        atomic_write(self.path, new_text)
        return {"changed": True, "backup": backup, "version": self.snapshot().version}

    def restore(self, base_version: str, name: str) -> dict:
        text = self.read_backup(name)
        cfg, err = parse_text(text)
        if err:
            raise InvalidConfig({"": f"la copia no es válida: {err}"})
        with self._lock:
            return self._write(base_version, text)

    # ---- copias ----
    def _backup(self) -> str:
        d = self.backup_dir
        d.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(d, 0o700)
        except OSError:
            pass
        t = _now().replace(microsecond=0)
        names = self._names()
        if names:  # el orden por nombre = orden cronológico: nunca por debajo de la más reciente
            m = BACKUP_RE.match(names[-1])
            t = max(t, datetime(*map(int, m.groups())) + timedelta(seconds=1))
        while True:
            name = BACKUP_PREFIX + t.strftime("%Y-%m-%d_%H%M%S")
            try:
                fd = os.open(d / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                break
            except FileExistsError:
                t += timedelta(seconds=1)
        with os.fdopen(fd, "wb") as f:
            f.write(self.path.read_bytes())
            f.flush()
            os.fsync(f.fileno())
        for old in self._names()[:-MAX_BACKUPS]:
            (d / old).unlink(missing_ok=True)
        return name

    def _names(self) -> List[str]:
        d = self.backup_dir
        if not d.is_dir():
            return []
        return sorted(p.name for p in d.iterdir() if BACKUP_RE.match(p.name) and p.is_file())

    def list_backups(self) -> List[dict]:
        out = []
        for n in reversed(self._names()):
            m = BACKUP_RE.match(n)
            iso = "{}-{}-{}T{}:{}:{}".format(*m.groups())
            out.append({"name": n, "created": iso, "size": (self.backup_dir / n).stat().st_size})
        return out

    def read_backup(self, name: str) -> str:
        if not BACKUP_RE.match(name or ""):
            raise FileNotFoundError(name)
        return (self.backup_dir / name).read_text(encoding="utf-8", errors="replace")


def config_events_gen(store: ConfigStore, interval: float = 1.0, keepalive: float = 15.0,
                      max_ticks: Optional[int] = None, sleep=time.sleep):
    """SSE: emite `config` al conectar y cada vez que cambia la versión del fichero (edición externa incluida)."""
    last, idle, ticks = None, 0.0, 0
    while max_ticks is None or ticks < max_ticks:
        snap = store.snapshot()
        if snap.version != last:
            last, idle = snap.version, 0.0
            yield "event: config\ndata: " + json.dumps({"version": snap.version, "error": snap.error}) + "\n\n"
        elif idle >= keepalive:
            idle = 0.0
            yield ": keepalive\n\n"
        ticks += 1
        sleep(interval)
        idle += interval
