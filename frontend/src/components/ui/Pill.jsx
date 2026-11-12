import React from 'react';

// Pastilla de texto corto (nombre de dispositivo...). highlight: resalta la ganadora.
// tone="info": pastilla informativa (icono + texto) con borde de acento.
// tone="manual" | "scheduled" | "launcher": origen de una ejecución del registro (punto y borde de color + texto).
// Los tonos de origen llevan prefijo `origin-`: un `.launcher` suelto choca con el panel de launchers de Configuración
// (`.launcher` = flex en columna), que estiraba la píldora y ponía el punto encima del texto.
const ORIGIN_TONES = ['manual', 'scheduled', 'launcher'];
export default function Pill({ highlight, tone, title, children }) {
  const toneCls = ORIGIN_TONES.includes(tone) ? `origin-${tone}` : tone;
  const cls = ['pill', highlight && 'win', toneCls].filter(Boolean).join(' ');
  return (
    <span className={cls} title={title}>
      {children}
    </span>
  );
}
