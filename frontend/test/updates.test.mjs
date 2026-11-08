// Insignia de actualización y ajuste: lógica pura + render a HTML (esbuild, ya incluido con Vite; si no está, se salta).
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { updatesApplicable, showBadge, safeUrl, updateSummary, channelOf, isPrerelease, installedVersion, CHANNEL_OPTIONS } from '../src/updates.js';

import { createI18n } from '../src/i18n.js';
const es = JSON.parse(fs.readFileSync(new URL('../src/locales/es.json', import.meta.url), 'utf8'));
const t = createI18n({ catalogs: { es }, storage: null, languages: ['es'] }).t;

const SRC = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'src');
const NEW = { actual: '0.4.2', ultima: '0.5.0', hay_actualizacion: true, habilitado: true, notas: 'Novedades <b>x</b>', url: 'https://github.com/o/r/releases/tag/v0.5.0', comprobado_en: '2026-01-01T10:00:00+00:00', error: null, canal: 'stable', prerelease: false };
const PRE = { ...NEW, canal: 'beta', ultima: '0.6.0-rc.1', prerelease: true };

test('showBadge: solo con actualización y comprobación activa', () => {
  assert.equal(showBadge(NEW), true);
  assert.equal(showBadge({ ...NEW, hay_actualizacion: false }), false);
  assert.equal(showBadge({ ...NEW, habilitado: false }), false);
  assert.equal(showBadge({ ...NEW, error: 'no se pudo comprobar' }), true); // un fallo posterior no oculta lo ya conocido
  assert.equal(showBadge(null), false);
  assert.equal(showBadge(undefined), false);
  assert.equal(showBadge({}), false);
});

test('aplicable false (Docker): sin insignia ni tarjeta; null = aún sin respuesta', () => {
  const NA = { ...NEW, aplicable: false };
  assert.equal(showBadge(NA), false);
  assert.equal(showBadge({ ...NEW, aplicable: true }), true);
  assert.equal(updatesApplicable(NA), false);
  assert.equal(updatesApplicable(null), false);       // sin respuesta: oculto, sin parpadeo
  assert.equal(updatesApplicable(NEW), true);          // backend sin el campo: se trata como aplicable
  assert.equal(updatesApplicable({ ...NEW, aplicable: true }), true);
});

test('safeUrl: solo https', () => {
  assert.equal(safeUrl('https://github.com/x'), 'https://github.com/x');
  for (const bad of ['javascript:alert(1)', 'http://x', '', null, undefined, 'data:text/html,x']) assert.equal(safeUrl(bad), null);
});

test('updateSummary: texto del ajuste', () => {
  assert.match(updateSummary({ ...NEW, hay_actualizacion: false }, t), /al día/i);
  assert.match(updateSummary(NEW, t), /0\.5\.0/);
  assert.match(updateSummary({ ...NEW, habilitado: false }, t), /desactivada/i);
  assert.equal(updateSummary(null, t), '');
});

test('canal y marca preliminar: lógica pura', () => {
  assert.equal(channelOf(NEW), 'stable'); assert.equal(channelOf(PRE), 'beta');
  for (const x of [null, {}, { canal: 'raro' }]) assert.equal(channelOf(x), 'stable');
  assert.equal(isPrerelease(PRE), true); assert.equal(isPrerelease(NEW), false); assert.equal(isPrerelease(null), false);
  assert.equal(isPrerelease({ prerelease: 'true' }), false);
  assert.equal(installedVersion(NEW), NEW.actual); assert.equal(installedVersion({ actual: 'desconocida' }), '');
  assert.equal(installedVersion(null), ''); assert.equal(installedVersion({}), '');
  assert.deepEqual(CHANNEL_OPTIONS.map((o) => o.value), ['stable', 'beta']);
  assert.match(updateSummary(PRE, t), /preliminar/); assert.ok(!/preliminar/.test(updateSummary(NEW, t)));
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
  assert.match(h, /recompila la web/i);
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

test('UpdateCheck: selector de canal con aviso de versiones preliminares', { skip }, () => {
  const h = r(mod.UpdateCheck, { info: NEW, onInfo() {} });
  assert.match(h, /<select[^>]*id="update-channel"/);
  assert.match(h, /<option value="stable" selected="">Estable<\/option>/);
  assert.match(h, /<option value="beta">Pruebas<\/option>/);
  assert.match(h, /versiones preliminares, que pueden fallar/);
  const b = r(mod.UpdateCheck, { info: PRE, onInfo() {} });
  assert.match(b, /<option value="beta" selected="">Pruebas<\/option>/);
  assert.match(r(mod.UpdateCheck, { info: null, onInfo() {} }), /<option value="stable" selected="">/);
  const off = r(mod.UpdateCheck, { info: { ...NEW, habilitado: false }, onInfo() {} });
  assert.match(off, /<select[^>]*disabled/);
});

test('UpdateBadge y UpdateDialog marcan «preliminar» solo cuando aplica', { skip }, () => {
  const bp = r(mod.UpdateBadge, { info: PRE, onOpen() {} });
  assert.match(bp, /preliminar/); assert.match(bp, /0\.6\.0-rc\.1/);
  assert.ok(!/preliminar/.test(r(mod.UpdateBadge, { info: NEW, onOpen() {} })));
  const dp = r(mod.UpdateDialog, { info: PRE, onClose() {} });
  assert.match(dp, /pre-tag/); assert.match(dp, /puede fallar/);
  const dn = r(mod.UpdateDialog, { info: NEW, onClose() {} });
  assert.ok(!/preliminar/.test(dn));
});

test('aplicable false: UpdateBadge y UpdateCheck no pintan nada', { skip }, () => {
  const NA = { ...NEW, aplicable: false, habilitado: false };
  assert.equal(r(mod.UpdateBadge, { info: { ...NEW, aplicable: false }, onOpen() {} }), '');
  assert.equal(r(mod.UpdateCheck, { info: NA, onInfo() {} }), '');
  assert.match(r(mod.UpdateCheck, { info: { ...NEW, aplicable: true }, onInfo() {} }), /Comprobar actualizaciones/);
});
