// «Este equipo» (dispositivo local): borrador <-> config, casilla, ids estables y sin cambios fantasma.
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  LOCAL_DOCKER_MSG, LOCAL_ONE_MSG, baseKeyOf, blankDevice, canOfferLocal, fromConfig, idOf, isDirty, localErrors,
  localOs, localPatch, pathsOf, removeDevice, toConfig,
} from '../src/draft.js';

const CFG = {
  max_versions: 20,
  devices: {
    'pc-1a2b3c4d': { name: 'PC', local: true, os: 'linux' },
    'laptop-5e6f7a8b': { name: 'Laptop', host: '192.0.2.10', user: 'usuario', os: 'linux', port: 2222 },
  },
  games: {
    'g-0a1b2c3d': { name: 'Juego', devices: ['pc-1a2b3c4d', 'laptop-5e6f7a8b'],
      paths: { 'pc-1a2b3c4d': '/home/usuario/saves', 'laptop-5e6f7a8b': '/home/usuario/g' } },
  },
};
const REMOTE_ONLY = {
  max_versions: 20,
  devices: { 'a-11111111': { name: 'A', host: '192.0.2.1', user: 'u', os: 'linux', port: 22 } },
  games: {},
};

test('fromConfig lee local y no inventa host/usuario', () => {
  const d = fromConfig(CFG);
  const pc = d.devices.find((x) => x.id === 'pc-1a2b3c4d');
  assert.equal(pc.local, true);
  assert.equal(pc.host, '');
  assert.equal(pc.user, '');
  const lap = d.devices.find((x) => x.id === 'laptop-5e6f7a8b');
  assert.equal(lap.local, false);
  assert.equal(lap.host, '192.0.2.10');
});

test('toConfig: el local no envía host/user/port y el remoto no envía local', () => {
  const out = toConfig(fromConfig(CFG));
  assert.deepEqual(out.devices['pc-1a2b3c4d'], { name: 'PC', local: true, os: 'linux' });
  assert.deepEqual(out.devices['laptop-5e6f7a8b'], { name: 'Laptop', host: '192.0.2.10', user: 'usuario', os: 'linux', port: 2222 });
  assert.ok(!('local' in out.devices['laptop-5e6f7a8b']));
});

test('ida y vuelta sin cambios fantasma (config con y sin local)', () => {
  for (const c of [CFG, REMOTE_ONLY]) {
    assert.deepEqual(toConfig(fromConfig(c)), c);
    assert.equal(isDirty(fromConfig(c), c, 'native'), false);
    assert.equal(baseKeyOf(c), JSON.stringify(toConfig(fromConfig(c))));
  }
});

test('config antigua sin campo local: dispositivos remotos intactos', () => {
  assert.deepEqual(toConfig(fromConfig(REMOTE_ONLY)), REMOTE_ONLY);
});

test('marcar la casilla: local + SO de la plataforma; host/usuario se conservan pero no se envían', () => {
  const d = fromConfig(REMOTE_ONLY);
  const dev = d.devices[0];
  const on = { ...dev, ...localPatch(true, 'windows') };
  assert.equal(on.local, true);
  assert.equal(on.os, 'windows');
  assert.equal(on.host, '192.0.2.1');
  const out = toConfig({ ...d, devices: [on] });
  assert.deepEqual(out.devices['a-11111111'], { name: 'A', local: true, os: 'windows' });
  assert.equal(isDirty({ ...d, devices: [on] }, REMOTE_ONLY, 'native'), true);
  // desmarcar y restaurar el SO deja exactamente lo cargado: sin cambios
  const off = { ...on, ...localPatch(false, 'windows'), os: 'linux' };
  assert.equal(off.local, false);
  assert.equal(isDirty({ ...d, devices: [off] }, REMOTE_ONLY, 'native'), false);
});

test('SO autorrellenado según plataforma', () => {
  assert.equal(localOs('windows'), 'windows');
  assert.equal(localOs('linux'), 'linux');
  assert.equal(localOs('macos'), 'linux');
  assert.equal(localOs(undefined), 'linux');
});

