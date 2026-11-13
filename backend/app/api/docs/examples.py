"""Respuestas de error y documentación de cada operación pública (resúmenes, descripciones y ejemplos).
Se pasa tal cual al decorador de la ruta: solo `summary`/`description`/`responses`."""

from ...services.hooks import MANIFEST_MAX_FILES, ManifestEntry
from .models import (
    ClosedResult,
    CommitResult,
    ErrorBody,
    FingerprintResult,
    GameItem,
    HubManifest,
    OpenedResult,
    Ping,
    UploadResult,
    WatchItem,
)


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
    "API key ausente, mal formada, inválida, revocada o regenerada (todo es el mismo 401), de una clase que este "
    "endpoint no acepta (la de usuario `ck_...` en un endpoint de dispositivo, o la de dispositivo `ckd_...` en uno de "
    "usuario), de un dispositivo borrado o que ya no es `http`, o se usó la cookie de sesión. Se comprueba antes que "
    "nada: no revela si el juego existe ni qué clase de key era. Cada fallo cuenta para el límite por IP.",
    ("invalid", "Sin key, key inválida, revocada o de otra clase", "err.apikey.invalid", None),
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

R400_DEVICE_HTTP = error_response(
    "El cuerpo no es una lista JSON.",
    ("body", "El cuerpo no es una lista JSON", "err.main.json_body_required", {}),
)

R422 = error_response(
    "Manifiesto inválido: ruta insegura (`..`, absoluta, caracteres no permitidos), ruta repetida, sha256 no "
    "hexadecimal de 64 caracteres, campos que faltan o con tipo incorrecto, o demasiados ficheros. No se compara nada.",
    ("path", "Ruta fuera de la carpeta del juego", "err.hook.manifest_path_invalid", {}),
    ("sha", "sha256 inválido", "err.hook.manifest_sha_invalid", {}),
    ("dup", "Ruta repetida", "err.hook.manifest_duplicate", {}),
    (
        "fields",
        "Campos mal formados",
        "err.hook.manifest_invalid",
        {"errors": [{"path": "0.size", "type": "int_type"}]},
    ),
    ("big", "Demasiados ficheros", "err.hook.manifest_too_large", {"max": MANIFEST_MAX_FILES}),
)

R404 = error_response(
    "El juego o el dispositivo no existen (o el dispositivo no pertenece al juego).",
    ("game", "Juego desconocido", "err.main.game_unknown", {}),
    ("device", "Dispositivo desconocido", "err.hook.device_unknown", {}),
)

R403 = error_response(
    "`?device=` (opcional con una key de dispositivo) no es el dispositivo de la key. Un dispositivo desconocido da "
    "el mismo 403, para no revelar cuáles existen. No cuenta como fallo de key para el límite por IP.",
    ("mismatch", "`?device=` distinto del de la key", "err.apikey.device_mismatch", {}),
)

