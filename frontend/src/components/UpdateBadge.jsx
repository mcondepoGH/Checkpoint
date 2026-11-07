import React from 'react';
import Icon from './Icon.jsx';
import { showBadge, isPrerelease } from '../updates.js';

// Botón de la cabecera: solo existe si hay una versión nueva. En móvil se queda en el icono.
export default function UpdateBadge({ info, onOpen }) {
  if (!showBadge(info)) return null;
  const pre = isPrerelease(info);
  const text = `Nueva versión${pre ? ' preliminar' : ''} disponible: ${info.ultima}`;
  return (
    <button className="btn ghost tool update-badge" onClick={onOpen} title={text} aria-label={text}>
      <Icon name="download" /><span className="lbl">Nueva versión disponible</span>
      {pre && <span className="lbl pre-tag">preliminar</span>}
    </button>
  );
}
