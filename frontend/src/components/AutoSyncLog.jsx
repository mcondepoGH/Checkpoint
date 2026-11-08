import React, { useCallback, useEffect, useState } from 'react';
import { api } from '../api.js';
import EmptyState from './EmptyState.jsx';
import { fmtDateTime, RESULT_CLASS, RESULT_TEXT } from '../format.js';
import { errText } from '../useI18n.js';

const TRIG_TXT = { scheduled: 'Programada', startup: 'Arranque' };

const fmtDur = (s) => {
  if (!Number.isFinite(s)) return '—';
  if (s < 60) return `${s.toFixed(s < 10 ? 1 : 0)} s`;
  const m = Math.floor(s / 60);
  return `${m} min ${Math.round(s % 60)} s`;
};

// Registro de ejecuciones automáticas (endpoint /api/scheduler/history). Refresca cada 30 s.
export default function AutoSyncLog() {
  const [entries, setEntries] = useState(null);
  const [err, setErr] = useState('');
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const d = await api('/api/scheduler/history?limit=50');
      setEntries(d.entries || []);
      setErr('');
    } catch (e) { setErr(errText(e)); } finally { setLoading(false); }
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 30000);
    return () => clearInterval(t);
  }, [load]);

  return (
    <section className="card autosync autosync-log" aria-labelledby="autosynclog-title">
      <div className="row between">
        <h3 id="autosynclog-title">Registro de ejecuciones</h3>
        <button type="button" className="btn" onClick={load} disabled={loading} aria-label="Refrescar registro">
          {loading ? 'Actualizando…' : 'Refrescar'}
        </button>
      </div>
      <div role="status" aria-live="polite">{err && <span className="alert error inline">{err}</span>}</div>
      {entries && entries.length === 0 && !err && (
        <EmptyState icon="📜" title="Sin ejecuciones"
          text="Todavía no se ha ejecutado ninguna sincronización automática. Las ejecuciones aparecerán aquí." />
      )}
      {entries && entries.length > 0 && (
        <ul className="runlog" aria-label="Ejecuciones automáticas, de más reciente a más antigua">
          {entries.map((e) => (
            <li key={e.id}>
              <details>
                <summary>
                  <span className="when">{fmtDateTime(e.started)}</span>
                  <span className="trig">{TRIG_TXT[e.trigger] || e.trigger}</span>
                  <span className="dur">{fmtDur(e.duration)}</span>
                  <span className={`badge ${RESULT_CLASS[e.result] || ''}`}>{RESULT_TEXT[e.result] || e.result}</span>
                </summary>
                <div className="detail">
                  {e.message && <p className={`msg ${e.result === 'error' ? 'is-error' : ''}`}>{e.message}</p>}
                  {Object.keys(e.games || {}).length === 0 ? <p className="muted">Sin detalle por juego.</p> : (
                    <ul className="games">
                      {Object.entries(e.games).map(([g, d]) => (
                        <li key={g}>
                          <b>{d.name || g}</b>
                          <span className={`badge ${RESULT_CLASS[d.result] || ''}`}>{RESULT_TEXT[d.result] || d.result}</span>
                          {d.message && <small className="muted">{d.message}</small>}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </details>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
