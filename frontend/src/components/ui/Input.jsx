import React, { forwardRef } from 'react';

// Campo de texto. Sin type (texto): sin autocompletar ni corrector, que es lo que quieren todos los campos de la app.
// Con otro type (number...) no añade nada. Las props explícitas mandan. Acepta ref.
const Input = forwardRef(function Input({ type, ...rest }, ref) {
  const text = type === undefined || type === 'text';
  return <input ref={ref} {...(type ? { type } : {})} {...(text ? { autoComplete: 'off', spellCheck: 'false' } : {})} {...rest} />;
});
export default Input;
