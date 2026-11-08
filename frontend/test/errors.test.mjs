// Errores de la API: ApiError expone code/params y errorText traduce con t(), con fallback al texto recibido.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { ApiError, api } from '../src/api.js';
import { errorText, fieldErrorText } from '../src/errors.js';
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

test('errorText traduce causas anidadas: cause {code,params} y causes [{path,code,params}]', () => {
  assert.equal(errorText({ code: 'err.main.backup_invalid', params: { cause: { code: 'err.config.yaml_malformed', params: {} } } }, t),
    'la copia no es válida: YAML mal formado: error de sintaxis');
  const causes = [{ path: 'host', code: 'err.config.host_invalid', params: {} }, { path: '', code: 'err.config.required', params: {} }];
  assert.equal(errorText({ code: 'err.main.device_invalid', params: { causes } }, t),
    'datos del dispositivo inválidos: host: host inválido; campo obligatorio');
  // anidado a dos niveles (config_file_invalid -> configstore.invalid -> config.*)
  const deep = { code: 'err.main.config_file_invalid', params: { cause: { code: 'err.configstore.invalid', params: { causes } } } };
  assert.equal(errorText(deep, t), 'config.yaml inválido: config no válida: host: host inválido; campo obligatorio');
});

test('fieldErrorText: string tal cual, {code,params} traducido, vacío -> undefined', () => {
  assert.equal(fieldErrorText('texto viejo', t), 'texto viejo');
  assert.equal(fieldErrorText({ code: 'err.config.name_too_long', params: { max: 64 } }, t), 'nombre demasiado largo (máx. 64 caracteres)');
  assert.equal(fieldErrorText(undefined, t), undefined);
  assert.equal(fieldErrorText('', t), '');
});

test('todos los err.config.* y err.configstore.* que emite el backend existen en es.json', () => {
  const src = ['config.py', 'configstore.py'].map((f) => fs.readFileSync(new URL(`../../backend/app/${f}`, import.meta.url), 'utf8')).join('');
  const codes = [...new Set([...src.matchAll(/"(err\.config(?:store)?\.[a-z_]+)"/g)].map((m) => m[1]))];
  assert.ok(codes.length >= 50, `solo ${codes.length} códigos`);
  for (const c of codes) assert.notEqual(t(c, { reason: 'r', max: 1 }), c, `falta ${c}`);
});
