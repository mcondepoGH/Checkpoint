"""Validación de hosts compartida por la config (`config/models.py`) y el bootstrap SSH (`core/bootstrap.py`)."""

import re

# Nombre o IP de un dispositivo: sin espacios ni metacaracteres de shell y sin guion inicial (no se confunde con una opción de ssh).
HOST_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.:\-]{0,252}$")
