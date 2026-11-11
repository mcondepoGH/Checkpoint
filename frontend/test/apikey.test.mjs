// Sección «API key» del perfil: lógica (reductor, llamadas, copiar) y render de cada estado en es y en.
// El render usa esbuild (viene con Vite); si no está disponible esos tests se saltan.
import test from 'node:test';
import assert from 'node:assert/strict';
import { initialState, isInsecure, reduce, run } from '#src/lib/apikey.js';
import { ApiError } from '#src/lib/api.js';
import { bundle } from './helpers/bundle.mjs';

const KEY = 'ck_' + 'A'.repeat(43);

// ---- lógica ----
test('estado inicial: sin cargar y sin key', () => {
  assert.deepEqual(initialState, { loaded: false, exists: false, key: null, confirm: null, busy: false, error: null });
});

test('generar: pide POST y el estado pasa a «con key»', async () => {
  const calls = [];
  const api = async (p, o) => { calls.push([p, o.method]); return { exists: true, key: KEY }; };
  let s = reduce(initialState, { type: 'start' });
  assert.equal(s.busy, true);
  s = reduce(s, await run(api, 'create'));
  assert.deepEqual(calls, [['/api/profile/apikey', 'POST']]);
  assert.deepEqual([s.loaded, s.exists, s.key, s.busy], [true, true, KEY, false]);
});

test('cargar sin key: exists false y key nula', async () => {
  const s = reduce(initialState, await run(async () => ({ exists: false, key: null }), 'load'));
  assert.deepEqual([s.loaded, s.exists, s.key], [true, false, null]);
});

test('regenerar exige confirmación: pedir, cancelar y confirmar', async () => {
  let s = { ...initialState, loaded: true, exists: true, key: KEY };
  s = reduce(s, { type: 'ask', what: 'regenerate' });
  assert.equal(s.confirm, 'regenerate');
  s = reduce(s, { type: 'cancel' });
  assert.equal(s.confirm, null);
  assert.equal(s.key, KEY);
  s = reduce(s, { type: 'ask', what: 'regenerate' });
  const NEW = 'ck_' + 'B'.repeat(43);
  s = reduce(s, await run(async (p, o) => { assert.equal(o.method, 'POST'); return { exists: true, key: NEW }; }, 'create'));
  assert.equal(s.key, NEW);
  assert.equal(s.confirm, null);
});

test('revocar: DELETE y vuelve a «sin key»', async () => {
  const calls = [];
  let s = reduce({ ...initialState, loaded: true, exists: true, key: KEY }, { type: 'ask', what: 'revoke' });
  s = reduce(s, await run(async (p, o) => { calls.push(o.method); return { exists: false, key: null }; }, 'revoke'));
  assert.deepEqual(calls, ['DELETE']);
  assert.deepEqual([s.exists, s.key, s.confirm], [false, null, null]);
});

test('un fallo de la API guarda el error (código traducible) y conserva la key mostrada', async () => {
  const err = new ApiError(403, 'err.main.origin_forbidden', null, 'err.main.origin_forbidden', {});
  let s = { ...initialState, loaded: true, exists: true, key: KEY, confirm: 'regenerate' };
  s = reduce(s, await run(async () => { throw err; }, 'create'));
  assert.equal(s.error, err);
  assert.equal(s.confirm, null);
  assert.equal(s.key, KEY);
  assert.equal(reduce(s, { type: 'start' }).error, null);
});

test('aviso de HTTP en claro solo fuera de localhost', () => {
  assert.equal(isInsecure({ protocol: 'http:', hostname: '192.168.1.5' }), true);
  assert.equal(isInsecure({ protocol: 'http:', hostname: 'localhost' }), false);
  assert.equal(isInsecure({ protocol: 'https:', hostname: 'hub.example' }), false);
  assert.equal(isInsecure(null), false);
});

// ---- render ----
const { mod: m, skip } = await bundle(`import React from 'react';
  import { renderToStaticMarkup } from 'react-dom/server';
  import { i18n } from '#src/hooks/useI18n.js';
  import ApiKeySection from '#src/components/ApiKeySection.jsx';
  import ProfileMenu from '#src/components/ProfileMenu.jsx';
  import { copyText } from '#src/lib/clipboard.js';
  export { React, renderToStaticMarkup, i18n, ApiKeySection, ProfileMenu, copyText };`, { navigator: true, tag: 'ckpt-apikey' });
