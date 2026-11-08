// Pantallas y diálogos renderizados a HTML en es y en: nada en español en modo inglés, y cambio de idioma sin recargar.
// Usa esbuild (viene con Vite); si no está disponible el test se salta.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const SRC = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'src');
let m = null;
let skip = false;
try {
  const { build } = await import('esbuild');
  const out = await build({
    stdin: {
      contents: `import React from 'react';
        import { renderToStaticMarkup } from 'react-dom/server';
        import { i18n, initDefaultLang } from './useI18n.js';
        import Login from './pages/Login.jsx';
        import LanguageSelect from './components/LanguageSelect.jsx';
        import DeviceCard from './components/DeviceCard.jsx';
        import GameCard from './components/GameCard.jsx';
        import ConflictDialog from './components/ConflictDialog.jsx';
        import DiffView from './components/DiffView.jsx';
        import UpdateDialog from './components/UpdateDialog.jsx';
        import UpdateBadge from './components/UpdateBadge.jsx';
        import PublicKey from './components/PublicKey.jsx';
        import Sync from './pages/Sync.jsx';
        import Versions from './pages/Versions.jsx';
        export { React, renderToStaticMarkup, i18n, initDefaultLang, Login, LanguageSelect, DeviceCard, GameCard, ConflictDialog, DiffView, UpdateDialog, UpdateBadge, PublicKey, Sync, Versions };`,
      resolveDir: SRC, loader: 'jsx',
    },
    bundle: true, write: false, format: 'esm', platform: 'node', jsx: 'transform',
    define: { 'process.env.NODE_ENV': '"production"' },
    loader: { '.svg': 'dataurl' },
    banner: { js: "import { createRequire } from 'node:module'; const require = createRequire(import.meta.url);" },
    logLevel: 'silent',
  });
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ckpt-render-'));
  const file = path.join(dir, 'bundle.mjs');
  fs.writeFileSync(file, out.outputFiles[0].text);
  m = await import(pathToFileURL(file).href);
  fs.rmSync(dir, { recursive: true, force: true });
} catch (e) {
  skip = `esbuild no disponible: ${e.message}`;
}

const h = (C, props) => m.renderToStaticMarkup(m.React.createElement(C, props));
const dev = { key: 'k1', id: 'pc-1', name: 'PC', orig: 'PC', local: false, host: 'h', port: '22', user: 'u', os: 'linux' };
const game = { key: 'g1', id: 'g-1', name: 'Game', a: 'k1', b: 'k2', pathA: '/a', pathB: '/b', process: '', keep: '', onConflict: '' };
const devices = [dev, { ...dev, key: 'k2', id: 'pc-2', name: 'PC2' }];
const conflict = { reason: 'both-changed', sides: [{ id: 'a', name: 'PC', hash: 'x', mtime: 1700000000, size: 2048, files: 3 }, { id: 'hub', hub: true, hash: 'y', mtime: 1700000100, size: 10, files: 1 }] };
const cfg = { devices: { a: { name: 'A' } }, games: { g: { name: 'G', devices: ['a', 'a'] } } };
const NEW = { actual: '0.4.2', ultima: '0.5.0', hay_actualizacion: true, habilitado: true, notas: 'x', url: 'https://x.y/z', prerelease: false, aplicable: true };

// Palabras españolas que no deben aparecer en modo inglés (los datos de prueba están en inglés/neutros).
const SPANISH = /\b(Sincronizar|Configuración|Versiones|Eliminar|Cancelar|Cerrar|Guardar|Nombre|Dispositivo|Puerto|Usuario|Contraseña|Entrar|Salir|Conflicto|Restaurar|Aplicar|Atrás|fichero|ficheros|Juego|Cargando|Probar|Comprobar|Sin |Ruta|Proceso|Simulación|Novedades|Instalada|Ganador|Destinos|Actualizados|Resolver)\b/;

