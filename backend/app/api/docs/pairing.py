"""Documentación OpenAPI de la vinculación de dispositivos (`/api/pairing/*`): modelos, errores y ejemplos. Solo describe."""

from typing import Optional

from pydantic import BaseModel, Field

from .examples import _ok, error_response

PAIRING_TAG = "Vinculación de dispositivos (público)"
PAIRING_SESSION_TAG = "Vinculación de dispositivos (sesión)"
SECURITY_PAIRING = "pairingSecretAuth"  # secreto de la solicitud, cabecera `X-Pairing-Secret`
SECURITY_SESSION = "sessionAuth"  # cookie de sesión de la web
COOKIE_NAME = "checkpoint_session"
PAIRING_PREFIX = "/api/pairing/"

PAIRING_TAG_DESCRIPTION = (
    "Rutas `POST /api/pairing/requests` y `GET /api/pairing/requests/{id}`: un dispositivo (p. ej. el plugin de la "
    "Steam Deck) pide acceso al hub **sin key previa**. Es **el único endpoint de Checkpoint sin credencial previa**; "
    "ver las mitigaciones en la descripción de la API."
)
PAIRING_SESSION_TAG_DESCRIPTION = (
    "Rutas `/api/pairing/pending*`: el usuario, **con sesión web**, ve las solicitudes pendientes, y acepta (solo si "
    "el código coincide con el que enseña su dispositivo) o rechaza."
)


class PairingCreateBody(BaseModel):
    name: str = Field(
        description="Nombre visible del dispositivo (1 a 64 caracteres, sin `/` ni `\\`, sin caracteres de control, "
        "sin espacios al principio o al final ni dobles).",
        examples=["Steam Deck"],
    )
    os: str = Field(description="Sistema operativo: `linux` o `windows`.", examples=["linux"])


class PairingCreated(BaseModel):
    id: str = Field(description="Id público de la solicitud (no es secreto; va en la URL de la consulta).")
    code: str = Field(
        description="Código de 6 dígitos. El dispositivo lo **muestra al usuario**; NO sirve para recoger la key.",
        examples=["482915"],
    )
    secret: str = Field(
        description="Secreto de la solicitud (32 bytes, base64 urlsafe). Solo lo conoce el dispositivo: es lo único "
        "que permite consultar la solicitud y recoger la key. No se vuelve a mostrar. Va en `X-Pairing-Secret`."
    )
    expires_in: int = Field(description="Segundos hasta que la solicitud caduca (600).", examples=[600])


class PairingStatus(BaseModel):
    status: str = Field(
        description="`pending` (esperando al usuario), `accepted` (trae `device` y `key`; se entrega **una sola "
        "vez**) o `rejected` (el usuario la rechazó; se entrega una vez).",
        examples=["accepted"],
    )
    expires_in: Optional[int] = Field(None, description="Solo con `pending`: segundos que quedan.")
    device: Optional[str] = Field(None, description="Solo con `accepted`: id interno del dispositivo `http`.")
    key: Optional[str] = Field(
        None,
        description="Solo con `accepted`: la key de dispositivo `ckd_...`, **una sola vez**. Guárdala; si se pierde, "
        "hay que volver a vincular. Si el dispositivo ya existía, esta key sustituye a la anterior.",
    )


class PairingPending(BaseModel):
    id: str = Field(description="Id de la solicitud (para aceptar o rechazar).")
    name: str = Field(description="Nombre que dijo el dispositivo (no verificado).")
    os: str = Field(description="`linux` o `windows` (no verificado).")
    code: str = Field(description="Código de 6 dígitos: compáralo con el que muestra el dispositivo.")
    ip: str = Field(description="IP desde la que se pidió (la que ve el hub).")
    expires_in: int = Field(description="Segundos que quedan.")
    existing: str = Field(
        description="`none`: se creará un dispositivo nuevo; `http`: ya hay uno `http` con ese nombre (se reutiliza y "
        "su key se regenera al recogerla); `other`: ya hay uno que no es `http` con ese nombre (aceptar da `409`).",
        examples=["none"],
    )


class PairingAcceptBody(BaseModel):
    code: str = Field(
        description="El código de 6 dígitos que muestra el dispositivo (obligatorio: obliga a compararlo). Tres "
        "códigos erróneos anulan la solicitud.",
        examples=["482915"],
    )


class PairingAccepted(BaseModel):
    id: str = Field(description="Id de la solicitud.")
    device: str = Field(description="Id interno del dispositivo `http` (creado o reutilizado).")
    name: str = Field(description="Nombre del dispositivo en la configuración.")
    created: bool = Field(description="`true` si se creó ahora; `false` si ya existía y se reutiliza.")


class PairingRejected(BaseModel):
    id: str = Field(description="Id de la solicitud.")
    rejected: bool = Field(description="Siempre `true`.")


