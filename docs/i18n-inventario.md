# Inventario de literales en español (i18n)

## Estado de la migración (fase 3 completada)

Las listas de abajo son el inventario original de la fase 1 (histórico, no se actualiza línea a línea). Estado actual:

| Área | Estado |
|---|---|
| Frontend (`App`, `Login`, `Sync`, `Versions`, `Settings` y todos los componentes) | **Migrado** a `t()` con claves jerárquicas (`frontend/src/locales/es.json` y `en.json`, mismas claves) |
| `format.js` (`RESULT_TEXT`, `ON_CONFLICT_OPTIONS`), `updates.js` (`CHANNEL_*`, `updateSummary`), `draft.js` (`NAME_HINT`, `LOCAL_*`, `localErrors`) | **Migrado**: guardan claves o `{code, params}` y se traducen al pintar; ids y valores (`skip`, `newest`, `stable`, `beta`) estables |
| Backend: `config.py`, `configstore.py`, `main.py`, `auth.py`, `sync.py`, `transport.py`, `bootstrap.py`, `scheduler.py`, `history.py` | **Migrado** a `code` + `params` (`err.<módulo>.<causa>`); el backend no traduce |
| Fechas, tamaños, duraciones y plurales | **Migrado**: `Intl` según el idioma activo; `files` con `Intl.PluralRules` |
| Idioma por defecto | **Hecho**: `CHECKPOINT_LANG` + `GET /api/public` |
| Backend: `cli.py` | **Fuera a propósito**: la CLI sigue en español |
| Backend: logs internos (`log.*`), `redact.py`, avisos de arranque | **Fuera a propósito** |
| `sync.py`: líneas de log por ejecución `L(...)` (registro en vivo y fichero de log) | **Fuera a propósito**: log técnico en español |
| Datos: ids de juego/dispositivo, nombres puestos por el usuario, rutas, valores `skip`/`newest`/`hub`, comandos de la guía SSH, nombres propios (Windows, Linux, Debian / Ubuntu, Arch Linux, Checkpoint, YAML, GitHub) | **No se traducen** |
| `status/*.json` e historial guardados antes del cambio | Se leen con su `message` antiguo (en español) como respaldo |

Comprobaciones automáticas (`frontend/test/locales.test.mjs`, `render-locales.test.mjs`): paridad de claves y `{params}` entre idiomas, existencia de todos los códigos `err.*` que emite el backend, JSX sin literales y pantallas renderizadas en inglés sin palabras en español.

**Total: 517 literales** (barrido automático + revisión de estructura).

## Método y límites

- Frontend: cadenas JS y texto JSX con español en `frontend/src/**` (sin comentarios ni tests). Backend: constantes `str` y f-strings de `backend/app/*.py` vía `ast`, sin docstrings.
- Es una cota de trabajo, no una lista cerrada: hay falsos positivos (mensajes solo de log o de depuración, claves técnicas) y literales compuestos en varias partes que cuentan por trozo. La fase 3 revisa cada fichero al migrarlo.
- No incluye CSS ni SVG. `{x}` en backend marca un valor interpolado en una f-string.
- Los literales de librerías externas (stderr de ssh/rsync, excepciones de Python) no entran: no se traducen.

## Agrupación por pantalla/módulo

| Pantalla / módulo | Ficheros |
|---|---|
| Cabecera y shell | `App.jsx`, `Icon.jsx`, `Modal.jsx`, `UpdateBadge.jsx`, `UpdateCheck.jsx`, `UpdateDialog.jsx`, `updates.js` |
| Login | `pages/Login.jsx`, `api.js` |
| Sincronizar | `pages/Sync.jsx`, `GameCard.jsx`, `ConflictDialog.jsx`, `DiffView.jsx`, `SaveDialog.jsx` |
| Versiones | `pages/Versions.jsx` |
| Configuración | `pages/Settings.jsx`, `DeviceCard.jsx`, `IdNote.jsx`, `YamlDialog.jsx`, `BackupsDialog.jsx`, `draft.js` |
| Guía de clave SSH | `PublicKey.jsx` |
| Registro automático | `AutoSync.jsx`, `AutoSyncLog.jsx` |
| Estados vacíos | `EmptyState.jsx` (contenedor sin texto propio; los textos viven en cada pantalla) |
| Formato compartido | `format.js` (`RESULT_TEXT`, `ON_CONFLICT_OPTIONS`) |
| Backend: validación | `config.py`, `configstore.py`, `settings.py` |
| Backend: API | `main.py`, `auth.py` |
| Backend: sync/transporte | `sync.py`, `transport.py`, `bootstrap.py`, `locking.py`, `runtime.py` |
| Backend: scheduler/historial | `scheduler.py`, `history.py` |
| Backend: CLI | `cli.py` |
| Backend: actualizaciones | `updates.py` |
| Backend: otros | `redact.py` |

