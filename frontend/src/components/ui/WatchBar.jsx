import React from 'react';

// Franja de estado inferior de la tarjeta de un juego vigilado (la tarjeta lleva además el borde de color: ver
// watchCardClass en watch.js). Icono decorativo + texto + hora opcional: el estado nunca depende solo del color.
// state: waiting | running | settling | stale (sin latido). children: texto; since: «desde HH:MM» (opcional).
const GLYPH = { waiting: '◌', running: '●', settling: '↻', stale: '⚠' };

export default function WatchBar({ state, since, children }) {
  return (
    <div className={`watch-bar ${state}`} role="status">
      <i className="watch-ico" aria-hidden="true">{GLYPH[state] || GLYPH.waiting}</i>
      <span className="watch-text">{children}</span>
      {since && <span className="watch-since">{since}</span>}
    </div>
  );
}
