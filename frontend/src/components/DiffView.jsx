import React from 'react';
import EmptyState from './EmptyState.jsx';

// Las secciones del diff van por id interno; `diff.names` da el nombre de cada id. Los renombrados salen como
// un cambio del campo `name`.
const fmt = (v, field, names) => {
  const dev = (id) => names?.devices?.[id] || id;
  if (v === undefined || v === null) return '—';
  if (field === 'devices' && Array.isArray(v)) return v.map(dev).join(', ');
  if (Array.isArray(v)) return v.join(', ');
  if (typeof v === 'object') return Object.entries(v).map(([k, x]) => `${field === 'paths' ? dev(k) : k}: ${x}`).join(' · ');
  return String(v);
};

const SECTIONS = [['general', 'General'], ['devices', 'Dispositivos'], ['games', 'Juegos']];

// Vista previa de cambios calculada por el backend (/api/config/diff).
export default function DiffView({ diff }) {
  if (!diff || diff.empty) return <EmptyState variant="inline" icon="✅" title="Sin cambios" text="No hay diferencias respecto al config.yaml actual." />;
  const label = (section, id) => diff.names?.[section]?.[id] || id;
  return (
    <div className="diff">
      {SECTIONS.map(([key, title]) => {
        const s = diff[key];
        if (!s || (!s.added.length && !s.removed.length && !Object.keys(s.changed).length)) return null;
        return (
          <section key={key}>
            <h4>{title}</h4>
            <ul>
              {s.added.map((n) => <li key={`a${n}`} className="add"><b>+ Añadir</b> {label(key, n)}</li>)}
              {Object.entries(s.changed).map(([n, f]) => (
                <li key={`c${n}`} className="chg">
                  <b>~ Cambiar</b> {label(key, n)}
                  <ul>{Object.entries(f).map(([k, v]) => (
                    <li key={k}><code>{k}</code>: {fmt(v.old, k, diff.names)} <span aria-label="pasa a">→</span> {fmt(v.new, k, diff.names)}</li>
                  ))}</ul>
                </li>
              ))}
              {s.removed.map((n) => <li key={`r${n}`} className="del"><b>− Eliminar</b> {label(key, n)}</li>)}
            </ul>
          </section>
        );
      })}
    </div>
  );
}
