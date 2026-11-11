// Tabs, CopyBox y la sección Lanzadores (panel único con selector de juego), renderizados a HTML (esbuild + react-dom/server).
import test from 'node:test';
import assert from 'node:assert/strict';
import { bundle } from '../../helpers/bundle.mjs';

const { mod: m, skip } = await bundle(
  `import React from 'react';
  import { renderToStaticMarkup } from 'react-dom/server';
  import { i18n } from '#src/hooks/useI18n.js';
  import LauncherBlock from '#src/components/launchers/LauncherBlock.jsx';
  import LaunchersPanel from '#src/components/launchers/LaunchersPanel.jsx';
  import GameCard from '#src/components/config/GameCard.jsx';
  import { Tabs, CopyBox } from '#src/components/ui/index.js';
  import { EntryMessage, EntryDetail, RunEntry } from '#src/components/autosync/AutoSyncLog.jsx';
  export { React, renderToStaticMarkup, i18n, LauncherBlock, LaunchersPanel, GameCard, Tabs, CopyBox, EntryMessage, EntryDetail, RunEntry };`,
  { navigator: true, tag: 'ckpt-launcher' },
);
const KEY = 'ck_AbC123xyz';
const has = (h, s) => h.includes(s);
const R = (C, props, lang = 'es') => {
  m.i18n.setLocale(lang);
  return m.renderToStaticMarkup(m.React.createElement(m[C], props));
};
const DEVS = [
  { id: 'mi-pc', name: 'Mi PC' },
  { id: 'deck', name: 'Deck' },
];
const game = (o = {}) => ({ sel: 'juego-1a2b3c4d', id: 'juego-1a2b3c4d', name: 'Juego', process: 'juego.exe', devices: DEVS, ...o });
const OTHER = {
  sel: 'otro-9f8e7d6c',
  id: 'otro-9f8e7d6c',
  name: 'Otro juego',
  process: 'otro.exe',
  devices: [{ id: 'mi-pc', name: 'Mi PC' }],
};
const block = (initial, o = {}, lang = 'es') =>
  R(
    'LauncherBlock',
    {
      games: [game(o.game), OTHER],
      selected: 'juego-1a2b3c4d',
      onSelect() {},
      active: true,
      defaultHub: 'http://hub.example.lan:8088',
      initial,
      now: new Date('2026-11-09T12:00:00Z'),
      ...o,
      game: undefined,
    },
    lang,
  );
const WITH = { loaded: true, key: KEY };

