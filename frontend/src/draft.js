// Borrador del formulario de Configuración: estado editable <-> estructura de config.yaml.
// Cada juego y dispositivo tiene un ID interno estable e inmutable (la clave en config.yaml); el nombre es solo
// una etiqueta editable. En el borrador cada elemento lleva:
//   key  : identidad en el formulario (React, referencias de los juegos a sus dispositivos). Es el id real si ya
//          existe; si es nuevo, un valor temporal que no se guarda.
//   id   : el id real si ya existía en config.yaml; null si es nuevo.
//   salt : 8 hex aleatorios de un elemento nuevo. Su id se forma al guardar como <parte ASCII del nombre>-<salt>
//          (no existe nada en disco con él hasta entonces) y desde ese momento ya no cambia aunque se renombre.
// Renombrar solo modifica `name`.
let seq = 0;
const uid = () => `i${++seq}`;

const hex8 = () => {
  const b = new Uint8Array(4);
  (globalThis.crypto?.getRandomValues ? globalThis.crypto.getRandomValues(b) : b.forEach((_, i) => { b[i] = Math.floor(Math.random() * 256); }));
  return Array.from(b, (x) => x.toString(16).padStart(2, '0')).join('');
};

// Prefijo legible del id: parte ASCII del nombre (NFKD, minúsculas, [a-z0-9_-], máx. 40) o el genérico.
export const idPrefix = (name, kind) => {
  const base = String(name || '').normalize('NFKD').replace(/[^\x00-\x7f]/g, '').toLowerCase()
    .replace(/[^a-z0-9_-]+/g, '-').slice(0, 40).replace(/^[-_]+|[-_]+$/g, '');
  return base || kind;
};

// Id con el que se guardará el elemento: el real si existe; si no, prefijo del nombre actual + su salt.
export const idOf = (item, kind) => item.id || `${idPrefix(item.name, kind)}-${item.salt}`;

export const OS_OPTIONS = [['windows', 'Windows'], ['linux', 'Linux']]

export const blankDevice = () => ({ key: uid(), id: null, salt: hex8(), name: '', local: false, host: '', port: '22', user: '', os: 'linux' });

// «Este equipo»: el dispositivo es la máquina donde corre Checkpoint (sin SSH). Solo existe fuera de Docker
// (runtime === 'native', lo informa /api/config) y como máximo uno.
// Textos de interfaz: LOCAL_LABEL y LOCAL_HELP son claves del catálogo; los errores son cuerpos {code, params}
// (los mismos códigos que devuelve el backend) que se traducen al pintar con errorText/fieldErrorText.
export const LOCAL_LABEL = 'device.localLabel';
export const LOCAL_DOCKER_MSG = { code: 'err.config.local_docker', params: {} };
export const LOCAL_ONE_MSG = { code: 'err.config.local_one', params: {} };
export const LOCAL_HELP = 'device.localHelp';
// SO que se autorrellena al marcarlo: el de la plataforma que informa el backend (macOS usa rutas POSIX = linux).
export const localOs = (platform) => (platform === 'windows' ? 'windows' : 'linux');
// ¿Se ofrece la casilla en este dispositivo? Solo en modo nativo y si no hay ya otro «Este equipo».
export const canOfferLocal = (draft, runtime, devKey) =>
  runtime === 'native' && !draft.devices.some((d) => d.local && d.key !== devKey);
// Cambio de borrador al marcar/desmarcar «Este equipo». Host/usuario/puerto se conservan en el borrador (por si
// se desmarca) pero no se envían ni se guardan mientras sea local; el SO se autorrellena con el de la plataforma.
export const localPatch = (on, platform) => (on ? { local: true, os: localOs(platform) } : { local: false });
// Rutas de los saves que usan un dispositivo (para «Comprobar carpeta»).
export const pathsOf = (draft, devKey) => draft.games.flatMap((g) => [
  g.a === devKey && g.pathA ? g.pathA : null, g.b === devKey && g.pathB ? g.pathB : null].filter(Boolean));
export const blankGame = () => ({ key: uid(), id: null, salt: hex8(), name: '', a: '', b: '', pathA: '', pathB: '', process: '', keep: '', onConflict: '' });

// Versiones guardadas por juego: global (por defecto) y override por juego (vacío = usar el global). 0 = sin límite.
export const DEFAULT_MAX_VERSIONS = 20;
export const MAX_VERSIONS_LIMIT = 1000;
export const VERSIONS_HINT = 'draft.versionsHint'; // clave del catálogo

export function fromConfig(cfg) {
  const devices = Object.entries(cfg?.devices || {}).map(([id, d]) => ({
    key: id, id, name: d.name, orig: d.name, local: d.local === true,
    host: d.host ?? '', port: String(d.port ?? 22), user: d.user ?? '', os: d.os,
  }));
  const keyOf = (id) => devices.find((d) => d.id === id)?.key || '';
  const games = Object.entries(cfg?.games || {}).map(([id, g]) => ({
    key: id, id, name: g.name, orig: g.name, a: keyOf(g.devices[0]), b: keyOf(g.devices[1]),
    pathA: g.paths?.[g.devices[0]] ?? '', pathB: g.paths?.[g.devices[1]] ?? '',
    process: g.process || '', keep: g.keep_versions == null ? '' : String(g.keep_versions),
    onConflict: g.on_conflict || '',
  }));
  return { devices, games, maxVersions: String(cfg?.max_versions ?? DEFAULT_MAX_VERSIONS) };
}

// Enteros como número; otro texto se envía tal cual para que el backend dé el error del campo.
const num = (v) => (/^\d+$/.test(String(v).trim()) ? Number(v) : String(v));

