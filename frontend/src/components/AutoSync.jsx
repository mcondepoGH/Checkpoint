import React, { useCallback, useEffect, useState } from 'react';
import { api } from '#src/lib/api.js';
import Field from './Field.jsx';
import AutoSyncLog from './AutoSyncLog.jsx';
import { fmtDateTime, ON_CONFLICT_OPTIONS } from '#src/lib/format.js';
import { errText, useI18n } from '#src/useI18n.js';
import { ui } from '#src/lib/errors.js';
import { Alert, Badge, Button, Checkbox, Input, Select, Switch } from '#src/components/ui/index.js';

const PRESETS = [1, 6, 12, 24];
const ON_CONFLICT_HELP = { skip: 'autosync.help.skip', newest: 'autosync.help.newest' }; // claves del catálogo

// Tarjeta "Sincronización automática": ejecuta todos los juegos cada X horas. Se guarda por separado
// del config.yaml (endpoint /api/scheduler).
export default function AutoSync() {
  const { t, locale } = useI18n();
  const [saved, setSaved] = useState(null);
  const [enabled, setEnabled] = useState(false);
  const [hours, setHours] = useState('24');
  const [runOnStart, setRunOnStart] = useState(false);
  const [onConflict, setOnConflict] = useState('skip');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null); // {kind:'ok'|'error', body}: `body` es un error o mensaje {code} (se traduce al pintar)
  const [serverErr, setServerErr] = useState(''); // {code, params} o texto antiguo: Field lo traduce

  const apply = (s) => {
    setSaved(s);
    setEnabled(s.enabled);
    setHours(String(s.interval_hours));
    setRunOnStart(s.run_on_start);
    setOnConflict(s.on_conflict || 'skip');
  };

  const load = useCallback(async () => {
    try { apply(await api('/api/scheduler')); } catch (e) { setMsg({ kind: 'error', body: e }); }
  }, []);
  useEffect(() => { load(); }, [load]);

  // Refresca estado (próxima ejecución) sin pisar lo que se esté editando.
  useEffect(() => {
    const timer = setInterval(async () => {
      try { setSaved(await api('/api/scheduler')); } catch { /* sin red: se reintenta */ }
    }, 30000);
    return () => clearInterval(timer);
  }, []);

  const min = saved?.min_hours ?? 0.25;
  const max = saved?.max_hours ?? 168;
  const num = Number(hours);
  const localErr = hours.trim() === '' || !Number.isFinite(num) || num < min || num > max
    ? ui('autosync.range', { min, max }) : '';
  const dirty = saved && (enabled !== saved.enabled || num !== saved.interval_hours || runOnStart !== saved.run_on_start || onConflict !== (saved.on_conflict || 'skip'));

  const save = async () => {
    setBusy(true); setMsg(null); setServerErr('');
    try {
      apply(await api('/api/scheduler', { method: 'PUT', body: { enabled, interval_hours: num, run_on_start: runOnStart, on_conflict: onConflict } }));
      setMsg({ kind: 'ok', body: ui('autosync.saved') });
    } catch (e) {
      setServerErr(e.data?.errors?.interval_hours || e.data?.errors?.on_conflict || ''); // {code, params} o texto: Field lo traduce
      setMsg({ kind: 'error', body: e });
    } finally { setBusy(false); }
  };

  return (
    <>
    <section className="card autosync" aria-labelledby="autosync-title">
      <div className="row between">
        <h3 id="autosync-title">{t('autosync.title')}</h3>
        {saved && (
          <Badge status={saved.running ? 'running' : saved.enabled ? 'ok' : ''}>
            {saved.running ? t('autosync.running') : saved.enabled ? t('autosync.active') : t('autosync.disabled')}
          </Badge>
        )}
      </div>
      <p className="muted">{t('autosync.intro')}</p>

      <Switch checked={enabled} onChange={(e) => setEnabled(e.target.checked)} label={enabled ? t('common.on') : t('common.off')} />

      <div className="autosync-grid">
        <Field label={t('autosync.hours')} error={localErr || serverErr} hint={t('autosync.hoursHint', { min, max })}>
          {(p) => (
            <Input {...p} type="number" inputMode="decimal" min={min} max={max} step="any" value={hours}
              onChange={(e) => setHours(e.target.value)} />
          )}
        </Field>
        <div className="presets" role="group" aria-label={t('autosync.presets')}>
          {PRESETS.map((h) => (
            <Button className="preset" key={h} aria-pressed={num === h} onClick={() => setHours(String(h))}>{t('autosync.hoursShort', { count: h })}</Button>
          ))}
        </div>
      </div>

      <Checkbox checked={runOnStart} onChange={(e) => setRunOnStart(e.target.checked)} label={t('autosync.runOnStart')} />

      <Field label={t('autosync.onConflict')} hint={ON_CONFLICT_HELP[onConflict] && t(ON_CONFLICT_HELP[onConflict])}>
        {(p) => (
          <Select {...p} value={onConflict} onChange={(e) => setOnConflict(e.target.value)}
            options={ON_CONFLICT_OPTIONS.map(([v, l]) => ({ value: v, label: t(l) }))} />
        )}
      </Field>

      <div className="row">
        <Button variant="primary" disabled={busy || !dirty || !!localErr} onClick={save}>{t('common.save')}</Button>
        <div role="status" aria-live="polite">{msg && <Alert as="span" variant={msg.kind} inline>{errText(msg.body)}</Alert>}</div>
      </div>

      {saved && (
        <p className="autosync-status" aria-live="polite">
          {t('autosync.nextRun')} {saved.enabled ? fmtDateTime(saved.next_run, locale) : t('autosync.nextOff')}
        </p>
      )}
    </section>
    <AutoSyncLog />
    </>
  );
}
