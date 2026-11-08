import React from 'react';
import { useI18n } from '../useI18n.js';

// Selector de idioma: "Automático" (navegador) o uno concreto, que se recuerda. Cada idioma con su propio nombre.
export default function LanguageSelect() {
  const { t, preference, available, setLocale } = useI18n();
  const name = (c) => new Intl.DisplayNames([c], { type: 'language' }).of(c);
  return (
    <label className="lang-select">{t('lang.label')}
      <select value={preference} onChange={(e) => setLocale(e.target.value)}>
        <option value="auto">{t('lang.auto')}</option>
        {available.map((c) => <option key={c} value={c}>{name(c)}</option>)}
      </select>
    </label>
  );
}
