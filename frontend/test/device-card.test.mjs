// Renderiza DeviceCard a HTML (react-dom/server) en modo nativo y Docker. Usa esbuild, que ya viene con Vite;
// si no está disponible (p. ej. instalación solo de producción) el test se salta.
import test from 'node:test';
import assert from 'node:assert/strict';
import os from 'node:os';
import path from 'node:path';
import { bundle } from './helpers/bundle.mjs';

const { mod, skip } = await bundle(`import React from 'react';
  import { renderToStaticMarkup } from 'react-dom/server';
  import DeviceCard from '#src/components/DeviceCard.jsx';
  export { React, renderToStaticMarkup, DeviceCard };`, { tag: 'ckpt-render' });

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

test('resultado con code+params se traduce; first_use añade el aviso', { skip }, () => {
  const ok = render({ dev: dev(), test: { ok: true, code: 'err.transport.connection_ok', params: {}, first_use: true } });
  assert.ok(has(ok, 'alert ok') && has(ok, 'conexión OK (host key guardada (primer uso))'));
  const bad = render({ dev: dev(), test: { ok: false, code: 'err.transport.ssh_failed', params: { detail: 'boom' }, first_use: true } });
  assert.ok(has(bad, 'SSH falló: boom [host key guardada (primer uso)]'));
  const multi = render({ dev: dev({ local: true }), test: { ok: false, results: [{ path: '/a', ok: true, code: 'err.transport.folder_ok', params: {} },
    { path: 'r', ok: false, code: 'err.transport.path_not_absolute', params: { path: 'r' } }] } });
  assert.ok(has(multi, '/a: carpeta OK') && has(multi, 'r: la ruta no es absoluta en este sistema: r'));
});

test('accesibilidad: casilla etiquetada y con descripción asociada', { skip }, () => {
  const h = render({});
  const m = h.match(/<input type="checkbox"[^>]*aria-describedby="([^"]+)"/);
  assert.ok(m, 'la casilla enlaza su ayuda');
  assert.ok(h.includes(`id="${m[1]}"`));
  assert.ok(/<label class="check"><input type="checkbox"/.test(h));
});
