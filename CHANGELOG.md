# Cambios

## Sin publicar

### Cambios

- Historial del cierre automático: cuando no hay checkpoint de cierre queda una entrada (disparador «Cierre del juego», con dispositivo y juego, icono y texto en es y en) con un código estable: `err.hook.never_seen` (proceso no visto a tiempo, vigilancia descartada), `err.hook.busy` (ejecución en curso o lock ocupado, sin reintento), `err.hook.game_removed` (el juego ya no está en la configuración) y `err.hook.checkpoint_failed` (error del checkpoint, solo el tipo de excepción). «Omitido» y «error» se distinguen por el resultado. `GET /api/games/{juego}/hook-status` añade `code` y `params` a `last`, y el panel «Último aviso» muestra el motivo. Solo se registra: la sincronización no cambia.
- Límite de frecuencia del login y de `/api/hook/*`: sin cambio de umbrales; ahora hay tests que fijan su comportamiento (escala de esperas, sin escalada mientras está bloqueado, por IP, `X-Forwarded-For` con y sin `CHECKPOINT_TRUST_PROXY`) y está documentado en «Seguridad». Los fallos de una IP sin actividad durante 1 h se olvidan, para que el mapa en memoria no crezca sin límite.

## 1.6.0 (2026-11-10)

### Novedades

- API key de usuario en el perfil (sección «API key» del menú): generar, ver siempre con botón de copiar, regenerar (con confirmación; invalida la anterior) y revocar. Nuevos `GET|POST|DELETE /api/profile/apikey`. Se guarda cifrada en `data/profile/<id>/apikey.enc`; se cifra con Fernet (librería `cryptography`, nueva dependencia con wheels musllinux; clave derivada de `hub.secret`, 0600, junto a `config.yaml`, fuera de `data/`; el id de usuario va dentro del payload). Si la copia de seguridad cubre `/config` y `/data` juntos, excluye `hub.secret`.
- `GET /api/hook/ping` con `Authorization: Bearer ck_...` y router `/api/hook/*` con autenticación propia por API key (sin cookie ni Origin; alcance mínimo; `401` único para cualquier fallo; límite de frecuencia por IP con `429`). Base del futuro aviso de apertura de juego.
- `POST /api/hook/{juego}/opened?device=<dispositivo>` (Bearer): aviso de apertura de juego con sincronización previa bloqueante (copia al dispositivo el save más nuevo del hub antes de arrancar). Política de conflictos siempre `skip` (ignora la del juego y la global del scheduler): ante un conflicto no toca nada, avisa con `outcome: conflict` y queda en el historial; el hook nunca resuelve solo. Fallo de sync o dispositivo sin conexión: `200` con `outcome`, sin reintentos; ejecución en curso: `409`. Nuevo disparador `hook` («Aviso del juego») en el historial. Docs de lanzadores (Steam, Lutris) en el README, sección «Hooks».
- Cierre automático: tras `opened`, el hub vigila el proceso del juego en ese dispositivo (nuevo `backend/app/watcher.py`; sondeo del `process` con el transport) y, al cerrarse, hace el checkpoint solo, sin hook de cierre en el lanzador. Una vigilancia por juego (un nuevo `opened` la reemplaza); sondeo cada 15 s, espera de 10 s tras dejar de verlo y descarte si no se ve abierto en 2 min (`CHECKPOINT_HOOK_POLL`, `CHECKPOINT_HOOK_SETTLE`, `CHECKPOINT_HOOK_FIRST_SEEN`). Si el dispositivo deja de responder se trata como cierre. El checkpoint usa la política `skip`, el mismo lock que `opened` y no se reintenta si aborta o el lock está tomado. Nuevo disparador `hook_closed` («Cierre del juego» / «Game closed») en el historial. `opened` añade `watching` (y `watch_reason: "no_process"` si el juego no tiene `process`). Nuevo `GET /api/hook/watches` (Bearer) con las vigilancias activas. Las vigilancias viven en memoria: si el hub se reinicia se pierden y lo cubre el cron.

- Sección «Lanzadores» en Configuración (tarjeta propia tras la lista de juegos, plegada por defecto con Mostrar/Ocultar): un solo panel para todos los juegos con selector de juego (se recuerda en el navegador), selector de dispositivo, pestañas Steam / Steam Deck, Lutris, Heroic (sin verificar) y Windows (Playnite) con el comando completo listo para copiar (API key, id del juego y dispositivo codificados; URL del hub editable y recordada en el navegador), nota de dónde se pega, aviso de HTTP, de que falta la API key o de que el juego no tiene `process`. Debajo, «Último aviso» por dispositivo del juego elegido (tipo, hace cuánto, resultado y estado de la vigilancia; se refresca cada 15 s mientras el panel está desplegado). La tarjeta de cada juego guardado tiene el enlace «Ver comandos de lanzador», que elige ese juego y baja hasta el panel. Nuevo `GET /api/games/{juego}/hook-status` (sesión); las entradas de historial `hook` y `hook_closed` guardan el campo `device` (las antiguas, sin él, siguen siendo válidas). Nuevos componentes de UI `Tabs` y `CopyBox`; comandos en `frontend/src/launchers.js`.

