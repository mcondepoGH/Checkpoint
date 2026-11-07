import React from 'react';
import Modal from './Modal.jsx';
import { safeUrl } from '../updates.js';

// Detalle de la versión nueva. Las notas se pintan como texto (React escapa todo): nunca como HTML.
export default function UpdateDialog({ info, onClose }) {
  const url = safeUrl(info.url);
  return (
    <Modal title="Nueva versión disponible" onClose={onClose} wide>
      <dl className="update-versions">
        <div><dt>Instalada</dt><dd>{info.actual}</dd></div>
        <div><dt>Nueva</dt><dd>{info.ultima}</dd></div>
      </dl>
      {info.notas ? <><h4>Novedades</h4><div className="update-notes" tabIndex={0}>{info.notas}</div></> : <p className="muted">Esta versión no incluye notas.</p>}
      {url && <p><a href={url} target="_blank" rel="noopener noreferrer">Ver la versión en GitHub</a></p>}
      <p className="muted">Para actualizar, reconstruye la imagen de Checkpoint y vuelve a levantar el contenedor.</p>
      <div className="row end"><button className="btn" onClick={onClose}>Cerrar</button></div>
    </Modal>
  );
}
