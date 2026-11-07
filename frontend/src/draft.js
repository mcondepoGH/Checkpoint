// Borrador del formulario de Configuración: estado editable <-> estructura de config.yaml.
// Los juegos referencian dispositivos por id interno (no por nombre) para que renombrar o
// borrar el nombre mientras se escribe no rompa las referencias.
let seq = 0;
const uid = () => `i${++seq}`;

export const OS_OPTIONS = [['windows', 'Windows'], ['steamos', 'SteamOS'], ['linux', 'Linux']];

export const blankDevice = () => ({ id: uid(), name: '', host: '', port: '22', user: '', os: 'linux' });
export const blankGame = () => ({ id: uid(), name: '', a: '', b: '', pathA: '', pathB: '', process: '', keep: '5' });

export function fromConfig(cfg) {
  const devices = Object.entries(cfg?.devices || {}).map(([name, d]) => ({
    id: uid(), name, host: d.host, port: String(d.port ?? 22), user: d.user, os: d.os,
  }));
  const idOf = (n) => devices.find((d) => d.name === n)?.id || '';
  const games = Object.entries(cfg?.games || {}).map(([name, g]) => ({
    id: uid(), name, a: idOf(g.devices[0]), b: idOf(g.devices[1]),
    pathA: g.paths?.[g.devices[0]] ?? '', pathB: g.paths?.[g.devices[1]] ?? '',
    process: g.process || '', keep: String(g.keep_versions ?? 5),
  }));
  return { devices, games };
}

// Enteros como número; otro texto se envía tal cual para que el backend dé el error del campo.
const num = (v) => (/^\d+$/.test(String(v).trim()) ? Number(v) : String(v));

export const nameOf = (draft, id) => draft.devices.find((d) => d.id === id)?.name || '';

// Nombres vacíos o repetidos: se detectan en local (no caben como claves de un mapa).
export function localErrors(draft) {
  const errs = {};
  for (const list of [draft.devices, draft.games]) {
    const seen = new Set();
    for (const it of list) {
      if (!it.name.trim()) errs[it.id] = 'El nombre es obligatorio';
      else if (seen.has(it.name)) errs[it.id] = 'Nombre repetido';
      seen.add(it.name);
    }
  }
  return errs;
}

export function toConfig(draft) {
  const bad = localErrors(draft);
  const devices = {};
  for (const d of draft.devices) {
    if (bad[d.id]) continue;
    devices[d.name] = { host: d.host, user: d.user, os: d.os, port: num(d.port) };
  }
  const games = {};
  for (const g of draft.games) {
    if (bad[g.id]) continue;
    const na = nameOf(draft, g.a);
    const nb = nameOf(draft, g.b);
    const paths = {};
    if (na) paths[na] = g.pathA;
    if (nb) paths[nb] = g.pathB;
    games[g.name] = {
      devices: [na, nb], paths,
      ...(g.process.trim() ? { process: g.process.trim() } : {}),
      keep_versions: num(g.keep),
    };
  }
  return { devices, games };
}

export const gamesUsing = (draft, devId) =>
  draft.games.filter((g) => g.a === devId || g.b === devId).map((g) => g.name || '(sin nombre)');

export function removeDevice(draft, devId) {
  const clear = (g) => ({
    ...g, a: g.a === devId ? '' : g.a, b: g.b === devId ? '' : g.b,
    pathA: g.a === devId ? '' : g.pathA, pathB: g.b === devId ? '' : g.pathB,
  });
  return { devices: draft.devices.filter((d) => d.id !== devId), games: draft.games.map(clear) };
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
