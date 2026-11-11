// Pantallas y diálogos renderizados a HTML en es y en: nada en español en modo inglés, y cambio de idioma sin recargar.
// Usa esbuild (viene con Vite); si no está disponible el test se salta.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { bundle, SRC } from './helpers/bundle.mjs';

const { mod: m, skip } = await bundle(`import React from 'react';
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
  import ProfileMenu from './components/ProfileMenu.jsx';
  import Avatar from './components/Avatar.jsx';
  import Sync from './pages/Sync.jsx';
  import Versions from './pages/Versions.jsx';
  export { React, renderToStaticMarkup, i18n, initDefaultLang, Login, LanguageSelect, DeviceCard, GameCard, ConflictDialog, DiffView, UpdateDialog, UpdateBadge, PublicKey, ProfileMenu, Avatar, Sync, Versions };`, { tag: 'ckpt-render' });

const h = (C, props) => m.renderToStaticMarkup(m.React.createElement(C, props));
const dev = { key: 'k1', id: 'pc-1', name: 'PC', orig: 'PC', local: false, host: 'h', port: '22', user: 'u', os: 'linux' };
const game = { key: 'g1', id: 'g-1', name: 'Game', a: 'k1', b: 'k2', pathA: '/a', pathB: '/b', process: '', keep: '', onConflict: '' };
const devices = [dev, { ...dev, key: 'k2', id: 'pc-2', name: 'PC2' }];
const conflict = { reason: 'both-changed', sides: [{ id: 'a', name: 'PC', hash: 'x', mtime: 1700000000, size: 2048, files: 3 }, { id: 'hub', hub: true, hash: 'y', mtime: 1700000100, size: 10, files: 1 }] };
const cfg = { devices: { a: { name: 'A' } }, games: { g: { name: 'G', devices: ['a', 'a'] } } };
const NEW = { actual: '0.4.2', ultima: '0.5.0', hay_actualizacion: true, habilitado: true, notas: 'x', url: 'https://x.y/z', prerelease: false, aplicable: true };

// Palabras españolas que no deben aparecer en modo inglés (los datos de prueba están en inglés/neutros).
const SPANISH = /\b(Sincronizar|Configuración|Versiones|Eliminar|Cancelar|Cerrar|Guardar|Nombre|Dispositivo|Puerto|Usuario|Contraseña|Entrar|Salir|Conflicto|Restaurar|Aplicar|Atrás|fichero|ficheros|Juego|Cargando|Probar|Comprobar|Sin |Ruta|Proceso|Simulación|Novedades|Instalada|Ganador|Destinos|Actualizados|Resolver)\b/;

const PROFILE = { profile: { name: 'admin', photo: null }, theme: 'auto', effectiveTheme: 'dark', onCycleTheme() {}, onLogout() {}, onPhoto() {} };

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
  ['ProfileMenu abierto', h(m.ProfileMenu, { ...PROFILE, open: true })],
  ['ProfileMenu abierto con foto', h(m.ProfileMenu, { ...PROFILE, open: true, profile: { name: 'admin', photo: { version: 'abc' } } })],
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

test('cabecera de la app (con sesión): idioma, tema y salir viven en el perfil, no en la barra', () => {
  const app = fs.readFileSync(path.join(SRC, 'App.jsx'), 'utf8');
  const login = fs.readFileSync(path.join(SRC, 'pages', 'Login.jsx'), 'utf8');
  const header = app.slice(app.indexOf('<header'), app.indexOf('</header>'));
  assert.match(header, /<AppIcon className="brand-logo" \/>/);
  assert.match(header, /<ProfileMenu /);
  assert.doesNotMatch(header, /LanguageSelect|<Icon |tool-label/);
  // El perfil es lo último de la barra (extremo derecho).
  assert.ok(header.lastIndexOf('<ProfileMenu') > header.lastIndexOf('<UpdateBadge'));
  const css = fs.readFileSync(path.join(SRC, 'styles', '_layout.scss'), 'utf8');
  // Pestañas: etiqueta corta oculta en escritorio. Sin restos de los controles movidos.
  assert.match(css, /\.tab \.short \{ display: none; \}/);
  assert.doesNotMatch(css, /tool-label|lang-select|lang-code/);
  // El icono de la app se ve también en móvil estrecho (a la izquierda).
  assert.doesNotMatch(css, /\.brand \{ display: none; \}/);
  // A <= 340 px (con el aviso de actualización) se reduce el relleno/gap de las pestañas; los textos siguen completos.
  const vars = fs.readFileSync(path.join(SRC, 'styles', '_variables.scss'), 'utf8');
  assert.match(vars, /\$bp-xxs: 340px/);
  const narrow = css.slice(css.indexOf('@media (max-width: v.$bp-xxs)'));
  assert.match(narrow, /\.tab \{ padding: 0 \.15rem; \}/);
  assert.doesNotMatch(narrow, /overflow|display: none|font-size/);
  assert.doesNotMatch(login, /LanguageSelect|cycleTheme|ProfileMenu/);
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

test('ProfileMenu: botón cerrado con aria correctos y silueta sin foto', { skip }, () => {
  m.i18n.setLocale('es');
  const html = h(m.ProfileMenu, PROFILE);
  assert.match(html, /aria-haspopup="dialog"/);
  assert.match(html, /aria-expanded="false"/);
  assert.match(html, /aria-label="Perfil y opciones"/);
  assert.doesNotMatch(html, /role="dialog"/);
  assert.doesNotMatch(html, /<img/); // silueta (svg), no foto
  assert.match(html, /class="ico"/);
});

test('ProfileMenu: popup abierto con nombre, idioma, tema, salir; sin foto no hay «Quitar foto»', { skip }, () => {
  m.i18n.setLocale('es');
  const html = h(m.ProfileMenu, { ...PROFILE, open: true });
  assert.match(html, /aria-expanded="true"/);
  assert.match(html, /role="dialog"[^>]*aria-label="Perfil"/);
  for (const txt of ['admin', 'Cambiar foto', 'Idioma', 'Tema', 'Automático', 'Preferencias', 'Integración', 'Cuenta', 'Salir']) assert.ok(html.includes(txt), txt);
  assert.ok(!html.includes('Quitar foto'));
  assert.match(html, /<select/);
  assert.match(html, /type="file"[^>]*accept="image\/jpeg,image\/png,image\/webp"|accept="image\/jpeg,image\/png,image\/webp"[^>]*type="file"/);
});

test('ProfileMenu: con foto se pinta la imagen versionada y aparece «Quitar foto»; el menú no muestra la versión', { skip }, () => {
  m.i18n.setLocale('es');
  const html = h(m.ProfileMenu, { ...PROFILE, open: true, profile: { name: '', photo: { version: 'abc' } } });
  assert.ok(html.includes('src="/api/profile/photo?v=abc"'));
  assert.ok(html.includes('Quitar foto'));
  assert.ok(html.includes('<strong class="profile-name">Checkpoint</strong>')); // el servidor no dio nombre: marca
  assert.ok(!html.includes('Versión'));
});
