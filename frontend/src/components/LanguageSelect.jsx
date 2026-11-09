import React from 'react';
import { useI18n } from '../useI18n.js';

// Selector de idioma: "Automático" (idioma del navegador) o uno concreto, que se recuerda. Cada idioma con su propio nombre.
// En móvil se ve solo el código corto (span .lang-code) y el select real, transparente, se superpone para abrir el selector nativo.
export default function LanguageSelect() {
  const { t, preference, available, setLocale } = useI18n();
  // Nombre del idioma en su propio idioma, con inicial mayúscula («español» -> «Español»).
  const name = (c) => { const n = new Intl.DisplayNames([c], { type: 'language' }).of(c); return n.charAt(0).toLocaleUpperCase(c) + n.slice(1); };
  return (
    <label className="lang-select"><span className="lang-label sr-only">{t('lang.label')}</span>
      <span className="lang-code" aria-hidden="true">{preference === 'auto' ? t('lang.autoShort') : preference.split('-')[0].toUpperCase()}</span>
      <select value={preference} onChange={(e) => setLocale(e.target.value)}>
        <option value="auto">{t('lang.auto')}</option>
        {available.map((c) => <option key={c} value={c}>{name(c)}</option>)}
      </select>
    </label>
  );
}
