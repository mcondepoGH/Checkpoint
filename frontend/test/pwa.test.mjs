// PWA: decisión de aviso por plataforma, detección, manifest/iconos/index.html coherentes y render del componente.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { detectPlatform, isMobileDevice, installHint, isDismissed, setDismissed, readEnv } from '../src/pwa.js';

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');
const SRC = path.join(ROOT, 'src');
const IPHONE = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148 Safari/604.1';
const ANDROID = 'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 Chrome/120 Mobile Safari/537.36';
const base = { mobile: true, standalone: false, dismissed: false, platform: 'other', hasPrompt: false };

test('detectPlatform: iPhone, iPadOS (Macintosh táctil), Android y escritorio', () => {
  assert.equal(detectPlatform({ userAgent: IPHONE }), 'ios');
  assert.equal(detectPlatform({ userAgent: 'Mozilla/5.0 (Macintosh)', platform: 'MacIntel', maxTouchPoints: 5 }), 'ios');
  assert.equal(detectPlatform({ userAgent: 'Mozilla/5.0 (Macintosh)', platform: 'MacIntel', maxTouchPoints: 0 }), 'other');
  assert.equal(detectPlatform({ userAgent: ANDROID }), 'android');
  assert.equal(detectPlatform({ userAgent: 'Mozilla/5.0 (X11; Linux x86_64)' }), 'other');
  assert.equal(detectPlatform(), 'other');
});

test('isMobileDevice: táctil, o estrecho con UA móvil; escritorio estrecho no', () => {
  assert.equal(isMobileDevice({ coarse: true }), true);
  assert.equal(isMobileDevice({ narrow: true, mobileUa: true }), true);
  assert.equal(isMobileDevice({ narrow: true, platform: 'android' }), true);
  assert.equal(isMobileDevice({ narrow: true }), false);
  assert.equal(isMobileDevice({}), false);
});

test('installHint: plataforma -> mensaje/botón', () => {
  assert.equal(installHint({ ...base, platform: 'android', hasPrompt: true }), 'prompt');
  assert.equal(installHint({ ...base, hasPrompt: true }), 'prompt');
  assert.equal(installHint({ ...base, platform: 'ios' }), 'ios');
  assert.equal(installHint({ ...base, platform: 'android' }), 'none'); // http plano: sin evento no hay nada que ofrecer
  assert.equal(installHint(base), 'none');
});

test('installHint: nada en escritorio, ya instalada o descartada', () => {
  assert.equal(installHint({ ...base, mobile: false, platform: 'ios', hasPrompt: true }), 'none');
  assert.equal(installHint({ ...base, standalone: true, platform: 'ios' }), 'none');
  assert.equal(installHint({ ...base, dismissed: true, platform: 'ios', hasPrompt: true }), 'none');
});

test('descartar se recuerda en storage y un storage roto no lanza', () => {
  const m = new Map();
  const st = { getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, v) };
  assert.equal(isDismissed(st), false);
  setDismissed(st);
  assert.equal(isDismissed(st), true);
  const broken = { getItem() { throw new Error('x'); }, setItem() { throw new Error('x'); } };
  assert.equal(isDismissed(broken), false);
  assert.doesNotThrow(() => setDismissed(broken));
  assert.equal(isDismissed(null), false);
});

test('readEnv: standalone por display-mode o navigator.standalone; sin matchMedia no lanza', () => {
  const win = (mm, nav) => ({ navigator: { userAgent: IPHONE, ...nav }, matchMedia: (q) => ({ matches: mm.includes(q) }) });
  assert.equal(readEnv(win(['(display-mode: standalone)'], {})).standalone, true);
  assert.equal(readEnv(win([], { standalone: true })).standalone, true);
  const e = readEnv(win(['(pointer: coarse)'], {}));
  assert.deepEqual([e.platform, e.mobile, e.standalone], ['ios', true, false]);
  assert.equal(readEnv({ navigator: { userAgent: '' } }).mobile, false);
});

