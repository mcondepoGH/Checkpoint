import React from 'react';

// Desplegable nativo. options: [{ value, label }]. placeholder: primera opción con valor '' (p. ej. «Elige...»).
// Resto de props (id, value, onChange, aria-*...) pasan al select nativo, así que sirve como control de un Field.
export default function Select({ options, placeholder, ...rest }) {
  return (
    <select {...rest}>
      {placeholder !== undefined && <option value="">{placeholder}</option>}
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  );
}
