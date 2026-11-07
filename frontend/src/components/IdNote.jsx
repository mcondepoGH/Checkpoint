import React from 'react';

// Pie de la tarjeta: ID interno (solo lectura) y aviso al renombrar un elemento que ya existe.
export default function IdNote({ id, isNew, renamed }) {
  return (
    <>
      {renamed && (
        <p className="alert info" role="status">
          El ID interno no cambia: tus saves y versiones siguen asociados.
        </p>
      )}
      <p className="idnote muted" title="Identificador interno: no cambia al renombrar">
        ID interno: <code>{id}</code>{isNew ? ' (se fija al guardar)' : ''}
      </p>
    </>
  );
}
