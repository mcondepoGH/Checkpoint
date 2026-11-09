import React, { forwardRef } from 'react';

// Botón único. variant: 'primary' | 'danger' | 'ghost' (sin variant = botón neutro). className añade clases de contexto (tool, preset, chip...).
// type es 'button' por defecto (nunca envía formularios por accidente); pasa type="submit" para enviar. Acepta ref.
const Button = forwardRef(function Button({ variant, className, type = 'button', children, ...rest }, ref) {
  const cls = ['btn', variant, className].filter(Boolean).join(' ');
  return <button ref={ref} type={type} className={cls} {...rest}>{children}</button>;
});
export default Button;
