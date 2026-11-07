import React, { useState } from 'react';
import { api, ApiError } from '../api.js';
import Modal from './Modal.jsx';
import DiffView from './DiffView.jsx';

// Vista previa + confirmación de guardado. Ante 409 (config.yaml cambió por fuera) vuelve a calcular
// el diff contra la versión nueva del fichero y deja confirmar o recargar.
export default function SaveDialog({ config, diff: initial, baseVersion, onSaved, onReload, onClose }) {
  const [diff, setDiff] = useState(initial);
  const [base, setBase] = useState(baseVersion);
  const [conflict, setConflict] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const confirm = async () => {
    setBusy(true);
    setError('');
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
        } catch (e2) { setError(e2.message); }
      } else if (e instanceof ApiError && e.status === 422) {
        setError('La configuración ya no es válida: revisa los campos marcados.');
      } else setError(e.message);
    } finally { setBusy(false); }
  };

  return (
    <Modal title={conflict ? 'config.yaml cambió por fuera' : 'Revisar cambios'} onClose={onClose} wide>
      {conflict && (
        <div className="alert error" role="alert">
          El fichero se modificó desde que lo cargaste. Abajo se ven las diferencias de tu borrador contra la versión actual:
          lo que no aparezca en tu borrador se eliminará. Puedes confirmar igualmente o recargar y descartar tus cambios.
        </div>
      )}
      <DiffView diff={diff} />
      {error && <div className="alert error" role="alert">{error}</div>}
      <div className="row end">
        {conflict && <button type="button" className="btn" onClick={onReload}>Recargar y descartar mis cambios</button>}
        <button type="button" className="btn" onClick={onClose}>Cancelar</button>
        <button type="button" className="btn primary" disabled={busy || diff?.empty} onClick={confirm}>
          {busy ? 'Guardando…' : conflict ? 'Guardar sobre la versión nueva' : 'Confirmar y guardar'}
        </button>
      </div>
    </Modal>
  );
}
