"""Respuestas de error y documentación de cada operación pública (resúmenes, descripciones y ejemplos).
Se pasa tal cual al decorador de la ruta: solo `summary`/`description`/`responses`."""

from .models import ErrorBody, GameItem, OpenedResult, Ping, WatchItem


def _ok(model, description: str, *examples: tuple) -> dict:
    """Respuesta 200 solo para el esquema (no valida ni filtra la respuesta real). examples = (clave, resumen, valor)."""
    ex = {k: {"summary": s, "value": v} for k, s, v in examples}
    return {"model": model, "description": description, "content": {"application/json": {"examples": ex}}}


def _err(code: str, params: dict = None) -> dict:
    return {"detail": {"code": code, "params": params or {}}}


def error_response(description: str, *examples: tuple, headers: dict = None) -> dict:
    """Respuesta de error documentada: `examples` = (clave, resumen, código, params)."""
    ex = {k: {"summary": s, "value": _err(c, p)} for k, s, c, p in examples}
    out = {"model": ErrorBody, "description": description, "content": {"application/json": {"examples": ex}}}
    if headers:
        out["headers"] = headers
    return out


R401 = error_response(
    "API key ausente, mal formada, inválida, revocada o regenerada (todo es el mismo 401), o se usó la cookie de "
    "sesión. Se comprueba antes que nada: no revela si el juego existe. Cada fallo cuenta para el límite por IP.",
    ("invalid", "Sin key, key inválida o revocada", "err.apikey.invalid", None),
    headers={
        "WWW-Authenticate": {"description": "Siempre `Bearer`.", "schema": {"type": "string", "example": "Bearer"}}
    },
)

R429 = error_response(
    "Demasiados fallos de key seguidos desde esta IP. Tras 3 fallos bloquea 5 s y cada fallo posterior duplica la "
    "espera (10, 20, 40 s...) hasta 900 s (15 min). Mientras dura, responde 429 incluso con una key válida. Es en "
    "memoria y por IP: un acierto reinicia el contador.",
    ("blocked", "IP bloqueada temporalmente", "err.main.too_many_attempts", {"seconds": 5}),
    headers={
        "Retry-After": {
            "description": "Segundos hasta poder reintentar (5 a 900).",
            "schema": {"type": "integer", "example": 5},
        }
    },
)

R400 = error_response(
    "Falta `device` (y el juego está en más de un dispositivo) o la referencia es ambigua.",
    ("required", "Falta `?device=`", "err.hook.device_required", {"devices": "PC uno (dev-1), Laptop (dev-2)"}),
    (
        "ambiguous",
        "El nombre coincide con varios dispositivos",
        "err.hook.device_ambiguous",
        {
            "cause": {
                "code": "err.config.ref_ambiguous",
                "params": {"ref": "PC", "matches": "'PC uno' (dev-1), 'pc' (dev-2)"},
            }
        },
    ),
)

R404 = error_response(
    "El juego o el dispositivo no existen (o el dispositivo no pertenece al juego).",
    ("game", "Juego desconocido", "err.main.game_unknown", {}),
    ("device", "Dispositivo desconocido", "err.hook.device_unknown", {}),
)

R409 = error_response(
    "Ya hay una ejecución de ese juego en curso (cron, manual u otro aviso), o la referencia al juego es ambigua. No se "
    "arma vigilancia.",
    ("busy", "Ejecución en curso", "err.main.run_in_progress", {}),
    (
        "ambiguous",
        "El nombre coincide con varios juegos",
        "err.main.game_ambiguous",
        {
            "cause": {
                "code": "err.config.ref_ambiguous",
                "params": {"ref": "Juego", "matches": "'Juego' (g1), 'juego' (g2)"},
            }
        },
    ),
)


# ---- documentación de cada operación (se pasa tal cual al decorador: solo summary/description/responses) ----
PING = dict(
    summary="Comprobar la API key",
    description="Devuelve `200` si la API key es válida. Úsalo para probar la key y la conexión con el hub: no cambia "
    "nada ni toca ningún juego.",
    responses={200: _ok(Ping, "La key es válida.", ("ok", "Key válida", {"ok": True, "user": "admin"}))},
)

WATCHES = dict(
    summary="Listar las vigilancias de cierre activas",
    description="Vigilancias activas ahora mismo: tras un aviso `opened`, el hub vigila el proceso del juego en ese "
    "dispositivo y, al cerrarse, hace el checkpoint solo. Son en memoria (se pierden si el hub se "
    "reinicia). Lista vacía si no hay ninguna. Solo lectura, sin datos sensibles.",
    responses={
        200: _ok(
            list[WatchItem],
            "Lista de vigilancias (puede estar vacía).",
            (
                "running",
                "Un juego en marcha",
                [
                    {
                        "game": "g1",
                        "device": "dev-1",
                        "state": "running",
                        "since": "2026-01-15T18:30:12Z",
                        "last_poll": "2026-01-15T18:45:12Z",
                        "poll": 15.0,
                    }
                ],
            ),
            ("empty", "Sin vigilancias", []),
        )
    },
)

