<p align="center">
  <img src="docs/logo.svg" alt="Checkpoint" width="360">
</p>

# Checkpoint

![Licencia MIT](https://img.shields.io/badge/licencia-MIT-green)

Checkpoint mantiene sincronizadas las partidas guardadas de un juego entre dos dispositivos (o, con uno solo, guarda versiones en el hub), por SSH, desde una interfaz web. Corre en Docker o directamente en un equipo (modo nativo); no se instala nada en los dispositivos.

- Sincroniza los guardados de un juego entre dos dispositivos y elige la copia más reciente.
- Con un solo dispositivo, «solo checkpoint»: el hub guarda versiones de la partida, sin copia entre equipos.
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
- **Juegos**: cada juego enlaza uno o dos dispositivos y la carpeta de guardado en cada uno (con uno solo es «solo checkpoint»; ver «Un solo dispositivo»). Los nombres de dispositivos y juegos son libres (hasta 64 caracteres, con espacios, acentos y emojis; sin `/` ni `\`).
- **Sincronizar**: Checkpoint descarga los guardados, recuerda cuál era el estado tras la última sincronización y propaga el lado que ha cambiado. Si solo un dispositivo está conectado, lo compara con la copia del hub. Antes de sobrescribir guarda la copia perdedora como versión.
- **Versiones**: se conservan las últimas N de cada juego (`max_versions` global, 20 por defecto, 0 = sin límite; `keep_versions` lo sustituye en un juego) y se pueden restaurar desde la UI.

Solo la opción «gana el más reciente» de los conflictos usa fechas de modificación: mantén la hora sincronizada (NTP) en el servidor y en los dispositivos.

## Instalación

Requisitos: Docker y Docker Compose. Sin Docker, ver [Instalación sin Docker](#instalación-sin-docker).

1. Clona el repositorio:
   ```bash
   git clone https://github.com/mcondepoGH/checkpoint.git && cd checkpoint
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
| `CHECKPOINT_HOOK_STAGING_TTL_H` | `24` | Horas sin escrituras tras las que se purga el staging de subidas (`data/staging/<juego>/<dispositivo>/`) al arrancar y cada hora; nunca el de un juego con el lock tomado o una ejecución en curso. Entre `1` y `720`; fuera de rango o no numérico, el arranque falla con un error claro |
| `CHECKPOINT_HOOK_STAGING_MAX_MB` | `2048` | Tope (MiB) del staging de cada juego (todos sus dispositivos) en la subida de saves por la API; al superarlo, `413` `err.hook.staging_full`. Entre `1` y `1048576`; fuera de rango o no numérico, el arranque falla con un error claro |
| `CHECKPOINT_HOOK_MAX_FILE_MB` | `512` | Tamaño máximo por fichero (MiB) en la subida de saves de los dispositivos `http` por la API (ver «Hooks»). Entre `1` y `16384` (16 GiB); fuera de rango o no numérico, el arranque falla con un error claro |
| `CHECKPOINT_RUNTIME` | automático | `docker` o `native`: fuerza el modo (la imagen lo fija a `docker`) |
| `CHECKPOINT_LANG` | `es` | Idioma por defecto de la interfaz: `es` o `en` (también `en-US`, `EN`…). Opcional; sin marcar es español. Un valor no soportado se ignora (español) y se avisa en el log de arranque. Ver [Idioma](#idioma) |
| `CHECKPOINT_LOG_LEVEL` | `info` | Nivel de log de la app: `info` o `debug` (también `warning`, `error`). Con `debug` salen las trazas detalladas por petición. Un valor no válido se ignora (`info`) y se avisa en el log de arranque. Se aplica al reiniciar |
| `TZ` | `UTC` | Zona horaria de los registros y la sincronización automática (p. ej. `Europe/London`); solo Docker, se añade a `environment:` |

Si la contraseña lleva `$`, ponla entre comillas simples.

## Instalación sin Docker

Modo «nativo»: Checkpoint corre directamente en un equipo. Es la única forma de usar el dispositivo **«Este equipo»** (ver más abajo).

**Requisitos**: Python 3.12, Node.js (solo para compilar la web) y, si vas a sincronizar dispositivos remotos, `rsync` y el cliente OpenSSH (`ssh`, `ssh-keygen`, `ssh-keyscan`) en el `PATH`. Con «Este equipo» como único tipo de dispositivo no hacen falta.

```bash
git clone https://github.com/mcondepoGH/checkpoint.git && cd checkpoint
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

La pantalla **Configuración** tiene tres subpestañas (en memoria, sin URL ni almacenamiento): **General** (sincronización automática con su registro de ejecuciones, y comprobación de actualizaciones), **Biblioteca** (clave SSH, versiones guardadas, dispositivos y juegos) y **Lanzadores**. Abre en General, y en Biblioteca la primera vez, cuando aún no hay dispositivos. La barra de guardar y el borrador son solo de Biblioteca: al cambiar de subpestaña el borrador se conserva, y con cambios sin guardar la subpestaña Biblioteca muestra un punto de aviso (con texto para lectores de pantalla). En móvil las etiquetas son cortas (General, Biblioteca, Lanzadores).

1. En **Configuración > Biblioteca**, copia la **clave pública SSH** (botón Copiar). Solo hace falta si vas a usar dispositivos remotos.
2. Añádela a `authorized_keys` de cada dispositivo. El botón **?** junto a la clave muestra los comandos para Linux y Windows, incluida la activación del servidor SSH. Cada comando va en su propia card con su botón **Copiar**; si hay alternativas (p. ej. ufw o firewalld) se elige solo una, y si hay varios comandos en un paso se ejecutan en orden.
3. Añade los **dispositivos** (nombre, host, puerto, usuario, sistema) y pulsa **Probar conexión**. La primera vez se guarda la huella del host. Sin Docker puedes marcar uno como **Este equipo** (sin SSH).
4. Añade los **juegos**: elige uno o dos dispositivos (el segundo es opcional) y la carpeta de guardado en cada uno (ruta absoluta, por ejemplo `/home/usuario/.local/share/Juego/Saves` o `C:\Users\Usuario\AppData\Local\Juego\Saves`).
5. Ve a **Sincronizar**. Prueba primero con **Simulación (dry-run)** y después sin él.

## Sincronización automática

En **Configuración > General > Sincronización automática** activa la opción y elige cada cuántas horas se ejecuta (de 0.25 a 168). Cada ciclo sincroniza todos los juegos **activos** (los desactivados se omiten en silencio; ver «Desactivar un juego»); si uno falla, los demás continúan. Debajo se muestra el **Registro de ejecuciones** (las últimas 200, límite fijo; cada una con su origen en una etiqueta de color: Manual, Programado o Launcher; incluye las sincronizaciones manuales reales, no las simulaciones) con resultado por juego y detalle al hacer clic. Sin ajustes guardados, está desactivada y el intervalo es de 24 horas.

## Nuevas versiones

Checkpoint comprueba si hay una versión nueva consultando las Releases públicas de GitHub (solo HTTPS, por defecto solo versiones estables: se ignoran borradores y pre-releases). Si la hay, aparece la insignia **Nueva versión disponible** en la cabecera, con la versión instalada, la nueva y sus notas. No actualiza nada: en Docker, actualiza la imagen (`docker compose pull` si usas la imagen publicada, o reconstruye si la construyes tú) y recrea el contenedor; en instalación nativa, descarga la nueva versión y reinicia.

**Solo en instalación nativa.** En Docker la versión la fija la imagen: la comprobación no se aplica (no hace ninguna petición a internet, no lee ni escribe caché y no aparecen la insignia ni la tarjeta «Comprobar actualizaciones»). La versión instalada se muestra siempre en el pie de la interfaz. Cómo se decide Docker o nativo: ver «Instalación sin Docker».

- La versión instalada sale del fichero `VERSION` de la raíz del repositorio (la imagen lo incluye). Sin él, o en desarrollo, es «desconocida» y no se ofrece ninguna actualización. El repositorio consultado es siempre el de este proyecto.
- El resultado se guarda en memoria y en `data/update_cache.json` durante 6 horas. Un fallo de red es silencioso: se conserva el último resultado y se reintenta pasados unos minutos.
- Se desactiva en **Configuración > General > Comprobar actualizaciones** (viene activada). Desactivada, no se hace ninguna petición a internet. El botón **Comprobar ahora** fuerza la consulta (máximo una por minuto).
- **Canal** (Configuración > General > Comprobar actualizaciones): **Estable** (por defecto) solo ofrece Releases normales; **Pruebas** (`beta`) ofrece también pre-releases (nunca borradores), que pueden fallar. En Pruebas se ofrece la versión más alta entre estables y preliminares, con el orden de semver: `1.0.0-rc.1` < `1.0.0-rc.2` < `1.0.0`. Un tag con sufijo (`-rc.1`) cuenta como preliminar aunque GitHub no lo marque. Cambiar de canal descarta el resultado guardado y vuelve a consultar. Nunca se ofrece bajar de versión: desde una preliminar en canal Estable solo se avisa cuando haya una estable mayor. La insignia y el diálogo marcan «preliminar» cuando procede.
- La etiqueta de imagen `beta` la publica el workflow de release (ver «Publicación de versiones»); el canal solo cambia qué avisos se muestran, no la imagen que ejecutas.
- API (requiere sesión): `GET /api/updates[?refresh=true]` (incluye `actual`, la versión instalada, `aplicable`, `canal` y `prerelease`, si la versión ofrecida es preliminar) y `PUT /api/updates` con `{"enabled": true|false, "channel": "stable"|"beta"}` (parcial: basta uno de los dos; valor no válido, 422). En Docker, `GET` devuelve `aplicable: false` con campos neutros (sin error, sin red) y `PUT` responde 409.

## Publicación de versiones

Al subir un tag `vX.Y.Z` el workflow `.github/workflows/release.yml` publica la imagen en GHCR y crea la GitHub Release (la que consulta la comprobación de nuevas versiones).

1. Edita `VERSION` con la versión nueva (sin `v`), por ejemplo `1.0.0` o `1.0.0-rc.1`, y pon la misma en `frontend/package.json` y `frontend/package-lock.json` (`npm test` lo comprueba). Haz commit en `main`.
2. Crea un tag anotado con el mismo número: `git tag -a v1.0.0 -m "v1.0.0"`.
3. Sube el commit y el tag: `git push origin main v1.0.0`.

Tras publicar, el job `trivy` escanea la imagen (informativo, no bloquea ni deshace la Release) y deja el informe JSON como artefacto; si hay vulnerabilidades altas o críticas, `security-issues` abre un issue por paquete y versión (con la lista de CVE y la solución) con plazo. Si `VERSION` no coincide con el tag, el workflow falla antes de construir nada. Un tag con sufijo (`-rc.1`, `-beta.2`) se publica como pre-release.

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

## Un solo dispositivo

Un juego puede tener un único dispositivo (el dispositivo 2 es opcional en el formulario; en `config.yaml`, `devices` con un solo id). Es el modo «solo checkpoint»: no hay copia entre equipos, el hub guarda la partida y sus versiones. La tarjeta del juego en Sincronizar lleva la etiqueta «Solo checkpoint».

- **Guardar:** al sincronizar (a mano, cada X horas, con el aviso de apertura o al cerrarse el juego) la partida del dispositivo pasa al hub. Antes de sustituir la copia anterior del hub se guarda como versión, como con dos dispositivos. La última partida está en el hub y no aparece en la lista de versiones; las versiones son las copias anteriores. El límite es `max_versions` o `keep_versions` del juego, igual que siempre.
- **Restaurar:** como siempre. En Versiones, restaura la versión al hub y sincroniza después; el hub (ahora distinto del dispositivo) gana y se copia al dispositivo.
- **Conflictos:** si el hub y el dispositivo difieren sin estado guardado (primera sincronización con datos en ambos), se trata como conflicto, igual que con dos dispositivos.
- **Partida local ausente:** si la ruta de guardado del dispositivo **no existe** (juego desinstalado o carpeta borrada) y el hub tiene datos, la sincronización automática (cada X horas, al arrancar) y el aviso de apertura del lanzador **no** recrean la carpeta ni restauran nada: se omiten con `err.sync.local_missing_manual_required` y quedan en el historial como omitidas. Solo una sincronización **manual** (botón Sincronizar o `checkpoint sync`) restaura la copia del hub en el dispositivo. Una carpeta que existe pero está vacía se trata como siempre. Con dos dispositivos nada cambia.
- **Aviso de apertura:** `?device=` es opcional (se deduce el único dispositivo).

## Desactivar un juego

Un juego se puede desactivar sin borrarlo: en **Configuración > Biblioteca**, el interruptor **Juego activo** del formulario del juego (visible sin pulsar «Mostrar más»); en `config.yaml`, `enabled: false` (sin el campo, el juego está activo). Un juego desactivado **no se sincroniza por ninguna vía**:

- La sincronización automática (cada X horas y al arrancar) lo omite en silencio: ni entrada en el registro ni cuenta en los resúmenes.
- `POST /api/sync/{juego}` responde `409` con `err.sync.game_disabled`, también con `dry_run: true`; la CLI (`checkpoint sync`) aborta con ese mismo código. Es una guarda central de la sincronización: para sincronizarlo hay que reactivarlo.
- El aviso de apertura (`opened`) y el cierre automático lo omiten (ver «Hooks»).
- En **Sincronizar** el juego sigue visible pero atenuado, con la etiqueta «Desactivado», sin botón «Sincronizar» ni «Simulación» y con un acceso a Configuración. En **Lanzadores** sigue con su fila, con la etiqueta «Desactivado» y una nota («Desactivado: el aviso se omitirá»). `checkpoint list` lo marca «(desactivado)».
- **Versiones:** se conservan y siguen visibles (con el sufijo «(desactivado)») y restaurables. Restaurar solo copia al hub: no se propaga a los dispositivos mientras el juego esté desactivado.

Al guardar solo se escribe `enabled: false`; reactivarlo quita la línea.

## Conflictos

Hay conflicto cuando los dos dispositivos han cambiado desde la última sincronización y su contenido es distinto (o, en la primera sincronización, ya difiere). Checkpoint nunca lo decide por la fecha a ciegas.

- **Sincronización automática**: `on_conflict` en Configuración > General > Sincronización automática. `skip` (por defecto) no guarda nada y marca el juego como «Conflicto»; `newest` hace ganar el save más reciente (si las fechas difieren menos de 2 s, se omite). Un juego puede sustituirlo con `on_conflict` en `config.yaml`.
- **Sincronización manual**: siempre pregunta. Un popup ofrece cancelar, «Gana el más reciente» o elegir qué dispositivo gana, con fecha y tamaño de cada uno. En la CLI: `checkpoint sync JUEGO --resolve newest|device:DISPOSITIVO` (sale con código 3 si hay conflicto).

En todos los casos la copia perdedora se guarda antes en versiones. En la primera sincronización de cada juego (aún sin estado guardado) el hub es la única referencia: si ambos lados difieren, se trata como conflicto.

## Configuración

| Carpeta | Contenido |
|---|---|
| `config/` | `config.yaml` (dispositivos y juegos) |
| `keys/` | clave SSH generada y `known_hosts` |
| `data/` | copias, versiones, logs, registro de la sync automática y la foto de perfil (`data/profile/`) |

Estas carpetas no vienen en el repositorio (están en `.gitignore`): se crean solas al arrancar, con Docker (bind mounts de `docker-compose.yml`) o sin Docker (`CHECKPOINT_HOME_DIR`, ver «Sin Docker»). Con Docker, si no existen en el clon, Docker las crea como root en el primer `docker compose up`; el contenedor arranca como root, las pasa a su usuario `checkpoint` (uid/gid 1000 por defecto, argumentos `PUID`/`PGID` del `Dockerfile`) y deja `keys/` en `0700`, así que funciona igual. Si prefieres que el propietario inicial en el host sea tu usuario, créalas antes del primer arranque:

```bash
mkdir -p config data keys && docker compose up -d
```

(El arranque vuelve a asignarlas al uid 1000 del contenedor; si tu usuario del host es el 1000, no cambia nada.) `config.yaml` se edita desde la UI (valida, muestra diff y guarda copias) o a mano; ver [`config.example.yaml`](config.example.yaml). Ejemplo mínimo:

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
    # enabled: false           # opcional: desactiva el juego (no se sincroniza por ninguna vía)
    # steam_appid: 1245620     # opcional: id de Steam del juego (ver abajo)
```

**Appid de Steam (opcional).** `steam_appid` es el id de Steam del juego: un dato del juego, igual en todos los dispositivos, que el plugin de Steam Deck usa para saber qué juego del hub corresponde a cada juego de Steam. Se edita en Configuración, en el campo «Appid de Steam» de la tarjeta del juego (o en `config.yaml`); vacío o ausente = sin appid. Debe ser un número entero mayor que 0: `0`, negativos, decimales, texto (también `"440"` entre comillas) y `true`/`false` se rechazan con `err.config.steam_appid_invalid`. Dos juegos no pueden compartir el mismo appid (`err.config.steam_appid_duplicate`, indica el otro juego). Solo se pueden guardar juegos de Steam por ahora: no hay appid para los que no lo son. Las keys de la API solo lo leen (`GET /api/games`); no pueden cambiarlo.

La clave de cada juego y dispositivo es su **ID interno**, que no cambia nunca; `name` es solo una etiqueta y se puede renombrar libremente sin perder saves, versiones ni logs. `name` es obligatorio en cada juego y dispositivo. La CLI y la API aceptan el ID o el nombre.

## Idioma

La interfaz está en español e inglés. El selector de idioma está en el menú del perfil (el icono redondo del extremo derecho de la cabecera, una vez iniciada la sesión; la pantalla de acceso no lleva selectores y usa el idioma y tema ya guardados). Ofrece **Automático**, **Español** y **English**, y recuerda la elección en ese navegador (`localStorage`, clave `checkpoint.lang`); se aplica al instante, sin recargar. El mismo menú tiene el cambio de tema (automático, claro, oscuro; muestra un sol o una luna según el tema efectivo) y **Salir**.

Orden de prioridad:

1. La elección manual guardada en el navegador (`Español` o `English`).
2. Si se eligió **Automático**, el idioma del navegador (si no es uno soportado, el de 3).
3. El idioma por defecto del servidor: `CHECKPOINT_LANG` (`es` o `en`) o español si no está marcado.

Es decir, sin elección guardada manda el servidor, no el navegador: así una instalación se puede dejar en inglés para todos los usuarios que no hayan elegido. Para fijarlo en Docker, descomenta `CHECKPOINT_LANG` en el `environment:` de `docker-compose.yml` (o añádelo al `.env`).

El backend no traduce nada: devuelve códigos y parámetros (`{"code": "err.sync.dry_run", "params": {...}}`) y la traducción vive en `frontend/src/locales/*.json`. Para añadir un idioma, crea `<código>.json` con las mismas claves que `es.json` (el test `frontend/test/locales/locales.test.mjs` lo comprueba), regístralo en `frontend/src/locales/index.js` y añade el código a `SUPPORTED_LANGS` de `backend/app/core/settings.py`.

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

- **Alcance mínimo:** esta key de **usuario** sirve para `GET /api/hook/ping`, `GET /api/hook/watches`, `POST /api/hook/{juego}/opened` y `GET /api/games` (todos los juegos). **No** vale en las rutas de los dispositivos `http` (`fingerprint`, `manifest`, `files`, `commit`, `closed`): esas piden la key del dispositivo (ver «API key de dispositivo `http`»). No da acceso al login, ajustes, versiones ni a restaurar, y la cookie de sesión no vale en esas rutas.
- **Autenticación:** cabecera `Authorization: Bearer ck_...`, sin cookie ni comprobación de `Origin`. Cualquier fallo (sin cabecera, mal formada, inválida, revocada o regenerada) es el mismo `401` con `err.apikey.invalid`; la comparación es en tiempo constante (`hmac.compare_digest`). Tras 3 fallos seguidos desde una IP, `429` con `Retry-After` (misma escala que el login, con contador propio: un lanzador mal configurado no bloquea el login web).
- **Dónde se guarda:** como la key se vuelve a mostrar, no vale guardar solo un hash. Se guarda cifrada en `data/profile/<id>/apikey.enc` (permisos 0600, misma carpeta por usuario que la foto). La clave de cifrado se deriva del **secreto del hub**, `hub.secret` (32 bytes aleatorios, 0600), que se crea la primera vez junto a `config.yaml` (en Docker, el volumen `/config`; sin Docker, `config/` del directorio de datos de la app), **fuera de `data/`**: una copia de seguridad solo de `data/` no expone la key. Haz copia de `hub.secret` si quieres conservar la key; sin él (o si lo cambias) la key guardada no se puede descifrar, la interfaz muestra «sin key» y basta generar una nueva.
- **Cifrado:** [Fernet](https://cryptography.io/en/latest/fernet/) de la librería `cryptography` (AES-128-CBC + HMAC-SHA256). La clave Fernet se deriva del secreto del hub con HMAC-SHA256. Fernet no admite datos asociados, así que el id de usuario va dentro del payload cifrado y se verifica al descifrar: un fichero manipulado, copiado a otro usuario o cifrado con otro secreto no descifra (la interfaz muestra «sin key»).
- **Copias de seguridad:** si tu copia cubre `/config` y `/data` juntos, el secreto viaja con la key cifrada y la protección frente a un backup se pierde. Excluye `hub.secret` de la copia (y guárdalo aparte si quieres poder restaurar la key).
- **HTTP en LAN:** la key viaja en claro; la interfaz lo avisa. Usa HTTPS (proxy inverso) o una VPN fuera de tu red de confianza.

API (con sesión de cookie, como el resto del perfil; las escrituras comprueban el origen; respuestas con `Cache-Control: no-store`):

- `GET /api/profile/apikey`: `{"exists": true, "key": "ck_..."}` o `{"exists": false, "key": null}`.
- `POST /api/profile/apikey`: genera o regenera; devuelve `{"exists": true, "key": "ck_..."}`.
- `DELETE /api/profile/apikey`: revoca (idempotente); devuelve `{"exists": false, "key": null}`.
- `GET /api/hook/ping` (Bearer): `{"ok": true, "user": "<nombre>"}`.

```bash
curl -H "Authorization: Bearer ck_..." http://HOST:PORT/api/hook/ping
```

### API key de dispositivo `http`

Cada dispositivo con `http: true` tiene **su propia key**, distinta de la de usuario y de la de los demás dispositivos. Formato: `ckd_` + 32 bytes aleatorios en base64 urlsafe (47 caracteres); el prefijo distinto (`ck_` usuario, `ckd_` dispositivo) le dice al hub qué comprobar sin ambigüedad. Se genera, se ve siempre, se regenera (la anterior deja de valer al instante) y se revoca por sesión de cookie (la interfaz está pendiente: tarjeta «UI de dispositivos http»; mientras tanto, con la API). Se guarda igual que la de usuario (Fernet con `hub.secret`, 0600, comparación en tiempo constante) en `data/profile/<id>/devices/<id de dispositivo>.enc`; el id del dispositivo va dentro del payload cifrado: un fichero copiado a otro dispositivo no descifra.

API (sesión de cookie; escrituras con comprobación de `Origin`; `Cache-Control: no-store`; `404` `err.hook.device_unknown` si el id no existe, `400` `err.hook.device_not_http` si el dispositivo no es `http`):

- `GET /api/devices/{id}/apikey`: `{"exists": true, "key": "ckd_..."}` o `{"exists": false, "key": null}`.
- `POST /api/devices/{id}/apikey`: genera o regenera; devuelve `{"exists": true, "key": "ckd_..."}`.
- `DELETE /api/devices/{id}/apikey`: revoca (idempotente); devuelve `{"exists": false, "key": null}`.

Con la sesión web (cookie, no una key; `COOKIE` = archivo de cookies del login, `ID` = id del dispositivo; las escrituras llevan `Origin`):

```bash
curl -fsS -b COOKIE "http://HOST:8088/api/devices/ID/apikey"
curl -fsS -b COOKIE -H "Origin: http://HOST:8088" -X POST "http://HOST:8088/api/devices/ID/apikey"
curl -fsS -b COOKIE -H "Origin: http://HOST:8088" -X DELETE "http://HOST:8088/api/devices/ID/apikey"
```

La key **identifica al dispositivo**: `?device=` pasa a ser opcional en sus endpoints y, si se pasa (id o nombre) y no es el de la key, `403` `err.apikey.device_mismatch` (también con un dispositivo desconocido, para no revelar cuáles existen). El juego solo se busca entre los que incluyen ese dispositivo: uno que no lo incluye responde el mismo `404` `err.main.game_unknown` que uno inexistente.

**Ciclo de vida con la config.** La key va ligada al **id** del dispositivo, no al nombre: **renombrar un dispositivo no cambia su key**. Borrar el dispositivo o quitarle `http` borra su key (al guardar o restaurar la config y al arrancar el hub, por si se editó `config.yaml` a mano); además, una key de un dispositivo que ya no es `http` no autentica aunque su fichero siguiera en disco. Un dispositivo nuevo con el mismo id no hereda la key anterior.

#### Qué key acepta cada endpoint

| Endpoint | Key de usuario (`ck_`) | Key de dispositivo (`ckd_`) |
|---|---|---|
| `GET /api/hook/ping` | sí | sí (añade `"device": "<id>"`) |
| `GET /api/hook/watches` | sí | no (`401`) |
| `POST /api/hook/{juego}/opened` | sí | no (`401`) |
| `GET /api/games` | sí: todos los juegos | sí: solo los juegos que tienen ese dispositivo |
| `POST /api/hook/{juego}/fingerprint`, `GET /manifest`, `GET`/`PUT /files`, `POST /commit`, `POST /closed` | no (`401`) | sí, solo en juegos que incluyen el dispositivo |

Una clase de key no admitida es el **mismo `401`** (`err.apikey.invalid`) que una key inválida, y cuenta como fallo para el límite por IP (`429`); `403` y `404` de alcance no cuentan.

**Aviso de seguridad.** Las keys de dispositivo dan acceso de lectura y escritura a los saves de sus juegos: trátalas como contraseñas (HTTPS o VPN fuera de tu red de confianza, no las subas a repositorios) y regenera o revoca la que se filtre o del dispositivo que pierdas. La de dispositivo limita el daño: no sirve para `opened`, `watches` ni para otros dispositivos, y no da acceso a ajustes. Excluye `hub.secret` de las copias, como con la de usuario.

### Documentación de la API (OpenAPI)

La API que usa la API key (la de usuario y la de dispositivo `http`: `/api/hook/*` y `GET /api/games`) se documenta con OpenAPI y se puede probar desde el navegador con Swagger UI:

- **Abrir:** enlace «Documentación de la API» en el menú del perfil, bajo «API key» (`/api/docs`, pestaña nueva). El esquema está en `/api/openapi.json`.
- **Solo con sesión:** `/api/docs`, `/api/openapi.json` y los ficheros de Swagger UI exigen la sesión de la web; sin ella responden `401` como el resto de rutas protegidas. La API key sola no abre la documentación.
- **Alcance:** solo las rutas de la API key (tag «Avisos del lanzador» las de `/api/hook/*` y «Juegos» la de `/api/games`); cada operación indica qué clase de key acepta (esquemas de seguridad `bearerAuth` = usuario y `deviceKeyAuth` = dispositivo). El resto de `/api/*` (login, perfil, configuración, sincronización, versiones...) es interno de la web, no está en el esquema y puede cambiar sin aviso.
- **Probar:** pulsa «Authorize», pega tu API key (sin el prefijo `Bearer`; hay un campo por clase de key) y usa «Try it out». Ojo: `POST .../opened` **ejecuta de verdad** una sincronización previa y arma el vigilante de cierre del juego.
- **Sin internet:** Swagger UI va empaquetada en la imagen (`swagger-ui-dist`, versión fijada en `frontend/package.json`; el build de Vite la copia a `docs-assets/` y el backend la sirve en `/api/docs-assets/`). No se carga nada de CDNs ni de terceros.
- **Idioma:** los textos de la documentación están en español; los códigos `err.*` van sin traducir.
- **Mantenimiento:** toda ruta `/api/*` nueva queda fuera del esquema por defecto; para publicarla hay que ponerle un tag público (`TAG` o `GAMES_TAG` en `backend/app/api/docs/install.py`). `backend/tests/test_apidocs.py` falla si el esquema deja de tener exactamente las rutas de la API key.

## Hooks

Rutas `/api/hook/*` para que un lanzador avise al hub con la API key de usuario (ver «API key de usuario») o, en las de los dispositivos `http`, con la del dispositivo (ver «API key de dispositivo `http`»). Hoy: el aviso de apertura (que además arma el **cierre automático**), la comparación de saves de un dispositivo `http` (`fingerprint`) y su subida y bajada fichero a fichero (`manifest`, `files`, `commit`), la consulta de vigilancias y, con la misma key, la lista de juegos (`GET /api/games`).

### `POST /api/hook/{juego}/opened?device=<dispositivo>`

Se llama justo antes de arrancar el juego. El hub hace una **sincronización previa y bloqueante** de ese juego: si tiene un save más nuevo, lo copia al dispositivo antes de que el juego arranque; si no toca, termina sin copiar. Usa **siempre** la política de conflictos `skip`, ignorando la del juego y el ajuste global de la sincronización automática: ante un conflicto **no se toca nada**, la respuesta lo indica y queda en el historial; nunca se pregunta ni se resuelve solo.

- **Autenticación:** `Authorization: Bearer ck_...` (nada de cookie).
- **Juego:** id o nombre, como `POST /api/sync/{juego}`.
- **Dispositivo (`?device=`):** id o nombre. Se valida que pertenezca al juego; es el dispositivo donde se vigila el proceso del juego (ver «Cierre automático»). Es obligatorio si el juego está en más de un dispositivo; si el juego tiene uno solo, se deduce y puede omitirse.
- **Respuesta `200`:** `{"ok": bool, "outcome": "...", "game": "<id>", "device": "<id>", "run_id": "...", "code": "err.sync....", "params": {...}}`. `outcome` es `ok`, `conflict`, `aborted` (dispositivo sin conexión, proceso del juego abierto...), `skipped` (juego de un dispositivo con la partida local ausente: `err.sync.local_missing_manual_required`), `partial`, `error` o `timeout`. Un juego **desactivado** responde `outcome: skipped` con `code: err.sync.game_disabled` (ver «Desactivar un juego»). `ok` es `true` solo con `outcome: ok`. `code`/`params` detallan qué pasó (p. ej. `err.sync.done`, `err.sync.already_synced`, `err.sync.conflict`). Un fallo de la sincronización **no** es un 5xx y no se reintenta: el cron de la sincronización automática sigue como red de seguridad. `timeout`: la sincronización superó los 55 s del servidor; sigue ejecutándose en segundo plano y deja su entrada en el historial al acabar.
- **Errores:** `401` `err.apikey.invalid` (sin key, inválida, revocada o cookie de sesión; se comprueba antes que nada, así que no revela si el juego existe), `404` `err.main.game_unknown` o `err.hook.device_unknown`, `400` `err.hook.device_required` (falta `?device=` y es ambiguo) o `err.hook.device_ambiguous`, `409` `err.main.run_in_progress` (ya hay una ejecución de ese juego: cron, manual u otro aviso), `429` tras varios fallos de key seguidos desde una IP.
- **Historial:** la ejecución aparece en el registro de la sincronización automática con el disparador «Aviso del juego» (`trigger: "hook"`).
- **`watching`:** la respuesta añade `watching: true` si se armó la vigilancia de cierre, o `watching: false` con `watch_reason: "no_process"` si el juego no tiene `process`, o `"disabled"` si el juego está desactivado (en ese caso no se sincroniza ni se vigila, y se deja una entrada `skipped` en el historial con disparador «Aviso del juego»; los `400`/`404` no cambian y se comprueban antes). Se arma con cualquier `200` (también `conflict`, `aborted` o `timeout`), nunca con `400`/`401`/`404`/`409`.

```bash
curl -fsS -m 60 -X POST -H "Authorization: Bearer ck_..." "http://HOST:8088/api/hook/MiJuego/opened?device=MiPC"
```

Pon la URL **entre comillas**: el `?` lo interpretaría el shell como comodín.

### Dispositivos `http` (sin SSH)

Un dispositivo con `http: true` no lleva `host`, `user` ni `port` (ni `local`; son excluyentes, `os` sigue siendo obligatorio) y funciona también en Docker: el hub **nunca lo contacta**, es el dispositivo quien llama a la API con **su propia key** (`ckd_...`, ver «API key de dispositivo `http`»), que ya lo identifica (`?device=` es opcional). Queda fuera de la sincronización clásica (manual y automática), del aviso `opened` (`400` `err.hook.device_push_only`) y de la vigilancia de cierre; en un juego con un dispositivo `http` y otro SSH o local, la sync clásica solo trata al segundo. Un juego con solo dispositivos `http` no entra en la sync automática y una sync manual responde `err.sync.push_only`. «Probar conexión» con un dispositivo `http` no intenta SSH: responde `err.transport.push_only`.

```yaml
devices:
  deck-1a2b3c4d: {name: "Steam Deck", http: true, os: linux}   # sin host, user ni port
```

#### `POST /api/hook/{juego}/fingerprint?device=<dispositivo>`

El dispositivo envía el manifiesto de su carpeta de saves y el hub responde qué debe hacer, comparándolo con su copia (`data/hub/<juego>`) y con la línea base de la última sync, con la misma lógica que la sync clásica (nunca decide por fecha; un lado vacío no gana a uno con datos). **Única escritura**: con `action: none` (`reason: same`, huella igual a la del hub y no vacía) fija la línea base del dispositivo y del hub, verificada contra el manifiesto real, con el lock del juego (ocupado: `409` `err.main.run_in_progress`) y sin reescribirla si ya es esa. Con el lock tomado vuelve a comprobar que el hub sigue teniendo esa huella: si un `commit` lo cambió entre medias, **no escribe la línea base** (la respuesta sigue siendo `none`; el siguiente `fingerprint` decidirá con el hub nuevo); con `upload`, `download` o `conflict` no escribe nada ni toma el lock. Nunca toca ficheros ni historial.

Parámetro opcional `?manifest=1` (aditivo): con `action: download`, la respuesta incluye además `hub_manifest` (`[{path, sha256, size, mtime}]`, la misma forma que `GET /manifest`), calculado de la misma lectura del hub que la decisión (sin segunda pasada ni carrera). Sin el parámetro, o con otra acción, la respuesta no cambia; `GET /manifest` sigue igual.

Petición (`Content-Type: application/json`): lista de ficheros, máximo 50 000; `path` relativa con `/` (se rechazan `..`, las rutas absolutas, el carácter NUL, las vacías y las repetidas; cualquier otro carácter vale: `'`, `&`, `:` o espacios, para que el save pueda igualar al del hub), `sha256` hexadecimal de 64, `size` en bytes y `mtime` en segundos Unix; `[]` es una carpeta vacía.

```json
[{"path": "slot1/save.dat", "sha256": "9f86d0...0a08", "size": 10240, "mtime": 1768501812}]
```

Respuesta `200`:

```json
{"game": "g1", "device": "deck", "action": "upload", "reason": null,
 "hub": {"hash": "…", "files": 2, "size": 20480, "mtime": 1768501000},
 "device_state": {"hash": "…", "files": 2, "size": 20480, "mtime": 1768501812}}
```

`action`: `upload` (manda el dispositivo), `download` (manda el hub), `none` (iguales, `reason: "same"`) o `conflict` (`reason`: `both-changed`, `no-baseline` o `inconsistent`; no se hace nada).

- **Errores:** `401`/`429` como el resto (la key de usuario es un `401`); `403` `err.apikey.device_mismatch` (`?device=` distinto del de la key); `404` `err.main.game_unknown` (juego inexistente o que no incluye el dispositivo); `400` `err.main.json_body_required` (el cuerpo no es una lista JSON); `409` `err.main.run_in_progress` (ejecución del juego en curso) o `err.sync.game_disabled`; `422` `err.hook.manifest_path_invalid`, `err.hook.manifest_sha_invalid`, `err.hook.manifest_duplicate`, `err.hook.manifest_invalid` o `err.hook.manifest_too_large`.

```bash
curl -fsS -X POST -H "Authorization: Bearer ckd_..." -H "Content-Type: application/json" \
  -d '[{"path": "slot1/save.dat", "sha256": "9f86d0...0a08", "size": 10240, "mtime": 1768501812}]' \
  "http://HOST:8088/api/hook/MiJuego/fingerprint?device=Steam%20Deck"
# con el listado del hub si la acción es download:
curl -fsS -X POST -H "Authorization: Bearer ckd_..." -H "Content-Type: application/json" \
  -d '[{"path": "slot1/save.dat", "sha256": "9f86d0...0a08", "size": 10240, "mtime": 1768501812}]' \
  "http://HOST:8088/api/hook/MiJuego/fingerprint?device=Steam%20Deck&manifest=1"
```

#### `POST /api/hook/{juego}/closed?device=<dispositivo>`

El dispositivo `http` avisa de que cerró el juego (el hub no puede sondear su proceso por SSH). **Solo deja constancia** en el historial (disparador `hook_closed`, con el dispositivo) y devuelve el estado: no hay pull ni push ni sync clásica; el dispositivo hará después `fingerprint` y subirá o bajará por su cuenta. Sin cuerpo.

Respuesta `200`:

```json
{"game": "g1", "device": "deck", "recorded": true, "outcome": "ok"}
```

Un juego **desactivado** responde `200` con `outcome: "skipped"`, `code: "err.sync.game_disabled"` y `params: {}` (queda `skipped` en el historial, como en `opened`).

- **Errores:** `401`/`429` como el resto (la key de usuario es un `401`); `403` `err.apikey.device_mismatch`; `404` `err.main.game_unknown` (juego inexistente o que no incluye el dispositivo); `409` `err.main.run_in_progress` (ejecución del juego en curso; el cierre queda `skipped` con `err.hook.busy`).

```bash
curl -fsS -m 10 -X POST -H "Authorization: Bearer ckd_..." "http://HOST:8088/api/hook/MiJuego/closed?device=Steam%20Deck"
```

#### Subida y bajada de saves (dispositivos `http`)

Tras `fingerprint`, el dispositivo sube o baja sus saves **fichero a fichero** (reanudable, con sha256 de cada fichero y del conjunto). Todas llevan `Authorization: Bearer ckd_...` (key del dispositivo; `401`/`429` como el resto; `?device=` opcional, `403` `err.apikey.device_mismatch` si no es el de la key; juego que no incluye el dispositivo, `404` `err.main.game_unknown`) y el id o nombre del juego. Política de conflicto: siempre `skip` (nunca se sobrescribe al perdedor de un conflicto).

**Rutas.** La `path` de los ficheros se normaliza (`\` pasa a `/`) y se **revalida cada vez** contra el directorio donde se lee o escribe (staging o hub): se rechazan `..`, las rutas absolutas, NUL, vacías, los enlaces simbólicos (nunca se siguen) y cualquier ruta que acabe fuera (`400` `err.hook.file_path_invalid`). El manifiesto acepta caracteres raros (`C:/x`, `a;b`, `'`), pero como ruta relativa dentro de esa carpeta, nada más.

**Bloqueo y límites.** `PUT files` **no toma el lock del juego**: una subida lenta no bloquea la sync clásica. Al entrar solo comprueba que no haya una ejecución del juego en curso (`409` `err.main.run_in_progress`) y reserva ese fichero del dispositivo (otro `PUT` simultáneo al mismo fichero: `409` `err.hook.upload_busy`; el staging es de cada juego y dispositivo). El resto (`commit`, `manifest`, `GET files`, y `fingerprint` al fijar la línea base) toma el lock del juego (el de la sync) mientras dura, sin esperar: ocupado, `409` `err.main.run_in_progress` (reintenta luego). El `commit` reserva además todo el staging de ese dispositivo (después del lock del juego, siempre en ese orden, y sin esperar: no hay interbloqueo) mientras verifica `tree/` y lo copia al hub, para que un `PUT` concurrente del mismo dispositivo no pueda cambiar un fichero entre la verificación y la escritura (el hub quedaría distinto del hash guardado en la línea base). Decisión: no espera, responde `409` `err.hook.upload_busy` en ambos sentidos y sin tocar nada: un `PUT files` que llegue durante el commit, o un `commit` que llegue con un `PUT` del mismo dispositivo aún en curso (que no se corta). Reintenta después. Tras un `409` el staging queda intacto (la purga recoge lo que no se reintente); si el commit termina bien, se borra entero, incluidos los restos que no estaban en el manifiesto. Los `PUT` de otros dispositivos no se ven afectados. Un juego desactivado da `409` `err.sync.game_disabled`. No hay sesiones ni tokens: la coherencia entre `fingerprint` y `commit` la da `expect`. Máximo por fichero: `CHECKPOINT_HOOK_MAX_FILE_MB` (512 MiB por defecto): `413` `err.hook.file_too_large` con `params.max_mb`; se comprueba con `size`, con `Content-Length` y mientras llega el cuerpo (`size` y `Content-Length` son falsificables y con chunked no hay `Content-Length`). La subida va en streaming a disco: nunca se carga el cuerpo en memoria. **Staging:** todo el de un juego (todos sus dispositivos) tiene un tope, `CHECKPOINT_HOOK_STAGING_MAX_MB` (2048 MiB por defecto): al superarlo, `413` `err.hook.staging_full` con `params.max_mb` (se comprueba con `size` y mientras llega el cuerpo). El staging sin escrituras en `CHECKPOINT_HOOK_STAGING_TTL_H` horas (24 por defecto) se borra solo, al arrancar, cada hora (tarea de mantenimiento del scheduler, aunque la sync automática esté apagada) y de forma oportunista al subir; nunca el de un juego con el lock tomado o una ejecución en curso.

**Flujo de subida** (`fingerprint` dio `action: upload`):

1. Por cada fichero del manifiesto: `PUT /api/hook/{juego}/files?device=..&path=slot1/save.dat&size=10240&sha256=<sha256 del fichero entero>&offset=0` con el contenido en bruto (`Content-Type: application/octet-stream`). Respuesta `200` `{"game", "device", "path", "received", "size", "complete"}`. Los ficheros van a `data/staging/<juego>/<dispositivo>/`; **`data/hub/<juego>` no se toca**. Si se corta, repite con `offset` = bytes ya recibidos; si `offset` no coincide con lo que el hub tiene (o `sha256`/`size` cambiaron), `409` `err.hook.upload_offset_mismatch` con `params.received` (continúa desde ahí, o `offset=0` para reiniciar). Al completar los `size` bytes se verifica el sha256 (`422` `err.hook.sha_mismatch`: se descarta) y `complete` pasa a `true`. Más bytes que `size`: `422` `err.hook.upload_size_mismatch`. `size`, `offset` o `sha256` mal formados: `422` `err.hook.param_invalid`.
2. `POST /api/hook/{juego}/commit?device=..` con `{"expect": "<hub.hash de fingerprint, o null si el hub estaba vacío>", "manifest": [ ...el manifiesto completo... ]}`. Con el lock del juego comprueba, en orden: el hub no cambió (`409` `err.hook.hub_changed`: repite `fingerprint`); sigue mandando el dispositivo con la misma lógica que `fingerprint` (conflicto o hub más nuevo: `409` `err.hook.commit_rejected`, `params.reason` = `both-changed`, `no-baseline`, `inconsistent` o `hub`; no se toca nada); están todos los ficheros (`422` `err.hook.upload_incomplete`, con `params.missing` y `params.paths`, hasta 10); y el conjunto da la huella del manifiesto (`422` `err.hook.set_mismatch`). Entonces: guarda el hub actual en una versión nueva (`hub`), lo **reemplaza por el manifiesto entero** (lo que el hub tuviera de más desaparece; los ficheros de staging que no estén en el manifiesto se ignoran), aplica el `mtime` del manifiesto, fija la línea base del dispositivo y del hub, poda las versiones antiguas y deja una entrada en el historial (disparador `hook`, con el dispositivo). Respuesta `200`: `{"game", "device", "outcome": "ok", "hash", "files", "size", "version"}`; `outcome: "unchanged"` (sin `version`) si el hub ya era igual. El staging del dispositivo se borra.

**Flujo de bajada** (`fingerprint` dio `action: download`):

1. `GET /api/hook/{juego}/manifest?device=..`: `{"game", "device", "hash", "files", "size", "mtime", "manifest": [{"path", "sha256", "size", "mtime"}, ...]}` (el mismo formato que el manifiesto de `fingerprint`; `hash` es el `hub.hash`). Con el lock del juego. Decisión: es un endpoint aparte (y no se reutiliza `fingerprint`) para no obligar a hashear el hub entero en cada comparación ni a enviar el listado cuando no hace falta.
2. `GET /api/hook/{juego}/files?device=..&path=slot1/save.dat` por cada fichero que difiera de lo que el dispositivo tiene: cuerpo en bruto, `Content-Length` y `Accept-Ranges: bytes`. Con `Range: bytes=a-b` (un solo rango; `a-` y `-n` valen) responde `206` con `Content-Range`; un rango inválido, múltiple o fuera del fichero, `416` `err.hook.range_invalid` con `Content-Range: bytes */tamaño`. Fichero que no existe, `404` `err.hook.file_unknown`. El lock solo se toma para abrir el fichero.
3. El dispositivo verifica el sha256 de cada fichero y la huella del conjunto contra el `hash` del manifiesto, borra lo que le sobre y vuelve a llamar a `POST /api/hook/{juego}/fingerprint` con su manifiesto: si ahora es igual al hub (`none`/`same`), el hub fija esa huella como línea base del dispositivo (sin ella, su siguiente cambio local daría un conflicto falso). No hay endpoint de confirmación aparte.

```bash
curl -fsS -H "Authorization: Bearer ckd_..." "http://HOST:8088/api/hook/MiJuego/manifest?device=Steam%20Deck"
curl -fsS -X PUT -H "Authorization: Bearer ckd_..." --data-binary @save.dat \
  "http://HOST:8088/api/hook/MiJuego/files?device=Steam%20Deck&path=slot1/save.dat&size=10240&sha256=9f86d0...0a08&offset=0"
curl -fsS -X POST -H "Authorization: Bearer ckd_..." -H "Content-Type: application/json" \
  -d '{"expect": null, "manifest": [{"path": "slot1/save.dat", "sha256": "9f86d0...0a08", "size": 10240, "mtime": 1768501812}]}' \
  "http://HOST:8088/api/hook/MiJuego/commit?device=Steam%20Deck"
curl -fsS -H "Authorization: Bearer ckd_..." -H "Range: bytes=1048576-" "http://HOST:8088/api/hook/MiJuego/files?device=Steam%20Deck&path=slot1/save.dat"
```

Todos aparecen en el Swagger (`/api/docs`) con ejemplos y los errores `401`, `403`, `404`, `429`, `409`, `413` y `422`.

### Lanzadores

**Copiar los comandos de la web:** Configuración → subpestaña **Lanzadores** (sin plegado: se ve al abrirla; la key y el estado solo se piden entonces). Una **fila por juego guardado** con su nombre y, para la plataforma elegida en las pestañas comunes (Steam / Steam Deck, Lutris, Heroic, Windows con Playnite), el comando completo con tu API key, el id del juego y el dispositivo ya codificados, listo para copiar (con una nota de dónde se pega). Si el juego tiene más de un dispositivo, la fila trae su selector de dispositivo. Necesita la API key del perfil (sin ella pide generarla). La URL del hub, común a todas las filas, se rellena con la de la página, se puede editar y se recuerda en el navegador; por HTTP fuera de localhost avisa de que la key viaja en claro. Si un juego no tiene `process`, su fila avisa de que el hub no podrá vigilar el cierre; si está desactivado, lo indica («el aviso se omitirá»); un juego sin guardar pide guardarlo antes; sin juegos, un mensaje vacío. En cada fila, **Último aviso** por dispositivo: último `opened` / cierre recibido, hace cuánto, su resultado y, si hay vigilancia activa, su estado (el estado se refresca cada 15 s).

Los comandos de abajo son los mismos que genera la web.

El cliente debe esperar (hasta 60 s) y arrancar el juego **aunque falle el aviso** (hub caído, conflicto...), por eso se encadena con `;` y no con `&&`.

- **Steam** (Opciones de lanzamiento del juego):

  ```
  curl -fsS -m 60 --retry 3 -X POST -H "Authorization: Bearer <API_KEY>" "http://<HUB>:8088/api/hook/<JUEGO>/opened?device=<DISPOSITIVO>"; %command%
  ```

- **Lutris** (Configurar > Opciones del sistema > *Pre-launch script*, con «Wait for pre-launch completion» activado para que Lutris espere al aviso antes de arrancar):

  ```
  curl -fsS -m 60 --retry 3 -X POST -H "Authorization: Bearer <API_KEY>" "http://<HUB>:8088/api/hook/<JUEGO>/opened?device=<DISPOSITIVO>"
  ```

  Si el script sale con error, Lutris arranca igualmente el juego; sin la opción de espera, el juego arrancaría a la vez que la sincronización.

- **Heroic** (ajustes del juego → Avanzado → script antes de lanzar): el mismo `curl` que Lutris.

- **Windows / Playnite** (script previo del juego, PowerShell 5.1):

  ```
  Invoke-WebRequest -Method Post -Uri "http://<HUB>:8088/api/hook/<JUEGO>/opened?device=<DISPOSITIVO>" -Headers @{Authorization='Bearer <API_KEY>'} -TimeoutSec 60 -UseBasicParsing
  ```

  Alternativa con `curl.exe` (incluido en Windows 10/11): el mismo comando que en Lutris con `curl.exe` en lugar de `curl`.

### Cierre automático

Tras `opened`, el hub **vigila el proceso del juego en ese dispositivo** (el `process` del juego; mismo sondeo que usa la sincronización: `pgrep -f` por SSH en Linux, `tasklist` en Windows, `/proc` en «Este equipo») y, cuando se cierra, hace el checkpoint solo. El lanzador no necesita ningún hook de cierre: basta la línea de `opened` de Steam o Lutris.

1. `opened` sincroniza y arma la vigilancia (una por juego; un nuevo `opened` del mismo juego **reemplaza** la anterior).
2. Sondeo cada **15 s**. No se da el juego por cerrado hasta haberlo visto abierto al menos una vez. Si en **2 min** no se ve nunca, se descarta la vigilancia (suele ser un `process` mal puesto) y queda en el historial como omitido (`err.hook.never_seen`) y en el log del hub (`vigilante never_seen`).
3. Al dejar de verse el proceso, o si el dispositivo deja de responder (SSH caído, suspensión), espera **10 s** (para que se liberen los ficheros) y lanza el checkpoint.
4. El checkpoint usa la política de conflictos `skip` (nunca resuelve solo), el mismo lock y la misma lógica que `opened`, y aparece en el historial con el disparador «Cierre del juego» (`trigger: "hook_closed"`). Si aborta o el lock está tomado **no se reintenta**; el cron de la sincronización automática sigue como red de seguridad.

**Por qué no hubo checkpoint (historial).** Cuando la vigilancia termina sin checkpoint, queda una entrada con el disparador «Cierre del juego», el dispositivo y el juego, con icono y texto en el registro y el motivo en «Último aviso» (`GET /api/games/{juego}/hook-status` añade `code` y `params` a `last` si los hay). Solo se registra, no cambia lo que se sincroniza:

| Código | Resultado | Cuándo |
|---|---|---|
| `err.hook.never_seen` | omitido | El proceso no se vio abierto en el tiempo previsto (`CHECKPOINT_HOOK_FIRST_SEEN`); vigilancia descartada. |
| `err.hook.busy` | omitido | Al cerrarse, ya había una ejecución de ese juego en curso o el lock estaba tomado. Sin reintento. |
| `err.hook.game_removed` | omitido | El juego ya no está en la configuración al cerrarse. |
| `err.sync.game_disabled` | omitido | El juego se desactivó con la vigilancia ya armada: al cerrarse no hay checkpoint (y el chip de vigilancia desaparece). |
| `err.hook.checkpoint_failed` | error | El checkpoint lanzó una excepción antes de sincronizar; solo se guarda el tipo de excepción. |

Un sondeo fallido aislado no se registra (se trata como dispositivo sin respuesta, ver arriba). Una vigilancia reemplazada por un nuevo `opened`, o cancelada al apagar el hub, tampoco deja entrada. Las vigilancias no se persisten: si el hub se reinicia se pierden y lo cubre el cron.

Tiempos configurables con variables de entorno (en segundos):

| Variable | Por defecto | Qué es |
|---|---|---|
| `CHECKPOINT_HOOK_POLL` | `15` | Cada cuánto se sondea el proceso |
| `CHECKPOINT_HOOK_SETTLE` | `10` | Espera tras dejar de verlo, antes del checkpoint |
| `CHECKPOINT_HOOK_FIRST_SEEN` | `120` | Tiempo máximo para verlo abierto por primera vez |

Limitaciones:

- La vigilancia **vive en memoria**: si el hub se reinicia se pierde y solo la cubre el cron.
- `process` debe coincidir con el proceso real del juego (en Proton/Wine, el `.exe` bajo Wine). Con `pgrep -f` basta un fragmento del nombre o de la línea de comandos.

#### `GET /api/games/{juego}/hook-status`

Con **sesión de cookie** (la usa la web; la API key no vale aquí). Por cada dispositivo del juego: el último evento de hook y la vigilancia activa, sin datos sensibles: `{"devices": [{"device": "<id>", "last": {"trigger": "hook|hook_closed", "at": "<UTC ISO 8601>", "outcome": "ok|conflict|..."} | null, "watching": {"state": "waiting|running|settling", "since": "..."} | null}]}`. `404` si el juego no existe. Las entradas de historial de `hook` y `hook_closed` guardan ahora el dispositivo (campo `device`); las anteriores no lo tienen y no cuentan como «último aviso».

#### `GET /api/games`

Con **API key** (Bearer; mismo 401 único y 429 por IP que `/api/hook/*`; la cookie de sesión no vale). Con la key de **usuario** devuelve todos los juegos; con la de **dispositivo** `http`, solo los que tienen ese dispositivo en su lista. Lista de juegos y su último estado, para consultar desde un dispositivo sin SSH. Solo lectura; no devuelve rutas, dispositivos ni ajustes, ni mensajes del resultado. `steam_appid` es el id de Steam del juego (entero) o `null` si no tiene; es el mismo para todos los dispositivos y con la key de dispositivo solo se ven los juegos de ese dispositivo, como siempre. `status` es `null` si el juego nunca se ha sincronizado; `started`/`finished` son hora local del hub (ISO 8601 sin zona). No confundir con `GET /api/games/{juego}/hook-status` (sesión, interna).

```json
[
  {"id": "g1", "name": "Mi Juego", "enabled": true, "steam_appid": 1245620,
   "status": {"result": "ok", "code": "err.sync.done", "started": "2026-01-15T18:30:12", "finished": "2026-01-15T18:30:14"}},
  {"id": "g2", "name": "Otro Juego", "enabled": true, "steam_appid": null, "status": null}
]
```

```bash
curl -fsS -H "Authorization: Bearer ck_..." "http://HOST:8088/api/games"
```

#### `GET /api/hook/watches`

Con `Authorization: Bearer ck_...` (sin cookie; `401` sin key). Lista las vigilancias activas, sin datos sensibles: `[{"game": "<id>", "device": "<id>", "state": "waiting|running|settling", "since": "<UTC ISO 8601>", "last_poll": "<UTC ISO 8601>", "poll": <segundos>}]`. `since` es el inicio del estado actual; `last_poll`, el último sondeo completado (latido); `poll`, el intervalo de sondeo. `waiting`: aún no se ha visto el proceso; `running`: visto abierto; `settling`: cerrado, esperando antes del checkpoint.

```bash
curl -fsS -H "Authorization: Bearer ck_..." "http://HOST:8088/api/hook/watches"
```

#### `GET /api/watches`

Con **sesión de cookie** (la usa la web). Mismas vigilancias que `/api/hook/watches`, solo de juegos existentes, más la hora del servidor para medir el latido: `{"now": "<UTC ISO 8601>", "watches": [{"game", "device", "state", "since", "last_poll", "poll"}]}`. La pestaña Sincronizar la consulta cada 5 s (solo con la pestaña visible) y marca cada juego vigilado con un borde del color de su estado y una franja inferior con icono + texto (esperando a que arranque / jugando desde HH:MM / cerrando / sin latido); en la cabecera, un contador «● Vigilando · N» que despliega la lista. Si `last_poll` tiene más de 3 × `poll` de antigüedad, pasa a ámbar (borde discontinuo) con el texto «Sin latido».

## Instalar como app (PWA)

Checkpoint sigue siendo instalable desde el menú del navegador (manifest, iconos y service worker incluidos), pero el hub ya no muestra un botón ni un aviso propio de instalación.

- **iOS (Safari):** funciona también por `http://`. Compartir, «Añadir a pantalla de inicio».
- **Android (Chrome):** la opción de instalar del menú de Chrome y el service worker exigen contexto seguro: **HTTPS** (o `localhost`). Con `http://IP-LAN` Chrome no ofrece instalarla. Pon Checkpoint detrás de un proxy inverso con TLS (Caddy, Traefik, nginx) y entra por el dominio HTTPS.
- Para probarlo sin certificado propio: en el móvil, `chrome://flags/#unsafely-treat-insecure-origin-as-secure` con tu `http://IP-LAN:8088` (solo para pruebas), o un túnel HTTPS al puerto 8088.
- El service worker no cachea nada: la app sigue necesitando el servidor, y las actualizaciones se ven al recargar.
- Los iconos se regeneran con `node frontend/scripts/make-icons.mjs` (sin dependencias).

## Seguridad

- Cambia el usuario y la contraseña del `.env` y restringe sus permisos (`chmod 600 .env`).
- No expongas el servicio a Internet sin un proxy inverso con TLS (activa `CHECKPOINT_COOKIE_SECURE=1` y `CHECKPOINT_TRUST_PROXY=1`).
- **Límite de frecuencia del login y de `/api/hook/*`:** se cuenta por IP de origen, con contadores separados (login y API key). Los 2 primeros fallos seguidos no esperan; el 3.º bloquea 5 s y cada fallo posterior duplica la espera (10, 20, 40 s...) hasta 15 min. Mientras dura el bloqueo se responde `429` con `Retry-After` (también con una key válida) y esos intentos no alargan la espera. Un acierto reinicia el contador, y una IP sin fallos durante 1 h se olvida. Es en memoria: se reinicia con el hub. **Detrás de un proxy inverso** pon `CHECKPOINT_TRUST_PROXY=1` para que cuente la IP real del cliente: se toma la **última** entrada de `X-Forwarded-For` (la que añade tu proxy; lo que el cliente ponga delante no cuenta), así que el proxy debe añadir esa cabecera y el hub no debe ser accesible sin pasar por él. Sin esa variable, todos los clientes comparten la IP del proxy y los fallos de uno bloquean a los demás; con ella activada sin proxy delante, un cliente podría falsear su IP y evadir el límite.
- La clave privada vive en `keys/` y no debe compartirse ni subirse a ningún repositorio.
- Las API keys (de usuario, ver «API key de usuario», y de dispositivo `http`, ver «API key de dispositivo `http`») se guardan cifradas en `data/`; su secreto, `hub.secret`, vive junto a `config.yaml`, fuera de `data/`. No subas ninguno de los dos a un repositorio y trata la key como una contraseña: regenérala si se filtra.
- Si cambia la huella de un dispositivo, la conexión falla; revisa la entrada de `keys/known_hosts` antes de borrarla.
- Usa una cuenta limitada en los dispositivos siempre que sea posible.
- Sin Docker, `serve` escucha en `127.0.0.1`: ábrelo a la red solo si lo necesitas. «Este equipo» da acceso al sistema de ficheros de quien ejecuta Checkpoint, con sus permisos; no lo ejecutes como administrador/root.

## Desarrollo

```bash
cd backend && python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt && pytest
cd ../frontend && npm install && npm run dev     # desarrollo
npm test                                         # pruebas de node (borrador, formato, i18n es/en, tarjeta de dispositivo, avisos de versión y arquitectura)
npm run build                                    # producción
```

### Formato, lint y auditorías

- Frontend: `npm run lint` (ESLint), `npm run format` y `npm run format:check` (Prettier, incluye los SCSS; los JSON de `src/locales` quedan fuera).
- Backend: `ruff check .` y `ruff format .` (o `--check`) desde `backend/`; configuración en `backend/ruff.toml`.
- Cobertura: `pytest --cov=app --cov-fail-under=90` (backend) y `npm run test:coverage` (frontend: líneas ≥ 90 %, ramas ≥ 88 % sobre `src/**`). Tamaño del bundle: `npm run build && npm run check:size` (umbrales en `frontend/scripts/check-bundle-size.mjs`).
- Las auditorías ya no están en `ci.yml`: las hacen workflows propios (gitleaks y CodeQL, además de `audit.yml`). El workflow `audit.yml` ejecuta `npm audit` y `pip-audit` (`--audit-level=high` en producción, también cada semana, más un lote mensual de desarrollo) y deja informes JSON; `security-issues.yml` los convierte, junto con los de gitleaks, en un issue con plazo por hallazgo (los de Trivy y de paquetes, agrupados por paquete y versión, máximo 10 nuevos por ejecución; 48 h crítico y alto, siguiente versión moderado, mensual bajo; un secreto, inmediato; ajustable con las variables `SLA_CRITICAL_HIGH_HOURS`, `SLA_MODERATE` y `SLA_LOW`). Gitleaks usa el binario oficial con versión y SHA-256 fijados: al actualizarlo cambia `GITLEAKS_VERSION` y `GITLEAKS_SHA256` a la vez (Dependabot no lo mantiene). Dependabot abre PRs que se revisan a mano: mensuales en npm y pip (un PR con las minor y patch agrupadas y uno aparte por cada major, salvo `react` con `react-dom` y `vite` con `@vitejs/*`, que llegan agrupados como majors porque son dependencias de pares acopladas y un PR suelto rompe `npm ci`; hay que probar cada major a mano) y semanales y agrupados en docker y github-actions (en github-actions, con 7 días de espera tras publicarse cada versión, `upload-artifact` y `download-artifact` en su propio grupo y sus majors, igual que los majors y minors de `codeql-action`, subidos a mano). Los majors de `eslint` y `@eslint/js` se ignoran porque `eslint-plugin-jsx-a11y` y `eslint-plugin-react` solo admiten eslint hasta la 9; hay que revisarlo cuando admitan la 10 (ver el comentario de `.github/dependabot.yml`). Los majors de `react` y `react-dom` también se ignoran por ahora: React 19 añade ~80 KB al bundle propio y hace fallar el presupuesto de `check:size`; al levantar la regla hay que subir ese presupuesto (ver el comentario de `.github/dependabot.yml`).
- Los commits de formato masivo están listados en `.git-blame-ignore-revs`. GitHub lo respeta solo; para que `git blame` también los ignore en local:

```bash
git config blame.ignoreRevsFile .git-blame-ignore-revs
```

### Estructura del código

El detalle (árbol, reglas de dependencia y cómo añadir un módulo) está en [`docs/structure.md`](docs/structure.md). Resumen:

**Backend (`backend/app/`)**: `main.py` es solo la fábrica de la app (`app_factory`); `cli.py` es la CLI.

| Carpeta | Contenido |
|---|---|
| `api/` | Capa web (FastAPI): `routers/` (uno por área: `hook`, `games`, `session`, `profile`, `devices`, `config`, `sync`, `versions`, `scheduler`, `updates`, `spa`), `auth.py`, `deps.py`, `middleware.py` y `docs/` (OpenAPI y Swagger de la API key) |
| `services/` | Lógica de negocio sin FastAPI (`context`, `runs`, `hooks`, `devices`, `games`, `status`, `versions`) |
| `sync/` | Motor de sincronización: `engine`, `decide`, `fingerprint`, `versions`, `baseline`, `errors`, `locking`, `scheduler`, `watcher` y `transport/` (`base`, `posix`, `windows`, `local`) |
| `config/` | Modelo y almacén de `config.yaml` |
| `users/` | Datos por usuario: `apikey`, `avatar`, `history` |
| `core/` | Utilidades base: `settings`, `errors`, `hosts`, `bootstrap`, `redact`, `runtime`, `updates` |

**Frontend (`frontend/src/`)**: `main.jsx` y `App.jsx`; `pages/` (Login, Sync, Versions, Settings); `components/ui/` (componentes genéricos con su SCSS); `components/<zona>/` (`profile`, `updates`, `watch`, `config`, `autosync`, `launchers`, `keyhelp`, `sync`); `hooks/`; `lib/` (cliente de la API en `lib/api.js` y `lib/api/<recurso>.js`, i18n, errores, formato...); `locales/`; `styles/` (variables, temas, base y `main.scss`, que solo ordena los `@use`). Los imports entre carpetas usan el alias `#src/` (`package.json` → `imports`; `#/` no es válido en Node). Los tests de `frontend/test/` reflejan esa estructura, con utilidades comunes en `test/helpers/`.

Dos tests comprueban las reglas de dependencia: `backend/tests/test_architecture.py` y `frontend/test/architecture.test.mjs`.

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

Los elementos que se repiten viven en `frontend/src/components/ui/` (importa desde `components/ui/index.js`), cada uno con su partial SCSS al lado (`frontend/src/components/ui/_<componente>.scss`). Para cambiar el aspecto de todos los usos, edita el partial; para cambiar el marcado, el componente. No escribas a mano `className="btn"`, `badge`, `alert`, etc.

| Componente | Props | Estilos |
|---|---|---|
| `Button` | `variant` (`primary`, `danger`, `ghost`), `className`, `type` (`button` por defecto) | `_button.scss` |
| `Badge` | `status` (`ok`, `error`, `conflict`, `partial`, `aborted`, `dry-run`, `running`) | `_badge.scss` |
| `Alert` | `variant` (`error`, `ok`, `warn`, `info`), `inline`, `compact` (sin márgenes, icono + texto en fila), `as` | `_alert.scss` |
| `Pill` | `highlight`, `tone` (`info`, y `manual`, `scheduled`, `launcher` = origen en el registro) | `_pill.scss` |
| `Select` | `options` (`[{ value, label }]`), `placeholder` | `_control.scss` |
| `Checkbox` | `label` + props del input | `_control.scss` |
| `Switch` | `label` + props del input | `_switch.scss` |
| `Tabs` | `tabs` (`[{ id, label, short?, dot? }]`), `value`, `onChange`, `label`; los hijos son el panel activo. `variant="subnav"`: subnavegación subrayada (Configuración), distinta del filtro normal; `keepMounted` + `panels` (`{ id: nodo }`): todos los paneles, los inactivos con `hidden` sin desmontar (un valor null no se pinta); `short`: etiqueta corta en ≤640 px; `dot`: punto de aviso con ese texto para lectores de pantalla. Roles `tablist`/`tab`/`tabpanel`, flechas, Inicio y Fin | `_tabs.scss` |
| `CopyBox` | `value`, `label`, `what` (qué se copia: el botón dice «Copiar {what}», p. ej. «Copiar comando de Steam» o «Copiar clave API»), `describedBy`; caja de código monoespaciada que ajusta líneas + botón copiar (`copy` → `check` 2 s, `clipboard.js` con fallback) | `_copybox.scss` |
| `WatchBar` | `state` (`waiting`, `running`, `settling`, `stale`), `since` (opcional), hijos = texto; franja inferior de la tarjeta con icono decorativo + texto, color por estado (el icono se dibuja sin glifos de fuente: punto y anillo por CSS, `spinner` y `alert` de `Icon`; alineado con la primera línea del texto); la tarjeta lleva el borde con `watchCardClass(estado)` de `src/components/watch/watch.js` | `_watch.scss` |
| `WatchStatus` | `state` (igual), hijos = texto; punto decorativo + texto en línea (filas de la lista de la cabecera), `running` pulsa | `_watch.scss` |
| `WatchSummary` (componente de la app, no genérico) | `watch` (`{now, watches}` de `useWatches`), `config`; chip «● Vigilando · N ▾» en la barra superior con lista desplegable (juego, dispositivo, estado con `WatchStatus`); oculto sin vigilancia; Esc, clic fuera y salir del foco lo cierran. En móvil (<=640 px) es punto + número («99+»; el texto completo va en `aria-label`) y la lista ocupa el ancho de la barra con 8 px de margen y scroll propio; chip y filas de 44 px (`$touch-watch`, local) | `_watch.scss` |
| `Input` | props del input (texto sin autocompletar ni corrector por defecto); acepta `ref` | `_control.scss` |

Registro de ejecuciones (`AutoSyncLog`): cada entrada es un `<li class="run">` con cabecera en rejilla (fecha y hora, origen —etiqueta `Pill` de color con texto: Manual, Programado o Launcher; `startup` cuenta como Programado y `hook`/`hook_closed` como Launcher, el valor guardado no cambia—, duración —«—» si es 0 o falta— y una única `Badge` de estado) y, debajo, una línea por juego (nombre y dispositivo si consta) con su mensaje; solo se repite la `Badge` en una fila de juego si hay resultados distintos. Todo lo que no es correcto lleva icono además de texto, y el motivo sale una sola vez (el resumen de una entrada con `code` no se repite si su juego dice lo mismo). Con más de 3 juegos, los correctos van plegados tras un botón-resumen con `aria-expanded` («N juegos: 12 correctos, 1 error») y los omitidos, con error o abortados se ven siempre. Encima de la lista, un filtro por origen (`Tabs`: Todos, Manual, Programado, Launcher; estado local, sin llamar al servidor; los orígenes desconocidos solo salen en «Todos»). Tipos y resultados desconocidos se muestran tal cual. El estilo vive en `_autosync.scss` (la etiqueta de origen, en `_pill.scss`); las columnas de la cabecera usan `minmax(..., max-content)` y en <=640 px pasa a dos líneas.

La consulta de `/api/watches` (cada 5 s, solo con la pestaña visible) vive en un único hook, `useWatches` (`src/hooks/useWatches.js`), llamado desde `App`: el contador de la barra y las tarjetas de Sincronizar reciben los mismos datos, sin peticiones duplicadas.

Aviso de actualización: en pantallas anchas (>=480 px) es el botón de la barra; por debajo sale de la barra y pasa al menú del perfil como entrada «Actualizar a vX.Y.Z» (abre el mismo diálogo), y el avatar muestra un punto con texto accesible mientras haya actualización aplicable.

Menú del perfil (`ProfileMenu`), de arriba abajo, con separador fino y rótulo discreto por grupo (`role="group"` + `aria-labelledby`): identidad (foto, nombre, Cambiar/Quitar foto), entrada «Actualizar a vX.Y.Z» (solo <480 px y con actualización), **Preferencias** (Idioma y Tema con el mismo patrón de fila `.profile-row`: icono + etiqueta + valor actual a la derecha, 44 px; el idioma es el `Select` nativo como valor, `LanguageSelect row`), **Integración** (API key plegable, cerrada por defecto, `aria-expanded`/`aria-controls`; el contenido sigue montado y solo `hidden`) con, justo debajo, el enlace «Documentación de la API» (`/api/docs`, pestaña nueva con `rel="noopener"`; fila `.profile-row`) y **Cuenta** (Salir; la versión instalada solo se muestra en el pie de la app). Esc y clic fuera cierran; no es modal.

El perfil usa estos componentes: la sección «API key» es un bloque con fondo `--surface-2` (encabezado con icono `key`), la key completa en un cuadro monoespaciado que ajusta en varias líneas, `CopyBox` para la key y para los comandos de la subpestaña Lanzadores (copia con icono `copy` → `check` 2 s), `Button` y `Button variant="danger"` (Regenerar / Revocar, mismo ancho) y `Alert compact` para el aviso de HTTP.

Los tests `frontend/test/components/ui/ui-components.test.mjs` fijan las clases y atributos que producen.

## Licencia

MIT. Ver [`LICENSE`](LICENSE).
