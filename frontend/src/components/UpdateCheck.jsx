import React, { useState } from 'react';
import { api } from '../api.js';
import { updatesApplicable, updateSummary, channelOf, CHANNEL_OPTIONS, CHANNEL_HELP } from '../updates.js';
import { errText } from '../useI18n.js';

// Tarjeta de Configuración: activar/desactivar la comprobación de versiones nuevas y forzarla a mano.
export default function UpdateCheck({ info, onInfo }) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');
  if (info && !updatesApplicable(info)) return null; // Docker sin forzar: ni tarjeta ni selector de canal
  const enabled = info ? info.habilitado !== false : true;

  // Ejecuta una acción con el indicador de trabajo y muestra su error, si lo hay.
  const act = async (fn) => {
    setBusy(true); setMsg('');
    try { await fn(); } catch (e) { setMsg(errText(e)); } finally { setBusy(false); }
  };
  const put = (body) => act(async () => onInfo(await api('/api/updates', { method: 'PUT', body })));
  const toggle = (value) => put({ enabled: value });
  const setChannel = (value) => put({ channel: value });
  const refresh = () => act(async () => {
    const r = await api('/api/updates?refresh=true');
    onInfo(r);
    if (r.limitado) setMsg('Acabas de comprobarlo; espera un minuto para volver a hacerlo.');
  });

  return (
    <section className="card" aria-labelledby="updates-title">
      <h3 id="updates-title">Comprobar actualizaciones</h3>
      <p className="muted">Consulta las versiones publicadas en GitHub (solo lectura, cada pocas horas) y avisa si hay una nueva. No instala nada.</p>
      <label className="switch">
        <input type="checkbox" role="switch" checked={enabled} disabled={busy} onChange={(e) => toggle(e.target.checked)} />
        <span className="track" aria-hidden="true"><i /></span>
        <span>{enabled ? 'Activada' : 'Desactivada'}</span>
      </label>
      <div className="update-channel">
        <label htmlFor="update-channel">Canal</label>
        <select id="update-channel" value={channelOf(info)} disabled={busy || !enabled} onChange={(e) => setChannel(e.target.value)}
          aria-describedby="update-channel-help">
          {CHANNEL_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
      </div>
      <p id="update-channel-help" className="muted">{CHANNEL_HELP}</p>
      {info && <p className="muted" role="status">{updateSummary(info)}</p>}
      <div className="row">
        <button className="btn ghost" onClick={refresh} disabled={busy || !enabled}>Comprobar ahora</button>
      </div>
      <div role="status" aria-live="polite">{msg && <div className="alert error">{msg}</div>}</div>
    </section>
  );
}
