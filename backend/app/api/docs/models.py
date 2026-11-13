"""Modelos pydantic solo para el esquema OpenAPI (no validan ni filtran las respuestas reales)."""

from typing import Optional

from pydantic import BaseModel, Field


class ErrorDetail(BaseModel):
    code: str = Field(
        description="Código estable `err.<módulo>.<causa>` (no traducido).", examples=["err.apikey.invalid"]
    )
    params: dict = Field(default_factory=dict, description="Parámetros del código (según el caso; puede estar vacío).")


class ErrorBody(BaseModel):
    """Solo para el esquema de documentación: las respuestas reales las construye `core.errors`."""

    detail: ErrorDetail


class Ping(BaseModel):
    ok: bool = Field(description="Siempre `true` si la key es válida.")
    user: str = Field(description="Usuario dueño de la API key.")
    device: Optional[str] = Field(
        None, description="Id del dispositivo `http` dueño de la key. Solo aparece con una key de dispositivo."
    )


class WatchItem(BaseModel):
    game: str = Field(description="Id interno del juego.")
    device: str = Field(description="Id interno del dispositivo donde se vigila el proceso.")
    state: str = Field(
        description="`waiting`: aún no se vio el proceso; `running`: visto abierto; `settling`: cerrado, "
        "esperando unos segundos antes del checkpoint.",
        examples=["running"],
    )
    since: str = Field(description="Inicio del estado actual (UTC, ISO 8601).")
    last_poll: str = Field(description="Último sondeo completado (latido, UTC ISO 8601).")
    poll: float = Field(description="Intervalo de sondeo, en segundos (15 por defecto).")


class OpenedResult(BaseModel):
    ok: bool = Field(description="`true` solo si `outcome` es `ok`.")
    outcome: str = Field(
        description="`ok`, `conflict`, `aborted` (dispositivo sin conexión, proceso del juego "
        "abierto...), `skipped` (juego de un dispositivo con la partida local ausente), `partial`, `error` o `timeout`.",
        examples=["ok"],
    )
    game: str = Field(description="Id interno del juego.")
    device: str = Field(description="Id interno del dispositivo.")
    run_id: Optional[str] = Field(
        None,
        description="Id de la ejecución (la misma que verás en el historial). "
        "Falta si el juego está desactivado (no hubo ejecución).",
    )
    code: Optional[str] = Field(
        None, description="Qué pasó, como código `err.sync.*` (o `err.hook.timeout`). Sin traducir. Puede faltar."
    )
    params: Optional[dict] = Field(None, description="Parámetros de `code`.")
    watching: bool = Field(description="`true` si se armó la vigilancia de cierre (el juego tiene `process`).")
    watch_reason: Optional[str] = Field(
        None,
        description="Si `watching` es `false`: `no_process` (el juego no tiene "
        "`process` configurado) o `disabled` (el juego está desactivado).",
    )


class GameSyncStatus(BaseModel):
    result: str = Field(
        description="Resultado de la última sincronización: `ok`, `conflict`, `aborted`, `skipped`, `partial` o `error`.",
        examples=["ok"],
    )
    code: Optional[str] = Field(None, description="Código `err.sync.*` del resultado (sin traducir). Puede faltar.")
    started: Optional[str] = Field(None, description="Inicio (hora local del hub, ISO 8601 sin zona).")
    finished: Optional[str] = Field(None, description="Fin (hora local del hub, ISO 8601 sin zona).")


class GameItem(BaseModel):
    id: str = Field(description="Id interno del juego (vale en las rutas `/api/hook/{game}/...`).")
    name: str = Field(description="Nombre visible del juego (también vale en las rutas).")
    enabled: bool = Field(description="`false` si el juego está desactivado: no se sincroniza por ninguna vía.")
    steam_appid: Optional[int] = Field(
        None,
        description="Appid de Steam del juego (entero positivo), o `null` si no tiene. Es un dato del juego, igual "
        "para todos los dispositivos; solo se edita desde la configuración del hub.",
        examples=[1245620],
    )
    status: Optional[GameSyncStatus] = Field(
        None, description="Última sincronización del juego, o `null` si aún no hay ninguna."
    )


class FingerprintSide(BaseModel):
    hash: Optional[str] = Field(
        description="Huella del conjunto de ficheros (sha256 hexadecimal), o `null` si está vacío.",
        examples=["9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"],
    )
    files: int = Field(description="Número de ficheros.", examples=[3])
    size: int = Field(description="Bytes en total.", examples=[20480])
    mtime: int = Field(description="Mayor mtime (segundos Unix); 0 si está vacío.", examples=[1768501812])


