"""Registro persistente de ciclos de la sincronización automática.

Un fichero JSONL (DATA_DIR/scheduler-history.jsonl), una entrada por línea. Retención acotada por número
(MAX_ENTRIES) y por antigüedad (MAX_DAYS). Las líneas ilegibles se ignoran y se descartan al reescribir.
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
MAX_ENTRIES = 200
MAX_DAYS = 30
MSG_LEN = 300
RESULTS = {"ok", "error", "aborted", "skipped", "conflict", "partial"}
TRIGGERS = {"scheduled", "startup", "config-change"}

_lock = threading.Lock()


def path():
    return settings.DATA_DIR / FILE


def short(msg, n: int = MSG_LEN) -> str:
    s = redact(str(msg or "")).replace("\n", " ").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def make_entry(started: datetime, duration: float, trigger: str, result: str, games: dict, message: str = "") -> dict:
    """`games`: {juego: {"result": ..., "message": ...}}. Valores desconocidos se normalizan."""
    gs = {}
    for g, d in games.items():
        r = d.get("result") if isinstance(d, dict) else d
        gs[str(g)] = {"result": r if r in RESULTS else "error",
                      "message": short(d.get("message", "")) if isinstance(d, dict) else ""}
    return {"id": uuid.uuid4().hex[:12],
            "started": started.astimezone(timezone.utc).isoformat(timespec="seconds"),
            "duration": round(max(0.0, float(duration)), 1),
            "trigger": trigger if trigger in TRIGGERS else "scheduled",
            "result": result if result in RESULTS else "error",
            "games": gs, "message": short(message)}


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


def append(entry: dict, now: Optional[datetime] = None) -> None:
    """Añade la entrada y aplica la retención. Reescritura atómica (tmp + os.replace)."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=MAX_DAYS)
    with _lock:
        entries, _bad = _read_all()
        entries.append(entry)
        entries = [e for e in entries if (_parse(e["started"]) or now) >= cutoff][-MAX_ENTRIES:]
        p = path()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(f".{p.name}.tmp")
        tmp.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries), encoding="utf-8")
        os.replace(tmp, p)


def read(limit: int = 50) -> List[dict]:
    """Más reciente primero."""
    with _lock:
        entries, _bad = _read_all()
    return list(reversed(entries))[: max(0, limit)]
