// Componentes de UI compartidos (src/components/ui) renderizados a HTML: clases, atributos y valores por defecto.
// Usa esbuild, que ya viene con Vite; si no está disponible el test se salta.
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
        import * as ui from './components/ui/index.js';
        export { React, renderToStaticMarkup, ui };`,
      resolveDir: SRC, loader: 'jsx',
    },
    bundle: true, write: false, format: 'esm', platform: 'node', jsx: 'transform',
    define: { 'process.env.NODE_ENV': '"production"' },
    banner: { js: "import { createRequire } from 'node:module'; const require = createRequire(import.meta.url);" },
    logLevel: 'silent',
  });
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ckpt-ui-'));
  const file = path.join(dir, 'bundle.mjs');
  fs.writeFileSync(file, out.outputFiles[0].text);
  mod = await import(pathToFileURL(file).href);
  fs.rmSync(dir, { recursive: true, force: true });
} catch (e) {
  skip = `esbuild no disponible: ${e.message}`;
}

const r = (C, props, ...kids) => mod.renderToStaticMarkup(mod.React.createElement(mod.ui[C], props, ...kids));

test('Button: clases por variante, type=button por defecto y submit explícito', { skip }, () => {
  assert.equal(r('Button', null, 'x'), '<button type="button" class="btn">x</button>');
  assert.match(r('Button', { variant: 'primary' }, 'x'), /class="btn primary"/);
  assert.match(r('Button', { variant: 'ghost', className: 'tool' }, 'x'), /class="btn ghost tool"/);
  assert.match(r('Button', { variant: 'danger', disabled: true }, 'x'), /class="btn danger"[^>]*disabled/);
  assert.match(r('Button', { type: 'submit' }, 'x'), /type="submit"/);  assert.match(r('Button', { variant: 'ghost', iconOnly: true }, 'x'), /class="btn ghost btn-icon"/);
});

test('Button iconOnly: .btn-icon va anidada en .btn (partial del botón), no suelta antes de ella', () => {
  const scss = fs.readFileSync(path.join(SRC, 'styles', 'ui', '_button.scss'), 'utf8');
  assert.match(scss, /&\.btn-icon\s*\{[^}]*padding: 0/);
  assert.ok(!/^\.btn-icon/m.test(fs.readFileSync(path.join(SRC, 'styles', '_components.scss'), 'utf8')));
});

test('Button iconOnly: borde transparente en reposo, cuadro en hover/focus-visible/active, icono a $icon-btn (1.25rem)', () => {
  const scss = fs.readFileSync(path.join(SRC, 'styles', 'ui', '_button.scss'), 'utf8');
  const block = scss.slice(scss.indexOf('&.btn-icon'));
  assert.match(block, /border-color: transparent; background: transparent/);
  assert.match(block, /&:focus-visible/);
  assert.match(block, /&:hover:not\(:disabled\)/);
  assert.match(block, /width: v\.\$icon-btn; height: v\.\$icon-btn/);
  assert.match(fs.readFileSync(path.join(SRC, 'styles', '_variables.scss'), 'utf8'), /\$icon-btn: 1\.25rem/);
});

test('Badge: estado como clase; sin estado queda neutra', { skip }, () => {
  assert.equal(r('Badge', { status: 'running' }, 'x'), '<span class="badge running">x</span>');
  assert.equal(r('Badge', { status: '' }, 'x'), '<span class="badge">x</span>');
  assert.equal(r('Badge', { status: 'dry-run' }, 'x'), '<span class="badge dry-run">x</span>');
});

test('Alert: variante, inline, etiqueta y atributos', { skip }, () => {
  assert.equal(r('Alert', { variant: 'error', role: 'alert' }, 'x'), '<div class="alert error" role="alert">x</div>');
  assert.equal(r('Alert', { variant: 'ok', inline: true, as: 'span' }, 'x'), '<span class="alert ok inline">x</span>');
  assert.equal(r('Alert', null, 'x'), '<div class="alert">x</div>');
});

test('Pill: normal y resaltada', { skip }, () => {
  assert.equal(r('Pill', null, 'x'), '<span class="pill">x</span>');
  assert.equal(r('Pill', { highlight: true }, 'x'), '<span class="pill win">x</span>');
});

test('Select: opciones, placeholder vacío y props al select', { skip }, () => {
  const html = r('Select', { id: 's', value: 'b', onChange() {}, placeholder: 'Elige', options: [{ value: 'a', label: 'A' }, { value: 'b', label: 'B' }] });
  assert.match(html, /^<select id="s">/);
  assert.match(html, /<option value="">Elige<\/option><option value="a">A<\/option><option value="b" selected="">B<\/option>/);
  assert.doesNotMatch(r('Select', { options: [{ value: 'a', label: 'A' }] }), /value=""/);
});

test('Checkbox y Switch: etiqueta, role y props al input', { skip }, () => {
  const c = r('Checkbox', { checked: true, onChange() {}, 'aria-describedby': 'h', label: 'Texto' });
  assert.match(c, /^<label class="check"><input type="checkbox"/);
  assert.match(c, /aria-describedby="h"/);
  assert.match(c, /<span>Texto<\/span><\/label>$/);
  const s = r('Switch', { checked: false, onChange() {}, disabled: true, label: 'No' });
  assert.match(s, /^<label class="switch"><input type="checkbox" role="switch"/);
  assert.match(s, /disabled/);
  assert.match(s, /<span class="track" aria-hidden="true"><i><\/i><\/span><span>No<\/span>/);
});

test('Input: texto sin autocompletar ni corrector; number y password sin añadidos; lo explícito manda', { skip }, () => {
  const t = r('Input', { value: 'x', onChange() {} });
  assert.match(t, /autocomplete="off"/i);
  assert.match(t, /spellcheck="false"/i);
  const n = r('Input', { type: 'number', inputMode: 'numeric', value: '1', onChange() {} });
  assert.doesNotMatch(n, /autocomplete|spellcheck/);
  assert.match(n, /type="number"/);
  assert.match(r('Input', { autoComplete: 'username', value: '', onChange() {} }), /autocomplete="username"/i);
  assert.doesNotMatch(r('Input', { type: 'password', value: '', onChange() {} }), /spellcheck/);
});
test('Alert compact', { skip }, () => { assert.equal(r('Alert', { variant: 'warn', compact: true }, 'x'), '<div class="alert warn compact">x</div>'); });
