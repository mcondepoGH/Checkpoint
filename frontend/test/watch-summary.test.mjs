// Contador de vigilancia en la cabecera (WatchSummary), punto/entrada de actualización en el perfil y consulta compartida.
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
        import WatchSummary from './components/WatchSummary.jsx';
        import ProfileMenu from './components/ProfileMenu.jsx';
        import { watchState, NO_WATCHES } from './useWatches.js';
        export { React, renderToStaticMarkup, i18n, WatchSummary, ProfileMenu, watchState, NO_WATCHES };`,
      resolveDir: SRC, loader: 'jsx',
    },
    bundle: true, write: false, format: 'esm', platform: 'node', jsx: 'transform',
    define: { 'process.env.NODE_ENV': '"production"' },
    loader: { '.svg': 'dataurl' },
    banner: { js: "import { createRequire } from 'node:module'; const require = createRequire(import.meta.url);" },
    logLevel: 'silent',
  });
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ckpt-watchsum-'));
  const file = path.join(dir, 'bundle.mjs');
  fs.writeFileSync(file, out.outputFiles[0].text);
  globalThis.navigator ??= { languages: ['es'], language: 'es' };
  m = await import(pathToFileURL(file).href);
  fs.rmSync(dir, { recursive: true, force: true });
} catch (e) {
  skip = `esbuild no disponible: ${e.message}`;
}
const has = (h, s) => h.includes(s);
const NOW = '2026-01-01T12:00:00Z';
const CONFIG = { devices: { pc: { name: 'Mi PC' } }, games: { a: { name: 'Juego A' }, b: { name: 'Juego B' } } };
const W = (o = {}) => ({ game: 'a', device: 'pc', state: 'running', since: '2026-01-01T11:00:00Z', last_poll: '2026-01-01T11:59:55Z', poll: 15, ...o });
const summary = (watches, o = {}, lang = 'es') => {
  m.i18n.setLocale(lang);
  return m.renderToStaticMarkup(m.React.createElement(m.WatchSummary, { watch: { now: NOW, watches }, config: CONFIG, ...o }));
};
const UPD = { actual: '1.0.0', ultima: '1.1.0', hay_actualizacion: true, habilitado: true, aplicable: true };
const menu = (o = {}, lang = 'es') => {
  m.i18n.setLocale(lang);
  return m.renderToStaticMarkup(m.React.createElement(m.ProfileMenu, {
    profile: { name: 'admin', photo: null }, version: '1.0.0', theme: 'auto', effectiveTheme: 'dark', onCycleTheme() {}, onLogout() {}, onPhoto() {}, ...o,
  }));
};

test('sin vigilancia no pinta nada (ni con lista vacía ni con juegos que ya no existen)', { skip }, () => {
  assert.equal(summary([]), '');
  assert.equal(summary([W({ game: 'borrado' })]), '');
});

test('chip en la cabecera: punto, número, texto completo en aria-label y desplegable cerrado', { skip }, () => {
  const h = summary([W(), W({ game: 'b' })]);
  assert.ok(has(h, 'class="watch-summary"') && has(h, 'class="watch-toggle"'));
  assert.ok(has(h, 'aria-label="2 juegos en vigilancia"') && has(h, 'aria-expanded="false"'));
  assert.ok(has(h, 'watch-chip-dot') && has(h, '<b class="watch-num" aria-hidden="true">2</b>'));
  assert.ok(has(h, '<span class="watch-lbl" aria-hidden="true">Vigilando · 2</span>') && has(summary([W()], {}, 'en'), 'Watching · 1</span>'));
  assert.ok(has(summary([W()]), 'Vigilando · 1</span>') && !has(summary([W()]), 'juego en vigilancia</span>'));
  assert.ok(!has(h, 'watch-list'));
  assert.ok(has(summary([W()]), 'aria-label="1 juego en vigilancia"'));
  assert.ok(has(summary([W()], {}, 'en'), 'aria-label="1 game being watched"'));
});

test('contador cuenta juegos, no vigilancias, y 99+ por encima de 99', { skip }, () => {
  const games = {};
  for (let i = 0; i < 100; i++) games[`g${i}`] = { name: `G${i}` };
  const h = summary(Object.keys(games).map((g) => W({ game: g })), { config: { devices: CONFIG.devices, games } });
  assert.ok(has(h, '>99+</b>') && has(h, 'Vigilando · 99+</span>') && has(h, 'aria-label="100 juegos en vigilancia"'));
  assert.ok(has(summary([W({ device: 'x' }), W()]), 'aria-label="1 juego en vigilancia"'));
});

test('lista abierta: juego, dispositivo y estado con WatchStatus; aria-controls enlaza la lista', { skip }, () => {
  const h = summary([W(), W({ game: 'b', state: 'waiting' })], { open: true });
  const id = /aria-controls="([^"]+)"/.exec(h)?.[1];
  assert.ok(id && has(h, `id="${id}"`) && has(h, 'aria-expanded="true"') && has(h, 'aria-label="Juegos en vigilancia"'));
  assert.ok(has(h, 'Juego A') && has(h, 'Mi PC') && has(h, 'class="watch running"') && has(h, 'Jugando'));
  assert.ok(has(h, 'class="watch waiting"') && has(h, 'Esperando'));
});

test('sin latido se pinta como stale en la lista', { skip }, () => {
  const h = summary([W({ last_poll: '2026-01-01T11:00:00Z' })], { open: true });
  assert.ok(has(h, 'class="watch stale"') && has(h, 'Sin latido'));
});

test('perfil con actualización: punto accesible en el avatar y entrada «Actualizar a vX.Y.Z»', { skip }, () => {
  const closed = menu({ updates: UPD });
  assert.ok(has(closed, 'class="upd-dot"') && has(closed, 'role="img"') && has(closed, 'aria-label="Hay una actualización disponible"'));
  assert.ok(has(closed, 'aria-label="Perfil y opciones (hay una actualización disponible)"'));
  const open = menu({ updates: UPD, open: true });
  assert.ok(has(open, 'profile-update') && has(open, 'Actualizar a v1.1.0'));
  const en = menu({ updates: UPD, open: true }, 'en');
  assert.ok(has(en, 'Update to v1.1.0') && has(en, 'aria-label="An update is available"'));
});

test('perfil sin aviso: ni punto ni entrada (sin actualización, desactivada, no aplicable o sin datos)', { skip }, () => {
  for (const updates of [null, { ...UPD, hay_actualizacion: false }, { ...UPD, habilitado: false }, { ...UPD, aplicable: false }, undefined]) {
    const h = menu({ updates, open: true });
    assert.ok(!has(h, 'upd-dot') && !has(h, 'profile-update') && has(h, 'aria-label="Perfil y opciones"'), JSON.stringify(updates));
  }
});

test('watchState tolera respuestas raras', { skip }, () => {
  assert.deepEqual(m.watchState({ now: NOW, watches: [W()] }), { now: NOW, watches: [W()] });
  assert.deepEqual(m.watchState(null), m.NO_WATCHES);
  assert.deepEqual(m.watchState({ watches: 'x' }), m.NO_WATCHES);
});

test('App: el chip va en la barra superior y hay una sola consulta de vigilancia', () => {
  const app = fs.readFileSync(path.join(SRC, 'App.jsx'), 'utf8');
  const header = /<header className="topbar">[\s\S]*<\/header>/.exec(app)?.[0] || '';
  assert.ok(header.includes('<WatchSummary') && header.includes('<UpdateBadge') && header.includes('<ProfileMenu'));
  assert.ok(header.indexOf('<WatchSummary') < header.indexOf('<ProfileMenu'));
  assert.equal(app.split('useWatches(').length - 1, 1);
  assert.ok(/<Sync [^>]*watch=\{watch\}/.test(app));
  assert.ok(/onUpdate=\{\(\) => setShowUpdate\(true\)\}/.test(app));
  const sync = fs.readFileSync(path.join(SRC, 'pages', 'Sync.jsx'), 'utf8');
  assert.ok(!sync.includes('/api/watches') && !sync.includes('watch-summary'));
});

test('cadenas de vigilancia y de actualización del perfil resueltas en es y en (no quedan claves a la vista)', () => {
  for (const lang of ['es', 'en']) {
    const j = JSON.parse(fs.readFileSync(path.join(SRC, 'locales', `${lang}.json`), 'utf8'));
    assert.ok(j.sync.watch.chip.includes('{count}') && j.sync.watch.count.one && j.sync.watch.count.other && j.sync.watch.listAria && j.sync.watch.bar.stale && j.sync.watch.short.running && j.sync.watch.since, lang);
    assert.ok(j.profile.openUpdate && j.profile.updateDot && j.profile.update.includes('{version}'), lang);
  }
});

test('SCSS: puntos y anillo del pulso son cuadrados explícitos (círculo, no óvalo) y el pulso respeta reduced-motion', () => {
  const css = (f) => fs.readFileSync(path.join(SRC, 'styles', f), 'utf8');
  const watch = css('ui/_watch.scss');
  const rule = (sel) => new RegExp(`${sel.replace(/[.]/g, '\\.')} \\{([^}]*)\\}`).exec(watch)?.[1] || '';
  for (const sel of ['.watch-ico', '.watch-dot', '.watch-chip-dot']) {
    const r = rule(sel);
    assert.ok(/aspect-ratio: 1/.test(r) && /border-radius: 50%/.test(r) && /flex: 0 0 auto/.test(r) && /align-self: center/.test(r), sel);
    const [w, h] = [/width: ([^;]+);/.exec(r)?.[1], /height: ([^;]+);/.exec(r)?.[1]];
    assert.ok(w && w === h, `${sel} ${w} x ${h}`);
    assert.ok(!/overflow/.test(r), sel);
  }
  assert.ok(/aspect-ratio: 1; border-radius: 50%/.test(css('_profile.scss').split('\n').find((l) => l.startsWith('.upd-dot'))));
  const pulse = /@keyframes watch-pulse \{([^@]*)\}\s*@keyframes/.exec(watch)?.[1] || '';
  assert.ok(pulse.includes('box-shadow') && !/transform|width|height|scale/.test(pulse));
  assert.ok(/prefers-reduced-motion: reduce\) \{[^}]*\.watch-ico[^}]*\.watch-chip-dot[^}]*animation: none/.test(watch));
});
