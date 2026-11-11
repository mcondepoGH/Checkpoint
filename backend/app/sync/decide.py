"""Decisión pura de quién manda en una sync y resolución de conflictos."""
from typing import Callable, Dict, List, Optional

from .errors import SyncAbort
from .fingerprint import Fingerprint

# Diferencia de mtime por debajo de la cual no se puede decir cuál es "el más reciente" (deriva de reloj).
CLOCK_TOLERANCE = 2


def _prefer_device(keys: List[str]) -> str:
    """Entre contenidos idénticos, el origen real es un dispositivo antes que el hub."""
    return next((k for k in keys if k != "hub"), keys[0])


def decide(fps: Dict[str, Fingerprint], base: Dict[str, Optional[str]]) -> dict:
    """Decide qué participantes (dispositivos en línea + 'hub') mandan. Función pura.

    Devuelve {"kind": "same"|"winner"|"conflict", "winner": clave, "sides": [claves], "reason": str}.
    `base[d]` = lo que el dispositivo d tenía (y el hub, igual) en su última sync; `base["hub"]` = lo que el hub
    tenía tras la última escritura. Con baseline completo:
    - un dispositivo cambió si su hash actual != su baseline; el hub cambió por fuera (p. ej. restaurar una
      versión) si hash != base["hub"];
    - un dispositivo que cambió sobre una base que el hub ya superó compite con el hub (conflicto);
    - si compite un único contenido, gana; si compiten varios distintos, conflicto; si nadie cambió, el hub
      (estado más reciente sincronizado) actualiza a los dispositivos rezagados.
    Sin baseline y contenidos distintos con datos -> conflicto (nunca se decide por mtime). Un lado vacío nunca
    gana a uno con datos (se rellena). Sin baseline y los dos dispositivos coinciden: el hub está desfasado.
    """
    if len({fp.hash for fp in fps.values()}) == 1:
        return {"kind": "same"}
    nonempty = [k for k, fp in fps.items() if not fp.empty]
    if len({fps[k].hash for k in nonempty}) == 1:
        return {"kind": "winner", "winner": _prefer_device(nonempty)}
    if all(k in base for k in fps):
        devs = [k for k in fps if k != "hub"]
        hub_h = fps["hub"].hash
        changed = [k for k in devs if not fps[k].empty and fps[k].hash != base[k]]
        holders = list(changed)
        stale_base = any(hub_h is not None and fps[k].hash != hub_h and base[k] != hub_h for k in changed)
        if not fps["hub"].empty and (stale_base or hub_h != base["hub"]):
            holders.append("hub")
        if holders:
            if len({fps[k].hash for k in holders}) == 1:
                return {"kind": "winner", "winner": _prefer_device(holders)}
            return {"kind": "conflict", "sides": holders, "reason": "both-changed"}
        if not fps["hub"].empty:  # nadie cambió: los dispositivos van por detrás del hub
            return {"kind": "winner", "winner": "hub"}
        return {"kind": "conflict", "sides": nonempty, "reason": "inconsistent"}
    devs = [k for k in nonempty if k != "hub"]
    if len(devs) > 1 and len({fps[k].hash for k in devs}) == 1:
        return {"kind": "winner", "winner": devs[0]}
    return {"kind": "conflict", "sides": nonempty, "reason": "no-baseline"}


def pick_resolution(resolution: str, sides: List[str], fps: Dict[str, Fingerprint],
                    dn: Callable[[str], str] = lambda k: k) -> Optional[str]:
    """Elige ganador para un conflicto. None = indeterminado (relojes demasiado parecidos).
    Lanza SyncAbort si `resolution` no es válida."""
    if resolution == "newest":
        ranked = sorted(sides, key=lambda k: fps[k].mtime, reverse=True)
        top = ranked[0]
        for k in ranked[1:]:
            if fps[k].hash != fps[top].hash and fps[top].mtime - fps[k].mtime < CLOCK_TOLERANCE:
                return None
        return _prefer_device([k for k in ranked if fps[k].hash == fps[top].hash])
    if resolution == "hub":
        name = "hub"
    elif resolution.startswith("device:"):
        name = resolution[len("device:"):]
    else:
        raise SyncAbort("err.sync.resolution_invalid", value=resolution)
    if name not in fps:
        raise SyncAbort("err.sync.side_unavailable", name=dn(name))
    if fps[name].empty:
        raise SyncAbort("err.sync.side_empty", name=dn(name))
    return name


def valid_resolution(value) -> bool:
    return isinstance(value, str) and (value in ("newest", "hub") or
                                       (value.startswith("device:") and len(value) > 7))