class ManifestFile(BaseModel):
    path: str = Field(description="Ruta relativa con `/`.", examples=["slot1/save.dat"])
    sha256: str = Field(
        description="sha256 hexadecimal del fichero.",
        examples=["9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"],
    )
    size: int = Field(description="Bytes.", examples=[10240])
    mtime: int = Field(description="mtime en segundos Unix.", examples=[1768501812])


class FingerprintResult(BaseModel):
    game: str = Field(description="Id interno del juego.")
    device: str = Field(description="Id interno del dispositivo `http`.")
    action: str = Field(
        description="Qué debe hacer el dispositivo: `upload` (gana el dispositivo: sus saves son los vigentes), "
        "`download` (gana el hub), `none` (iguales) o `conflict` (ambos cambiaron: no se hace nada).",
        examples=["upload"],
    )
    reason: Optional[str] = Field(
        None,
        description="Solo con `none` (`same`) y `conflict` (`both-changed`, `no-baseline` o `inconsistent`); "
        "`null` con `upload` y `download`.",
    )
    hub: FingerprintSide = Field(description="Huella actual del hub para este juego.")
    device_state: FingerprintSide = Field(description="Huella calculada del manifiesto recibido.")
    hub_manifest: Optional[list[ManifestFile]] = Field(
        None,
        description="Solo con `?manifest=1` y `action: download`: el manifiesto del hub (como `GET /manifest`), de la "
        "misma lectura del hub que `hub` y la decisión. Ausente en cualquier otro caso.",
    )


class ClosedResult(BaseModel):
    game: str = Field(description="Id interno del juego.")
    device: str = Field(description="Id interno del dispositivo `http`.")
    recorded: bool = Field(description="`true`: el aviso quedó en el historial (`ok` o `skipped`).")
    outcome: str = Field(
        description="`ok` (cierre registrado) o `skipped` (juego desactivado: se registra como omitido).",
        examples=["ok"],
    )
    code: Optional[str] = Field(None, description="Solo con `skipped`: `err.sync.game_disabled`.")
    params: Optional[dict] = Field(None, description="Parámetros de `code`.")


class HubManifest(BaseModel):
    game: str = Field(description="Id interno del juego.")
    device: str = Field(description="Id interno del dispositivo `http`.")
    hash: Optional[str] = Field(
        description="Huella del hub (la misma que `hub.hash` de `fingerprint`); `null` si está vacío."
    )
    files: int = Field(description="Número de ficheros.", examples=[2])
    size: int = Field(description="Bytes en total.", examples=[20480])
    mtime: int = Field(description="Mayor mtime (segundos Unix); 0 si está vacío.", examples=[1768501000])
    manifest: list[ManifestFile] = Field(description="Un elemento por fichero del hub, ordenados por ruta.")


class UploadResult(BaseModel):
    game: str = Field(description="Id interno del juego.")
    device: str = Field(description="Id interno del dispositivo `http`.")
    path: str = Field(description="Ruta normalizada del fichero (`\\` pasa a `/`).", examples=["slot1/save.dat"])
    received: int = Field(description="Bytes que el hub tiene ya de este fichero.", examples=[4096])
    size: int = Field(description="Tamaño total declarado.", examples=[10240])
    complete: bool = Field(
        description="`true`: el fichero está completo y su sha256 verificado (en staging, aún no en el hub). "
        "`false`: faltan bytes; sigue con `offset=received`."
    )


class CommitResult(BaseModel):
    game: str = Field(description="Id interno del juego.")
    device: str = Field(description="Id interno del dispositivo `http`.")
    outcome: str = Field(
        description="`ok` (el hub quedó igual que el manifiesto) o `unchanged` (ya era igual: no se tocó nada).",
        examples=["ok"],
    )
    hash: Optional[str] = Field(description="Huella del hub tras el commit.")
    files: int = Field(description="Ficheros del hub tras el commit.", examples=[2])
    size: int = Field(description="Bytes del hub tras el commit.", examples=[20480])
    version: Optional[str] = Field(
        None,
        description="Versión donde quedó guardado el contenido anterior del hub; ausente si no había nada que guardar.",
        examples=["2026-01-15_183012"],
    )
