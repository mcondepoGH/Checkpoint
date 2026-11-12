import React from 'react';
import Field from '#src/components/ui/Field.jsx';
import EmptyState from '#src/components/ui/EmptyState.jsx';
import Icon from '#src/components/ui/Icon.jsx';
import DeviceCard from '#src/components/config/DeviceCard.jsx';
import GameCard from '#src/components/config/GameCard.jsx';
import PublicKey from '#src/components/keyhelp/PublicKey.jsx';
import { Button, Input } from '#src/components/ui/index.js';
import {
  MAX_VERSIONS_LIMIT,
  VERSIONS_HINT,
  blankDevice,
  blankGame,
  canOfferLocal,
  deviceId,
  idOf,
  nameOf,
  renamed,
} from '#src/components/config/draft.js';
import { useI18n } from '#src/hooks/useI18n.js';

// Subpestaña «Biblioteca» de Configuración: clave SSH, versiones guardadas, dispositivos y juegos, con la barra de guardar.
// Es la única que edita el borrador de config.yaml: la barra vive aquí. `bar` agrupa el estado y las acciones de la barra.
export default function Library({
  draft,
  setDraft,
  patch,
  errors,
  local,
  fe,
  devErrs,
  gameErrs,
  runtime,
  platform,
  tests,
  onTest,
  onDelDevice,
  bar,
}) {
  const { t } = useI18n();
  const noNamed = draft.devices.filter((d) => d.name).length < 1;
  return (
    <>
      {/* La clave SSH solo importa si hay (o puede haber) dispositivos remotos. */}
      {(draft.devices.length === 0 || draft.devices.some((d) => !d.local)) && <PublicKey />}

      <fieldset className="card cfg-card">
        <legend className="cfg-title">{t('settings.versions.legend')}</legend>
        <Field label={t('settings.versions.max')} hint={t(VERSIONS_HINT)} error={local.maxVersions || fe(errors.max_versions)}>
          {(p) => (
            <Input
              {...p}
              type="number"
              inputMode="numeric"
              min="0"
              max={MAX_VERSIONS_LIMIT}
              step="1"
              value={draft.maxVersions}
              onChange={(e) => setDraft((d) => ({ ...d, maxVersions: e.target.value }))}
            />
          )}
        </Field>
      </fieldset>

      <div className="row between section-head">
        <h3>{t('settings.devices')}</h3>
        <Button onClick={() => setDraft((d) => ({ ...d, devices: [...d.devices, blankDevice()] }))}>{t('settings.addDevice')}</Button>
      </div>
      <div className="grid">
        {draft.devices.map((d) => (
          <DeviceCard
            key={d.key}
            dev={d}
            errors={devErrs(d)}
            localError={local[d.key]}
            localFlagError={local[`local-${d.key}`]}
            canLocal={canOfferLocal(draft, runtime, d.key)}
            runtime={runtime}
            platform={platform}
            test={tests[d.key]}
            idText={idOf(d, 'dispositivo')}
            renamed={renamed(d)}
            onChange={(p) => patch('devices', d.key, p)}
            onTest={() => onTest(d)}
            onRemove={() => onDelDevice(d)}
          />
        ))}
      </div>
      {draft.devices.length === 0 && (
        <EmptyState
          icon="💻"
          title={t('settings.noDevices.title')}
          text={t('settings.noDevices.text')}
          action={
            <Button variant="primary" onClick={() => setDraft((d) => ({ ...d, devices: [...d.devices, blankDevice()] }))}>
              {t('settings.addDevice')}
            </Button>
          }
        />
      )}

      <div className="row between section-head">
        <h3>{t('settings.games')}</h3>
        <Button disabled={noNamed} onClick={() => setDraft((d) => ({ ...d, games: [...d.games, blankGame()] }))}>
          {t('settings.addGame')}
        </Button>
      </div>
      {noNamed && <p className="muted">{t('settings.needOne')}</p>}
      <div className="grid">
        {draft.games.map((g) => (
          <GameCard
            key={g.key}
            game={g}
            devices={draft.devices}
            errors={gameErrs(g)}
            localError={local[g.key]}
            keepError={local[`keep-${g.key}`]}
            globalMax={draft.maxVersions}
            nameA={nameOf(draft, g.a)}
            nameB={nameOf(draft, g.b)}
            idA={deviceId(draft, g.a)}
            idB={deviceId(draft, g.b)}
            idText={idOf(g, 'juego')}
            renamed={renamed(g)}
            onChange={(p) => patch('games', g.key, p)}
            onRemove={() => setDraft((d) => ({ ...d, games: d.games.filter((x) => x.key !== g.key) }))}
          />
        ))}
      </div>

      <div className="actionbar" role="group" aria-label={t('settings.bar.aria')}>
        {bar.hasErrors && !bar.validating ? (
          <button
            type="button"
            className="ab-chip error"
            onClick={bar.jumpToError}
            aria-label={t('settings.bar.errorsAria', { count: bar.errorCount || 1 })}
          >
            <Icon name="alert" />
            <b>{bar.errorCount || 1}</b>
            <span className="ab-long">{t('settings.bar.errors')}</span>
          </button>
        ) : (
          <span className={`ab-chip${bar.dirty ? ' dirty' : ''}`} aria-live="polite">
            {bar.validating ? (
              t('settings.bar.validating')
            ) : bar.dirty ? (
              <>
                <span className="ab-long">{t('settings.bar.dirty')}</span>
                <span className="ab-short">{t('settings.bar.dirtyShort')}</span>
              </>
            ) : (
              t('settings.bar.clean')
            )}
          </span>
        )}
        <span className="spacer" />
        <Button
          variant="ghost"
          className="ab-tool"
          title={t('settings.bar.backups')}
          aria-label={t('settings.bar.backups')}
          onClick={bar.onBackups}
        >
          <Icon name="history" />
          <span className="lbl">{t('settings.bar.backups')}</span>
        </Button>
        <Button
          variant="ghost"
          className="ab-tool"
          title={t('settings.bar.yaml')}
          aria-label={t('settings.bar.yaml')}
          onClick={bar.onYaml}
          disabled={bar.hasErrors}
        >
          <Icon name="code" />
          <span className="lbl">{t('settings.bar.yaml')}</span>
        </Button>
        <Button
          className="ab-tool"
          title={t('settings.bar.discardTitle')}
          aria-label={t('settings.bar.discardTitle')}
          disabled={!bar.dirty}
          onClick={bar.onDiscard}
        >
          <Icon name="undo" />
          <span className="lbl">{t('settings.bar.discard')}</span>
        </Button>
        <Button variant="primary" disabled={!bar.canSave} onClick={bar.onSave}>
          {t('settings.bar.save')}
        </Button>
      </div>
    </>
  );
}
