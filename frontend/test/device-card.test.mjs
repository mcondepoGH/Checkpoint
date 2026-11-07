// Renderiza DeviceCard a HTML (react-dom/server) en modo nativo y Docker. Usa esbuild, que ya viene con Vite;
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
        import DeviceCard from './components/DeviceCard.jsx';
        export { React, renderToStaticMarkup, DeviceCard };`,
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

const dev = (o = {}) => ({ key: 'k1', id: 'pc-1a2b3c4d', name: 'PC', orig: 'PC', local: false, host: '192.0.2.5', port: '22', user: 'usuario', os: 'linux', ...o });
const render = (props) => mod.renderToStaticMarkup(mod.React.createElement(mod.DeviceCard, {
  dev: dev(), errors: {}, idText: 'pc-1a2b3c4d', renamed: false, onChange() {}, onTest() {}, onRemove() {},
  runtime: 'native', platform: 'linux', canLocal: true, ...props,
}));
const has = (html, s) => html.includes(s);

test('native, remoto: casilla «Este equipo» visible y campos SSH presentes', { skip }, () => {
  const h = render({});
  assert.ok(has(h, 'Este equipo') && has(h, 'type="checkbox"'));
  assert.ok(has(h, 'Host / IP') && has(h, 'Puerto') && has(h, 'Usuario'));
  assert.ok(has(h, 'Probar conexión') && !has(h, 'Comprobar carpeta'));
  assert.ok(!has(h, 'checked'));
});

test('native, local: oculta host/usuario/puerto, ofrece «Comprobar carpeta» y muestra ayuda', { skip }, () => {
  const h = render({ dev: dev({ local: true }) });
  assert.ok(has(h, 'checked'));
  assert.ok(!has(h, 'Host / IP') && !has(h, 'Puerto') && !has(h, 'Usuario'));
  assert.ok(!has(h, '192.0.2.5')); // el valor oculto no se pinta
  assert.ok(has(h, 'Comprobar carpeta') && !has(h, 'Probar conexión'));
  assert.ok(has(h, 'sin SSH') && has(h, 'Sistema operativo'));
  assert.ok(has(h, 'ID interno'));
});

test('native, ya hay otro local: la casilla no se ofrece al resto', { skip }, () => {
  const h = render({ canLocal: false });
  assert.ok(!has(h, 'Este equipo') && !has(h, 'type="checkbox"'));
  assert.ok(has(h, 'Host / IP'));
});

test('docker: la casilla no aparece', { skip }, () => {
  const h = render({ runtime: 'docker', canLocal: false });
  assert.ok(!has(h, 'Este equipo') && !has(h, 'type="checkbox"'));
  assert.ok(has(h, 'Host / IP') && has(h, 'Probar conexión'));
});

test('docker con local en el borrador: aviso de error y sin casilla', { skip }, () => {
  const h = render({ runtime: 'docker', canLocal: false, dev: dev({ local: true }) });
  assert.ok(has(h, 'role="alert"') && has(h, 'sin Docker'));
  assert.ok(!has(h, 'type="checkbox"'));
});

test('error de validación del backend sobre local se muestra', { skip }, () => {
  const h = render({ dev: dev({ local: true }), errors: { local: 'solo puede haber un dispositivo “Este equipo”' } });
  assert.ok(has(h, 'solo puede haber un dispositivo'));
  const h2 = render({ dev: dev({ local: true }), localFlagError: 'Solo puede haber un dispositivo “Este equipo”' });
  assert.ok(has(h2, 'role="alert"'));
});

test('resultado del test se pinta, también multilínea', { skip }, () => {
  const h = render({ dev: dev({ local: true }), test: { ok: false, message: 'a: mal\nb: mal' } });
  assert.ok(has(h, 'alert error') && has(h, 'a: mal'));
  const busy = render({ dev: dev({ local: true }), test: { busy: true } });
  assert.ok(has(busy, 'Comprobando…') && has(busy, 'disabled'));
});

test('accesibilidad: casilla etiquetada y con descripción asociada', { skip }, () => {
  const h = render({});
  const m = h.match(/<input type="checkbox"[^>]*aria-describedby="([^"]+)"/);
  assert.ok(m, 'la casilla enlaza su ayuda');
  assert.ok(h.includes(`id="${m[1]}"`));
  assert.ok(/<label class="check"><input type="checkbox"/.test(h));
});
