import React from 'react';
import EmptyState from './EmptyState.jsx';

const fmt = (v) => {
  if (v === undefined || v === null) return '—';
  if (Array.isArray(v)) return v.join(', ');
  if (typeof v === 'object') return Object.entries(v).map(([k, x]) => `${k}: ${x}`).join(' · ');
  return String(v);
};

const SECTIONS = [['devices', 'Dispositivos'], ['games', 'Juegos']];

// Vista previa de cambios calculada por el backend (/api/config/diff).
export default function DiffView({ diff }) {
  if (!diff || diff.empty) return <EmptyState variant="inline" icon="✅" title="Sin cambios" text="No hay diferencias respecto al config.yaml actual." />;
  return (
    <div className="diff">
      {SECTIONS.map(([key, title]) => {
        const s = diff[key];
        if (!s || (!s.added.length && !s.removed.length && !Object.keys(s.changed).length)) return null;
        return (
          <section key={key}>
            <h4>{title}</h4>
            <ul>
              {s.added.map((n) => <li key={`a${n}`} className="add"><b>+ Añadir</b> {n}</li>)}
              {Object.entries(s.changed).map(([n, f]) => (
                <li key={`c${n}`} className="chg">
                  <b>~ Cambiar</b> {n}
                  <ul>{Object.entries(f).map(([k, v]) => (
                    <li key={k}><code>{k}</code>: {fmt(v.old)} <span aria-label="pasa a">→</span> {fmt(v.new)}</li>
                  ))}</ul>
                </li>
              ))}
              {s.removed.map((n) => <li key={`r${n}`} className="del"><b>− Eliminar</b> {n}</li>)}
            </ul>
          </section>
        );
      })}
    </div>
  );
}