## Frontend

### `frontend/src/App.jsx` (7)

- L15: ['sync', 'Sincronizar', 'Sync'],
- L16: ['versions', 'Versiones', 'Versiones'],
- L17: ['settings', 'Configuración', 'Ajustes'],
- L94: Cargando…
- L102: Checkpoint
- L112: Cambiar tema (actual: ${theme})
- L116: Salir

### `frontend/src/api.js` (2)

- L12: method,
- L13: credentials: 'same-origin',

### `frontend/src/components/AutoSync.jsx` (11)

- L9: skip: 'Omitir: el guardado no se efectúa y el juego queda marcado como «Conflicto» para resolverlo a mano. Es la opción segura.',
- L10: newest: 'Gana el más reciente: se aplica el save con fecha más nueva y el otro se guarda en versiones. Si las fechas difieren menos de 2 s, se omite.',
- L50: Introduce un número entre ${min} y ${max} horas.
- L69: Sincronización automática
- L76: Sincroniza todos los juegos cada cierto tiempo. Si ya hay una sincronización en curso, ese ciclo se omite.
- L85: Cada X horas
- L85: Entre ${min} y ${max} (admite decimales, p. ej. 0.5).
- L91: Intervalos rápidos
- L100: Ejecutar también al arrancar la aplicación
- L103: En caso de conflicto
- L112: Guardar

### `frontend/src/components/AutoSyncLog.jsx` (9)

- L10: ${s.toFixed(s < 10 ? 1 : 0)} s
- L12: ${m} min ${Math.round(s % 60)} s
- L39: Registro de ejecuciones
- L40: Refrescar registro
- L41: Actualizando…
- L46: Sin ejecuciones
- L50: Ejecuciones automáticas, de más reciente a más antigua
- L61: msg ${e.result === 'error' ? 'is-error' : ''}
- L62: Sin detalle por juego.

### `frontend/src/components/BackupsDialog.jsx` (12)

- L8: ${Math.max(1, Math.round(n / 1024))} KB
- L30: config.yaml cambió por fuera mientras tanto: cierra, recarga y vuelve a intentarlo.
- L35: Restaurar versión anterior
- L39: Cargando…
- L41: Sin copias
- L48: Ver cambios
- L56: Al restaurar
- L56: el config.yaml actual
- L58: Tienes cambios sin guardar en el borrador: se descartarán.
- L61: Volver
- L62: Restaurando…
- L66: Cerrar

### `frontend/src/components/ConflictDialog.jsx` (17)

- L11: ${v.toFixed(v < 10 ? 1 : 0)} ${u[i]}
- L20: 'both-changed': 'Los dos lados han cambiado desde la última sincronización y su contenido es distinto.',
- L21: 'no-baseline': 'Es la primera comparación con estos datos y los contenidos son distintos.',
- L22: inconsistent: 'Los contenidos difieren y no hay cambios registrados.',
- L23: indeterminate: 'Las fechas difieren menos de 2 segundos: no se puede saber cuál es más reciente. Elige a mano.',
- L24: stale: 'Los datos han cambiado desde que se mostró el aviso anterior. Revisa y vuelve a elegir.',
- L32: Hub (copia en Checkpoint)
- L35: device:${sid(s)}
- L39: Conflicto en ${game}
- L42: Versiones en conflicto
- L54: ¿Qué save debe ganar?
- L56: conflict-opt${pick === value(s) ? ' on' : ''}
- L66: Cancelar
- L69: Gana el más reciente
- L70: Elegir dispositivo
- L75: Atrás
- L76: Aplicar

