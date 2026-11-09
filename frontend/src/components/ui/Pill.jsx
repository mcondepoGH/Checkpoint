import React from 'react';

// Pastilla de texto corto (nombre de dispositivo...). highlight: resalta la ganadora.
export default function Pill({ highlight, children }) {
  return <span className={highlight ? 'pill win' : 'pill'}>{children}</span>;
}