test('Tabs: roles, aria-selected/controls y roving tabindex', { skip }, () => {
  const h = R(
    'Tabs',
    {
      tabs: [
        { id: 'a', label: 'A' },
        { id: 'b', label: 'B' },
      ],
      value: 'b',
      onChange() {},
      label: 'Lista',
    },
    'es',
  );
  const x = m.React.createElement(
    m.Tabs,
    {
      tabs: [
        { id: 'a', label: 'A' },
        { id: 'b', label: 'B' },
      ],
      value: 'b',
      onChange() {},
      label: 'Lista',
    },
    'contenido',
  );
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
  assert.ok(
    has(h, 'class="copybox"') &&
      has(h, 'class="copybox-field"') &&
      has(h, 'role="textbox"') &&
      has(h, 'aria-readonly="true"') &&
      has(h, 'aria-label="Comando"'),
  );
  assert.ok(has(h, 'curl -X POST &quot;x&quot;'));
  assert.match(h, /<button[^>]*class="btn btn-icon copybox-copy"[^>]*aria-label="Copiar"/);
  assert.ok(has(h, 'M9 9h11') && !has(h, 'M20 6 9 17l-5-5'));
  const w = R('CopyBox', { value: 'x', label: 'C', what: 'comando de Steam' });
  assert.match(
    w,
    /<button[^>]*title="Copiar comando de Steam"[^>]*aria-label="Copiar comando de Steam"|<button[^>]*aria-label="Copiar comando de Steam"[^>]*title="Copiar comando de Steam"/,
  );
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
  assert.ok(
    has(h, `Bearer ${KEY}`) && has(h, 'http://hub.example.lan:8088/api/hook/juego-1a2b3c4d/opened?device=mi-pc') && has(h, '; %command%'),
  );
  assert.equal(h.split(KEY).length - 1, 1);
  assert.ok(has(h, 'aria-label="Copiar comando de Steam / Steam Deck"'), h);
  assert.ok(
    has(
      R(
        'LauncherBlock',
        {
          games: [game({ devices: DEVS })],
          selected: 'juego-1a2b3c4d',
          onSelect() {},
          active: true,
          initial: WITH,
          defaultHub: 'http://x:1',
        },
        'en',
      ),
      'aria-label="Copy Steam / Steam Deck command"',
    ),
  );
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
  const status = {
    devices: [
      {
        device: 'mi-pc',
        last: { trigger: 'hook', at: '2026-11-09T11:57:00Z', outcome: 'ok' },
        watching: { state: 'running', since: '2026-11-09T11:57:05Z' },
      },
      { device: 'deck', last: null, watching: null },
    ],
  };
  const h = block({ ...WITH, status });
  assert.ok(has(h, 'Último aviso') && has(h, 'Mi PC: Aviso del juego, hace 3 minutos, correcta · vigilando: juego abierto'), h);
  assert.ok(has(h, 'Deck: sin avisos todavía'));
  const c = block({
    ...WITH,
    status: {
      devices: [
        {
          device: 'deck',
          last: { trigger: 'hook_closed', at: '2026-11-09T11:59:00Z', outcome: 'conflict' },
          watching: { state: 'settling', since: 'x' },
        },
      ],
    },
  });
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
  const o = R('LauncherBlock', {
    games: [game(), OTHER],
    selected: 'otro-9f8e7d6c',
    onSelect() {},
    active: true,
    initial: WITH,
    defaultHub: 'http://h:1',
  });
  assert.ok(has(o, '/api/hook/otro-9f8e7d6c/opened?device=mi-pc') && !has(o, '>Deck<'));
  assert.equal(o.split(KEY).length - 1, 1);
  // Selección desconocida: cae en el primero.
  assert.ok(
    has(
      R('LauncherBlock', {
        games: [game(), OTHER],
        selected: 'nada',
        onSelect() {},
        active: true,
        initial: WITH,
        defaultHub: 'http://h:1',
      }),
      'juego-1a2b3c4d/opened',
    ),
  );
});

test('Panel: sin juegos aviso; el último aviso es solo del juego elegido', { skip }, () => {
  const h = R('LauncherBlock', { games: [], selected: '', onSelect() {}, active: true, initial: WITH });
  assert.ok(has(h, 'Añade un juego para obtener sus comandos.') && !has(h, 'curl'));
  assert.ok(
    has(
      R('LauncherBlock', { games: [], selected: '', onSelect() {}, active: true, initial: WITH }, 'en'),
      'Add a game to get its commands.',
    ),
  );
});

test('LaunchersPanel: tarjeta propia plegada por defecto (hidden, sin contenido) y desplegada con Ocultar', { skip }, () => {
  const props = {
    id: 'launchers-section',
    games: [game()],
    selected: 'juego-1a2b3c4d',
    onSelect() {},
    onToggle() {},
    initial: WITH,
    defaultHub: 'http://h:1',
  };
  const closed = R('LaunchersPanel', { ...props, open: false });
  assert.ok(
    has(closed, 'id="launchers-section"') &&
      has(closed, '>Lanzadores</h3>') &&
      has(closed, '>Mostrar</button>') &&
      has(closed, 'aria-expanded="false"'),
  );
  assert.match(closed, /<div id="([^"]+)" class="launchers-body" hidden="">/);
  assert.ok(!has(closed, 'curl') && !has(closed, 'class="launcher"'));
  const id = /aria-controls="([^"]+)"/.exec(closed)[1];
  assert.ok(has(closed, `id="${id}"`));
  const open = R('LaunchersPanel', { ...props, open: true });
  assert.ok(has(open, '>Ocultar</button>') && has(open, 'aria-expanded="true"') && has(open, 'curl') && !has(open, 'hidden=""'));
  assert.ok(
    has(R('LaunchersPanel', { ...props, open: false }, 'en'), '>Show</button>') &&
      has(R('LaunchersPanel', { ...props, open: true }, 'en'), '>Hide</button>'),
  );
});

