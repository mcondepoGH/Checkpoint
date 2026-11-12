import React from 'react';
import Icon from '#src/components/ui/Icon.jsx';
import LauncherBlock from '#src/components/launchers/LauncherBlock.jsx';
import { useI18n } from '#src/hooks/useI18n.js';

// Subpestaña «Lanzadores» de Configuración: comandos listos para copiar. Solo se monta al abrirla (el contenedor la pinta
// únicamente cuando está activa), así que sus peticiones (API key, estado) no se hacen antes.
export default function Launchers(props) {
  const { t } = useI18n();
  return (
    <section className="card launchers-panel" aria-labelledby="launchers-title">
      <h3 id="launchers-title" className="launcher-title">
        <Icon name="code" />
        {t('launcher.title')}
      </h3>
      <LauncherBlock {...props} active />
    </section>
  );
}
