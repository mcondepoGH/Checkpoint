# Estructura del código

Mapa de carpetas del backend y del frontend, qué hace cada una, qué puede importar de qué y cómo añadir un módulo nuevo. Las reglas de dependencia las comprueban dos tests (`backend/tests/test_architecture.py` y `frontend/test/architecture.test.mjs`): si rompes una, el test falla y dice qué import sobra.

## Backend (`backend/app/`)

```
backend/app/
├── main.py              fábrica de la app (create_app / app_factory): monta middleware, routers y docs
├── cli.py               CLI (`python -m app.cli`): list, sync...
├── api/                 capa web (FastAPI)
│   ├── auth.py          sesiones, login, API key en cabecera
│   ├── deps.py          dependencias de FastAPI (require, usuario actual; keys Bearer: `hook_user` = usuario, `hook_device` = dispositivo http, `hook_any` = las dos, todas devuelven `Principal(user, device|None)`)
│   ├── middleware.py    log de depuración de cada petición
│   ├── docs/            OpenAPI y Swagger de la API key (install, models, examples)
│   └── routers/         un router por área: hook, games, session, profile, devices (API key por dispositivo http, con sesión), config, sync,
│                        versions, scheduler, updates, pairing (vinculación por solicitud y código: la parte pública es el ÚNICO endpoint sin key ni sesión) y spa (catch-all, siempre el último)
├── services/            lógica de negocio sin FastAPI
│   ├── context.py       AppContext: objetos compartidos de la app (auth, scheduler, watcher...)
│   └── runs, pairing, hooks (aviso `opened`, cierre y, para dispositivos http, `fingerprint`, `closed`, `manifest`, subida `files` y `commit`, purga y tope del staging), hookfiles (staging reanudable, `part_lock` por fichero y `stage_lock` del dispositivo durante el commit, tope y lectura por rangos de las subidas/bajadas http), devices, games, status, versions
├── sync/                motor de sincronización
│   ├── engine.py        run_sync, restore_version, resolve_game; `write_winner_to_hub` y `finish_hub_update` (aplicar un ganador al hub, compartido con el commit HTTP)
│   ├── safepath.py      `resolve_inside`: ruta relativa segura dentro de una raíz (sin `..`, ni enlaces simbólicos); obligatoria al leer o escribir con rutas de un dispositivo http
│   ├── decide.py        decisión pura de quién manda y resolución de conflictos
│   ├── fingerprint.py   huella de un directorio o de un manifiesto (`fingerprint_from_manifest`)
│   ├── versions.py      versiones guardadas y reemplazo casi atómico de directorios
│   ├── baseline.py      huella de cada participante tras la última sync completa
│   ├── errors.py        SyncAbort
│   ├── locking.py       lock por juego
│   ├── scheduler.py     sincronización automática + tareas de mantenimiento periódicas (`maintenance`: purga del staging)
│   ├── watcher.py       vigilancia del cierre del juego
│   └── transport/       acceso a dispositivos: base (interfaz y utilidades), posix (ssh + rsync),
│                        windows (ssh + tar) y local («Este equipo»); __init__ reexporta lo público
├── config/              modelo (models.py) y almacén (store.py) de config.yaml; `Game.steam_appid` (opcional; entero > 0, único entre juegos) lo expone `GET /api/games`
├── users/               datos por usuario: apikey (key de usuario `ck_` y de dispositivo http `ckd_`, mismo almacén cifrado), avatar, history
└── core/                utilidades base: settings, errors, hosts, bootstrap, redact, runtime, updates
```

### Reglas de dependencia (backend)

Las capas se apilan: `api` → `services` → `sync` / `config` / `users` → `core`. Nunca se importa hacia arriba.

| Capa | Puede importar de | No puede importar de |
|---|---|---|
| `core` | solo de sí misma | ninguna otra capa |
| `sync`, `config`, `users` | `core` y entre ellas | `api`, `services` |
| `services` | `sync`, `config`, `users`, `core` | `api` |
| `api` | todas | (ninguna) |

Excepción documentada: `sync/scheduler` importa `users/history` (registra en el historial de cada usuario el resultado de sus ejecuciones). Está en la lista `ALLOWED` del test; si deja de hacer falta, el test pide borrarla.

Para repartir los imports públicos de un paquete sin romper a quien ya importa de él, el `__init__.py` reexporta (por ejemplo `sync/transport/__init__.py`, o `sync/engine.py` con las funciones que viven en `decide`, `fingerprint`, `versions` y `baseline`). Los tests que sustituyen una función con `monkeypatch` deben apuntar al módulo donde se *usa* (p. ej. `app.sync.engine.get_transport`, `app.sync.transport.base._run`).

### Añadir un módulo al backend

