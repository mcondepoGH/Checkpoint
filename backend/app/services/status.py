"""Último estado de sync de cada juego (ficheros `DATA_DIR/status/<id>.json`). Sin FastAPI."""

import json
import logging

from ..core import settings

api_log = logging.getLogger("checkpoint.api")  # DEBUG: detalle por endpoint (sin secretos)


def read_statuses(games: dict) -> dict:
    """{id del juego: estado}. `games`: los de la config vigente (vacío si no se puede leer), para poner el nombre actual."""
    out = {}
    sd = settings.DATA_DIR / "status"
    if sd.is_dir():
        for f in sd.glob("*.json"):
            try:
                st = json.loads(f.read_text())
                # El fichero se llama como el id del juego: esa es la clave y el valor de "game".
                st["game"] = f.stem
                # La UI pinta `name`: siempre el nombre actual de la config (nunca el id).
                if f.stem in games and games[f.stem].name:
                    st["name"] = games[f.stem].name
                elif st.get("name") in (None, "", f.stem):
                    st.pop("name", None)
                out[f.stem] = st
            except Exception as e:
                api_log.debug("status: no se pudo leer %s: %s", f.name, type(e).__name__)
    api_log.debug("status: %d juegos con estado", len(out))
    return out
