import React from 'react';
import { useI18n } from '../useI18n.js';

// Pie de la tarjeta: ID interno (solo lectura) y aviso al renombrar un elemento que ya existe.
export default function IdNote({ id, isNew, renamed }) {
  const { t } = useI18n();
  return (
    <>
      {renamed && (
        <p className="alert info" role="status">
          {t('idnote.keeps')}
        </p>
      )}
      <p className="idnote muted" title={t('idnote.title')}>
        {t('idnote.label')} <code>{id}</code>{isNew ? t('idnote.pending') : ''}
      </p>
    </>
  );
}
