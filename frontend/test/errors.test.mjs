// Errores de la API: ApiError expone code/params y errorText traduce con t(), con fallback al texto recibido.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { es } from './helpers/locales.mjs';
import { ApiError, api } from '../src/api.js';
import { errorText, fieldErrorText } from '../src/errors.js';
import { createI18n } from '../src/i18n.js';

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

// Código de la capa web: main.py, los routers/dependencias de api/ y la lógica de services/.
function apiSources() {
  const root = new URL('../../backend/app/', import.meta.url);
  const files = ['main.py'];
  for (const d of ['api', 'services']) {
    for (const f of fs.readdirSync(new URL(`${d}/`, root), { recursive: true })) if (f.endsWith('.py')) files.push(`${d}/${f}`);
  }
  return files.map((f) => fs.readFileSync(new URL(f, root), 'utf8')).join('\n');
}

test('todas las claves err.main.* que emite el backend existen en es.json', () => {
  const src = apiSources();
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
  const src = ['config/models.py', 'config/store.py'].map((f) => fs.readFileSync(new URL(`../../backend/app/${f}`, import.meta.url), 'utf8')).join('');
  const codes = [...new Set([...src.matchAll(/"(err\.config(?:store)?\.[a-z_]+)"/g)].map((m) => m[1]))];
  assert.ok(codes.length >= 50, `solo ${codes.length} códigos`);
  for (const c of codes) assert.notEqual(t(c, { reason: 'r', max: 1 }), c, `falta ${c}`);
});

test('todas las claves err.sync/transport/bootstrap que emite el backend existen en es.json', () => {
  const dir = new URL('../../backend/app/', import.meta.url);
  const syncFiles = fs.readdirSync(new URL('sync/', dir), { recursive: true }).filter((f) => f.endsWith('.py')).map((f) => `sync/${f}`);
  const src = [...syncFiles, 'core/bootstrap.py'].map((f) => fs.readFileSync(new URL(f, dir), 'utf8')).join('\n') + apiSources();
  const codes = [...new Set([...src.matchAll(/"(err\.(?:sync|transport|bootstrap)\.[a-z_]+)"/g)].map((m) => m[1]))]
    .filter((c) => !c.endsWith('_'));
  for (const r of ['indeterminate', 'stale', 'no_baseline', 'inconsistent', 'both_changed']) codes.push(`err.sync.conflict_${r}`);
  assert.ok(codes.length > 50, `solo ${codes.length} códigos`);
  for (const c of codes) assert.notEqual(t(c, { x: 1 }), c, `falta ${c}`);
});

test('estado de sync con code+params se traduce, también con causas anidadas y lista de fallos', () => {
  assert.equal(errorText({ result: 'ok', code: 'err.sync.already_synced', params: {}, message: 'err.sync.already_synced' }, t), 'ya sincronizado');
  assert.equal(errorText({ code: 'err.sync.conflict', params: { sides: 'PC, Portátil', cause: { code: 'err.sync.conflict_both_changed', params: {} } } }, t),
    'conflicto en PC, Portátil: ambos lados cambiaron desde la última sincronización');
  assert.equal(errorText({ code: 'err.sync.conflict_indeterminate', params: { seconds: 2 } }, t), 'los relojes difieren menos de 2 s: no se puede saber cuál es más reciente');
  const failed = [{ path: 'PC', code: 'err.transport.rsync_push_failed', params: { detail: 'Permission denied' } }];
  assert.equal(errorText({ code: 'err.sync.partial', params: { winner: 'A', updated: 'hub', failed } }, t),
    'ganador A; actualizados hub; fallaron PC: rsync push falló: Permission denied');
  assert.equal(errorText({ code: 'err.sync.process_check_failed', params: { device: 'PC', cause: { code: 'err.transport.pgrep_failed', params: { detail: 'x' } } } }, t),
    'no se pudo comprobar el proceso en PC: pgrep falló: x');
});

test('estado persistido antiguo (texto en español, sin code) se muestra tal cual', () => {
  assert.equal(errorText({ result: 'ok', message: 'ya sincronizado' }, t), 'ya sincronizado');
});

test('versión restaurada y restore_failed con causa anidada', () => {
  assert.equal(errorText({ ok: true, code: 'err.sync.restored', params: { version: 'v1', source: 'PC' } }, t), 'hub restaurado desde v1/PC; ejecuta Sincronizar para propagarlo');
  assert.equal(errorText({ code: 'err.main.restore_failed', params: { cause: { code: 'err.sync.version_unknown', params: {} } } }, t), 'no existe esa versión');
});

test('recordText: registros de scheduler/historial con code+params, fallback al texto antiguo', async () => {
  const { recordText } = await import('../src/errors.js');
  assert.equal(recordText({ code: 'err.scheduler.busy', params: {}, message: '' }, t), 'ya en curso');
  const sum = { code: 'err.scheduler.summary', params: { causes: [
    { path: 'Zelda', code: 'err.scheduler.skipped_busy', params: {} },
    { path: 'Mario', code: 'err.scheduler.skipped_conflict', params: { cause: { code: 'err.sync.conflict_stale', params: {} } } }] } };
  assert.equal(recordText(sum, t), 'Zelda: omitido (ya en curso); Mario: omitido por conflicto: los datos cambiaron desde que se mostró el conflicto');
  assert.equal(recordText({ message: 'Zelda: texto antiguo' }, t), 'Zelda: texto antiguo');
  assert.equal(recordText({}, t), '');
  assert.equal(recordText(null, t), '');
});

test('errores de validación del scheduler: {code, params} traducen y el texto antiguo pasa', () => {
  assert.equal(fieldErrorText({ code: 'err.scheduler.interval_range', params: { min: 0.25, max: 168 } }, t), 'debe estar entre 0.25 y 168 horas');
  assert.equal(fieldErrorText('debe ser un número', t), 'debe ser un número');
});
