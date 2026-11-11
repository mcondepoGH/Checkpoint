// Presupuesto de tamaño del bundle: suma los bytes de dist/<carpeta> y falla si pasa del umbral.
// Los umbrales son el tamaño medido en v1.10.0 + ~10 %. Si crece a propósito, súbelos aquí en el mismo cambio.
// swagger-ui-dist (docs-assets) pesa mucho más que la app: se mide aparte para que no tape el crecimiento de la app.
import { readdirSync, statSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

export const BUDGETS = [
  { dir: 'assets', label: 'app (JS + CSS propios y React)', max: 363_000 }, // medido: 329 905 B
  { dir: 'docs-assets', label: 'swagger-ui-dist (docs de la API)', max: 2_080_000 }, // medido: 1 888 467 B
];

// Suma recursiva del tamaño en bytes de los ficheros de una carpeta.
export function dirSize(dir) {
  let total = 0;
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, entry.name);
    total += entry.isDirectory() ? dirSize(p) : statSync(p).size;
  }
  return total;
}

function main() {
  const dist = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', 'dist');
  let ok = true;
  for (const b of BUDGETS) {
    let size;
    try {
      size = dirSize(path.join(dist, b.dir));
    } catch {
      console.error(`No existe dist/${b.dir}: ejecuta antes "npm run build".`);
      process.exit(1);
    }
    const pass = size <= b.max;
    ok &&= pass;
    console.log(`${pass ? 'OK ' : 'FALLA'} dist/${b.dir}: ${size} B de ${b.max} B (${((100 * size) / b.max).toFixed(1)} %) - ${b.label}`);
  }
  if (!ok) {
    console.error('El bundle supera el presupuesto de tamaño.');
    process.exit(1);
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) main();
