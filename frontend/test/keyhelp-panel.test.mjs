// Panel de ayuda de la clave pública, abierto y renderizado a HTML (es y en) para Windows, Debian/Ubuntu y Arch:
// un comando por card, etiquetas de las alternativas, clave interpolada o marcador, y «Copiar» que copia SOLO su comando.
// Sin jsdom: el botón se sustituye por un doble que registra sus props, y el clic se simula llamando a su `onClick`
// con un portapapeles falso. Usa esbuild (viene con Vite); si no está disponible el test se salta.
import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { osSteps } from '#src/keyhelpSteps.js';
import { bundle, SRC } from './helpers/bundle.mjs';

// Los botones de `ui` se sustituyen por un stub que registra sus props; el resto de `ui` es el real.
const stubButtons = {
  name: 'stub-buttons',
  setup(b) {
    b.onResolve({ filter: /ui\/index\.js$/ }, () => ({ path: 'ui', namespace: 'stub' }));
    b.onLoad({ filter: /.*/, namespace: 'stub' }, () => ({
      resolveDir: SRC,
      loader: 'jsx',
      contents: `import React, { forwardRef } from 'react';
        export { default as Alert } from '#src/components/ui/Alert.jsx';
        export const Button = forwardRef(function Button({ variant, className, iconOnly, children, ...rest }, ref) {
          (globalThis.__buttons ||= []).push({ ...rest, className, children });
          return <button type="button" className={className} {...rest}>{children}</button>;
        });`,
    }));
  },
};
const { mod: m, skip } = await bundle(`import React from 'react';
  import { renderToStaticMarkup } from 'react-dom/server';
  import { i18n } from '#src/hooks/useI18n.js';
  import { KeyHelp } from '#src/components/PublicKey.jsx';
  export { React, renderToStaticMarkup, i18n, KeyHelp };`, { plugins: [stubButtons], tag: 'ckpt-keyhelp' });

