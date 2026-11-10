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

// Mensaje de una entrada (traducido). Las de «no hubo checkpoint» (isHookNote) llevan icono además del texto.
export function EntryMessage({ entry: e }) {
  const { t } = useI18n();
  const text = recordText(e, t);
  if (!text) return null;
  const note = isHookNote(e);
  return (
    <p className={`msg ${e.result === 'error' ? 'is-error' : ''}${note ? ' hook-note' : ''}`}>
      {note && <Icon name={e.result === 'error' ? 'alert' : 'skip'} />}
      <span>{text}</span>
    </p>
  );
}

// Registro de ejecuciones automáticas (endpoint /api/scheduler/history). Refresca cada 30 s.
export default function AutoSyncLog() {
  const { t, locale } = useI18n();
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
          {entries.map((e) => (
            <li key={e.id}>
              <details>
                <summary>
                  <span className="when">{fmtDateTime(e.started, locale)}</span>
                  <span className="trig">{TRIGGERS.includes(e.trigger) ? t(`autolog.trigger.${e.trigger}`) : e.trigger}</span>
                  <span className="dur">{fmtDuration(e.duration, locale)}</span>
                  <Badge status={RESULT_CLASS[e.result]}>{resultText(e.result, t)}</Badge>
                </summary>
                <div className="detail">
                  <EntryMessage entry={e} />
                  {Object.keys(e.games || {}).length === 0 ? <p className="muted">{t('autolog.noDetail')}</p> : (
                    <ul className="games">
                      {Object.entries(e.games).map(([g, d]) => (
                        <li key={g}>
                          <b>{d.name || g}</b>
                          <Badge status={RESULT_CLASS[d.result]}>{resultText(d.result, t)}</Badge>
                          {recordText(d, t) && <small className="muted">{recordText(d, t)}</small>}
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
