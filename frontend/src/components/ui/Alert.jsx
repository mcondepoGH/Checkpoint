import React from 'react';

// Aviso. variant: 'error' | 'ok' | 'warn' | 'info' (sin variant = neutro). inline: caja en línea sin márgenes.
// compact: bloque pequeño sin márgenes, con icono y texto en fila (el icono va como primer hijo).
// as: etiqueta HTML (div por defecto). Resto de props (role, style...) pasan al elemento.
export default function Alert({ variant, inline, compact, as: Tag = 'div', children, ...rest }) {
  const cls = ['alert', variant, inline && 'inline', compact && 'compact'].filter(Boolean).join(' ');
  return <Tag className={cls} {...rest}>{children}</Tag>;
}
