import React from 'react';
import Icon from '../Icon.jsx';

// Franja de estado inferior de la tarjeta de un juego vigilado (la tarjeta lleva además el borde de color: ver
// watchCardClass en watch.js). Icono decorativo + texto + hora opcional: el estado nunca depende solo del color.
// state: waiting | running | settling | stale (sin latido). children: texto; since: «desde HH:MM» (opcional).
// El icono no usa glifos de fuente: running (punto) y waiting (anillo) los dibuja el CSS (::before) y settling/stale
// son SVG del componente Icon; todo centrado por geometría (ver _watch.scss).
const ICON = { settling: 'spinner', stale: 'alert' };

export default function WatchBar({ state, since, children }) {
  return (
    <div className={`watch-bar ${state}`} role="status">
      <i className="watch-ico" aria-hidden="true"><i className="watch-mark">{ICON[state] && <Icon name={ICON[state]} />}</i></i>
      <span className="watch-text">{children}</span>
      {since && <span className="watch-since">{since}</span>}
    </div>
  );
}
