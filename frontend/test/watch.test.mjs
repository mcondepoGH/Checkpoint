import test from 'node:test';
import assert from 'node:assert/strict';
import { chipCount, clock, groupByGame, watchCardClass, watchHealth, worstHealth } from '../src/watch.js';

const NOW = '2026-01-01T12:00:00Z';
const w = (o = {}) => ({ game: 'g', device: 'd', state: 'running', since: '2026-01-01T11:00:00Z', last_poll: '2026-01-01T11:59:55Z', poll: 15, ...o });

test('latido reciente: el estado manda', () => {
  for (const s of ['waiting', 'running', 'settling']) assert.equal(watchHealth(w({ state: s }), NOW), s);
});
test('umbral exacto no es stale, un segundo más sí', () => {
  assert.equal(watchHealth(w({ last_poll: '2026-01-01T11:59:15Z' }), NOW), 'running');
  assert.equal(watchHealth(w({ last_poll: '2026-01-01T11:59:14Z' }), NOW), 'stale');
});
test('sin poll usa 15 s; fechas ilegibles no marcan stale; estado raro -> waiting', () => {
  assert.equal(watchHealth(w({ poll: 0, last_poll: '2026-01-01T11:59:00Z' }), NOW), 'stale');
  assert.equal(watchHealth(w({ last_poll: 'x' }), NOW), 'running');
  assert.equal(watchHealth(w({ state: '??' }), NOW), 'waiting');
});
test('groupByGame agrupa y ordena por dispositivo', () => {
  const g = groupByGame([w({ device: 'b' }), w({ device: 'a' }), w({ game: 'h' })]);
  assert.deepEqual(g.g.map((x) => x.device), ['a', 'b']);
  assert.equal(g.h.length, 1);
  assert.deepEqual(groupByGame(null), {});
});
test('clock devuelve HH:MM o —', () => {
  assert.match(clock('2026-01-01T12:34:00Z', 'en-GB'), /^\d{2}:\d{2}$/);
  assert.equal(clock('nope', 'es'), '—');
});

test('worstHealth: la peor vigilancia manda; sin vigilancias, null', () => {
  const NOW = '2026-01-01T12:00:00Z';
  const w = (state, last_poll = NOW) => ({ state, last_poll, poll: 15 });
  assert.equal(worstHealth([w('waiting'), w('running')], NOW), 'running');
  assert.equal(worstHealth([w('running'), w('settling')], NOW), 'settling');
  assert.equal(worstHealth([w('settling'), w('running', '2026-01-01T11:00:00Z')], NOW), 'stale');
  assert.equal(worstHealth([], NOW), null);
  assert.equal(worstHealth(undefined, NOW), null);
});
test('watchCardClass: borde solo con vigilancia', () => {
  assert.equal(watchCardClass(null), 'card');
  assert.equal(watchCardClass('stale'), 'card watched watch-stale');
});
test('chipCount: 99+ por encima de 99', () => {
  assert.equal(chipCount(1), '1');
  assert.equal(chipCount(99), '99');
  assert.equal(chipCount(100), '99+');
});
