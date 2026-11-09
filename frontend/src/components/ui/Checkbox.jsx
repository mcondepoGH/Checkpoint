import React from 'react';

// Casilla con su etiqueta. label: texto o nodo. Las props van al <input> (checked, onChange, aria-*...).
export default function Checkbox({ label, ...rest }) {
  return (
    <label className="check">
      <input type="checkbox" {...rest} />
      <span>{label}</span>
    </label>
  );
}
