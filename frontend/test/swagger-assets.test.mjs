// Swagger UI empaquetada: versión fijada, ficheros que el build copia a dist/docs-assets y que no dependa de CDNs.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { SWAGGER_FILES, SWAGGER_LEGAL } from '../vite.config.js';

const root = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');
const pkg = JSON.parse(fs.readFileSync(path.join(root, 'package.json'), 'utf8'));

test('swagger-ui-dist va con versión exacta (sin ^ ni ~)', () => {
  assert.match(pkg.dependencies['swagger-ui-dist'], /^\d+\.\d+\.\d+$/);
});

test('el paquete instalado coincide con la versión fijada y trae los ficheros que se copian', { skip: !fs.existsSync(path.join(root, 'node_modules/swagger-ui-dist')) && 'sin node_modules' }, () => {
  const dir = path.join(root, 'node_modules/swagger-ui-dist');
  assert.equal(JSON.parse(fs.readFileSync(path.join(dir, 'package.json'), 'utf8')).version, pkg.dependencies['swagger-ui-dist']);
  for (const f of [...SWAGGER_FILES, ...SWAGGER_LEGAL]) assert.ok(fs.existsSync(path.join(dir, f)), f);
});

test('el backend sirve exactamente los ficheros que el build copia', () => {
  const py = fs.readFileSync(path.join(root, '..', 'backend/app/api/docs/install.py'), 'utf8');
  for (const f of SWAGGER_FILES) assert.ok(py.includes(`"${f}"`), f);
});
