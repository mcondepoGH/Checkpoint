import React, { useId, useRef } from 'react';
import { nextTabIndex } from '#src/lib/tabs.js';

// Pestañas accesibles (roles tablist/tab/tabpanel; flechas, Inicio y Fin; solo la activa entra por Tab).
// tabs: [{ id, label }]. value: id activo. onChange(id). label: aria-label del tablist. children: contenido del panel activo.
export default function Tabs({ tabs, value, onChange, label, children }) {
  const uid = useId();
  const refs = useRef({});
  const tabId = (id) => `${uid}-tab-${id}`;
  const panelId = (id) => `${uid}-panel-${id}`;
  const onKeyDown = (e) => {
    const i = nextTabIndex(
      tabs.length,
      tabs.findIndex((x) => x.id === value),
      e.key,
    );
    if (i === null) return;
    e.preventDefault();
    onChange(tabs[i].id);
    refs.current[tabs[i].id]?.focus();
  };
  return (
    <div className="uitabs">
      <div className="uitabs-list" role="tablist" aria-label={label} onKeyDown={onKeyDown}>
        {tabs.map((x) => (
          <button
            key={x.id}
            ref={(el) => {
              refs.current[x.id] = el;
            }}
            type="button"
            role="tab"
            id={tabId(x.id)}
            className={x.id === value ? 'uitab active' : 'uitab'}
            aria-selected={x.id === value}
            aria-controls={panelId(x.id)}
            tabIndex={x.id === value ? 0 : -1}
            onClick={() => onChange(x.id)}
          >
            {x.label}
          </button>
        ))}
      </div>
      <div className="uitabs-panel" role="tabpanel" id={panelId(value)} aria-labelledby={tabId(value)} tabIndex={0}>
        {children}
      </div>
    </div>
  );
}
