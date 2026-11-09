import React, { useId } from 'react';
import Field from './Field.jsx';
import { LOCAL_DOCKER_MSG, LOCAL_HELP, LOCAL_LABEL, NAME_HINT, NAME_MAX, OS_OPTIONS, localPatch } from '../draft.js';
import IdNote from './IdNote.jsx';
import { fieldErrorText } from '../errors.js';
import { errText, useI18n } from '../useI18n.js';
import { Alert, Button, Checkbox, Input, Select } from './ui/index.js';

// `runtime` ('docker' | 'native') y `platform` vienen de /api/config. «Este equipo» solo se ofrece en modo nativo.
// Resultado de «Probar conexión»/«Comprobar carpeta»: con varias carpetas, una línea por ruta (cada una con su code si lo hay).
// Si se guardó una host key nueva (`first_use`), se añade el aviso: « (…)» tras un OK y « […]» tras un fallo.
const firstUse = (test, t) => (test.first_use ? (test.ok ? ` (${t('err.bootstrap.first_use')})` : ` [${t('err.bootstrap.first_use')}]`) : '');
const testText = (test, t) => (test.results ? test.results.map((r) => `${r.path}: ${errText(r)}`).join('\n') : errText(test) + firstUse(test, t));

export default function DeviceCard({ dev, errors, localError, localFlagError, canLocal, runtime, platform, test, idText, renamed, onChange, onTest, onRemove }) {
  const { t } = useI18n();
  const set = (k) => (e) => onChange({ [k]: e.target.value });
  const descId = useId();
  const title = dev.name || t('device.new');
  return (
    <fieldset className="card cfg-card">
      <legend className="cfg-title">{title}</legend>
      <Field label={t('game.name')} hint={t(NAME_HINT, { max: NAME_MAX })} error={localError || errors.name || errors['']}>
        {(p) => <Input {...p} value={dev.name} onChange={set('name')} maxLength={NAME_MAX} placeholder={t('device.namePh')} />}
      </Field>
      {(canLocal || dev.local) && runtime !== 'docker' && (
        <div className="local-opt">
          <Checkbox checked={dev.local} aria-describedby={`${descId}-local`} aria-invalid={localFlagError || errors.local ? true : undefined}
            onChange={(e) => onChange(localPatch(e.target.checked, platform))} label={t(LOCAL_LABEL)} />
          <small id={`${descId}-local`} className="muted">{t(LOCAL_HELP)}</small>
        </div>
      )}
      {dev.local && runtime === 'docker' && <Alert variant="error" role="alert">{errText(LOCAL_DOCKER_MSG)}.</Alert>}
      {dev.local && runtime !== 'docker' && (localFlagError || errors.local) && (
        <Alert variant="error" role="alert">{fieldErrorText(localFlagError || errors.local, t)}</Alert>
      )}
      {dev.local ? (
        <Field label={t('device.os')} hint={t('device.osHint')} error={errors.os}>
          {(p) => (
            <Select {...p} value={dev.os} onChange={set('os')} options={OS_OPTIONS.map(([v, l]) => ({ value: v, label: l }))} />
          )}
        </Field>
      ) : (
        <>
          <div className="two">
            <Field label={t('device.host')} error={errors.host}>
              {(p) => <Input {...p} value={dev.host} onChange={set('host')} />}
            </Field>
            <Field label={t('device.port')} error={errors.port}>
              {(p) => <Input {...p} type="number" inputMode="numeric" min="1" max="65535" value={dev.port} onChange={set('port')} />}
            </Field>
          </div>
          <div className="two">
            <Field label={t('device.user')} error={errors.user}>
              {(p) => <Input {...p} value={dev.user} onChange={set('user')} />}
            </Field>
            <Field label={t('device.os')} error={errors.os}>
              {(p) => (
                <Select {...p} value={dev.os} onChange={set('os')} options={OS_OPTIONS.map(([v, l]) => ({ value: v, label: l }))} />
              )}
            </Field>
          </div>
        </>
      )}
      <IdNote id={idText} isNew={!dev.id} renamed={renamed} />
      <div role="status" aria-live="polite">
        {test && !test.busy && <Alert variant={test.ok ? 'ok' : 'error'} style={{ whiteSpace: 'pre-line' }}>{testText(test, t)}</Alert>}
      </div>
      <div className="row">
        <Button disabled={test?.busy} onClick={onTest}>
          {test?.busy ? (dev.local ? t('device.checking') : t('device.testing')) : (dev.local ? t('device.checkFolder') : t('device.test'))}
        </Button>
        <span className="spacer" />
        <Button variant="danger" onClick={onRemove} aria-label={t('device.deleteAria', { title })}>{t('common.delete')}</Button>
      </div>
    </fieldset>
  );
}