### `frontend/src/components/DeviceCard.jsx` (10)

- L10: Dispositivo nuevo
- L15: p. ej. Mi PC (salón)
- L32: Sistema operativo
- L42: Host / IP
- L53: Sistema operativo
- L69: Comprobando…
- L69: Probando…
- L69: Comprobar carpeta
- L69: Probar conexión
- L72: Eliminar dispositivo ${title}

### `frontend/src/components/DiffView.jsx` (5)

- L11: ${field === 'paths' ? dev(k) : k}: ${x}
- L19: Sin cambios
- L30: + Añadir
- L33: ~ Cambiar
- L39: − Eliminar

### `frontend/src/components/GameCard.jsx` (13)

- L9: Juego nuevo
- L14: — elige —
- L23: p. ej. Mi Juego: Edición
- L27: Dispositivo 1
- L28: Dispositivo 2
- L31: Ruta del save en ${nameA}
- L36: Ruta del save en ${nameB}
- L41: Proceso (opcional)
- L44: Máx. de versiones (este juego)
- L44: Vacío = usar el global (${globalMax}). ${VERSIONS_HINT}
- L48: En conflicto (sync automática)
- L51: Usar el ajuste global
- L58: Eliminar juego ${title}

### `frontend/src/components/Icon.jsx` (7)

- L5: logout: 'M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9',
- L6: theme: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 3v18',
- L7: history: 'M3 12a9 9 0 1 0 3-6.7M3 4v5h5M12 7v5l3 2',
- L8: code: 'M16 18l6-6-6-6M8 6l-6 6 6 6',
- L9: undo: 'M1 4v6h6M3.5 15a9 9 0 1 0 2.1-9.4L1 10',
- L10: download: 'M12 3v12M7 10l5 5 5-5M5 21h14',
- L11: alert: 'M12 9v4M12 17h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z',

### `frontend/src/components/IdNote.jsx` (4)

- L9: El ID interno no cambia: tus saves y versiones siguen asociados.
- L12: Identificador interno: no cambia al renombrar
- L13:  (se fija al guardar)
- L13: ID interno:

### `frontend/src/components/Modal.jsx` (1)

- L15: button:not(:disabled), [href], input, select, textarea, [tabindex]:not([tabindex="-1"])

### `frontend/src/components/PublicKey.jsx` (47)

- L34: mkdir -p ~/.ssh && chmod 700 ~/.ssh\necho "${k}" >> ~/.ssh/authorized_keys\nchmod 600 ~/.ssh/authorized_keys
- L40: Activar el servidor OpenSSH
- L40: En PowerShell abierto como administrador.
- L40: Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0\nStart-Service sshd; Set-Service sshd -StartupType Automatic
- L41: Pegar la clave (usuario normal)
- L41: En PowerShell, con el usuario con el que se conectará Checkpoint.
- L41: New-Item -ItemType Directory -Force "$env:USERPROFILE\\.ssh" | Out-Null\nAdd-Content -Path "$env:USERPROFILE\\.ssh\\authorized_keys" -Value '${k}'
- L42: Pegar la clave (usuario administrador)
- L42: Si ese usuario es administrador, la clave va en otro fichero. PowerShell como administrador.
- L42: Add-Content -Path "C:\\ProgramData\\ssh\\administrators_authorized_keys" -Value '${k}'\nicacls "C:\\ProgramData\\ssh\\administrators_authorized_keys" /inheritance:r /grant "Administrators:F" /grant "SYSTEM:F"
- L45: Arch Linux
- L47: ['Instalar y activar el servidor SSH', 'En una terminal. El servicio se llama sshd.', 'sudo pacman -S --needed openssh\nsudo systemctl enable --now sshd'],
- L48: Abrir el puerto 22 (solo si hay firewall)
- L48: Arch no trae firewall activo por defecto. Usa el que tengas.
- L48: # ufw\nsudo ufw allow 22/tcp\n# firewalld\nsudo firewall-cmd --permanent --add-service=ssh && sudo firewall-cmd --reload
- L49: Pegar la clave en authorized_keys
- L49: Como el usuario con el que se conectará Checkpoint (sin sudo).
- L53: ['Instalar y activar el servidor SSH', 'En una terminal. El servicio se llama ssh.', 'sudo apt update && sudo apt install -y openssh-server\nsudo systemctl enable --now ssh'],
- L54: Abrir el puerto 22 (solo si ufw está activo)
- L54: Comprueba antes con sudo ufw status.
- L54: sudo ufw allow 22/tcp
- L55: Pegar la clave en authorized_keys
- L55: Como el usuario con el que se conectará Checkpoint (sin sudo).
- L97: Debian / Ubuntu
- L97: Arch Linux
- L109: Info: pasos para dar de alta la clave
- L113: Checkpoint usa su propia clave SSH para entrar, sin contraseña, a cada dispositivo y copiar sus partidas. Hay que dar de alta la parte
- L113: en cada dispositivo.
- L115: Copia la clave
- L116: Pulsa
- L116: Copiar
- L116: bajo la caja de la clave pública. Es la clave de Checkpoint: no hay que generar ninguna en tu PC.
- L118: Pégala en el dispositivo remoto
- L119: Sistema del dispositivo remoto
- L120: Distribución Linux
- L122: Aún no hay clave visible: sustituye
- L122: por la clave copiada.
- L132: la clave ocupa una sola línea, con este aspecto:
- L137: Comprueba la conexión
- L138: En la tarjeta del dispositivo, pulsa
- L138: Probar conexión
- L138: conexión OK
- L166: Clave pública SSH
- L168: Cópiala y añádela a
- L168: de cada dispositivo. Pulsa
- L168: para ver los pasos.
- L173: Clave pública SSH

