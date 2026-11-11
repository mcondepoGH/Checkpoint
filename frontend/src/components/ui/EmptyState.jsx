import React from 'react';

// Estado vacío centrado: icono, título, texto de ayuda y CTA opcional.
// variant: 'page' (ocupa el área restante de la página), 'card' (dentro de una tarjeta/sección), 'inline' (compacto, p. ej. en diálogos).
export default function EmptyState({ icon, title, text, children, action, variant = 'card', live = true }) {
  const body = children ?? text;
  return (
    <div className={`empty-state ${variant}`} role={live ? 'status' : undefined}>
      {icon && (
        <span className="empty-icon" aria-hidden="true">
          {icon}
        </span>
      )}
      {title && <h3 className="empty-title">{title}</h3>}
      {body && <p className="empty-text">{body}</p>}
      {action && <div className="empty-action">{action}</div>}
    </div>
  );
}