- Indicador de vigilancia en la pestaña Sincronizar: la tarjeta de cada juego vigilado lleva un borde del color de su estado (discontinuo y ámbar sin latido) y una franja inferior con icono + texto: «Esperando a que arranque · dispositivo», «Jugando en dispositivo» con «desde HH:MM» (el icono pulsa, sin animación con `prefers-reduced-motion`), «Cerrando · guardando checkpoint…» o «Sin latido» (último sondeo con más de 3 intervalos `poll`). Sin vigilancia la tarjeta no cambia. El contador «N juegos en vigilancia» con lista desplegable (juego, dispositivo y estado) vive en la barra superior (ver más abajo). En móvil (<=640 px) la franja salta de línea, el nombre del juego se limita a 2 líneas, el chip de escritorio dice «● Vigilando · N ▾» (plural invariable) y se reduce a icono + número («99+» por encima de 99; el texto completo queda en `aria-label`) y la lista ocupa el ancho con 8 px de margen y scroll propio; chip y filas de la lista miden al menos 44 px (valor local, sin tocar `$touch`). Se actualiza consultando cada 5 s el nuevo `GET /api/watches` (sesión; `{now, watches}`); las vigilancias (también en `/api/hook/watches`) añaden `last_poll` y `poll`. Nuevos componentes de UI `WatchBar` y `WatchStatus` e icono `eye`; cadenas en es y en.

- Contador de vigilancia en la barra superior del hub, visible desde cualquier pestaña y oculto si no hay vigilancia (nuevo `WatchSummary`). La consulta de `/api/watches` sube a `App` (hook `useWatches`, una sola consulta cada 5 s con la pestaña visible, que además refresca al volver a ella): la barra y las tarjetas de Sincronizar comparten datos. Sin cambios de backend.
- Aviso de actualización en móvil: por debajo de 480 px sale de la barra y pasa al menú del perfil como entrada «Actualizar a vX.Y.Z» (es/en) que abre el mismo diálogo; el avatar lleva un punto con texto accesible mientras haya actualización aplicable. En >=480 px se queda como estaba.

### Cambios

