# Cambios

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