test('manifest, iconos e index.html enlazados y coherentes', () => {
  const man = JSON.parse(fs.readFileSync(path.join(ROOT, 'public', 'manifest.webmanifest'), 'utf8'));
  assert.equal(man.display, 'standalone');
  assert.ok(!man.start_url.startsWith('/') && !man.scope.startsWith('/'), 'rutas relativas');
  assert.ok(man.icons.some((i) => i.sizes === '192x192') && man.icons.some((i) => i.sizes === '512x512' && i.purpose === 'any') && man.icons.some((i) => i.purpose === 'maskable'));
  const png = (f) => fs.readFileSync(path.join(ROOT, 'public', f));
  for (const i of man.icons) {
    const b = png(i.src);
    assert.equal(b.subarray(1, 4).toString(), 'PNG', i.src);
    assert.equal(`${b.readUInt32BE(16)}x${b.readUInt32BE(20)}`, i.sizes, i.src);
  }
  assert.equal(png('apple-touch-icon.png').readUInt32BE(16), 180);
  const html = fs.readFileSync(path.join(ROOT, 'index.html'), 'utf8');
  for (const s of ['rel="manifest"', 'rel="apple-touch-icon"', 'apple-mobile-web-app-capable', 'name="theme-color"']) assert.ok(html.includes(s), s);
  assert.ok(html.includes(`content="${man.theme_color}"`), 'theme-color igual al del manifest');
});

test('service worker: no cachea ni intercepta peticiones', () => {
  const sw = fs.readFileSync(path.join(ROOT, 'public', 'sw.js'), 'utf8');
  assert.ok(!/caches\.|respondWith|cache\.put/.test(sw.replace(/^\/\/.*$/gm, '')));
});

let mod = null;
let skip = false;
try {
  const { build } = await import('esbuild');
  const out = await build({
    stdin: {
      contents: `import React from 'react';
        import { renderToStaticMarkup } from 'react-dom/server';
        import PwaInstall from './components/PwaInstall.jsx';
        export { React, renderToStaticMarkup, PwaInstall };`,
      resolveDir: SRC, loader: 'jsx',
    },
    bundle: true, write: false, format: 'esm', platform: 'node', jsx: 'transform',
    define: { 'process.env.NODE_ENV': '"production"' },
    banner: { js: "import { createRequire } from 'node:module'; const require = createRequire(import.meta.url);" },
    logLevel: 'silent',
  });
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ckpt-pwa-'));
  const file = path.join(dir, 'bundle.mjs');
  fs.writeFileSync(file, out.outputFiles[0].text);
  mod = await import(pathToFileURL(file).href);
  fs.rmSync(dir, { recursive: true, force: true });
} catch (e) {
  skip = `esbuild no disponible: ${e.message}`;
}

test('PwaInstall: en escritorio/servidor (sin window) no pinta nada', { skip }, () => {
  assert.equal(mod.renderToStaticMarkup(mod.React.createElement(mod.PwaInstall)), '');
});

test('PwaInstall: en iPhone pinta Alert info con instrucciones y «Ahora no», sin botón Instalar', { skip }, () => {
  const win = { navigator: { userAgent: IPHONE }, matchMedia: (q) => ({ matches: q === '(pointer: coarse)' }), localStorage: { getItem: () => null, setItem() {} } };
  globalThis.window = win;
  try {
    const html = mod.renderToStaticMarkup(mod.React.createElement(mod.PwaInstall));
    assert.match(html, /class="pwa-install"><div class="alert info"/);
    assert.match(html, /Añadir a pantalla de inicio/);
    assert.match(html, /Ahora no/);
    assert.ok(!html.includes('Instalar</button>'));
    win.localStorage.getItem = () => '1';
    assert.equal(mod.renderToStaticMarkup(mod.React.createElement(mod.PwaInstall)), '');
  } finally { delete globalThis.window; }
});
