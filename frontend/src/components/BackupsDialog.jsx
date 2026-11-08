import React, { useEffect, useState } from 'react';
import { api, ApiError } from '../api.js';
import EmptyState from './EmptyState.jsx';
import Modal from './Modal.jsx';
import DiffView from './DiffView.jsx';
import { errText } from '../useI18n.js';

const when = (iso) => iso.replace('T', ' ');
const kb = (n) => `${Math.max(1, Math.round(n / 1024))} KB`;

export default function BackupsDialog({ baseVersion, dirty, onRestored, onClose }) {
  const [list, setList] = useState(null);
  const [pick, setPick] = useState(null); // {name, diff}
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => { api('/api/config/backups').then(setList).catch((e) => setError(errText(e))); }, []);

  const preview = async (name) => {
    setError('');
    try { setPick({ name, diff: (await api('/api/config/diff', { method: 'POST', body: { backup: name } })).diff }); }
    catch (e) { setError(errText(e)); }
  };

  const restore = async () => {
    setBusy(true);
    setError('');
    try { onRestored(await api('/api/config/restore', { method: 'POST', body: { name: pick.name, base_version: baseVersion } })); }
    catch (e) {
      setError(e instanceof ApiError && e.status === 409
        ? 'config.yaml cambió por fuera mientras tanto: cierra, recarga y vuelve a intentarlo.' : errText(e));
    } finally { setBusy(false); }
  };

  return (
    <Modal title="Restaurar versión anterior" onClose={onClose} wide>
      {error && <div className="alert error" role="alert">{error}</div>}
      {!pick && (
        <>
          {list === null && !error && <p className="muted">Cargando…</p>}
          {list?.length === 0 && (
            <EmptyState variant="inline" icon="🗂️" title="Sin copias"
              text="Se crea una copia cada vez que guardas (máximo 10)." />
          )}
          <ul className="backups">
            {list?.map((b) => (
              <li key={b.name} className="row between">
                <span><code>{when(b.created)}</code> <span className="muted">· {kb(b.size)}</span></span>
                <button type="button" className="btn" onClick={() => preview(b.name)}>Ver cambios</button>
              </li>
            ))}
          </ul>
        </>
      )}
      {pick && (
        <>
          <p>Al restaurar <code>{when(pick.name.replace('config.yaml.bak-', '').replace('_', 'T').replace(/(\d\d)(\d\d)(\d\d)$/, '$1:$2:$3'))}</code> el config.yaml actual
            cambiaría así (el actual queda también en las copias):</p>
          {dirty && <div className="alert">Tienes cambios sin guardar en el borrador: se descartarán.</div>}
          <DiffView diff={pick.diff} />
          <div className="row end">
            <button type="button" className="btn" onClick={() => setPick(null)}>Volver</button>
            <button type="button" className="btn primary" disabled={busy} onClick={restore}>{busy ? 'Restaurando…' : 'Restaurar'}</button>
          </div>
        </>
      )}
      {!pick && <div className="row end"><button type="button" className="btn" onClick={onClose}>Cerrar</button></div>}
    </Modal>
  );
}
