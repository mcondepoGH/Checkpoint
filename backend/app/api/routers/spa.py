"""Web (SPA): estáticos del build del frontend y `index.html` para el resto de rutas. Catch-all: se monta el último."""
from fastapi.responses import FileResponse

from ...core import settings
from ...core.errors import ApiError
from ..deps import public_router

# index.html nunca se cachea: así un despliegue nuevo se ve al recargar (los assets con hash sí se cachean).
NO_CACHE = {"Cache-Control": "no-cache"}
router = public_router()


# Los estáticos no contienen secretos; solo así se puede pintar la pantalla de login.
@router.get("/{path:path}")
def spa(path: str):
    if path.startswith("api/"):
        raise ApiError(404, "err.main.not_found")
    root = settings.STATIC_DIR.resolve()
    f = (root / path).resolve()
    if path and f.is_file() and root in f.parents:
        # Los assets de Vite llevan hash en el nombre: cacheables para siempre. El resto, a revalidar.
        if "assets" in f.relative_to(root).parts[:1]:
            return FileResponse(f, headers={"Cache-Control": "public, max-age=31536000, immutable"})
        return FileResponse(f, headers=NO_CACHE)
    idx = root / "index.html"
    if idx.is_file():
        return FileResponse(idx, headers=NO_CACHE)
    raise ApiError(404, "err.main.frontend_not_built")
