import React, { useEffect, useId, useReducer, useRef } from 'react';
import { api as realApi } from '../api.js';
import { initialState, isInsecure, reduce, run } from '../apikey.js';
import { errText, useI18n } from '../useI18n.js';
import Icon from './Icon.jsx';
import { Alert, Button, CopyBox } from './ui/index.js';

// Sección «API key» del menú del perfil: generar, ver siempre (completa, ajustada en varias líneas), copiar, regenerar y revocar.
// Una sola key por usuario; sirve solo para /api/hook/*. `initial`, `api` e `insecure` permiten pintar cada estado en pruebas sin red.
export default function ApiKeySection({ initial = null, api = realApi, insecure }) {
  const { t } = useI18n();
  const [s, dispatch] = useReducer(reduce, initial ? { ...initialState, ...initial } : initialState);
  const confirmBtn = useRef(null);
  const hintId = useId();
  const warnInsecure = insecure ?? (typeof window !== 'undefined' && isInsecure(window.location));

  const act = async (what) => { dispatch({ type: 'start' }); dispatch(await run(api, what)); };
  useEffect(() => { if (!initial) act('load'); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (s.confirm) confirmBtn.current?.focus(); }, [s.confirm]);

  const confirmed = () => act(s.confirm === 'revoke' ? 'revoke' : 'create');

  return (
    <section className="apikey" aria-labelledby={`${hintId}-t`}>
      <h3 id={`${hintId}-t`} className="apikey-title"><Icon name="key" />{t('profile.apikey.title')}</h3>
      <small className="muted" id={hintId}>{t('profile.apikey.hint')}</small>
      {s.error && <Alert variant="error" compact role="alert">{errText(s.error)}</Alert>}
      {!s.loaded && !s.error && <small className="muted" role="status">{t('common.loading')}</small>}
      {s.loaded && !s.exists && (
        <div className="apikey-none">
          <small className="muted">{t('profile.apikey.none')}</small>
          <Button onClick={() => act('create')} disabled={s.busy}>{t('profile.apikey.generate')}</Button>
        </div>
      )}
      {s.exists && (
        <>
          <CopyBox value={s.key} label={t('profile.apikey.field')} describedBy={hintId} />
          {warnInsecure && <Alert variant="warn" compact><Icon name="alert" /><span>{t('profile.apikey.insecure')}</span></Alert>}
          {s.confirm ? (
            <Alert variant="warn" role="alertdialog" aria-label={t(`profile.apikey.confirm.${s.confirm}.title`)}>
              <p className="apikey-confirm">{t(`profile.apikey.confirm.${s.confirm}.text`)}</p>
              <div className="apikey-actions">
                <Button ref={confirmBtn} variant="danger" onClick={confirmed} disabled={s.busy}>{t(`profile.apikey.confirm.${s.confirm}.yes`)}</Button>
                <Button variant="ghost" onClick={() => dispatch({ type: 'cancel' })} disabled={s.busy}>{t('common.cancel')}</Button>
              </div>
            </Alert>
          ) : (
            <div className="apikey-actions">
              <Button onClick={() => dispatch({ type: 'ask', what: 'regenerate' })} disabled={s.busy}>{t('profile.apikey.regenerate')}</Button>
              <Button variant="danger" onClick={() => dispatch({ type: 'ask', what: 'revoke' })} disabled={s.busy}>{t('profile.apikey.revoke')}</Button>
            </div>
          )}
        </>
      )}
    </section>
  );
}
