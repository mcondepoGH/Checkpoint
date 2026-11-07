// Insignia de actualización y ajuste: lógica pura + render a HTML (esbuild, ya incluido con Vite; si no está, se salta).
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { showBadge, safeUrl, updateSummary } from '../src/updates.js';

const SRC = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'src');
const NEW = { actual: '0.4.2', ultima: '0.5.0', hay_actualizacion: true, habilitado: true, notas: 'Novedades <b>x</b>', url: 'https://github.com/o/r/releases/tag/v0.5.0', comprobado_en: '2026-01-01T10:00:00+00:00', error: null };

test('showBadge: solo con actualización y comprobación activa', () => {
  assert.equal(showBadge(NEW), true);
  assert.equal(showBadge({ ...NEW, hay_actualizacion: false }), false);
  assert.equal(showBadge({ ...NEW, habilitado: false }), false);
  assert.equal(showBadge({ ...NEW, error: 'no se pudo comprobar' }), true); // un fallo posterior no oculta lo ya conocido
  assert.equal(showBadge(null), false);
  assert.equal(showBadge(undefined), false);
  assert.equal(showBadge({}), false);
});

test('safeUrl: solo https', () => {
  assert.equal(safeUrl('https://github.com/x'), 'https://github.com/x');
  for (const bad of ['javascript:alert(1)', 'http://x', '', null, undefined, 'data:text/html,x']) assert.equal(safeUrl(bad), null);
});

test('updateSummary: texto del ajuste', () => {
  assert.match(updateSummary({ ...NEW, hay_actualizacion: false }), /al día/i);
  assert.match(updateSummary(NEW), /0\.5\.0/);
  assert.match(updateSummary({ ...NEW, habilitado: false }), /desactivada/i);
  assert.equal(updateSummary(null), '');
});

let mod = null;
let skip = false;
try {
  const { build } = await import('esbuild');
  const out = await build({
    stdin: {
      contents: `import React from 'react';
        import { renderToStaticMarkup } from 'react-dom/server';
        import UpdateBadge from './components/UpdateBadge.jsx';
        import UpdateDialog from './components/UpdateDialog.jsx';
        import UpdateCheck from './components/UpdateCheck.jsx';
        export { React, renderToStaticMarkup, UpdateBadge, UpdateDialog, UpdateCheck };`,
      resolveDir: SRC, loader: 'jsx',
    },
    bundle: true, write: false, format: 'esm', platform: 'node', jsx: 'transform',
    define: { 'process.env.NODE_ENV': '"production"' },
    banner: { js: "import { createRequire } from 'node:module'; const require = createRequire(import.meta.url);" },
    logLevel: 'silent',
  });
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ckpt-upd-'));
  const file = path.join(dir, 'bundle.mjs');
  fs.writeFileSync(file, out.outputFiles[0].text);
  mod = await import(pathToFileURL(file).href);
  fs.rmSync(dir, { recursive: true, force: true });
} catch (e) {
  skip = `esbuild no disponible: ${e.message}`;
}
const r = (C, props) => mod.renderToStaticMarkup(mod.React.createElement(C, props));

test('UpdateBadge visible con actualización', { skip }, () => {
  const h = r(mod.UpdateBadge, { info: NEW, onOpen() {} });
  assert.match(h, /Nueva versión disponible/);
});

test('UpdateBadge oculta sin actualización o desactivada', { skip }, () => {
  assert.equal(r(mod.UpdateBadge, { info: { ...NEW, hay_actualizacion: false }, onOpen() {} }), '');
  assert.equal(r(mod.UpdateBadge, { info: { ...NEW, habilitado: false }, onOpen() {} }), '');
  assert.equal(r(mod.UpdateBadge, { info: null, onOpen() {} }), '');
});

test('UpdateDialog: versiones, notas escapadas, enlace https y sin botón de actualizar', { skip }, () => {
  const h = r(mod.UpdateDialog, { info: NEW, onClose() {} });
  assert.match(h, /0\.4\.2/); assert.match(h, /0\.5\.0/);
  assert.match(h, /&lt;b&gt;x&lt;\/b&gt;/); assert.ok(!h.includes('<b>x</b>'));
  assert.match(h, /href="https:\/\/github\.com\/o\/r\/releases\/tag\/v0\.5\.0"/);
  assert.match(h, /reconstruye la imagen/i);
  const bad = r(mod.UpdateDialog, { info: { ...NEW, url: 'javascript:alert(1)' }, onClose() {} });
  assert.ok(!bad.includes('javascript:'));
});

test('UpdateCheck: ajuste activado/desactivado', { skip }, () => {
  const on = r(mod.UpdateCheck, { info: NEW, onInfo() {} });
  assert.match(on, /Comprobar actualizaciones/); assert.match(on, /checked=""/);
  const off = r(mod.UpdateCheck, { info: { ...NEW, habilitado: false }, onInfo() {} });
  assert.ok(!off.includes('checked=""'));
  assert.ok(!off.includes('Comprobar ahora') || /disabled/.test(off));
});