test('la casilla solo se ofrece en native y mientras no haya otro local', () => {
  const d = fromConfig(CFG);
  const pc = d.devices.find((x) => x.id === 'pc-1a2b3c4d');
  const lap = d.devices.find((x) => x.id === 'laptop-5e6f7a8b');
  assert.equal(canOfferLocal(d, 'native', pc.key), true); // el propio local puede desmarcarse
  assert.equal(canOfferLocal(d, 'native', lap.key), false); // ya hay uno
  assert.equal(canOfferLocal(d, 'docker', pc.key), false);
  assert.equal(canOfferLocal(d, 'docker', lap.key), false);
  assert.equal(canOfferLocal(d, undefined, lap.key), false); // runtime aún no cargado
  const r = fromConfig(REMOTE_ONLY);
  assert.equal(canOfferLocal(r, 'native', r.devices[0].key), true);
  assert.equal(canOfferLocal(r, 'docker', r.devices[0].key), false);
  assert.equal(canOfferLocal(removeDevice(d, pc.key), 'native', lap.key), true); // al borrar el local vuelve a ofrecerse
});

test('un solo local: el segundo marcado da error', () => {
  const d = fromConfig(CFG);
  const lap = d.devices.find((x) => x.id === 'laptop-5e6f7a8b');
  const two = { ...d, devices: d.devices.map((x) => (x === lap ? { ...x, ...localPatch(true, 'linux') } : x)) };
  const errs = localErrors(two, 'native');
  assert.equal(errs[`local-${lap.key}`], LOCAL_ONE_MSG);
  assert.equal(Object.keys(errs).filter((k) => k.startsWith('local-')).length, 1);
  assert.equal(isDirty(two, CFG, 'native'), true);
});

test('en docker un local es error de validación', () => {
  const d = fromConfig(CFG);
  const errs = localErrors(d, 'docker');
  assert.equal(errs['local-pc-1a2b3c4d'], LOCAL_DOCKER_MSG);
  assert.deepEqual(Object.keys(localErrors(d, 'native')), []);
  assert.match(LOCAL_DOCKER_MSG, /sin Docker/);
});

test('ids estables: renombrar no cambia claves, juegos ni rutas', () => {
  const d = fromConfig(CFG);
  const pc = d.devices.find((x) => x.id === 'pc-1a2b3c4d');
  const renamed = { ...pc, name: 'Sobremesa' };
  assert.equal(idOf(renamed, 'dispositivo'), 'pc-1a2b3c4d');
  const out = toConfig({ ...d, devices: d.devices.map((x) => (x === pc ? renamed : x)) });
  assert.deepEqual(Object.keys(out.devices), ['pc-1a2b3c4d', 'laptop-5e6f7a8b']);
  assert.deepEqual(out.games['g-0a1b2c3d'].devices, ['pc-1a2b3c4d', 'laptop-5e6f7a8b']);
  assert.deepEqual(out.games['g-0a1b2c3d'].paths, CFG.games['g-0a1b2c3d'].paths);
});

test('dispositivo nuevo marcado como local recibe id nombre-salt y no envía SSH', () => {
  const b = { ...blankDevice(), name: 'Mi Sobremesa', ...localPatch(true, 'linux') };
  const out = toConfig({ devices: [b], games: [], maxVersions: '20' });
  const id = idOf(b, 'dispositivo');
  assert.match(id, /^mi-sobremesa-[0-9a-f]{8}$/);
  assert.deepEqual(out.devices[id], { name: 'Mi Sobremesa', local: true, os: 'linux' });
  assert.equal(blankDevice().local, false);
});

test('pathsOf devuelve las rutas de los juegos que usan el dispositivo', () => {
  const d = fromConfig(CFG);
  const pc = d.devices.find((x) => x.id === 'pc-1a2b3c4d');
  const lap = d.devices.find((x) => x.id === 'laptop-5e6f7a8b');
  assert.deepEqual(pathsOf(d, pc.key), ['/home/usuario/saves']);
  assert.deepEqual(pathsOf(d, lap.key), ['/home/usuario/g']);
  assert.deepEqual(pathsOf({ ...d, games: [] }, pc.key), []);
});

test('quitar el dispositivo local limpia el juego', () => {
  const d = fromConfig(CFG);
  const pc = d.devices.find((x) => x.id === 'pc-1a2b3c4d');
  const r = removeDevice(d, pc.key);
  assert.equal(r.devices.length, 1);
  assert.equal(r.games[0].a, '');
  assert.equal(r.games[0].pathA, '');
});
