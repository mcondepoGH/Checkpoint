import React, { useId } from 'react';

// Etiqueta + control + error asociado (aria-describedby / aria-invalid). `children` recibe los props a esparcir en el control.
export default function Field({ label, error, hint, children }) {
  const id = useId();
  const errId = `${id}-err`;
  const hintId = `${id}-hint`;
  const describedBy = [error ? errId : null, hint ? hintId : null].filter(Boolean).join(' ') || undefined;
  return (
    <div className={error ? 'field has-error' : 'field'}>
      <label htmlFor={id}>{label}</label>
      {children({ id, 'aria-invalid': error ? true : undefined, 'aria-describedby': describedBy })}
      {hint && <small id={hintId} className="muted">{hint}</small>}
      {error && <small id={errId} className="field-error">{error}</small>}
    </div>
  );
}
