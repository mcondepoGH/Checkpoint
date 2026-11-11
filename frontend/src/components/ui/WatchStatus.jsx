import React from 'react';

// Indicador de vigilancia: punto + texto (el estado nunca depende solo del color).
// state: waiting | running | settling | stale (sin latido). children: el texto.
export default function WatchStatus({ state, children }) {
  return (
    <span className={`watch ${state}`}>
      <i className="watch-dot" aria-hidden="true" />
      {children}
    </span>
  );
}
