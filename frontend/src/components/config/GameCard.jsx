import React, { useEffect, useId, useState } from 'react';
import Field from '#src/components/ui/Field.jsx';
import { MAX_VERSIONS_LIMIT, NAME_HINT, NAME_MAX, VERSIONS_HINT } from './draft.js';
import IdNote from './IdNote.jsx';
import { ON_CONFLICT_OPTIONS } from '#src/lib/format.js';
import { useI18n } from '#src/hooks/useI18n.js';
import { Alert, Button, Input, Select, Switch } from '#src/components/ui/index.js';

export default function GameCard({ game, devices, errors, localError, keepError, globalMax, nameA, nameB, idA, idB, idText, renamed, onChange, onRemove, onShowLaunchers }) {
  const { t } = useI18n();
  // Campos secundarios (proceso, versiones, conflicto, id) tras «Mostrar más»: la tarjeta arranca siempre plegada, tengan o no valor propio.
  // Solo se despliega sola si aparece un error de validación en esos campos (si no, quedaría invisible). Después puede plegarlos.
  const extraId = useId();
  const extraErr = Boolean(errors.process || errors.keep_versions || errors.on_conflict || keepError);
  const [more, setMore] = useState(extraErr);
  useEffect(() => { if (extraErr) setMore(true); }, [extraErr]);
  const set = (k) => (e) => onChange({ [k]: e.target.value });
  const title = game.name || t('game.new');
  // Solo dispositivos con nombre; el elegido en el otro selector no se ofrece.
  const options = (other) => devices.filter((d) => d.name && d.key !== other);
  const sel = (key, other, placeholder) => (p) => (
    <Select {...p} value={game[key]} onChange={set(key)} placeholder={placeholder}
      options={options(other).map((d) => ({ value: d.key, label: d.name }))} />
  );
  const pathErr = (id) => (id ? errors[`paths.${id}`] : undefined);
  return (
    <fieldset className={game.enabled === false ? 'card cfg-card cfg-card-disabled' : 'card cfg-card'}>
      <legend className="cfg-title">{title}{game.enabled === false && <span className="cfg-tag">{t('game.disabledTag')}</span>}</legend>
      <Field label={t('game.name')} hint={t(NAME_HINT, { max: NAME_MAX })} error={localError || errors.name || errors['']}>
        {(p) => <Input {...p} value={game.name} onChange={set('name')} maxLength={NAME_MAX} placeholder={t('game.namePh')} />}
      </Field>
      <div className="game-enabled">
        <Switch checked={game.enabled !== false} aria-describedby={`${extraId}-enabled`}
          onChange={(e) => onChange({ enabled: e.target.checked })} label={t('game.enabled')} />
        <small id={`${extraId}-enabled`} className="muted">{t('game.enabledHelp')}</small>
      </div>
      {errors.devices && <Alert variant="error" role="alert">{errors.devices}</Alert>}
      <div className="two">
        <Field label={t('game.dev1')} error={errors['devices.0']}>{sel('a', game.b, t('game.choose'))}</Field>
        <Field label={t('game.dev2')} error={errors['devices.1']}>{sel('b', game.a, t('game.none'))}</Field>
      </div>
      {!game.b && <small className="muted game-solo-hint">{t('game.soloHint')}</small>}
      {game.a && (
        <Field label={t('game.pathOn', { device: nameA })} error={pathErr(idA)}>
          {(p) => <Input {...p} value={game.pathA} onChange={set('pathA')} />}
        </Field>
      )}
      {game.b && (
        <Field label={t('game.pathOn', { device: nameB })} error={pathErr(idB)}>
          {(p) => <Input {...p} value={game.pathB} onChange={set('pathB')} />}
        </Field>
      )}
      <div id={extraId} className="cfg-more" hidden={!more}>
        <div className="two">
          <Field label={t('game.process')} hint={t('game.processHint')} error={errors.process}>
            {(p) => <Input {...p} value={game.process} onChange={set('process')} placeholder={t('game.processPh')} />}
          </Field>
          <Field label={t('game.keep')} hint={t('game.keepHint', { max: globalMax, hint: t(VERSIONS_HINT) })} error={keepError || errors.keep_versions}>
            {(p) => <Input {...p} type="number" inputMode="numeric" min="0" max={MAX_VERSIONS_LIMIT} step="1" value={game.keep} onChange={set('keep')} placeholder={String(globalMax)} />}
          </Field>
        </div>
        <Field label={t('game.onConflict')} hint={t('game.onConflictHint')} error={errors.on_conflict}>
          {(p) => (
            <Select {...p} value={game.onConflict || ''} onChange={set('onConflict')} placeholder={t('game.useGlobal')}
              options={ON_CONFLICT_OPTIONS.map(([v, l]) => ({ value: v, label: t(l) }))} />
          )}
        </Field>
        <IdNote id={idText} isNew={!game.id} renamed={renamed} />
      </div>
      <div className="row between">
        <Button variant="ghost" onClick={() => setMore((m) => !m)} aria-expanded={more} aria-controls={extraId}>{t(more ? 'game.showLess' : 'game.showMore')}</Button>
        {onShowLaunchers && game.id && <Button variant="ghost" onClick={onShowLaunchers} aria-label={t('game.launchersAria', { title })}>{t('game.launchers')}</Button>}
        <Button variant="danger" onClick={onRemove} aria-label={t('game.deleteAria', { title })}>{t('common.delete')}</Button>
      </div>
    </fieldset>
  );
}
