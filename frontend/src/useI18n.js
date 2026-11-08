// Instancia global del navegador + hook de React. Sin migrar aún ninguna pantalla (fase 3).
import { useSyncExternalStore } from 'react';
import { createI18n } from './i18n.js';
import { catalogs } from './locales/index.js';

const safeStorage = () => { try { return window.localStorage; } catch { return null; } };

export const i18n = createI18n({ catalogs, storage: safeStorage(), languages: navigator.languages?.length ? navigator.languages : [navigator.language] });
export const t = (key, params) => i18n.t(key, params);

// Devuelve t, el idioma activo, la preferencia ('auto' o código) y setLocale; re-renderiza al cambiar de idioma.
export function useI18n() {
  useSyncExternalStore(i18n.subscribe, () => i18n.locale);
  return { t: i18n.t, locale: i18n.locale, preference: i18n.preference, available: i18n.available, setLocale: i18n.setLocale };
}
