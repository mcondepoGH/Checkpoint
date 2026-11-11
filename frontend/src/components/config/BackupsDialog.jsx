import React, { useEffect, useState } from 'react';
import { ApiError } from '#src/lib/api.js';
import EmptyState from '#src/components/ui/EmptyState.jsx';
import Modal from '#src/components/ui/Modal.jsx';
import DiffView from './DiffView.jsx';
import { errText, useI18n } from '#src/hooks/useI18n.js';
import { ui } from '#src/lib/errors.js';
import { Alert, Button } from '#src/components/ui/index.js';
import { diffConfig, listBackups, restoreBackup } from '#src/lib/api/config.js';

const when = (iso) => iso.replace('T', ' ');
const kb = (n) => `${Math.max(1, Math.round(n / 1024))} KB`;

export default function BackupsDialog({ baseVersion, dirty, onRestored, onClose }) {
  const { t, rich } = useI18n();
  const [list, setList] = useState(null);
  const [pick, setPick] = useState(null); // {name, diff}
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null); // error de la API o mensaje {code} (se traduce al pintar)

  useEffect(() => {
    listBackups()
      .then(setList)
      .catch((e) => setError(e));
  }, []);

  const preview = async (name) => {
    setError(null);
    try {
      setPick({ name, diff: (await diffConfig({ backup: name })).diff });
    } catch (e) {
      setError(e);
    }
  };

  const restore = async () => {
    setBusy(true);
    setError(null);
    try {
      onRestored(await restoreBackup(pick.name, baseVersion));
    } catch (e) {
      setError(e instanceof ApiError && e.status === 409 ? ui('backups.stale') : e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal title={t('backups.title')} onClose={onClose} wide>
      {error && (
        <Alert variant="error" role="alert">
          {errText(error)}
        </Alert>
      )}
      {!pick && (
        <>
          {list === null && !error && <p className="muted">{t('common.loading')}</p>}
          {list?.length === 0 && <EmptyState variant="inline" icon="🗂️" title={t('backups.none.title')} text={t('backups.none.text')} />}
          <ul className="backups">
            {list?.map((b) => (
              <li key={b.name} className="row between">
                <span>
                  <code>{when(b.created)}</code> <span className="muted">· {kb(b.size)}</span>
                </span>
                <Button onClick={() => preview(b.name)}>{t('backups.view')}</Button>
              </li>
            ))}
          </ul>
        </>
      )}
      {pick && (
        <>
          <p>
            {rich('backups.prompt', {
              when: when(
                pick.name
                  .replace('config.yaml.bak-', '')
                  .replace('_', 'T')
                  .replace(/(\d\d)(\d\d)(\d\d)$/, '$1:$2:$3'),
              ),
            })}
          </p>
          {dirty && <Alert>{t('backups.dirty')}</Alert>}
          <DiffView diff={pick.diff} />
          <div className="row end">
            <Button onClick={() => setPick(null)}>{t('backups.back')}</Button>
            <Button variant="primary" disabled={busy} onClick={restore}>
              {busy ? t('backups.restoring') : t('backups.restore')}
            </Button>
          </div>
        </>
      )}
      {!pick && (
        <div className="row end">
          <Button onClick={onClose}>{t('common.close')}</Button>
        </div>
      )}
    </Modal>
  );
}