const KEY = 'ssh-ed25519 AAAATESTKEY checkpoint';
const ONE_LINE_EXAMPLE = 'ssh-ed25519 AAAAC3Nza...XXXX checkpoint';
const CASES = [['Windows', 'Debian / Ubuntu'], ['Linux', 'Debian / Ubuntu'], ['Linux', 'Arch Linux']];
const unesc = (s) => s.replace(/&quot;/g, '"').replace(/&#x27;/g, "'").replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');

// Renderiza el panel abierto y devuelve el HTML y los botones «Copiar» (los de CodeBlock) en orden de aparición.
function panel({ sys, distro, lang = 'es', pubKey = KEY, open = true }) {
  m.i18n.setLocale(lang);
  globalThis.__buttons = [];
  const html = m.renderToStaticMarkup(m.React.createElement(m.KeyHelp, { pubKey, open, sys, distro }, m.React.createElement('p', null, 'intro')));
  const copyLabel = lang === 'es' ? 'Copiar' : 'Copy';
  const copyBtns = globalThis.__buttons.filter((b) => b.role !== 'tab' && b.children === copyLabel);
  const codes = [...html.matchAll(/<pre><code>([\s\S]*?)<\/code><\/pre>/g)].map((x) => unesc(x[1]));
  return { html, codes, copyBtns };
}

const expected = (sys, distro, k = KEY) => osSteps(sys, distro, k).flatMap((s) => s.cmds.map((c) => c.text));

test('panel cerrado por defecto: sin cards ni comandos; abierto con `open`', { skip }, () => {
  const closed = panel({ sys: 'Linux', distro: 'Arch Linux', open: false });
  assert.ok(!closed.html.includes('<pre>') && !closed.html.includes('id="keyhelp-panel"') && closed.html.includes('aria-expanded="false"'));
  const open = panel({ sys: 'Linux', distro: 'Arch Linux' });
  assert.ok(open.html.includes('id="keyhelp-panel"') && open.html.includes('aria-expanded="true"'));
});

for (const lang of ['es', 'en']) {
  for (const [sys, distro] of CASES) {
    test(`${lang} / ${sys}${sys === 'Linux' ? ' ' + distro : ''}: una card por comando, un comando exacto por <code>`, { skip }, () => {
      const { html, codes, copyBtns } = panel({ sys, distro, lang });
      const steps = osSteps(sys, distro, KEY);
      const cmds = expected(sys, distro);
      // nº de cards por paso y sistema (cada paso es un <li class="keysub"> con tantas .keycmd como comandos)
      const subs = html.split('<li class="keysub">').slice(1);
      assert.equal(subs.length, steps.length);
      subs.forEach((chunk, i) => assert.equal((chunk.split('</li>')[0].match(/<pre><code>/g) || []).length, steps[i].cmds.length, steps[i].id));
      // los <code> de las cards son exactamente los comandos, en orden, más el ejemplo de una línea
      assert.deepEqual(codes, [...cmds, ONE_LINE_EXAMPLE]);
      for (const c of codes) assert.ok(!c.includes('\n'), `salto de línea en «${c}»`);
      for (const c of cmds) assert.ok(!/(^|\s)# /.test(c), `comentario en «${c}»`);
      // «Copiar»: uno por comando + el del ejemplo de una línea (el de la clave pública sale solo con la clave cargada, fuera de KeyHelp)
      assert.equal(copyBtns.length, cmds.length + 1);
      assert.equal((html.match(lang === 'es' ? /<button[^>]*>Copiar</g : /<button[^>]*>Copy</g) || []).length, cmds.length + 1);
    });
  }
}

test('Arch: ufw y firewalld con su etiqueta (es y en), el paso pide elegir una; Debian/Windows sin etiquetas', { skip }, () => {
  for (const [lang, ufw, fw, pick] of [['es', 'Si usas ufw', 'Si usas firewalld', 'Elige solo una'], ['en', 'If you use ufw', 'If you use firewalld', 'Pick only one']]) {
    const { html } = panel({ sys: 'Linux', distro: 'Arch Linux', lang });
    assert.equal((html.match(/class="keycmd-label"/g) || []).length, 2, lang);
    assert.ok(html.includes(`<p class="keycmd-label">${ufw}</p>`), `${lang}: ${ufw}`);
    assert.ok(html.includes(`<p class="keycmd-label">${fw}</p>`), `${lang}: ${fw}`);
    assert.ok(html.indexOf(ufw) < html.indexOf(fw));
    assert.ok(html.toLowerCase().includes(pick.toLowerCase()), `${lang}: ${pick}`);
    // cada etiqueta va justo antes de SU comando
    const ufwCmd = 'sudo ufw allow 22/tcp';
    const fwCmd = 'sudo firewall-cmd --permanent --add-service=ssh &amp;&amp; sudo firewall-cmd --reload';
    assert.ok(html.indexOf(ufw) < html.indexOf(`<code>${ufwCmd}</code>`) && html.indexOf(`<code>${ufwCmd}</code>`) < html.indexOf(fw));
    assert.ok(html.indexOf(fw) < html.indexOf(`<code>${fwCmd}</code>`));
    assert.ok(!html.includes(`<code>${ufwCmd}\n`) && !/# /.test(html.match(/<pre><code>[\s\S]*?<\/code>/g).join('')));
    for (const [s, d] of [['Linux', 'Debian / Ubuntu'], ['Windows', 'Debian / Ubuntu']]) assert.ok(!panel({ sys: s, distro: d, lang }).html.includes('keycmd-label'));
  }
});

test('clave interpolada en los comandos que la llevan; sin clave, el marcador (es y en) y el aviso', { skip }, () => {
  for (const [sys, distro, n] of [['Windows', 'Debian / Ubuntu', 2], ['Linux', 'Debian / Ubuntu', 1], ['Linux', 'Arch Linux', 1]]) {
    const w = panel({ sys, distro });
    assert.equal(w.codes.filter((c) => c.includes(KEY)).length, n, `${sys}/${distro}`);
    assert.ok(!w.html.includes('PEGA_AQUÍ_LA_CLAVE'));
  }
  for (const [lang, ph] of [['es', 'PEGA_AQUÍ_LA_CLAVE'], ['en', null]]) {
    m.i18n.setLocale(lang);
    const marker = unesc(panel({ sys: 'Linux', distro: 'Arch Linux', lang, pubKey: '' }).html.match(/<code>echo &quot;([\s\S]*?)&quot; &gt;&gt;/)?.[1] ?? '');
    assert.ok(marker && !marker.includes('ssh-ed25519'), lang);
    if (ph) assert.equal(marker, ph);
    const html = panel({ sys: 'Linux', distro: 'Arch Linux', lang, pubKey: '' }).html;
    assert.ok(html.includes(marker) && html.includes('class="muted"'));
  }
  // con clave, no sale el aviso de «aún no hay clave»
  assert.ok(!panel({ sys: 'Linux', distro: 'Arch Linux' }).html.includes('Aún no hay clave visible'));
  assert.ok(panel({ sys: 'Linux', distro: 'Arch Linux', pubKey: '' }).html.includes('Aún no hay clave visible'));
});

test('clic en «Copiar»: cada card copia SOLO su comando exacto (sin los de al lado, sin etiqueta ni la clave sola)', { skip }, async () => {
  const realTimeout = globalThis.setTimeout;
  const realNav = Object.getOwnPropertyDescriptor(globalThis, 'navigator');
  const written = [];
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: { clipboard: { writeText: async (t) => { written.push(t); } } } });
  globalThis.setTimeout = () => 0; // sin el temporizador de 2 s del «Copiado»
  try {
    for (const lang of ['es', 'en']) for (const [sys, distro] of CASES) {
      const { copyBtns, codes } = panel({ sys, distro, lang });
      written.length = 0;
      for (const b of copyBtns) await b.onClick();
      assert.deepEqual(written, codes, `${lang} ${sys} ${distro}`); // uno por botón, en orden, texto exacto
      assert.equal(new Set(written).size, written.length); // ningún comando repetido: cada botón, el suyo
    }
    // Arch: el botón de ufw copia solo ufw, el de firewalld solo firewalld
    const { copyBtns } = panel({ sys: 'Linux', distro: 'Arch Linux' });
    written.length = 0;
    await copyBtns[2].onClick();
    assert.deepEqual(written, ['sudo ufw allow 22/tcp']);
    written.length = 0;
    await copyBtns[3].onClick();
    assert.deepEqual(written, ['sudo firewall-cmd --permanent --add-service=ssh && sudo firewall-cmd --reload']);
  } finally {
    globalThis.setTimeout = realTimeout;
    if (realNav) Object.defineProperty(globalThis, 'navigator', realNav); else delete globalThis.navigator;
    m.i18n.setLocale('es');
  }
});
