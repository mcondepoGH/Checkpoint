import React, { useEffect, useState } from 'react';
import { api, ApiError } from '../api.js';
import EmptyState from './EmptyState.jsx';
import Modal from './Modal.jsx';
import DiffView from './DiffView.jsx';
import { errText, useI18n } from '../useI18n.js';
import { ui } from '../errors.js';

const when = (iso) => iso.replace('T', ' ');
const kb = (n) => `${Math.max(1, Math.round(n / 1024))} KB`;

export default function BackupsDialog({ baseVersion, dirty, onRestored, onClose }) {
  const { t, rich } = useI18n();
  const [list, setList] = useState(null);
  const [pick, setPick] = useState(null); // {name, diff}
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null); // error de la API o mensaje {code} (se traduce al pintar)

  useEffect(() => { api('/api/config/backups').then(setList).catch((e) => setError(e)); }, []);

  const preview = async (name) => {
    setError(null);
    try { setPick({ name, diff: (await api('/api/config/diff', { method: 'POST', body: { backup: name } })).diff }); }
    catch (e) { setError(e); }
  };

  const restore = async () => {
    setBusy(true);
    setError(null);
    try { onRestored(await api('/api/config/restore', { method: 'POST', body: { name: pick.name, base_version: baseVersion } })); }
    catch (e) {
      setError(e instanceof ApiError && e.status === 409 ? ui('backups.stale') : e);
    } finally { setBusy(false); }
  };

  return (
    <Modal title={t('backups.title')} onClose={onClose} wide>
      {error && <div className="alert error" role="alert">{errText(error)}</div>}
      {!pick && (
        <>
          {list === null && !error && <p className="muted">{t('common.loading')}</p>}
          {list?.length === 0 && (
            <EmptyState variant="inline" icon="🗂️" title={t('backups.none.title')}
              text={t('backups.none.text')} />
          )}
          <ul className="backups">
            {list?.map((b) => (
              <li key={b.name} className="row between">
                <span><code>{when(b.created)}</code> <span className="muted">· {kb(b.size)}</span></span>
                <button type="button" className="btn" onClick={() => preview(b.name)}>{t('backups.view')}</button>
              </li>
            ))}
          </ul>
        </>
      )}
      {pick && (
        <>
          <p>{rich('backups.prompt', { when: when(pick.name.replace('config.yaml.bak-', '').replace('_', 'T').replace(/(\d\d)(\d\d)(\d\d)$/, '$1:$2:$3')) })}</p>
          {dirty && <div className="alert">{t('backups.dirty')}</div>}
          <DiffView diff={pick.diff} />
          <div className="row end">
            <button type="button" className="btn" onClick={() => setPick(null)}>{t('backups.back')}</button>
            <button type="button" className="btn primary" disabled={busy} onClick={restore}>{busy ? t('backups.restoring') : t('backups.restore')}</button>
          </div>
        </>
      )}
      {!pick && <div className="row end"><button type="button" className="btn" onClick={onClose}>{t('common.close')}</button></div>}
    </Modal>
  );
}
