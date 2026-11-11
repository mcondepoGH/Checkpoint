import React from 'react';

// Pastilla de texto corto (nombre de dispositivo...). highlight: resalta la ganadora.
// tone="info": pastilla informativa (icono + texto) con borde de acento.
export default function Pill({ highlight, tone, title, children }) {
  const cls = ['pill', highlight && 'win', tone].filter(Boolean).join(' ');
  return (
    <span className={cls} title={title}>
      {children}
    </span>
  );
}
