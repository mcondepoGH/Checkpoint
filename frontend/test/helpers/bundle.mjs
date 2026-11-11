// Monta módulos de `src/` con esbuild (viene con Vite) para probarlos con react-dom/server.
// Si esbuild no está disponible devuelve `skip` con el motivo, para pasarlo a `test(..., { skip })`.
// Dentro de `contents` los imports se escriben con el alias `#src/...` (package.json -> imports).
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

export const FRONTEND = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
export const SRC = path.join(FRONTEND, 'src');

/** Texto de un fichero de `src/` (partes de ruta relativas a `src`). */
export const readSrc = (...parts) => fs.readFileSync(path.join(SRC, ...parts), 'utf8');

/**
 * Compila `contents` (JSX/JS, con `export { ... }`) y devuelve { mod, skip }.
 * Opciones: `plugins` (esbuild), `navigator` (true: define `globalThis.navigator` con es antes de importar).
 */
export async function bundle(contents, { plugins = [], navigator = false, tag = 'ckpt' } = {}) {
  try {
    const { build } = await import('esbuild');
    const out = await build({
      stdin: { contents, resolveDir: SRC, loader: 'jsx' },
      plugins,
      bundle: true,
      write: false,
      format: 'esm',
      platform: 'node',
      jsx: 'transform',
      define: { 'process.env.NODE_ENV': '"production"' },
      loader: { '.svg': 'dataurl' },
      banner: { js: "import { createRequire } from 'node:module'; const require = createRequire(import.meta.url);" },
      logLevel: 'silent',
    });
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), `${tag}-`));
    const file = path.join(dir, 'bundle.mjs');
    fs.writeFileSync(file, out.outputFiles[0].text);
    if (navigator) globalThis.navigator ??= { languages: ['es'], language: 'es' };
    const mod = await import(pathToFileURL(file).href);
    fs.rmSync(dir, { recursive: true, force: true });
    return { mod, skip: false };
  } catch (e) {
    return { mod: null, skip: `esbuild no disponible: ${e.message}` };
  }
}
