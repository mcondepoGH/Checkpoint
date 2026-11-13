"""API externa (la de la API key, `/api/hook/*`): única parte que sale en el Swagger. Autenticación Bearer, sin cookie
ni Origin. Para añadir un endpoint público nuevo, cuélgalo de este router y documéntalo en `api/docs/examples.py`;
cualquier otro router sale oculto por defecto (`deps.internal_router`)."""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Header, Path, Query, Request
from fastapi.responses import StreamingResponse

from ...services.context import AppContext
from .. import docs
from ...core.errors import ApiError
from ..deps import Principal, get_ctx, hook_any, hook_device, hook_user

api_log = logging.getLogger(
    "checkpoint.api"
)  # DEBUG: una línea por petición /api y detalle por endpoint (sin secretos)

# Todo lo de /api/hook/* cuelga de este router. La autenticación es POR ENDPOINT (no hay dependencia global), porque
# cada ruta acepta una clase de key distinta: `hook_user` (usuario: opened, watches), `hook_any` (ping) o
# `hook_device` (dispositivo http: fingerprint, manifest, files, commit, closed). `test_apidocs` comprueba que
# ninguna ruta de /api/hook queda sin autenticar.
router = APIRouter(prefix="/api/hook", tags=[docs.TAG], responses={401: docs.R401, 429: docs.R429})


@router.get("/ping", **docs.PING)
def hook_ping(p: Principal = Depends(hook_any)):
    api_log.debug("hook ping: usuario=%s dispositivo=%s", p.user, p.device)
    return {"ok": True, "user": p.user, **({"device": p.device} if p.device else {})}


@router.get("/watches", **docs.WATCHES, dependencies=[Depends(hook_user)])
def hook_watches(ctx: AppContext = Depends(get_ctx)):
    """Vigilancias de cierre activas (en memoria): [{game, device, state: waiting|running|settling, since}]. Sin los juegos desactivados."""
    cfg = ctx.cfg()
    w = ctx.hooks.active_watches(cfg)
    api_log.debug("hook watches: %d vigilancias activas", len(w))
    return w


@router.post("/{game}/opened", **docs.OPENED, dependencies=[Depends(hook_user)])
async def hook_opened(
    game: str = Path(description="Id o nombre del juego.", examples=["Mi Juego"]),
    device: Optional[str] = Query(
        None,
        description="Id o nombre del dispositivo donde se "
        "vigila el proceso del juego. Obligatorio si el juego está en "
        "más de un dispositivo.",
        examples=["PC uno"],
    ),
    ctx: AppContext = Depends(get_ctx),
):
    """Aviso «se va a abrir el juego»: sync previo bloqueante con política de conflictos siempre `skip` (ignora la del juego y la del scheduler).
    Tras el aviso (salvo 400/401/404/409) arma la vigilancia de cierre si el juego tiene `process` (`watching`). Un fallo de la sync no es un 5xx: 200 con `outcome` descriptivo."""
    cfg = ctx.cfg()
    game = ctx.game_id(game)  # el 401 ya lo dio la dependencia de key: no se revela si el juego existe
    return await ctx.hooks.opened(cfg, game, device)


@router.post("/{game}/closed", **docs.CLOSED)
def hook_closed(
    game: str = Path(description="Id o nombre del juego.", examples=["Mi Juego"]),
    device: Optional[str] = Query(
        None,
        description="Opcional: la key de dispositivo ya lo identifica. Si se pasa (id o nombre) y no es el de la "
        "key, `403`.",
        examples=["Steam Deck"],
    ),
    p: Principal = Depends(hook_device),
    ctx: AppContext = Depends(get_ctx),
):
    """Aviso «se cerró el juego» de un dispositivo `http`: solo deja constancia en el historial (`hook_closed`); no sincroniza."""
    cfg = ctx.cfg()
    game, device = ctx.hooks.scope(
        cfg, game, device, p.device
    )  # 403 si `?device=` no es el de la key; 404 si el juego no lo incluye
    return ctx.hooks.closed(cfg, game, device)


@router.post("/{game}/fingerprint", **docs.FINGERPRINT)
async def hook_fingerprint(
    request: Request,
    game: str = Path(description="Id o nombre del juego.", examples=["Mi Juego"]),
    device: Optional[str] = Query(
        None,
        description="Opcional: la key de dispositivo ya lo identifica. Si se pasa (id o nombre) y no es el de la "
        "key, `403`.",
        examples=["Steam Deck"],
    ),
    manifest_q: Optional[str] = Query(
        None,
        alias="manifest",
        description="`1` = con `action: download`, añade `hub_manifest` (el de `GET /manifest`, de la misma lectura del "
        "hub que la decisión) para bajar sin otra petición. Otro valor o ausente: la respuesta no cambia.",
        examples=["1"],
    ),
    p: Principal = Depends(hook_device),
    ctx: AppContext = Depends(get_ctx),
):
    """Compara el manifiesto del dispositivo con el hub y dice qué hacer (`upload`, `download`, `none`, `conflict`). Solo escribe la línea base si son iguales."""
    try:
        manifest = await request.json()
    except Exception:
        raise ApiError(400, "err.main.json_body_required") from None
    if not isinstance(manifest, list):
        raise ApiError(400, "err.main.json_body_required")
    cfg = ctx.cfg()
    game, device = ctx.hooks.scope(
        cfg, game, device, p.device
    )  # 403 si `?device=` no es el de la key; 404 si el juego no lo incluye
    return await ctx.hooks.fingerprint(cfg, game, device, manifest, with_manifest=manifest_q == "1")


