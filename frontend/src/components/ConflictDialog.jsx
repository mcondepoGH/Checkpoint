import React, { useState } from 'react';
import Modal from './Modal.jsx';
import { fmtSize, fmtWhen } from '#src/lib/format.js';
import { useI18n } from '#src/useI18n.js';
import { Button } from '#src/components/ui/index.js';

// Motivos del conflicto (ids estables del backend) -> clave `conflict.reason.<id con _>`.
const REASONS = ['both-changed', 'no-baseline', 'inconsistent', 'indeterminate', 'stale'];

// Popup de conflicto: Cancelar | Gana el más reciente | Elegir dispositivo. Esc = Cancelar.
export default function ConflictDialog({ game, conflict, busy, onCancel, onResolve }) {
  const { t, locale } = useI18n();
  const sides = conflict?.sides || [];
  const [choosing, setChoosing] = useState(false);
  const [pick, setPick] = useState('');
  const label = (s) => (s.hub ? t('conflict.hub') : s.name);
  // El origen se identifica por su id (el nombre solo se muestra).
  const sid = (s) => s.id;
  const value = (s) => (s.hub ? 'hub' : `device:${sid(s)}`);
  const expect = Object.fromEntries(sides.map((s) => [sid(s), s.hash]));
  const reason = REASONS.includes(conflict?.reason) ? conflict.reason : 'both-changed';
  const files = (s) => t('files', { count: s.files });

  return (
    <Modal title={t('conflict.title', { game })} onClose={onCancel} wide>
      <p>{t(`conflict.reason.${reason.replace('-', '_')}`)} {t('conflict.note')}</p>
      {!choosing && (
        <ul className="conflict-sides" aria-label={t('conflict.sidesAria')}>
          {sides.map((s) => (
            <li key={sid(s)}>
              <b>{label(s)}</b>
              <span>{fmtWhen(s.mtime, locale)}</span>
              <span>{fmtSize(s.size, locale)} · {files(s)}</span>
            </li>
          ))}
        </ul>
      )}
      {choosing && (
        <fieldset className="conflict-pick">
          <legend>{t('conflict.pick')}</legend>
          {sides.map((s) => (
            <label key={sid(s)} className={`conflict-opt${pick === value(s) ? ' on' : ''}`}>
              <input type="radio" name="conflict-winner" value={value(s)} checked={pick === value(s)}
                onChange={() => setPick(value(s))} />
              <span><b>{label(s)}</b><br />
                <small>{fmtWhen(s.mtime, locale)} · {fmtSize(s.size, locale)} · {files(s)}</small></span>
            </label>
          ))}
        </fieldset>
      )}
      <div className="row end">
        <Button onClick={onCancel} disabled={busy}>{t('common.cancel')}</Button>
        {!choosing && (
          <>
            <Button disabled={busy} onClick={() => onResolve('newest', expect)}>{t('conflict.newest')}</Button>
            <Button variant="primary" disabled={busy} onClick={() => setChoosing(true)}>{t('conflict.choose')}</Button>
          </>
        )}
        {choosing && (
          <>
            <Button disabled={busy} onClick={() => { setChoosing(false); setPick(''); }}>{t('conflict.back')}</Button>
            <Button variant="primary" disabled={busy || !pick} onClick={() => onResolve(pick, expect)}>{t('conflict.apply')}</Button>
          </>
        )}
      </div>
    </Modal>
  );
}
