// Tabs, CopyBox y el bloque Lanzador de la tarjeta de juego, renderizados a HTML (esbuild + react-dom/server).
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const SRC = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'src');
let m = null;
let skip = false;
try {
  const { build } = await import('esbuild');
  const out = await build({
    stdin: {
      contents: `import React from 'react';
        import { renderToStaticMarkup } from 'react-dom/server';
        import { i18n } from './useI18n.js';
        import LauncherBlock from './components/LauncherBlock.jsx';
        import GameCard from './components/GameCard.jsx';
        import { Tabs, CopyBox } from './components/ui/index.js';
        export { React, renderToStaticMarkup, i18n, LauncherBlock, GameCard, Tabs, CopyBox };`,
      resolveDir: SRC, loader: 'jsx',
    },
    bundle: true, write: false, format: 'esm', platform: 'node', jsx: 'transform',
    define: { 'process.env.NODE_ENV': '"production"' },
    loader: { '.svg': 'dataurl' },
    banner: { js: "import { createRequire } from 'node:module'; const require = createRequire(import.meta.url);" },
    logLevel: 'silent',
  });
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ckpt-launcher-'));
  const file = path.join(dir, 'bundle.mjs');
  fs.writeFileSync(file, out.outputFiles[0].text);
  globalThis.navigator ??= { languages: ['es'], language: 'es' };
  m = await import(pathToFileURL(file).href);
  fs.rmSync(dir, { recursive: true, force: true });
} catch (e) {
  skip = `esbuild no disponible: ${e.message}`;
}
const KEY = 'ck_AbC123xyz';
const has = (h, s) => h.includes(s);
const R = (C, props, lang = 'es') => { m.i18n.setLocale(lang); return m.renderToStaticMarkup(m.React.createElement(m[C], props)); };
const DEVS = [{ id: 'mi-pc', name: 'Mi PC' }, { id: 'deck', name: 'Deck' }];
const game = (o = {}) => ({ id: 'juego-1a2b3c4d', name: 'Juego', process: 'juego.exe', ...o });
const block = (initial, o = {}, lang = 'es') => R('LauncherBlock', { game: game(), devices: DEVS, active: true, defaultHub: 'http://192.168.1.98:8088', initial, now: new Date('2026-11-09T12:00:00Z'), ...o }, lang);
const WITH = { loaded: true, key: KEY };

test('Tabs: roles, aria-selected/controls y roving tabindex', { skip }, () => {
  const h = R('Tabs', { tabs: [{ id: 'a', label: 'A' }, { id: 'b', label: 'B' }], value: 'b', onChange() {}, label: 'Lista' }, 'es');
  const x = m.React.createElement(m.Tabs, { tabs: [{ id: 'a', label: 'A' }, { id: 'b', label: 'B' }], value: 'b', onChange() {}, label: 'Lista' }, 'contenido');
  const html = m.renderToStaticMarkup(x);
  assert.ok(has(html, 'role="tablist"') && has(html, 'aria-label="Lista"') && has(html, 'role="tabpanel"') && has(html, 'contenido'));
  assert.match(html, /<button[^>]*role="tab"[^>]*class="uitab"[^>]*aria-selected="false"[^>]*tabindex="-1"[^>]*>A</);
  assert.match(html, /<button[^>]*role="tab"[^>]*class="uitab active"[^>]*aria-selected="true"[^>]*tabindex="0"[^>]*>B</);
  const panel = /<div class="uitabs-panel" role="tabpanel" id="([^"]+)" aria-labelledby="([^"]+)"/.exec(html);
  assert.ok(panel && has(html, `aria-controls="${panel[1]}"`) && has(html, `id="${panel[2]}"`));
  assert.ok(h.length > 0);
});

test('CopyBox: caja de solo lectura + botón de icono con aria-label; copiado = check', { skip }, () => {
  const h = R('CopyBox', { value: 'curl -X POST "x"', label: 'Comando' });
  assert.ok(has(h, 'class="copybox"') && has(h, 'class="copybox-field"') && has(h, 'role="textbox"') && has(h, 'aria-readonly="true"') && has(h, 'aria-label="Comando"'));
  assert.ok(has(h, 'curl -X POST &quot;x&quot;'));
  assert.match(h, /<button[^>]*class="btn btn-icon copybox-copy"[^>]*aria-label="Copiar"/);
  assert.ok(has(h, 'M9 9h11') && !has(h, 'M20 6 9 17l-5-5'));
  const c = R('CopyBox', { value: 'x', label: 'C', initialCopied: true });
  assert.match(c, /aria-label="Copiado"/);
  assert.ok(has(c, 'M20 6 9 17l-5-5') && has(c, 'role="status"'));
});

