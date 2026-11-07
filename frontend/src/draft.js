// Borrador del formulario de Configuración: estado editable <-> estructura de config.yaml.
// Los juegos referencian dispositivos por id interno (no por nombre) para que renombrar o
// borrar el nombre mientras se escribe no rompa las referencias.
let seq = 0;
const uid = () => `i${++seq}`;

export const OS_OPTIONS = [['windows', 'Windows'], ['linux', 'Linux']]
// Valor heredado de config.yaml: se muestra como Linux (equivale a él) y se guarda como tal.
const LEGACY_OS = { steamos: 'linux' };;

export const blankDevice = () => ({ id: uid(), name: '', host: '', port: '22', user: '', os: 'linux' });
export const blankGame = () => ({ id: uid(), name: '', a: '', b: '', pathA: '', pathB: '', process: '', keep: '', onConflict: '' });

// Versiones guardadas por juego: global (por defecto) y override por juego (vacío = usar el global). 0 = sin límite.
export const DEFAULT_MAX_VERSIONS = 20;
export const MAX_VERSIONS_LIMIT = 1000;
export const VERSIONS_HINT = '0 = sin límite; al superarlo se borran las más antiguas';

export function fromConfig(cfg) {
  const devices = Object.entries(cfg?.devices || {}).map(([name, d]) => ({
    id: uid(), name, host: d.host, port: String(d.port ?? 22), user: d.user, os: LEGACY_OS[d.os] || d.os,
  }));
  const idOf = (n) => devices.find((d) => d.name === n)?.id || '';
  const games = Object.entries(cfg?.games || {}).map(([name, g]) => ({
    id: uid(), name, a: idOf(g.devices[0]), b: idOf(g.devices[1]),
    pathA: g.paths?.[g.devices[0]] ?? '', pathB: g.paths?.[g.devices[1]] ?? '',
    process: g.process || '', keep: g.keep_versions == null ? '' : String(g.keep_versions),
    onConflict: g.on_conflict || '',
  }));
  return { devices, games, maxVersions: String(cfg?.max_versions ?? DEFAULT_MAX_VERSIONS) };
}

// Enteros como número; otro texto se envía tal cual para que el backend dé el error del campo.
const num = (v) => (/^\d+$/.test(String(v).trim()) ? Number(v) : String(v));

export const nameOf = (draft, id) => cleanName(draft.devices.find((d) => d.id === id)?.name || '');

// Nombre visible libre: sin / ni \\, sin caracteres de control; máx. 64. Se normaliza al enviar.
export const NAME_MAX = 64;
export const NAME_HINT = `Hasta ${NAME_MAX} caracteres. Se admiten espacios, símbolos, acentos y emojis; no / ni \\`;
export const cleanName = (n) => String(n).replace(/\s+/g, ' ').trim();
const BAD_NAME = /[\u0000-\u001f\u007f-\u009f\u2028\u2029/\\]/;
const nameKey = (n) => cleanName(n).toLowerCase();

// Nombres vacíos, inválidos o repetidos: se detectan en local (no caben como claves de un mapa).
const versionsError = (v) => (/^\d+$/.test(String(v).trim()) && Number(v) <= MAX_VERSIONS_LIMIT
  ? undefined : `Debe ser un número entero entre 0 y ${MAX_VERSIONS_LIMIT} (0 = sin límite)`);

export function localErrors(draft) {
  const errs = {};
  const gv = versionsError(draft.maxVersions);
  if (gv) errs.maxVersions = gv;
  for (const g of draft.games) {
    const e = String(g.keep).trim() === '' ? undefined : versionsError(g.keep);
    if (e) errs[`keep-${g.id}`] = e;
  }
  for (const list of [draft.devices, draft.games]) {
    const seen = new Set();
    for (const it of list) {
      const n = cleanName(it.name);
      if (!n) errs[it.id] = 'El nombre es obligatorio';
      else if (n.length > NAME_MAX) errs[it.id] = `Nombre demasiado largo (máx. ${NAME_MAX} caracteres)`;
      else if (BAD_NAME.test(n)) errs[it.id] = 'Nombre inválido: no se admiten / \\ ni caracteres de control';
      else if (!n.replace(/\./g, '')) errs[it.id] = 'Nombre inválido: no puede ser solo puntos';
      else if (seen.has(nameKey(n))) errs[it.id] = 'Nombre repetido (sin distinguir mayúsculas ni espacios extra)';
      seen.add(nameKey(n));
    }
  }
  return errs;
}

export function toConfig(draft) {
  const bad = localErrors(draft);
  const devices = {};
  for (const d of draft.devices) {
    if (bad[d.id]) continue;
    devices[cleanName(d.name)] = { host: d.host, user: d.user, os: LEGACY_OS[d.os] || d.os, port: num(d.port) };
  }
  const games = {};
  for (const g of draft.games) {
    if (bad[g.id]) continue;
    const na = nameOf(draft, g.a);
    const nb = nameOf(draft, g.b);
    const paths = {};
    if (na) paths[na] = g.pathA;
    if (nb) paths[nb] = g.pathB;
    games[cleanName(g.name)] = {
      devices: [na, nb], paths,
      ...(g.process.trim() ? { process: g.process.trim() } : {}),
      ...(String(g.keep).trim() !== '' ? { keep_versions: num(g.keep) } : {}),
      ...(g.onConflict ? { on_conflict: g.onConflict } : {}),
    };
  }
  return { max_versions: num(draft.maxVersions), devices, games };
}

export const gamesUsing = (draft, devId) =>
  draft.games.filter((g) => g.a === devId || g.b === devId).map((g) => g.name || '(sin nombre)');

export function removeDevice(draft, devId) {
  const clear = (g) => ({
    ...g, a: g.a === devId ? '' : g.a, b: g.b === devId ? '' : g.b,
    pathA: g.a === devId ? '' : g.pathA, pathB: g.b === devId ? '' : g.pathB,
  });
  return { ...draft, devices: draft.devices.filter((d) => d.id !== devId), games: draft.games.map(clear) };
}

// Los errores del backend vienen como {"games.ejemplo.paths.pc": "msg"}.
export const errorsFor = (errors, prefix) => {
  const out = {};
  for (const [k, v] of Object.entries(errors || {})) {
    if (k === prefix) out[''] = v;
    else if (k.startsWith(prefix + '.')) out[k.slice(prefix.length + 1)] = v;
  }
  return out;
};
