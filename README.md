<p align="center">
  <img src="docs/logo.svg" alt="Checkpoint" width="360">
</p>

# Checkpoint

![Licencia MIT](https://img.shields.io/badge/licencia-MIT-green)

Checkpoint mantiene sincronizadas las partidas guardadas de un juego entre dos dispositivos, por SSH, desde una interfaz web. Corre en Docker o directamente en un equipo (modo nativo); no se instala nada en los dispositivos.

- Sincroniza los guardados de un juego entre dos dispositivos y elige la copia más reciente.
- Interfaz web con tema gaming.
- Sincronización automática cada X horas, con registro de ejecuciones.
- Versiones y copias de seguridad de cada guardado, con restauración desde la UI.
- Modo de simulación (dry-run) y log en vivo.
- Configuración editable desde la UI o a mano.

## Cómo funciona

```
 Dispositivo A  <--- SSH --->  Checkpoint           <--- SSH --->  Dispositivo B
 (ruta del save)               copias + versiones                  (ruta del save)
```

- **Dispositivos**: equipos con servidor SSH (Windows o Linux) o, en modo nativo, el propio equipo donde corre Checkpoint («Este equipo»). Checkpoint entra por SSH con una clave que genera él mismo.
- **Juegos**: cada juego enlaza dos dispositivos y la carpeta de guardado en cada uno. Los nombres de dispositivos y juegos son libres (hasta 64 caracteres, con espacios, acentos y emojis; sin `/` ni `\`).
- **Sincronizar**: Checkpoint descarga los guardados, recuerda cuál era el estado tras la última sincronización y propaga el lado que ha cambiado. Si solo un dispositivo está conectado, lo compara con la copia del hub. Antes de sobrescribir guarda la copia perdedora como versión.
- **Versiones**: se conservan las últimas N de cada juego (`max_versions` global, 20 por defecto, 0 = sin límite; `keep_versions` lo sustituye en un juego) y se pueden restaurar desde la UI.

Solo la opción «gana el más reciente» de los conflictos usa fechas de modificación: mantén la hora sincronizada (NTP) en el servidor y en los dispositivos.

## Instalación

Requisitos: Docker y Docker Compose. Sin Docker, ver [Instalación sin Docker](#instalación-sin-docker).

1. Clona el repositorio:
   ```bash
   git clone https://github.com/mcondepoGH/Checkpoint.git && cd Checkpoint
   ```
2. Copia la plantilla y pon tu usuario y contraseña:
   ```bash
   cp .env.example .env     # edita CHECKPOINT_USER y CHECKPOINT_PASSWORD
   ```
3. Arranca (descarga la imagen publicada, `ghcr.io/mcondepogh/checkpoint:latest`):
   ```bash
   docker compose up -d
   ```
   `latest` es siempre la última versión estable. Para probar versiones preliminares usa `:beta` y para fijar una versión concreta `:X.Y.Z` (p. ej. `:1.0.0`); cámbialo en `image:` de `docker-compose.yml`. Para actualizar: `docker compose pull && docker compose up -d`. Ver «Publicación de versiones».
4. Abre `http://IP-DEL-SERVIDOR:8088`.

Variables (todas con prefijo `CHECKPOINT_`, salvo `TZ`). El `docker-compose.yml` solo pasa las obligatorias (`CHECKPOINT_USER` y `CHECKPOINT_PASSWORD`, tomadas del `.env`); para usar una opcional, añádela en `environment:` del servicio (p. ej. `TZ: Europe/London` o `CHECKPOINT_SESSION_HOURS: 24`), con su valor o como `${VARIABLE:-valor}` si la defines en el `.env`. La sincronización automática y la comprobación de versiones se ajustan desde la pantalla Configuración, no con variables.

| Variable | Por defecto | Descripción |
|---|---|---|
| `CHECKPOINT_USER` | (obligatoria) | Usuario de acceso a la web |
| `CHECKPOINT_PASSWORD` | (obligatoria) | Contraseña, en claro en el `.env` |
| `CHECKPOINT_PORT` | `8088` | Solo con `serve` (sin Docker): puerto de escucha. En Docker la web escucha siempre en el 8088 del contenedor; para cambiar el puerto del equipo edita `ports:` en el compose |
| `CHECKPOINT_HOST` | `127.0.0.1` | Solo con `serve` (sin Docker): dirección de escucha |
| `CHECKPOINT_HOME_DIR` | según el sistema | Solo sin Docker: carpeta base de `config/`, `data/` y `keys/` (ver más abajo) |
| `CHECKPOINT_SESSION_HOURS` | `12` | Horas de validez de la sesión |
| `CHECKPOINT_COOKIE_SECURE` / `CHECKPOINT_TRUST_PROXY` | `0` | Pon `1` tras un proxy inverso con HTTPS |
| `CHECKPOINT_RUNTIME` | automático | `docker` o `native`: fuerza el modo (la imagen lo fija a `docker`) |
| `CHECKPOINT_LANG` | `es` | Idioma por defecto de la interfaz: `es` o `en` (también `en-US`, `EN`…). Opcional; sin marcar es español. Un valor no soportado se ignora (español) y se avisa en el log de arranque. Ver [Idioma](#idioma) |
| `TZ` | `UTC` | Zona horaria de los registros y la sincronización automática (p. ej. `Europe/London`); solo Docker, se añade a `environment:` |

Si la contraseña lleva `$`, ponla entre comillas simples.

## Instalación sin Docker

Modo «nativo»: Checkpoint corre directamente en un equipo. Es la única forma de usar el dispositivo **«Este equipo»** (ver más abajo).

**Requisitos**: Python 3.12, Node.js (solo para compilar la web) y, si vas a sincronizar dispositivos remotos, `rsync` y el cliente OpenSSH (`ssh`, `ssh-keygen`, `ssh-keyscan`) en el `PATH`. Con «Este equipo» como único tipo de dispositivo no hacen falta.

```bash
git clone https://github.com/mcondepoGH/Checkpoint.git && cd Checkpoint
python3 -m venv .venv && . .venv/bin/activate
pip install -r backend/requirements.txt
(cd frontend && npm ci && npm run build)            # genera frontend/dist, que se sirve solo
export CHECKPOINT_USER=usuario CHECKPOINT_PASSWORD='cámbiala'
cd backend && python -m app.cli serve               # http://127.0.0.1:8088
```

Equivale a `python -m uvicorn app.main:app_factory --factory --port 8088`, pero `serve` además comprueba las credenciales y escucha solo en `127.0.0.1` por defecto (usa `--host 0.0.0.0` o `CHECKPOINT_HOST` para abrirlo a la red; ver [Seguridad](#seguridad)).

Sin Docker las carpetas no son `/config`, `/data` y `/keys`, sino (se crean solas):

| Sistema | Carpeta base (`config/`, `data/`, `keys/` dentro) |
|---|---|
| Linux | `$XDG_DATA_HOME/checkpoint` o `~/.local/share/checkpoint` |
| macOS | `~/Library/Application Support/checkpoint` |
| Windows | `%APPDATA%\checkpoint` |

Para cambiar la carpeta base usa `CHECKPOINT_HOME_DIR`. También `CHECKPOINT_HOST` y `CHECKPOINT_PORT` para `serve`. La web compilada se sirve desde `frontend/dist`.

Cómo se decide si es Docker o nativo: la imagen fija `CHECKPOINT_RUNTIME=docker`; si no, se mira si existe `/.dockerenv` o `/run/.containerenv`. `CHECKPOINT_RUNTIME=docker|native` fuerza el resultado.

La CLI (`checkpoint list|versions|sync|serve`; en Docker, `docker exec checkpoint checkpoint list`) acepta el id o el nombre de cada juego.

Arranque al iniciar sesión en Linux (unidad de usuario de systemd, `~/.config/systemd/user/checkpoint.service`; ajusta las rutas):

```ini
[Unit]
Description=Checkpoint

[Service]
WorkingDirectory=/home/usuario/Checkpoint/backend
EnvironmentFile=/home/usuario/.config/checkpoint.env     # CHECKPOINT_USER=... y CHECKPOINT_PASSWORD=...
ExecStart=/home/usuario/Checkpoint/.venv/bin/python -m app.cli serve
Restart=on-failure

[Install]
WantedBy=default.target
```

```bash
chmod 600 ~/.config/checkpoint.env && systemctl --user enable --now checkpoint
```

### «Este equipo»

En modo nativo, cada dispositivo puede marcarse como **Este equipo**: el mismo equipo donde corre Checkpoint. Se omite todo SSH (host, usuario, puerto, clave) y el motor lee y escribe directamente en sus carpetas, con las mismas garantías que en remoto (copia a temporal, huellas, escritura atómica con carpeta nueva y renombrado, fecha de modificación conservada, proceso abierto, conflictos, versiones). Solo puede haber uno. En vez de «Probar conexión» hay **Comprobar carpeta**, que verifica que la ruta existe (o se puede crear) y es legible y escribible. Los enlaces simbólicos dentro de la carpeta de saves no se siguen ni se sincronizan.

**En Docker la casilla no aparece** (allí «este equipo» sería el contenedor) y un `config.yaml` con `local: true` se rechaza con el error «“Este equipo” solo está disponible cuando Checkpoint se ejecuta sin Docker».

```yaml
devices:
  pc-1a2b3c4d:     {name: "Mi PC", local: true, os: linux}      # sin host, user ni port
  laptop-5e6f7a8b: {name: "Portátil", host: 192.0.2.11, user: usuario, os: linux, port: 22}
```

### Plataformas probadas

- **Linux**: probado (suite automática de pruebas, incluido el motor de sincronización con «Este equipo» sobre el sistema de ficheros real, y un arranque real con `serve`).
- **macOS y Windows nativo**: **experimental, no verificado**. El código contempla `pgrep`/`tasklist`, el bloqueo con `msvcrt` y las rutas `C:/...`, pero solo se ha comprobado con simulaciones. Con Windows como equipo anfitrión, además, `rsync` no existe de serie, así que los dispositivos remotos no están soportados ahí; «Este equipo» sí está pensado para funcionar.
- El acceso por SSH a dispositivos remotos no está cubierto por pruebas contra un servidor SSH real (las pruebas lo simulan).

## Primeros pasos

1. En **Configuración**, copia la **clave pública SSH** (botón Copiar). Solo hace falta si vas a usar dispositivos remotos.
2. Añádela a `authorized_keys` de cada dispositivo. El botón **?** junto a la clave muestra los comandos para Linux y Windows, incluida la activación del servidor SSH.
3. Añade los **dispositivos** (nombre, host, puerto, usuario, sistema) y pulsa **Probar conexión**. La primera vez se guarda la huella del host. Sin Docker puedes marcar uno como **Este equipo** (sin SSH).
4. Añade los **juegos**: elige dos dispositivos y la carpeta de guardado en cada uno (ruta absoluta, por ejemplo `/home/usuario/.local/share/Juego/Saves` o `C:\Users\Usuario\AppData\Local\Juego\Saves`).
5. Ve a **Sincronizar**. Prueba primero con **Simulación (dry-run)** y después sin él.

## Sincronización automática

En **Configuración > Sincronización automática** activa la opción y elige cada cuántas horas se ejecuta (de 0.25 a 168). Cada ciclo sincroniza todos los juegos; si uno falla, los demás continúan. Debajo se muestra el **Registro de ejecuciones** (las últimas 50, límite fijo) con resultado por juego y detalle al hacer clic. Sin ajustes guardados, está desactivada y el intervalo es de 24 horas.

## Nuevas versiones

Checkpoint comprueba si hay una versión nueva consultando las Releases públicas de GitHub (solo HTTPS, por defecto solo versiones estables: se ignoran borradores y pre-releases). Si la hay, aparece la insignia **Nueva versión disponible** en la cabecera, con la versión instalada, la nueva y sus notas. No actualiza nada: en Docker, actualiza la imagen (`docker compose pull` si usas la imagen publicada, o reconstruye si la construyes tú) y recrea el contenedor; en instalación nativa, descarga la nueva versión y reinicia.

**Solo en instalación nativa.** En Docker la versión la fija la imagen: la comprobación no se aplica (no hace ninguna petición a internet, no lee ni escribe caché y no aparecen la insignia ni la tarjeta «Comprobar actualizaciones»). La versión instalada se muestra siempre en el pie de la interfaz. Cómo se decide Docker o nativo: ver «Instalación sin Docker».

- La versión instalada sale del fichero `VERSION` de la raíz del repositorio (la imagen lo incluye). Sin él, o en desarrollo, es «desconocida» y no se ofrece ninguna actualización. El repositorio consultado es siempre el de este proyecto.
- El resultado se guarda en memoria y en `data/update_cache.json` durante 6 horas. Un fallo de red es silencioso: se conserva el último resultado y se reintenta pasados unos minutos.
- Se desactiva en **Configuración > Comprobar actualizaciones** (viene activada). Desactivada, no se hace ninguna petición a internet. El botón **Comprobar ahora** fuerza la consulta (máximo una por minuto).
- **Canal** (Configuración > Comprobar actualizaciones): **Estable** (por defecto) solo ofrece Releases normales; **Pruebas** (`beta`) ofrece también pre-releases (nunca borradores), que pueden fallar. En Pruebas se ofrece la versión más alta entre estables y preliminares, con el orden de semver: `1.0.0-rc.1` < `1.0.0-rc.2` < `1.0.0`. Un tag con sufijo (`-rc.1`) cuenta como preliminar aunque GitHub no lo marque. Cambiar de canal descarta el resultado guardado y vuelve a consultar. Nunca se ofrece bajar de versión: desde una preliminar en canal Estable solo se avisa cuando haya una estable mayor. La insignia y el diálogo marcan «preliminar» cuando procede.
- La etiqueta de imagen `beta` la publica el workflow de release (ver «Publicación de versiones»); el canal solo cambia qué avisos se muestran, no la imagen que ejecutas.
- API (requiere sesión): `GET /api/updates[?refresh=true]` (incluye `actual`, la versión instalada, `aplicable`, `canal` y `prerelease`, si la versión ofrecida es preliminar) y `PUT /api/updates` con `{"enabled": true|false, "channel": "stable"|"beta"}` (parcial: basta uno de los dos; valor no válido, 422). En Docker, `GET` devuelve `aplicable: false` con campos neutros (sin error, sin red) y `PUT` responde 409.

## Publicación de versiones

Al subir un tag `vX.Y.Z` el workflow `.github/workflows/release.yml` publica la imagen en GHCR y crea la GitHub Release (la que consulta la comprobación de nuevas versiones).

1. Edita `VERSION` con la versión nueva (sin `v`), por ejemplo `1.0.0` o `1.0.0-rc.1`, y pon la misma en `frontend/package.json` y `frontend/package-lock.json` (`npm test` lo comprueba). Haz commit en `main`.
2. Crea un tag anotado con el mismo número: `git tag -a v1.0.0 -m "v1.0.0"`.
3. Sube el commit y el tag: `git push origin main v1.0.0`.

Si `VERSION` no coincide con el tag, el workflow falla antes de construir nada. Un tag con sufijo (`-rc.1`, `-beta.2`) se publica como pre-release.

Etiquetas de imagen (`ghcr.io/<owner>/checkpoint`, con `<owner>` en minúsculas):

| Tag | Etiquetas de imagen | Release |
|---|---|---|
| `v1.0.0` (estable) | `v1.0.0`, `1.0.0`, `latest` | normal |
| `v1.0.0-rc.1` (pre-release) | `v1.0.0-rc.1`, `1.0.0-rc.1`, `beta` | pre-release |

La imagen se construye solo para `linux/amd64`; para añadir `arm64` hay instrucciones en un comentario del workflow.

Uso en compose:

```yaml
services:
  checkpoint:
    image: ghcr.io/<owner>/checkpoint:latest   # o una versión fija, p. ej. :1.0.0, o :beta
```

Tras la primera publicación, el paquete de GHCR es privado por defecto: cámbialo a público en la página del paquete (Package settings > Danger Zone > Change visibility) si quieres bajarlo sin autenticarte.

## Conflictos

Hay conflicto cuando los dos dispositivos han cambiado desde la última sincronización y su contenido es distinto (o, en la primera sincronización, ya difiere). Checkpoint nunca lo decide por la fecha a ciegas.

- **Sincronización automática**: `on_conflict` en Configuración > Sincronización automática. `skip` (por defecto) no guarda nada y marca el juego como «Conflicto»; `newest` hace ganar el save más reciente (si las fechas difieren menos de 2 s, se omite). Un juego puede sustituirlo con `on_conflict` en `config.yaml`.
- **Sincronización manual**: siempre pregunta. Un popup ofrece cancelar, «Gana el más reciente» o elegir qué dispositivo gana, con fecha y tamaño de cada uno. En la CLI: `checkpoint sync JUEGO --resolve newest|device:DISPOSITIVO` (sale con código 3 si hay conflicto).

En todos los casos la copia perdedora se guarda antes en versiones. En la primera sincronización de cada juego (aún sin estado guardado) el hub es la única referencia: si ambos lados difieren, se trata como conflicto.

## Configuración

| Carpeta | Contenido |
|---|---|
| `config/` | `config.yaml` (dispositivos y juegos) |
| `keys/` | clave SSH generada y `known_hosts` |
| `data/` | copias, versiones, logs, registro de la sync automática y la foto de perfil (`data/profile/`) |

Se crean solas al arrancar. `config.yaml` se edita desde la UI (valida, muestra diff y guarda copias) o a mano; ver [`config.example.yaml`](config.example.yaml). Ejemplo mínimo:

```yaml
devices:
  pc-1a2b3c4d:     {name: "Mi PC", host: 192.0.2.10, user: usuario, os: windows, port: 22}
  laptop-5e6f7a8b: {name: "Portátil", host: 192.0.2.11, user: usuario, os: linux, port: 22}
games:
  ejemplo-0a1b2c3d:
    name: "Ejemplo"
    devices: [pc-1a2b3c4d, laptop-5e6f7a8b]
    paths:
      pc-1a2b3c4d: "C:/Users/usuario/AppData/Local/Ejemplo/Saves"
      laptop-5e6f7a8b: "/home/usuario/.local/share/Ejemplo/Saves"
    keep_versions: 5           # opcional: sustituye a max_versions para este juego
```

La clave de cada juego y dispositivo es su **ID interno**, que no cambia nunca; `name` es solo una etiqueta y se puede renombrar libremente sin perder saves, versiones ni logs. `name` es obligatorio en cada juego y dispositivo. La CLI y la API aceptan el ID o el nombre.

## Idioma

La interfaz está en español e inglés. El selector de idioma está en el menú del perfil (el icono redondo del extremo derecho de la cabecera, una vez iniciada la sesión; la pantalla de acceso no lleva selectores y usa el idioma y tema ya guardados). Ofrece **Automático**, **Español** y **English**, y recuerda la elección en ese navegador (`localStorage`, clave `checkpoint.lang`); se aplica al instante, sin recargar. El mismo menú tiene el cambio de tema (automático, claro, oscuro; muestra un sol o una luna según el tema efectivo) y **Salir**.

Orden de prioridad:

1. La elección manual guardada en el navegador (`Español` o `English`).
2. Si se eligió **Automático**, el idioma del navegador (si no es uno soportado, el de 3).
3. El idioma por defecto del servidor: `CHECKPOINT_LANG` (`es` o `en`) o español si no está marcado.

Es decir, sin elección guardada manda el servidor, no el navegador: así una instalación se puede dejar en inglés para todos los usuarios que no hayan elegido. Para fijarlo en Docker, descomenta `CHECKPOINT_LANG` en el `environment:` de `docker-compose.yml` (o añádelo al `.env`).

El backend no traduce nada: devuelve códigos y parámetros (`{"code": "err.sync.dry_run", "params": {...}}`) y la traducción vive en `frontend/src/locales/*.json`. Para añadir un idioma, crea `<código>.json` con las mismas claves que `es.json` (el test `locales.test.mjs` lo comprueba), regístralo en `frontend/src/locales/index.js` y añade el código a `SUPPORTED_LANGS` de `backend/app/settings.py`.

Se mantienen en español a propósito: la CLI, los logs internos del servidor, el log técnico de cada ejecución (las líneas del registro en vivo de «Sincronizar») y los textos de estado antiguos guardados en `data/` antes de este cambio.

API: `GET /api/public` (sin sesión) devuelve `{"default_lang": "es"|"en"}`.

## Perfil y foto

El icono redondo del extremo derecho de la cabecera abre el menú del perfil: foto, nombre (el usuario del login, `CHECKPOINT_USER`), idioma, tema, **Salir** y la versión instalada. Sin foto se ve una silueta.

La foto se guarda en el servidor (`data/profile/<id>/photo.jpg|png|webp`, nombre fijo; `<id>` es un hash SHA-256 truncado del nombre de usuario, nunca el nombre en crudo), así que se ve igual desde cualquier dispositivo. El navegador la recorta al centro, la reduce a 256x256 y la sube como WebP (JPEG si no puede). Entrada máxima: 2 MB, solo JPG, PNG o WebP; se valida en el navegador y en el servidor (tipo real por los bytes, sin dependencias nuevas: firma y estructura mínima, no se decodifica la imagen). Se sirve con el tipo fijado por el servidor, `nosniff`, `Content-Security-Policy: sandbox` y `ETag`.

API (requiere sesión; las escrituras comprueban el origen como el resto):

- `GET /api/profile`: `{"name": "...", "photo": {"version": "..."} | null}`. `version` sirve de cache-busting (`/api/profile/photo?v=<version>`).
- `GET /api/profile/photo`: la imagen (`404` si no hay; `304` con `If-None-Match`).
- `PUT /api/profile/photo`: cuerpo = la imagen en bruto con su `Content-Type` (`image/jpeg`, `image/png` o `image/webp`). `415` si el tipo o los bytes no cuadran, `413` por encima de 2 MB, `400` si está vacía. Responde `{"ok": true, "photo": {"version": "..."}}`.
- `DELETE /api/profile/photo`: borra la foto (idempotente).

Todos operan sobre el usuario de la sesión (sin ids en la URL). Hoy solo existe el usuario de `CHECKPOINT_USER`; el almacenamiento por carpeta de usuario y un único punto de código que resuelve el usuario de la sesión dejan el diseño listo para un futuro registro de usuarios (aún no hay roles ni registro). Una foto antigua en `data/profile/photo.<ext>` se mueve sola a la carpeta del usuario al arrancar o en el primer acceso.

### API key de usuario

Una sola API key por usuario, para que lanzadores y plugins avisen al hub sin iniciar sesión. Se gestiona en la sección «API key» del menú del perfil: **Generar** (nunca se crea sola), verla siempre (campo de solo lectura con botón **Copiar**), **Regenerar** (con confirmación: la anterior deja de valer y hay que actualizar los comandos y plugins ya vinculados) y **Revocar**. Formato: `ck_` + 32 bytes aleatorios en base64 urlsafe (46 caracteres).

- **Alcance mínimo:** solo sirve para las rutas `/api/hook/*` (hoy `GET /api/hook/ping`; el aviso de apertura de juego colgará de aquí). No da acceso al login, ajustes, versiones ni a restaurar, y la cookie de sesión no vale en esas rutas.
- **Autenticación:** cabecera `Authorization: Bearer ck_...`, sin cookie ni comprobación de `Origin`. Cualquier fallo (sin cabecera, mal formada, inválida, revocada o regenerada) es el mismo `401` con `err.apikey.invalid`; la comparación es en tiempo constante (`hmac.compare_digest`). Tras 3 fallos seguidos desde una IP, `429` con `Retry-After` (misma escala que el login, con contador propio: un lanzador mal configurado no bloquea el login web).
- **Dónde se guarda:** como la key se vuelve a mostrar, no vale guardar solo un hash. Se guarda cifrada en `data/profile/<id>/apikey.enc` (permisos 0600, misma carpeta por usuario que la foto). La clave de cifrado se deriva del **secreto del hub**, `hub.secret` (32 bytes aleatorios, 0600), que se crea la primera vez junto a `config.yaml` (en Docker, el volumen `/config`; sin Docker, `config/` del directorio de datos de la app), **fuera de `data/`**: una copia de seguridad solo de `data/` no expone la key. Haz copia de `hub.secret` si quieres conservar la key; sin él (o si lo cambias) la key guardada no se puede descifrar, la interfaz muestra «sin key» y basta generar una nueva.
- **Cifrado:** solo biblioteca estándar de Python (sin dependencias nuevas): flujo de claves HMAC-SHA256 en modo contador y etiqueta HMAC-SHA256 (cifrar y luego autenticar), con claves distintas derivadas del secreto y la etiqueta atada al id de usuario. Un fichero manipulado o copiado a otro usuario no descifra.
- **HTTP en LAN:** la key viaja en claro; la interfaz lo avisa. Usa HTTPS (proxy inverso) o una VPN fuera de tu red de confianza.

API (con sesión de cookie, como el resto del perfil; las escrituras comprueban el origen; respuestas con `Cache-Control: no-store`):

- `GET /api/profile/apikey`: `{"exists": true, "key": "ck_..."}` o `{"exists": false, "key": null}`.
- `POST /api/profile/apikey`: genera o regenera; devuelve `{"exists": true, "key": "ck_..."}`.
- `DELETE /api/profile/apikey`: revoca (idempotente); devuelve `{"exists": false, "key": null}`.
- `GET /api/hook/ping` (Bearer): `{"ok": true, "user": "<nombre>"}`.

```bash
curl -H "Authorization: Bearer ck_..." http://HOST:PORT/api/hook/ping
```

## Instalar como app (PWA)

Checkpoint se puede instalar en el móvil y abrirse a pantalla completa. En móvil, la interfaz propone instalarla (se puede descartar con «Ahora no»).

- **iOS (Safari):** funciona también por `http://`. Compartir, «Añadir a pantalla de inicio».
- **Android (Chrome):** el botón «Instalar» y el service worker exigen contexto seguro: **HTTPS** (o `localhost`). Con `http://IP-LAN` Chrome no lanza el evento de instalación y la interfaz no muestra el aviso. Pon Checkpoint detrás de un proxy inverso con TLS (Caddy, Traefik, nginx) y entra por el dominio HTTPS.
- Para probarlo sin certificado propio: en el móvil, `chrome://flags/#unsafely-treat-insecure-origin-as-secure` con tu `http://IP-LAN:8088` (solo para pruebas), o un túnel HTTPS al puerto 8088.
- El service worker no cachea nada: la app sigue necesitando el servidor, y las actualizaciones se ven al recargar.
- Los iconos se regeneran con `node frontend/scripts/make-icons.mjs` (sin dependencias).

## Seguridad

- Cambia el usuario y la contraseña del `.env` y restringe sus permisos (`chmod 600 .env`).
- No expongas el servicio a Internet sin un proxy inverso con TLS (activa `CHECKPOINT_COOKIE_SECURE=1` y `CHECKPOINT_TRUST_PROXY=1`).
- La clave privada vive en `keys/` y no debe compartirse ni subirse a ningún repositorio.
- La API key de usuario (ver «API key de usuario») se guarda cifrada en `data/`; su secreto, `hub.secret`, vive junto a `config.yaml`, fuera de `data/`. No subas ninguno de los dos a un repositorio y trata la key como una contraseña: regenérala si se filtra.
- Si cambia la huella de un dispositivo, la conexión falla; revisa la entrada de `keys/known_hosts` antes de borrarla.
- Usa una cuenta limitada en los dispositivos siempre que sea posible.
- Sin Docker, `serve` escucha en `127.0.0.1`: ábrelo a la red solo si lo necesitas. «Este equipo» da acceso al sistema de ficheros de quien ejecuta Checkpoint, con sus permisos; no lo ejecutes como administrador/root.

## Desarrollo

```bash
cd backend && python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt && pytest
cd ../frontend && npm install && npm run dev     # desarrollo
npm test                                         # pruebas de node (borrador, formato, i18n es/en, tarjeta de dispositivo y avisos de versión)
npm run build                                    # producción
```

### Escala tipográfica

Los tamaños de texto viven como tokens en `frontend/src/styles/_variables.scss` (`$fs-*`, en rem con html a 16 px). No uses tamaños sueltos.

| Token | px | Uso |
|---|---|---|
| `$fs-label` | 12 | badges, etiquetas en mayúsculas, pie |
| `$fs-hint` | 13 | ayudas, texto secundario, código, logs |
| `$fs-body` | 15 | texto normal, botones, campos |
| `$fs-subtitle` | 17 | h3, título de tarjeta |
| `$fs-title` | 20 | h2, estado vacío |
| `$fs-page` | 28 | h1 |

Excepciones explícitas: `$fs-input-mobile` (1rem = 16 px, evita el zoom de iOS), `$fs-tab-mobile` y `$fs-tab-narrow` (pestañas móviles compactas), `$fs-icon` y `$fs-hero` (iconos).

`esbuild` no está declarado en `frontend/package.json`: llega como dependencia transitiva de `vite`.

### Componentes de UI

Los elementos que se repiten viven en `frontend/src/components/ui/` (importa desde `components/ui/index.js`), cada uno con su partial en `frontend/src/styles/ui/`. Para cambiar el aspecto de todos los usos, edita el partial; para cambiar el marcado, el componente. No escribas a mano `className="btn"`, `badge`, `alert`, etc.

| Componente | Props | Estilos |
|---|---|---|
| `Button` | `variant` (`primary`, `danger`, `ghost`), `className`, `type` (`button` por defecto) | `_button.scss` |
| `Badge` | `status` (`ok`, `error`, `conflict`, `partial`, `aborted`, `dry-run`, `running`) | `_badge.scss` |
| `Alert` | `variant` (`error`, `ok`, `warn`, `info`), `inline`, `as` | `_alert.scss` |
| `Pill` | `highlight` | `_pill.scss` |
| `Select` | `options` (`[{ value, label }]`), `placeholder` | `_control.scss` |
| `Checkbox` | `label` + props del input | `_control.scss` |
| `Switch` | `label` + props del input | `_switch.scss` |
| `Input` | props del input (texto sin autocompletar ni corrector por defecto); acepta `ref` | `_control.scss` |

Los tests `test/ui-components.test.mjs` fijan las clases y atributos que producen.

## Licencia

MIT. Ver [`LICENSE`](LICENSE).
