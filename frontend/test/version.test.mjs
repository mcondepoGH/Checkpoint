// VERSION (raíz) es la fuente única de la versión; package.json y package-lock.json deben coincidir con ella.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');
const version = fs.readFileSync(path.join(ROOT, '..', 'VERSION'), 'utf8').trim();

test('package.json y package-lock.json tienen la versión de VERSION', () => {
  const pkg = JSON.parse(fs.readFileSync(path.join(ROOT, 'package.json'), 'utf8'));
  const lock = JSON.parse(fs.readFileSync(path.join(ROOT, 'package-lock.json'), 'utf8'));
  assert.equal(pkg.version, version);
  assert.equal(lock.version, version);
  assert.equal(lock.packages[''].version, version);
});
