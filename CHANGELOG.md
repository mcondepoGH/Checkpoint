# Cambios

## Sin publicar

## 1.2.1 (2026-11-09)

### Correcciones

- El botón de tema muestra solo el icono sol/luna en todos los viewports.
- El botón de salir recupera su aspecto anterior (corrige el efecto colateral de 1.2.0).

### Novedades

- Nueva prop `iconOnly` en Button.

## 1.2.0 (2026-11-09)

### Novedades

- Escala tipográfica tokenizada en rem (texto normal de 15px).
- Componentes de UI compartidos (Button, Alert, Badge, Pill, Select, Checkbox, Switch, Input), con un único estilo cada uno.
- Icono sol/luna en el botón de tema en todos los viewports; el botón de salir también lleva icono en escritorio.

## 1.1.1 (2026-11-09)

### Correcciones

- Barra superior en móvil: se ven todas las pestañas completas sin scroll, el selector de idioma muestra un código corto centrado y el tema se cambia con un icono sol/luna.
- Tarjeta de sincronización programada: muestra solo la próxima ejecución.

## 1.1.0 (2026-11-08)

### Novedades

- Interfaz en **español e inglés**. Selector de idioma en la cabecera, una vez iniciada la sesión (Automático, Español, English; la pantalla de acceso no lleva selectores de idioma ni de tema); la elección se recuerda en el navegador y se aplica sin recargar. Fechas, tamaños, duraciones y plurales siguen el idioma activo.
- Variable opcional `CHECKPOINT_LANG` (`es` o `en`, por defecto `es`): idioma por defecto del servidor. Sin elección guardada en el navegador se usa este; «Automático» sigue usando el idioma del navegador. Un valor no soportado se ignora (español) y se avisa en el log de arranque. Comentada en `docker-compose.yml` y en `.env.example`.
- `GET /api/public` (sin sesión) informa del idioma por defecto para la pantalla de acceso.

### Cambios en el contrato de la API

El backend ya no devuelve texto para mostrar: devuelve códigos y parámetros y el frontend traduce (`frontend/src/locales/*.json`). Quien consuma la API desde fuera debe tenerlo en cuenta. Donde sigue habiendo un campo `message`, es un texto técnico de respaldo (el código con sus parámetros), no traducido.

| Dónde | Antes | Ahora |
|---|---|---|
| Errores HTTP (`detail`) | texto | `{"code": "err.<módulo>.<causa>", "params": {...}}` |
| `errors` de las respuestas 422 (config, ajustes, scheduler) | `{"campo": "texto"}` | `{"campo": {"code", "params"}}` (causas anidadas en `params.cause` / `params.causes`) |
| Estado de una sincronización (`GET /api/status`, evento `done` del stream) | `message` con texto | `code` y `params` (`message` es texto técnico de respaldo) |
| `error` de `GET /api/config` y del evento `config` (config.yaml inválido; `Snapshot.error`) | texto | `{code, params}` |
| `POST /api/config/restore`, `POST /api/versions/{juego}/restore` | `message` con texto | `code` y `params` (más `message` técnico) |
| `POST /api/devices/test` | `message` con texto | `code` y `params`; con varias rutas, `results` con `code`/`params` por ruta |
| `GET /api/scheduler` (`last_status`) y `GET /api/scheduler/history` (entradas y juegos) | `message` con texto | `code` y `params`; las entradas guardadas antes de este cambio se leen tal cual (solo `message`, en español) |

Se mantienen en español: la CLI, los logs internos del servidor y las líneas del log técnico de cada ejecución.

## 1.0.0 (2026-11-08)

Primera versión estable.

### Novedades

- Comprobación de actualizaciones en instalación nativa, con canal Estable o Pruebas (pre-releases). En Docker no se aplica.
- Imagen publicada en GHCR con las etiquetas `latest` (estable), `beta` (pre-releases) y la versión fija.
- La versión instalada se muestra en el pie de la interfaz.
- El modo de prueba se llama «Simulación (dry-run)» en la interfaz y en los registros.
- El `docker-compose.yml` usa la imagen publicada (`ghcr.io/mcondepogh/checkpoint:latest`) y solo pasa las variables obligatorias.
- Sincronización automática con registro de ejecuciones y política ante conflictos configurable.

### Cambios incompatibles

Si vienes de una versión anterior (0.x o 1.0.0-rc), revisa esta lista antes de actualizar. No hay migrador automático.

| Qué cambia | Qué hacer |
|---|---|
| Se elimina el prefijo `SAVESYNC_*` (variables de entorno y comando `savesync` de la imagen). | Renombra las variables a `CHECKPOINT_*` y usa `checkpoint` en `docker exec`. |
| `name` es obligatorio en cada dispositivo y cada juego. Un `config.yaml` antiguo (indexado por nombre, sin `name`) ya no se convierte. | Añade `name: ...` a cada dispositivo y juego. La clave del mapa es el id interno y no debe cambiar: así se conservan los saves, versiones y logs ya guardados en `data/`. |
| `os: steamos` ya no es válido. | Cámbialo a `os: linux`. |
| Variables de entorno eliminadas: `CHECKPOINT_AUTO_*`, `CHECKPOINT_UPDATE_*`, `CHECKPOINT_CONFIG`, `CHECKPOINT_DATA`, `CHECKPOINT_SSH_KEY`, `CHECKPOINT_KNOWN_HOSTS`, `CHECKPOINT_STATIC`, `CHECKPOINT_SSH_TIMEOUT`, `CHECKPOINT_VERSION_FILE` y `CHECKPOINT_IN_DOCKER`. | Quítalas del `.env` y del compose. La sincronización automática y la comprobación de versiones se ajustan desde Configuración. Sin Docker, usa `CHECKPOINT_HOME_DIR` para cambiar la carpeta base. `CHECKPOINT_RUNTIME=docker\|native` sustituye a `CHECKPOINT_IN_DOCKER`. |
| Variables que se conservan: `CHECKPOINT_USER`, `CHECKPOINT_PASSWORD`, `CHECKPOINT_PORT`, `CHECKPOINT_HOST`, `CHECKPOINT_HOME_DIR`, `CHECKPOINT_SESSION_HOURS`, `CHECKPOINT_COOKIE_SECURE`, `CHECKPOINT_TRUST_PROXY` y `CHECKPOINT_RUNTIME`. | Nada. |
| En Docker la comprobación de nuevas versiones no se aplica nunca (antes se podía forzar con `CHECKPOINT_UPDATE_CHECK=1`). | Actualiza la imagen a mano (`docker compose pull` o reconstruye). La versión instalada se ve en el pie de la interfaz. |
| La zona horaria por defecto de `docker-compose.yml` es `UTC` (antes `Europe/Madrid`). | Añade `TZ: ...` en `environment:` del compose si quieres otra. |
| Endpoints eliminados: `GET /api/version` (la versión instalada viaja en el campo `actual` de `GET /api/updates`) y `GET /api/config/status`. | Si los usabas desde fuera, usa `/api/updates` y `/api/config`. |
| Se dejan de leer formatos antiguos de datos: estados de `data/status/*.json` con el nombre en `game`, historial de la sync automática indexado por nombre y la caché de versiones sin canal. | Nada: se regeneran solos en la siguiente ejecución o comprobación. |