### `frontend/src/components/SaveDialog.jsx` (10)

- L30: La configuración ya no es válida: revisa los campos marcados.
- L36: config.yaml cambió por fuera
- L36: Revisar cambios
- L39: El fichero se modificó desde que lo cargaste. Abajo se ven las diferencias de tu borrador contra la versión actual:
- L40: lo que no aparezca en tu borrador se eliminará. Puedes confirmar igualmente o recargar y descartar tus cambios.
- L46: Recargar y descartar mis cambios
- L47: Cancelar
- L49: Guardando…
- L49: Guardar sobre la versión nueva
- L49: Confirmar y guardar

### `frontend/src/components/UpdateBadge.jsx` (2)

- L9: Nueva versión${pre ? ' preliminar' : ''} disponible: ${info.ultima}
- L12: Nueva versión disponible

### `frontend/src/components/UpdateCheck.jsx` (4)

- L23: Acabas de comprobarlo; espera un minuto para volver a hacerlo.
- L28: Comprobar actualizaciones
- L36: Canal
- L45: Comprobar ahora

### `frontend/src/components/UpdateDialog.jsx` (9)

- L10: Nueva versión disponible
- L12: Instalada
- L13: Nueva
- L15: Es una versión preliminar del canal de pruebas: puede fallar.
- L16: Novedades
- L16: Esta versión no incluye notas.
- L17: Ver la versión en GitHub
- L18: Checkpoint no se actualiza solo: descarga la nueva versión, recompila la web y reinicia Checkpoint.
- L19: Cerrar

### `frontend/src/components/YamlDialog.jsx` (5)

- L12: El borrador tiene errores: corrígelos para ver el YAML.
- L15: YAML (solo lectura)
- L17: Generando…
- L20: YAML resultante
- L24: Cerrar

### `frontend/src/draft.js` (17)

- L11: i${++seq}
- L27: ${idPrefix(item.name, kind)}-${item.salt}
- L35: Este equipo
- L36: “Este equipo” solo está disponible cuando Checkpoint se ejecuta sin Docker
- L37: Solo puede haber un dispositivo “Este equipo”
- L38: Es el equipo donde se ejecuta Checkpoint: se accede directamente a sus carpetas, sin SSH.
- L55: 0 = sin límite; al superarlo se borran las más antiguas
- L65: pathA: g.paths?.[g.devices[0]] ?? '', pathB: g.paths?.[g.devices[1]] ?? '',
- L67: onConflict: g.on_conflict || '',
- L86: Hasta ${NAME_MAX} caracteres. Se admiten espacios, símbolos, acentos y emojis; no / ni \\
- L93: Debe ser un número entero entre 0 y ${MAX_VERSIONS_LIMIT} (0 = sin límite)
- L112: El nombre es obligatorio
- L113: Nombre demasiado largo (máx. ${NAME_MAX} caracteres)
- L114: Nombre inválido: no se admiten / \\ ni caracteres de control
- L115: Nombre inválido: no puede ser solo puntos
- L116: Nombre repetido (sin distinguir mayúsculas ni espacios extra)
- L155: (sin nombre)

