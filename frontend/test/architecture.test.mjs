// Reglas de dependencia entre carpetas de src/ (ver docs/structure.md), comprobadas leyendo los imports.
//  - assets, locales y styles son recursos: los puede importar cualquiera.
//  - lib: sin React ni imports de hooks, components o pages.
//  - hooks: pueden usar lib y React; nada de components ni pages.
//  - components/ui: solo lib, hooks y otros ui; nunca una zona ni pages.
//  - components/<zona>: lib, hooks, ui y su propia zona; nunca otra zona ni pages.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { SRC } from './helpers/bundle.mjs';

const walk = (d) => fs.readdirSync(d, { withFileTypes: true }).flatMap((e) => (e.isDirectory() ? walk(path.join(d, e.name)) : [path.join(d, e.name)]));
const SPEC = /(?:\bfrom|\bimport)\s*\(?\s*(['"])([^'"\n]+)\1/g;
const rel = (f) => path.relative(SRC, f).split(path.sep).join('/');

/** Capa de un fichero o import (relativo a src): 'lib', 'hooks', 'pages', 'ui', 'zone:<nombre>', 'data', 'app' o 'react'/'ext'. */
function layerOf(p) {
  const parts = p.split('/');
  if (['assets', 'locales', 'styles'].includes(parts[0])) return 'data'; // recursos: los puede importar cualquiera
  if (parts[0] === 'lib' || parts[0] === 'hooks' || parts[0] === 'pages') return parts[0];
  if (parts[0] === 'components') return parts[1] === 'ui' ? 'ui' : `zone:${parts[1]}`;
  return 'app';
}

function importsOf(file) {
  const out = [];
  const s = fs.readFileSync(file, 'utf8');
  for (const m of s.matchAll(SPEC)) {
    const spec = m[2];
    if (spec.startsWith('#src/')) out.push({ spec, target: spec.slice(5) });
    else if (spec.startsWith('.')) out.push({ spec, target: rel(path.resolve(path.dirname(file), spec)) });
    else out.push({ spec, target: null });
  }
  return out;
}

const FILES = walk(SRC).filter((f) => /\.(js|jsx)$/.test(f) && !f.includes(`${path.sep}locales${path.sep}`));

test('las capas de src/ respetan las reglas de dependencia', () => {
  const bad = [];
  for (const f of FILES) {
    const me = layerOf(rel(f));
    for (const { spec, target } of importsOf(f)) {
      if (target === null) {
        if (me === 'lib' && /^react(-dom)?(\/|$)/.test(spec)) bad.push(`${rel(f)}: lib no importa React (${spec})`);
        continue;
      }
      const to = layerOf(target);
      if (to === 'data') continue;
      const note = `${rel(f)} importa ${target}`;
      if (me === 'lib' && to !== 'lib') bad.push(`${note}: lib solo importa de lib`);
      else if (me === 'hooks' && !['lib', 'hooks'].includes(to)) bad.push(`${note}: hooks solo importa de lib y hooks`);
      else if (me === 'ui' && !['lib', 'hooks', 'ui'].includes(to)) bad.push(`${note}: ui no importa de zonas ni páginas`);
      else if (me.startsWith('zone:') && !['lib', 'hooks', 'ui', me].includes(to)) bad.push(`${note}: una zona no importa de otra zona ni de páginas`);
    }
  }
  assert.deepEqual(bad, []);
});

test('el comprobador clasifica las capas', () => {
  assert.equal(layerOf('lib/api.js'), 'lib');
  assert.equal(layerOf('components/ui/Button.jsx'), 'ui');
  assert.equal(layerOf('components/profile/Avatar.jsx'), 'zone:profile');
  assert.equal(layerOf('App.jsx'), 'app');
});
