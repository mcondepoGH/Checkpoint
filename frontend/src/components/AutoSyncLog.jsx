import React, { useCallback, useEffect, useState } from 'react';
import { api } from '../api.js';
import EmptyState from './EmptyState.jsx';
import { fmtDateTime, fmtDuration, RESULT_CLASS, resultText } from '../format.js';
import { errText, useI18n } from '../useI18n.js';
import { recordText } from '../errors.js';
import { Alert, Badge, Button } from './ui/index.js';
import Icon from './Icon.jsx';

// Disparadores conocidos (ids del backend): clave `autolog.trigger.<id>`; otro se muestra tal cual.
const TRIGGERS = ['scheduled', 'startup', 'hook', 'hook_closed'];

// Entrada que explica por qué NO hubo checkpoint de cierre (códigos err.hook.*): omitida (`skipped`) o con error. Lleva icono además del texto.
export const isHookNote = (e) => typeof e?.code === 'string' && e.code.startsWith('err.hook.') && (e.result === 'skipped' || e.result === 'error');

// Mensaje de un registro (entrada o juego) ya traducido. Omitidas y con error llevan icono además del texto (nunca solo color).
function Msg({ result, text, className = '' }) {
  if (!text) return null;
  const icon = result === 'error' ? 'alert' : result === 'skipped' ? 'skip' : null;
  return (
    <p className={`msg${className ? ` ${className}` : ''}${result === 'error' ? ' is-error' : ''}${icon ? ' has-icon' : ''}`}>
      {icon && <Icon name={icon} />}
      <span>{text}</span>
    </p>
  );
}

// Mensaje de una entrada (traducido). Las omitidas y con error (y las de «no hubo checkpoint», isHookNote) llevan icono.
export function EntryMessage({ entry: e }) {
  const { t } = useI18n();
  const text = recordText(e, t);
  if (!text) return null;
  return <Msg result={e.result} text={text} className={isHookNote(e) ? 'hook-note' : ''} />;
}

// Detalle de una entrada, sin repetir nada que ya diga la cabecera ni dos veces el mismo mensaje.
// - Un juego con el mismo resultado que la cabecera: línea ligera con su nombre (y dispositivo, si existe), sin etiqueta;
//   debajo, el mensaje (solo si existe) una vez.
// - Varios juegos o resultados distintos: una fila por juego con su etiqueta (todas si hay mezcla) y su mensaje debajo.
// El mensaje de la entrada solo sale si ningún juego dice lo mismo.
export function EntryDetail({ entry: e }) {
  const { t } = useI18n();
  const games = Object.entries(e.games || {});
  const entryText = recordText(e, t);
  const gameTexts = games.map(([, d]) => recordText(d, t));
  const showEntryMsg = entryText && !gameTexts.includes(entryText);
  const results = new Set([e.result, ...games.map(([, d]) => d.result)]);
  const labelled = results.size > 1; // algún juego difiere de la cabecera (o entre sí): todas las filas llevan etiqueta
  const dev = e.device ? <span className="dev">{e.device}</span> : null;
  return (
    <div className="detail">
      {showEntryMsg && <Msg result={e.result} text={entryText} className={isHookNote(e) ? 'hook-note' : ''} />}
      {games.length === 0 && !showEntryMsg && <p className="muted">{t('autolog.noDetail')}</p>}
      {games.length > 0 && (
        <ul className="games">
          {games.map(([g, d], i) => (
            <li key={g}>
              <div className="game-line">
                <b className="game">{d.name || g}</b>
                {dev}
                {labelled && <Badge status={RESULT_CLASS[d.result]}>{resultText(d.result, t)}</Badge>}
              </div>
              <Msg result={d.result} text={gameTexts[i]} className={isHookNote(d) ? 'hook-note' : ''} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// Una entrada del registro: elemento de lista con cabecera en rejilla (fecha, tipo, duración y estado, una sola vez) y detalle.
export function RunEntry({ entry: e }) {
  const { t, locale } = useI18n();
  return (
    <li className="run">
      <div className="run-head">
        <span className="when">{fmtDateTime(e.started, locale)}</span>
        <span className="trig">{TRIGGERS.includes(e.trigger) ? t(`autolog.trigger.${e.trigger}`) : e.trigger}</span>
        <span className="dur">{fmtDuration(e.duration, locale)}</span>
        <Badge status={RESULT_CLASS[e.result]}>{resultText(e.result, t)}</Badge>
      </div>
      <EntryDetail entry={e} />
    </li>
  );
}

// Registro de ejecuciones automáticas (endpoint /api/scheduler/history). Refresca cada 30 s.
export default function AutoSyncLog() {
  const { t } = useI18n();
  const [entries, setEntries] = useState(null);
  const [err, setErr] = useState(null); // error de la API (se traduce al pintar)
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const d = await api('/api/scheduler/history?limit=50');
      setEntries(d.entries || []);
      setErr(null);
    } catch (e) { setErr(e); } finally { setLoading(false); }
  }, []);

  useEffect(() => {
    load();
    const timer = setInterval(load, 30000);
    return () => clearInterval(timer);
  }, [load]);

  return (
    <section className="card autosync autosync-log" aria-labelledby="autosynclog-title">
      <div className="row between">
        <h3 id="autosynclog-title">{t('autolog.title')}</h3>
        <Button onClick={load} disabled={loading} aria-label={t('autolog.refreshAria')}>
          {loading ? t('autolog.refreshing') : t('autolog.refresh')}
        </Button>
      </div>
      <div role="status" aria-live="polite">{err && <Alert as="span" variant="error" inline>{errText(err)}</Alert>}</div>
      {entries && entries.length === 0 && !err && (
        <EmptyState icon="📜" title={t('autolog.none.title')}
          text={t('autolog.none.text')} />
      )}
      {entries && entries.length > 0 && (
        <ul className="runlog" aria-label={t('autolog.listAria')}>
          {entries.map((e) => <RunEntry key={e.id} entry={e} />)}
        </ul>
      )}
    </section>
  );
}
