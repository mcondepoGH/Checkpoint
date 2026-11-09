import React, { useEffect, useId, useReducer, useRef } from 'react';
import { api as realApi } from '../api.js';
import { initialState, isInsecure, reduce, run } from '../apikey.js';
import { copyText } from '../clipboard.js';
import { errText, useI18n } from '../useI18n.js';
import { Alert, Button, Input } from './ui/index.js';

// Sección «API key» del menú del perfil: generar, ver siempre, copiar, regenerar y revocar. Una sola key por usuario;
// sirve solo para /api/hook/*. `initial` y `api` permiten pintar cada estado en pruebas sin red.
export default function ApiKeySection({ initial = null, api = realApi }) {
  const { t } = useI18n();
  const [s, dispatch] = useReducer(reduce, initial ? { ...initialState, ...initial } : initialState);
  const field = useRef(null);
  const confirmBtn = useRef(null);
  const copyTimer = useRef(null);
  const hintId = useId();
  const warnInsecure = typeof window !== 'undefined' && isInsecure(window.location);

  const act = async (what) => { dispatch({ type: 'start' }); dispatch(await run(api, what)); };
  useEffect(() => { if (!initial) act('load'); return () => clearTimeout(copyTimer.current); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (s.confirm) confirmBtn.current?.focus(); }, [s.confirm]);

  const copy = async () => {
    const ok = await copyText(s.key, field.current);
    dispatch({ type: 'copied', ok });
    clearTimeout(copyTimer.current);
    if (ok) copyTimer.current = setTimeout(() => dispatch({ type: 'copied', ok: false }), 2000);
  };
  const confirmed = () => act(s.confirm === 'revoke' ? 'revoke' : 'create');

  return (
    <section className="apikey" aria-labelledby={`${hintId}-t`}>
      <h3 id={`${hintId}-t`} className="apikey-title">{t('profile.apikey.title')}</h3>
      <small className="muted" id={hintId}>{t('profile.apikey.hint')}</small>
      {s.error && <Alert variant="error" role="alert">{errText(s.error)}</Alert>}
      {!s.loaded && !s.error && <small className="muted" role="status">{t('common.loading')}</small>}
      {s.loaded && !s.exists && (
        <div className="apikey-actions">
          <small className="muted">{t('profile.apikey.none')}</small>
          <Button onClick={() => act('create')} disabled={s.busy}>{t('profile.apikey.generate')}</Button>
        </div>
      )}
      {s.exists && (
        <>
          <Input ref={field} readOnly className="apikey-field" value={s.key} aria-label={t('profile.apikey.field')} aria-describedby={hintId}
            onFocus={(e) => e.target.select()} />
          {warnInsecure && <small className="muted">{t('profile.apikey.insecure')}</small>}
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
              <Button onClick={copy} aria-live="polite">{s.copied ? t('common.copied') : t('common.copy')}</Button>
              <Button onClick={() => dispatch({ type: 'ask', what: 'regenerate' })} disabled={s.busy}>{t('profile.apikey.regenerate')}</Button>
              <Button variant="ghost" onClick={() => dispatch({ type: 'ask', what: 'revoke' })} disabled={s.busy}>{t('profile.apikey.revoke')}</Button>
            </div>
          )}
        </>
      )}
    </section>
  );
}
