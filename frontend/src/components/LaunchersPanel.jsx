import React, { useId } from 'react';
import { useI18n } from '#src/hooks/useI18n.js';
import Icon from './Icon.jsx';
import LauncherBlock from './LauncherBlock.jsx';
import { Button } from '#src/components/ui/index.js';

// Sección «Lanzadores» de Configuración: tarjeta propia, plegada por defecto, con Mostrar/Ocultar. El contenido (y sus peticiones)
// solo existe mientras está desplegada. Props de LauncherBlock más `open` y `onToggle`; `id` permite saltar a ella desde la tarjeta de un juego.
export default function LaunchersPanel({ open, onToggle, id, ...rest }) {
  const { t } = useI18n();
  const uid = useId();
  const bodyId = `${uid}-body`;
  return (
    <section className="card launchers-panel" id={id} aria-labelledby={`${uid}-t`}>
      <div className="row between">
        <h3 id={`${uid}-t`} className="launcher-title"><Icon name="code" />{t('launcher.title')}</h3>
        <Button variant="ghost" onClick={onToggle} aria-expanded={open} aria-controls={bodyId}>{t(open ? 'launcher.hide' : 'launcher.show')}</Button>
      </div>
      <div id={bodyId} className="launchers-body" hidden={!open}>
        {open && <LauncherBlock {...rest} active />}
      </div>
    </section>
  );
}
