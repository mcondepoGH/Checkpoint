import test from 'node:test';
import assert from 'node:assert/strict';
import { fmtDuration, fmtSize, fmtWhen, parseRun } from '#src/lib/format.js';

test('parseRun: ejecución normal, simulación (dry-run) y sin datos', () => {
  assert.deepEqual(parseRun({ winner: 'pc', targets: ['hub', 'lap'], result: 'ok' }), {
    winner: 'pc',
    list: ['hub', 'lap'],
    planned: false,
    structured: true,
  });
  assert.equal(parseRun({ winner: 'pc', targets: ['lap'], result: 'dry-run' }).planned, true);
  assert.equal(parseRun({ winner: 'pc', targets: ['lap'], dry_run: true }).planned, true);
  assert.deepEqual(parseRun({ result: 'ok', message: 'sin cambios' }), { winner: '', list: [], planned: false, structured: false });
  // ya no se interpreta el texto del mensaje
  assert.equal(parseRun({ message: 'ganador X; actualizados A, B' }).structured, false);
});

test('constantes compartidas de resultado y formato de fecha', async () => {
  const { RESULT_CLASS, RESULT_TEXT, ON_CONFLICT_OPTIONS, fmtDateTime } = await import('#src/lib/format.js');
  for (const r of ['ok', 'error', 'aborted', 'skipped', 'conflict', 'partial']) {
    assert.ok(RESULT_CLASS[r] && RESULT_TEXT[r], r);
  }
  assert.deepEqual(
    ON_CONFLICT_OPTIONS.map(([v]) => v),
    ['skip', 'newest'],
  );
  assert.equal(fmtDateTime(null), '—');
  assert.notEqual(fmtDateTime('2026-01-01T10:00:00+00:00'), '—');
});

test('fmtSize: bytes, KB, MB y GB según el idioma; no numérico = —', () => {
  assert.equal(fmtSize(512, 'es'), '512 B');
  assert.equal(fmtSize(1536, 'en'), '1.5 KB');
  assert.equal(fmtSize(1536, 'es'), '1,5 KB');
  assert.equal(fmtSize(20 * 1024 * 1024, 'en'), '20 MB');
  assert.equal(fmtSize(5 * 1024 ** 4, 'en'), '5,120 GB');
  assert.equal(fmtSize(NaN, 'es'), '—');
});

test('fmtWhen y fmtDuration: fecha local, segundos y minutos; vacío o no numérico = —', () => {
  assert.equal(fmtWhen(0, 'es'), '—');
  assert.match(fmtWhen(1700000000, 'en'), /2023/);
  assert.equal(fmtDuration(1.5, 'en'), '1.5 s');
  assert.equal(fmtDuration(12, 'es'), '12 s');
  assert.equal(fmtDuration(125, 'es'), '2 min 5 s');
  assert.equal(fmtDuration(undefined, 'es'), '—');
});
