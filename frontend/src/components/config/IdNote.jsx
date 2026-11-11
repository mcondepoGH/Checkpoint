import React from 'react';
import { useI18n } from '#src/hooks/useI18n.js';
import { Alert } from '#src/components/ui/index.js';

// Pie de la tarjeta: ID interno (solo lectura) y aviso al renombrar un elemento que ya existe.
export default function IdNote({ id, isNew, renamed }) {
  const { t } = useI18n();
  return (
    <>
      {renamed && (
        <Alert as="p" variant="info" role="status">
          {t('idnote.keeps')}
        </Alert>
      )}
      <p className="idnote muted" title={t('idnote.title')}>
        {t('idnote.label')} <code>{id}</code>{isNew ? t('idnote.pending') : ''}
      </p>
    </>
  );
}