DEVICE_Q = dict(
    description="Opcional: la key de dispositivo ya lo identifica. Si se pasa (id o nombre) y no es el de la key, `403`.",
    examples=["Steam Deck"],
)


@router.get("/{game}/manifest", **docs.MANIFEST)
async def hook_manifest(
    game: str = Path(description="Id o nombre del juego.", examples=["Mi Juego"]),
    device: Optional[str] = Query(None, **DEVICE_Q),
    p: Principal = Depends(hook_device),
    ctx: AppContext = Depends(get_ctx),
):
    """Manifiesto del hub: qué ficheros (ruta, sha256, tamaño y mtime) debe bajar un dispositivo `http`."""
    cfg = ctx.cfg()
    game, device = ctx.hooks.scope(
        cfg, game, device, p.device
    )  # 403 si `?device=` no es el de la key; 404 si el juego no lo incluye
    return await ctx.hooks.manifest(cfg, game, device)


@router.get("/{game}/files", **docs.DOWNLOAD)
def hook_download(
    game: str = Path(description="Id o nombre del juego.", examples=["Mi Juego"]),
    path: Optional[str] = Query(
        None, description="Ruta del fichero (la del manifiesto del hub).", examples=["slot1/save.dat"]
    ),
    device: Optional[str] = Query(None, **DEVICE_Q),
    range: Optional[str] = Header(
        None, description="`bytes=<inicio>-[<fin>]` o `bytes=-<n>`: un solo rango.", examples=["bytes=1048576-"]
    ),
    p: Principal = Depends(hook_device),
    ctx: AppContext = Depends(get_ctx),
):
    """Descarga un fichero del hub, con `Range` para reanudar."""
    cfg = ctx.cfg()
    game, device = ctx.hooks.scope(
        cfg, game, device, p.device
    )  # 403 si `?device=` no es el de la key; 404 si el juego no lo incluye
    status, headers, body = ctx.hooks.open_download(cfg, game, device, path, range)
    return StreamingResponse(body, status_code=status, headers=headers, media_type="application/octet-stream")


@router.put("/{game}/files", **docs.UPLOAD)
async def hook_upload(
    request: Request,
    game: str = Path(description="Id o nombre del juego.", examples=["Mi Juego"]),
    path: Optional[str] = Query(None, description="Ruta relativa del fichero (con `/`).", examples=["slot1/save.dat"]),
    size: Optional[str] = Query(None, description="Tamaño TOTAL del fichero en bytes.", examples=["10240"]),
    sha256: Optional[str] = Query(
        None,
        description="sha256 hexadecimal del fichero ENTERO.",
        examples=["9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"],
    ),
    offset: Optional[str] = Query(
        "0", description="Bytes que el hub ya tiene de este fichero (0 = empieza o reinicia).", examples=["0"]
    ),
    device: Optional[str] = Query(None, **DEVICE_Q),
    p: Principal = Depends(hook_device),
    ctx: AppContext = Depends(get_ctx),
):
    """Sube (o continúa) un fichero a staging. El cuerpo es el contenido en bruto, en streaming."""
    cfg = ctx.cfg()
    game, device = ctx.hooks.scope(
        cfg, game, device, p.device
    )  # 403 si `?device=` no es el de la key; 404 si el juego no lo incluye
    cl = request.headers.get("content-length")
    return await ctx.hooks.upload(
        cfg, game, device, path, size, sha256, offset, request.stream(), int(cl) if cl and cl.isdigit() else None
    )


async def _json_obj(request: Request) -> dict:
    try:
        body = await request.json()
    except Exception:
        raise ApiError(400, "err.main.json_body_required") from None
    if not isinstance(body, dict):
        raise ApiError(400, "err.main.json_body_required")
    return body


@router.post("/{game}/commit", **docs.COMMIT)
async def hook_commit(
    request: Request,
    game: str = Path(description="Id o nombre del juego.", examples=["Mi Juego"]),
    device: Optional[str] = Query(None, **DEVICE_Q),
    p: Principal = Depends(hook_device),
    ctx: AppContext = Depends(get_ctx),
):
    """Aplica al hub los ficheros subidos: `{"expect": <hash del hub o null>, "manifest": [...]}`."""
    body = await _json_obj(request)
    expect, manifest = body.get("expect"), body.get("manifest")
    if "expect" not in body or not (expect is None or isinstance(expect, str)) or not isinstance(manifest, list):
        raise ApiError(400, "err.main.json_body_required")
    cfg = ctx.cfg()
    game, device = ctx.hooks.scope(
        cfg, game, device, p.device
    )  # 403 si `?device=` no es el de la key; 404 si el juego no lo incluye
    return await ctx.hooks.commit(cfg, game, device, expect, manifest)
