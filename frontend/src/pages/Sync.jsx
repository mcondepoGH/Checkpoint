import React, { useEffect, useRef, useState } from 'react';
import { api } from '../api.js';
import EmptyState from '../components/EmptyState.jsx';
import { labelOf } from '../names.js';
import { parseRun } from '../format.js';
import Icon from '../components/Icon.jsx';
import { isSoloCheckpoint } from '../draft.js';
import ConflictDialog from '../components/ConflictDialog.jsx';
import { errText, useI18n } from '../useI18n.js';
import { NO_WATCHES } from '../useWatches.js';
import { clock, groupByGame, watchCardClass, watchHealth, worstHealth } from '../watch.js';
import { Alert, Badge, Button, Checkbox, Pill, WatchBar } from '../components/ui/index.js';


// Estados con texto propio en el distintivo: clave `sync.state.<resultado>`; otro resultado se muestra tal cual.
const RES_KEYS = ['conflict', 'partial', 'dry-run', 'skipped'];

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

// `watch` ({now, watches}) llega de App (useWatches): la misma consulta alimenta el contador de la cabecera.
export default function Sync({ config, watch = NO_WATCHES, onGoSettings }) {
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
  const esRef = useRef(null);
  const logRef = useRef(null);

  const loadStatus = () => api('/api/status').then(setStatus).catch(() => {});
  useEffect(() => { loadStatus(); return () => esRef.current?.close(); }, []);
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
  // Franja inferior de la tarjeta: estado en texto + icono (nunca solo color); la hora solo cuando aporta (jugando, sin latido).
  const watchBar = (w) => {
    const h = watchHealth(w, watch.now);
    const since = h === 'running' || h === 'stale' ? t('sync.watch.since', { time: clock(w.since, locale) }) : null;
    return <WatchBar key={`${w.game}|${w.device}`} state={h} since={since}>{t(`sync.watch.bar.${h}`, { device: devName(w.device) })}</WatchBar>;
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
            <div className={watchCardClass(worstHealth(byGame[g], watch.now))} key={g}>
              <h3 title={t('sync.idTitle', { id: g })}><span className="game-name">{gameName(g)}</span> {running ? <Badge status="running">{t('sync.state.running')}</Badge> : badge(s)}</h3>
              <p className="muted">{config.games[g].devices.map(devName).join(' ⇄ ')}</p>
              {isSoloCheckpoint(config.games[g]) && (
                <p><Pill tone="info" title={t('sync.solo.help')}><Icon name="history" />{t('sync.solo.label')}</Pill></p>
              )}
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
              {byGame[g]?.map(watchBar)}
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
