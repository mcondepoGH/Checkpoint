// Catálogos de idioma para los tests: es y en ya parseados, y `flat` (objeto anidado -> pares [clave.ruta, valor]).
import fs from 'node:fs';
import path from 'node:path';
import { SRC } from './bundle.mjs';

const load = (lang) => JSON.parse(fs.readFileSync(path.join(SRC, 'locales', `${lang}.json`), 'utf8'));
export const es = load('es');
export const en = load('en');
export const flat = (o, p = '') =>
  Object.entries(o).flatMap(([k, v]) => (v && typeof v === 'object' ? flat(v, `${p}${k}.`) : [[`${p}${k}`, v]]));
