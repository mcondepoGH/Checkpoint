import React, { useEffect, useRef, useState } from 'react';
import { api } from '../api.js';
import EmptyState from '../components/EmptyState.jsx';
import ConflictDialog from '../components/ConflictDialog.jsx';

const RES_TXT = { conflict: 'Conflicto', partial: 'Parcial' };

// Fecha ISO -> {time, date}; null si no se puede interpretar.
function splitWhen(iso) {
  const d = iso ? new Date(iso) : null;
  if (!d || Number.isNaN(d.getTime())) return null;
  return {
    time: d.toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
    date: d.toLocaleDateString('es-ES', { day: 'numeric', month: 'short', year: 'numeric' }),
  };
}

// Ganador y dispositivos: campos del estado o, si faltan, se extraen del mensaje "ganador X; actualizados A, B".
function parseRun(s) {
  const m = /^ganador\s+([^;]+?);\s*(actualizados|destinos)\s+(.+)$/.exec(s.message || '');
  const winner = s.winner || (m && m[1].trim()) || '';
  const list = Array.isArray(s.targets) && s.targets.length ? s.targets : (m ? m[3].split(',').map((x) => x.trim()).filter(Boolean) : []);
  const planned = s.dry_run || (m && m[2] === 'destinos') || s.result === 'dry-run';
  return { winner, list, planned, structured: !!(winner || list.length) };
}

function LastRun({ s }) {
  if (!s) return <EmptyState variant="inline" icon="⏳" title="Sin ejecuciones" text="Aún no se ha sincronizado este juego." />;
  const when = splitWhen(s.finished);
  const { winner, list, planned, structured } = parseRun(s);
  return (
    <dl className="lastrun">
      <div className="lr-row">
        <dt>Última sync</dt>
        <dd>{when ? <><strong className="lr-time">{when.time}</strong><span className="lr-date">{when.date}</span></>
                  : <span>{s.finished?.replace('T', ' ') || '—'}</span>}
          {s.dry_run && <span className="lr-tag">dry-run</span>}</dd>
      </div>
      {s.result === 'conflict' && <div className="lr-row"><dt>Conflicto</dt><dd className="lr-msg">{s.message}</dd></div>}
      {s.result === 'partial' && <div className="lr-row"><dt>Parcial</dt><dd className="lr-msg">{s.message}</dd></div>}
      {s.offline?.length > 0 && <div className="lr-row"><dt>Offline</dt><dd className="pills">{s.offline.map((d) => <span className="pill" key={d}>{d}</span>)}</dd></div>}
      {winner && <div className="lr-row"><dt>Ganador</dt><dd><span className="pill win">{winner}</span></dd></div>}
      {list.length > 0 && (
        <div className="lr-row"><dt>{planned ? 'Destinos' : 'Actualizados'}</dt>
          <dd className="pills">{list.map((d) => <span className="pill" key={d}>{d}</span>)}</dd></div>
      )}
      {!structured && s.message && <div className="lr-row"><dt>Detalle</dt><dd className="lr-msg">{s.message}</dd></div>}
    </dl>
  );
}

export default function Sync({ config, onGoSettings }) {
  const games = Object.keys(config.games);
  const [dry, setDry] = useState({});
  const [status, setStatus] = useState({});
  const [active, setActive] = useState(null); // {game, lines, done}
  const [error, setError] = useState('');
  const [conflict, setConflict] = useState(null); // {game, conflict}
  const [resolving, setResolving] = useState(false);
  const esRef = useRef(null);
  const logRef = useRef(null);

  const loadStatus = () => api('/api/status').then(setStatus).catch(() => {});
  useEffect(() => { loadStatus(); return () => esRef.current?.close(); }, []);
  useEffect(() => { if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight; }, [active?.lines.length]);

  // resolution/expect: solo al resolver un conflicto desde el popup.
  const run = async (game, resolution, expect) => {
    setError('');
    try {
      const body = { dry_run: !!dry[game] };
      if (resolution) { body.resolution = resolution; body.expect = expect; }
      const { run_id } = await api(`/api/sync/${encodeURIComponent(game)}`, { method: 'POST', body });
      setActive({ game, lines: [], done: false });
      esRef.current?.close();
      const es = new EventSource(`/api/runs/${run_id}/stream`);
      esRef.current = es;
      es.onmessage = (ev) => setActive((a) => ({ ...a, lines: [...a.lines, JSON.parse(ev.data)] }));
      es.addEventListener('done', (ev) => {
        es.close(); setActive((a) => ({ ...a, done: true })); loadStatus(); setResolving(false);
        try {
          const st = JSON.parse(ev.data);
          if (st?.result === 'conflict' && st.conflict) setConflict({ game, conflict: st.conflict });
          else setConflict(null);
        } catch { setConflict(null); }
      });
      es.onerror = () => { es.close(); setResolving(false); setActive((a) => a && { ...a, done: true }); loadStatus(); };
    } catch (e) { setError(e.message); }
  };

  const badge = (s) => s && <span className={`badge ${s.result}`}>{RES_TXT[s.result] || s.result}</span>;
  const openConflict = (g) => {
    const c = status[g]?.conflict;
    if (c) setConflict({ game: g, conflict: c });
  };
  const resolve = (resolution, expect) => {
    setResolving(true);
    const g = conflict.game;
    setConflict(null);
    run(g, resolution, expect);
  };

  return (
    <section className={games.length === 0 ? 'fill' : undefined}>
      <h2>Sincronizar</h2>
      {error && <div className="alert error">{error}</div>}
      {games.length === 0 && (
        <EmptyState variant="page" icon="🎮" title="Sin juegos configurados"
          text="Añade un juego en Configuración para poder sincronizar sus partidas guardadas entre dispositivos."
          action={onGoSettings && <button type="button" className="btn primary" onClick={onGoSettings}>Ir a Configuración</button>} />
      )}
      <div className="grid">
        {games.map((g) => {
          const s = status[g];
          const running = active && active.game === g && !active.done;
          return (
            <div className="card" key={g}>
              <h3>{g} {running ? <span className="badge running">en curso</span> : badge(s)}</h3>
              <p className="muted">{config.games[g].devices.join(' ⇄ ')}</p>
              <div className={`meter ${running ? 'running' : (s?.result || '')}`} role="progressbar" aria-label={`Estado de ${g}`}><i /></div>
              <LastRun s={s} />
              <label className="check"><input type="checkbox" checked={!!dry[g]} onChange={(e) => setDry({ ...dry, [g]: e.target.checked })} /> Dry-run</label>
              {s?.result === 'conflict' && !running && (
                <div className="conflict-flag" role="alert">
                  <span><b>Conflicto:</b> dos versiones distintas, no se ha guardado nada.</span>
                  <button type="button" className="btn" onClick={() => openConflict(g)}>Resolver</button>
                </div>
              )}
              <button className="btn primary" disabled={running} onClick={() => run(g)}>{running ? 'En curso…' : 'Sincronizar'}</button>
            </div>
          );
        })}
      </div>
      {conflict && (
        <ConflictDialog game={conflict.game} conflict={conflict.conflict} busy={resolving}
          onCancel={() => setConflict(null)} onResolve={resolve} />
      )}
      {active && (
        <div className="card logcard">
          <h3>Log: {active.game} {active.done ? '(terminado)' : '(en vivo)'}</h3>
          <pre className="log" ref={logRef}>{active.lines.join('\n') || 'Esperando…'}</pre>
        </div>
      )}
    </section>
  );
}
