// Juego desactivado en Sync, Versiones, Lanzadores y el contador de vigilancia (render a HTML, es y en).
// Usa esbuild (viene con Vite); si no está disponible el test se salta.
import test from 'node:test';
import assert from 'node:assert/strict';
import { bundle } from '../helpers/bundle.mjs';

const { mod: m, skip } = await bundle(
  `import React from 'react';
  import { renderToStaticMarkup } from 'react-dom/server';
  import { i18n } from '#src/hooks/useI18n.js';
  import Sync from '#src/pages/Sync.jsx';
  import Versions from '#src/pages/Versions.jsx';
  import WatchSummary from '#src/components/watch/WatchSummary.jsx';
  import LauncherBlock from '#src/components/launchers/LauncherBlock.jsx';
  export { React, renderToStaticMarkup, i18n, Sync, Versions, WatchSummary, LauncherBlock };`,
  { navigator: true, tag: 'ckpt-disabled' },
);

const has = (h, s) => h.includes(s);
const R = (C, props, lang = 'es') => {
  m.i18n.setLocale(lang);
  return m.renderToStaticMarkup(m.React.createElement(m[C], props));
};
const dev = { name: 'PC' };
const mk = (games) => ({ devices: { pc: dev, tv: { name: 'TV' } }, games });
const ON = { name: 'Activo', devices: ['pc', 'tv'] };
const OFF = { name: 'Apagado', devices: ['pc', 'tv'], enabled: false };

test('Sync: el desactivado es visible, atenuado, con etiqueta, sin Sincronizar/Simulación y con ir a Configuración', { skip }, () => {
  const h = R('Sync', { config: mk({ a: ON, b: OFF }), onGoSettings() {} });
  assert.equal((h.match(/game-disabled/g) || []).length, 1);
  assert.ok(has(h, 'Apagado') && has(h, 'Desactivado'));
  const card = h.slice(h.indexOf('game-disabled'));
  const cardOff = card;
  assert.ok(has(cardOff, 'Ir a Configuración'));
  assert.equal((h.match(/btn primary">Sincronizar/g) || []).length, 1, 'solo el juego activo tiene botón Sincronizar');
  assert.equal((h.match(/Simulación/g) || []).length, 1, 'solo el juego activo tiene Simulación');
  assert.ok(!has(h, 'Todos los juegos están desactivados'));
});

test('Sync: todos desactivados lo dice y no hay botón Sincronizar', { skip }, () => {
  const h = R('Sync', { config: mk({ b: OFF }), onGoSettings() {} });
  assert.ok(has(h, 'Todos los juegos están desactivados') && has(h, 'game-disabled'));
  assert.ok(!has(h, 'btn primary">Sincronizar') && !has(h, 'Simulación'));
  const en = R('Sync', { config: mk({ b: OFF }), onGoSettings() {} }, 'en');
  assert.ok(has(en, 'All games are disabled') && has(en, 'Disabled'));
});

test('Versiones: el juego desactivado sale con sufijo y nota; el activo no', { skip }, () => {
  const h = R('Versions', { config: mk({ a: ON, b: OFF }), onGoSettings() {} });
  assert.ok(has(h, 'Apagado (desactivado)') && has(h, 'Activo</option>'));
  assert.ok(!has(h, 'Activo (desactivado)'));
  const only = R('Versions', { config: mk({ b: OFF }), onGoSettings() {} });
  assert.ok(has(only, 'restaurar solo copia al hub'));
  assert.ok(!has(R('Versions', { config: mk({ a: ON }), onGoSettings() {} }), 'restaurar solo copia'));
  assert.ok(has(R('Versions', { config: mk({ b: OFF }) }, 'en'), 'Apagado (disabled)'));
});

test('WatchSummary: no cuenta los desactivados', { skip }, () => {
  const w = (game) => ({
    game,
    device: 'pc',
    state: 'running',
    since: '2026-01-01T11:00:00Z',
    last_poll: '2026-01-01T11:59:55Z',
    poll: 15,
  });
  const watch = { now: '2026-01-01T12:00:00Z', watches: [w('a'), w('b')] };
  assert.equal(R('WatchSummary', { watch, config: mk({ a: ON, b: OFF }), open: true }).includes('Apagado'), false);
  assert.ok(has(R('WatchSummary', { watch, config: mk({ a: ON, b: OFF }), open: true }), 'Activo'));
  assert.equal(R('WatchSummary', { watch: { ...watch, watches: [w('b')] }, config: mk({ b: OFF }) }), '');
});

test('LauncherBlock: nota «Desactivado: el aviso se omitirá» solo con el juego desactivado', { skip }, () => {
  const g = (o = {}) => ({ sel: 'j-1', id: 'j-1', name: 'J', process: 'j.exe', devices: [{ id: 'pc', name: 'PC' }], ...o });
  const props = (game) => ({
    games: [game],
    active: true,
    defaultHub: 'http://h:1',
    initial: { loaded: true, key: 'ck_abc', status: null },
    now: new Date('2026-11-09T12:00:00Z'),
  });
  const off = R('LauncherBlock', props(g({ enabled: false })));
  assert.ok(has(off, 'Desactivado: el aviso se omitirá.'));
  assert.ok(!has(R('LauncherBlock', props(g({ enabled: true }))), 'el aviso se omitirá'));
  assert.ok(!has(R('LauncherBlock', props(g())), 'el aviso se omitirá'), 'sin el campo cuenta como activo');
  assert.ok(has(R('LauncherBlock', props(g({ enabled: false })), 'en'), 'Disabled: the notice will be skipped.'));
});
