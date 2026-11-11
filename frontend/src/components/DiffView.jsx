import React from 'react';
import EmptyState from './EmptyState.jsx';
import { useI18n } from '#src/hooks/useI18n.js';

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

// Secciones del diff (ids del backend); su título es `diff.<id>`.
const SECTIONS = ['general', 'devices', 'games'];

// Vista previa de cambios calculada por el backend (/api/config/diff).
export default function DiffView({ diff }) {
  const { t } = useI18n();
  if (!diff || diff.empty) return <EmptyState variant="inline" icon="✅" title={t('diff.none.title')} text={t('diff.none.text')} />;
  const label = (section, id) => diff.names?.[section]?.[id] || id;
  return (
    <div className="diff">
      {SECTIONS.map((key) => {
        const s = diff[key];
        if (!s || (!s.added.length && !s.removed.length && !Object.keys(s.changed).length)) return null;
        return (
          <section key={key}>
            <h4>{t(`diff.${key}`)}</h4>
            <ul>
              {s.added.map((n) => <li key={`a${n}`} className="add"><b>{t('diff.add')}</b> {label(key, n)}</li>)}
              {Object.entries(s.changed).map(([n, f]) => (
                <li key={`c${n}`} className="chg">
                  <b>{t('diff.change')}</b> {label(key, n)}
                  <ul>{Object.entries(f).map(([k, v]) => (
                    <li key={k}><code>{k}</code>: {fmt(v.old, k, diff.names)} <span aria-label={t('diff.arrow')}>→</span> {fmt(v.new, k, diff.names)}</li>
                  ))}</ul>
                </li>
              ))}
              {s.removed.map((n) => <li key={`r${n}`} className="del"><b>{t('diff.remove')}</b> {label(key, n)}</li>)}
            </ul>
          </section>
        );
      })}
    </div>
  );
}
