// Heroic ya no se marca como «sin verificar»: pestaña y nota (es y en), fuente de los lanzadores y README.
// Playnite y Proton/Wine tampoco: ningún lanzador del README ni de la interfaz lleva la marca.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { en, es, flat } from './helpers/locales.mjs';
import { LAUNCHERS } from '#src/launchers.js';

const read = (rel) => fs.readFileSync(new URL(rel, import.meta.url), 'utf8');
const UNVERIFIED = /sin verificar|unverified|not verified|no verificad/i;
const locale = (l) => Object.fromEntries(flat({ es, en }[l]));

test('Heroic está entre los lanzadores y su pestaña se llama «Heroic» a secas (es y en)', () => {
  assert.ok(LAUNCHERS.includes('heroic'));
  for (const l of ['es', 'en']) {
    const L = locale(l);
    assert.equal(L['launcher.tab.heroic'], 'Heroic', l);
    assert.ok(L['launcher.where.heroic'].length > 0, l);
  }
});

test('ningún texto de Heroic en los locales (pestaña, dónde pegarlo, cualquier clave heroic) dice «sin verificar»', () => {
  for (const l of ['es', 'en']) {
    const L = locale(l);
    const heroic = Object.entries(L).filter(([k, v]) => /heroic/i.test(k) || /heroic/i.test(String(v)));
    assert.ok(heroic.length >= 2, `${l}: pocas cadenas de Heroic`);
    for (const [k, v] of heroic) assert.ok(!UNVERIFIED.test(String(v)), `${l}: ${k} = «${v}»`);
  }
});

test('la fuente de los lanzadores no marca Heroic como no verificado', () => {
  for (const f of ['../src/launchers.js', '../src/components/LauncherBlock.jsx']) assert.ok(!UNVERIFIED.test(read(f)), f);
});

test('README: ni Heroic ni Windows/Playnite ni la nota de Proton/Wine dicen «sin verificar»', () => {
  const readme = read('../../README.md');
  const line = (re) => readme.split('\n').find((x) => re.test(x));
  const heroic = line(/^- \*\*Heroic\*\*/);
  assert.ok(heroic, 'falta la entrada de Heroic en el README');
  assert.ok(!UNVERIFIED.test(heroic), heroic);
  const win = line(/^- \*\*Windows \/ Playnite\*\*/);
  assert.ok(win && !UNVERIFIED.test(win), win);
  const proton = line(/Proton\/Wine/);
  assert.ok(proton && !UNVERIFIED.test(proton), proton);
  // la sección de lanzadores (Hooks) entera, salvo el motor de macOS/Windows nativo, que no es un lanzador
  const hooks = readme.slice(readme.indexOf('Steam / Steam Deck'));
  for (const x of hooks.split('\n')) assert.ok(!UNVERIFIED.test(x), x.slice(0, 120));
  // y ninguna línea que hable de Heroic lo da por no verificado
  for (const x of readme.split('\n').filter((y) => /heroic/i.test(y))) assert.ok(!UNVERIFIED.test(x), x.slice(0, 120));
});