R404_GAME = error_response(
    "El juego no existe **o no incluye el dispositivo de la key**: es el mismo 404 en los dos casos, para no revelar "
    "juegos que no son del dispositivo.",
    ("game", "Juego desconocido o que no incluye el dispositivo", "err.main.game_unknown", {}),
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


R409_FINGERPRINT = error_response(
    "Ya hay una ejecución de ese juego en curso (cron, manual u otro aviso), el juego está desactivado o la "
    "referencia al juego es ambigua.",
    ("busy", "Ejecución en curso", "err.main.run_in_progress", {}),
    ("disabled", "Juego desactivado", "err.sync.game_disabled", {}),
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
    responses={
        200: _ok(
            Ping,
            "La key es válida (de usuario o de dispositivo).",
            ("ok", "Key de usuario", {"ok": True, "user": "admin"}),
            ("device", "Key de dispositivo", {"ok": True, "user": "admin", "device": "deck"}),
        )
    },
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

_SIDE = {"hash": "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08", "files": 2, "size": 20480}
_FP = {"game": "g1", "device": "deck", "reason": None, "hub": {**_SIDE, "mtime": 1768501000}}
_FP["device_state"] = {**_SIDE, "mtime": 1768501812}
FINGERPRINT = dict(
    summary="Comparar los saves de un dispositivo http con el hub",
    description=(
        "Para dispositivos con `http: true` (sin SSH). El dispositivo envía el **manifiesto** de su carpeta de saves "
        "(`path` relativa con `/`, `sha256` en hexadecimal, `size` en bytes y `mtime` en segundos Unix) y el hub lo "
        "compara con su copia y con la línea base de la última sincronización, con la misma lógica que la sync "
        "clásica. La **key de dispositivo** identifica al dispositivo (`?device=` es opcional; si se pasa y no es el "
        "de la key, `403`).\n\n"
        "`action`: `upload` (el dispositivo manda: debe subir sus saves), `download` (manda el hub: debe bajarlos), "
        "`none` (iguales) o `conflict` (ambos cambiaron o no hay línea base: no se decide nada, nunca por mtime). "
        "Un lado vacío nunca gana a uno con datos.\n\n"
        "**Única escritura:** con `action: none` (`reason: same`, huella igual a la del hub y no vacía) fija la línea "
        "base del dispositivo y del hub (verificada contra el manifiesto real), con el lock del juego y sin reescribir "
        "si ya es esa; con `upload`, `download` o `conflict` no escribe nada ni toma el lock. Nunca toca ficheros ni "
        "historial. Si el lock está ocupado o hay una "
        "ejecución del juego en curso responde `409` (`err.main.run_in_progress`); si el juego está desactivado, "
        "`409` (`err.sync.game_disabled`). Las rutas del manifiesto se validan: una ruta insegura da `422`.\n\n"
        "**`?manifest=1` (opcional, aditivo):** con `action: download` la respuesta incluye además `hub_manifest` (la "
        "misma forma que `GET /manifest`: `[{path, sha256, size, mtime}]`), calculado de la misma lectura del hub que "
        "`hub` y la decisión, para bajar sin otra petición ni carrera. Sin el parámetro, o con otra acción, la "
        "respuesta no cambia (`GET /manifest` sigue igual)."
    ),
    response_model=FingerprintResult,
    response_model_exclude_unset=True,
    openapi_extra={
        "requestBody": {
            "required": True,
            "description": f"Manifiesto: lista de ficheros (máx. {MANIFEST_MAX_FILES}); `[]` = carpeta vacía.",
            "content": {
                "application/json": {
                    "schema": {"type": "array", "items": ManifestEntry.model_json_schema()},
                    "examples": {
                        "manifest": {
                            "summary": "Dos ficheros",
                            "value": [
                                {
                                    "path": "slot1/save.dat",
                                    "sha256": "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
                                    "size": 10240,
                                    "mtime": 1768501812,
                                },
                                {
                                    "path": "settings.ini",
                                    "sha256": "2c26b46b68ffc68ff99b453c1d30413413422d706483bfa0f98a5e886266e7ae",
                                    "size": 10240,
                                    "mtime": 1768501000,
                                },
                            ],
                        },
                        "empty": {"summary": "Carpeta vacía", "value": []},
                    },
                }
            },
        }
    },
    responses={
        200: _ok(
            FingerprintResult,
            "Decisión para el dispositivo. Mira `action`.",
            ("upload", "Gana el dispositivo", {**_FP, "action": "upload"}),
            ("download", "Gana el hub", {**_FP, "action": "download"}),
            (
                "download_manifest",
                "Gana el hub, con `?manifest=1`",
                {
                    **_FP,
                    "action": "download",
                    "hub_manifest": [
                        {
                            "path": "slot1/save.dat",
                            "sha256": "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
                            "size": 10240,
                            "mtime": 1768501000,
                        },
                        {
                            "path": "settings.ini",
                            "sha256": "2c26b46b68ffc68ff99b453c1d30413413422d706483bfa0f98a5e886266e7ae",
                            "size": 10240,
                            "mtime": 1768500000,
                        },
                    ],
                },
            ),
            ("none", "Iguales", {**_FP, "action": "none", "reason": "same"}),
            ("conflict", "Conflicto: no se hace nada", {**_FP, "action": "conflict", "reason": "both-changed"}),
        ),
        400: R400_DEVICE_HTTP,
        403: R403,
        404: R404_GAME,
        409: R409_FINGERPRINT,
        422: R422,
    },
)

R409_CLOSED = error_response(
    "Ya hay una ejecución de ese juego en curso (cron, manual u otro aviso; el cierre queda como omitido en el "
    "historial) o la referencia al juego es ambigua.",
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

_CLOSED_OK = {"game": "g1", "device": "deck", "recorded": True, "outcome": "ok"}
CLOSED = dict(
    summary="Avisar de que un dispositivo http cerró el juego",
    description=(
        "Para dispositivos con `http: true` (sin SSH): el hub no puede sondear su proceso, así que es el dispositivo "
        "quien avisa de que el juego se cerró. **Solo deja constancia** en el historial (disparador `hook_closed`, "
        "dispositivo incluido): no sincroniza, no copia nada ni toca la línea base. Después el dispositivo hace "
        "`fingerprint` y sube o baja sus saves por su cuenta. Sin cuerpo.\n\n"
        "Un juego **desactivado** responde `200` con `outcome: skipped` y `code: err.sync.game_disabled` (queda "
        "`skipped` en el historial). Si hay una ejecución del juego en curso, `409` (`err.main.run_in_progress`) y "
        "queda `skipped` (`err.hook.busy`). La **key de dispositivo** identifica al dispositivo: "
        "`?device=` es opcional y, si se pasa y no es el de la key, `403`."
    ),
    response_model=ClosedResult,
    response_model_exclude_none=True,
    responses={
        200: _ok(
            ClosedResult,
            "Cierre registrado (`ok`) u omitido por juego desactivado (`skipped`).",
            ("ok", "Cierre registrado", _CLOSED_OK),
            (
                "disabled",
                "Juego desactivado: omitido",
                {**_CLOSED_OK, "outcome": "skipped", "code": "err.sync.game_disabled", "params": {}},
            ),
        ),
        403: R403,
        404: R404_GAME,
        409: R409_CLOSED,
    },
)

# ---- subida y bajada de saves de dispositivos `http` ----
_SHA = "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"
_AMBIGUOUS = (
    "ambiguous",
    "El nombre coincide con varios juegos",
    "err.main.game_ambiguous",
    {
        "cause": {
            "code": "err.config.ref_ambiguous",
            "params": {"ref": "Juego", "matches": "'Juego' (g1), 'juego' (g2)"},
        }
    },
)
_BUSY = ("busy", "Ejecución en curso o lock del juego tomado", "err.main.run_in_progress", {})
_DISABLED = ("disabled", "Juego desactivado", "err.sync.game_disabled", {})
_PATH_INVALID = (
    "path",
    "Ruta insegura (`..`, absoluta, enlace simbólico...)",
    "err.hook.file_path_invalid",
    {},
)

R400_FILE = error_response(
    "La ruta del fichero no es segura. La ruta se normaliza (`\\` pasa a `/`) y se revalida contra el directorio de "
    "trabajo: se rechazan `..`, las rutas absolutas, NUL, los enlaces simbólicos y cualquier ruta que acabe fuera de él.",
    _PATH_INVALID,
)
R400_BODY = error_response(
    "El cuerpo no tiene la forma esperada.",
    ("body", "Cuerpo JSON incorrecto", "err.main.json_body_required", {}),
)
R409_BUSY = error_response(
    "Ya hay una ejecución de ese juego en curso o su lock lo tiene otra operación (otra subida, el commit o la sync), "
    "el juego está desactivado o la referencia al juego es ambigua. Se puede reintentar más tarde.",
    _BUSY,
    _DISABLED,
    _AMBIGUOUS,
)
R416 = error_response(
    "`Range` inválido, de varios rangos o fuera del fichero. La respuesta lleva `Content-Range: bytes */<tamaño>`.",
    ("range", "Rango insatisfacible", "err.hook.range_invalid", {}),
    headers={
        "Content-Range": {
            "description": "`bytes */<tamaño>`.",
            "schema": {"type": "string", "example": "bytes */10240"},
        }
    },
)
R413 = error_response(
    "El fichero supera el máximo por fichero (`CHECKPOINT_HOOK_MAX_FILE_MB`, 512 MiB por defecto; `err.hook.file_too_large`) "
    "o el staging del juego (todos sus dispositivos) supera su tope (`CHECKPOINT_HOOK_STAGING_MAX_MB`, 2048 MiB por "
    "defecto; `err.hook.staging_full`). Se comprueba con el `size` declarado, con el `Content-Length` y, como ambos "
    "son falsificables, también mientras llega el cuerpo (sin `Content-Length`, en chunked). Lo recibido de ese "
    "fichero se descarta.",
    ("big", "Fichero demasiado grande", "err.hook.file_too_large", {"max_mb": 512}),
    ("full", "Staging del juego lleno", "err.hook.staging_full", {"max_mb": 2048}),
)

_FILE_Q = {"game": "g1", "device": "deck"}
MANIFEST = dict(
    summary="Manifiesto del hub para bajar los saves",
    description=(
        "Para dispositivos con `http: true`. Devuelve el listado de ficheros que tiene el hub de ese juego (`path`, "
        "`sha256`, `size`, `mtime`), con el mismo formato que el manifiesto de `fingerprint`, y su huella `hash`. "
        "Tras `fingerprint` con `action: download`, el dispositivo compara este listado con lo que tiene, baja cada "
        "fichero con `GET /api/hook/{game}/files?path=...` (reanudable con `Range`), verifica el sha256 de cada uno "
        "y la huella del conjunto, y vuelve a llamar a `fingerprint` (con `none` el hub fija su línea base). Lo que el dispositivo tenga de más "
        "y no esté aquí debe borrarlo él.\n\n"
        "Toma el lock del juego durante la lectura: si está ocupado, `409` (`err.main.run_in_progress`). Solo lectura."
    ),
    response_model=HubManifest,
    responses={
        200: _ok(
            HubManifest,
            "Manifiesto del hub (`manifest` vacío si el hub no tiene nada de ese juego).",
            (
                "two",
                "Dos ficheros",
                {
                    **_FILE_Q,
                    "hash": _SHA,
                    "files": 2,
                    "size": 20480,
                    "mtime": 1768501000,
                    "manifest": [
                        {"path": "settings.ini", "sha256": _SHA, "size": 10240, "mtime": 1768501000},
                        {"path": "slot1/save.dat", "sha256": _SHA, "size": 10240, "mtime": 1768500000},
                    ],
                },
            ),
            ("empty", "Hub vacío", {**_FILE_Q, "hash": None, "files": 0, "size": 0, "mtime": 0, "manifest": []}),
        ),
        403: R403,
        404: R404_GAME,
        409: R409_BUSY,
    },
)

DOWNLOAD = dict(
    summary="Descargar un fichero del hub",
    description=(
        "Para dispositivos con `http: true`. Devuelve el contenido en bruto de un fichero del hub (`path` de "
        "`GET /api/hook/{game}/manifest`). Admite **un** `Range` (`bytes=a-b`, `bytes=a-` o `bytes=-n`) para reanudar: "
        "responde `206` con `Content-Range`; sin `Range`, `200` con `Content-Length` y `Accept-Ranges: bytes`. El "
        "dispositivo debe verificar el sha256 con el del manifiesto.\n\n"
        "La ruta se normaliza y se revalida contra el directorio del juego en el hub: `..`, rutas absolutas, NUL y "
        "enlaces simbólicos dan `400` (`err.hook.file_path_invalid`). Fichero inexistente: `404` "
        "(`err.hook.file_unknown`). El lock del juego solo se toma para abrir el fichero: un commit posterior no corta "
        "una descarga en curso, pero cambia el hub; el hash del conjunto lo detecta (repetir el manifiesto)."
    ),
    responses={
        200: {
            "description": "Contenido completo del fichero.",
            "content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}},
        },
        206: {
            "description": "Rango pedido. Cabecera `Content-Range: bytes <inicio>-<fin>/<tamaño>`.",
            "content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}},
        },
        400: R400_FILE,
        403: R403,
        404: error_response(
            "El juego no existe o no incluye el dispositivo de la key, o el fichero no existe.",
            ("game", "Juego desconocido o que no incluye el dispositivo", "err.main.game_unknown", {}),
            ("file", "El hub no tiene ese fichero", "err.hook.file_unknown", {}),
        ),
        409: R409_BUSY,
        416: R416,
    },
)

UPLOAD = dict(
    summary="Subir un fichero de saves (reanudable)",
    description=(
        "Para dispositivos con `http: true`. Tras `fingerprint` con `action: upload`, el dispositivo sube **cada "
        "fichero** de su manifiesto con `PUT`, cuerpo en bruto (`application/octet-stream`) y en streaming. Query: "
        "`path` (ruta relativa), `size` (tamaño TOTAL), `sha256` (del fichero ENTERO) y `offset` (bytes que el hub ya "
        "tiene; 0 empieza o reinicia).\n\n"
        "**Nada toca el hub:** los ficheros se guardan en un directorio de staging por juego y dispositivo; solo "
        "`POST /api/hook/{game}/commit` modifica `data/hub/<juego>`. La subida **no toma el lock del juego** "
        "(una subida lenta no bloquea la sync clásica): solo comprueba al entrar que no haya una ejecución en curso "
        "(`409` `err.main.run_in_progress`) y reserva ese fichero del dispositivo (otro `PUT` simultáneo al mismo "
        "fichero: `409` `err.hook.upload_busy`). El lock del juego lo toma `commit`, que además reserva todo el staging "
        "del dispositivo mientras verifica y aplica: un `PUT` que llegue entonces recibe el mismo `409` "
        "`err.hook.upload_busy` (reintenta luego).\n\n"
        "**Reanudar:** si se corta, repite con `offset` = lo recibido. Si `offset` no coincide con lo que el hub tiene "
        "(o `sha256`/`size` cambiaron), `409` `err.hook.upload_offset_mismatch` con `params.received` (los bytes que "
        "tiene de verdad: continúa desde ahí, o con `offset=0` para reiniciar). Al llegar a `size` bytes se verifica el "
        "sha256: distinto, `422` `err.hook.sha_mismatch` y se descarta. `complete: true` = fichero verificado en staging.\n\n"
        "**Límites:** `CHECKPOINT_HOOK_MAX_FILE_MB` por fichero (`413` `err.hook.file_too_large`, `params.max_mb`) y "
        "`CHECKPOINT_HOOK_STAGING_MAX_MB` para todo el staging del juego (`413` `err.hook.staging_full`, "
        "`params.max_mb`). El staging sin escrituras en `CHECKPOINT_HOOK_STAGING_TTL_H` horas se purga solo. "
        "La ruta se normaliza y se revalida contra el staging (nada fuera de él, ni por `..` ni por enlaces simbólicos)."
    ),
    response_model=UploadResult,
    openapi_extra={
        "requestBody": {
            "required": True,
            "description": "Contenido del fichero (o del trozo desde `offset`) en bruto.",
            "content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}},
        }
    },
    responses={
        200: _ok(
            UploadResult,
            "Trozo recibido. Mira `complete`.",
            (
                "partial",
                "Faltan bytes",
                {**_FILE_Q, "path": "slot1/save.dat", "received": 4096, "size": 10240, "complete": False},
            ),
            (
                "complete",
                "Fichero completo y verificado",
                {**_FILE_Q, "path": "slot1/save.dat", "received": 10240, "size": 10240, "complete": True},
            ),
        ),
        400: R400_FILE,
        403: R403,
        404: R404_GAME,
        409: error_response(
            "Ejecución en curso, juego desactivado, referencia ambigua, otra subida en curso del mismo fichero y "
            "dispositivo o un commit de ese dispositivo en curso (`err.hook.upload_busy`), o `offset` que no coincide con lo que el hub tiene "
            "(`params.received`).",
            _BUSY,
            _DISABLED,
            _AMBIGUOUS,
            ("offset", "Offset incorrecto", "err.hook.upload_offset_mismatch", {"received": 4096}),
            ("upload_busy", "Otra subida del mismo fichero", "err.hook.upload_busy", {}),
        ),
        413: R413,
        422: error_response(
            "Parámetros de query inválidos (`size`, `offset`, `sha256`), más bytes de los declarados en `size` o sha256 "
            "del fichero completo que no coincide.",
            ("param", "Parámetro inválido", "err.hook.param_invalid", {"param": "size"}),
            ("size", "Más bytes que `size`", "err.hook.upload_size_mismatch", {}),
            ("sha", "sha256 no coincide", "err.hook.sha_mismatch", {}),
        ),
    },
)

_COMMIT_OK = {**_FILE_Q, "outcome": "ok", "hash": _SHA, "files": 2, "size": 20480, "version": "2026-01-15_183012"}
COMMIT = dict(
    summary="Aplicar al hub los ficheros subidos",
    description=(
        "Para dispositivos con `http: true`. Cuando todos los ficheros del manifiesto están subidos "
        "(`complete: true`), el dispositivo llama aquí con `expect` (el `hub.hash` que vio en `fingerprint`, `null` si "
        "el hub estaba vacío) y el `manifest` completo. **El manifiesto es la verdad entera**: el hub queda con "
        "exactamente esos ficheros (lo que tuviera de más desaparece, tras guardarse en una versión).\n\n"
        "Con el lock del juego (ocupado: `409`) comprueba, en este orden: que el hub no cambió (`409` "
        "`err.hook.hub_changed`: repite `fingerprint`); que sigue mandando el dispositivo, con la política `skip` y la "
        "misma lógica que `fingerprint` (conflicto u hub más nuevo: `409` `err.hook.commit_rejected`, "
        "`params.reason`: `both-changed`, `no-baseline`, `inconsistent` o `hub`; no se toca nada); que están todos los "
        "ficheros (`422` `err.hook.upload_incomplete`, `params.missing` y `params.paths`, hasta 10); y que el "
        "conjunto da la huella del manifiesto (`422` `err.hook.set_mismatch`). Si todo cuadra: guarda el hub actual "
        "como versión, lo reemplaza, aplica el mtime del manifiesto a cada fichero, fija la línea base del "
        "dispositivo, poda versiones antiguas y deja una entrada en el historial (disparador `hook`, con el "
        "dispositivo). `outcome: unchanged` si el hub ya era igual (solo se fija la línea base). El staging se borra.\n\n"
        "Además del lock del juego, reserva el staging del dispositivo durante la verificación y la escritura (siempre "
        "en ese orden, sin esperar): con un `PUT` del mismo dispositivo en curso responde `409` "
        "`err.hook.upload_busy` sin tocar nada, y mientras dura los `PUT` de ese dispositivo reciben el mismo `409`."
    ),
    response_model=CommitResult,
    response_model_exclude_none=True,
    openapi_extra={
        "requestBody": {
            "required": True,
            "description": "`expect` (obligatoria, puede ser `null`) y `manifest` (misma forma que en `fingerprint`).",
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "required": ["expect", "manifest"],
                        "properties": {
                            "expect": {
                                "type": ["string", "null"],
                                "description": "Hash del hub visto en `fingerprint`.",
                            },
                            "manifest": {"type": "array", "items": ManifestEntry.model_json_schema()},
                        },
                    },
                    "examples": {
                        "commit": {
                            "summary": "Dos ficheros",
                            "value": {
                                "expect": _SHA,
                                "manifest": [
                                    {"path": "slot1/save.dat", "sha256": _SHA, "size": 10240, "mtime": 1768501812},
                                    {"path": "settings.ini", "sha256": _SHA, "size": 10240, "mtime": 1768501000},
                                ],
                            },
                        },
                        "first": {"summary": "Primera subida (hub vacío)", "value": {"expect": None, "manifest": []}},
                    },
                }
            },
        }
    },
    responses={
        200: _ok(
            CommitResult,
            "Hub actualizado (`ok`) o ya igual (`unchanged`).",
            ("ok", "Hub reemplazado", _COMMIT_OK),
            (
                "unchanged",
                "Ya era igual",
                {**_FILE_Q, "outcome": "unchanged", "hash": _SHA, "files": 2, "size": 20480},
            ),
        ),
        400: R400_BODY,
        403: R403,
        404: R404_GAME,
        409: error_response(
            "Lock del juego tomado o ejecución en curso, juego desactivado, referencia ambigua, el hub cambió desde "
            "`fingerprint` o la decisión ya no es «sube el dispositivo» (conflicto: no se resuelve), o una subida del mismo "
            "dispositivo sigue en curso (`err.hook.upload_busy`).",
            _BUSY,
            _DISABLED,
            _AMBIGUOUS,
            ("changed", "El hub cambió", "err.hook.hub_changed", {}),
            ("upload_busy", "Subida del dispositivo en curso", "err.hook.upload_busy", {}),
            ("rejected", "Conflicto (política skip)", "err.hook.commit_rejected", {"reason": "both-changed"}),
        ),
        422: error_response(
            "Manifiesto inválido (mismos códigos que `fingerprint`), faltan ficheros por subir o el conjunto no da la "
            "huella del manifiesto.",
            ("path", "Ruta insegura", "err.hook.manifest_path_invalid", {}),
            (
                "incomplete",
                "Faltan ficheros",
                "err.hook.upload_incomplete",
                {"missing": 1, "paths": ["slot1/save.dat"]},
            ),
            ("set", "El conjunto no cuadra", "err.hook.set_mismatch", {}),
        ),
    },
)

GAMES = dict(
    summary="Listar los juegos y su estado",
    description="Con la key de **usuario**, todos los juegos de la configuración; con la de **dispositivo**, solo los "
    "que tienen ese dispositivo en su lista. Con el resultado de su última sincronización, para consultarlo "
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
