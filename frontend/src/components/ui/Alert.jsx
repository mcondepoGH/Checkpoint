import React from 'react';

// Aviso. variant: 'error' | 'ok' | 'warn' | 'info' (sin variant = neutro). inline: caja en línea sin márgenes.
// as: etiqueta HTML (div por defecto). Resto de props (role, style...) pasan al elemento.
export default function Alert({ variant, inline, as: Tag = 'div', children, ...rest }) {
  const cls = ['alert', variant, inline && 'inline'].filter(Boolean).join(' ');
  return <Tag className={cls} {...rest}>{children}</Tag>;
}
