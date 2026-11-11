// i18n propio y mínimo (sin dependencias). Catálogos JSON jerárquicos, t(clave, params) con Intl.PluralRules.
// Núcleo puro: recibe catálogos, almacenamiento e idiomas del navegador por parámetro (testable en Node).

export const BASE_LOCALE = 'es';
export const STORAGE_KEY = 'checkpoint.lang';
export const AUTO = 'auto';

// Elige idioma. Prioridad: elección manual guardada > (si eligió «Automático») idiomas del navegador >
// idioma por defecto del servidor (CHECKPOINT_LANG) > base. Sin elección guardada manda el por defecto, no el navegador.
export function pickLocale({ stored, languages = [], available, base = BASE_LOCALE, defaultLocale }) {
  if (stored && stored !== AUTO && available.includes(stored)) return stored;
  if (stored === AUTO) {
    for (const l of languages) {
      const short = String(l || '')
        .toLowerCase()
        .split('-')[0];
      if (available.includes(short)) return short;
    }
  }
  if (defaultLocale && available.includes(defaultLocale)) return defaultLocale;
  return available.includes(base) ? base : available[0];
}

const lookup = (cat, key) => key.split('.').reduce((o, k) => (o && typeof o === 'object' ? o[k] : undefined), cat);
const fill = (s, params) => s.replace(/\{(\w+)\}/g, (m, k) => (params && k in params ? String(params[k]) : m));

export function createI18n({ catalogs, storage, languages = [], base = BASE_LOCALE }) {
  const available = Object.keys(catalogs);
  const read = () => {
    try {
      return storage?.getItem(STORAGE_KEY) ?? null;
    } catch {
      return null;
    }
  };
  const write = (v) => {
    try {
      storage?.setItem(STORAGE_KEY, v);
    } catch {
      /* sin almacenamiento: no se recuerda */
    }
  };
  const subs = new Set();
  let choice = read(); // elección manual ('auto' o un código); null = ninguna
  let defaultLocale = base; // idioma por defecto del servidor (setDefaultLocale)
  const resolve = () => pickLocale({ stored: choice, languages, available, base, defaultLocale });
  let locale = resolve();
  const refresh = () => {
    const now = resolve();
    if (now !== locale) {
      locale = now;
      subs.forEach((f) => f());
    }
  };

  // Valor del catálogo activo; si falta, el del base. Los objetos plurales {one, other, ...} se resuelven con count.
  function t(key, params) {
    let v = lookup(catalogs[locale], key);
    if (v === undefined && locale !== base) v = lookup(catalogs[base], key);
    if (v && typeof v === 'object') {
      const n = params?.count;
      const cat = typeof n === 'number' ? new Intl.PluralRules(locale).select(n) : 'other';
      v = v[cat] ?? v.other;
    }
    return typeof v === 'string' ? fill(v, params) : key;
  }

  function setLocale(next) {
    if (next !== AUTO && !available.includes(next)) return;
    choice = next;
    write(next);
    refresh();
  }

  // Idioma por defecto que informa el servidor. No se guarda como elección del usuario; uno no soportado se ignora.
  function setDefaultLocale(next) {
    if (!available.includes(next)) return;
    defaultLocale = next;
    refresh();
  }

  return {
    t,
    setLocale,
    setDefaultLocale,
    available,
    get locale() {
      return locale;
    },
    // Valor para el selector: la elección guardada ('auto' o código) o, sin elección, el idioma por defecto en uso.
    get preference() {
      return choice && (choice === AUTO || available.includes(choice)) ? choice : locale;
    },
    subscribe(f) {
      subs.add(f);
      return () => subs.delete(f);
    },
  };
}