R400_CREATE = error_response(
    "Cuerpo que no es un objeto JSON, nombre inválido (`cause` lleva el motivo `err.config.name_*`) o sistema "
    "operativo desconocido.",
    ("name", "Nombre inválido", "err.pairing.name_invalid", {"cause": {"code": "err.config.name_empty", "params": {}}}),
    ("os", "Sistema operativo desconocido", "err.pairing.os_invalid", {"options": "windows, linux"}),
    ("body", "El cuerpo no es un objeto JSON", "err.main.json_body_required", {}),
)
R413 = error_response(
    "El cuerpo supera 2048 bytes.", ("big", "Cuerpo demasiado grande", "err.pairing.body_too_large", {"max": 2048})
)
R429_PAIRING = error_response(
    "Límites del endpoint público, por IP: **máx. 5 solicitudes por 10 min** (`too_many_requests`), **máx. 3 "
    "pendientes a la vez** (`too_many_pending`), y bloqueo por **fallos de secreto** en la consulta (`too_many_attempts`: "
    "tras 3 fallos bloquea 5 s y cada fallo posterior duplica la espera hasta 900 s; mientras dura, 429 incluso con el "
    "secreto bueno). Es en memoria.",
    ("requests", "Demasiadas solicitudes desde esta IP", "err.pairing.too_many_requests", {"seconds": 120}),
    ("pending", "Demasiadas pendientes desde esta IP", "err.pairing.too_many_pending", {}),
    ("attempts", "IP bloqueada por secretos erróneos", "err.main.too_many_attempts", {"seconds": 5}),
    headers={
        "Retry-After": {
            "description": "Segundos hasta poder reintentar (no está en `too_many_pending`).",
            "schema": {"type": "integer", "example": 5},
        }
    },
)
R503 = error_response(
    "Ya hay 10 solicitudes pendientes en el hub (entre todas las IP). Espera a que caduquen o se resuelvan.",
    ("busy", "Hub lleno de solicitudes", "err.pairing.busy", {"seconds": 60}),
    headers={"Retry-After": {"description": "Segundos hasta la primera caducidad.", "schema": {"type": "integer"}}},
)
R404_STATUS = error_response(
    "Solicitud inexistente, caducada, ya entregada **o secreto ausente/erróneo**: es el **mismo 404** en todos los "
    "casos (no revela si la solicitud existe). Cada fallo cuenta para el bloqueo por IP. Una solicitud aceptada deja de "
    "existir tras entregar la key.",
    ("unknown", "Desconocida o secreto erróneo", "err.pairing.request_unknown", {}),
)
R401_SESSION = error_response(
    "Falta la sesión web (cookie). Una API key no vale aquí.",
    ("session", "Sin sesión válida", "err.main.session_required", {}),
)
R403_ORIGIN = error_response(
    "En las escrituras, la cabecera `Origin` no coincide con `Host` (protección CSRF).",
    ("origin", "Origin distinto de Host", "err.main.origin_forbidden", {}),
)
R404_SESSION = error_response(
    "La solicitud no existe o caducó.", ("unknown", "Desconocida o caducada", "err.pairing.request_unknown", {})
)
R400_ACCEPT = error_response(
    "El código no coincide (o falta). Quedan `remaining` intentos; al llegar a 0 la solicitud se anula.",
    ("mismatch", "Código erróneo", "err.pairing.code_mismatch", {"remaining": 2}),
)
R409_ACCEPT = error_response(
    "Ya hay un dispositivo que **no es `http`** con ese nombre (`device_not_http`: no se suplanta; la solicitud sigue "
    "pendiente, rechácela), la solicitud ya no está pendiente (`not_pending`) o `config.yaml` cambió sin parar mientras "
    "se aceptaba (`err.main.config_changed`; reintenta).",
    ("not_http", "Nombre de un dispositivo no http", "err.pairing.device_not_http", {"name": "PC"}),
    ("done", "Ya resuelta", "err.pairing.not_pending", {}),
    ("changed", "La configuración cambió", "err.main.config_changed", {}),
)
R422_ACCEPT = error_response(
    "La configuración resultante no es válida (mismo cuerpo que `PUT /api/config`, con `errors`).",
    ("invalid", "Configuración inválida", "err.main.config_invalid", {}),
)
R500_ACCEPT = error_response(
    "`config.yaml` actual es inválido: no se puede añadir el dispositivo.",
    ("config", "Config inválida", "err.main.config_file_invalid", {"cause": {"code": "err.config.yaml_malformed"}}),
)

_NOSTORE = " La respuesta lleva `Cache-Control: no-store`."


def _body(model, description, example):
    return {
        "requestBody": {
            "required": True,
            "description": description,
            "content": {
                "application/json": {
                    "schema": model.model_json_schema(),
                    "examples": {"example": {"summary": "Ejemplo", "value": example}},
                }
            },
        }
    }