const section = (initial, lang = 'es', props = {}) => {
  m.i18n.setLocale(lang);
  return m.renderToStaticMarkup(m.React.createElement(m.ApiKeySection, { initial, ...props }));
};
const has = (h, s) => h.includes(s);
const WITH = { loaded: true, exists: true, key: KEY };

test('sin key: botón «Generar» y sin campo ni copiar', { skip }, () => {
  const h = section({ loaded: true });
  assert.ok(has(h, 'API key') && has(h, 'Generar') && has(h, 'Aún no hay API key'));
  assert.ok(!has(h, 'copybox-field') && !has(h, 'Copiar') && !has(h, 'Regenerar'));
});

test('con key: la key completa se renderiza sin truncar en un cuadro monoespaciado', { skip }, () => {
  const h = section(WITH);
  assert.ok(has(h, `>${KEY}</code>`) && has(h, 'class="copybox-field"') && has(h, 'aria-label="API key (solo lectura)"'), h);
  assert.ok(!has(h, '<input') && !has(h, '…'));
});

test('con key: Copiar es botón de icono accesible; Regenerar y Revocar usan Button (danger en Revocar)', { skip }, () => {
  const h = section(WITH);
  assert.match(h, /<button[^>]*class="btn btn-icon copybox-copy"[^>]*aria-label="Copiar clave API"/);
  assert.match(h, /<button[^>]*class="btn"[^>]*>Regenerar<\/button>/);
  assert.match(h, /<button[^>]*class="btn danger"[^>]*>Revocar<\/button>/);
  assert.ok(has(h, 'Regenerar') && has(h, 'Revocar') && !has(h, 'Generar<'));
});

test('aviso HTTP: Alert compacto solo cuando aplica', { skip }, () => {
  assert.ok(!has(section(WITH, 'es', { insecure: false }), 'alert warn compact'));
  const h = section(WITH, 'es', { insecure: true });
  assert.ok(has(h, 'class="alert warn compact"') && has(h, 'Por HTTP la key viaja en claro: usa HTTPS o VPN fuera de tu LAN.'), h);
  assert.ok(has(section(WITH, 'en', { insecure: true }), 'Over HTTP the key travels in clear text'));
});

test('regenerar pide confirmación y avisa de que invalida comandos y plugins', { skip }, () => {
  const h = section({ ...WITH, confirm: 'regenerate' });
  assert.ok(has(h, 'role="alertdialog"') && has(h, 'comandos y plugins ya vinculados') && has(h, 'Sí, regenerar') && has(h, 'Cancelar'));
  assert.ok(!has(h, '>Regenerar<') && has(h, KEY));
  assert.match(h, /class="btn danger"[^>]*>Sí, regenerar/);
});

test('revocar pide confirmación', { skip }, () => {
  const h = section({ ...WITH, confirm: 'revoke' });
  assert.ok(has(h, 'Sí, revocar') && has(h, 'dejarán de funcionar'));
});

test('error traducido', { skip }, () => {
  const h = section({ loaded: true, exists: true, key: KEY, error: { code: 'err.main.origin_forbidden', params: {} } });
  assert.ok(has(h, 'role="alert"') && has(h, 'origen no permitido'));
});

test('en inglés no queda nada en español', { skip }, () => {
  for (const st of [{ loaded: true }, WITH, { ...WITH, confirm: 'regenerate' }, { ...WITH, confirm: 'revoke' }]) {
    const h = section(st, 'en', { insecure: true });
    assert.ok(!/Generar|Regenerar|Revocar|Copiar|Cancelar|Aún|vinculados|Sí,/.test(h), h);
  }
  const h = section(WITH, 'en');
  assert.ok(has(h, 'Regenerate') && has(h, 'Revoke') && has(h, 'aria-label="Copy API key"'));
  m.i18n.setLocale('es');
});

test('el menú del perfil abierto incluye la sección', { skip }, () => {
  m.i18n.setLocale('es');
  const h = m.renderToStaticMarkup(m.React.createElement(m.ProfileMenu, {
    profile: { name: 'admin', photo: null }, theme: 'auto', effectiveTheme: 'dark',
    onCycleTheme() {}, onLogout() {}, onPhoto() {}, open: true,
  }));
  assert.ok(has(h, 'class="apikey"') && has(h, 'profile-pop'));
});

// ---- copiar ----
test('copyText usa la API del portapapeles y devuelve true', { skip }, async () => {
  const wrote = [];
  Object.defineProperty(globalThis, 'navigator', { value: { clipboard: { writeText: async (t) => wrote.push(t) } }, configurable: true });
  assert.equal(await m.copyText(KEY), true);
  assert.deepEqual(wrote, [KEY]);
});
