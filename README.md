<p align="center">
  <img src="docs/logo.svg" alt="Checkpoint" width="360">
</p>

# Checkpoint

![Licencia MIT](https://img.shields.io/badge/licencia-MIT-green)

Checkpoint mantiene sincronizadas las partidas guardadas de un juego entre dos dispositivos, por SSH, desde una interfaz web. Corre en un contenedor Docker; no se instala nada en los dispositivos.

- Sincroniza los guardados de un juego entre dos dispositivos y elige la copia más reciente.
- Interfaz web con tema gaming.
- Sincronización automática cada X horas, con registro de ejecuciones.
- Versiones y copias de seguridad de cada guardado, con restauración desde la UI.
- Modo de prueba (dry-run) y log en vivo.
- Configuración editable desde la UI o a mano.

## Cómo funciona

```
 Dispositivo A  <--- SSH --->  Checkpoint (Docker)  <--- SSH --->  Dispositivo B
 (ruta del save)               copias + versiones                  (ruta del save)
```

- **Dispositivos**: equipos con servidor SSH (Windows o Linux). Checkpoint entra con una clave que genera él mismo.
- **Juegos**: cada juego enlaza dos dispositivos y la carpeta de guardado en cada uno. Los nombres de dispositivos y juegos son libres (hasta 64 caracteres, con espacios, acentos y emojis; sin `/` ni `\`).
- **Sincronizar**: Checkpoint descarga los guardados, recuerda cuál era el estado tras la última sincronización y propaga el lado que ha cambiado. Si solo un dispositivo está conectado, lo compara con la copia del hub. Antes de sobrescribir guarda la copia perdedora como versión.
- **Versiones**: se conservan las últimas N de cada juego (`max_versions` global, 20 por defecto, 0 = sin límite; `keep_versions` lo sustituye en un juego) y se pueden restaurar desde la UI.

Solo la opción «gana el más reciente» de los conflictos usa fechas de modificación: mantén la hora sincronizada (NTP) en el servidor y en los dispositivos.

## Instalación

Requisitos: Docker y Docker Compose.

1. Clona el repositorio:
   ```bash
   git clone https://github.com/mcondepoGH/Checkpoint.git && cd Checkpoint
   ```
2. Copia la plantilla y pon tu usuario y contraseña:
   ```bash
   cp .env.example .env     # edita CHECKPOINT_USER y CHECKPOINT_PASSWORD
   ```
3. Arranca:
   ```bash
   docker compose up -d --build
   ```
4. Abre `http://IP-DEL-SERVIDOR:8088`.

| Variable | Por defecto | Descripción |
|---|---|---|
| `CHECKPOINT_USER` | (obligatoria) | Usuario de acceso a la web |
| `CHECKPOINT_PASSWORD` | (obligatoria) | Contraseña, en claro en el `.env` |
| `CHECKPOINT_PORT` | `8088` | Puerto publicado |
| `CHECKPOINT_AUTO_ENABLED` | `0` | Valor inicial de la sync automática |
| `CHECKPOINT_AUTO_INTERVAL_HOURS` | `24` | Valor inicial del intervalo |
| `CHECKPOINT_AUTO_ON_CONFLICT` | `skip` | Valor inicial ante conflictos en la sync automática (`skip` o `newest`) |
| `CHECKPOINT_UPDATE_CHECK` | `1` | Valor inicial de la comprobación de versiones nuevas (`0` la desactiva; lo guardado en la UI prevalece) |
| `CHECKPOINT_UPDATE_CHANNEL` | `stable` | Canal inicial de versiones: `stable` o `beta` (pruebas; otro valor se trata como `stable`; lo guardado en la UI prevalece) |
| `CHECKPOINT_UPDATE_REPO` | `mcondepoGH/Checkpoint` | Repositorio de GitHub (`dueño/repo`) cuyas Releases se consultan |
| `CHECKPOINT_UPDATE_CACHE_HOURS` | `6` | Horas que se reutiliza el resultado antes de volver a consultar (mínimo 0.25) |
| `CHECKPOINT_COOKIE_SECURE` / `CHECKPOINT_TRUST_PROXY` | `0` | Pon `1` tras un proxy inverso con HTTPS |
| `TZ`, `PUID`, `PGID` | `Europe/Madrid`, `1000` | Zona horaria y usuario del contenedor |

El prefijo antiguo `SAVESYNC_*` sigue aceptándose (obsoleto). Si la contraseña lleva `$`, ponla entre comillas simples.

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

Variables para cambiarlo (las de Docker siguen igual): `CHECKPOINT_HOME_DIR` (carpeta base), o una a una `CHECKPOINT_CONFIG` (fichero `config.yaml`), `CHECKPOINT_DATA`, `CHECKPOINT_SSH_KEY`, `CHECKPOINT_KNOWN_HOSTS` y `CHECKPOINT_STATIC` (web compilada; por defecto `frontend/dist`). También `CHECKPOINT_HOST` y `CHECKPOINT_PORT` para `serve`.

Cómo se decide si es Docker o nativo: la imagen fija `CHECKPOINT_IN_DOCKER=1`; si no, se mira si existe `/.dockerenv` o `/run/.containerenv`. `CHECKPOINT_RUNTIME=docker|native` fuerza el resultado.

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
- El acceso por SSH a dispositivos remotos no se ha probado en esta rama contra un servidor SSH real (las pruebas lo simulan); es el mismo código que antes.

## Primeros pasos

1. En **Configuración**, copia la **clave pública SSH** (botón Copiar). Solo hace falta si vas a usar dispositivos remotos.
2. Añádela a `authorized_keys` de cada dispositivo. El botón **?** junto a la clave muestra los comandos para Linux y Windows, incluida la activación del servidor SSH.
3. Añade los **dispositivos** (nombre, host, puerto, usuario, sistema) y pulsa **Probar conexión**. La primera vez se guarda la huella del host. Sin Docker puedes marcar uno como **Este equipo** (sin SSH).
4. Añade los **juegos**: elige dos dispositivos y la carpeta de guardado en cada uno (ruta absoluta, por ejemplo `/home/usuario/.local/share/Juego/Saves` o `C:\Users\Usuario\AppData\Local\Juego\Saves`).
5. Ve a **Sincronizar**. Prueba primero con **Dry-run** y después sin él.

## Sincronización automática

En **Configuración > Sincronización automática** activa la opción y elige cada cuántas horas se ejecuta (de 0.25 a 168). Cada ciclo sincroniza todos los juegos; si uno falla, los demás continúan. Debajo se muestra el **Registro de ejecuciones** con resultado por juego y detalle al hacer clic. Los ajustes guardados en la UI prevalecen sobre las variables de entorno.

## Nuevas versiones

Checkpoint comprueba si hay una versión nueva consultando las Releases públicas de GitHub (solo HTTPS, por defecto solo versiones estables: se ignoran borradores y pre-releases). Si la hay, aparece la insignia **Nueva versión disponible** en la cabecera, con la versión instalada, la nueva y sus notas. Por ahora no actualiza nada: para actualizar, reconstruye la imagen y vuelve a levantar el contenedor.

- La versión instalada sale del fichero `VERSION` de la raíz del repositorio (la imagen lo incluye). Sin él, o en desarrollo, es «desconocida» y no se ofrece ninguna actualización.
- El resultado se guarda en memoria y en `data/update_cache.json` durante `CHECKPOINT_UPDATE_CACHE_HOURS`. Un fallo de red es silencioso: se conserva el último resultado y se reintenta pasados unos minutos.
- Se desactiva en **Configuración > Comprobar actualizaciones** (o con `CHECKPOINT_UPDATE_CHECK=0` como valor inicial). Desactivada, no se hace ninguna petición a internet. El botón **Comprobar ahora** fuerza la consulta (máximo una por minuto).
- **Canal** (Configuración > Comprobar actualizaciones): **Estable** (por defecto) solo ofrece Releases normales; **Pruebas** (`beta`) ofrece también pre-releases (nunca borradores), que pueden fallar. En Pruebas se ofrece la versión más alta entre estables y preliminares, con el orden de semver: `0.5.0-rc.1` < `0.5.0-rc.2` < `0.5.0`. Un tag con sufijo (`-rc.1`) cuenta como preliminar aunque GitHub no lo marque. Cambiar de canal descarta el resultado guardado y vuelve a consultar. Nunca se ofrece bajar de versión: desde una preliminar en canal Estable solo se avisa cuando haya una estable mayor. La insignia y el diálogo marcan «preliminar» cuando procede.
- La etiqueta de imagen `beta` llegará con la fase de publicación; hoy el canal solo cambia qué avisos se muestran.
- API (requiere sesión): `GET /api/version`, `GET /api/updates[?refresh=true]` (incluye `canal` y `prerelease`, si la versión ofrecida es preliminar) y `PUT /api/updates` con `{"enabled": true|false, "channel": "stable"|"beta"}` (parcial: basta uno de los dos; valor no válido, 422).

## Conflictos

Hay conflicto cuando los dos dispositivos han cambiado desde la última sincronización y su contenido es distinto (o, en la primera sincronización, ya difiere). Checkpoint nunca lo decide por la fecha a ciegas.

- **Sincronización automática**: `on_conflict` en Configuración > Sincronización automática. `skip` (por defecto) no guarda nada y marca el juego como «Conflicto»; `newest` hace ganar el save más reciente (si las fechas difieren menos de 2 s, se omite). Un juego puede sustituirlo con `on_conflict` en `config.yaml`.
- **Sincronización manual**: siempre pregunta. Un popup ofrece cancelar, «Gana el más reciente» o elegir qué dispositivo gana, con fecha y tamaño de cada uno. En la CLI: `checkpoint sync JUEGO --resolve newest|device:DISPOSITIVO` (sale con código 3 si hay conflicto).

En todos los casos la copia perdedora se guarda antes en versiones. La primera sincronización tras actualizar solo tiene el hub como referencia: si ambos lados difieren, se trata como conflicto.

## Configuración

| Carpeta | Contenido |
|---|---|
| `config/` | `config.yaml` (dispositivos y juegos) |
| `keys/` | clave SSH generada y `known_hosts` |
| `data/` | copias, versiones, logs y registro de la sync automática |

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

La clave de cada juego y dispositivo es su **ID interno**, que no cambia nunca; `name` es solo una etiqueta y se puede renombrar libremente sin perder saves, versiones ni logs. La CLI y la API aceptan el ID o el nombre. Un `config.yaml` antiguo (indexado por nombre, sin `name`) sigue funcionando y se convierte al formato nuevo la primera vez que guardas desde la UI, conservando los datos.

## Seguridad

- Cambia el usuario y la contraseña del `.env` y restringe sus permisos (`chmod 600 .env`).
- No expongas el servicio a Internet sin un proxy inverso con TLS (activa `CHECKPOINT_COOKIE_SECURE=1` y `CHECKPOINT_TRUST_PROXY=1`).
- La clave privada vive en `keys/` y no debe compartirse ni subirse a ningún repositorio.
- Si cambia la huella de un dispositivo, la conexión falla; revisa la entrada de `keys/known_hosts` antes de borrarla.
- Usa una cuenta limitada en los dispositivos siempre que sea posible.
- Sin Docker, `serve` escucha en `127.0.0.1`: ábrelo a la red solo si lo necesitas. «Este equipo» da acceso al sistema de ficheros de quien ejecuta Checkpoint, con sus permisos; no lo ejecutes como administrador/root.

## Desarrollo

```bash
cd backend && python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt && pytest
cd ../frontend && npm install && npm run dev     # desarrollo
npm test                                         # pruebas de node (borrador, tarjeta de dispositivo y avisos de versión)
npm run build                                    # producción
```

## Licencia

MIT. Ver [`LICENSE`](LICENSE).