PAIRING_CREATE = dict(
    summary="Pedir acceso al hub (sin key)",
    description=(
        "El dispositivo pide acceso **sin credencial previa**. El hub crea una solicitud **pendiente** y devuelve un "
        "`code` de 6 dígitos (que el dispositivo enseña al usuario) y un `secret` largo (que solo guarda el "
        "dispositivo). La solicitud vive **10 minutos, solo en memoria**. El usuario la ve en el hub con su código y, "
        "si coincide con el del dispositivo, la acepta.\n\n"
        "**Seguridad.** El código NO sirve para recoger la key: solo el `secret`. Envíalo siempre en la cabecera "
        "`X-Pairing-Secret`, nunca en la URL (las URL acaban en logs de accesos, proxies y historial). Límites por "
        "IP: 5 solicitudes por 10 min y 3 pendientes; 10 pendientes en todo el hub (`503`)." + _NOSTORE
    ),
    responses={
        201: _ok(
            PairingCreated,
            "Solicitud creada.",
            (
                "created",
                "Solicitud creada",
                {
                    "id": "k3x9Qd2LmP0aRtUv",
                    "code": "482915",
                    "secret": "<secreto de la solicitud, ~43 caracteres>",
                    "expires_in": 600,
                },
            ),
        ),
        400: R400_CREATE,
        413: R413,
        503: R503,
    },
    **{
        "openapi_extra": _body(
            PairingCreateBody, "Nombre y sistema operativo del dispositivo.", {"name": "Steam Deck", "os": "linux"}
        )
    },
)

PAIRING_STATUS = dict(
    summary="Consultar el estado de la solicitud (y recoger la key)",
    description=(
        "El dispositivo consulta su solicitud con su secreto (cabecera `X-Pairing-Secret`). `pending`: sigue "
        "esperando. `accepted`: devuelve el `device` y su key `ckd_...` **una sola vez** (se genera en este momento) "
        "y la solicitud se borra; la siguiente consulta es `404`. `rejected`: se entrega una vez y se borra. Id "
        "desconocido, caducada o secreto erróneo: el mismo `404`, y cada fallo cuenta para el bloqueo por IP."
        + _NOSTORE
    ),
    responses={
        200: _ok(
            PairingStatus,
            "Estado de la solicitud.",
            ("pending", "Esperando al usuario", {"status": "pending", "expires_in": 540}),
            (
                "accepted",
                "Aceptada: key entregada una sola vez",
                {"status": "accepted", "device": "steam-deck-1a2b3c4d", "key": "ckd_" + "A" * 43},
            ),
            ("rejected", "Rechazada", {"status": "rejected"}),
        ),
        404: R404_STATUS,
    },
)

PAIRING_LIST = dict(
    summary="Listar las solicitudes pendientes",
    description="Solicitudes pendientes (más próximas a caducar primero), con nombre y código para compararlo con el "
    "del dispositivo. Nunca incluye el secreto de la solicitud. Lista vacía si no hay." + _NOSTORE,
    responses={
        200: _ok(
            list[PairingPending],
            "Solicitudes pendientes (puede estar vacía).",
            (
                "list",
                "Una solicitud",
                [
                    {
                        "id": "k3x9Qd2LmP0aRtUv",
                        "name": "Steam Deck",
                        "os": "linux",
                        "code": "482915",
                        "ip": "192.168.1.50",
                        "expires_in": 540,
                        "existing": "none",
                    }
                ],
            ),
            ("empty", "Sin solicitudes", []),
        )
    },
)

PAIRING_ACCEPT = dict(
    summary="Aceptar una solicitud",
    description=(
        "Acepta solo si `code` coincide con el que muestra el dispositivo. Crea el dispositivo `http` en la "
        "configuración si no existe (id interno `<nombre>-<8 hex>`; mismo camino y validaciones que `PUT "
        "/api/config`, con copia de seguridad) o reutiliza el `http` que ya tenga ese nombre. **La key no se genera "
        "ni se devuelve aquí**: la recoge el dispositivo, una vez, con su secreto; entonces la anterior (si había) "
        "deja de valer." + _NOSTORE
    ),
    responses={
        200: _ok(
            PairingAccepted,
            "Solicitud aceptada; el dispositivo ya puede recoger su key.",
            (
                "created",
                "Dispositivo creado",
                {"id": "k3x9Qd2LmP0aRtUv", "device": "steam-deck-1a2b3c4d", "name": "Steam Deck", "created": True},
            ),
            (
                "reused",
                "Dispositivo existente reutilizado",
                {"id": "k3x9Qd2LmP0aRtUv", "device": "deck", "name": "Steam Deck", "created": False},
            ),
        ),
        400: R400_ACCEPT,
        404: R404_SESSION,
        409: R409_ACCEPT,
        422: R422_ACCEPT,
        500: R500_ACCEPT,
    },
    **{"openapi_extra": _body(PairingAcceptBody, "El código que muestra el dispositivo.", {"code": "482915"})},
)

PAIRING_REJECT = dict(
    summary="Rechazar una solicitud",
    description="Rechaza la solicitud pendiente. No crea nada. El dispositivo lo verá una vez (`rejected`)." + _NOSTORE,
    responses={
        200: _ok(
            PairingRejected,
            "Solicitud rechazada.",
            ("rejected", "Rechazada", {"id": "k3x9Qd2LmP0aRtUv", "rejected": True}),
        ),
        404: R404_SESSION,
        409: error_response(
            "La solicitud ya no está pendiente.", ("done", "Ya resuelta", "err.pairing.not_pending", {})
        ),
    },
)
