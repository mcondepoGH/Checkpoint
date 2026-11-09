// Renderiza GameCard a HTML (react-dom/server): campos secundarios plegados, desplegados y auto-expansión. Usa esbuild, que ya viene con Vite;
// si no está disponible (p. ej. instalación solo de producción) el test se salta.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const SRC = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'src');
let mod = null;
let skip = false;
try {
  const { build } = await import('esbuild');
  const out = await build({
    stdin: {
      contents: `import React from 'react';
        import { renderToStaticMarkup } from 'react-dom/server';
        import GameCard from './components/GameCard.jsx';
        export { React, renderToStaticMarkup, GameCard };`,
      resolveDir: SRC, loader: 'jsx',
    },
    bundle: true, write: false, format: 'esm', platform: 'node', jsx: 'transform',
    define: { 'process.env.NODE_ENV': '"production"' },
    banner: { js: "import { createRequire } from 'node:module'; const require = createRequire(import.meta.url);" },
    logLevel: 'silent',
  });
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ckpt-render-'));
  const file = path.join(dir, 'bundle.mjs');
  fs.writeFileSync(file, out.outputFiles[0].text);
  mod = await import(pathToFileURL(file).href);
  fs.rmSync(dir, { recursive: true, force: true });
} catch (e) {
  skip = `esbuild no disponible: ${e.message}`;
}

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

test('con valor propio en un campo extra: expandido, botón Mostrar menos', { skip }, () => {
  for (const o of [{ process: 'juego.exe' }, { keep: '3' }, { keep: '0' }, { onConflict: 'skip' }]) {
    const h = render({ game: game(o) });
    assert.ok(!more(h)[2], JSON.stringify(o));
    const b = btn(h);
    assert.equal(b[1], 'true');
    assert.equal(b[2], 'Mostrar menos');
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
