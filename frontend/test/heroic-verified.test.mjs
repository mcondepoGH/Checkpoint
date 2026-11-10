// Heroic ya no se marca como «sin verificar»: pestaña y nota (es y en), fuente de los lanzadores y README.
// Windows (Playnite) sí sigue marcado en el README: el test lo fija para no relajar los dos a la vez por error.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { LAUNCHERS } from '../src/launchers.js';

const read = (rel) => fs.readFileSync(new URL(rel, import.meta.url), 'utf8');
const UNVERIFIED = /sin verificar|unverified|not verified|no verificad/i;
const flat = (o, p = '') => Object.entries(o).flatMap(([k, v]) => (v && typeof v === 'object' ? flat(v, `${p}${k}.`) : [[`${p}${k}`, v]]));
const locale = (l) => Object.fromEntries(flat(JSON.parse(read(`../src/locales/${l}.json`))));

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

test('README: la entrada de Heroic no dice «sin verificar»; la de Windows sí (sigue marcada)', () => {
  const readme = read('../../README.md');
  const line = (re) => readme.split('\n').find((x) => re.test(x));
  const heroic = line(/^- \*\*Heroic\*\*/);
  assert.ok(heroic, 'falta la entrada de Heroic en el README');
  assert.ok(!UNVERIFIED.test(heroic), heroic);
  assert.ok(UNVERIFIED.test(line(/^- \*\*Windows \/ Playnite\*\*/)));
  // y ninguna línea que hable de Heroic (salvo la de Windows, que no lo nombra) lo da por no verificado
  for (const x of readme.split('\n').filter((y) => /heroic/i.test(y))) assert.ok(!UNVERIFIED.test(x), x.slice(0, 120));
});
