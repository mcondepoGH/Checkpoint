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
