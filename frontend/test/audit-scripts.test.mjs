// Scripts de auditoría de CI: umbral de cobertura (lcov) y presupuesto de tamaño del bundle.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { summarize, check } from '../scripts/check-coverage.mjs';
import { dirSize, BUDGETS } from '../scripts/check-bundle-size.mjs';

const LCOV = [
  'TN:',
  'SF:src/a.js',
  'LF:10',
  'LH:9',
  'BRF:4',
  'BRH:4',
  'end_of_record',
  'SF:test/b.mjs',
  'LF:100',
  'LH:0',
  'end_of_record',
  'SF:src/c.js',
  'LF:10',
  'LH:9',
  'BRF:6',
  'BRH:5',
  'end_of_record',
  '',
].join('\n');

test('cobertura: suma LF/LH y BRF/BRH solo de src/** y compara con los umbrales', () => {
  const t = summarize(LCOV);
  assert.deepEqual(t, { LF: 20, LH: 18, BRF: 10, BRH: 9, files: 2 });
  assert.deepEqual(check(t), { lines: 90, branches: 90, ok: true });
  assert.equal(check(t, 91, 88).ok, false); // líneas por debajo
  assert.equal(check(t, 90, 91).ok, false); // ramas por debajo
  assert.equal(check(summarize('SF:test/x.mjs\nLF:1\nLH:1\n')).ok, false); // sin ficheros de src: no es un éxito
});

test('presupuesto de bundle: suma recursiva y umbrales definidos', () => {
  const d = fs.mkdtempSync(path.join(os.tmpdir(), 'size-'));
  fs.mkdirSync(path.join(d, 'sub'));
  fs.writeFileSync(path.join(d, 'a'), 'x'.repeat(10));
  fs.writeFileSync(path.join(d, 'sub', 'b'), 'y'.repeat(5));
  assert.equal(dirSize(d), 15);
  fs.rmSync(d, { recursive: true });
  assert.deepEqual(
    BUDGETS.map((b) => b.dir),
    ['assets', 'docs-assets'],
  );
});
