import React from 'react';
import Icon from './Icon.jsx';
import { showBadge } from '../updates.js';

// Botón de la cabecera: solo existe si hay una versión nueva. En móvil se queda en el icono.
export default function UpdateBadge({ info, onOpen }) {
  if (!showBadge(info)) return null;
  return (
    <button className="btn ghost tool update-badge" onClick={onOpen} title={`Nueva versión disponible: ${info.ultima}`}
      aria-label={`Nueva versión disponible: ${info.ultima}`}>
      <Icon name="download" /><span className="lbl">Nueva versión disponible</span>
    </button>
  );
}
