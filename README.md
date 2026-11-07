# Checkpoint (savesync)

Checkpoint mantiene sincronizadas las partidas guardadas de un juego entre dos dispositivos (por ejemplo un PC con Windows y una Steam Deck). Corre en un contenedor Docker y se conecta por SSH; no se instala nada en los dispositivos.

## Características
- Sincronización de partidas guardadas por SSH entre dos dispositivos, decidiendo qué copia es la más reciente.
- Interfaz web con tema gaming.
- Sincronización automática cada X horas, con registro de lo ocurrido.
- Versiones y copias de seguridad de cada guardado, con restauración desde la UI.
- Backend Python FastAPI (pydantic valida la config y trae streaming SSE). Frontend React + SCSS (Vite).

## Instalación con docker compose
```bash
git clone https://github.com/mcondepoGH/Checkpoint.git && cd Checkpoint
cp .env.example .env     # edita SAVESYNC_USER y SAVESYNC_PASSWORD
docker compose up -d --build
```
La UI queda en `http://IP-DEL-SERVIDOR:8088`.

## Aviso de seguridad
- Cambia el usuario y la contraseña por defecto del `.env` antes de arrancar.
- La clave SSH se genera sola y se guarda en `/keys` (volumen `./keys`). Es la clave privada de acceso a tus dispositivos: no la compartas ni la subas a ningún repositorio.
- No expongas el servicio a Internet sin un proxy inverso con TLS (ver HTTPS más abajo).

## Arranque
1. Añade a tu `.env` (copia `.env.example`, o usa el de tu stack):
   ```
   SAVESYNC_USER=admin
   SAVESYNC_PASSWORD=cambia-esto
   ```
2. Levanta el servicio (UI en `http://IP-DEL-SERVIDOR:8088`):
   ```bash
   docker compose up -d --build savesync
   ```
3. En la UI, pantalla **Dispositivos**: copia la **clave pública** y pégala en cada dispositivo (ver "Clave SSH y huellas").

No hay nada más que preparar. Al arrancar, el contenedor crea `./config`, `./keys` y `./data` si faltan y corrige sus propietarios (aunque Docker las haya creado como root), crea un `config.yaml` vacío si falta (`config.example.yaml` queda solo como referencia), genera la clave SSH si falta y guarda las huellas de los dispositivos en el primer uso. La app corre sin root (`PUID`/`PGID` en `.env`, por defecto 1000). Imágenes base multi-arch (x86_64 y arm64).

### Contraseña
La autenticación usa solo `SAVESYNC_USER` y `SAVESYNC_PASSWORD` (en claro en el `.env`; acceso solo LAN, restringe los permisos del `.env`, p. ej. `chmod 600`). El contenedor hashea la contraseña con bcrypt en memoria al arrancar, la compara en tiempo constante y no la escribe a disco ni la loguea. Si falta alguna de las dos, el contenedor no arranca y el log dice `Faltan SAVESYNC_USER / SAVESYNC_PASSWORD`.

### HTTPS
La app escucha HTTP en la LAN. Para HTTPS pon un proxy inverso (Nginx Proxy Manager, Caddy, Traefik) hacia `savesync:8088`, activa `SAVESYNC_COOKIE_SECURE=1` y `SAVESYNC_TRUST_PROXY=1` (el límite de intentos usará `X-Forwarded-For`). Sin proxy deja ambas a 0, o la cookie `Secure` no viajará por HTTP. Los estáticos del frontend se sirven sin sesión (solo pintan el login, sin secretos); toda ruta `/api/*` exige sesión.

## Clave SSH y huellas (automático)
- **Clave**: si `keys/id_ed25519` no existe, se genera al primer arranque (ed25519, sin passphrase, permisos 600). `./keys` se monta en lectura-escritura. La UI (Dispositivos) muestra la **pública** con botón Copiar; también la da `GET /api/ssh/public-key` (con sesión). La privada nunca se expone.
- **known_hosts** (confianza en el primer uso, TOFU): al "Probar conexión" o sincronizar con un host sin entrada, se hace `ssh-keyscan`, se guarda en `keys/known_hosts` y se avisa en el log ("host key guardada (primer uso)"). Si la clave de un host cambia después, la conexión **falla** con un aviso claro y no se sobrescribe nada; si el cambio es legítimo, quita a mano esa entrada de `keys/known_hosts`. SSH sigue con `StrictHostKeyChecking=yes`. Si te preocupa un primer contacto en una red no fiable, rellena `known_hosts` tú antes.

Copia la clave pública a cada dispositivo:
- Steam Deck / Linux: añade la línea a `~/.ssh/authorized_keys` (o `ssh-copy-id -i keys/id_ed25519.pub deck@IP`).
- Windows: cuenta administradora, en `C:\ProgramData\ssh\administrators_authorized_keys` (permisos solo Administrators y SYSTEM); cuenta normal, en `C:\Users\<user>\.ssh\authorized_keys`.

