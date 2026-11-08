import React, { useEffect, useState } from 'react';
import { api } from '../api.js';
import Modal from './Modal.jsx';
import { errText } from '../useI18n.js';

// Solo lectura: el YAML tal como se escribiría (conserva los comentarios del fichero actual).
export default function YamlDialog({ config, onClose }) {
  const [text, setText] = useState(null);
  const [err, setErr] = useState('');
  useEffect(() => {
    api('/api/config/yaml', { method: 'POST', body: { config } })
      .then((r) => setText(r.yaml))
      .catch((e) => setErr(e.data?.errors ? 'El borrador tiene errores: corrígelos para ver el YAML.' : errText(e)));
  }, [config]);
  return (
    <Modal title="YAML (solo lectura)" onClose={onClose} wide>
      {err && <div className="alert error" role="alert">{err}</div>}
      {text === null && !err && <p className="muted">Generando…</p>}
      {text !== null && (
        <>
          <label htmlFor="yaml-view" className="sr-only">YAML resultante</label>
          <textarea id="yaml-view" className="yaml" readOnly rows={18} value={text} wrap="off" />
        </>
      )}
      <div className="row end"><button type="button" className="btn" onClick={onClose}>Cerrar</button></div>
    </Modal>
  );
}