### `frontend/src/format.js` (2)

- L19: Omitir el guardado (seguro)
- L19: Gana el más reciente

### `frontend/src/pages/Login.jsx` (4)

- L22: Checkpoint
- L23: Usuario
- L26: Contraseña
- L30: Entrar

### `frontend/src/pages/Settings.jsx` (37)

- L4: MAX_VERSIONS_LIMIT, VERSIONS_HINT, blankDevice, blankGame, canOfferLocal, deviceId, baseKeyOf, errorsFor, fromConfig, gamesUsing, hasChanges, idOf, localErrors, nameOf, pathsOf, removeDevice, renamed, toConfig,
- L78: El dispositivo ${dev.name || '(sin nombre)'} lo usan: ${used.join(', ')}.\n
- L79: Esos juegos perderán este dispositivo y deberás elegir otro. ¿Eliminarlo?
- L88: method: 'POST',
- L90: body: dev.local
- L122: devices.${idOf(d, 'dispositivo')}
- L123: games.${idOf(g, 'juego')}
- L133: input, select
- L138: Configuración
- L145: config.yaml cambió por fuera.
- L145: Guardar está desactivado para no pisar esos cambios.
- L148: Ver diferencias
- L164: Versiones guardadas
- L165: Máx. de versiones por juego
- L172: Dispositivos
- L174: Añadir dispositivo
- L186: Sin dispositivos
- L188: Añadir dispositivo
- L192: Juegos
- L195: Añadir juego
- L209: Acciones de configuración
- L212: ${errorCount || 1} errores por corregir: ir al primero
- L213: Hay errores por corregir
- L216: ab-chip${dirty ? ' dirty' : ''}
- L217: Validando…
- L217: Sin cambios
- L217: Cambios sin guardar
- L217: Sin guardar
- L221: Restaurar versión anterior
- L222: Restaurar versión anterior
- L224: Ver YAML
- L225: Ver YAML
- L227: Descartar cambios
- L228: Descartar
- L230: Guardar…
- L235: Guardado y aplicado al instante.
- L241: Versión restaurada y aplicada.

### `frontend/src/pages/Sync.jsx` (20)

- L8: Simulación (dry-run)
- L21: Sin ejecuciones
- L31: Última sync
- L36: Conflicto
- L37: Parcial
- L38: Offline
- L39: Ganador
- L44: Detalle
- L105: Sincronizar
- L108: Sin juegos configurados
- L110: Ir a Configuración
- L118: ID interno: ${g}
- L120: meter ${running ? 'running' : (s?.result || '')}
- L120: Estado de ${gameName(g)}
- L125: dos versiones distintas, no se ha guardado nada.
- L126: Resolver
- L129: En curso…
- L140: (terminado)
- L140: (en vivo)
- L141: Esperando…

### `frontend/src/pages/Versions.jsx` (10)

- L18: ¿Restaurar ${version}/${sourceName} en el hub? La copia actual del hub se guarda como versión.
- L28: Versiones
- L35: ${limit.count} (sin límite)
- L35: ${limit.count} de máx. ${limit.max}
- L35:  (ajuste de este juego)
- L35:  (ajuste global)
- L40: Sin juegos configurados
- L42: Ir a Configuración
- L44: Sin versiones guardadas
- L54: Restaurar

### `frontend/src/updates.js` (5)

- L20: Estable: solo versiones publicadas como definitivas. Pruebas: incluye también versiones preliminares, que pueden fallar.
- L39: Comprobación desactivada: no se hace ninguna petición a internet.
- L40: Hay una versión nueva${isPrerelease(info) ? ' preliminar' : ''}: ${info.ultima} (instalada: ${info.actual}).
- L41: Estás al día (versión ${info.actual}).
- L42: Versión instalada: ${info.actual}. Aún no hay datos de la última versión.

## Backend

