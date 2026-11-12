// Subpestañas de Configuración (General, Biblioteca, Lanzadores): render a HTML (esbuild + react-dom/server, sin DOM).
// Cubre el contenedor (por defecto, paneles conservados, barra de guardar solo en Biblioteca, punto de aviso) y el contrato de ui/Tabs.
import test from 'node:test';
import assert from 'node:assert/strict';
import { bundle, readSrc } from '../helpers/bundle.mjs';

const { mod: m, skip } = await bundle(
  `import React from 'react';
  import { renderToStaticMarkup } from 'react-dom/server';
  import { i18n } from '#src/hooks/useI18n.js';
  import Settings from '#src/pages/Settings.jsx';
  import Launchers from '#src/pages/settings/Launchers.jsx';
  import { Tabs } from '#src/components/ui/index.js';
  export { React, renderToStaticMarkup, i18n, Settings, Launchers, Tabs };`,
  { navigator: true, tag: 'ckpt-subtabs' },
);

const has = (h, s) => h.includes(s);
const CLEAN = {
  version: 'v1',
  config: {
    max_versions: 5,
    devices: { 'pc-1a2b3c4d': { name: 'Mi PC', host: '10.0.0.1', user: 'u', os: 'linux', port: 22 } },
    games: {},
  },
};
// max_versions fuera de rango: error local, el borrador cuenta como «con cambios» desde el primer render.
const DIRTY = { version: 'v1', config: { ...CLEAN.config, max_versions: 99999 } };
const S = (o = {}, lang = 'es') => {
  m.i18n.setLocale(lang);
  return m.renderToStaticMarkup(
    m.React.createElement(m.Settings, {
      loaded: CLEAN,
      stale: false,
      configError: null,
      runtime: 'host',
      platform: 'linux',
      onApplied() {},
      onReload() {},
      onDirty() {},
      updates: null,
      onUpdates() {},
      ...o,
    }),
  );
};
// Panel (div role=tabpanel) cuya pestaña lleva ese texto: devuelve su etiqueta de apertura.
const panelTag = (h, label) => {
  const tabId = new RegExp(`id="([^"]+)"[^>]*>(?:<span class="uitab-full">)?${label}`).exec(h)?.[1];
  assert.ok(tabId, `pestaña ${label}`);
  return new RegExp(`<div[^>]*aria-labelledby="${tabId}"[^>]*>`).exec(h)?.[0];
};

test('Configuración: tres subpestañas (las etiquetas largas y cortas, es y en), barra superior intacta', { skip }, () => {
  const h = S();
  assert.equal((h.match(/role="tab"/g) || []).length, 3);
  for (const t of ['Ajustes generales', 'Biblioteca de juegos', 'Lanzadores', '>General<', '>Biblioteca<']) assert.ok(has(h, t), t);
  assert.ok(has(h, 'class="uitabs subnav"') && has(h, 'aria-label="Subpestañas de Configuración"'));
  assert.ok(!has(h, 'Notificaciones'), 'Notificaciones la crea otra tarjeta');
  const e = S({}, 'en');
  for (const t of ['General settings', 'Game library', '>Library<', 'Launchers']) assert.ok(has(e, t), t);
});

test('Por defecto abre General; con firstUse (sin dispositivos) abre Biblioteca', { skip }, () => {
  const h = S();
  assert.match(h, /aria-selected="true"[^>]*tabindex="0"[^>]*>(<span class="uitab-full">)?Ajustes generales/);
  assert.ok(!has(panelTag(h, 'Ajustes generales'), 'hidden') && has(panelTag(h, 'Biblioteca de juegos'), 'hidden=""'));
  const f = S({ firstUse: true });
  assert.match(f, /aria-selected="true"[^>]*tabindex="0"[^>]*>(<span class="uitab-full">)?Biblioteca de juegos/);
  assert.ok(!has(panelTag(f, 'Biblioteca de juegos'), 'hidden') && has(panelTag(f, 'Ajustes generales'), 'hidden=""'));
});

