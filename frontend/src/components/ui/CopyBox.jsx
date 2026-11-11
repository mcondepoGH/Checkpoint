import React, { useEffect, useId, useRef, useState } from 'react';
import { copyText } from '#src/lib/clipboard.js';
import { useI18n } from '#src/hooks/useI18n.js';
import Icon from './Icon.jsx';
import Button from './Button.jsx';

// Caja de código de solo lectura con botón de copiar (icono copiar -> check 2 s). El texto ajusta en varias líneas.
// value: texto a copiar. label: aria-label de la caja. what: qué se copia («comando de Steam»); el botón dice «Copiar {what}» (sin él, «Copiar»). describedBy: id de una ayuda. initialCopied: solo para pintar el estado «copiado» en pruebas.
// Copia con clipboard.js (fallback con execCommand cuando no hay API moderna, p. ej. HTTP en la LAN).
export default function CopyBox({ value, label, what, describedBy, initialCopied = false, className }) {
  const { t } = useI18n();
  const [copied, setCopied] = useState(initialCopied);
  const timer = useRef(null);
  const id = useId();
  useEffect(() => () => clearTimeout(timer.current), []);
  const copy = async () => {
    const ok = await copyText(value);
    setCopied(ok);
    clearTimeout(timer.current);
    if (ok) timer.current = setTimeout(() => setCopied(false), 2000);
  };
  const copyLabel = copied ? t('common.copied') : what ? t('common.copyWhat', { what }) : t('common.copy');
  return (
    <div className={['copybox', className].filter(Boolean).join(' ')}>
      <div
        id={id}
        className="copybox-field"
        tabIndex={0}
        role="textbox"
        aria-readonly="true"
        aria-multiline="true"
        aria-label={label}
        aria-describedby={describedBy}
      >
        {value}
      </div>
      <Button iconOnly className="copybox-copy" onClick={copy} title={copyLabel} aria-label={copyLabel}>
        <Icon name={copied ? 'check' : 'copy'} />
      </Button>
      <span className="sr-only" role="status">
        {copied ? t('common.copied') : ''}
      </span>
    </div>
  );
}
