import test from 'node:test';
import assert from 'node:assert/strict';
import { parseRun } from '../src/format.js';

test('parseRun: ejecución normal, dry-run y sin datos', () => {
  assert.deepEqual(parseRun({ winner: 'pc', targets: ['hub', 'lap'], result: 'ok' }),
    { winner: 'pc', list: ['hub', 'lap'], planned: false, structured: true });
  assert.equal(parseRun({ winner: 'pc', targets: ['lap'], result: 'dry-run' }).planned, true);
  assert.equal(parseRun({ winner: 'pc', targets: ['lap'], dry_run: true }).planned, true);
  assert.deepEqual(parseRun({ result: 'ok', message: 'sin cambios' }),
    { winner: '', list: [], planned: false, structured: false });
  // ya no se interpreta el texto del mensaje
  assert.equal(parseRun({ message: 'ganador X; actualizados A, B' }).structured, false);
});
