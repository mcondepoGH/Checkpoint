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
// Espejo de generate_id (backend/app/config.py).
export const newId = (name, kind = 'juego') => `${idPrefix(name, kind)}-${hex8()}`;
export const ID_RE = /^[A-Za-z0-9_-]{1,64}$/;

// Id con el que se guardará el elemento: el real si existe; si no, prefijo del nombre actual + su salt.
export const idOf = (item, kind) => item.id || `${idPrefix(item.name, kind)}-${item.salt}`;

export const OS_OPTIONS = [['windows', 'Windows'], ['linux', 'Linux']]
// Valor heredado de config.yaml: se muestra como Linux (equivale a él) y se guarda como tal.
const LEGACY_OS = { steamos: 'linux' };;

export const blankDevice = () => ({ key: uid(), id: null, salt: hex8(), name: '', host: '', port: '22', user: '', os: 'linux' });
export const blankGame = () => ({ key: uid(), id: null, salt: hex8(), name: '', a: '', b: '', pathA: '', pathB: '', process: '', keep: '', onConflict: '' });

// Versiones guardadas por juego: global (por defecto) y override por juego (vacío = usar el global). 0 = sin límite.
export const DEFAULT_MAX_VERSIONS = 20;
export const MAX_VERSIONS_LIMIT = 1000;
export const VERSIONS_HINT = '0 = sin límite; al superarlo se borran las más antiguas';

export function fromConfig(cfg) {
  const devices = Object.entries(cfg?.devices || {}).map(([id, d]) => ({
    key: id, id, name: d.name ?? id, orig: d.name ?? id, host: d.host, port: String(d.port ?? 22), user: d.user,
    os: LEGACY_OS[d.os] || d.os,
  }));
  const keyOf = (id) => devices.find((d) => d.id === id)?.key || '';
  const games = Object.entries(cfg?.games || {}).map(([id, g]) => ({
    key: id, id, name: g.name ?? id, orig: g.name ?? id, a: keyOf(g.devices[0]), b: keyOf(g.devices[1]),
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
export const NAME_HINT = `Hasta ${NAME_MAX} caracteres. Se admiten espacios, símbolos, acentos y emojis; no / ni \\`;
export const cleanName = (n) => String(n).replace(/\s+/g, ' ').trim();
const BAD_NAME = /[\u0000-\u001f\u007f-\u009f\u2028\u2029/\\]/;
const nameKey = (n) => cleanName(n).toLowerCase();

// Nombres vacíos, inválidos o repetidos: se detectan en local para avisar al instante (el backend repite la comprobación).
const versionsError = (v) => (/^\d+$/.test(String(v).trim()) && Number(v) <= MAX_VERSIONS_LIMIT
  ? undefined : `Debe ser un número entero entre 0 y ${MAX_VERSIONS_LIMIT} (0 = sin límite)`);

export function localErrors(draft) {
  const errs = {};
  const gv = versionsError(draft.maxVersions);
  if (gv) errs.maxVersions = gv;
  for (const g of draft.games) {
    const e = String(g.keep).trim() === '' ? undefined : versionsError(g.keep);
    if (e) errs[`keep-${g.key}`] = e;
  }
  for (const list of [draft.devices, draft.games]) {
    const seen = new Set();
    for (const it of list) {
      const n = cleanName(it.name);
      if (!n) errs[it.key] = 'El nombre es obligatorio';
      else if (n.length > NAME_MAX) errs[it.key] = `Nombre demasiado largo (máx. ${NAME_MAX} caracteres)`;
      else if (BAD_NAME.test(n)) errs[it.key] = 'Nombre inválido: no se admiten / \\ ni caracteres de control';
      else if (!n.replace(/\./g, '')) errs[it.key] = 'Nombre inválido: no puede ser solo puntos';
      else if (seen.has(nameKey(n))) errs[it.key] = 'Nombre repetido (sin distinguir mayúsculas ni espacios extra)';
      seen.add(nameKey(n));
    }
  }
  return errs;
}

export function toConfig(draft) {
  const devices = {};
  for (const d of draft.devices) {
    devices[idOf(d, 'dispositivo')] = {
      name: cleanName(d.name), host: d.host, user: d.user, os: LEGACY_OS[d.os] || d.os, port: num(d.port),
    };
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
export const isDirty = (draft, config) => JSON.stringify(toConfig(draft)) !== baseKeyOf(config) || Object.keys(localErrors(draft)).length > 0;

export const gamesUsing = (draft, devKey) =>
  draft.games.filter((g) => g.a === devKey || g.b === devKey).map((g) => g.name || '(sin nombre)');

export function removeDevice(draft, devKey) {
  const clear = (g) => ({
    ...g, a: g.a === devKey ? '' : g.a, b: g.b === devKey ? '' : g.b,
    pathA: g.a === devKey ? '' : g.pathA, pathB: g.b === devKey ? '' : g.pathB,
  });
  return { ...draft, devices: draft.devices.filter((d) => d.key !== devKey), games: draft.games.map(clear) };
}

// Los errores del backend vienen como {"games.<id>.paths.<id dispositivo>": "msg"}.
export const errorsFor = (errors, prefix) => {
  const out = {};
  for (const [k, v] of Object.entries(errors || {})) {
    if (k === prefix) out[''] = v;
    else if (k.startsWith(prefix + '.')) out[k.slice(prefix.length + 1)] = v;
  }
  return out;
};
