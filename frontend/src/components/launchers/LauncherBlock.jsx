import React, { useEffect, useId, useState } from 'react';
import { api as realApi } from '#src/lib/api.js';
import { getApiKey } from '#src/lib/api/profile.js';
import { hookStatus } from '#src/lib/api/sync.js';
import { isInsecure } from '#src/lib/apikey.js';
import { RESULT_TEXT, resultText } from '#src/lib/format.js';
import { LAUNCHERS, ago, commandsFor, loadHubUrl, normalizeHubUrl, saveHubUrl } from './launchers.js';
import { errText, rich, useI18n } from '#src/hooks/useI18n.js';
import Field from '#src/components/ui/Field.jsx';
import Icon from '#src/components/ui/Icon.jsx';
import { Alert, Badge, CopyBox, Input, Select, Tabs } from '#src/components/ui/index.js';

const POLL_MS = 15000;
const storage = () => {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
};
const defaultUrl = () => (typeof window !== 'undefined' ? window.location.origin : '');

// Subpestaña «Lanzadores»: una fila por juego guardado con los comandos de la plataforma elegida (pestañas Steam/Lutris/Heroic/Windows,
// comunes a todas las filas) listos para copiar con la API key del usuario, más el último aviso por dispositivo de ese juego.
// `games`: [{ sel (clave única), id, name, process, enabled (false = desactivado), devices: [{ id, name }] }] (`id` vacío = sin guardar: su fila no da comandos).
// `active`: panel abierto (solo entonces pide la key y consulta el estado de cada juego, cada 15 s).
// `defaultHub`: URL por defecto (si no, el origen de la página). `initial` ({ key, loaded, status: { [idJuego]: estado }, error }) y `api`
// permiten pintar cada estado en pruebas sin red; `now` fija la hora.
export default function LauncherBlock({ games, active, initial = null, api = realApi, now, defaultHub }) {
  const { t } = useI18n();
  const uid = useId();
  const [keyState, setKeyState] = useState(
    initial
      ? { loaded: !!initial.loaded, key: initial.key ?? null, error: initial.error ?? null }
      : { loaded: false, key: null, error: null },
  );
  const [hubUrl, setHubUrl] = useState(() => loadHubUrl(storage(), defaultHub ?? defaultUrl()));
  const [tab, setTab] = useState(LAUNCHERS[0]);

  useEffect(() => {
    if (!active || initial) return undefined;
    let alive = true;
    getApiKey(api)
      .then((r) => alive && setKeyState({ loaded: true, key: r.exists ? r.key : null, error: null }))
      .catch((error) => alive && setKeyState({ loaded: true, key: null, error }));
    return () => {
      alive = false;
    };
  }, [active]); // eslint-disable-line react-hooks/exhaustive-deps

  const onUrl = (e) => {
    setHubUrl(e.target.value);
    const n = normalizeHubUrl(e.target.value);
    if (n) saveHubUrl(storage(), n);
  };
  const url = normalizeHubUrl(hubUrl);
  const insecure = url ? isInsecure(new URL(url)) : false;
  const hintId = `${uid}-hint`;

  let body;
  if (!games.length) body = <Alert variant="info">{t('launcher.noGames')}</Alert>;
  else if (keyState.error)
    body = (
      <Alert variant="error" compact role="alert">
        {errText(keyState.error)}
      </Alert>
    );
  else if (!keyState.loaded)
    body = (
      <small className="muted" role="status">
        {t('common.loading')}
      </small>
    );
  else if (!keyState.key) body = <Alert variant="info">{t('launcher.noKey')}</Alert>;
  else {
    body = (
      <>
        <Field label={t('launcher.hubUrl')} hint={t('launcher.hubUrlHint')} error={url ? undefined : t('launcher.invalidUrl')}>
          {(p) => <Input {...p} value={hubUrl} onChange={onUrl} inputMode="url" />}
        </Field>
        {insecure && (
          <Alert variant="warn" compact>
            <Icon name="alert" />
            <span>{t('profile.apikey.insecure')}</span>
          </Alert>
        )}
        <Tabs
          label={t('launcher.tabsAria')}
          value={tab}
          onChange={setTab}
          tabs={LAUNCHERS.map((id) => ({ id, label: t(`launcher.tab.${id}`) }))}
        >
          <small className="muted launcher-note" id={hintId}>
            {t(`launcher.where.${tab}`)} {t('launcher.closeNote')}
          </small>
          <ul className="launcher-rows">
            {games.map((g) => (
              <GameRow
                key={g.sel ?? g.id}
                game={g}
                tab={tab}
                url={url}
                apiKey={keyState.key}
                hintId={hintId}
                active={active}
                initial={initial}
                api={api}
                now={now}
              />
            ))}
          </ul>
        </Tabs>
      </>
    );
  }
  return (
    <div className="launcher">
      <small className="muted">{t('launcher.hint')}</small>
      {body}
    </div>
  );
}

