// Menú del perfil reorganizado: orden de grupos, filas de preferencias, API key plegable, entrada de actualización, a11y y paridad es/en.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { bundle, SRC } from './helpers/bundle.mjs';

const { mod: m, skip } = await bundle(`import React from 'react';
  import { renderToStaticMarkup } from 'react-dom/server';
  import { i18n } from '#src/hooks/useI18n.js';
  import ProfileMenu from '#src/components/ProfileMenu.jsx';
  import ApiKeySection from '#src/components/ApiKeySection.jsx';
  export { React, renderToStaticMarkup, i18n, ProfileMenu, ApiKeySection };`, { navigator: true, tag: 'ckpt-profmenu' });
const UPD = { actual: '1.0.0', ultima: '1.1.0', hay_actualizacion: true, habilitado: true, aplicable: true };
const menu = (o = {}, lang = 'es') => {
  m.i18n.setLocale(lang);
  return m.renderToStaticMarkup(m.React.createElement(m.ProfileMenu, {
    profile: { name: 'admin', photo: null }, theme: 'auto', effectiveTheme: 'dark', onCycleTheme() {}, onLogout() {}, onPhoto() {}, open: true, ...o,
  }));
};
const at = (h, s) => { const i = h.indexOf(s); assert.ok(i >= 0, `falta ${s}`); return i; };
const read = (...p) => fs.readFileSync(path.join(SRC, ...p), 'utf8');

test('orden: identidad, actualización, Preferencias, Integración, Cuenta (salir)', { skip }, () => {
  const h = menu({ updates: UPD });
  const order = ['profile-head', 'Cambiar foto', 'profile-update', 'Preferencias', 'Idioma', 'Tema', 'Integración', 'class="apikey"', 'Cuenta', 'Salir'];
  const pos = order.map((s) => at(h, s));
  assert.deepEqual(pos, [...pos].sort((a, b) => a - b), order.join(' < '));
});

test('enlace «Documentación de la API»: tras la API key, antes de Cuenta, a /api/docs en pestaña nueva (es y en)', { skip }, () => {
  for (const [lang, txt, acct] of [['es', 'Documentación de la API', 'Cuenta'], ['en', 'API documentation', 'Account']]) {
    const h = menu({}, lang);
    const a = h.match(/<a [^>]*href="\/api\/docs"[^>]*>/);
    assert.ok(a, `falta el enlace (${lang})`);
    assert.match(a[0], /target="_blank"/); assert.match(a[0], /rel="noopener"/); assert.match(a[0], /class="[^"]*profile-row/);
    const i = at(h, a[0]);
    assert.ok(i > at(h, 'class="apikey"') && i < at(h, `>${acct}<`), lang);
    assert.ok(h.slice(i).startsWith(a[0]) && h.slice(i, i + 800).includes(txt), lang);
    assert.ok(h.slice(i, i + 300).includes('class="ico"'), 'lleva icono');
  }
});

test('sin actualización no hay entrada; con ella va justo bajo la identidad y antes de Preferencias', { skip }, () => {
  assert.ok(!menu({ updates: null }).includes('profile-update'));
  const h = menu({ updates: UPD });
  assert.ok(at(h, 'profile-update') > at(h, 'profile-head') && at(h, 'profile-update') < at(h, 'Preferencias'));
  assert.ok(h.includes('Actualizar a v1.1.0'));
});

test('Idioma y Tema comparten patrón de fila (icono + etiqueta + valor a la derecha)', { skip }, () => {
  const h = menu();
  const lang = h.slice(at(h, 'profile-row profile-pref'), at(h, '</select>'));
  assert.match(lang, /class="ico"/); assert.match(lang, /<label[^>]*class="profile-row-label"[^>]*>Idioma<\/label>/); assert.match(lang, /<select[^>]*class="profile-row-value"/);
  const theme = h.slice(h.indexOf('profile-row profile-pref', at(h, '</select>')), at(h, 'Integración'));
  assert.match(theme, /class="ico"/); assert.match(theme, /profile-row-label">Tema</); assert.match(theme, /profile-row-value">automático</);
  assert.match(h, /<label for="([^"]+)"[^>]*>Idioma<\/label><select id="\1"/); // etiqueta asociada al select
});

