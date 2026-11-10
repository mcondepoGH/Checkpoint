import React, { useEffect, useId, useRef, useState } from 'react';
import { labelOf } from '../names.js';
import { useI18n } from '../useI18n.js';
import { chipCount, groupByGame, watchHealth } from '../watch.js';
import { WatchStatus } from './ui/index.js';

// Contador de vigilancia en la cabecera del hub: chip «● Vigilando · N ▾» + lista desplegable (juego, dispositivo, estado).
// Sin vigilancia no pinta nada. Popover no modal como ProfileMenu: Esc cierra y devuelve el foco al chip; pulsar fuera o sacar el foco lo cierra.
// `watch` es el estado compartido de useWatches ({now, watches}); `open` inicial solo se usa para renderizar la lista en pruebas.
export default function WatchSummary({ watch, config, open: initialOpen = false }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(initialOpen);
  const wrap = useRef(null);
  const btn = useRef(null);
  const listId = useId();
  const byGame = groupByGame(watch.watches);
  const watched = Object.keys(config.games).filter((g) => byGame[g] && config.games[g].enabled !== false);

  useEffect(() => {
    if (!open) return undefined;
    const outside = (e) => { if (wrap.current && !wrap.current.contains(e.target)) setOpen(false); };
    document.addEventListener('pointerdown', outside);
    return () => document.removeEventListener('pointerdown', outside);
  }, [open]);
  useEffect(() => { if (watched.length === 0) setOpen(false); }, [watched.length]);

  if (watched.length === 0) return null;
  const count = t('sync.watch.count', { count: watched.length });
  const onKeyDown = (e) => { if (e.key === 'Escape' && open) { e.stopPropagation(); setOpen(false); btn.current?.focus(); } };
  const onBlur = (e) => { if (open && e.relatedTarget && !wrap.current.contains(e.relatedTarget)) setOpen(false); };
  const row = (w) => {
    const h = watchHealth(w, watch.now);
    return (
      <li key={`${w.game}|${w.device}`}>
        <span className="watch-row-name">{labelOf(config.games, w.game)}</span>
        <small className="watch-row-dev">{labelOf(config.devices, w.device)}</small>
        <WatchStatus state={h}>{t(`sync.watch.short.${h}`)}</WatchStatus>
      </li>
    );
  };

  return (
    <div className="watch-summary" ref={wrap} onKeyDown={onKeyDown} onBlur={onBlur}>
      <button ref={btn} type="button" className="watch-toggle" aria-label={count} aria-expanded={open} aria-controls={open ? listId : undefined} onClick={() => setOpen((o) => !o)}>
        <i className="watch-chip-dot" aria-hidden="true" />
        <b className="watch-num" aria-hidden="true">{chipCount(watched.length)}</b>
        <span className="watch-lbl" aria-hidden="true">{t('sync.watch.chip', { count: chipCount(watched.length) })}</span>
        <i className="watch-caret" aria-hidden="true">▾</i>
      </button>
      {open && (
        <ul id={listId} className="watch-list" aria-label={t('sync.watch.listAria')}>
          {watched.map((g) => byGame[g].map(row))}
        </ul>
      )}
    </div>
  );
}
