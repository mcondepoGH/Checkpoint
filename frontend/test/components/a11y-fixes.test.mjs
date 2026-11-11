// Arreglos de accesibilidad que sustituyeron a los eslint-disable de jsx-a11y: roles, atributos y teclado.
// Sin jsdom: se renderiza a HTML (esbuild + react-dom/server) y los manejadores se capturan interceptando
// React.createElement para llamarlos con eventos falsos. Si esbuild no está disponible, se salta.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { bundle, SRC, readSrc } from '../helpers/bundle.mjs';
import { readFlat } from '../helpers/source.mjs';

const { mod: m, skip } = await bundle(
  `import React from 'react';
  import { renderToStaticMarkup } from 'react-dom/server';
  import { i18n } from '#src/hooks/useI18n.js';
  import { Tabs, CopyBox } from '#src/components/ui/index.js';
  import Modal from '#src/components/ui/Modal.jsx';
  import UpdateDialog from '#src/components/updates/UpdateDialog.jsx';
  import Login from '#src/pages/Login.jsx';
  import { KeyHelp } from '#src/components/keyhelp/PublicKey.jsx';
  export { React, renderToStaticMarkup, i18n, Tabs, CopyBox, Modal, UpdateDialog, Login, KeyHelp };`,
  { navigator: true, tag: 'ckpt-a11y' },
);

// Renderiza `el` y devuelve { html, seen }: seen = props de cada elemento creado (tipo string) durante el render.
function render(el) {
  const seen = [];
  const orig = m.React.createElement;
  m.React.createElement = (type, props, ...kids) => {
    if (typeof type === 'string') seen.push({ type, props: props || {} });
    return orig(type, props, ...kids);
  };
  try {
    return { html: m.renderToStaticMarkup(el), seen };
  } finally {
    m.React.createElement = orig;
  }
}
const ev = (key) => ({
  key,
  calls: [],
  preventDefault() {
    this.calls.push('prevent');
  },
  stopPropagation() {
    this.calls.push('stop');
  },
});

test('ui/Tabs: el teclado va en cada pestaña (no en el tablist) y mueve la selección', { skip }, () => {
  const picked = [];
  const tabs = [
    { id: 'a', label: 'A' },
    { id: 'b', label: 'B' },
    { id: 'c', label: 'C' },
  ];
  const { seen } = render(m.React.createElement(m.Tabs, { tabs, value: 'a', onChange: (id) => picked.push(id), label: 'L' }, 'x'));
  const list = seen.find((s) => s.props.role === 'tablist');
  assert.equal(list.props.onKeyDown, undefined);
  const tabEls = seen.filter((s) => s.props.role === 'tab');
  assert.equal(tabEls.length, 3);
  for (const t of tabEls) assert.equal(typeof t.props.onKeyDown, 'function');
  const k = ev('ArrowRight');
  tabEls[0].props.onKeyDown(k);
  assert.deepEqual(picked, ['b']);
  assert.deepEqual(k.calls, ['prevent']);
  tabEls[0].props.onKeyDown(ev('End'));
  tabEls[0].props.onKeyDown(ev('ArrowLeft'));
  assert.deepEqual(picked, ['b', 'c', 'c']);
  const other = ev('a');
  tabEls[0].props.onKeyDown(other);
  assert.deepEqual(other.calls, []);
  assert.equal(picked.length, 3);
});

test('PublicKey Tabs (keytabs): onKeyDown en cada pestaña, tablist sin manejador, tabindex itinerante', { skip }, () => {
  const { seen, html } = render(m.React.createElement(m.KeyHelp, { open: true, sys: 'Linux', pubKey: 'k' }));
  const lists = seen.filter((s) => s.props.role === 'tablist');
  assert.equal(lists.length, 2); // sistema y distribución
  for (const l of lists) assert.equal(l.props.onKeyDown, undefined);
  const tabEls = seen.filter((s) => s.props.role === 'tab');
  assert.equal(tabEls.length, 4);
  for (const t of tabEls) assert.equal(typeof t.props.onKeyDown, 'function');
  const k = ev('Home');
  tabEls[0].props.onKeyDown(k);
  assert.deepEqual(k.calls, ['prevent']);
  const none = ev('Enter');
  tabEls[0].props.onKeyDown(none);
  assert.deepEqual(none.calls, []);
  assert.match(html, /role="tab"[^>]*tabindex="-1"/);
});

