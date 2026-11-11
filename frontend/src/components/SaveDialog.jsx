import React, { useState } from 'react';
import { api, ApiError } from '#src/lib/api.js';
import Modal from './Modal.jsx';
import DiffView from './DiffView.jsx';
import { errText, useI18n } from '#src/hooks/useI18n.js';
import { ui } from '#src/lib/errors.js';
import { Alert, Button } from '#src/components/ui/index.js';

// Vista previa + confirmación de guardado. Ante 409 (config.yaml cambió por fuera) vuelve a calcular
// el diff contra la versión nueva del fichero y deja confirmar o recargar.
export default function SaveDialog({ config, diff: initial, baseVersion, onSaved, onReload, onClose }) {
  const { t } = useI18n();
  const [diff, setDiff] = useState(initial);
  const [base, setBase] = useState(baseVersion);
  const [conflict, setConflict] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null); // error de la API o mensaje {code} (se traduce al pintar)

  const confirm = async () => {
    setBusy(true);
    setError(null);
    try {
      const r = await api('/api/config', { method: 'PUT', body: { config, base_version: base } });
      onSaved(r);
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        try {
          const d = await api('/api/config/diff', { method: 'POST', body: { config } });
          setDiff(d.diff);
          setBase(d.version);
          setConflict(true);
        } catch (e2) { setError(e2); }
      } else if (e instanceof ApiError && e.status === 422) {
        setError(ui('save.invalid'));
      } else setError(e);
    } finally { setBusy(false); }
  };

  return (
    <Modal title={conflict ? t('save.titleStale') : t('save.title')} onClose={onClose} wide>
      {conflict && (
        <Alert variant="error" role="alert">
          {t('save.staleText')}
        </Alert>
      )}
      <DiffView diff={diff} />
      {error && <Alert variant="error" role="alert">{errText(error)}</Alert>}
      <div className="row end">
        {conflict && <Button onClick={onReload}>{t('save.reload')}</Button>}
        <Button onClick={onClose}>{t('common.cancel')}</Button>
        <Button variant="primary" disabled={busy || diff?.empty} onClick={confirm}>
          {busy ? t('save.saving') : conflict ? t('save.overwrite') : t('save.confirm')}
        </Button>
      </div>
    </Modal>
  );
}
