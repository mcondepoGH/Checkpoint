import React, { useEffect, useState } from 'react';
import { Alert, Button } from './ui/index.js';
import { useI18n } from '../useI18n.js';
import { getInstallPrompt, installHint, isDismissed, readEnv, setDismissed, subscribeInstallPrompt } from '../pwa.js';

const storage = () => { try { return window.localStorage; } catch { return null; } };

// Aviso para instalar Checkpoint como app. Solo móvil y no instalada; «Ahora no» se recuerda en localStorage.
export default function PwaInstall() {
  const { t } = useI18n();
  const [env] = useState(() => readEnv());
  const [prompt, setPrompt] = useState(getInstallPrompt);
  const [dismissed, setGone] = useState(() => isDismissed(storage()));
  useEffect(() => subscribeInstallPrompt(setPrompt), []);

  const hint = installHint({ ...env, dismissed, hasPrompt: !!prompt });
  if (hint === 'none') return null;
  const close = () => { const s = storage(); if (s) setDismissed(s); setGone(true); };
  const install = async () => {
    try { await prompt.prompt(); await prompt.userChoice; } catch { /* ignorar */ }
    setPrompt(null); // el evento solo sirve una vez
  };
  return (
    <div className="pwa-install">
      <Alert variant="info" role="region" aria-label={t('pwa.title')}>
        <strong>{t('pwa.title')}</strong>
        <p>{t(hint === 'ios' ? 'pwa.ios' : 'pwa.android')}</p>
        <div className="pwa-actions">
          {hint === 'prompt' && <Button variant="primary" onClick={install}>{t('pwa.install')}</Button>}
          <Button variant="ghost" onClick={close}>{t('pwa.dismiss')}</Button>
        </div>
      </Alert>
    </div>
  );
}
