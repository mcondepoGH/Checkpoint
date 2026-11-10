import React, { useEffect, useRef, useState } from 'react';
import { api } from '../api.js';
import EmptyState from '../components/EmptyState.jsx';
import { labelOf } from '../names.js';
import { parseRun } from '../format.js';
import ConflictDialog from '../components/ConflictDialog.jsx';
import { errText, useI18n } from '../useI18n.js';
import Icon from '../components/Icon.jsx';
import { clock, groupByGame, watchHealth } from '../watch.js';
import { Alert, Badge, Button, Checkbox, Pill, WatchStatus } from '../components/ui/index.js';

const WATCH_POLL_MS = 5000; // el backend no emite eventos de vigilancia: se consulta /api/watches (los SSE existentes son de config y de ejecuciones)

// Estados con texto propio en el distintivo: clave `sync.state.<resultado>`; otro resultado se muestra tal cual.
const RES_KEYS = ['conflict', 'partial', 'dry-run'];

// Fecha ISO -> {time, date}; null si no se puede interpretar.
function splitWhen(iso, locale) {
  const d = iso ? new Date(iso) : null;
  if (!d || Number.isNaN(d.getTime())) return null;
  return {
    time: d.toLocaleTimeString(locale, { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
    date: d.toLocaleDateString(locale, { day: 'numeric', month: 'short', year: 'numeric' }),
  };
}

function LastRun({ s, devName }) {
  const { t, locale } = useI18n();
  if (!s) return <EmptyState variant="inline" icon="⏳" title={t('sync.none.title')} text={t('sync.none.text')} />;
  const when = splitWhen(s.finished, locale);
  const parsed = parseRun(s);
  // winner/targets/offline del estado son ids de dispositivo (los mensajes ya llevan nombres)
  const winner = parsed.winner && devName(parsed.winner);
  const list = parsed.list.map(devName);
  const { planned, structured } = parsed;
  return (
    <dl className="lastrun">
      <div className="lr-row">
        <dt>{t('sync.last')}</dt>
        <dd>{when ? <><strong className="lr-time">{when.time}</strong><span className="lr-date">{when.date}</span></>
                  : <span>{s.finished?.replace('T', ' ') || '—'}</span>}
          {s.dry_run && <span className="lr-tag">{t('common.dryRun')}</span>}</dd>
      </div>
      {s.result === 'conflict' && <div className="lr-row"><dt>{t('sync.conflict')}</dt><dd className="lr-msg">{errText(s)}</dd></div>}
      {s.result === 'partial' && <div className="lr-row"><dt>{t('sync.partial')}</dt><dd className="lr-msg">{errText(s)}</dd></div>}
      {s.offline?.length > 0 && <div className="lr-row"><dt>{t('sync.offline')}</dt><dd className="pills">{s.offline.map((d) => <Pill key={d}>{devName(d)}</Pill>)}</dd></div>}
      {winner && <div className="lr-row"><dt>{t('sync.winner')}</dt><dd><Pill highlight>{winner}</Pill></dd></div>}
      {list.length > 0 && (
        <div className="lr-row"><dt>{planned ? t('sync.targets') : t('sync.updated')}</dt>
          <dd className="pills">{list.map((d) => <Pill key={d}>{d}</Pill>)}</dd></div>
      )}
      {!structured && (s.code || s.message) && <div className="lr-row"><dt>{t('sync.detail')}</dt><dd className="lr-msg">{errText(s)}</dd></div>}
    </dl>
  );
}

export default function Sync({ config, onGoSettings }) {
  const { t, locale } = useI18n(); // re-renderiza al cambiar de idioma
  // Las claves de config.games/status son ids internos; en pantalla siempre el nombre.
  const games = Object.keys(config.games);
  const devName = (id) => labelOf(config.devices, id);
  const gameName = (id) => labelOf(config.games, id);
  const [dry, setDry] = useState({});
  const [status, setStatus] = useState({});
  const [active, setActive] = useState(null); // {game, lines, done}
  const [error, setError] = useState(null); // error de la API (se traduce al pintar)
  const [conflict, setConflict] = useState(null); // {game, conflict}
  const [resolving, setResolving] = useState(false);
  const [watch, setWatch] = useState({ now: null, watches: [] });
  const [watchOpen, setWatchOpen] = useState(false);
  const esRef = useRef(null);
  const logRef = useRef(null);

  const loadStatus = () => api('/api/status').then(setStatus).catch(() => {});
  useEffect(() => { loadStatus(); return () => esRef.current?.close(); }, []);
  useEffect(() => {
    let alive = true;
    const load = () => {
      if (typeof document !== 'undefined' && document.hidden) return;
      api('/api/watches').then((r) => alive && setWatch({ now: r.now, watches: r.watches || [] })).catch(() => {});
    };
    load();
    const timer = setInterval(load, WATCH_POLL_MS);
    return () => { alive = false; clearInterval(timer); };
  }, []);
  useEffect(() => { if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight; }, [active?.lines.length]);

  // resolution/expect: solo al resolver un conflicto desde el popup.
  const run = async (game, resolution, expect) => {
    setError(null);
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
    } catch (e) { setError(e); }
  };

  const byGame = groupByGame(watch.watches);
  const watched = games.filter((g) => byGame[g]);
  // Una línea de vigilancia: punto + «Vigilando · dispositivo · desde HH:MM» + estado (texto, no solo color).
  const watchLine = (w) => {
    const h = watchHealth(w, watch.now);
    return (
      <WatchStatus key={`${w.game}|${w.device}`} state={h}>
        <span>{t('sync.watch.line', { device: devName(w.device), time: clock(w.since, locale) })} · {t(`sync.watch.state.${h}`)}</span>
      </WatchStatus>
    );
  };
  const badge = (s) => s && <Badge status={s.result}>{RES_KEYS.includes(s.result) ? t(`sync.state.${s.result}`) : s.result}</Badge>;
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
      <h2>{t('sync.title')}</h2>
      {error && <Alert variant="error">{errText(error)}</Alert>}
      {watched.length > 0 && (
        <div className="watch-summary">
          <button type="button" className="watch-toggle" aria-expanded={watchOpen} aria-controls="watch-list" onClick={() => setWatchOpen((o) => !o)}>
            <Icon name="eye" />{t('sync.watch.count', { count: watched.length })}
          </button>
          {watchOpen && (
            <ul id="watch-list" className="watch-list" aria-label={t('sync.watch.listAria')}>
              {watched.map((g) => byGame[g].map((w) => <li key={`${g}|${w.device}`}><b>{gameName(g)}</b> {watchLine(w)}</li>))}
            </ul>
          )}
        </div>
      )}
      {games.length === 0 && (
        <EmptyState variant="page" icon="🎮" title={t('sync.noGames.title')}
          text={t('sync.noGames.text')}
          action={onGoSettings && <Button variant="primary" onClick={onGoSettings}>{t('common.goSettings')}</Button>} />
      )}
      <div className="grid">
        {games.map((g) => {
          const s = status[g];
          const running = active && active.game === g && !active.done;
          return (
            <div className="card" key={g}>
              <h3 title={t('sync.idTitle', { id: g })}>{gameName(g)} {running ? <Badge status="running">{t('sync.state.running')}</Badge> : badge(s)}</h3>
              <p className="muted">{config.games[g].devices.map(devName).join(' ⇄ ')}</p>
              {byGame[g]?.map(watchLine)}
              <div className={`meter ${running ? 'running' : (s?.result || '')}`} role="progressbar" aria-label={t('sync.meterAria', { game: gameName(g) })}><i /></div>
              <LastRun s={s} devName={devName} />
              <Checkbox checked={!!dry[g]} onChange={(e) => setDry({ ...dry, [g]: e.target.checked })} label={t('common.dryRun')} />
              {s?.result === 'conflict' && !running && (
                <div className="conflict-flag" role="alert">
                  <span><b>{t('sync.flagLead')}</b> {t('sync.flagText')}</span>
                  <Button onClick={() => openConflict(g)}>{t('sync.resolve')}</Button>
                </div>
              )}
              <Button variant="primary" disabled={running} onClick={() => run(g)}>{running ? t('sync.running') : t('sync.run')}</Button>
            </div>
          );
        })}
      </div>
      {conflict && (
        <ConflictDialog game={gameName(conflict.game)} conflict={conflict.conflict} busy={resolving}
          onCancel={() => setConflict(null)} onResolve={resolve} />
      )}
      {active && (
        <div className="card logcard">
          <h3>{t('sync.log.title', { game: gameName(active.game), state: active.done ? t('sync.log.done') : t('sync.log.live') })}</h3>
          <pre className="log" ref={logRef}>{active.lines.join('\n') || t('sync.log.waiting')}</pre>
        </div>
      )}
    </section>
  );
}
