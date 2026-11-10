// Test sin dependencias: `node --test test/` (Node >= 18). Cubre el borrador de Configuración y los nombres visibles.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { baseKeyOf, fromConfig, isDirty, toConfig } from '../src/draft.js';
import { labelOf } from '../src/names.js';

// Lo que devuelve /api/config para un config.yaml LEGADO (claves por nombre, sin `name`): el backend lo
// normaliza a ids, con el nombre antiguo en `name`.
const LEGACY = {
  max_versions: 20,
  devices: {
    pc: { name: 'pc', host: '10.0.0.1', user: 'u', os: 'windows', port: 22 },
    laptop: { name: 'laptop', host: '10.0.0.2', user: 'u', os: 'linux', port: 22 },
  },
  games: {
    'Mi-Juego-82542a10': {
      name: 'Mi Juego', devices: ['pc', 'laptop'], paths: { pc: 'C:/Saves', laptop: '/home/usuario/saves' },
      process: 'juego.exe', keep_versions: 3, on_conflict: 'skip',
    },
  },
};
// Formato NUEVO (ids estables).
const NEW = {
  max_versions: 5,
  devices: {
    'pc-1a2b3c4d': { name: 'Mi PC', host: '10.0.0.1', user: 'u', os: 'windows', port: 2222 },
    'laptop-5e6f7a8b': { name: 'Portátil', host: '10.0.0.2', user: 'u', os: 'linux', port: 22 },
  },
  games: {
    'zelda-0a1b2c3d': { name: 'Zelda', devices: ['pc-1a2b3c4d', 'laptop-5e6f7a8b'], paths: { 'pc-1a2b3c4d': 'C:/z', 'laptop-5e6f7a8b': '/home/usuario/z' } },
  },
};
const EMPTY = { max_versions: 20, devices: {}, games: {} };

for (const [label, cfg] of [['legado', LEGACY], ['nuevo', NEW]]) {
  test(`sin cambios no hay pendientes (${label})`, () => {
    const d = fromConfig(cfg);
    assert.equal(isDirty(d, cfg), false);
    // el formulario reenvía exactamente la config cargada (mismos ids, nombres y valores)
    assert.deepEqual(toConfig(d), cfg);
  });

  test(`editar cualquier campo marca cambios (${label})`, () => {
    const edits = [
      (d) => { d.maxVersions = '7'; },
      (d) => { d.devices[0].name += ' 2'; },   // renombrar
      (d) => { d.devices[0].host = '10.9.9.9'; },
      (d) => { d.devices[0].port = '2200'; },
      (d) => { d.devices[0].os = d.devices[0].os === 'linux' ? 'windows' : 'linux'; },
      (d) => { d.games[0].name += ' 2'; },     // renombrar
      (d) => { d.games[0].pathA += 'x'; },
      (d) => { d.games[0].process = 'otro.exe'; },
      (d) => { d.games[0].keep = '9'; },
      (d) => { d.games[0].onConflict = 'hub'; },
      (d) => { d.games.pop(); },
    ];
    for (const [i, edit] of edits.entries()) {
      const d = fromConfig(cfg);
      edit(d);
      assert.equal(isDirty(d, cfg), true, `edición ${i}`);
    }
  });

  test(`renombrar no cambia el id (${label})`, () => {
    const d = fromConfig(cfg);
    const [gid] = Object.keys(cfg.games);
    d.games[0].name = 'Otro nombre';
    assert.deepEqual(Object.keys(toConfig(d).games), [gid]);
  });
}

test('borrador vacío previo a la carga no cuenta como cambios al llegar la config', () => {
  // La config llega con un borrador aún vacío: ese borrador es de otra versión, no una edición del usuario.
  const stale = fromConfig(EMPTY);
  assert.equal(isDirty(stale, LEGACY), true, 'comparación cruzada sí difiere (por eso hay que reiniciar el borrador en el render)');
  assert.equal(isDirty(fromConfig(LEGACY), LEGACY), false);
});

test('la config real normalizada por el backend (si existe copia local de prueba) no tiene cambios', { skip: !process.env.CHECKPOINT_TEST_CONFIG_JSON }, () => {
  const cfg = JSON.parse(fs.readFileSync(process.env.CHECKPOINT_TEST_CONFIG_JSON, 'utf8'));
  assert.equal(isDirty(fromConfig(cfg), cfg), false);
  assert.equal(baseKeyOf(cfg), JSON.stringify(toConfig(fromConfig(cfg))));
});

test('labelOf muestra el nombre, nunca el id', () => {
  assert.equal(labelOf(LEGACY.games, 'Mi-Juego-82542a10'), 'Mi Juego');
  assert.equal(labelOf(LEGACY.devices, 'pc'), 'pc');
  assert.equal(labelOf(NEW.devices, 'pc-1a2b3c4d'), 'Mi PC');
  assert.equal(labelOf({ x: { name: '  ' } }, 'x'), 'x');   // sin nombre: el id como último recurso
  assert.equal(labelOf(undefined, 'x'), 'x');
});

test('las pantallas no pintan ids de juego como título', () => {
  const src = (f) => fs.readFileSync(new URL(`../src/${f}`, import.meta.url), 'utf8');
  assert.match(src('pages/Sync.jsx'), /<h3 title=.*><span className=\"game-name\">\{gameName\(g\)\}<\/span>/);
  assert.match(src('pages/Versions.jsx'), /labelOf\(config\.games, g\)/);
});

test('Configuración reinicia el borrador durante el render, no en un efecto', () => {
  // En un efecto, el primer render tras cargar compara el borrador vacío con la config nueva y marca
  // "Cambios sin guardar" (y avisa a App con onDirty(true)) sin que el usuario toque nada.
  const src = fs.readFileSync(new URL('../src/pages/Settings.jsx', import.meta.url), 'utf8');
  assert.doesNotMatch(src, /useEffect\(\(\) => \{ setDraft\(fromConfig/);
  assert.match(src, /if \(draftVersion !== loaded\.version\) \{/);
});

test('hasChanges: borrador distinto o errores locales', async () => {
  const { hasChanges } = await import('../src/draft.js');
  assert.equal(hasChanges('a', 'a', {}), false);
  assert.equal(hasChanges('a', 'b', {}), true);
  assert.equal(hasChanges('a', 'a', { x: 'err' }), true);
});

test('errorsFor traduce {code,params} con el traductor y deja pasar texto antiguo', async () => {
  const { errorsFor } = await import('../src/draft.js');
  const tr = (v) => (typeof v === 'string' ? v : `T(${v.code})`);
  const errs = { 'games.g': { code: 'a', params: {} }, 'games.g.paths.pc': { code: 'b', params: {} }, 'games.g.name': 'viejo', 'games.h.name': 'otro' };
  assert.deepEqual(errorsFor(errs, 'games.g', tr), { '': 'T(a)', 'paths.pc': 'T(b)', name: 'viejo' });
  assert.deepEqual(errorsFor({ 'x.y': 'z' }, 'x'), { y: 'z' });
});
