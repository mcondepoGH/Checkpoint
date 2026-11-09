// Catálogos: es y en tienen exactamente las mismas claves, {params} y categorías de plural; los códigos que usa el
// backend existen; y no quedan literales sin traducir en el JSX (heurística acotada).
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.join(HERE, '..', 'src');
const load = (n) => JSON.parse(fs.readFileSync(path.join(SRC, 'locales', `${n}.json`), 'utf8'));
const es = load('es');
const en = load('en');
const PLURAL = new Set(['zero', 'one', 'two', 'few', 'many', 'other']);
const isPlural = (v) => v && typeof v === 'object' && 'other' in v && Object.keys(v).every((k) => PLURAL.has(k));

// Hojas {clave plana -> cadena | objeto plural}
function flat(o, p = '') {
  const out = {};
  for (const [k, v] of Object.entries(o)) {
    if (v && typeof v === 'object' && !isPlural(v)) Object.assign(out, flat(v, `${p}${k}.`));
    else out[p + k] = v;
  }
  return out;
}
const params = (v) => [...new Set((JSON.stringify(v).match(/\{(\w+)\}/g) || []))].sort();
const F = { es: flat(es), en: flat(en) };

test('es y en tienen exactamente las mismas claves', () => {
  const a = Object.keys(F.es).sort();
  const b = Object.keys(F.en).sort();
  assert.deepEqual(a.filter((k) => !(k in F.en)), [], 'faltan en en.json');
  assert.deepEqual(b.filter((k) => !(k in F.es)), [], 'sobran en en.json');
  assert.ok(a.length > 400);
});

test('mismos {params} en cada clave y misma forma (cadena / plural)', () => {
  for (const k of Object.keys(F.es)) {
    assert.deepEqual(params(F.en[k]), params(F.es[k]), `params de ${k}`);
    assert.equal(isPlural(F.en[k]), isPlural(F.es[k]), `forma de ${k}`);
    if (isPlural(F.en[k])) {
      // inglés: one/other; español: one/other
      assert.deepEqual(Object.keys(F.en[k]).sort(), ['one', 'other'], `plural en de ${k}`);
      assert.ok(params(F.en[k].one).includes('{count}') && params(F.en[k].other).includes('{count}'), `count en ${k}`);
    }
  }
});

test('ninguna traducción vacía y las de en no son copia literal del español (salvo términos comunes)', () => {
  const SAME_OK = /^(sync\.log\.title|app\.tab\.sync\.short|device\.host|diff\.general|keyhelp\.infoTitle|autosync\.hoursShort|sync\.offline|err\.main\.game_ambiguous|err\.hook\.device_ambiguous|err\.main\.restore_failed|err\.config\.invalid|err\.config\.inconsistent|err\.sync\.(ref_invalid|unexpected)|err\.scheduler\.summary|err\.configstore\.backup_invalid|profile\.apikey\.title|launcher\.tab\.(steam|lutris|windows)|launcher\.cmd\.powershell|launcher\.last)$/;
  for (const k of Object.keys(F.en)) {
    const s = JSON.stringify(F.en[k]);
    assert.ok(s.length > 2 && !/^"\s*"$/.test(s), `vacía ${k}`);
    if (!SAME_OK.test(k) && !k.startsWith('keyhelp.step.') && F.en[k] === F.es[k] && typeof F.es[k] === 'string') {
      assert.fail(`en.json igual a es.json en ${k}: ${F.en[k]}`);
    }
  }
});

test('los códigos err.* del backend existen en el catálogo (y en inglés)', () => {
  const dir = path.join(HERE, '..', '..', 'backend', 'app');
  const used = new Set();
  for (const f of fs.readdirSync(dir).filter((x) => x.endsWith('.py'))) {
    for (const m of fs.readFileSync(path.join(dir, f), 'utf8').matchAll(/["'](err\.[a-z_]+\.[a-z_.]+)["']/g)) used.add(m[1]);
  }
  assert.ok(used.size > 100);
  for (const c of used) {
    if (c.endsWith('_')) { // prefijo de un código dinámico (p. ej. err.sync.conflict_ + motivo): debe haber claves con él
      assert.ok(Object.keys(F.es).some((k) => k.startsWith(c)) && Object.keys(F.en).some((k) => k.startsWith(c)), `prefijo ${c}`);
      continue;
    }
    assert.ok(c in F.es, `falta en es.json: ${c}`);
    assert.ok(c in F.en, `falta en en.json: ${c}`);
  }
});

// ---- heurística de literales sin traducir en JSX ----
function jsxFiles(d) {
  return fs.readdirSync(d, { withFileTypes: true }).flatMap((e) => (e.isDirectory() ? jsxFiles(path.join(d, e.name))
    : e.name.endsWith('.jsx') ? [path.join(d, e.name)] : []));
}
// Marcas, términos técnicos y ejemplos de código que no se traducen.
const ALLOWED = new Set(['Checkpoint']);

test('el JSX no contiene texto ni atributos de texto literales (todo va por t())', () => {
  const found = [];
  for (const f of jsxFiles(SRC)) {
    const s = fs.readFileSync(f, 'utf8');
    // Texto entre etiquetas: solo se mira lo que parece prosa JSX (sin código de JS cerca).
    for (const m of s.matchAll(/>([^<>{}=;()`]*[A-Za-zÁ-ú]{2}[^<>{}=;()`]*)</g)) {
      const tx = m[1].trim();
      if (tx && !ALLOWED.has(tx) && !/[|&?:]/.test(tx)) found.push(`${path.relative(SRC, f)}: texto «${tx}»`);
    }
    for (const m of s.matchAll(/\b(placeholder|title|aria-label|alt|label|hint|text|legend)="([^"]*[A-Za-zÁ-ú]{2}[^"]*)"/g)) {
      if (m[2] !== 'ssh-ed25519 AAAAC3Nza...XXXX checkpoint') found.push(`${path.relative(SRC, f)}: ${m[1]}="${m[2]}"`);
    }
  }
  assert.deepEqual(found, []);
});
