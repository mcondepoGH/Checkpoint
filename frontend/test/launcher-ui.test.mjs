// Tabs, CopyBox y la sección Lanzadores (panel único con selector de juego), renderizados a HTML (esbuild + react-dom/server).
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
        import { i18n } from './useI18n.js';
        import LauncherBlock from './components/LauncherBlock.jsx';
        import LaunchersPanel from './components/LaunchersPanel.jsx';
        import GameCard from './components/GameCard.jsx';
        import { Tabs, CopyBox } from './components/ui/index.js';
        import { EntryMessage } from './components/AutoSyncLog.jsx';
        export { React, renderToStaticMarkup, i18n, LauncherBlock, LaunchersPanel, GameCard, Tabs, CopyBox, EntryMessage };`,
      resolveDir: SRC, loader: 'jsx',
    },
    bundle: true, write: false, format: 'esm', platform: 'node', jsx: 'transform',
    define: { 'process.env.NODE_ENV': '"production"' },
    loader: { '.svg': 'dataurl' },
    banner: { js: "import { createRequire } from 'node:module'; const require = createRequire(import.meta.url);" },
    logLevel: 'silent',
  });
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ckpt-launcher-'));
  const file = path.join(dir, 'bundle.mjs');
  fs.writeFileSync(file, out.outputFiles[0].text);
  globalThis.navigator ??= { languages: ['es'], language: 'es' };
  m = await import(pathToFileURL(file).href);
  fs.rmSync(dir, { recursive: true, force: true });
} catch (e) {
  skip = `esbuild no disponible: ${e.message}`;
}
const KEY = 'ck_AbC123xyz';
const has = (h, s) => h.includes(s);
const R = (C, props, lang = 'es') => { m.i18n.setLocale(lang); return m.renderToStaticMarkup(m.React.createElement(m[C], props)); };
const DEVS = [{ id: 'mi-pc', name: 'Mi PC' }, { id: 'deck', name: 'Deck' }];
const game = (o = {}) => ({ sel: 'juego-1a2b3c4d', id: 'juego-1a2b3c4d', name: 'Juego', process: 'juego.exe', devices: DEVS, ...o });
const OTHER = { sel: 'otro-9f8e7d6c', id: 'otro-9f8e7d6c', name: 'Otro juego', process: 'otro.exe', devices: [{ id: 'mi-pc', name: 'Mi PC' }] };
const block = (initial, o = {}, lang = 'es') => R('LauncherBlock', { games: [game(o.game), OTHER], selected: 'juego-1a2b3c4d', onSelect() {}, active: true, defaultHub: 'http://hub.example.lan:8088', initial, now: new Date('2026-11-09T12:00:00Z'), ...o, game: undefined }, lang);
const WITH = { loaded: true, key: KEY };

test('Tabs: roles, aria-selected/controls y roving tabindex', { skip }, () => {
  const h = R('Tabs', { tabs: [{ id: 'a', label: 'A' }, { id: 'b', label: 'B' }], value: 'b', onChange() {}, label: 'Lista' }, 'es');
  const x = m.React.createElement(m.Tabs, { tabs: [{ id: 'a', label: 'A' }, { id: 'b', label: 'B' }], value: 'b', onChange() {}, label: 'Lista' }, 'contenido');
  const html = m.renderToStaticMarkup(x);
  assert.ok(has(html, 'role="tablist"') && has(html, 'aria-label="Lista"') && has(html, 'role="tabpanel"') && has(html, 'contenido'));
  assert.match(html, /<button[^>]*role="tab"[^>]*class="uitab"[^>]*aria-selected="false"[^>]*tabindex="-1"[^>]*>A</);
  assert.match(html, /<button[^>]*role="tab"[^>]*class="uitab active"[^>]*aria-selected="true"[^>]*tabindex="0"[^>]*>B</);
  const panel = /<div class="uitabs-panel" role="tabpanel" id="([^"]+)" aria-labelledby="([^"]+)"/.exec(html);
  assert.ok(panel && has(html, `aria-controls="${panel[1]}"`) && has(html, `id="${panel[2]}"`));
  assert.ok(h.length > 0);
});

test('CopyBox: caja de solo lectura + botón de icono con aria-label; copiado = check', { skip }, () => {
  const h = R('CopyBox', { value: 'curl -X POST "x"', label: 'Comando' });
  assert.ok(has(h, 'class="copybox"') && has(h, 'class="copybox-field"') && has(h, 'role="textbox"') && has(h, 'aria-readonly="true"') && has(h, 'aria-label="Comando"'));
  assert.ok(has(h, 'curl -X POST &quot;x&quot;'));
  assert.match(h, /<button[^>]*class="btn btn-icon copybox-copy"[^>]*aria-label="Copiar"/);
  assert.ok(has(h, 'M9 9h11') && !has(h, 'M20 6 9 17l-5-5'));
  const w = R('CopyBox', { value: 'x', label: 'C', what: 'comando de Steam' });
  assert.match(w, /<button[^>]*title="Copiar comando de Steam"[^>]*aria-label="Copiar comando de Steam"|<button[^>]*aria-label="Copiar comando de Steam"[^>]*title="Copiar comando de Steam"/);
  assert.match(R('CopyBox', { value: 'x', label: 'C', what: 'Steam command' }, 'en'), /aria-label="Copy Steam command"/);
  const c = R('CopyBox', { value: 'x', label: 'C', initialCopied: true });
  assert.match(c, /aria-label="Copiado"/);
  assert.ok(has(c, 'M20 6 9 17l-5-5') && has(c, 'role="status"'));
});

test('Lanzador con key: pestañas, selector de dispositivo, URL y comando Steam con %command%', { skip }, () => {
  const h = block(WITH, {}, 'es');
  for (const l of ['Steam / Steam Deck', 'Lutris', 'Heroic', 'Windows (Playnite)']) assert.ok(has(h, `>${l}</button>`), l);
  assert.ok(has(h, 'Opciones de lanzamiento') && has(h, 'El cierre lo vigila el hub solo'));
  assert.ok(has(h, 'Mi PC') && has(h, 'Deck') && has(h, 'Dispositivo del lanzador') && has(h, 'URL del hub'));
  assert.ok(has(h, `Bearer ${KEY}`) && has(h, 'http://hub.example.lan:8088/api/hook/juego-1a2b3c4d/opened?device=mi-pc') && has(h, '; %command%'));
  assert.equal(h.split(KEY).length - 1, 1);
  assert.ok(has(h, 'aria-label="Copiar comando de Steam / Steam Deck"'), h);
  assert.ok(has(R('LauncherBlock', { games: [game({ devices: DEVS })], selected: 'juego-1a2b3c4d', onSelect() {}, active: true, initial: WITH, defaultHub: 'http://x:1' }, 'en'), 'aria-label="Copy Steam / Steam Deck command"'));
});

test('Lanzador: sin key -> aviso informativo y ningún comando ni placeholder', { skip }, () => {
  const h = block({ loaded: true, key: null });
  assert.ok(has(h, 'Genera primero la API key en tu perfil.') && !has(h, 'curl') && !has(h, 'copybox') && !has(h, 'Bearer'));
  assert.ok(has(block({ loaded: true, key: null }, {}, 'en'), 'Generate the API key in your profile first.'));
});

test('Lanzador: sin process -> aviso; con process no', { skip }, () => {
  const h = block(WITH, { game: { process: '' } });
  assert.ok(has(h, '<code>process</code>') && has(h, 'el hub no podrá vigilar el cierre') && has(h, 'class="alert warn compact"'));
  assert.ok(!has(block(WITH), 'no podrá vigilar'));
  assert.ok(has(block(WITH, { game: { process: '  ' } }), 'no podrá vigilar'));
});

test('Lanzador: juego sin guardar o sin dispositivos no muestra comandos', { skip }, () => {
  assert.ok(has(block(WITH, { game: { id: '' } }), 'Guarda el juego para obtener sus comandos.'));
  const h = block(WITH, { game: { devices: [] } });
  assert.ok(has(h, 'Elige los dispositivos') && !has(h, 'curl'));
});

test('Lanzador: cargando y error de API', { skip }, () => {
  assert.ok(has(block({ loaded: false }), 'role="status"'));
  assert.ok(has(block({ loaded: true, error: { code: 'err.main.origin_forbidden', params: {} } }), 'role="alert"'));
});

test('Último aviso por dispositivo: tipo, hace cuánto, resultado y vigilancia', { skip }, () => {
  const status = { devices: [
    { device: 'mi-pc', last: { trigger: 'hook', at: '2026-11-09T11:57:00Z', outcome: 'ok' }, watching: { state: 'running', since: '2026-11-09T11:57:05Z' } },
    { device: 'deck', last: null, watching: null },
  ] };
  const h = block({ ...WITH, status });
  assert.ok(has(h, 'Último aviso') && has(h, 'Mi PC: Aviso del juego, hace 3 minutos, correcta · vigilando: juego abierto'), h);
  assert.ok(has(h, 'Deck: sin avisos todavía'));
  const c = block({ ...WITH, status: { devices: [{ device: 'deck', last: { trigger: 'hook_closed', at: '2026-11-09T11:59:00Z', outcome: 'conflict' }, watching: { state: 'settling', since: 'x' } }] } });
  assert.ok(has(c, 'Deck: Cierre del juego, hace 1 minuto') && has(c, 'cerrado, a punto de sincronizar'), c);
  const e = block({ ...WITH, status }, {}, 'en');
  assert.ok(has(e, 'Last notice') && has(e, 'Mi PC: Game opened, 3 minutes ago') && has(e, 'watching: game open'), e);
});

test('Panel: selector de juego con todos los juegos, el elegido seleccionado y sus dispositivos', { skip }, () => {
  const h = block(WITH);
  assert.match(h, /<select[^>]*>(<option[^>]*>[^<]*<\/option>)+<\/select>/);
  assert.ok(has(h, '>Juego</label>') || has(h, 'Juego</label>'), h);
  assert.match(h, /<option value="juego-1a2b3c4d" selected="">Juego<\/option><option value="otro-9f8e7d6c">Otro juego<\/option>/);
  assert.ok(has(h, '/api/hook/juego-1a2b3c4d/opened?device=mi-pc') && !has(h, 'otro-9f8e7d6c/opened'));
  // Otro juego elegido: sus dispositivos (solo Mi PC) y su id; sin Deck.
  const o = R('LauncherBlock', { games: [game(), OTHER], selected: 'otro-9f8e7d6c', onSelect() {}, active: true, initial: WITH, defaultHub: 'http://h:1' });
  assert.ok(has(o, '/api/hook/otro-9f8e7d6c/opened?device=mi-pc') && !has(o, '>Deck<'));
  assert.equal(o.split(KEY).length - 1, 1);
  // Selección desconocida: cae en el primero.
  assert.ok(has(R('LauncherBlock', { games: [game(), OTHER], selected: 'nada', onSelect() {}, active: true, initial: WITH, defaultHub: 'http://h:1' }), 'juego-1a2b3c4d/opened'));
});

test('Panel: sin juegos aviso; el último aviso es solo del juego elegido', { skip }, () => {
  const h = R('LauncherBlock', { games: [], selected: '', onSelect() {}, active: true, initial: WITH });
  assert.ok(has(h, 'Añade un juego para obtener sus comandos.') && !has(h, 'curl'));
  assert.ok(has(R('LauncherBlock', { games: [], selected: '', onSelect() {}, active: true, initial: WITH }, 'en'), 'Add a game to get its commands.'));
});

test('LaunchersPanel: tarjeta propia plegada por defecto (hidden, sin contenido) y desplegada con Ocultar', { skip }, () => {
  const props = { id: 'launchers-section', games: [game()], selected: 'juego-1a2b3c4d', onSelect() {}, onToggle() {}, initial: WITH, defaultHub: 'http://h:1' };
  const closed = R('LaunchersPanel', { ...props, open: false });
  assert.ok(has(closed, 'id="launchers-section"') && has(closed, '>Lanzadores</h3>') && has(closed, '>Mostrar</button>') && has(closed, 'aria-expanded="false"'));
  assert.match(closed, /<div id="([^"]+)" class="launchers-body" hidden="">/);
  assert.ok(!has(closed, 'curl') && !has(closed, 'class="launcher"'));
  const id = /aria-controls="([^"]+)"/.exec(closed)[1];
  assert.ok(has(closed, `id="${id}"`));
  const open = R('LaunchersPanel', { ...props, open: true });
  assert.ok(has(open, '>Ocultar</button>') && has(open, 'aria-expanded="true"') && has(open, 'curl') && !has(open, 'hidden=""'));
  assert.ok(has(R('LaunchersPanel', { ...props, open: false }, 'en'), '>Show</button>') && has(R('LaunchersPanel', { ...props, open: true }, 'en'), '>Hide</button>'));
});

test('GameCard: sin bloque Lanzador; enlace «Ver comandos de lanzador» solo con onShowLaunchers y juego guardado', { skip }, () => {
  m.i18n.setLocale('es');
  const g = { key: 'g1', id: 'juego-1a2b3c4d', name: 'Juego', a: 'd1', b: 'd2', pathA: '/a', pathB: '/b', process: '', keep: '', onConflict: '' };
  const render = (o = {}, game = g) => m.renderToStaticMarkup(m.React.createElement(m.GameCard, {
    game, devices: [{ key: 'd1', name: 'PC' }, { key: 'd2', name: 'Deck' }], errors: {}, globalMax: 20, nameA: 'PC', nameB: 'Deck',
    idA: 'pc', idB: 'deck', idText: 'juego-1a2b3c4d', renamed: false, onChange() {}, onRemove() {}, ...o,
  }));
  const h = render();
  assert.ok(!has(h, 'class="launcher"') && !has(h, 'Lanzador') && !has(h, 'Ver comandos'), h);
  const l = render({ onShowLaunchers() {} });
  assert.ok(has(l, '>Ver comandos de lanzador</button>') && has(l, 'aria-label="Ver comandos de lanzador de Juego"'), l);
  assert.ok(!has(render({ onShowLaunchers() {} }, { ...g, id: '' }), 'Ver comandos'));
});

const NOTES = [
  [{ result: 'skipped', code: 'err.hook.never_seen', params: { seconds: 120 } },
    'No se vio el proceso del juego abierto en 120 s: vigilancia descartada, sin checkpoint de cierre',
    'The game process was not seen running within 120 s: watch dropped, no closing checkpoint'],
  [{ result: 'skipped', code: 'err.hook.busy', params: {} },
    'Checkpoint de cierre omitido: ya había una sincronización de este juego en curso (no se reintenta)',
    'Closing checkpoint skipped: a sync of this game was already running (not retried)'],
  [{ result: 'skipped', code: 'err.hook.game_removed', params: {} },
    'Checkpoint de cierre omitido: el juego ya no está en la configuración',
    'Closing checkpoint skipped: the game is no longer in the configuration'],
  [{ result: 'error', code: 'err.hook.checkpoint_failed', params: { error: 'RuntimeError' } },
    'El checkpoint de cierre falló (RuntimeError); no se reintenta',
    'The closing checkpoint failed (RuntimeError); not retried'],
];

test('Historial: descartes y omitidos del cierre con texto traducido (es/en) e icono, no solo color', { skip }, () => {
  for (const [entry, es, en] of NOTES) {
    const h = R('EntryMessage', { entry: { ...entry, message: '' } });
    assert.ok(has(h, es) && has(h, 'hook-note') && has(h, '<svg'), h);
    assert.ok(has(h, entry.result === 'error' ? 'is-error' : 'hook-note'), h);
    const e = R('EntryMessage', { entry: { ...entry, message: '' } }, 'en');
    assert.ok(has(e, en) && !has(e, 'vigilancia'), e);
  }
  // una entrada normal (sin código err.hook.*) no lleva icono
  assert.ok(!has(R('EntryMessage', { entry: { result: 'ok', code: 'err.scheduler.busy', params: {}, message: '' } }), 'hook-note'));
});

test('Último aviso: el motivo del descarte se añade al resultado', { skip }, () => {
  const status = { devices: [{ device: 'mi-pc', last: { trigger: 'hook_closed', at: '2026-11-09T11:57:00Z', outcome: 'skipped', code: 'err.hook.busy', params: {} }, watching: null }] };
  const h = block({ ...WITH, status });
  assert.ok(has(h, 'Mi PC: Cierre del juego, hace 3 minutos, omitida · Checkpoint de cierre omitido'), h);
  const e = block({ ...WITH, status }, {}, 'en');
  assert.ok(has(e, 'Closing checkpoint skipped'), e);
});
