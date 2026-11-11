// Renderiza GameCard a HTML (react-dom/server): campos secundarios plegados y auto-expansión solo por error. Usa esbuild, que ya viene con Vite;
// si no está disponible (p. ej. instalación solo de producción) el test se salta.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { bundle, SRC } from '../../helpers/bundle.mjs';

const { mod, skip } = await bundle(`import React from 'react';
  import { renderToStaticMarkup } from 'react-dom/server';
  import GameCard from '#src/components/config/GameCard.jsx';
  export { React, renderToStaticMarkup, GameCard };`, { tag: 'ckpt-render' });

const game = (o = {}) => ({ key: 'g1', id: 'juego-1a2b3c4d', salt: 'a', name: 'Juego', a: 'd1', b: 'd2', pathA: '/a', pathB: '/b', process: '', keep: '', onConflict: '', ...o });
const render = (props) => mod.renderToStaticMarkup(mod.React.createElement(mod.GameCard, {
  game: game(), devices: [{ key: 'd1', name: 'PC' }, { key: 'd2', name: 'Deck' }], errors: {}, globalMax: 20,
  nameA: 'PC', nameB: 'Deck', idA: 'pc', idB: 'deck', idText: 'juego-1a2b3c4d', renamed: false, onChange() {}, onRemove() {}, ...props,
}));
const has = (h, s) => h.includes(s);
// Marcado del contenedor de campos extra y de su botón.
const more = (h) => /<div id="([^"]+)" class="cfg-more"( hidden="")?>/.exec(h);
const btn = (h) => /<button[^>]*aria-expanded="(true|false)"[^>]*>([^<]*)<\/button>/.exec(h);

test('por defecto plegado: extras con hidden, botón Mostrar más con aria-expanded/controls', { skip }, () => {
  const h = render({});
  const m = more(h);
  assert.ok(m && m[2], 'contenedor extra con hidden');
  assert.ok(has(h, `aria-controls="${m[1]}"`));
  const b = btn(h);
  assert.equal(b[1], 'false');
  assert.equal(b[2], 'Mostrar más');
  assert.ok(has(h, 'Ruta del save en PC') && has(h, 'Ruta del save en Deck') && has(h, 'Eliminar'));
  assert.ok(has(h, 'Máx. de versiones') && !has(h, 'este juego)'));
});

test('con valor propio en un campo extra: sigue plegado, botón Mostrar más', { skip }, () => {
  for (const o of [{ process: 'juego.exe' }, { keep: '3' }, { keep: '0' }, { onConflict: 'skip' }]) {
    const h = render({ game: game(o) });
    assert.ok(more(h)[2], JSON.stringify(o));
    const b = btn(h);
    assert.equal(b[1], 'false');
    assert.equal(b[2], 'Mostrar más');
  }
});

test('con error en un campo extra: expandido; error en campos visibles no expande', { skip }, () => {
  for (const p of [{ errors: { process: 'mal' } }, { errors: { keep_versions: 'mal' } }, { errors: { on_conflict: 'mal' } }, { keepError: 'mal' }]) {
    const h = render({ errors: {}, ...p });
    assert.ok(!more(h)[2], JSON.stringify(p));
    assert.equal(btn(h)[1], 'true');
  }
  const h = render({ errors: { name: 'mal', 'devices.0': 'mal' }, localError: 'mal' });
  assert.ok(more(h)[2]);
});

test('dispositivo 2 opcional: con b vacío sale la ayuda de solo checkpoint y no la ruta B; con b no', { skip }, () => {
  const solo = render({ game: game({ b: '', pathB: '' }) });
  assert.ok(has(solo, 'Con un solo dispositivo, el hub guarda versiones') && has(solo, 'ninguno (solo checkpoint)'));
  assert.ok(has(solo, 'Ruta del save en PC') && !has(solo, 'Ruta del save en Deck'));
  const dos = render({});
  assert.ok(!has(dos, 'Con un solo dispositivo') && has(dos, 'Ruta del save en Deck'));
});

test('etiqueta Solo checkpoint (Pill info): icono + texto y title de ayuda', { skip }, () => {
  const src = fs.readFileSync(path.join(SRC, 'components/ui/Pill.jsx'), 'utf8');
  assert.match(src, /tone/);
  const css = fs.readFileSync(path.join(SRC, 'components/ui/_pill.scss'), 'utf8');
  assert.match(css, /&\.info/);
  assert.ok(!/font-size:\s*[\d.]+(px|rem)/.test(css.split('&.info')[1].split('\n')[0]), 'sin font-size suelto');
});

test('juego desactivado: interruptor visible sin desplegar, tarjeta atenuada y etiqueta Desactivado', { skip }, () => {
  const on = render({});
  assert.ok(has(on, 'role="switch"') && has(on, 'Juego activo') && has(on, 'checked=""'));
  assert.ok(!has(on, 'cfg-card-disabled') && !has(on, 'cfg-tag'));
  const off = render({ game: game({ enabled: false }) });
  assert.ok(has(off, 'cfg-card-disabled') && has(off, 'class="cfg-tag">Desactivado<'));
  assert.ok(has(off, 'role="switch"') && !has(off, 'checked=""'));
  assert.ok(has(off, 'No se sincroniza') || has(off, 'Desactivado: no se sincroniza'));
  // el interruptor queda fuera del contenedor plegado de campos extra
  const sw = off.indexOf('role="switch"');
  assert.ok(sw < off.indexOf('class="cfg-more"'));
});

test('juego sin el campo enabled (borradores antiguos) cuenta como activo', { skip }, () => {
  const h = render({ game: game() });
  assert.ok(has(h, 'checked=""') && !has(h, 'cfg-card-disabled'));
});
