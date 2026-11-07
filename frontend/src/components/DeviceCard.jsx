import React from 'react';
import Field from './Field.jsx';
import { NAME_HINT, NAME_MAX, OS_OPTIONS } from '../draft.js';
import IdNote from './IdNote.jsx';

export default function DeviceCard({ dev, errors, localError, test, idText, renamed, onChange, onTest, onRemove }) {
  const set = (k) => (e) => onChange({ [k]: e.target.value });
  const title = dev.name || 'Dispositivo nuevo';
  return (
    <fieldset className="card cfg-card">
      <legend className="cfg-title">{title}</legend>
      <Field label="Nombre" hint={NAME_HINT} error={localError || errors.name || errors['']}>
        {(p) => <input {...p} value={dev.name} onChange={set('name')} maxLength={NAME_MAX} placeholder="p. ej. Mi PC (salón)" autoComplete="off" spellCheck="false" />}
      </Field>
      <div className="two">
        <Field label="Host / IP" error={errors.host}>
          {(p) => <input {...p} value={dev.host} onChange={set('host')} autoComplete="off" spellCheck="false" />}
        </Field>
        <Field label="Puerto" error={errors.port}>
          {(p) => <input {...p} type="number" inputMode="numeric" min="1" max="65535" value={dev.port} onChange={set('port')} />}
        </Field>
      </div>
      <div className="two">
        <Field label="Usuario" error={errors.user}>
          {(p) => <input {...p} value={dev.user} onChange={set('user')} autoComplete="off" spellCheck="false" />}
        </Field>
        <Field label="Sistema operativo" error={errors.os}>
          {(p) => (
            <select {...p} value={dev.os} onChange={set('os')}>
              {OS_OPTIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          )}
        </Field>
      </div>
      <IdNote id={idText} isNew={!dev.id} renamed={renamed} />
      <div role="status" aria-live="polite">
        {test && !test.busy && <div className={`alert ${test.ok ? 'ok' : 'error'}`}>{test.message}</div>}
      </div>
      <div className="row">
        <button type="button" className="btn" disabled={test?.busy} onClick={onTest}>
          {test?.busy ? 'Probando…' : 'Probar conexión'}
        </button>
        <span className="spacer" />
        <button type="button" className="btn danger" onClick={onRemove} aria-label={`Eliminar dispositivo ${title}`}>Eliminar</button>
      </div>
    </fieldset>
  );
}
