import React, { useEffect, useId, useReducer, useRef, useState } from 'react';
import { api as realApi } from '#src/lib/api.js';
import { initialState, isInsecure, reduce, run } from '#src/lib/apikey.js';
import { errText, useI18n } from '#src/hooks/useI18n.js';
import Icon from '#src/components/ui/Icon.jsx';
import { Alert, Button, CopyBox } from '#src/components/ui/index.js';

// Sección «API key» del menú del perfil, plegable y cerrada por defecto (`defaultOpen`); el contenido sigue montado (solo `hidden`), así que el estado y la carga no se pierden al plegar. Generar, ver siempre (completa, ajustada en varias líneas), copiar, regenerar y revocar.
// Una sola key por usuario; sirve solo para /api/hook/*. `initial`, `api` e `insecure` permiten pintar cada estado en pruebas sin red.
export default function ApiKeySection({ initial = null, api = realApi, insecure, defaultOpen = false }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(defaultOpen);
  const bodyId = useId();
  const [s, dispatch] = useReducer(reduce, initial ? { ...initialState, ...initial } : initialState);
  const confirmBtn = useRef(null);
  const hintId = useId();
  const warnInsecure = insecure ?? (typeof window !== 'undefined' && isInsecure(window.location));

  const act = async (what) => {
    dispatch({ type: 'start' });
    dispatch(await run(api, what));
  };
  useEffect(() => {
    if (!initial) act('load');
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (s.confirm) confirmBtn.current?.focus();
  }, [s.confirm]);

  const confirmed = () => act(s.confirm === 'revoke' ? 'revoke' : 'create');

  return (
    <section className="apikey" aria-labelledby={`${hintId}-t`}>
      <h3 id={`${hintId}-t`} className="apikey-title">
        <Button
          variant="ghost"
          className="profile-row apikey-toggle"
          aria-expanded={open}
          aria-controls={bodyId}
          onClick={() => setOpen((o) => !o)}
        >
          <Icon name="key" />
          <span className="profile-row-label">{t('profile.apikey.title')}</span>
          <Icon name="chevron" />
        </Button>
      </h3>
      <div id={bodyId} className="apikey-body" hidden={!open}>
        <small className="muted" id={hintId}>
          {t('profile.apikey.hint')}
        </small>
        {s.error && (
          <Alert variant="error" compact role="alert">
            {errText(s.error)}
          </Alert>
        )}
        {!s.loaded && !s.error && (
          <small className="muted" role="status">
            {t('common.loading')}
          </small>
        )}
        {s.loaded && !s.exists && (
          <div className="apikey-none">
            <small className="muted">{t('profile.apikey.none')}</small>
            <Button onClick={() => act('create')} disabled={s.busy}>
              {t('profile.apikey.generate')}
            </Button>
          </div>
        )}
        {s.exists && (
          <>
            <CopyBox value={s.key} label={t('profile.apikey.field')} what={t('profile.apikey.copyWhat')} describedBy={hintId} />
            {warnInsecure && (
              <Alert variant="warn" compact>
                <Icon name="alert" />
                <span>{t('profile.apikey.insecure')}</span>
              </Alert>
            )}
            {s.confirm ? (
              <Alert variant="warn" role="alertdialog" aria-label={t(`profile.apikey.confirm.${s.confirm}.title`)}>
                <p className="apikey-confirm">{t(`profile.apikey.confirm.${s.confirm}.text`)}</p>
                <div className="apikey-actions">
                  <Button ref={confirmBtn} variant="danger" onClick={confirmed} disabled={s.busy}>
                    {t(`profile.apikey.confirm.${s.confirm}.yes`)}
                  </Button>
                  <Button variant="ghost" onClick={() => dispatch({ type: 'cancel' })} disabled={s.busy}>
                    {t('common.cancel')}
                  </Button>
                </div>
              </Alert>
            ) : (
              <div className="apikey-actions">
                <Button onClick={() => dispatch({ type: 'ask', what: 'regenerate' })} disabled={s.busy}>
                  {t('profile.apikey.regenerate')}
                </Button>
                <Button variant="danger" onClick={() => dispatch({ type: 'ask', what: 'revoke' })} disabled={s.busy}>
                  {t('profile.apikey.revoke')}
                </Button>
              </div>
            )}
          </>
        )}
      </div>
    </section>
  );
}
