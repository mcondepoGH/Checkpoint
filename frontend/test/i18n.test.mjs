// Infraestructura i18n: lookup jerárquico, parámetros, plurales con Intl.PluralRules, detección y persistencia del idioma.
import test from 'node:test';
import assert from 'node:assert/strict';
import { es as realEs } from './helpers/locales.mjs';
import { createI18n, pickLocale, STORAGE_KEY } from '../src/i18n.js';

const es = { app: { name: 'Checkpoint' }, hello: 'Hola {name}', files: { one: '{count} fichero', other: '{count} ficheros' }, solo: 'solo es' };
const en = { hello: 'Hello {name}', files: { one: '{count} file', other: '{count} files' } };
const mem = (init = {}) => { const m = { ...init }; return { getItem: (k) => (k in m ? m[k] : null), setItem: (k, v) => { m[k] = String(v); }, m }; };

test('clave jerárquica y parámetros', () => {
  const i = createI18n({ catalogs: { es }, storage: mem(), languages: ['es-ES'] });
  assert.equal(i.t('app.name'), 'Checkpoint');
  assert.equal(i.t('hello', { name: 'Ana' }), 'Hola Ana');
});

test('parámetro ausente se deja visible; clave ausente devuelve la clave', () => {
  const i = createI18n({ catalogs: { es }, storage: mem(), languages: ['es'] });
  assert.equal(i.t('hello'), 'Hola {name}');
  assert.equal(i.t('no.existe'), 'no.existe');
});

test('plurales con Intl.PluralRules (es y en)', () => {
  const i = createI18n({ catalogs: { es, en }, storage: mem(), languages: ['es'] });
  assert.equal(i.t('files', { count: 1 }), '1 fichero');
  assert.equal(i.t('files', { count: 3 }), '3 ficheros');
  assert.equal(i.t('files', { count: 0 }), '0 ficheros');
  i.setLocale('en');
  assert.equal(i.t('files', { count: 1 }), '1 file');
  assert.equal(i.t('files', { count: 2 }), '2 files');
});

test('plural sin categoría exacta cae a other', () => {
  const i = createI18n({ catalogs: { es: { x: { other: '{count} cosas' } } }, storage: mem(), languages: ['es'] });
  assert.equal(i.t('x', { count: 1 }), '1 cosas');
});

test('clave que falta en el idioma activo cae al base (es)', () => {
  const i = createI18n({ catalogs: { es, en }, storage: mem({ [STORAGE_KEY]: 'auto' }), languages: ['en-US'] });
  assert.equal(i.locale, 'en');
  assert.equal(i.t('solo'), 'solo es');
});

test('pickLocale: guardado > navegador > base', () => {
  const av = ['es', 'en'];
  assert.equal(pickLocale({ stored: 'en', languages: ['es-ES'], available: av }), 'en');
  assert.equal(pickLocale({ stored: 'fr', languages: ['en-GB', 'es'], available: av }), 'es'); // guardado inválido = sin elección
  assert.equal(pickLocale({ stored: null, languages: ['fr', 'de'], available: av }), 'es');
  assert.equal(pickLocale({ stored: null, languages: [], available: av }), 'es');
  // sin elección guardada manda el idioma por defecto (compose), no el del navegador
  assert.equal(pickLocale({ stored: null, languages: ['en'], available: av }), 'es');
  assert.equal(pickLocale({ stored: null, languages: ['es'], available: av, defaultLocale: 'en' }), 'en');
  assert.equal(pickLocale({ stored: null, languages: [], available: av, defaultLocale: 'fr' }), 'es');
  // «Automático» (guardado) sí usa el navegador y cae al por defecto
  assert.equal(pickLocale({ stored: 'auto', languages: ['es'], available: av, defaultLocale: 'en' }), 'es');
  assert.equal(pickLocale({ stored: 'auto', languages: ['fr'], available: av, defaultLocale: 'en' }), 'en');
  // la elección manual gana al por defecto
  assert.equal(pickLocale({ stored: 'es', languages: ['en'], available: av, defaultLocale: 'en' }), 'es');
  assert.equal(pickLocale({ stored: 'auto', languages: ['en'], available: av }), 'en');
});

test('idioma por defecto del compose: prioridad guardado > por defecto; sin guardar ignora el navegador', () => {
  const st = mem();
  const i = createI18n({ catalogs: { es, en }, storage: st, languages: ['es'] });
  let n = 0; i.subscribe(() => { n++; });
  assert.equal(i.locale, 'es');
  i.setDefaultLocale('en');
  assert.equal(i.locale, 'en'); assert.equal(i.preference, 'en'); assert.equal(n, 1);
  assert.equal(st.m[STORAGE_KEY], undefined, 'el por defecto no se guarda como elección');
  i.setDefaultLocale('zz'); // no soportado: sin cambios
  assert.equal(i.locale, 'en');
  i.setLocale('es'); // elección manual
  i.setDefaultLocale('en');
  assert.equal(i.locale, 'es');
  i.setLocale('auto'); // Automático: navegador (es)
  assert.equal(i.locale, 'es'); assert.equal(i.preference, 'auto');
  const j = createI18n({ catalogs: { es, en }, storage: mem({ [STORAGE_KEY]: 'auto' }), languages: ['en-GB'] });
  j.setDefaultLocale('es');
  assert.equal(j.locale, 'en');
});

test('setLocale recuerda la elección; auto la olvida y vuelve al navegador', () => {
  const st = mem();
  const i = createI18n({ catalogs: { es, en }, storage: st, languages: ['es'] });
  i.setLocale('en');
  assert.equal(st.m[STORAGE_KEY], 'en');
  assert.equal(createI18n({ catalogs: { es, en }, storage: st, languages: ['es'] }).locale, 'en');
  i.setLocale('auto');
  assert.equal(i.locale, 'es');
  assert.equal(i.preference, 'auto');
  assert.equal(createI18n({ catalogs: { es, en }, storage: st, languages: ['en'] }).locale, 'en');
  assert.equal(st.m[STORAGE_KEY], 'auto');
});

test('idioma desconocido en setLocale se ignora; storage roto no revienta', () => {
  const bad = { getItem() { throw new Error('x'); }, setItem() { throw new Error('x'); } };
  const i = createI18n({ catalogs: { es }, storage: bad, languages: ['es'] });
  i.setLocale('zz');
  assert.equal(i.locale, 'es');
  assert.doesNotThrow(() => i.setLocale('es'));
});

test('suscriptores se avisan al cambiar de idioma', () => {
  const i = createI18n({ catalogs: { es, en }, storage: mem(), languages: ['es'] });
  let n = 0; const off = i.subscribe(() => { n++; });
  i.setLocale('en'); i.setLocale('en'); off(); i.setLocale('es');
  assert.equal(n, 1);
});

test('locales/es.json es JSON válido con claves de prueba', async () => {
  const i = createI18n({ catalogs: { es: realEs }, storage: mem(), languages: ['es'] });
  assert.equal(i.t('lang.label'), 'Idioma');
  assert.equal(i.t('lang.auto'), 'Automático');
});