## Activar SSH
**Windows** (PowerShell como administrador):
```powershell
Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0
Set-Service sshd -StartupType Automatic; Start-Service sshd
```
Deja el shell por defecto (cmd.exe): savesync lo necesita. Usa `tar.exe` (incluido en Windows 10+). Usuario local, no de dominio.

**Steam Deck** (modo escritorio, Konsole): `passwd` y luego `sudo systemctl enable --now sshd`.

## Rutas típicas
- Windows: `C:/Users/<user>/AppData/Local/<Juego>/...` o `C:/Users/<user>/Documents/...` (se acepta `\` y se normaliza a `/`).
- Steam Deck con Proton: `/home/deck/.local/share/Steam/steamapps/compatdata/<AppID>/pfx/drive_c/users/steamuser/...` (sustituye `<AppID>` por el número real).
- Debe ser un **directorio absoluto** del save. Caracteres permitidos: letras, números, espacio y `_ - . / ( ) [ ] + , @ ~ = # { }`.

## Relojes (NTP)
"Gana el más reciente" depende de las fechas de modificación. El servidor de savesync, el PC y el Deck deben tener NTP activo (Windows: `w32tm /resync`; SteamOS: `timedatectl set-ntp true`; servidor: sincronización de hora del sistema). Un desfase de minutos puede elegir mal el ganador; aun así, las copias perdedoras se guardan siempre antes de sobrescribir.

## Uso
**UI**: Sincronizar (dry-run opcional, log en vivo, estado de la última ejecución) > Versiones > Configuración (dispositivos y juegos, ver abajo). También puedes editar `config/config.yaml` a mano: se valida al leerlo y la UI se entera sola.

### Pantalla Configuración
Sustituye a las antiguas pantallas Dispositivos y Juegos: todo el `config.yaml` se edita en un formulario, sin reiniciar el contenedor.

- **Dispositivos**: una tarjeta por dispositivo (nombre, host, puerto, usuario, SO desplegable). "Probar conexión" prueba los datos del formulario aunque aún no estén guardados. Añadir y eliminar con botones; si eliminas un dispositivo que usa algún juego, pide confirmación y esos juegos pierden ese dispositivo.
- **Juegos**: una tarjeta por juego con dos selectores de dispositivo (no se pueden repetir y solo ofrecen los existentes), una ruta del save por cada dispositivo elegido, proceso opcional y versiones a conservar (1 a 100).
- **Validación en vivo**: mientras escribes, la UI llama a `POST /api/config/validate`, que usa el mismo validador que la carga del fichero (`config.py`). Los errores salen junto a su campo (`games.ejemplo.paths.pc`, etc.) antes de guardar.
- **Guardar**: "Guardar…" muestra primero un diff (qué dispositivos y juegos se añaden, cambian o eliminan). Al confirmar se escribe `config.yaml` de forma atómica (temporal + fsync + rename, conservando los permisos del fichero) y se aplica al instante. Las sincronizaciones en curso terminan con la configuración con la que empezaron.
- **Copias**: antes de cada guardado la versión anterior se copia a `data/config-backups/config.yaml.bak-AAAA-MM-DD_HHMMSS` (máximo 10; se podan las más antiguas). "Restaurar versión anterior" lista las copias, muestra el diff y restaura (la versión actual también queda respaldada).
- **Ver YAML**: muestra, solo lectura, el YAML tal como se escribiría.
- **Comentarios**: el guardado usa `ruamel.yaml` sobre el fichero existente, así que los comentarios, el orden y el estilo de comillas y de listas `[a, b]` se conservan. Los dispositivos y juegos nuevos se escriben en estilo de bloque. Si el fichero actual no se puede interpretar, se regenera sin comentarios.
- **Cambios externos**: el backend comprueba `config.yaml` cada segundo (inodo, tamaño, mtime) y avisa a la UI por SSE (`/api/config/events`). Si editas a mano y no tienes cambios pendientes en el formulario, la UI se recarga sola; si los tienes, muestra "config.yaml cambió por fuera" con "Recargar" y "Ver diferencias" y bloquea el guardado. Si aun así se guarda con una versión vieja, el servidor responde 409 (cada guardado envía la versión base, un hash del contenido) y la UI enseña el diff contra la versión nueva para confirmar o recargar.
- Un `config.yaml` inválido (edición a mano) no tumba la UI: se avisa y se puede corregir o restaurar una copia.

API (todas bajo sesión): `GET /api/config`, `PUT /api/config` (`{config, base_version}`), `POST /api/config/validate|diff|yaml|restore`, `GET /api/config/backups|status|events`, `POST /api/devices/test`. Ninguna devuelve secretos ni la clave privada SSH.

**CLI** (dentro del contenedor):
```bash
docker exec savesync savesync list
docker exec savesync savesync sync ejemplo --dry-run
docker exec savesync savesync sync ejemplo
docker exec savesync savesync versions ejemplo
```
Un `flock` por juego impide ejecuciones solapadas (UI y CLI). Si un dispositivo no responde, o el `process` está abierto, no se toca nada. Log por ejecución en `data/logs/<juego>/`.

### Sincronización automática
La tarjeta "Sincronización automática" de Configuración ejecuta todos los juegos cada X horas (de 0.25 a 168, admite decimales; presets 1/6/12/24 h) en modo normal, no dry-run. Muestra la última ejecución con su resultado y la próxima. Notas:
- Si un juego ya está sincronizándose (a mano o en el ciclo anterior), se omite en ese ciclo; un error en un juego no detiene los demás ni el planificador.
- Guardar reprograma al instante (próxima = ahora + intervalo). "Ejecutar también al arrancar" lanza un ciclo nada más iniciar la aplicación.
- Los ajustes se guardan en `data/scheduler.json` (aparte de `config.yaml`) y prevalecen sobre las variables de entorno. Las fechas se guardan en UTC (ISO 8601) y la UI las muestra en tu hora local.
- API (misma sesión que el resto): `GET /api/scheduler` y `PUT /api/scheduler` con `{enabled, interval_hours, run_on_start}` (parcial; 422 si no es válido). Devuelve además `next_run`, `last_run`, `last_status` y `running`.
- Registro de ejecuciones: cada ciclo añade una entrada a `data/scheduler-history.jsonl` (una línea JSON por ciclo): id, inicio (UTC), duración, disparador (`scheduled` o `startup`), resultado global y por juego (`ok`/`error`/`aborted`/`skipped`, con mensaje corto) y mensaje de error. Retención: últimas 200 entradas y máximo 30 días (constantes `MAX_ENTRIES` y `MAX_DAYS` en `backend/app/history.py`). Escritura atómica; las líneas corruptas se ignoran y se descartan al reescribir. Los mensajes pasan por la redacción de secretos y se truncan. Cada ciclo y cada juego emiten además líneas de log `INFO`/`ERROR` (logger `savesync.scheduler`) visibles en los logs del contenedor.
- `GET /api/scheduler/history?limit=N` (misma sesión; `N` de 1 a 200, por defecto 50; fuera de rango da 422): `{"entries": [...]}`, más reciente primero. En la UI, bloque "Registro de ejecuciones" bajo la tarjeta (se refresca cada 30 s y con el botón Refrescar; clic en una fila para ver el detalle por juego). No hay endpoint para borrar el registro: se limpia solo por retención, o borrando el fichero.
- Valores iniciales opcionales (solo cuentan si aún no se ha guardado nada desde la UI): `SAVESYNC_AUTO_ENABLED` (`0`/`1`, por defecto `0`), `SAVESYNC_AUTO_INTERVAL_HOURS` (por defecto `24`) y `SAVESYNC_AUTO_RUN_ON_START` (`0`/`1`).

## Cómo decide
Descarga ambos saves a un temporal y calcula hash del contenido y mtime máximo de ambos y del hub (`data/hub/<juego>`). Gana el más reciente; con el mismo mtime y contenido distinto aborta. Las copias distintas del ganador se guardan en `data/versions/<juego>/<AAAA-MM-DD_HHMMSS>/<origen>/` (se conservan `keep_versions`) y se sobrescriben con el ganador, incluidos los ficheros sobrantes.

## Restaurar versiones
UI > Versiones > Restaurar: copia esa versión al hub con fecha actual (el hub previo se guarda como versión). Luego pulsa Sincronizar: la versión restaurada es la más reciente y se propaga a los dos dispositivos. A mano: copia la carpeta de `data/versions/...` sobre el save con el juego cerrado.

## Integración en un compose existente
Servicio `savesync` en el `compose.yml` de tu stack (`build: ./savesync`, puerto `${SAVESYNC_PORT:-8088}`). El `docker-compose.yml` de esta carpeta sigue valiendo en modo independiente.

Variables en el `.env` del stack (`SAVESYNC_USER` y `SAVESYNC_PASSWORD` son obligatorias en la práctica: sin ellas el contenedor no arranca, pero el resto del stack no se ve afectado):
```
SAVESYNC_USER=admin
SAVESYNC_PASSWORD=cambia-esto           # en claro; restringe los permisos del .env
# opcionales: SAVESYNC_PORT=8088, SAVESYNC_SESSION_HOURS=12, SAVESYNC_COOKIE_SECURE=0, SAVESYNC_TRUST_PROXY=0, PUID=1000, PGID=1000
# sync automática (opcionales): SAVESYNC_AUTO_ENABLED=0, SAVESYNC_AUTO_INTERVAL_HOURS=24, SAVESYNC_AUTO_RUN_ON_START=0
```
Si la contraseña lleva `$`, ponla entre comillas simples en el `.env`.

```bash
cd <ruta de tu stack>
docker compose up -d --build savesync
docker compose logs savesync
```

## Desarrollo y tests
```bash
cd backend && pip install -r requirements.txt pytest httpx && pytest
cd frontend && npm install && npm run build
```
