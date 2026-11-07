import React, { useState } from 'react';
import Modal from './Modal.jsx';

export function fmtSize(n) {
  if (!Number.isFinite(n)) return '—';
  if (n < 1024) return `${n} B`;
  const u = ['KB', 'MB', 'GB'];
  let v = n / 1024;
  let i = 0;
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i += 1; }
  return `${v.toFixed(v < 10 ? 1 : 0)} ${u[i]}`;
}

export function fmtWhen(sec) {
  if (!sec) return '—';
  return new Date(sec * 1000).toLocaleString('es-ES', { dateStyle: 'medium', timeStyle: 'medium' });
}

const REASONS = {
  'both-changed': 'Los dos lados han cambiado desde la última sincronización y su contenido es distinto.',
  'no-baseline': 'Es la primera comparación con estos datos y los contenidos son distintos.',
  inconsistent: 'Los contenidos difieren y no hay cambios registrados.',
  indeterminate: 'Las fechas difieren menos de 2 segundos: no se puede saber cuál es más reciente. Elige a mano.',
  stale: 'Los datos han cambiado desde que se mostró el aviso anterior. Revisa y vuelve a elegir.',
};

// Popup de conflicto: Cancelar | Gana el más reciente | Elegir dispositivo. Esc = Cancelar.
export default function ConflictDialog({ game, conflict, busy, onCancel, onResolve }) {
  const sides = conflict?.sides || [];
  const [choosing, setChoosing] = useState(false);
  const [pick, setPick] = useState('');
  const label = (s) => (s.hub ? 'Hub (copia en Checkpoint)' : s.name);
  const value = (s) => (s.hub ? 'hub' : `device:${s.name}`);
  const expect = Object.fromEntries(sides.map((s) => [s.name, s.hash]));

  return (
    <Modal title={`Conflicto en ${game}`} onClose={onCancel} wide>
      <p>{REASONS[conflict?.reason] || REASONS['both-changed']} No se ha modificado nada. Antes de sobrescribir, la copia perdedora se guarda en versiones.</p>
      {!choosing && (
        <ul className="conflict-sides" aria-label="Versiones en conflicto">
          {sides.map((s) => (
            <li key={s.name}>
              <b>{label(s)}</b>
              <span>{fmtWhen(s.mtime)}</span>
              <span>{fmtSize(s.size)} · {s.files} {s.files === 1 ? 'fichero' : 'ficheros'}</span>
            </li>
          ))}
        </ul>
      )}
      {choosing && (
        <fieldset className="conflict-pick">
          <legend>¿Qué save debe ganar?</legend>
          {sides.map((s) => (
            <label key={s.name} className={`conflict-opt${pick === value(s) ? ' on' : ''}`}>
              <input type="radio" name="conflict-winner" value={value(s)} checked={pick === value(s)}
                onChange={() => setPick(value(s))} />
              <span><b>{label(s)}</b><br />
                <small>{fmtWhen(s.mtime)} · {fmtSize(s.size)} · {s.files} {s.files === 1 ? 'fichero' : 'ficheros'}</small></span>
            </label>
          ))}
        </fieldset>
      )}
      <div className="row end">
        <button type="button" className="btn" onClick={onCancel} disabled={busy}>Cancelar</button>
        {!choosing && (
          <>
            <button type="button" className="btn" disabled={busy} onClick={() => onResolve('newest', expect)}>Gana el más reciente</button>
            <button type="button" className="btn primary" disabled={busy} onClick={() => setChoosing(true)}>Elegir dispositivo</button>
          </>
        )}
        {choosing && (
          <>
            <button type="button" className="btn" disabled={busy} onClick={() => { setChoosing(false); setPick(''); }}>Atrás</button>
            <button type="button" className="btn primary" disabled={busy || !pick} onClick={() => onResolve(pick, expect)}>Aplicar</button>
          </>
        )}
      </div>
    </Modal>
  );
}
