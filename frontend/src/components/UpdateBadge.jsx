import React from 'react';
import Icon from './Icon.jsx';
import { showBadge, isPrerelease } from '../updates.js';
import { useI18n } from '../useI18n.js';

// Botón de la cabecera: solo existe si hay una versión nueva. En móvil se queda en el icono.
export default function UpdateBadge({ info, onOpen }) {
  const { t } = useI18n();
  if (!showBadge(info)) return null;
  const pre = isPrerelease(info);
  const text = t(pre ? 'updates.badgePre' : 'updates.badge', { version: info.ultima });
  return (
    <button className="btn ghost tool update-badge" onClick={onOpen} title={text} aria-label={text}>
      <Icon name="download" /><span className="lbl">{t('updates.badgeLabel')}</span>
      {pre && <span className="lbl pre-tag">{t('updates.pre')}</span>}
    </button>
  );
}
