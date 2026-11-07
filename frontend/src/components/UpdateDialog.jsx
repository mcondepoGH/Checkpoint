import React from 'react';
import Modal from './Modal.jsx';
import { safeUrl, isPrerelease } from '../updates.js';

// Detalle de la versión nueva. Las notas se pintan como texto (React escapa todo): nunca como HTML.
export default function UpdateDialog({ info, onClose }) {
  const url = safeUrl(info.url);
  const pre = isPrerelease(info);
  return (
    <Modal title="Nueva versión disponible" onClose={onClose} wide>
      <dl className="update-versions">
        <div><dt>Instalada</dt><dd>{info.actual}</dd></div>
        <div><dt>Nueva</dt><dd>{info.ultima}{pre && <span className="pre-tag">preliminar</span>}</dd></div>
      </dl>
      {pre && <p className="alert warn">Es una versión preliminar del canal de pruebas: puede fallar.</p>}
      {info.notas ? <><h4>Novedades</h4><div className="update-notes" tabIndex={0}>{info.notas}</div></> : <p className="muted">Esta versión no incluye notas.</p>}
      {url && <p><a href={url} target="_blank" rel="noopener noreferrer">Ver la versión en GitHub</a></p>}
      <p className="muted">Checkpoint no se actualiza solo: descarga la nueva versión, recompila la web y reinicia Checkpoint.</p>
      <div className="row end"><button className="btn" onClick={onClose}>Cerrar</button></div>
    </Modal>
  );
}
