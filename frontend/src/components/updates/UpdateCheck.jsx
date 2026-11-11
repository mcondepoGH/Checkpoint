import React, { useState } from 'react';
import { updatesApplicable, updateSummary, channelOf, CHANNEL_OPTIONS, CHANNEL_HELP } from '#src/lib/updates.js';
import { errText, useI18n } from '#src/hooks/useI18n.js';
import { ui } from '#src/lib/errors.js';
import { Alert, Button, Select, Switch } from '#src/components/ui/index.js';
import { putUpdates, refreshUpdates } from '#src/lib/api/updates.js';

// Tarjeta de Configuración: activar/desactivar la comprobación de versiones nuevas y forzarla a mano.
export default function UpdateCheck({ info, onInfo }) {
  const { t } = useI18n();
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null); // error de la API o mensaje {code} (se traduce al pintar)
  if (info && !updatesApplicable(info)) return null; // Docker sin forzar: ni tarjeta ni selector de canal
  const enabled = info ? info.habilitado !== false : true;

  // Ejecuta una acción con el indicador de trabajo y muestra su error, si lo hay.
  const act = async (fn) => {
    setBusy(true); setMsg(null);
    try { await fn(); } catch (e) { setMsg(e); } finally { setBusy(false); }
  };
  const put = (body) => act(async () => onInfo(await putUpdates(body)));
  const toggle = (value) => put({ enabled: value });
  const setChannel = (value) => put({ channel: value });
  const refresh = () => act(async () => {
    const r = await refreshUpdates();
    onInfo(r);
    if (r.limitado) setMsg(ui('updates.check.limited'));
  });

  return (
    <section className="card" aria-labelledby="updates-title">
      <h3 id="updates-title">{t('updates.check.title')}</h3>
      <p className="muted">{t('updates.check.text')}</p>
      <Switch checked={enabled} disabled={busy} onChange={(e) => toggle(e.target.checked)} label={enabled ? t('common.on') : t('common.off')} />
      <div className="update-channel">
        <label htmlFor="update-channel">{t('updates.check.channel')}</label>
        <Select id="update-channel" value={channelOf(info)} disabled={busy || !enabled} onChange={(e) => setChannel(e.target.value)}
          aria-describedby="update-channel-help" options={CHANNEL_OPTIONS.map((o) => ({ value: o.value, label: t(o.label) }))} />
      </div>
      <p id="update-channel-help" className="muted">{t(CHANNEL_HELP)}</p>
      {info && <p className="muted" role="status">{updateSummary(info, t)}</p>}
      <div className="row">
        <Button variant="ghost" onClick={refresh} disabled={busy || !enabled}>{t('updates.check.now')}</Button>
      </div>
      <div role="status" aria-live="polite">{msg && <Alert variant="error">{errText(msg)}</Alert>}</div>
    </section>
  );
}
