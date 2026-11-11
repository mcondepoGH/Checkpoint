// Cobertura del frontend: ejecuta `node --test` con el reporter lcov (Node 22 no tiene umbral nativo),
// suma LF/LH (líneas) y BRF/BRH (ramas) de src/** y falla si no alcanza los mínimos.
// Uso: node scripts/check-coverage.mjs           (ejecuta los tests y comprueba)
//      node scripts/check-coverage.mjs --only    (solo comprueba coverage/lcov.info ya generado)
import { spawnSync } from 'node:child_process';
import { mkdirSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

export const MIN_LINES = 90;
export const MIN_BRANCHES = 88;

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const lcovPath = path.join(root, 'coverage', 'lcov.info');

// Suma los totales de los registros SF de src/**. `text` es el contenido de un lcov.info.
export function summarize(text) {
  const t = { LF: 0, LH: 0, BRF: 0, BRH: 0, files: 0 };
  let inSrc = false;
  for (const raw of text.split('\n')) {
    const line = raw.trim();
    if (line.startsWith('SF:')) {
      inSrc = /(^|[\\/])src[\\/]/.test(line.slice(3));
      if (inSrc) t.files++;
    } else if (inSrc) {
      const m = /^(LF|LH|BRF|BRH):(\d+)$/.exec(line);
      if (m) t[m[1]] += Number(m[2]);
    }
  }
  return t;
}

const pct = (h, f) => (f ? (100 * h) / f : 100);

export function check(t, minLines = MIN_LINES, minBranches = MIN_BRANCHES) {
  const lines = pct(t.LH, t.LF);
  const branches = pct(t.BRH, t.BRF);
  const ok = t.files > 0 && lines >= minLines && branches >= minBranches;
  return { lines, branches, ok };
}

function main() {
  if (!process.argv.includes('--only')) {
    mkdirSync(path.dirname(lcovPath), { recursive: true });
    const r = spawnSync(
      process.execPath,
      [
        '--test',
        '--experimental-test-coverage',
        '--test-coverage-include=src/**',
        '--test-reporter=spec',
        '--test-reporter-destination=stdout',
        '--test-reporter=lcov',
        `--test-reporter-destination=${lcovPath}`,
        'test/**/*.test.mjs',
      ],
      { cwd: root, stdio: ['ignore', 'inherit', 'inherit'] },
    );
    if (r.status !== 0) {
      console.error('Los tests fallan: no se comprueba la cobertura.');
      process.exit(r.status ?? 1);
    }
  }
  const t = summarize(readFileSync(lcovPath, 'utf8'));
  const { lines, branches, ok } = check(t);
  console.log(
    `Cobertura src/** (${t.files} ficheros): líneas ${lines.toFixed(1)} % (mín. ${MIN_LINES}), ramas ${branches.toFixed(1)} % (mín. ${MIN_BRANCHES})`,
  );
  if (!ok) {
    console.error('Cobertura por debajo del umbral.');
    process.exit(1);
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) main();