_OPENED_OK = {
    "ok": True,
    "outcome": "ok",
    "game": "g1",
    "device": "dev-1",
    "run_id": "3f9c1a7b2d4e",
    "code": "err.sync.done",
    "params": {},
    "watching": True,
}
OPENED = dict(
    summary="Avisar de que se va a abrir un juego",
    description=(
        "> **Atención: Try it out ejecuta de verdad.** Esta operación hace una **sincronización previa real** del "
        "juego (puede copiar ficheros de save al dispositivo) y **arma el vigilante de cierre** del juego. No es una "
        "simulación: úsala solo con un juego y dispositivo reales y ten en cuenta que, al cerrarse el juego, el hub "
        "hará un checkpoint.\n\n"
        "Se llama justo antes de arrancar el juego. El hub sincroniza ese juego **antes de que arranque**: si tiene un "
        "save más nuevo, lo copia al dispositivo; si no, termina sin copiar. Usa **siempre** la política de conflictos "
        "`skip`: ante un conflicto no toca nada, lo indica en la respuesta y lo deja en el historial (disparador "
        "«Aviso del juego»).\n\n"
        "**Bloqueante.** La petición espera a que acabe la sincronización, hasta 55 s. Si se supera, responde `200` "
        "con `outcome: timeout` y la sincronización sigue en segundo plano. Usa en el cliente un tiempo máximo mayor "
        "(p. ej. `curl -m 60`).\n\n"
        "**Un fallo de la sincronización no es un 5xx.** Responde `200` con `ok: false`, `outcome` (`conflict`, "
        "`aborted`, `partial`, `error`, `timeout`) y `code`/`params` con el detalle. No se reintenta; el cron de la "
        "sincronización automática sigue como red de seguridad. Solo `ok: true` es éxito.\n\n"
        "**Vigilancia de cierre.** Con cualquier `200` (también `conflict`, `aborted` o `timeout`) se arma la "
        "vigilancia si el juego tiene `process` (`watching: true`); si no, `watching: false` con "
        "`watch_reason: no_process`. Nunca se arma con `400`, `401`, `404` ni `409`. La respuesta no incluye la "
        "duración: la sincronización dura hasta 55 s.\n\n"
        "**Juego desactivado** (`enabled: false` en la configuración). No se sincroniza ni se arma la vigilancia: "
        "responde `200` con `ok: false`, `outcome: skipped`, `code: err.sync.game_disabled`, `watching: false` y "
        "`watch_reason: disabled`, y lo deja en el historial (disparador «Aviso del juego», omitido). Antes se "
        "resuelven juego y dispositivo (los `400`/`404` no cambian).\n\n"
        "**Juego y dispositivo.** `game` es el id o el nombre del juego. `device` (id o nombre) debe pertenecer al "
        "juego; es obligatorio si el juego está en más de un dispositivo; si tiene uno solo se deduce y puede omitirse."
    ),
    responses={
        200: _ok(
            OpenedResult,
            "La sincronización terminó (con éxito o no) o superó el tiempo máximo. Mira `outcome`.",
            ("ok", "Éxito: se copió el save más nuevo", _OPENED_OK),
            ("already_synced", "Éxito: no había nada que copiar", {**_OPENED_OK, "code": "err.sync.already_synced"}),
            (
                "conflict",
                "Conflicto: no se tocó nada",
                {**_OPENED_OK, "ok": False, "outcome": "conflict", "code": "err.sync.conflict"},
            ),
            (
                "aborted",
                "Abortado (p. ej. dispositivo sin conexión)",
                {**_OPENED_OK, "ok": False, "outcome": "aborted", "code": "err.sync.all_offline"},
            ),
            (
                "no_process",
                "Éxito, pero el juego no tiene `process`: sin vigilancia",
                {**_OPENED_OK, "watching": False, "watch_reason": "no_process"},
            ),
            (
                "disabled",
                "Juego desactivado: no se sincroniza ni se vigila",
                {
                    "ok": False,
                    "outcome": "skipped",
                    "game": "g1",
                    "device": "dev-1",
                    "code": "err.sync.game_disabled",
                    "params": {},
                    "watching": False,
                    "watch_reason": "disabled",
                },
            ),
            (
                "timeout",
                "Superó los 55 s: sigue en segundo plano",
                {
                    "ok": False,
                    "outcome": "timeout",
                    "game": "g1",
                    "device": "dev-1",
                    "run_id": "3f9c1a7b2d4e",
                    "code": "err.hook.timeout",
                    "params": {"seconds": 55},
                    "watching": True,
                },
            ),
        ),
        400: R400,
        404: R404,
        409: R409,
    },
)

GAMES = dict(
    summary="Listar los juegos y su estado",
    description="Todos los juegos de la configuración con el resultado de su última sincronización, para consultarlo "
    "desde un dispositivo sin SSH. `status` es `null` si el juego aún no se ha sincronizado. Solo lectura: no "
    "sincroniza nada y no devuelve rutas, dispositivos ni ajustes.",
    responses={
        200: _ok(
            list[GameItem],
            "Lista de juegos (puede estar vacía).",
            (
                "games",
                "Un juego sincronizado y otro sin sincronizar",
                [
                    {
                        "id": "g1",
                        "name": "Mi Juego",
                        "enabled": True,
                        "status": {
                            "result": "ok",
                            "code": "err.sync.done",
                            "started": "2026-01-15T18:30:12",
                            "finished": "2026-01-15T18:30:14",
                        },
                    },
                    {"id": "g2", "name": "Otro Juego", "enabled": True, "status": None},
                ],
            ),
            ("empty", "Sin juegos configurados", []),
        )
    },
)
