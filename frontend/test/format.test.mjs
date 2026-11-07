import test from 'node:test';
import assert from 'node:assert/strict';
import { parseRun } from '../src/format.js';

test('parseRun: ejecución normal, simulación (dry-run) y sin datos', () => {
  assert.deepEqual(parseRun({ winner: 'pc', targets: ['hub', 'lap'], result: 'ok' }),
    { winner: 'pc', list: ['hub', 'lap'], planned: false, structured: true });
  assert.equal(parseRun({ winner: 'pc', targets: ['lap'], result: 'dry-run' }).planned, true);
  assert.equal(parseRun({ winner: 'pc', targets: ['lap'], dry_run: true }).planned, true);
  assert.deepEqual(parseRun({ result: 'ok', message: 'sin cambios' }),
    { winner: '', list: [], planned: false, structured: false });
  // ya no se interpreta el texto del mensaje
  assert.equal(parseRun({ message: 'ganador X; actualizados A, B' }).structured, false);
});

test('constantes compartidas de resultado y formato de fecha', async () => {
  const { RESULT_CLASS, RESULT_TEXT, ON_CONFLICT_OPTIONS, fmtDateTime } = await import('../src/format.js');
  for (const r of ['ok', 'error', 'aborted', 'skipped', 'conflict', 'partial']) {
    assert.ok(RESULT_CLASS[r] && RESULT_TEXT[r], r);
  }
  assert.deepEqual(ON_CONFLICT_OPTIONS.map(([v]) => v), ['skip', 'newest']);
  assert.equal(fmtDateTime(null), '—');
  assert.notEqual(fmtDateTime('2026-01-01T10:00:00+00:00'), '—');
});
