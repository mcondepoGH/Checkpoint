// PWA: manifest, iconos e index.html coherentes y service worker sin caché (el hub no muestra botón de instalar).
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');

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