test('GameCard: sin bloque Lanzador; enlace «Ver comandos de lanzador» solo con onShowLaunchers y juego guardado', { skip }, () => {
  m.i18n.setLocale('es');
  const g = {
    key: 'g1',
    id: 'juego-1a2b3c4d',
    name: 'Juego',
    a: 'd1',
    b: 'd2',
    pathA: '/a',
    pathB: '/b',
    process: '',
    keep: '',
    onConflict: '',
  };
  const render = (o = {}, game = g) =>
    m.renderToStaticMarkup(
      m.React.createElement(m.GameCard, {
        game,
        devices: [
          { key: 'd1', name: 'PC' },
          { key: 'd2', name: 'Deck' },
        ],
        errors: {},
        globalMax: 20,
        nameA: 'PC',
        nameB: 'Deck',
        idA: 'pc',
        idB: 'deck',
        idText: 'juego-1a2b3c4d',
        renamed: false,
        onChange() {},
        onRemove() {},
        ...o,
      }),
    );
  const h = render();
  assert.ok(!has(h, 'class="launcher"') && !has(h, 'Lanzador') && !has(h, 'Ver comandos'), h);
  const l = render({ onShowLaunchers() {} });
  assert.ok(has(l, '>Ver comandos de lanzador</button>') && has(l, 'aria-label="Ver comandos de lanzador de Juego"'), l);
  assert.ok(!has(render({ onShowLaunchers() {} }, { ...g, id: '' }), 'Ver comandos'));
});