### `backend/app/bootstrap.py` (13)

- L20: host key guardada (primer uso)
- L21: la host key de {host}:{port} ha CAMBIADO respecto a la guardada en known_hosts (posible suplantación o reinstalación del dispositivo). No se sobrescribe. Si el cambio es legítimo, borra a mano esa entrada de known_hosts
- L43: config.yaml no existía: creado vacío en %s
- L64: no se pudo generar la clave SSH: {}
- L66: ssh-keygen falló:
- L68: clave SSH generada en %s (primer arranque)
- L102: host inválido
- L106: puerto inválido
- L124: no se pudo leer known_hosts: {}
- L134: ssh-keyscan falló: {}
- L138: (¿SSH activo y accesible?)
- L138: no se pudo obtener la host key de {}:{} (¿SSH activo y accesible?)
- L162: HOST IDENTIFICATION HAS CHANGED|Host key verification failed

### `backend/app/cli.py` (11)

- L17: faltan CHECKPOINT_USER y CHECKPOINT_PASSWORD (variables de entorno)
- L25: ) en http://
- L25: Checkpoint ({}, {}) en http://{}:{}
- L39: resuelve un conflicto: gana el más reciente, el hub o el save de un dispositivo
- L40: arranca la web (modo nativo, sin Docker)
- L41: por defecto CHECKPOINT_HOST o 127.0.0.1
- L42: por defecto CHECKPOINT_PORT o 8088
- L53: config inválida: {}
- L57: {}: {} <-> {}
- L70: --resolve debe ser newest, hub o device:<dispositivo>
- L82: Nada se ha modificado. Resuélvelo con: checkpoint sync <juego> --resolve newest|hub|device:<dispositivo>

### `backend/app/config.py` (54)

