"""Baseline: huella que cada participante tenía tras la última sync completa."""
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional


def _state_path(data_dir: Path, game: str) -> Path:
    return Path(data_dir) / "state" / f"{game}.json"


def load_baseline(data_dir: Path, game: str) -> Dict[str, Optional[str]]:
    """{origen: hash|None}. None = estaba vacío. Sin fichero o ilegible = sin baseline (comportamiento seguro)."""
    try:
        raw = json.loads(_state_path(data_dir, game).read_text())
        base = raw["base"]
        if isinstance(base, dict) and all(v is None or isinstance(v, str) for v in base.values()):
            return dict(base)
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return {}


def save_baseline(data_dir: Path, game: str, updates: Dict[str, Optional[str]]) -> None:
    """Fusiona `updates` (origen -> hash) en el baseline. Escritura atómica."""
    p = _state_path(data_dir, game)
    p.parent.mkdir(parents=True, exist_ok=True)
    base = load_baseline(data_dir, game)
    base.update(updates)
    tmp = p.with_name(f".{p.name}.tmp")
    tmp.write_text(json.dumps({"base": base, "updated": datetime.now().isoformat(timespec="seconds")}))
    os.replace(tmp, p)
