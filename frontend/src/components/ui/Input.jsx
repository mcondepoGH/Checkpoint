import React from 'react';

// Campo de texto. Sin type (texto): sin autocompletar ni corrector, que es lo que quieren todos los campos de la app.
// Con otro type (number...) no añade nada. Las props explícitas mandan.
export default function Input({ type, ...rest }) {
  const text = type === undefined || type === 'text';
  return <input {...(type ? { type } : {})} {...(text ? { autoComplete: 'off', spellCheck: 'false' } : {})} {...rest} />;
}
