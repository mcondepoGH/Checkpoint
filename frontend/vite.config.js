import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import path from 'node:path';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Swagger UI empaquetada (documentación de la API en /api/docs): se copia de `swagger-ui-dist` (versión fijada en
// package.json) a `dist/docs-assets/`, que el Dockerfile deja en `static/`. El backend la sirve en
// `/api/docs-assets/<fichero>` (solo con sesión): no se usa ningún CDN y funciona sin internet.
export const SWAGGER_FILES = ['swagger-ui-bundle.js', 'swagger-ui.css', 'favicon-32x32.png'];
// Licencia Apache-2.0: va junto al código redistribuido (no se sirve por HTTP, solo queda en la imagen).
export const SWAGGER_LEGAL = ['LICENSE', 'NOTICE', 'swagger-ui-bundle.js.LICENSE.txt'];
const swaggerAssets = () => ({
  name: 'swagger-ui-assets',
  generateBundle() {
    const dir = path.dirname(createRequire(import.meta.url).resolve('swagger-ui-dist/package.json'));
    for (const f of [...SWAGGER_FILES, ...SWAGGER_LEGAL]) this.emitFile({ type: 'asset', fileName: `docs-assets/${f}`, source: readFileSync(path.join(dir, f)) });
  },
});

export default defineConfig({
  plugins: [react(), swaggerAssets()],
  server: { proxy: { '/api': 'http://localhost:8088' } },
});
