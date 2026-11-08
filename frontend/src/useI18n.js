// Instancia global del navegador + hook de React. Los componentes llaman a useI18n() para re-renderizar al cambiar de idioma.
import React, { useSyncExternalStore } from 'react';
import { createI18n } from './i18n.js';
import { catalogs } from './locales/index.js';
import { errorText } from './errors.js';
import { api } from './api.js';

const safeStorage = () => { try { return window.localStorage; } catch { return null; } };

export const i18n = createI18n({ catalogs, storage: safeStorage(), languages: navigator.languages?.length ? navigator.languages : [navigator.language] });
export const t = (key, params) => i18n.t(key, params);

// Texto con marcas mínimas: <b>negrita</b> y <code>código</code> (solo en textos del catálogo, nunca en datos).
// Devuelve nodos de React; el resto de {params} ya viene sustituido por t().
export function rich(text) {
  const out = [];
  const re = /<(b|code)>(.*?)<\/\1>/g;
  let last = 0;
  let m;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    out.push(React.createElement(m[1] === 'b' ? 'strong' : 'code', { key: out.length }, m[2]));
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push(text.slice(last));
  return React.createElement(React.Fragment, null, ...out);
}

// Idioma por defecto del servidor (CHECKPOINT_LANG), público: se pide antes de pintar el login. Nunca falla.
export const initDefaultLang = () => api('/api/public')
  .then((r) => { if (r && typeof r.default_lang === 'string') i18n.setDefaultLocale(r.default_lang); })
  .catch(() => {});

// Devuelve t, rich (t con <b>/<code> como nodos), el idioma activo, la preferencia ('auto' o código) y setLocale;
// re-renderiza al cambiar de idioma.
export function useI18n() {
  useSyncExternalStore(i18n.subscribe, () => i18n.locale, () => i18n.locale); // 3.er argumento: render en servidor (tests)
  return {
    t: i18n.t, rich: (key, params) => rich(i18n.t(key, params)), locale: i18n.locale, preference: i18n.preference,
    available: i18n.available, setLocale: i18n.setLocale,
  };
}

// Texto traducido de un error de la API (ver errors.js). Llamar al pintar (en un componente con useI18n), no al
// producirse el error: así se retraduce al cambiar de idioma. Guardar el error (o `ui(...)`), no su texto.
export const errText = (e) => errorText(e, i18n.t);