export const nameOf = (draft, key) => cleanName(draft.devices.find((d) => d.key === key)?.name || '');
// Id con el que se guardará el dispositivo referenciado por `key` ('' si no existe).
export const deviceId = (draft, key) => {
  const d = draft.devices.find((x) => x.key === key);
  return d ? idOf(d, 'dispositivo') : '';
};
// ¿Se ha cambiado el nombre de un elemento que ya existía? (el id no cambia)
export const renamed = (item) => !!item.id && cleanName(item.name) !== cleanName(item.orig ?? item.name);

// Nombre visible libre: sin / ni \\, sin caracteres de control; máx. 64. Se normaliza al enviar.
export const NAME_MAX = 64;
export const NAME_HINT = 'draft.nameHint'; // clave del catálogo; parámetro {max} = NAME_MAX
export const cleanName = (n) => String(n).replace(/\s+/g, ' ').trim();
const SLASH_NAME = /[/\\]/;
const CONTROL_NAME = /[\u0000-\u001f\u007f-\u009f\u2028\u2029]/;
const nameKey = (n) => cleanName(n).toLowerCase();

// Nombres vacíos, inválidos o repetidos: se detectan en local para avisar al instante (el backend repite la comprobación).
// Los errores son cuerpos {code, params} con los mismos códigos `err.config.*` del backend.
const versionsError = (v) => (/^\d+$/.test(String(v).trim()) && Number(v) <= MAX_VERSIONS_LIMIT
  ? undefined : { code: 'err.config.versions_range', params: { max: MAX_VERSIONS_LIMIT } });

export function localErrors(draft, runtime) {
  const errs = {};
  const locals = draft.devices.filter((d) => d.local);
  locals.forEach((d, i) => {
    if (runtime === 'docker') errs[`local-${d.key}`] = LOCAL_DOCKER_MSG;
    else if (i > 0) errs[`local-${d.key}`] = LOCAL_ONE_MSG;
  });
  const gv = versionsError(draft.maxVersions);
  if (gv) errs.maxVersions = gv;
  for (const g of draft.games) {
    const e = String(g.keep).trim() === '' ? undefined : versionsError(g.keep);
    if (e) errs[`keep-${g.key}`] = e;
  }
  for (const list of [draft.devices, draft.games]) {
    const seen = new Map(); // nombre normalizado -> primer nombre que lo usó
    for (const it of list) {
      const n = cleanName(it.name);
      const err = (code, params = {}) => { errs[it.key] = { code: `err.config.${code}`, params }; };
      if (!n) err('name_empty');
      else if (n.length > NAME_MAX) err('name_too_long', { max: NAME_MAX });
      else if (SLASH_NAME.test(n)) err('name_slash');
      else if (CONTROL_NAME.test(n)) err('name_control');
      else if (!n.replace(/\./g, '')) err('name_dots');
      else if (seen.has(nameKey(n))) err('name_duplicate', { other: seen.get(nameKey(n)) });
      if (!seen.has(nameKey(n))) seen.set(nameKey(n), n);
    }
  }
  return errs;
}

export function toConfig(draft) {
  const devices = {};
  for (const d of draft.devices) {
    const { os } = d;
    devices[idOf(d, 'dispositivo')] = d.local
      ? { name: cleanName(d.name), local: true, os }
      : { name: cleanName(d.name), host: d.host, user: d.user, os, port: num(d.port) };
  }
  const games = {};
  for (const g of draft.games) {
    const ia = deviceId(draft, g.a);
    const ib = deviceId(draft, g.b);
    const paths = {};
    if (ia) paths[ia] = g.pathA;
    if (ib) paths[ib] = g.pathB;
    games[idOf(g, 'juego')] = {
      name: cleanName(g.name), devices: [ia, ib], paths,
      ...(g.process.trim() ? { process: g.process.trim() } : {}),
      ...(String(g.keep).trim() !== '' ? { keep_versions: num(g.keep) } : {}),
      ...(g.onConflict ? { on_conflict: g.onConflict } : {}),
    };
  }
  return { max_versions: num(draft.maxVersions), devices, games };
}

// Clave canónica de la config tal como la enviaría el formulario sin tocar nada.
export const baseKeyOf = (config) => JSON.stringify(toConfig(fromConfig(config)));
// ¿Hay cambios pendientes? Solo si el borrador difiere de la config cargada o hay errores locales.
export const hasChanges = (payloadKey, baseKey, local) => payloadKey !== baseKey || Object.keys(local).length > 0;
export const isDirty = (draft, config, runtime) => hasChanges(JSON.stringify(toConfig(draft)), baseKeyOf(config), localErrors(draft, runtime));

export const gamesUsing = (draft, devKey) =>
  draft.games.filter((g) => g.a === devKey || g.b === devKey).map((g) => g.name);  // '' si no tiene nombre (la pantalla pone «(sin nombre)»)

export function removeDevice(draft, devKey) {
  const clear = (g) => ({
    ...g, a: g.a === devKey ? '' : g.a, b: g.b === devKey ? '' : g.b,
    pathA: g.a === devKey ? '' : g.pathA, pathB: g.b === devKey ? '' : g.pathB,
  });
  return { ...draft, devices: draft.devices.filter((d) => d.key !== devKey), games: draft.games.map(clear) };
}

// Los errores del backend vienen como {"games.<id>.paths.<id dispositivo>": {code, params}} (o texto, si es antiguo).
// `tr` convierte cada valor en texto (p. ej. v => fieldErrorText(v, t)); por defecto los deja tal cual.
export const errorsFor = (errors, prefix, tr = (v) => v) => {
  const out = {};
  for (const [k, v] of Object.entries(errors || {})) {
    if (k === prefix) out[''] = tr(v);
    else if (k.startsWith(prefix + '.')) out[k.slice(prefix.length + 1)] = tr(v);
  }
  return out;
};
