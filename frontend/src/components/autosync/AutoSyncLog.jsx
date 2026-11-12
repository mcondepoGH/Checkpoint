import React, { useCallback, useEffect, useId, useState } from 'react';
import EmptyState from '#src/components/ui/EmptyState.jsx';
import { fmtDateTime, fmtDuration, RESULT_CLASS, resultText } from '#src/lib/format.js';
import { errText, useI18n } from '#src/hooks/useI18n.js';
import { recordText } from '#src/lib/errors.js';
import { FOLD_AFTER, MSG_ICON, countSummary, detailModel, isHookNote, originOf } from './runLog.js';
import { Alert, Badge, Button, Pill } from '#src/components/ui/index.js';
import Icon from '#src/components/ui/Icon.jsx';
import { schedulerHistory } from '#src/lib/api/sync.js';

// Reexportados: la lógica pura vive en runLog.js
export { FOLD_AFTER, countSummary, isHookNote };

// Mensaje de un registro (entrada o juego) ya traducido. Todo lo que no es `ok` lleva icono además del texto (nunca solo color).
function Msg({ result, text, className = '' }) {
  if (!text) return null;
  const icon = MSG_ICON[result] || null;
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
// - El mensaje de la entrada solo sale si ningún juego lo dice ya: el resumen de una entrada con code
//   (`err.scheduler.summary`: «Juego: motivo») es el mismo motivo que el de su juego, con el nombre delante.
// - Más de FOLD_AFTER juegos: botón-resumen («N juegos: 12 correctos, 1 error», aria-expanded) que despliega los `ok`;
//   los omitidos, con error, abortados, etc. se ven siempre. Hasta FOLD_AFTER, todo visible.
export function EntryDetail({ entry: e }) {
  const { t } = useI18n();
  const listId = useId();
  const [open, setOpen] = useState(false);
  const { games, entryText, showEntryMsg, labelled, fold, rows } = detailModel(e, t, open);
  const dev = e.device ? <span className="dev">{e.device}</span> : null;
  return (
    <div className="detail">
      {showEntryMsg && <Msg result={e.result} text={entryText} className={isHookNote(e) ? 'hook-note' : ''} />}
      {games.length === 0 && !showEntryMsg && <p className="muted">{t('autolog.noDetail')}</p>}
      {fold && (
        <button type="button" className="fold" aria-expanded={open} aria-controls={listId} onClick={() => setOpen(!open)}>
          <Icon name="chevron" />
          <span>
            {t('autolog.games', { n: games.length })}: {countSummary(games, t)}
          </span>
        </button>
      )}
      {rows.length > 0 && (
        <ul className="games" id={listId}>
          {rows.map(({ g, d, text }) => (
            <li key={g}>
              <div className="game-line">
                <b className="game">{d.name || g}</b>
                {dev}
                {labelled && <Badge status={RESULT_CLASS[d.result]}>{resultText(d.result, t)}</Badge>}
              </div>
              <Msg result={d.result} text={text} className={isHookNote(d) ? 'hook-note' : ''} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// Una entrada del registro: elemento de lista con cabecera en rejilla (fecha, tipo, duración y estado, una sola vez) y detalle.
// Duración vacía o 0 (avisos que no ejecutaron nada) se muestra «—».
export function RunEntry({ entry: e }) {
  const { t, locale } = useI18n();
  const origin = originOf(e.trigger);
  const trig = origin ? <Pill tone={origin}>{t(`autolog.origin.${origin}`)}</Pill> : e.trigger || '—'; // desconocido: tal cual
  return (
    <li className="run">
      <div className="run-head">
        <span className="when">{fmtDateTime(e.started, locale)}</span>
        <span className="trig">{trig}</span>
        <span className="dur">{e.duration > 0 ? fmtDuration(e.duration, locale) : '—'}</span>
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
      const d = await schedulerHistory(200);
      setEntries(d.entries || []);
      setErr(null);
    } catch (e) {
      setErr(e);
    } finally {
      setLoading(false);
    }
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
      <div role="status" aria-live="polite">
        {err && (
          <Alert as="span" variant="error" inline>
            {errText(err)}
          </Alert>
        )}
      </div>
      {entries && entries.length === 0 && !err && <EmptyState icon="📜" title={t('autolog.none.title')} text={t('autolog.none.text')} />}
      {entries && entries.length > 0 && (
        <ul className="runlog" aria-label={t('autolog.listAria')}>
          {entries.map((e) => (
            <RunEntry key={e.id} entry={e} />
          ))}
        </ul>
      )}
    </section>
  );
}
