import React, { useId } from 'react';
import { useI18n } from '#src/hooks/useI18n.js';
import Field from '#src/components/ui/Field.jsx';
import Icon from '#src/components/ui/Icon.jsx';
import { Select } from '#src/components/ui/index.js';

// Selector de idioma: "Automático" (idioma del navegador) o uno concreto, que se recuerda. Cada idioma con su propio nombre.
// `row`: misma fila que las demás preferencias del perfil (icono + etiqueta a la izquierda, valor actual = el propio select a la derecha).
export default function LanguageSelect({ row = false }) {
  const { t, preference, available, setLocale } = useI18n();
  const id = useId();
  // Nombre del idioma en su propio idioma, con inicial mayúscula («español» -> «Español»).
  const name = (c) => { const n = new Intl.DisplayNames([c], { type: 'language' }).of(c); return n.charAt(0).toLocaleUpperCase(c) + n.slice(1); };
  const options = [{ value: 'auto', label: t('lang.auto') }, ...available.map((c) => ({ value: c, label: name(c) }))];
  if (row) {
    return (
      <div className="profile-row profile-pref">
        <Icon name="globe" />
        <label htmlFor={id} className="profile-row-label">{t('lang.label')}</label>
        <Select id={id} className="profile-row-value" value={preference} onChange={(e) => setLocale(e.target.value)} options={options} />
      </div>
    );
  }
  return (
    <Field label={t('lang.label')}>
      {(p) => <Select {...p} value={preference} onChange={(e) => setLocale(e.target.value)} options={options} />}
    </Field>
  );
}