// Una fila: nombre del juego, dispositivo (si tiene más de uno), comandos de la plataforma elegida y último aviso por dispositivo.
function GameRow({ game, tab, url, apiKey, hintId, active, initial, api, now }) {
  const { t, locale } = useI18n();
  const uid = useId();
  const devices = game.devices || [];
  const gameId = game.id || '';
  const [device, setDevice] = useState(devices[0]?.id || '');
  const [status, setStatus] = useState(initial?.status?.[gameId] ?? null);
  const devKey = devices.map((d) => d.id).join('|');
  const name = game.name || t('common.unnamed');

  useEffect(() => {
    if (!devices.some((d) => d.id === device)) setDevice(devices[0]?.id || '');
  }, [devKey]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!active || initial || !gameId) return undefined;
    let alive = true;
    const load = () => {
      if (typeof document !== 'undefined' && document.hidden) return;
      hookStatus(gameId, api)
        .then((r) => alive && setStatus(r))
        .catch(() => alive && setStatus(null));
    };
    load();
    const timer = setInterval(load, POLL_MS);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [active, gameId]); // eslint-disable-line react-hooks/exhaustive-deps

  const when = now || new Date();
  const lines = devices
    .map((d) => {
      const s = status?.devices?.find((x) => x.device === d.id);
      if (!s) return null;
      const w = s.watching ? ` · ${t(`launcher.watch.${s.watching.state}`)}` : '';
      if (!s.last)
        return (
          <li key={d.id}>
            {t('launcher.lastNone', { device: d.name })}
            {w}
          </li>
        );
      const trigger = t(`autolog.trigger.${s.last.trigger}`);
      const outcome = RESULT_TEXT[s.last.outcome] ? resultText(s.last.outcome, t) : String(s.last.outcome ?? '—');
      const why = s.last.code ? errText(s.last) : ''; // motivo si el último aviso fue un descarte u omisión (err.hook.*)
      return (
        <li key={d.id}>
          {t('launcher.last', { device: d.name, trigger, ago: ago(s.last.at, when, locale), outcome })}
          {why ? ` · ${why}` : ''}
          {w}
        </li>
      );
    })
    .filter(Boolean);

  let cmdsView = null;
  if (!gameId) cmdsView = <Alert variant="info">{t('launcher.saveFirst')}</Alert>;
  else if (!devices.length) cmdsView = <Alert variant="info">{t('launcher.noDevices')}</Alert>;
  else {
    const cmds = url ? commandsFor(tab, { url, key: apiKey, game: gameId, device }) : null;
    const platform = t(`launcher.tab.${tab}`);
    cmdsView = (
      <>
        {devices.length > 1 && (
          <Field label={t('launcher.device')}>
            {(p) => (
              <Select
                {...p}
                value={device}
                onChange={(e) => setDevice(e.target.value)}
                options={devices.map((d) => ({ value: d.id, label: d.name }))}
              />
            )}
          </Field>
        )}
        {cmds &&
          cmds.map((c) => (
            <div key={`${tab}-${c.id}`} className="launcher-cmd">
              {cmds.length > 1 && <span className="launcher-cmd-title">{t(`launcher.cmd.${c.id}`)}</span>}
              <CopyBox
                value={c.text}
                label={t('launcher.cmdAria', { launcher: platform, game: name })}
                describedBy={hintId}
                what={t(cmds.length > 1 ? 'launcher.copyWhatCmd' : 'launcher.copyWhat', {
                  launcher: platform,
                  cmd: t(`launcher.cmd.${c.id}`),
                  game: name,
                })}
              />
            </div>
          ))}
        {!game.process?.trim() && (
          <Alert variant="warn" compact>
            <Icon name="alert" />
            <span>{rich(t('launcher.noProcess'))}</span>
          </Alert>
        )}
        {lines.length > 0 && (
          <div>
            <span className="launcher-cmd-title">{t('launcher.lastTitle')}</span>
            <ul className="launcher-last" aria-live="polite">
              {lines}
            </ul>
          </div>
        )}
      </>
    );
  }
  return (
    <li className="launcher-row" aria-labelledby={`${uid}-n`}>
      <div className="launcher-row-head">
        <strong id={`${uid}-n`}>{name}</strong>
        {game.enabled === false && <Badge>{t('game.disabledTag')}</Badge>}
      </div>
      {game.enabled === false && (
        <Alert variant="info" compact>
          {t('launcher.disabledNote')}
        </Alert>
      )}
      {cmdsView}
    </li>
  );
}