- Menú del perfil reorganizado por grupos con separador y rótulo accesible: identidad; «Actualizar a vX.Y.Z» (móvil) justo debajo; Preferencias (Idioma y Tema con el mismo patrón de fila: icono + etiqueta + valor a la derecha, 44 px); Integración (API key, ahora plegable y cerrada por defecto, con `aria-expanded`; el contenido sigue montado); Cuenta (Salir y la versión debajo, discreta). Nuevas cadenas `profile.group.*` y `profile.themeLabel` (es/en; sustituye a `profile.theme`), iconos `globe` y `chevron`, `LanguageSelect` acepta `row`.
- Barra superior: el relleno compacto de las pestañas (.3rem) se aplica hasta 400 px (antes solo <=380 px; a 390 px iban con 1-5 px de margen) y, a <=340 px, el chip de vigilancia usa padding .3rem y gap .2rem (sigue en 44 px) para que quepa a 320 px.
- Pulso del punto verde de «Jugando en…» (franja de la tarjeta vigilada) ovalado en vez de circular: el icono era un ítem de rejilla de 1.1em de ancho y alto de línea, y el anillo (`box-shadow`) copiaba esa caja. Ahora `.watch-ico` es un cuadrado explícito (`width = height`, `aspect-ratio: 1`, `align-self: center`, `border-radius: 50%`); mismo blindaje en el punto de `WatchStatus`, el del chip de la barra y `.upd-dot`. Chip de escritorio: «● Vigilando · N ▾» en lugar de «N juegos en vigilancia» (plural invariable; `aria-label` conserva el texto completo; móvil sin cambios).
- Icono de la franja de la tarjeta vigilada descentrado (el punto `●` caía abajo a la derecha por las métricas del glifo; ◌ ↻ ⚠ igual y según la fuente del dispositivo). Ya no hay glifos de texto: `WatchBar` renderiza `.watch-ico > .watch-mark`; `running` es un punto CSS (`::before` al 55 %, centrado con `inset: 0; margin: auto`), `waiting` un anillo CSS de 2 px, `settling` el icono SVG nuevo `spinner` (gira sobre un cuadrado, sin desplazar el centro) y `stale` el SVG `alert`. La marca es un cuadrado de 1.1em con `place-items: center`; la caja `.watch-ico` mide el interlineado de la franja (`$watch-lh`) y va con `align-self: start`, así que en móvil, con el texto en varias líneas, el icono queda alineado con la primera. El pulso sigue circular; `prefers-reduced-motion` intacto. Sin cambios en `WatchStatus`, el punto del chip ni `.upd-dot` (ya son cajas cuadradas con fondo).
- Las cadenas `sync.watch.*` (franja, contador y lista de vigilancia) estaban dentro de `app.tab.sync` en es y en y la interfaz habría mostrado la clave en vez del texto; pasan a `sync.watch` (con test).
- Logs de nivel DEBUG en los endpoints de la API (logger `checkpoint.api`): una línea por petición `/api/*` (método, ruta, nombres de los parámetros de la query, estado, duración, IP) y detalle por endpoint (entrada con parámetros, resultado, errores y duración en `opened`, sync, dispositivos, config, versiones, API key y auth de hooks). Nunca se registran cabeceras, cookies, cuerpos, contraseñas, API keys ni tokens. Nuevo `CHECKPOINT_LOG_LEVEL` (`INFO` por defecto; `DEBUG` para verlos): con el nivel por defecto la salida no cambia.
- Trazas DEBUG del flujo apertura, vigilancia, cierre y sync (loggers `checkpoint.watcher`, `checkpoint.hook`, `checkpoint.sync`, `checkpoint.transport`): armado, reemplazo y cancelación de vigilancias, cada sondeo con su resultado, transiciones de estado, inicio del checkpoint de cierre y sus salidas silenciosas, duración y resultado de cada ejecución del hook, inicio y fin de cada sync con duración, huellas por lado (nº de ficheros, bytes), decisión, duración de pull/push y de cada comando ssh/rsync. Nunca rutas de claves, argumentos de comandos ni contenidos. El log INFO `hook ... resultado=` añade `code=` y `duración=`. Si falla el guardado en el historial tras un aviso se registra un warning con el tipo de excepción (antes se ignoraba en silencio); el comportamiento no cambia.
- `CopyBox` acepta `what` y el botón de copiar pasa a «Copiar comando de Steam» / «Copiar clave API» (antes «Copiar» a secas).
- La key del perfil usa el nuevo `CopyBox` (misma apariencia y comportamiento; clases `copybox-*` en lugar de `apikey-field` / `apikey-copy`).
- Sección «API key» del perfil rediseñada: bloque con fondo y encabezado con icono, key completa ajustada en varias líneas (antes se cortaba), copiar como botón de icono (copia → check), Regenerar y Revocar (variante `danger`, con borde en el color de error) del mismo tamaño en una fila, texto de ayuda de una frase y aviso de HTTP como `Alert` compacto. Nuevos iconos `key`, `copy` y `check`; `Alert` admite `compact`.

- La lógica de ejecutar un juego y traducir su resultado se extrae del ciclo del scheduler a `Scheduler.run_game` (sin cambios de comportamiento).
- `Input` (componente de UI) acepta `ref`; la función de copiar al portapapeles pasa a `src/clipboard.js` y la comparten `PublicKey` y la API key.

## 1.5.1 (2026-11-09)

### Cambios

- El registro de ejecuciones de la sincronización automática guarda como máximo las últimas 50 ejecuciones (límite fijo, antes 200). Un historial existente con más se recorta solo al leerlo o en la siguiente ejecución. Se mantiene el tope de 30 días. `GET /api/scheduler/history` acepta `limit` de 1 a 50 (por defecto 50).

## 1.5.0 (2026-11-09)

### Novedades

- Cabecera más limpia: pestañas y, en el extremo derecho, un icono de perfil que abre un menú con la foto, el nombre, el idioma, el tema, "Salir" y la versión. En móvil, el icono de la app va a la izquierda y la barra cabe sin scroll lateral.
- Foto de perfil guardada en el servidor (se ve igual en todos los dispositivos): se recorta al centro y se reduce a 256x256 en el navegador; JPG, PNG o WebP de hasta 2 MB. Nuevos endpoints `GET /api/profile`, `GET|PUT|DELETE /api/profile/photo`. La foto vive en `data/profile/<id>/` (id = SHA-256 truncado del usuario), lista para un futuro registro de usuarios; una foto en la ruta antigua `data/profile/photo.<ext>` se migra sola.

### Cambios

- El selector de idioma, el botón de tema y "Salir" salen de la cabecera y pasan al menú del perfil.

## 1.4.0 (2026-11-09)

### Novedades

- Instalable como app (PWA): manifest, iconos y aviso de instalación en móvil (instrucciones en iOS; botón "Instalar" en Android con HTTPS).

## 1.3.0 (2026-11-09)

### Correcciones

- El botón de tema pasa a 20px, con el cuadro solo en hover/foco (corrige el icono minúsculo de 1.2.0 y 1.2.1).

### Novedades

- El botón de salir lleva icono y texto en escritorio y solo icono en móvil.
- La tarjeta de juego aparece plegada por defecto, con botón "Mostrar más/menos"; se despliega sola ante errores de validación en campos ocultos.
- Literal "Máx. de versiones".

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
