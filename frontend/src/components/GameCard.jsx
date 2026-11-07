import React from 'react';
import Field from './Field.jsx';
import { MAX_VERSIONS_LIMIT, NAME_HINT, NAME_MAX, VERSIONS_HINT } from '../draft.js';
import IdNote from './IdNote.jsx';
import { ON_CONFLICT_OPTIONS } from '../format.js';

export default function GameCard({ game, devices, errors, localError, keepError, globalMax, nameA, nameB, idA, idB, idText, renamed, onChange, onRemove }) {
  const set = (k) => (e) => onChange({ [k]: e.target.value });
  const title = game.name || 'Juego nuevo';
  // Solo dispositivos con nombre; el elegido en el otro selector no se ofrece.
  const options = (other) => devices.filter((d) => d.name && d.key !== other);
  const sel = (key, other) => (p) => (
    <select {...p} value={game[key]} onChange={set(key)}>
      <option value="">— elige —</option>
      {options(other).map((d) => <option key={d.key} value={d.key}>{d.name}</option>)}
    </select>
  );
  const pathErr = (id) => (id ? errors[`paths.${id}`] : undefined);
  return (
    <fieldset className="card cfg-card">
      <legend className="cfg-title">{title}</legend>
      <Field label="Nombre" hint={NAME_HINT} error={localError || errors.name || errors['']}>
        {(p) => <input {...p} value={game.name} onChange={set('name')} maxLength={NAME_MAX} placeholder="p. ej. Mi Juego: Edición" autoComplete="off" spellCheck="false" />}
      </Field>
      {errors.devices && <div className="alert error" role="alert">{errors.devices}</div>}
      <div className="two">
        <Field label="Dispositivo 1" error={errors['devices.0']}>{sel('a', game.b)}</Field>
        <Field label="Dispositivo 2" error={errors['devices.1']}>{sel('b', game.a)}</Field>
      </div>
      {game.a && (
        <Field label={`Ruta del save en ${nameA}`} error={pathErr(idA)}>
          {(p) => <input {...p} value={game.pathA} onChange={set('pathA')} autoComplete="off" spellCheck="false" />}
        </Field>
      )}
      {game.b && (
        <Field label={`Ruta del save en ${nameB}`} error={pathErr(idB)}>
          {(p) => <input {...p} value={game.pathB} onChange={set('pathB')} autoComplete="off" spellCheck="false" />}
        </Field>
      )}
      <div className="two">
        <Field label="Proceso (opcional)" hint="No copia si está abierto" error={errors.process}>
          {(p) => <input {...p} value={game.process} onChange={set('process')} placeholder="juego.exe" autoComplete="off" spellCheck="false" />}
        </Field>
        <Field label="Máx. de versiones (este juego)" hint={`Vacío = usar el global (${globalMax}). ${VERSIONS_HINT}`} error={keepError || errors.keep_versions}>
          {(p) => <input {...p} type="number" inputMode="numeric" min="0" max={MAX_VERSIONS_LIMIT} step="1" value={game.keep} onChange={set('keep')} placeholder={String(globalMax)} />}
        </Field>
      </div>
      <Field label="En conflicto (sync automática)" hint="Sustituye al ajuste global de Sincronización automática solo para este juego." error={errors.on_conflict}>
        {(p) => (
          <select {...p} value={game.onConflict || ''} onChange={set('onConflict')}>
            <option value="">Usar el ajuste global</option>
            {ON_CONFLICT_OPTIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        )}
      </Field>
      <IdNote id={idText} isNew={!game.id} renamed={renamed} />
      <div className="row end">
        <button type="button" className="btn danger" onClick={onRemove} aria-label={`Eliminar juego ${title}`}>Eliminar</button>
      </div>
    </fieldset>
  );
}