1. Decide la capa por la regla de arriba: ¿habla HTTP? `api`. ¿Orquesta casos de uso sin conocer FastAPI? `services`. ¿Es del motor de sincronización? `sync`. ¿Es del fichero de configuración? `config`. ¿Es dato de un usuario? `users`. ¿Lo usan todas las capas y no depende de ninguna? `core`.
2. Un endpoint nuevo: crea `api/routers/<area>.py` con un `APIRouter`, regístralo en la lista de `main.py` (antes del router `spa`) y pon la lógica en `services/`. Por defecto queda fuera del esquema público de OpenAPI; solo las rutas con el tag `TAG` de `api/docs/install.py` salen en Swagger.
   Autenticación de `/api/hook/*` y `/api/games`: no hay dependencia global; cada endpoint declara la suya según la key que acepta (`deps.hook_user` usuario: `watches`, `opened`; `deps.hook_device` dispositivo: `fingerprint`, `manifest`, `files`, `commit`, `closed`; `deps.hook_any`: `ping` y `GET /api/games`, que con key de dispositivo filtra por sus juegos). La clase equivocada es el mismo 401 que una inválida y cuenta para `hook_fail`. Un endpoint nuevo debe elegir una; `docs/install.KEY_KINDS` la declara para el Swagger y `test_apidocs`/`test_device_apikey` fallan si falta o no coincide. Con key de dispositivo, `HookService.scope` fija dispositivo y juego (403 `err.apikey.device_mismatch` si `?device=` no es el de la key; 404 `err.main.game_unknown` si el juego no lo incluye). Las keys de dispositivo viven en `users/apikey` (`devices/<id>.enc`, ligadas al id de dispositivo) y se podan con `services/devices.prune_device_keys` al guardar/restaurar la config y al arrancar.
   Vinculación de dispositivos (`routers/pairing.py` + `services/pairing.py`, docs en `api/docs/pairing.py`): dos routers en `/api/pairing`. `POST /requests` y `GET /requests/{id}` son PÚBLICOS (sin key ni sesión; el único caso: `KEY_KINDS` = `public` y `pairing_secret`, secreto en la cabecera `X-Pairing-Secret`, nunca en la URL) y limitados por IP (`Auth.pair_fails`, `pair_wait/pair_fail/pair_ok`, más los topes y la caducidad de `PairingService`, con el reloj de `Auth`); `GET /pending` y `POST /pending/{id}/accept|reject` exigen sesión (`session`). Las solicitudes viven solo en memoria (`ctx.pairing`, `purge` en `scheduler.maintenance`). Aceptar da de alta el dispositivo por `ConfigStore.save` (mismas validaciones que `PUT /api/config`) y la key `ckd_` se genera al recogerla, no al aceptar. Una ruta pública nueva sin credencial debe justificarse y pasar por los mismos límites.
   Los dispositivos `http: true` (`Device.http`) no tienen transporte: `get_transport` lanza `err.transport.push_only` y quedan fuera de `_do_sync`, del scheduler, de `opened` y de la vigilancia (`config.models.classic_devices` lista los que el hub sí contacta). Los atiende la API de `routers/hook.py` con `services/hooks.py` (`fingerprint`: no toca ficheros ni historial y solo escribe la línea base con `none`/`same`, bajo el lock del juego; `closed`: solo registra el cierre en el historial, sin sync; subida: `PUT files` escribe solo en `data/staging/<juego>/<dispositivo>/` SIN el lock del juego (solo guarda `game_busy` y un lock por fichero, `hookfiles.part_lock`) y únicamente `commit` toca `data/hub/<juego>`, con el lock del juego, comprobando `expect`; el staging se purga por antigüedad (`CHECKPOINT_HOOK_STAGING_TTL_H`, al arrancar y cada hora vía `Scheduler.maintenance`, sin tocar juegos con lock o run) y tiene tope por juego (`CHECKPOINT_HOOK_STAGING_MAX_MB`, `err.hook.staging_full`); `fingerprint?manifest=1` devuelve `hub_manifest` de la misma lectura (`fingerprint_with_manifest`); bajada: `manifest`, `GET files` con `Range`; la línea base del dispositivo la fija después un `fingerprint` igual). `/api/devices/test` con un `http` responde `err.transport.push_only` sin intentar SSH. El manifiesto solo rechaza rutas que escapan (`..`, absolutas, NUL, vacías, repetidas): no usa `PATH_CHARS_RE`, que queda para rutas de dispositivo. Como esas reglas son relajadas, toda ruta que se lea o escriba en disco (staging o hub) debe pasar por `sync/safepath.resolve_inside`.
3. Un transporte nuevo: módulo en `sync/transport/` que implemente `Transport` (de `base.py`) y exporta en `__init__.py`; engánchalo en `get_transport`.
4. Textos para el usuario: el backend no traduce; devuelve códigos `err.<módulo>.<causa>` con `params` y la traducción va en `frontend/src/locales/*.json`.
5. Ejecuta `pytest`: `test_architecture.py` confirma que no has roto las reglas.

## Frontend (`frontend/src/`)