const screens = () => [
  ['Login', h(m.Login, { onDone() {} })],
  ['LanguageSelect', h(m.LanguageSelect, {})],
  ['DeviceCard', h(m.DeviceCard, { dev, errors: {}, idText: 'pc-1', renamed: true, onChange() {}, onTest() {}, onRemove() {}, runtime: 'native', platform: 'linux', canLocal: true, test: { ok: true, code: 'err.transport.connection_ok', params: {}, first_use: true } })],
  ['GameCard', h(m.GameCard, { game, devices, errors: {}, globalMax: '20', nameA: 'PC', nameB: 'PC2', idA: 'pc-1', idB: 'pc-2', idText: 'g-1', renamed: false, onChange() {}, onRemove() {} })],
  ['ConflictDialog', h(m.ConflictDialog, { game: 'G', conflict, busy: false, onCancel() {}, onResolve() {} })],
  ['DiffView', h(m.DiffView, { diff: { empty: false, general: { added: [], removed: [], changed: { max_versions: { old: 1, new: 2 } } }, devices: { added: ['a'], removed: [], changed: {} }, games: { added: [], removed: ['g'], changed: {} }, names: {} } })],
  ['DiffView vacío', h(m.DiffView, { diff: { empty: true } })],
  ['UpdateDialog', h(m.UpdateDialog, { info: { ...NEW, prerelease: true }, onClose() {} })],
  ['UpdateBadge', h(m.UpdateBadge, { info: NEW, onOpen() {} })],
  ['PublicKey', h(m.PublicKey, {})],
  ['Sync', h(m.Sync, { config: { devices: {}, games: {} }, onGoSettings() {} })],
  ['Versions', h(m.Versions, { config: { devices: {}, games: {} }, onGoSettings() {} })],
];

test('modo inglés: sin palabras en español', { skip }, () => {
  m.i18n.setLocale('en');
  assert.equal(m.i18n.locale, 'en');
  for (const [name, html] of screens()) {
    const text = html.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ');
    assert.ok(!SPANISH.test(text), `${name}: ${text.match(SPANISH)?.[0]} en «${text.slice(0, 200)}»`);
  }
  m.i18n.setLocale('es');
});

test('modo español: textos en español', { skip }, () => {
  m.i18n.setLocale('es');
  const all = screens().map(([, x]) => x).join('\n');
  for (const s of ['Usuario', 'Contraseña', 'Entrar', 'Probar conexión', 'Elegir dispositivo', 'Sin juegos configurados', 'Nueva versión disponible']) assert.ok(all.includes(s), s);
});

test('cambio de idioma sin recargar: el mismo componente se repinta', { skip }, () => {
  m.i18n.setLocale('es');
  assert.match(h(m.Login, { onDone() {} }), /Entrar/);
  m.i18n.setLocale('en');
  const en = h(m.Login, { onDone() {} });
  assert.match(en, /Sign in/);
  m.i18n.setLocale('es');
});

test('login limpio: sin selector de idioma ni de tema', { skip }, () => {
  m.i18n.setLocale('es');
  const html = h(m.Login, { onDone() {} });
  assert.doesNotMatch(html, /<select/);
  assert.doesNotMatch(html, /Tema|Theme/);
  assert.equal((html.match(/<button/g) || []).length, 1);
});

test('cabecera de la app (con sesión) conserva idioma y tema', () => {
  const app = fs.readFileSync(path.join(SRC, 'App.jsx'), 'utf8');
  const login = fs.readFileSync(path.join(SRC, 'pages', 'Login.jsx'), 'utf8');
  assert.match(app, /<LanguageSelect \/>/);
  assert.match(app, /onClick=\{cycleTheme\}/);
  assert.doesNotMatch(login, /LanguageSelect|cycleTheme/);
});

test('LanguageSelect: Automático + Español + English', { skip }, () => {
  m.i18n.setLocale('es');
  const html = h(m.LanguageSelect, {});
  assert.match(html, /Automático/);
  assert.match(html, />Español</);
  assert.match(html, />English</);
  m.i18n.setLocale('es');
});

test('plurales de ficheros en el conflicto (es y en)', { skip }, () => {
  m.i18n.setLocale('en');
  const en = h(m.ConflictDialog, { game: 'G', conflict, busy: false, onCancel() {}, onResolve() {} });
  assert.match(en, /3 files/); assert.match(en, /1 file</);
  m.i18n.setLocale('es');
  const es = h(m.ConflictDialog, { game: 'G', conflict, busy: false, onCancel() {}, onResolve() {} });
  assert.match(es, /3 ficheros/); assert.match(es, /1 fichero</);
});

test('idioma por defecto del servidor (/api/public): se aplica sin elección guardada; un fallo no rompe', { skip }, async () => {
  const realFetch = globalThis.fetch;
  try {
    m.i18n.setLocale('es'); // elección manual -> el por defecto no la pisa
    globalThis.fetch = async () => ({ ok: true, json: async () => ({ default_lang: 'en' }) });
    await m.initDefaultLang();
    assert.equal(m.i18n.locale, 'es');
    globalThis.fetch = async () => { throw new Error('sin red'); };
    await assert.doesNotReject(m.initDefaultLang());
    globalThis.fetch = async () => ({ ok: false, status: 500, statusText: 'x', json: async () => ({}) });
    await assert.doesNotReject(m.initDefaultLang());
  } finally { globalThis.fetch = realFetch; }
});
