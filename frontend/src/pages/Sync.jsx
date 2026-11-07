import React, { useEffect, useRef, useState } from 'react';
import { api } from '../api.js';
import EmptyState from '../components/EmptyState.jsx';

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
  const esRef = useRef(null);
  const logRef = useRef(null);

  const loadStatus = () => api('/api/status').then(setStatus).catch(() => {});
  useEffect(() => { loadStatus(); return () => esRef.current?.close(); }, []);
  useEffect(() => { if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight; }, [active?.lines.length]);

  const run = async (game) => {
    setError('');
    try {
      const { run_id } = await api(`/api/sync/${encodeURIComponent(game)}`, { method: 'POST', body: { dry_run: !!dry[game] } });
      setActive({ game, lines: [], done: false });
      esRef.current?.close();
      const es = new EventSource(`/api/runs/${run_id}/stream`);
      esRef.current = es;
      es.onmessage = (ev) => setActive((a) => ({ ...a, lines: [...a.lines, JSON.parse(ev.data)] }));
      es.addEventListener('done', () => { es.close(); setActive((a) => ({ ...a, done: true })); loadStatus(); });
      es.onerror = () => { es.close(); setActive((a) => a && { ...a, done: true }); loadStatus(); };
    } catch (e) { setError(e.message); }
  };

  const badge = (s) => s && <span className={`badge ${s.result}`}>{s.result}</span>;

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
              <button className="btn primary" disabled={running} onClick={() => run(g)}>{running ? 'En curso…' : 'Sincronizar'}</button>
            </div>
          );
        })}
      </div>
      {active && (
        <div className="card logcard">
          <h3>Log: {active.game} {active.done ? '(terminado)' : '(en vivo)'}</h3>
          <pre className="log" ref={logRef}>{active.lines.join('\n') || 'Esperando…'}</pre>
        </div>
      )}
    </section>
  );
}
