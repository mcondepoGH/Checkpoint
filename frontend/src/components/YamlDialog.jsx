import React, { useEffect, useState } from 'react';
import { api } from '#src/lib/api.js';
import Modal from './Modal.jsx';
import { errText, useI18n } from '#src/hooks/useI18n.js';
import { ui } from '#src/lib/errors.js';
import { Alert, Button } from '#src/components/ui/index.js';

// Solo lectura: el YAML tal como se escribiría (conserva los comentarios del fichero actual).
export default function YamlDialog({ config, onClose }) {
  const { t } = useI18n();
  const [text, setText] = useState(null);
  const [err, setErr] = useState(null); // error de la API o mensaje {code} (se traduce al pintar)
  useEffect(() => {
    api('/api/config/yaml', { method: 'POST', body: { config } })
      .then((r) => setText(r.yaml))
      .catch((e) => setErr(e.data?.errors ? ui('yaml.invalid') : e));
  }, [config]);
  return (
    <Modal title={t('yaml.title')} onClose={onClose} wide>
      {err && <Alert variant="error" role="alert">{errText(err)}</Alert>}
      {text === null && !err && <p className="muted">{t('yaml.generating')}</p>}
      {text !== null && (
        <>
          <label htmlFor="yaml-view" className="sr-only">{t('yaml.label')}</label>
          <textarea id="yaml-view" className="yaml" readOnly rows={18} value={text} wrap="off" />
        </>
      )}
      <div className="row end"><Button onClick={onClose}>{t('common.close')}</Button></div>
    </Modal>
  );
}