test('Lanzador con key: pestañas, selector de dispositivo, URL y comando Steam con %command%', { skip }, () => {
  const h = block(WITH, {}, 'es');
  for (const l of ['Steam / Steam Deck', 'Lutris', 'Heroic (sin verificar)', 'Windows (Playnite)']) assert.ok(has(h, `>${l}</button>`), l);
  assert.ok(has(h, 'Opciones de lanzamiento') && has(h, 'El cierre lo vigila el hub solo'));
  assert.ok(has(h, 'Mi PC') && has(h, 'Deck') && has(h, 'Dispositivo del lanzador') && has(h, 'URL del hub'));
  assert.ok(has(h, `Bearer ${KEY}`) && has(h, 'http://192.168.1.98:8088/api/hook/juego-1a2b3c4d/opened?device=mi-pc') && has(h, '; %command%'));
  assert.equal(h.split(KEY).length - 1, 1);
  assert.ok(has(h, 'Copiar'));
});

test('Lanzador: sin key -> aviso informativo y ningún comando ni placeholder', { skip }, () => {
  const h = block({ loaded: true, key: null });
  assert.ok(has(h, 'Genera primero la API key en tu perfil.') && !has(h, 'curl') && !has(h, 'copybox') && !has(h, 'Bearer'));
  assert.ok(has(block({ loaded: true, key: null }, {}, 'en'), 'Generate the API key in your profile first.'));
});

test('Lanzador: sin process -> aviso; con process no', { skip }, () => {
  const h = block(WITH, { game: game({ process: '' }) });
  assert.ok(has(h, '<code>process</code>') && has(h, 'el hub no podrá vigilar el cierre') && has(h, 'class="alert warn compact"'));
  assert.ok(!has(block(WITH), 'no podrá vigilar'));
  assert.ok(has(block(WITH, { game: game({ process: '  ' }) }), 'no podrá vigilar'));
});

test('Lanzador: juego sin guardar o sin dispositivos no muestra comandos', { skip }, () => {
  assert.ok(has(block(WITH, { game: game({ id: '' }) }), 'Guarda el juego para obtener sus comandos.'));
  const h = block(WITH, { devices: [] });
  assert.ok(has(h, 'Elige los dispositivos') && !has(h, 'curl'));
});

test('Lanzador: cargando y error de API', { skip }, () => {
  assert.ok(has(block({ loaded: false }), 'role="status"'));
  assert.ok(has(block({ loaded: true, error: { code: 'err.main.origin_forbidden', params: {} } }), 'role="alert"'));
});

test('Último aviso por dispositivo: tipo, hace cuánto, resultado y vigilancia', { skip }, () => {
  const status = { devices: [
    { device: 'mi-pc', last: { trigger: 'hook', at: '2026-11-09T11:57:00Z', outcome: 'ok' }, watching: { state: 'running', since: '2026-11-09T11:57:05Z' } },
    { device: 'deck', last: null, watching: null },
  ] };
  const h = block({ ...WITH, status });
  assert.ok(has(h, 'Último aviso') && has(h, 'Mi PC: Aviso del juego, hace 3 minutos, correcta · vigilando: juego abierto'), h);
  assert.ok(has(h, 'Deck: sin avisos todavía'));
  const c = block({ ...WITH, status: { devices: [{ device: 'deck', last: { trigger: 'hook_closed', at: '2026-11-09T11:59:00Z', outcome: 'conflict' }, watching: { state: 'settling', since: 'x' } }] } });
  assert.ok(has(c, 'Deck: Cierre del juego, hace 1 minuto') && has(c, 'cerrado, a punto de sincronizar'), c);
  const e = block({ ...WITH, status }, {}, 'en');
  assert.ok(has(e, 'Last notice') && has(e, 'Mi PC: Game opened, 3 minutes ago') && has(e, 'watching: game open'), e);
});

test('GameCard: el bloque Lanzador está dentro del área plegable (plegada por defecto)', { skip }, () => {
  m.i18n.setLocale('es');
  const g = { key: 'g1', id: 'juego-1a2b3c4d', name: 'Juego', a: 'd1', b: 'd2', pathA: '/a', pathB: '/b', process: '', keep: '', onConflict: '' };
  const h = m.renderToStaticMarkup(m.React.createElement(m.GameCard, {
    game: g, devices: [{ key: 'd1', name: 'PC' }, { key: 'd2', name: 'Deck' }], errors: {}, globalMax: 20, nameA: 'PC', nameB: 'Deck',
    idA: 'pc', idB: 'deck', idText: 'juego-1a2b3c4d', renamed: false, onChange() {}, onRemove() {},
  }));
  const more = /<div id="[^"]+" class="cfg-more" hidden="">([\s\S]*?)<\/div><div class="row between">/.exec(h);
  assert.ok(more && has(more[1], 'class="launcher"') && has(more[1], 'Lanzador'), h);
});
