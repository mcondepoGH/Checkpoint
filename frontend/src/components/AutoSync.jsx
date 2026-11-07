import React, { useCallback, useEffect, useState } from 'react';
import { api } from '../api.js';
import Field from './Field.jsx';
import AutoSyncLog from './AutoSyncLog.jsx';

const PRESETS = [1, 6, 12, 24];
const STATUS = { ok: 'ok', error: 'error', aborted: 'aborted', skipped: 'aborted', conflict: 'conflict', partial: 'aborted' };
const STATUS_TXT = { ok: 'correcta', error: 'con errores', aborted: 'abortada', skipped: 'omitida (ya en curso)', conflict: 'con conflictos', partial: 'parcial' };
const ON_CONFLICT_HELP = {
  skip: 'Omitir: el guardado no se efectúa y el juego queda marcado como «Conflicto» para resolverlo a mano. Es la opción segura.',
  newest: 'Gana el más reciente: se aplica el save con fecha más nueva y el otro se guarda en versiones. Si las fechas difieren menos de 2 s, se omite.',
};

const fmt = (iso) => (iso ? new Date(iso).toLocaleString() : '—');

// Tarjeta "Sincronización automática": ejecuta todos los juegos cada X horas. Se guarda por separado
// del config.yaml (endpoint /api/scheduler).
export default function AutoSync() {
  const [saved, setSaved] = useState(null);
  const [enabled, setEnabled] = useState(false);
  const [hours, setHours] = useState('24');
  const [runOnStart, setRunOnStart] = useState(false);
  const [onConflict, setOnConflict] = useState('skip');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null); // {kind:'ok'|'error', text}
  const [serverErr, setServerErr] = useState('');

  const apply = (s) => {
    setSaved(s);
    setEnabled(s.enabled);
    setHours(String(s.interval_hours));
    setRunOnStart(s.run_on_start);
    setOnConflict(s.on_conflict || 'skip');
  };

  const load = useCallback(async () => {
    try { apply(await api('/api/scheduler')); } catch (e) { setMsg({ kind: 'error', text: e.message }); }
  }, []);
  useEffect(() => { load(); }, [load]);

  // Refresca estado (última/próxima ejecución) sin pisar lo que se esté editando.
  useEffect(() => {
    const t = setInterval(async () => {
      try { setSaved(await api('/api/scheduler')); } catch { /* sin red: se reintenta */ }
    }, 30000);
    return () => clearInterval(t);
  }, []);

  const min = saved?.min_hours ?? 0.25;
  const max = saved?.max_hours ?? 168;
  const num = Number(hours);
  const localErr = hours.trim() === '' || !Number.isFinite(num) || num < min || num > max
    ? `Introduce un número entre ${min} y ${max} horas.` : '';
  const dirty = saved && (enabled !== saved.enabled || num !== saved.interval_hours || runOnStart !== saved.run_on_start || onConflict !== (saved.on_conflict || 'skip'));

  const save = async () => {
    setBusy(true); setMsg(null); setServerErr('');
    try {
      apply(await api('/api/scheduler', { method: 'PUT', body: { enabled, interval_hours: num, run_on_start: runOnStart, on_conflict: onConflict } }));
      setMsg({ kind: 'ok', text: 'Guardado.' });
    } catch (e) {
      setServerErr(e.data?.errors?.interval_hours || e.data?.errors?.on_conflict || '');
      setMsg({ kind: 'error', text: e.message });
    } finally { setBusy(false); }
  };

  const ls = saved?.last_status;
  return (
    <>
    <section className="card autosync" aria-labelledby="autosync-title">
      <div className="row between">
        <h3 id="autosync-title">Sincronización automática</h3>
        {saved && (
          <span className={`badge ${saved.running ? 'running' : saved.enabled ? 'ok' : ''}`}>
            {saved.running ? 'Ejecutando' : saved.enabled ? 'Activa' : 'Desactivada'}
          </span>
        )}
      </div>
      <p className="muted">Sincroniza todos los juegos cada cierto tiempo. Si ya hay una sincronización en curso, ese ciclo se omite.</p>

      <label className="switch">
        <input type="checkbox" role="switch" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
        <span className="track" aria-hidden="true"><i /></span>
        <span>{enabled ? 'Activada' : 'Desactivada'}</span>
      </label>

      <div className="autosync-grid">
        <Field label="Cada X horas" error={localErr || serverErr} hint={`Entre ${min} y ${max} (admite decimales, p. ej. 0.5).`}>
          {(p) => (
            <input {...p} type="number" inputMode="decimal" min={min} max={max} step="any" value={hours}
              onChange={(e) => setHours(e.target.value)} />
          )}
        </Field>
        <div className="presets" role="group" aria-label="Intervalos rápidos">
          {PRESETS.map((h) => (
            <button key={h} type="button" className="btn preset" aria-pressed={num === h} onClick={() => setHours(String(h))}>{h} h</button>
          ))}
        </div>
      </div>

      <label className="check">
        <input type="checkbox" checked={runOnStart} onChange={(e) => setRunOnStart(e.target.checked)} />
        Ejecutar también al arrancar la aplicación
      </label>

      <Field label="En caso de conflicto" hint={ON_CONFLICT_HELP[onConflict]}>
        {(p) => (
          <select {...p} value={onConflict} onChange={(e) => setOnConflict(e.target.value)}>
            <option value="skip">Omitir el guardado (seguro)</option>
            <option value="newest">Gana el más reciente</option>
          </select>
        )}
      </Field>
      <p className="muted">Hay conflicto cuando los dos dispositivos han cambiado desde la última sincronización y su contenido es distinto. Cada juego puede sustituir este ajuste en Configuración. En la sincronización manual siempre se pregunta.</p>

      <div className="row">
        <button type="button" className="btn primary" disabled={busy || !dirty || !!localErr} onClick={save}>Guardar</button>
        <div role="status" aria-live="polite">{msg && <span className={`alert ${msg.kind} inline`}>{msg.text}</span>}</div>
      </div>

      {saved && (
        <p className="autosync-status" aria-live="polite">
          Última ejecución: {fmt(saved.last_run)}
          {ls && <> <span className={`badge ${STATUS[ls.result] || ''}`}>{STATUS_TXT[ls.result] || ls.result}</span></>}
          {' · '}Próxima: {saved.enabled ? fmt(saved.next_run) : 'desactivada'}
          {ls?.message && <small className="muted block">{ls.message}</small>}
        </p>
      )}
    </section>
    <AutoSyncLog />
    </>
  );
}
