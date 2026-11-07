import React, { useState } from 'react';
import { api } from '../api.js';
import { updateSummary } from '../updates.js';

// Tarjeta de Configuración: activar/desactivar la comprobación de versiones nuevas y forzarla a mano.
export default function UpdateCheck({ info, onInfo }) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');
  const enabled = info ? info.habilitado !== false : true;

  const toggle = async (value) => {
    setBusy(true); setMsg('');
    try { onInfo(await api('/api/updates', { method: 'PUT', body: { enabled: value } })); }
    catch (e) { setMsg(e.message); } finally { setBusy(false); }
  };
  const refresh = async () => {
    setBusy(true); setMsg('');
    try {
      const r = await api('/api/updates?refresh=true');
      onInfo(r);
      if (r.limitado) setMsg('Acabas de comprobarlo; espera un minuto para volver a hacerlo.');
    } catch (e) { setMsg(e.message); } finally { setBusy(false); }
  };

  return (
    <section className="card" aria-labelledby="updates-title">
      <h3 id="updates-title">Comprobar actualizaciones</h3>
      <p className="muted">Consulta las versiones publicadas en GitHub (solo lectura, cada pocas horas) y avisa si hay una nueva. No instala nada.</p>
      <label className="switch">
        <input type="checkbox" role="switch" checked={enabled} disabled={busy} onChange={(e) => toggle(e.target.checked)} />
        <span className="track" aria-hidden="true"><i /></span>
        <span>{enabled ? 'Activada' : 'Desactivada'}</span>
      </label>
      {info && <p className="muted" role="status">{updateSummary(info)}</p>}
      <div className="row">
        <button className="btn ghost" onClick={refresh} disabled={busy || !enabled}>Comprobar ahora</button>
      </div>
      <div role="status" aria-live="polite">{msg && <div className="alert error">{msg}</div>}</div>
    </section>
  );
}
