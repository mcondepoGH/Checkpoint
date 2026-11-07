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
- **Juegos**: cada juego enlaza dos dispositivos y la carpeta de guardado en cada uno.
- **Sincronizar**: Checkpoint descarga ambos guardados, compara fechas de modificación y propaga el más reciente. Antes de sobrescribir guarda la copia perdedora como versión.
- **Versiones**: se conservan las últimas N de cada juego y se pueden restaurar desde la UI.

Para que "gana el más reciente" funcione, mantén la hora sincronizada (NTP) en el servidor y en los dispositivos.

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
| `CHECKPOINT_COOKIE_SECURE` / `CHECKPOINT_TRUST_PROXY` | `0` | Pon `1` tras un proxy inverso con HTTPS |
| `TZ`, `PUID`, `PGID` | `Europe/Madrid`, `1000` | Zona horaria y usuario del contenedor |

El prefijo antiguo `SAVESYNC_*` sigue aceptándose (obsoleto). Si la contraseña lleva `$`, ponla entre comillas simples.

## Primeros pasos

1. En **Configuración**, copia la **clave pública SSH** (botón Copiar).
2. Añádela a `authorized_keys` de cada dispositivo. El botón **?** junto a la clave muestra los comandos para Linux y Windows, incluida la activación del servidor SSH.
3. Añade los **dispositivos** (nombre, host, puerto, usuario, sistema) y pulsa **Probar conexión**. La primera vez se guarda la huella del host.
4. Añade los **juegos**: elige dos dispositivos y la carpeta de guardado en cada uno (ruta absoluta, por ejemplo `/home/usuario/.local/share/Juego/Saves` o `C:\Users\Usuario\AppData\Local\Juego\Saves`).
5. Ve a **Sincronizar**. Prueba primero con **Dry-run** y después sin él.

## Sincronización automática

En **Configuración > Sincronización automática** activa la opción y elige cada cuántas horas se ejecuta (de 0.25 a 168). Cada ciclo sincroniza todos los juegos; si uno falla, los demás continúan. Debajo se muestra el **Registro de ejecuciones** con resultado por juego y detalle al hacer clic. Los ajustes guardados en la UI prevalecen sobre las variables de entorno.

## Configuración

| Carpeta | Contenido |
|---|---|
| `config/` | `config.yaml` (dispositivos y juegos) |
| `keys/` | clave SSH generada y `known_hosts` |
| `data/` | copias, versiones, logs y registro de la sync automática |

Se crean solas al arrancar. `config.yaml` se edita desde la UI (valida, muestra diff y guarda copias) o a mano; ver [`config.example.yaml`](config.example.yaml). Ejemplo mínimo:

```yaml
devices:
  pc:     {host: 192.0.2.10, user: usuario, os: windows, port: 22}
  laptop: {host: 192.0.2.11, user: usuario, os: linux, port: 22}
games:
  ejemplo:
    devices: [pc, laptop]
    paths:
      pc: "C:/Users/usuario/AppData/Local/Ejemplo/Saves"
      laptop: "/home/usuario/.local/share/Ejemplo/Saves"
    keep_versions: 5
```

## Seguridad

- Cambia el usuario y la contraseña del `.env` y restringe sus permisos (`chmod 600 .env`).
- No expongas el servicio a Internet sin un proxy inverso con TLS (activa `CHECKPOINT_COOKIE_SECURE=1` y `CHECKPOINT_TRUST_PROXY=1`).
- La clave privada vive en `keys/` y no debe compartirse ni subirse a ningún repositorio.
- Si cambia la huella de un dispositivo, la conexión falla; revisa la entrada de `keys/known_hosts` antes de borrarla.
- Usa una cuenta limitada en los dispositivos siempre que sea posible.

## Desarrollo

```bash
cd backend && python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt pytest httpx && pytest
cd ../frontend && npm install && npm run dev     # desarrollo
npm run build                                    # producción
```

## Licencia

MIT. Ver [`LICENSE`](LICENSE).
