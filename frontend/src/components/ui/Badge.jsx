import React from 'react';

// Etiqueta de estado con punto de color. status: ok | error | conflict | partial | aborted | dry-run | running (vacío = neutra).
export default function Badge({ status, children }) {
  return <span className={status ? `badge ${status}` : 'badge'}>{children}</span>;
}