- L16: caracteres: se admiten espacios (sin dobles ni al principio/final), símbolos, acentos y emojis; no se admiten / \ ni caracteres de control
- L16: 1 a {} caracteres: se admiten espacios (sin dobles ni al principio/final), símbolos, acentos y emojis; no se admiten / \ ni caracteres de control
- L23: ^[A-Za-z0-9_][A-Za-z0-9_. \-]{0,63}$
- L25: ^[\w .\-/()\[\]+,@~=#{}]+$
- L31: (0 = sin límite)
- L31: debe ser un número entero entre 0 y {} (0 = sin límite)
- L38: falta el campo name (obligatorio): el nombre visible del elemento
- L46: nombre inválido: debe ser texto ({})
- L48: el nombre es obligatorio
- L50: nombre inválido: sin espacios al principio ni al final ni dobles
- L52: nombre demasiado largo (máx. {} caracteres)
- L54: nombre inválido: no se admiten / ni \
- L60: nombre inválido: sin caracteres de control ni espacios especiales
- L62: nombre inválido: no puede ser solo puntos
- L77: es ambiguo: coincide con
- L77: {} es ambiguo: coincide con
- L78: ; usa el id
- L78: {} (id {})
- L84: ruta debe ser texto
- L91: ruta Windows debe ser absoluta tipo C:/Users/...
- L95: ruta debe ser absoluta (empieza por /)
- L98: ruta con caracteres no permitidos: {}
- L101: '..' no permitido en rutas
- L103: ruta demasiado general (raíz)
- L107: “Este equipo” solo está disponible cuando Checkpoint se ejecuta sin Docker
- L108: solo puede haber un dispositivo “Este equipo”
- L109: no aplica a “Este equipo” (se accede directamente al sistema de ficheros local)
- L149: host inválido
- L151: user inválido
- L160: os debe ser uno de {}
- L196: on_conflict debe ser 'skip' o 'newest'
- L205: process inválido
- L230: id interno inválido: 1 a 64 caracteres entre letras, números, _ y -
- L236: id repetido o igual (sin distinguir mayúsculas) a {}
- L248: nombre repetido (sin distinguir mayúsculas): {}
- L263: debe ser true o false
- L278: dispositivo desconocido (id inexistente): {}
- L282: debe ser distinto del dispositivo 1
- L285: paths debe ser un mapa dispositivo -> ruta
- L289: sobra: este dispositivo no es del juego
- L293: falta la ruta del save
- L340: config debe ser un mapa YAML
- L346: debe ser un número entero
- L347: debe ser un número entero
- L348: debe ser un número entero
- L349: debe ser texto
- L350: campo no permitido
- L351: debe ser un mapa
- L352: debe ser una lista
- L361: config debe ser un mapa YAML
- L370: Value error,
- L393: (los ids no pueden repetirse)
- L393: clave repetida: {} (los ids no pueden repetirse)
- L410: error de sintaxis

### `backend/app/configstore.py` (3)

- L30: config.yaml cambió desde que lo cargaste
- L63: error de sintaxis
- L220: la copia no es válida: {}

### `backend/app/main.py` (24)

- L69: sesión requerida
- L74: origen no permitido
- L93: demasiados intentos; espera {} s
- L123: config no válida
- L155: la copia no es válida: {}
- L176: falta base_version (recarga la configuración)
- L195: falta base_version (recarga la configuración)
- L216: datos del dispositivo inválidos:
- L227: paths debe ser una lista de rutas (máx. 50)
- L248: conexión OK
- L257: clave SSH aún no generada
- L263: config.yaml inválido: {}
- L286: ajustes no válidos
- L298: La comprobación de actualizaciones no se aplica en Docker (la versión la fija la imagen)
- L303: debe ser verdadero o falso
- L305: debe ser «stable» o «beta»
- L307: indica «enabled» o «channel»
- L309: ajustes no válidos
- L347: resolution debe ser 'newest', 'hub' o 'device:<id o nombre>'
- L351: expect debe ser un mapa origen -> hash
- L353: ya hay una ejecución en curso de este juego
- L375: ejecución desconocida
- L454: frontend no construido
- L461: Value error,

### `backend/app/redact.py` (1)

- L7: -----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----

### `backend/app/scheduler.py` (11)

- L26: %(asctime)s %(levelname)s %(name)s: %(message)s
- L55: debe ser verdadero o falso
- L59: debe ser un número
- L61: debe estar entre {} y {} horas
- L68: debe ser 'skip' (omitir) o 'newest' (gana el más reciente)
- L156: : omitido (ya en curso)
- L156: {}: omitido (ya en curso)
- L157: ya en curso
- L158: auto-sync juego=%s resultado=skipped (ya en curso)
- L167: omitido por conflicto:
- L207: auto-sync no se pudo guardar el registro: %s

### `backend/app/settings.py` (2)

- L66: debe ser un número (valor:
- L66: CHECKPOINT_{} debe ser un número (valor: {})

### `backend/app/sync.py` (70)

- L126: no se pudo eliminar la versión {}: {}
- L130: ): eliminadas
- L130: poda (máx. {}): eliminadas {} versiones antiguas: {}
- L141: ya hay una operación de este juego en curso
- L265: resolución inválida: {}
- L267: no está disponible para resolver (offline o desconocido)
- L267: {} no está disponible para resolver (offline o desconocido)
- L269: no tiene datos: no puede ganar
- L269: {} no tiene datos: no puede ganar
- L319: resolución inválida: {}
- L325: política de conflicto inválida: {}
- L334: [{}] {}
- L345: ya hay una sincronización de este juego en curso
- L383: no se pudo comprobar el proceso en {}: {}
- L385: está abierto en
- L385: {} está abierto en {}
- L387: no está abierto
- L387: {} no está abierto
- L404: (simulación (dry-run))
- L412: : host key guardada (primer uso)
- L412: {}: host key guardada (primer uso)
- L413: : conexión OK
- L413: {}: conexión OK
- L416: : no responde (
- L416: {}: no responde ({})
- L420: no responden; no se toca nada
- L420: {} no responden; no se toca nada
- L422: offline: se compara
- L422: solo con el hub
- L422: {} offline: se compara {} solo con el hub
- L438: : la ruta no existe todavía (se trata como vacía)
- L438: {}: la ruta no existe todavía (se trata como vacía)
- L445: , mtime máx
- L445: {}: {} ficheros, hash {}, mtime máx {}
- L458: nada que sincronizar (todo vacío)
- L461: ya sincronizado
- L462: ya sincronizado: nada que hacer
- L473: ); elige de nuevo
- L473: los datos cambiaron desde que se mostró el conflicto ({}); elige de nuevo
- L479: ): gana
- L479: conflicto resuelto manualmente ({}): gana {}
- L485: conflicto resuelto por política 'newest': gana {}
- L490: s: no se puede saber cuál es más reciente
- L490: los relojes difieren menos de {} s: no se puede saber cuál es más reciente
- L492: los datos cambiaron desde que se mostró el conflicto
- L493: primera sincronización con contenidos distintos
- L494: los contenidos difieren sin cambios registrados
- L495: ambos lados cambiaron desde la última sincronización
- L500: (política: omitir)
- L500: no se modifica nada
- L509: (versión anterior se guarda)
- L510: plan: {} -> {}{}
- L513: ; destinos
- L513: ganador {}; destinos {}
- L514: simulación (dry-run): no se modifica nada
- L528: versión guardada: {}/{}
- L549: ; actualizados
- L549: ; fallaron
- L549: ganador {}; actualizados {}; fallaron {}
- L550: {} ({})
- L551: sincronización PARCIAL: baseline sin actualizar; se completará en la próxima ejecución
- L556: ({} offline: pendiente)
- L556: offline: pendiente)
- L557: ; actualizados
- L557: ganador {}; actualizados {}{}
- L558: sincronización completada
- L569: versión/origen inválido
- L574: no existe esa versión
- L593: ; ejecuta Sincronizar para propagarlo
- L593: hub restaurado desde {}/{}; ejecuta Sincronizar para propagarlo