```
frontend/src/
├── main.jsx, App.jsx        arranque y raíz (pestañas, sesión, cabecera)
├── pages/                   Login, Sync, Versions, Settings (una por pestaña; Settings es el contenedor de las subpestañas)
│   └── settings/            paneles de las subpestañas de Configuración: General, Library (Biblioteca) y Launchers
├── components/
│   ├── ui/                  componentes genéricos (Button, Badge, Alert, Pill, Select, Checkbox, Switch,
│   │                        Tabs (con variante subnav y paneles conservados), CopyBox, WatchBar, WatchStatus, Input, Icon, Modal, Field,
│   │                        EmptyState, AppIcon) con su parcial SCSS al lado (_button.scss...)
│   ├── profile/             Avatar, ProfileMenu, ApiKeySection, LanguageSelect, photo.js, _profile.scss
│   ├── updates/             UpdateBadge, UpdateDialog, UpdateCheck
│   ├── watch/               WatchSummary, watch.js
│   ├── config/              DeviceCard, GameCard, IdNote, SaveDialog, YamlDialog, BackupsDialog,
│   │                        DiffView, draft.js, useConfigDraft.js, _config.scss
│   ├── autosync/            AutoSync, AutoSyncLog, runLog.js, _autosync.scss
│   ├── launchers/           LauncherBlock (una fila por juego), launchers.js
│   ├── keyhelp/             PublicKey, keyhelpSteps.js
│   └── sync/                ConflictDialog
├── hooks/                   useI18n, useWatches, useTheme
├── lib/                     lógica sin React: api.js (cliente y ApiError), api/<recurso>.js, i18n, errors,
│                            format, clipboard, tabs, names, pwa, updates, apikey
├── locales/                 es.json, en.json e index.js
├── assets/                  imágenes
└── styles/                  _variables, _themes, _base, _layout, _components y main.scss
```

`styles/main.scss` solo ordena los `@use`; los parciales de cada componente viven junto a él (`components/ui/`, `components/config/`, `components/autosync/`, `components/profile/`). El orden de los `@use` en `main.scss` importa (cascada): no lo reordenes sin comprobar el CSS resultante. `_components.scss` queda en `styles/`: mezcla reglas globales de varias pantallas (tarjetas, rejilla, modal, conflictos).

Los imports entre carpetas usan el alias `#src/` (`package.json` → `imports`: `#src/lib/api.js`); dentro de una misma carpeta, rutas relativas (`./Button.jsx`). Se usa `#src/` y no `#/` porque Node no admite subpaths que empiecen por `#/`. Funciona igual en Vite, en esbuild (tests) y en Node.

### Reglas de dependencia (frontend)

| Carpeta | Puede importar de | No puede importar de |
|---|---|---|
| `lib` | solo de `lib` (y recursos) | React, `hooks`, `components`, `pages` |
| `hooks` | `lib`, `hooks` | `components`, `pages` |
| `components/ui` | `lib`, `hooks`, `ui` | zonas, `pages` |
| `components/<zona>` | `lib`, `hooks`, `ui` y su propia zona | otra zona, `pages` |
| `pages`, `App.jsx` | todo | (ninguna) |

`assets/`, `locales/` y `styles/` son recursos: los puede importar cualquiera. Si dos zonas comparten algo, súbelo a `ui` (si es de interfaz) o a `lib` (si es lógica): por eso `updates.js` y `apikey.js` viven en `lib/` (los usan varias zonas). Algunos módulos de `lib` usan el navegador (`clipboard`, `pwa`, `launchers`), pero ninguno importa React.

Todas las llamadas a la API pasan por `lib/api/<recurso>.js` (`session`, `config`, `sync`, `versions`, `updates`, `profile`); los componentes no llaman a `api()` directamente. Dos componentes (`ApiKeySection`, `LauncherBlock`) reciben el cliente por prop `api` para poder sustituirlo en los tests.

`components/ui/index.js` reexporta los componentes de uso común; `Icon`, `Modal`, `Field`, `EmptyState` y `AppIcon` se importan directamente desde su fichero.

### Añadir un módulo al frontend

1. Componente genérico y reutilizable (varios usos, sin lógica de negocio): `components/ui/<Nombre>.jsx`, su parcial `_<nombre>.scss` al lado, y la línea en `components/ui/index.js` y en `components/ui/_index.scss`. Con tres o más usos de un mismo patrón, conviértelo en componente.
2. Componente propio de una funcionalidad: en la zona que corresponda (`components/<zona>/`), con sus ayudas puras (`.js`) al lado. Zona nueva: carpeta nueva con su parcial SCSS y su `@use` en `styles/main.scss` en el sitio correcto de la cascada.
3. Una llamada nueva a la API: función en `lib/api/<recurso>.js`; el componente importa la función, no `api()`.
4. Lógica compartida sin React: `lib/`. Estado compartido con React: `hooks/`.
5. Textos: claves en `locales/es.json` y `en.json` con las mismas claves (`locales.test.mjs` lo comprueba). Tamaños de texto con los tokens `$fs-*` de `styles/_variables.scss`.
6. Tests: en `frontend/test/` en el mismo sitio que el fichero (`test/components/<zona>/...`), con `test/helpers/bundle.mjs` para renderizar componentes y `test/helpers/locales.mjs` para los catálogos. Ejecuta `npm test`: `architecture.test.mjs` comprueba las reglas de dependencia.