test('API key: plegada por defecto (aria-expanded=false, contenido montado pero hidden); defaultOpen la despliega', { skip }, () => {
  const h = menu();
  const sec = h.slice(at(h, '<section class="apikey"'));
  assert.match(sec, /<button[^>]*aria-expanded="false"[^>]*aria-controls="([^"]+)"/);
  const id = sec.match(/aria-controls="([^"]+)"/)[1];
  assert.match(sec, new RegExp(`<div id="${id.replace(/:/g, '\\:')}" class="apikey-body" hidden="">`));
  m.i18n.setLocale('es');
  const open = m.renderToStaticMarkup(m.React.createElement(m.ApiKeySection, { initial: { loaded: true, exists: true, key: 'ck_x' }, defaultOpen: true, insecure: false }));
  assert.match(open, /aria-expanded="true"/); assert.ok(!open.includes('hidden=""'));
  assert.ok(open.includes('Regenerar') && open.includes('ck_x'));
});

test('a11y: grupos con role=group y aria-labelledby apuntando a su rótulo; popup no modal', { skip }, () => {
  const h = menu();
  const groups = [...h.matchAll(/<div class="profile-group" role="group" aria-labelledby="([^"]+)"><h3 id="([^"]+)"[^>]*>([^<]+)<\/h3>/g)];
  assert.deepEqual(groups.map((g) => g[3]), ['Preferencias', 'Integración', 'Cuenta']);
  for (const g of groups) assert.equal(g[1], g[2]);
  assert.match(h, /role="dialog"[^>]*aria-label="Perfil"/);
  assert.doesNotMatch(h, /aria-modal/);
  assert.match(h, /tabindex="-1"/);
});

test('paridad es/en: claves nuevas presentes y en inglés sin español', { skip }, () => {
  for (const lang of ['es', 'en']) {
    const j = JSON.parse(read('locales', `${lang}.json`)).profile;
    assert.ok(j.themeLabel && j.group.prefs && j.group.integration && j.group.account, lang);
    assert.equal(j.theme, undefined, 'profile.theme (antigua) retirada');
  }
  const en = menu({ updates: UPD }, 'en');
  for (const s of ['Preferences', 'Language', 'Theme', 'Integration', 'Account', 'Update to v1.1.0']) assert.ok(en.includes(s), s);
  assert.doesNotMatch(en.replace(/<[^>]+>/g, ' '), /Preferencias|Idioma|Integración|Cuenta|Salir|Actualizar/);
  m.i18n.setLocale('es');
});

test('estilos: filas de 44 px, anchos y chip compacto sin tamaños sueltos', () => {
  const prof = read('styles', '_profile.scss');
  assert.match(prof, /\$touch-profile: 44px/);
  assert.match(prof, /\.profile-group \{[^}]*margin-top: 10px; margin-bottom: 10px;/);
  assert.match(prof, /\.apikey-body \{[^}]*&\[hidden\] \{ display: none; \}/);
  assert.doesNotMatch(prof, /font-size: \d/);
  assert.match(read('styles', '_variables.scss'), /\$bp-xs-tabs: 400px/);
  assert.match(read('styles', '_layout.scss'), /@media \(max-width: v\.\$bp-xs-tabs\) \{\s*\.tab \{ padding: 0 \.3rem; \}/);
  assert.match(read('styles', 'ui', '_watch.scss'), /@media \(max-width: v\.\$bp-xxs\) \{\s*\.watch-summary \.watch-toggle \{ padding: 0 \.3rem; gap: \.2rem; \}/);
  assert.match(read('styles', 'ui', '_watch.scss'), /min-height: \$touch-watch/); // el alto de 44 px del chip se mantiene
});

test('Esc devuelve el foco al botón y fuera cierra (contrato en el código)', () => {
  const src = read('components', 'ProfileMenu.jsx');
  assert.match(src, /e\.key === 'Escape'[^}]*btn\.current\?\.focus\(\)/);
  assert.match(src, /addEventListener\('pointerdown', outside\)/);
  assert.match(src, /aria-haspopup="dialog"/);
  assert.match(src, /pop\.current\?\.focus\(\)/);
});