### `backend/app/transport.py` (55)

- L56: falta binario: {}
- L87: SSH falló: {}
- L95: SSH falló: {}
- L105: rsync pull falló: {}
- L110: mkdir remoto falló: {}
- L115: rsync push falló: {}
- L119: nombre de proceso inválido
- L127: pgrep falló: {}
- L147: SSH falló: {}
- L150: \" (exit 0) else (exit 1)
- L150: if exist "{}\" (exit 0) else (exit 1)
- L155: SSH falló: {}
- L159: tar -cf - -C "{}" .
- L171: tar pull falló: {}
- L177: \" mkdir "
- L177: if not exist "{}\" mkdir "{}"
- L179: mkdir remoto falló: {}
- L183: del /f /q "{}"
- L186: tar -xf - -C "{}"
- L196: tar push falló: {}
- L200: nombre de proceso inválido
- L201: " /NH
- L201: tasklist /FI "IMAGENAME eq {}" /NH
- L203: tasklist falló: {}
- L229: ruta vacía
- L231: ruta inválida (carácter nulo)
- L233: '..' no permitido en rutas
- L235: la ruta no es absoluta en este sistema: {}
- L244: ruta no resoluble: {}
- L270: no se pudo leer {}: {}
- L283: no se pudo copiar {}: {}
- L307: la ruta existe pero no es una carpeta: {}
- L309: sin permiso de lectura en {}
- L311: sin permiso para acceder a {}: {}
- L313: no se pudo acceder a {}: {}
- L319: la carpeta no existe: {}
- L326: la ruta existe pero no es una carpeta: {}
- L330: no se pudo crear {}: {}
- L337: no se pudo escribir en {}: {}
- L369: no se pudo colocar la carpeta nueva: {}
- L414: no se pudo escribir {}: {}
- L421: no se pudo borrar {}: {}
- L434: nombre de proceso inválido
- L438: tasklist falló:
- L448: pgrep falló:
- L463: no se puede comprobar el proceso: falta pgrep
- L489: Este equipo: acceso local directo, sin SSH. Indica la ruta de los saves en cada juego.
- L498: la ruta existe pero no es una carpeta
- L500: la carpeta existe pero no se puede leer (sin permiso)
- L502: la carpeta se puede leer pero no escribir (sin permiso o solo lectura)
- L508: no es una carpeta
- L508: no se puede crear la carpeta: {} no es una carpeta
- L510: la carpeta no existe y no se puede crear: sin permiso de escritura en {}
- L511: la carpeta no existe todavía; se creará al sincronizar (se trata como vacía)
- L513: no se pudo comprobar la carpeta: {}

### `backend/app/updates.py` (3)

- L98: redirección no HTTPS rechazada
- L196: canal no válido
- L246: no se pudo comprobar

