import React, { useId, useRef } from 'react';
import { nextTabIndex } from '#src/lib/tabs.js';

// Pestañas accesibles (roles tablist/tab/tabpanel; flechas, Inicio y Fin; solo la activa entra por Tab).
// tabs: [{ id, label, short?, dot? }]. value: id activo. onChange(id). label: aria-label del tablist.
// `short`: etiqueta corta (se muestra en móvil en lugar de `label`). `dot`: texto para lectores de pantalla; si existe, la pestaña lleva un punto de aviso.
// children: contenido del panel activo (solo ese se monta). Con `keepMounted`, `panels` ({ id: nodo }) pinta todos los paneles y los inactivos
// quedan ocultos con `hidden`, sin desmontar (conservan su estado); un panel con valor null/false no se pinta (montaje condicional de uno concreto).
// variant="subnav": subnavegación de una pantalla (subrayado, sin cajas), distinta de las pestañas normales (filtros).
export default function Tabs({ tabs, value, onChange, label, children, variant, keepMounted = false, panels = {} }) {
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
    <div className={variant === 'subnav' ? 'uitabs subnav' : 'uitabs'}>
      <div className="uitabs-list" role="tablist" aria-label={label}>
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
            onKeyDown={onKeyDown}
          >
            {x.short ? (
              <>
                <span className="uitab-full">{x.label}</span>
                <span className="uitab-short">{x.short}</span>
              </>
            ) : (
              x.label
            )}
            {x.dot && (
              <>
                <span className="uitab-dot" aria-hidden="true" />
                <span className="sr-only">{x.dot}</span>
              </>
            )}
          </button>
        ))}
      </div>
      {keepMounted ? (
        tabs.map((x) => (
          <div
            key={x.id}
            className="uitabs-panel"
            role="tabpanel"
            id={panelId(x.id)}
            aria-labelledby={tabId(x.id)}
            hidden={x.id !== value}
            tabIndex={variant === 'subnav' ? undefined : 0}
          >
            {panels[x.id] || null}
          </div>
        ))
      ) : (
        <div className="uitabs-panel" role="tabpanel" id={panelId(value)} aria-labelledby={tabId(value)} tabIndex={0}>
          {children}
        </div>
      )}
    </div>
  );
}
