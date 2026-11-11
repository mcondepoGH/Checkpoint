import React from 'react';
import Icon from '#src/components/ui/Icon.jsx';
import { showBadge, isPrerelease } from '#src/lib/updates.js';
import { useI18n } from '#src/hooks/useI18n.js';
import { Button } from '#src/components/ui/index.js';

// Botón de la cabecera: solo existe si hay una versión nueva. En móvil se queda en el icono.
export default function UpdateBadge({ info, onOpen }) {
  const { t } = useI18n();
  if (!showBadge(info)) return null;
  const pre = isPrerelease(info);
  const text = t(pre ? 'updates.badgePre' : 'updates.badge', { version: info.ultima });
  return (
    <Button variant="ghost" className="tool update-badge" onClick={onOpen} title={text} aria-label={text}>
      <Icon name="download" /><span className="lbl">{t('updates.badgeLabel')}</span>
      {pre && <span className="lbl pre-tag">{t('updates.pre')}</span>}
    </Button>
  );
}
