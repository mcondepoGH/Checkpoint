import React from 'react';
import Field from './Field.jsx';
import { MAX_VERSIONS_LIMIT, NAME_HINT, NAME_MAX, VERSIONS_HINT } from '../draft.js';
import IdNote from './IdNote.jsx';
import { ON_CONFLICT_OPTIONS } from '../format.js';
import { useI18n } from '../useI18n.js';

export default function GameCard({ game, devices, errors, localError, keepError, globalMax, nameA, nameB, idA, idB, idText, renamed, onChange, onRemove }) {
  const { t } = useI18n();
  const set = (k) => (e) => onChange({ [k]: e.target.value });
  const title = game.name || t('game.new');
  // Solo dispositivos con nombre; el elegido en el otro selector no se ofrece.
  const options = (other) => devices.filter((d) => d.name && d.key !== other);
  const sel = (key, other) => (p) => (
    <select {...p} value={game[key]} onChange={set(key)}>
      <option value="">{t('game.choose')}</option>
      {options(other).map((d) => <option key={d.key} value={d.key}>{d.name}</option>)}
    </select>
  );
  const pathErr = (id) => (id ? errors[`paths.${id}`] : undefined);
  return (
    <fieldset className="card cfg-card">
      <legend className="cfg-title">{title}</legend>
      <Field label={t('game.name')} hint={t(NAME_HINT, { max: NAME_MAX })} error={localError || errors.name || errors['']}>
        {(p) => <input {...p} value={game.name} onChange={set('name')} maxLength={NAME_MAX} placeholder={t('game.namePh')} autoComplete="off" spellCheck="false" />}
      </Field>
      {errors.devices && <div className="alert error" role="alert">{errors.devices}</div>}
      <div className="two">
        <Field label={t('game.dev1')} error={errors['devices.0']}>{sel('a', game.b)}</Field>
        <Field label={t('game.dev2')} error={errors['devices.1']}>{sel('b', game.a)}</Field>
      </div>
      {game.a && (
        <Field label={t('game.pathOn', { device: nameA })} error={pathErr(idA)}>
          {(p) => <input {...p} value={game.pathA} onChange={set('pathA')} autoComplete="off" spellCheck="false" />}
        </Field>
      )}
      {game.b && (
        <Field label={t('game.pathOn', { device: nameB })} error={pathErr(idB)}>
          {(p) => <input {...p} value={game.pathB} onChange={set('pathB')} autoComplete="off" spellCheck="false" />}
        </Field>
      )}
      <div className="two">
        <Field label={t('game.process')} hint={t('game.processHint')} error={errors.process}>
          {(p) => <input {...p} value={game.process} onChange={set('process')} placeholder={t('game.processPh')} autoComplete="off" spellCheck="false" />}
        </Field>
        <Field label={t('game.keep')} hint={t('game.keepHint', { max: globalMax, hint: t(VERSIONS_HINT) })} error={keepError || errors.keep_versions}>
          {(p) => <input {...p} type="number" inputMode="numeric" min="0" max={MAX_VERSIONS_LIMIT} step="1" value={game.keep} onChange={set('keep')} placeholder={String(globalMax)} />}
        </Field>
      </div>
      <Field label={t('game.onConflict')} hint={t('game.onConflictHint')} error={errors.on_conflict}>
        {(p) => (
          <select {...p} value={game.onConflict || ''} onChange={set('onConflict')}>
            <option value="">{t('game.useGlobal')}</option>
            {ON_CONFLICT_OPTIONS.map(([v, l]) => <option key={v} value={v}>{t(l)}</option>)}
          </select>
        )}
      </Field>
      <IdNote id={idText} isNew={!game.id} renamed={renamed} />
      <div className="row end">
        <button type="button" className="btn danger" onClick={onRemove} aria-label={t('game.deleteAria', { title })}>{t('common.delete')}</button>
      </div>
    </fieldset>
  );
}
