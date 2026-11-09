"""Registro persistente de ciclos de la sincronización automática.

Un fichero JSONL (DATA_DIR/scheduler-history.jsonl), una entrada por línea. Retención acotada por número
(MAX_ENTRIES, fijo: nunca más de 50 en disco ni en la API) y por antigüedad (MAX_DAYS). Las líneas ilegibles se ignoran y se descartan al reescribir.
Nunca guarda secretos: los mensajes pasan por redact() y se truncan."""
import json
import os
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from . import settings
from .redact import redact

FILE = "scheduler-history.jsonl"
MAX_ENTRIES = 50
MAX_DAYS = 30
MSG_LEN = 300
RESULTS = {"ok", "error", "aborted", "skipped", "conflict", "partial"}
TRIGGERS = {"scheduled", "startup", "hook", "hook_closed"}

_lock = threading.Lock()


def path():
    return settings.DATA_DIR / FILE


def short(msg, n: int = MSG_LEN) -> str:
    s = redact(str(msg or "")).replace("\n", " ").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def clean_params(v, n: int = MSG_LEN):
    """Params de un code: cadenas redactadas y truncadas, recursivo (causas anidadas). Nunca guarda secretos."""
    if isinstance(v, str):
        return short(v, n)
    if isinstance(v, dict):
        return {str(k): clean_params(x, n) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [clean_params(x, n) for x in v]
    return v if v is None or isinstance(v, (bool, int, float)) else short(v, n)


def _coded(d: dict, out: dict) -> dict:
    """Si `d` trae `code`, guarda code+params (la UI traduce) y deja `message` vacío; si no, el texto (`message`)."""
    if isinstance(d.get("code"), str) and d["code"]:
        out["code"], out["params"], out["message"] = d["code"], clean_params(d.get("params") or {}), ""
    return out


def make_entry(started: datetime, duration: float, trigger: str, result: str, games: dict, message: str = "",
               code: Optional[str] = None, params: Optional[dict] = None) -> dict:
    """`games`: {id del juego: {"result": ..., "message": ..., "name": ..., "code"?, "params"?}}. Registros nuevos
    llevan `code`+`params` (sin `message`); los antiguos solo `message` y se leen tal cual. Valores desconocidos se normalizan.
    Se guarda el id (clave estable) y el nombre que tenía entonces (legible aunque el juego se renombre o borre)."""
    gs = {}
    for g, d in games.items():
        r = d.get("result") if isinstance(d, dict) else d
        gs[str(g)] = {"result": r if r in RESULTS else "error",
                      "message": short(d.get("message", "")) if isinstance(d, dict) else ""}
        if isinstance(d, dict) and isinstance(d.get("name"), str) and d["name"]:
            gs[str(g)]["name"] = short(d["name"], 64)
        if isinstance(d, dict):
            _coded(d, gs[str(g)])
    entry = {"id": uuid.uuid4().hex[:12],
            "started": started.astimezone(timezone.utc).isoformat(timespec="seconds"),
            "duration": round(max(0.0, float(duration)), 1),
            "trigger": trigger if trigger in TRIGGERS else "scheduled",
            "result": result if result in RESULTS else "error",
            "games": gs, "message": short(message)}
    return _coded({"code": code, "params": params}, entry)


def _valid(e) -> bool:
    return (isinstance(e, dict) and isinstance(e.get("id"), str) and isinstance(e.get("started"), str)
            and isinstance(e.get("games"), dict))


def _read_all() -> tuple:
    """(entradas válidas en orden de fichero, nº de líneas descartadas)."""
    out, bad = [], 0
    try:
        text = path().read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out, bad
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            e = json.loads(line)
        except ValueError:
            bad += 1
            continue
        if _valid(e):
            out.append(e)
        else:
            bad += 1
    return out, bad


def _parse(s) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(s)
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _write(entries: List[dict]) -> None:
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f".{p.name}.tmp")
    tmp.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries), encoding="utf-8")
    os.replace(tmp, p)


def append(entry: dict, now: Optional[datetime] = None) -> None:
    """Añade la entrada y aplica la retención. Reescritura atómica (tmp + os.replace)."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=MAX_DAYS)
    with _lock:
        entries, _bad = _read_all()
        entries.append(entry)
        entries = [e for e in entries if (_parse(e["started"]) or now) >= cutoff][-MAX_ENTRIES:]
        _write(entries)


def annotate(entries: List[dict], games: dict) -> List[dict]:
    """Copia de `entries` donde cada juego lleva `id` (o None) y `name` legibles. `games` = {id: Game} actual.

    Clave = id del juego, `name` guardado (se actualiza al nombre actual si el juego sigue existiendo; si ya
    no existe se muestra el guardado con id None)."""
    out = []
    for e in entries:
        gs = {}
        for key, d in e["games"].items():
            d = dict(d) if isinstance(d, dict) else {"result": d}
            if key in games:
                gid, name = key, games[key].name
            else:
                gid, name = None, d.get("name") or key
            gs[key] = {**d, "id": gid, "name": name}
        out.append({**e, "games": gs})
    return out


def read(limit: int = 50) -> List[dict]:
    """Más reciente primero, como mucho MAX_ENTRIES. Un fichero con más (de una versión anterior) se poda al leer."""
    with _lock:
        entries, _bad = _read_all()
        if len(entries) > MAX_ENTRIES:
            entries = entries[-MAX_ENTRIES:]
            _write(entries)
    return list(reversed(entries))[: max(0, min(limit, MAX_ENTRIES))]
