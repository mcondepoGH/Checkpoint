import React from 'react';
import { useI18n } from '../useI18n.js';
import Field from './Field.jsx';
import { Select } from './ui/index.js';

// Selector de idioma: "Automático" (idioma del navegador) o uno concreto, que se recuerda. Cada idioma con su propio nombre.
export default function LanguageSelect() {
  const { t, preference, available, setLocale } = useI18n();
  // Nombre del idioma en su propio idioma, con inicial mayúscula («español» -> «Español»).
  const name = (c) => { const n = new Intl.DisplayNames([c], { type: 'language' }).of(c); return n.charAt(0).toLocaleUpperCase(c) + n.slice(1); };
  return (
    <Field label={t('lang.label')}>
      {(p) => (
        <Select {...p} value={preference} onChange={(e) => setLocale(e.target.value)}
          options={[{ value: 'auto', label: t('lang.auto') }, ...available.map((c) => ({ value: c, label: name(c) }))]} />
      )}
    </Field>
  );
}