test('Modal: el fondo es presentation y recoge el teclado; el diálogo no lleva manejador de teclado', { skip }, () => {
  let closed = 0;
  const { html, seen } = render(m.React.createElement(m.Modal, { title: 'T', onClose: () => closed++ }, 'cuerpo'));
  assert.match(html, /^<div class="modal" role="presentation">/);
  assert.match(html, /role="dialog" aria-modal="true" aria-labelledby="[^"]+" tabindex="-1"/);
  const back = seen.find((s) => s.props.className === 'modal');
  const dlg = seen.find((s) => s.props.role === 'dialog');
  assert.equal(dlg.props.onKeyDown, undefined);
  const k = ev('Escape');
  back.props.onKeyDown(k);
  assert.equal(closed, 1);
  assert.deepEqual(k.calls, ['stop']);
  // clic de ratón: solo en el propio fondo
  const bg = {};
  back.props.onMouseDown({ target: bg, currentTarget: bg });
  back.props.onMouseDown({ target: {}, currentTarget: bg });
  assert.equal(closed, 2);
});

test('Modal: Tab atrapa el foco desde el fondo (último -> primero, Mayús+Tab primero -> último)', { skip }, () => {
  const { seen } = render(m.React.createElement(m.Modal, { title: 'T', onClose() {} }, 'x'));
  const back = seen.find((s) => s.props.className === 'modal');
  const dlg = seen.find((s) => s.props.role === 'dialog');
  const first = {
    focus() {
      this.f = 1;
    },
  };
  const last = {
    focus() {
      this.f = 1;
    },
  };
  const root = { querySelectorAll: () => [first, last] };
  // el ref del diálogo se rellena como lo haría React
  dlg.props.ref.current = root;
  globalThis.document = { activeElement: last };
  try {
    const t1 = {
      key: 'Tab',
      shiftKey: false,
      preventDefault() {
        this.p = 1;
      },
    };
    back.props.onKeyDown(t1);
    assert.ok(t1.p && first.f);
    first.f = 0;
    globalThis.document.activeElement = first;
    const t2 = {
      key: 'Tab',
      shiftKey: true,
      preventDefault() {
        this.p = 1;
      },
    };
    back.props.onKeyDown(t2);
    assert.ok(t2.p && last.f);
  } finally {
    delete globalThis.document;
  }
});

test('Contenedores de ProfileMenu y WatchSummary: role=presentation y siguen recogiendo Escape/blur', () => {
  for (const [f, cls] of [
    [['components', 'profile', 'ProfileMenu.jsx'], 'profile'],
    [['components', 'watch', 'WatchSummary.jsx'], 'watch-summary'],
  ]) {
    const src = readFlat(path.join(SRC, ...f));
    assert.match(
      src,
      new RegExp(`<div className="${cls}" role="presentation" ref=\\{wrap\\} onKeyDown=\\{onKeyDown\\} onBlur=\\{onBlur\\}>`),
    );
  }
});

test('CopyBox: textbox de solo lectura enfocable sobre un div (no sobre code)', { skip }, () => {
  const { html } = render(m.React.createElement(m.CopyBox, { value: 'v', label: 'L', describedBy: 'h' }));
  assert.match(
    html,
    /<div id="[^"]+" class="copybox-field" tabindex="0" role="textbox" aria-readonly="true" aria-multiline="true" aria-label="L" aria-describedby="h">v<\/div>/,
  );
  assert.ok(!html.includes('<code'));
});

test('UpdateDialog: las notas con scroll son una región con nombre y enfocable', { skip }, () => {
  const info = { actual: '1.0.0', ultima: '1.1.0', notas: 'notas', url: null, canal: 'stable', prerelease: false };
  const { html } = render(m.React.createElement(m.UpdateDialog, { info, onClose() {} }));
  assert.match(html, /<div class="update-notes" role="region" aria-label="[^"]+" tabindex="0">notas<\/div>/);
});

test('Login: sin autoFocus; el foco inicial lo gestiona un ref + efecto', { skip }, () => {
  const { html } = render(m.React.createElement(m.Login, { onDone() {} }));
  assert.ok(!/autofocus/i.test(html));
  const src = readFlat(path.join(SRC, 'pages', 'Login.jsx'));
  assert.match(src, /useEffect\(\(\) => \{ userRef\.current\?\.focus\(\); \}, \[\]\)/);
  assert.match(src, /<input ref=\{userRef\} value=\{user\}/);
});

test('No quedan eslint-disable de jsx-a11y en src', () => {
  const found = [];
  const walk = (d) => {
    for (const e of fs.readdirSync(d, { withFileTypes: true })) {
      const p = path.join(d, e.name);
      if (e.isDirectory()) walk(p);
      else if (/\.(jsx?|mjs)$/.test(e.name) && /eslint-disable[^\n]*jsx-a11y/.test(readSrc(path.relative(SRC, p)))) found.push(p);
    }
  };
  walk(SRC);
  assert.deepEqual(found, []);
});