test(
  'Los paneles General y Biblioteca se conservan montados (ocultos, no desmontados); Lanzadores no se monta hasta abrirla',
  { skip },
  () => {
    const h = S();
    assert.ok(has(h, 'Sincronización automática') || has(h, 'autosync'), 'General montado');
    assert.ok(has(h, 'Dispositivos') && has(h, 'Mi PC'), 'Biblioteca montada aunque oculta (el borrador sobrevive)');
    assert.ok(!has(h, 'class="launcher"') && !has(h, 'launchers-panel'), 'Lanzadores sin montar (sin peticiones)');
    assert.ok(has(panelTag(h, 'Lanzadores'), 'hidden=""'));
  },
);

test('La barra de guardar solo está en Biblioteca (dentro de su panel); General y Lanzadores no la tienen', { skip }, () => {
  const h = S();
  assert.equal((h.match(/class="actionbar"/g) || []).length, 1);
  const open = h.indexOf(panelTag(h, 'Biblioteca de juegos'));
  const next = h.indexOf(panelTag(h, 'Lanzadores'));
  const bar = h.indexOf('class="actionbar"');
  assert.ok(open >= 0 && bar > open && (next < 0 || bar < next), 'la barra va dentro del panel de Biblioteca');
  const src = readSrc('pages', 'settings', 'General.jsx');
  assert.ok(!/actionbar|useConfigDraft/.test(src));
});

test('Punto de aviso accesible en Biblioteca solo con cambios sin guardar', { skip }, () => {
  assert.ok(!has(S(), 'uitab-dot'));
  const d = S({ loaded: DIRTY });
  assert.ok(has(d, 'class="uitab-dot" aria-hidden="true"') && has(d, '<span class="sr-only">Cambios sin guardar en Biblioteca</span>'));
  assert.equal((d.match(/uitab-dot/g) || []).length, 1);
  assert.ok(has(S({ loaded: DIRTY }, 'en'), 'Unsaved changes in Library'));
});

test('Lanzadores: solo el contenido (sin plegado Mostrar/Ocultar) y el botón de GameCard ya no existe', { skip }, () => {
  m.i18n.setLocale('es');
  const h = m.renderToStaticMarkup(m.React.createElement(m.Launchers, { games: [], selected: '', onSelect() {} }));
  assert.ok(has(h, 'Lanzadores</h3>') && !has(h, 'Mostrar') && !has(h, 'Ocultar') && !has(h, 'aria-expanded'));
  assert.ok(!/onShowLaunchers|showLaunchers|launchers-section|launchersOpen/.test(readSrc('pages', 'Settings.jsx')));
});

test('ui/Tabs keepMounted: todos los paneles, inactivos con hidden; null no se pinta; dot y short', { skip }, () => {
  m.i18n.setLocale('es');
  const tabs = [
    { id: 'a', label: 'Larga A', short: 'A', dot: 'Aviso' },
    { id: 'b', label: 'B' },
  ];
  const h = m.renderToStaticMarkup(
    m.React.createElement(m.Tabs, {
      tabs,
      value: 'b',
      onChange() {},
      label: 'L',
      keepMounted: true,
      variant: 'subnav',
      panels: { a: 'PANEL-A', b: 'PANEL-B' },
    }),
  );
  assert.equal((h.match(/role="tabpanel"/g) || []).length, 2);
  assert.match(h, /<div class="uitabs-panel" role="tabpanel"[^>]*hidden=""[^>]*>PANEL-A</);
  assert.ok(has(h, 'PANEL-B') && !/hidden=""[^>]*>PANEL-B/.test(h));
  assert.ok(has(h, '<span class="uitab-full">Larga A</span><span class="uitab-short">A</span>') && has(h, 'Aviso'));
  const n = m.renderToStaticMarkup(
    m.React.createElement(m.Tabs, { tabs, value: 'b', onChange() {}, label: 'L', keepMounted: true, panels: { a: null, b: 'X' } }),
  );
  assert.ok(!has(n, 'class="uitabs subnav"') && /hidden=""[^>]*><\/div>/.test(n));
});
