// Errores de la API: ApiError expone code/params y errorText traduce con t(), con fallback al texto recibido.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { ApiError, api } from '../src/api.js';
import { errorText } from '../src/errors.js';
import { createI18n } from '../src/i18n.js';

const es = JSON.parse(fs.readFileSync(new URL('../src/locales/es.json', import.meta.url), 'utf8'));
const { t } = createI18n({ catalogs: { es }, storage: null, languages: ['es'] });

const fakeFetch = (status, data) => async () => ({ ok: status < 400, status, statusText: 'x', json: async () => data });

test('api: detail {code, params} -> ApiError con code y params', async () => {
  globalThis.fetch = fakeFetch(429, { detail: { code: 'err.main.too_many_attempts', params: { seconds: 7 } }, retry_after: 7 });
  await assert.rejects(api('/api/login'), (e) => e instanceof ApiError && e.status === 429
    && e.code === 'err.main.too_many_attempts' && e.params.seconds === 7 && e.data.retry_after === 7);
});

test('api: detail en texto (error antiguo u otro origen) -> sin code, message = texto', async () => {
  globalThis.fetch = fakeFetch(500, { detail: 'boom' });
  await assert.rejects(api('/x'), (e) => e.code === undefined && e.message === 'boom' && e.params === undefined);
  globalThis.fetch = fakeFetch(502, null);
  await assert.rejects(api('/x'), (e) => e.message === 'x');
});

test('errorText traduce el code con params', () => {
  assert.equal(errorText(new ApiError(429, 'x', {}, 'err.main.too_many_attempts', { seconds: 7 }), t), 'demasiados intentos; espera 7 s');
  assert.equal(errorText({ code: 'err.main.game_unknown', params: {} }, t), 'juego desconocido');
});

test('errorText: sin code usa el texto; code sin traducción usa reason o el code', () => {
  assert.equal(errorText(new Error('texto'), t), 'texto');
  assert.equal(errorText({ message: 'hola' }, t), 'hola');
  assert.equal(errorText({ code: 'err.zz.nueva', params: { reason: 'motivo' } }, t), 'motivo');
  assert.equal(errorText({ code: 'err.zz.nueva', params: {} }, t), 'err.zz.nueva');
});

test('todas las claves err.main.* que emite el backend existen en es.json', () => {
  const src = fs.readFileSync(new URL('../../backend/app/main.py', import.meta.url), 'utf8');
  const codes = [...new Set([...src.matchAll(/"(err\.main\.[a-z_.]+)"/g)].map((m) => m[1]))];
  assert.ok(codes.length >= 25, `solo ${codes.length} códigos`);
  for (const c of codes) assert.notEqual(t(c, { reason: 'r', seconds: 1, max: 1 }), c, `falta ${c}`);
});
