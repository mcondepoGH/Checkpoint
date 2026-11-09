import React from 'react';
import Modal from './Modal.jsx';
import { safeUrl, isPrerelease } from '../updates.js';
import { useI18n } from '../useI18n.js';
import { Alert, Button } from './ui/index.js';

// Detalle de la versión nueva. Las notas se pintan como texto (React escapa todo): nunca como HTML.
export default function UpdateDialog({ info, onClose }) {
  const { t } = useI18n();
  const url = safeUrl(info.url);
  const pre = isPrerelease(info);
  return (
    <Modal title={t('updates.badgeLabel')} onClose={onClose} wide>
      <dl className="update-versions">
        <div><dt>{t('updates.dialog.installed')}</dt><dd>{info.actual}</dd></div>
        <div><dt>{t('updates.dialog.new')}</dt><dd>{info.ultima}{pre && <span className="pre-tag">{t('updates.pre')}</span>}</dd></div>
      </dl>
      {pre && <Alert as="p" variant="warn">{t('updates.dialog.preWarn')}</Alert>}
      {info.notas ? <><h4>{t('updates.dialog.notesTitle')}</h4><div className="update-notes" tabIndex={0}>{info.notas}</div></> : <p className="muted">{t('updates.dialog.noNotes')}</p>}
      {url && <p><a href={url} target="_blank" rel="noopener noreferrer">{t('updates.dialog.link')}</a></p>}
      <p className="muted">{t('updates.dialog.manual')}</p>
      <div className="row end"><Button onClick={onClose}>{t('common.close')}</Button></div>
    </Modal>
  );
}
