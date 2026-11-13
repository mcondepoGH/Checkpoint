"""Resolución segura de rutas relativas que vienen de un dispositivo `http` (manifiesto, subida, bajada).

Las reglas del manifiesto son relajadas a propósito (`C:/x`, `a;b`, `'`, `&`, `:` valen como relativas, para que un save
iguale al del hub), así que NO bastan cuando la ruta se usa para leer o ESCRIBIR en disco: aquí se revalida cada vez."""

from pathlib import Path

from .fingerprint import ManifestError, _manifest_rel


class UnsafePath(ValueError):
    """La ruta no es una ruta relativa segura dentro de la raíz."""


def resolve_inside(root: Path, rel) -> Path:
    """Ruta absoluta de `rel` (relativa a `root`) tras normalizarla (`\\` -> `/`) y comprobarla: sin `..`, sin ruta
    absoluta, sin NUL, sin vacíos, sin ningún componente existente que sea un enlace simbólico (nunca se sigue uno)
    y con la ruta resuelta DENTRO de `root`. Lanza UnsafePath si falla. No crea nada."""
    try:
        norm = _manifest_rel(rel)
    except ManifestError:
        raise UnsafePath("ruta no relativa o con `..`") from None
    root = Path(root).resolve()
    cur = root
    try:
        for part in norm.split("/"):
            cur = cur / part
            if cur.is_symlink():
                raise UnsafePath("enlace simbólico")
        target = (root / norm).resolve()
    except (OSError, RuntimeError, ValueError):  # nombre demasiado largo, bucle de enlaces...
        raise UnsafePath("ruta no resoluble") from None
    if target == root or not target.is_relative_to(root):
        raise UnsafePath("fuera de la raíz")
    return root / norm