const NOTES = [
  [
    { result: 'skipped', code: 'err.hook.never_seen', params: { seconds: 120 } },
    'No se vio el proceso del juego abierto en 120 s: vigilancia descartada, sin checkpoint de cierre',
    'The game process was not seen running within 120 s: watch dropped, no closing checkpoint',
  ],
  [
    { result: 'skipped', code: 'err.hook.busy', params: {} },
    'Checkpoint de cierre omitido: ya había una sincronización de este juego en curso (no se reintenta)',
    'Closing checkpoint skipped: a sync of this game was already running (not retried)',
  ],
  [
    { result: 'skipped', code: 'err.hook.game_removed', params: {} },
    'Checkpoint de cierre omitido: el juego ya no está en la configuración',
    'Closing checkpoint skipped: the game is no longer in the configuration',
  ],
  [
    { result: 'error', code: 'err.hook.checkpoint_failed', params: { error: 'RuntimeError' } },
    'El checkpoint de cierre falló (RuntimeError); no se reintenta',
    'The closing checkpoint failed (RuntimeError); not retried',
  ],
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

const count = (h, s) => h.split(s).length - 1;
const runEntry = (o) => ({ id: 'x1', started: '2026-11-09T11:00:00Z', duration: 0, trigger: 'hook_closed', message: '', params: {}, ...o });
const oneGame = (result, code, params = {}, name = 'Juego 0') =>
  runEntry({ result, code, params, games: { juego0: { name, result, code, params, message: '' } } });

test('Registro: una entrada omitida de un solo juego lleva UNA etiqueta de estado y UN mensaje (es/en)', { skip }, () => {
  for (const [entry, es, en] of NOTES) {
    const e = oneGame(entry.result, entry.code, entry.params);
    for (const [lang, text] of [
      ['es', es],
      ['en', en],
    ]) {
      const h = R('RunEntry', { entry: e }, lang);
      assert.equal(count(h, text), 1, h);
      assert.equal(count(h, '<svg'), 1, h);
      assert.equal(count(h, 'class="badge '), 1, h); // solo la de la cabecera
      assert.ok(has(h, 'Juego 0') && has(h, 'hook-note'), h);
      assert.equal(has(h, 'is-error'), entry.result === 'error', h);
    }
  }
});

test('Registro: varios juegos conservan su etiqueta y su mensaje; sin entrada de nota no cambia', { skip }, () => {
  const e = runEntry({
    result: 'skipped',
    code: 'err.hook.busy',
    games: {
      a: { name: 'Juego A', result: 'skipped', code: 'err.hook.busy', params: {}, message: '' },
      b: { name: 'Juego B', result: 'error', code: 'err.hook.checkpoint_failed', params: { error: 'RuntimeError' }, message: '' },
    },
  });
  const h = R('EntryDetail', { entry: e });
  assert.ok(has(h, 'Juego A') && has(h, 'Juego B'), h);
  assert.equal(count(h, 'class="badge aborted"'), 1, h);
  assert.equal(count(h, 'class="badge error"'), 1, h);
  assert.equal(count(h, 'ya había una sincronización'), 1, h); // el texto de la entrada no se repite en la fila A
  assert.equal(count(h, 'RuntimeError'), 1, h);
});

test('Registro: entrada correcta con mensaje de entrada y de juego distintos: una etiqueta, cada mensaje una vez', { skip }, () => {
  const e = runEntry({
    result: 'ok',
    trigger: 'scheduled',
    message: 'Todo bien',
    games: { g: { name: 'Juego', result: 'ok', message: 'Listo' } },
  });
  const h = R('RunEntry', { entry: e });
  assert.equal(count(h, 'Todo bien'), 1, h);
  assert.equal(count(h, 'Listo'), 1, h);
  assert.ok(!has(h, 'hook-note') && !has(h, '<svg'), h);
  assert.equal(count(h, 'class="badge '), 1, h);
});

test('Registro: correcta de un juego = cabecera + línea de juego, UNA etiqueta, sin tercera línea (es/en)', { skip }, () => {
  for (const [trigger, es, en] of [
    ['hook', 'Aviso del juego', 'Game opened'],
    ['hook_closed', 'Cierre del juego', 'Game closed'],
  ]) {
    const e = runEntry({ trigger, result: 'ok', device: 'mi-pc', games: { juego0: { name: 'Juego 0', result: 'ok', message: '' } } });
    for (const [lang, txt] of [
      ['es', es],
      ['en', en],
    ]) {
      const h = R('RunEntry', { entry: e }, lang);
      assert.equal(count(h, 'class="badge '), 1, h);
      assert.equal(count(h, 'Juego 0'), 1, h);
      assert.equal(count(h, 'mi-pc'), 1, h);
      assert.ok(has(h, txt) && !has(h, 'class="msg') && !has(h, '<svg'), h);
      assert.ok(has(h, '<li class="run"') && has(h, 'class="run-head"') && !has(h, '<details'), h);
    }
  }
});

test('Registro: error de un juego sin dispositivo: una etiqueta, mensaje una vez con icono', { skip }, () => {
  const e = oneGame('error', 'err.hook.checkpoint_failed', { error: 'RuntimeError' });
  const h = R('RunEntry', { entry: e });
  assert.equal(count(h, 'class="badge '), 1, h);
  assert.equal(count(h, 'RuntimeError'), 1, h);
  assert.equal(count(h, '<svg'), 1, h);
  assert.ok(!has(h, 'class="dev"'), h);
});

test('Registro: varios juegos con el mismo resultado que la cabecera no llevan etiqueta; con mezcla, todos', { skip }, () => {
  const same = runEntry({ result: 'ok', games: { a: { name: 'A', result: 'ok' }, b: { name: 'B', result: 'ok' } } });
  assert.equal(count(R('RunEntry', { entry: same }), 'class="badge '), 1);
  const mixed = runEntry({
    result: 'partial',
    games: {
      a: { name: 'A', result: 'ok' },
      b: { name: 'B', result: 'error', code: 'err.hook.checkpoint_failed', params: { error: 'X' } },
    },
  });
  const h = R('RunEntry', { entry: mixed });
  assert.equal(count(h, 'class="badge '), 3, h); // cabecera + dos filas
  assert.equal(count(h, 'El checkpoint de cierre falló (X)'), 1, h);
});

const gm = (n, result = 'ok', extra = {}) =>
  Object.fromEntries(Array.from({ length: n }, (_, i) => [`g${i}`, { name: `Juego ${i}`, result, message: '', ...extra }]));
const OFFLINE = { code: 'err.sync.all_offline', params: { devices: 'Deck' } };
const abortedScheduled = (trigger = 'scheduled') =>
  runEntry({
    trigger,
    result: 'aborted',
    duration: 1.2,
    code: 'err.scheduler.summary',
    params: { causes: [{ path: 'Juego 0', ...OFFLINE }] },
    games: { g0: { name: 'Juego 0', result: 'aborted', ...OFFLINE, message: '' } },
  });

test('Registro: programada correcta de un juego (es/en): una etiqueta, juego una vez, sin mensaje ni icono', { skip }, () => {
  const e = runEntry({ trigger: 'scheduled', result: 'ok', duration: 3.4, games: gm(1) });
  for (const [lang, txt, ok] of [
    ['es', 'Programada', 'correcta'],
    ['en', 'Scheduled', 'ok'],
  ]) {
    const h = R('RunEntry', { entry: e }, lang);
    assert.equal(count(h, 'class="badge '), 1, h);
    assert.equal(count(h, 'Juego 0'), 1, h);
    assert.ok(has(h, txt) && has(h, ok) && !has(h, '<svg') && !has(h, 'class="msg'), h);
  }
});

test('Registro: programada con varios juegos mezclados (<=3): todas las filas con etiqueta, sin plegar', { skip }, () => {
  const e = runEntry({
    trigger: 'scheduled',
    result: 'partial',
    games: {
      a: { name: 'A', result: 'ok' },
      b: { name: 'B', result: 'skipped', code: 'err.scheduler.busy', params: {} },
      c: { name: 'C', result: 'error', code: 'err.sync.unexpected', params: { type: 'X', detail: 'boom' } },
    },
  });
  for (const lang of ['es', 'en']) {
    const h = R('RunEntry', { entry: e }, lang);
    assert.equal(count(h, 'class="badge '), 4, h); // cabecera + 3 filas
    assert.equal(count(h, 'X: boom'), 1, h);
    assert.ok(!has(h, 'class="fold"') && !has(h, 'aria-expanded'), h);
  }
});

test('Registro: programada con >3 juegos: plegada, resumen accesible y juegos no correctos visibles (es/en)', { skip }, () => {
  const games = {
    ...gm(12),
    x: { name: 'Roto', result: 'error', code: 'err.sync.unexpected', params: { type: 'E', detail: 'fallo' }, message: '' },
  };
  const e = runEntry({ trigger: 'scheduled', result: 'error', games });
  for (const [lang, sum] of [
    ['es', '13 juegos: 12 correctos, 1 error'],
    ['en', '13 games: 12 succeeded, 1 failed'],
  ]) {
    const h = R('RunEntry', { entry: e }, lang);
    assert.ok(has(h, sum), h);
    assert.ok(has(h, 'aria-expanded="false"') && has(h, 'aria-controls='), h);
    assert.ok(has(h, 'Roto') && has(h, 'E: fallo'), h);
    assert.ok(!has(h, 'Juego 0') && !has(h, 'Juego 11'), h); // los correctos, plegados
    assert.equal(count(h, 'class="badge '), 2, h); // cabecera + el juego con error (hay mezcla)
    assert.equal(count(h, 'E: fallo'), 1, h);
  }
  // todos correctos: solo el resumen
  const h = R('RunEntry', { entry: runEntry({ trigger: 'scheduled', result: 'ok', games: gm(5) }) });
  assert.ok(has(h, '5 juegos: 5 correctos') && !has(h, 'Juego 0') && !has(h, '<ul'), h);
  // exactamente 3: sin plegar
  assert.ok(!has(R('RunEntry', { entry: runEntry({ result: 'ok', games: gm(3) }) }), 'class="fold"'));
});

test('Registro: arranque correcto (es/en)', { skip }, () => {
  const e = runEntry({ trigger: 'startup', result: 'ok', duration: 12, games: gm(2) });
  assert.ok(has(R('RunEntry', { entry: e }), 'Arranque') && has(R('RunEntry', { entry: e }, 'en'), 'Startup'));
  assert.equal(count(R('RunEntry', { entry: e }), 'class="badge '), 1);
});

test('Registro: hook y hook_closed ok / omitida / error con dispositivo: una etiqueta, mensaje una vez (es/en)', { skip }, () => {
  const cases = [
    ['ok', null],
    ['skipped', 'err.hook.busy'],
    ['error', 'err.hook.checkpoint_failed'],
  ];
  for (const trigger of ['hook', 'hook_closed'])
    for (const [result, code] of cases) {
      const g = { name: 'Juego 0', result, message: '', ...(code ? { code, params: { error: 'RuntimeError' } } : {}) };
      const e = runEntry({
        trigger,
        result,
        device: 'mi-pc',
        ...(code ? { code, params: { error: 'RuntimeError' } } : {}),
        games: { juego0: g },
      });
      for (const lang of ['es', 'en']) {
        const h = R('RunEntry', { entry: e }, lang);
        assert.equal(count(h, 'class="badge '), 1, h);
        assert.equal(count(h, 'Juego 0'), 1, h);
        assert.equal(count(h, 'mi-pc'), 1, h);
        assert.equal(count(h, '<svg'), code ? 1 : 0, h);
        assert.equal(count(h, 'class="msg'), code ? 1 : 0, h);
      }
    }
});

test('Registro: abortada sin juegos con err.sync.all_offline: motivo traducido UNA vez con icono (es/en)', { skip }, () => {
  const e = runEntry({ trigger: 'scheduled', result: 'aborted', ...OFFLINE, games: {} });
  for (const [lang, txt] of [
    ['es', 'Deck no responden; no se toca nada'],
    ['en', null],
  ]) {
    const h = R('RunEntry', { entry: e }, lang);
    assert.equal(count(h, 'class="badge '), 1, h);
    assert.equal(count(h, '<svg'), 1, h);
    assert.equal(count(h, 'class="msg'), 1, h);
    assert.ok(!has(h, 'all_offline') && !has(h, 'err.sync') && !has(h, 'autolog.noDetail') && !has(h, 'class="games"'), h);
    if (txt) assert.equal(count(h, txt), 1, h);
  }
});

test('Registro: abortada con un juego y resumen «Juego: motivo»: el motivo sale una vez, no dos', { skip }, () => {
  for (const trigger of ['scheduled', 'hook'])
    for (const lang of ['es', 'en']) {
      const h = R('RunEntry', { entry: abortedScheduled(trigger) }, lang);
      assert.equal(count(h, 'class="msg'), 1, h);
      assert.equal(count(h, '<svg'), 1, h);
      assert.equal(count(h, 'class="badge '), 1, h);
      assert.ok(!has(h, 'Juego 0: '), h);
    }
});

test('Registro: ciclo sin juegos y sin mensaje: «Sin detalle por juego.» una vez; duración 0 o vacía = «—»', { skip }, () => {
  const e = runEntry({ trigger: 'scheduled', result: 'ok', duration: 0, games: {} });
  const h = R('RunEntry', { entry: e });
  assert.equal(count(h, 'Sin detalle por juego.'), 1, h);
  assert.ok(has(h, '<span class="dur">—</span>'), h);
  assert.ok(has(R('RunEntry', { entry: { ...e, duration: undefined } }), '<span class="dur">—</span>'));
  assert.ok(has(R('RunEntry', { entry: { ...e, duration: 2.5 } }), '2,5 s'));
  assert.ok(has(R('RunEntry', { entry: e }, 'en'), 'No per-game detail.'));
});

test('Registro: entrada antigua (solo message, sin device ni code) y tipo desconocido se muestran tal cual', { skip }, () => {
  const old = {
    id: 'o1',
    started: '2026-01-02T03:04:05Z',
    duration: 4,
    trigger: 'manual',
    result: 'weird',
    message: 'Texto viejo',
    games: { g: { name: 'Viejo', result: 'weird', message: 'Texto viejo' } },
  };
  for (const lang of ['es', 'en']) {
    const h = R('RunEntry', { entry: old }, lang);
    assert.ok(has(h, '>manual<') && has(h, '>weird<'), h);
    assert.equal(count(h, 'Texto viejo'), 1, h);
    assert.equal(count(h, 'class="badge'), 1, h);
    assert.ok(!has(h, 'class="dev"'), h);
  }
  const noTrig = R('RunEntry', { entry: { ...old, trigger: undefined } });
  assert.ok(has(noTrig, '<span class="trig">—</span>'), noTrig);
});

test('Registro: SCSS del registro sin font-size suelto y con rejilla colapsable en móvil', { skip }, async () => {
  const fs = await import('node:fs');
  const scss = fs.readFileSync(new URL('../../../src/components/autosync/_autosync.scss', import.meta.url), 'utf8');
  const log = scss.slice(scss.indexOf('.autosync-log'));
  assert.doesNotMatch(log, /font-size: *[\d.]/);
  assert.match(log, /font-size: v\.\$fs-/);
  assert.match(log, /@media \(max-width: v\.\$bp-sm\)[\s\S]*grid-template-areas/);
  assert.doesNotMatch(log, /animation|transition/);
});

test('Último aviso: el motivo del descarte se añade al resultado', { skip }, () => {
  const status = {
    devices: [
      {
        device: 'mi-pc',
        last: { trigger: 'hook_closed', at: '2026-11-09T11:57:00Z', outcome: 'skipped', code: 'err.hook.busy', params: {} },
        watching: null,
      },
    ],
  };
  const h = block({ ...WITH, status });
  assert.ok(has(h, 'Mi PC: Cierre del juego, hace 3 minutos, omitida · Checkpoint de cierre omitido'), h);
  const e = block({ ...WITH, status }, {}, 'en');
  assert.ok(has(e, 'Closing checkpoint skipped'), e);
});
