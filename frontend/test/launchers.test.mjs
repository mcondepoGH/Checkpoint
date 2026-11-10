// Comandos de lanzador (funciones puras): sin navegador ni React.
import test from 'node:test';
import assert from 'node:assert/strict';
import { LAUNCHERS, commandsFor, hookUrl, normalizeHubUrl, ago, loadHubUrl, saveHubUrl, loadGameSel, saveGameSel } from '../src/launchers.js';
import { nextTabIndex } from '../src/tabs.js';

const KEY = 'ck_AbC123xyz';
const base = { url: 'http://192.168.1.98:8088', key: KEY, game: 'juego-1a2b3c4d', device: 'mi-pc' };
const main = (l, o = {}) => commandsFor(l, { ...base, ...o })[0].text;
const CURL = `curl -fsS -m 60 --retry 3 -X POST -H "Authorization: Bearer ${KEY}" "http://192.168.1.98:8088/api/hook/juego-1a2b3c4d/opened?device=mi-pc"`;

test('lanzadores en orden', () => assert.deepEqual(LAUNCHERS, ['steam', 'lutris', 'heroic', 'windows']));

test('Steam: curl + "; %command%" en una sola línea', () => {
  assert.equal(main('steam'), `${CURL}; %command%`);
  assert.ok(!main('steam').includes('\n'));
});

test('Lutris y Heroic: mismo curl sin %command%', () => {
  assert.equal(main('lutris'), CURL);
  assert.equal(main('heroic'), CURL);
});

test('%command% solo en Steam', () => {
  for (const l of LAUNCHERS) for (const c of commandsFor(l, base)) assert.equal(c.text.includes('%command%'), l === 'steam', `${l}/${c.id}`);
});

test('Windows: PowerShell 5.1 y alternativa curl.exe', () => {
  const [ps, cx] = commandsFor('windows', base);
  assert.equal(ps.id, 'powershell');
  assert.equal(ps.text, `Invoke-WebRequest -Method Post -Uri "http://192.168.1.98:8088/api/hook/juego-1a2b3c4d/opened?device=mi-pc" -Headers @{Authorization='Bearer ${KEY}'} -TimeoutSec 60 -UseBasicParsing`);
  assert.equal(cx.id, 'curl');
  assert.equal(cx.text, `curl.exe${CURL.slice('curl'.length)}`);
});

test('la key aparece exactamente una vez en cada comando', () => {
  for (const l of LAUNCHERS) for (const c of commandsFor(l, base)) assert.equal(c.text.split(KEY).length - 1, 1, `${l}/${c.id}`);
});

test('id y dispositivo con espacios, &, comillas y unicode van codificados', () => {
  const o = { game: 'Mi Juego & "Co" ñ', device: 'PC "sala" & más?=#' };
  const u = hookUrl({ ...base, ...o });
  assert.equal(u, 'http://192.168.1.98:8088/api/hook/Mi%20Juego%20%26%20%22Co%22%20%C3%B1/opened?device=PC%20%22sala%22%20%26%20m%C3%A1s%3F%3D%23');
  for (const l of LAUNCHERS) for (const c of commandsFor(l, { ...base, ...o })) {
    assert.ok(c.text.includes(u), `${l}/${c.id}`);
    assert.ok(!/[ñá]/.test(c.text));
  }
});

test('caracteres que el shell interpreta dentro de comillas también se codifican', () => {
  const u = hookUrl({ ...base, game: "a$b`c!d'e(f)*g\\h", device: 'x' });
  assert.ok(!/[$`!'()*\\]/.test(u.split('/api/hook/')[1]), u);
});

test('URL del hub: se normaliza y se rechaza lo peligroso', () => {
  assert.equal(normalizeHubUrl(' https://hub.example.com/ '), 'https://hub.example.com');
  assert.equal(normalizeHubUrl('http://h:8088//'), 'http://h:8088');
  assert.equal(normalizeHubUrl('https://h/prefijo/'), 'https://h/prefijo');
  for (const bad of ['', 'ftp://h', 'h:8088', 'http://h" ; rm -rf ~ #', 'http://h$(x)', 'http://h`x`', 'http://h x', 'http://h\\x']) assert.equal(normalizeHubUrl(bad), null, bad);
  assert.equal(commandsFor('steam', { ...base, url: 'http://h" ; x' }), null);
});

test('ago: hace cuánto, en el idioma pedido', () => {
  const now = new Date('2026-11-09T12:00:00Z');
  assert.match(ago('2026-11-09T11:59:30Z', now, 'es'), /30 segundos/);
  assert.match(ago('2026-11-09T11:57:00Z', now, 'es'), /3 minutos/);
  assert.match(ago('2026-11-09T09:00:00Z', now, 'en'), /3 hours ago/);
  assert.match(ago('2026-11-07T12:00:00Z', now, 'es'), /2 días/);
  assert.equal(ago('2026-11-09T12:00:05Z', now, 'es').includes('-'), false); // futuro (reloj desfasado) -> 0
  assert.equal(ago('basura', now, 'es'), '');
});

test('URL recordada: localStorage con try/catch', () => {
  const mem = new Map();
  const st = { getItem: (k) => mem.get(k) ?? null, setItem: (k, v) => mem.set(k, v) };
  assert.equal(loadHubUrl(st, 'http://def'), 'http://def');
  saveHubUrl(st, 'http://otra:1');
  assert.equal(loadHubUrl(st, 'http://def'), 'http://otra:1');
  const boom = { getItem() { throw new Error('x'); }, setItem() { throw new Error('x'); } };
  assert.equal(loadHubUrl(boom, 'http://def'), 'http://def');
  assert.doesNotThrow(() => saveHubUrl(boom, 'u'));
  assert.equal(loadHubUrl(null, 'http://def'), 'http://def');
  assert.doesNotThrow(() => saveHubUrl(null, 'u'));
});

test('teclado de pestañas: flechas con vuelta, Inicio y Fin', () => {
  assert.equal(nextTabIndex(4, 0, 'ArrowRight'), 1);
  assert.equal(nextTabIndex(4, 3, 'ArrowRight'), 0);
  assert.equal(nextTabIndex(4, 0, 'ArrowLeft'), 3);
  assert.equal(nextTabIndex(4, 2, 'ArrowLeft'), 1);
  assert.equal(nextTabIndex(4, 2, 'Home'), 0);
  assert.equal(nextTabIndex(4, 1, 'End'), 3);
  assert.equal(nextTabIndex(4, 1, 'a'), null);
});

test('juego elegido: se recuerda y nunca lanza sin almacenamiento', () => {
  const mem = {}; const st = { getItem: (k) => mem[k] ?? null, setItem: (k, v) => { mem[k] = v; } };
  assert.equal(loadGameSel(st), '');
  saveGameSel(st, 'juego-1');
  assert.equal(loadGameSel(st), 'juego-1');
  const boom = { getItem() { throw new Error('x'); }, setItem() { throw new Error('x'); } };
  assert.equal(loadGameSel(boom), '');
  assert.doesNotThrow(() => saveGameSel(boom, 'a'));
  assert.equal(loadGameSel(null), '');
  assert.doesNotThrow(() => saveGameSel(null, 'a'));
});
