import React, { useEffect, useId, useState } from 'react';
import { api as realApi } from '../api.js';
import { isInsecure } from '../apikey.js';
import { RESULT_TEXT, resultText } from '../format.js';
import { LAUNCHERS, ago, commandsFor, loadHubUrl, normalizeHubUrl, saveHubUrl } from '../launchers.js';
import { errText, rich, useI18n } from '../useI18n.js';
import Field from './Field.jsx';
import Icon from './Icon.jsx';
import { Alert, CopyBox, Input, Select, Tabs } from './ui/index.js';

const POLL_MS = 15000;
const storage = () => { try { return window.localStorage; } catch { return null; } };
const defaultUrl = () => (typeof window !== 'undefined' ? window.location.origin : '');

// Contenido de la sección «Lanzadores»: un solo panel para todos los juegos. Selector de juego, dispositivo, URL del hub, comandos
// listos para copiar (con la API key del usuario) y último aviso por dispositivo del juego elegido.
// `games`: [{ sel, id, name, process, devices: [{ id, name }] }] (`sel` identifica el juego en el selector; `id` vacío = sin guardar).
// `selected`/`onSelect`: juego elegido (controlado por quien lo recuerda). `active`: panel desplegado (solo entonces pide la key y consulta el estado, cada 15 s).
// `defaultHub`: URL por defecto (si no, el origen de la página). `initial` ({ key, loaded, status, error }) y `api` permiten pintar cada estado en pruebas sin red; `now` fija la hora.
export default function LauncherBlock({ games, selected, onSelect, active, initial = null, api = realApi, now, defaultHub }) {
  const { t, locale } = useI18n();
  const uid = useId();
  const [keyState, setKeyState] = useState(initial ? { loaded: !!initial.loaded, key: initial.key ?? null, error: initial.error ?? null } : { loaded: false, key: null, error: null });
  const [status, setStatus] = useState(initial?.status ?? null);
  const [hubUrl, setHubUrl] = useState(() => loadHubUrl(storage(), defaultHub ?? defaultUrl()));
  const game = games.find((g) => g.sel === selected) || games[0] || null;
  const devices = game?.devices || [];
  const [device, setDevice] = useState(devices[0]?.id || '');
  const [tab, setTab] = useState(LAUNCHERS[0]);
  const gameId = game?.id || '';
  const devKey = devices.map((d) => d.id).join('|');

  useEffect(() => { if (!devices.some((d) => d.id === device)) setDevice(devices[0]?.id || ''); }, [devKey]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!active || initial) return undefined;
    let alive = true;
    api('/api/profile/apikey').then((r) => alive && setKeyState({ loaded: true, key: r.exists ? r.key : null, error: null }))
      .catch((error) => alive && setKeyState({ loaded: true, key: null, error }));
    return () => { alive = false; };
  }, [active]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!active || initial || !gameId) return undefined;
    let alive = true;
    const load = () => {
      if (typeof document !== 'undefined' && document.hidden) return;
      api(`/api/games/${encodeURIComponent(gameId)}/hook-status`).then((r) => alive && setStatus(r)).catch(() => alive && setStatus(null));
    };
    load();
    const timer = setInterval(load, POLL_MS);
    return () => { alive = false; clearInterval(timer); };
  }, [active, gameId]); // eslint-disable-line react-hooks/exhaustive-deps

  const onUrl = (e) => { setHubUrl(e.target.value); const n = normalizeHubUrl(e.target.value); if (n) saveHubUrl(storage(), n); };
  const url = normalizeHubUrl(hubUrl);
  const insecure = url ? isInsecure(new URL(url)) : false;
  const hintId = `${uid}-hint`;
  const when = now || new Date();

  const lines = devices.map((d) => {
    const s = status?.devices?.find((x) => x.device === d.id);
    if (!s) return null;
    const w = s.watching ? ` · ${t(`launcher.watch.${s.watching.state}`)}` : '';
    if (!s.last) return <li key={d.id}>{t('launcher.lastNone', { device: d.name })}{w}</li>;
    const trigger = t(`autolog.trigger.${s.last.trigger}`);
    const outcome = RESULT_TEXT[s.last.outcome] ? resultText(s.last.outcome, t) : String(s.last.outcome ?? '—');
    const why = s.last.code ? errText(s.last) : '';  // motivo si el último aviso fue un descarte u omisión (err.hook.*)
    return <li key={d.id}>{t('launcher.last', { device: d.name, trigger, ago: ago(s.last.at, when, locale), outcome })}{why ? ` · ${why}` : ''}{w}</li>;
  }).filter(Boolean);

  let body;
  if (!game) body = <Alert variant="info">{t('launcher.noGames')}</Alert>;
  else if (!gameId) body = <Alert variant="info">{t('launcher.saveFirst')}</Alert>;
  else if (!devices.length) body = <Alert variant="info">{t('launcher.noDevices')}</Alert>;
  else if (keyState.error) body = <Alert variant="error" compact role="alert">{errText(keyState.error)}</Alert>;
  else if (!keyState.loaded) body = <small className="muted" role="status">{t('common.loading')}</small>;
  else if (!keyState.key) body = <Alert variant="info">{t('launcher.noKey')}</Alert>;
  else {
    const cmds = url ? commandsFor(tab, { url, key: keyState.key, game: gameId, device }) : null;
    body = (
      <>
        <div className="two">
          <Field label={t('launcher.device')}>
            {(p) => <Select {...p} value={device} onChange={(e) => setDevice(e.target.value)} options={devices.map((d) => ({ value: d.id, label: d.name }))} />}
          </Field>
          <Field label={t('launcher.hubUrl')} hint={t('launcher.hubUrlHint')} error={url ? undefined : t('launcher.invalidUrl')}>
            {(p) => <Input {...p} value={hubUrl} onChange={onUrl} inputMode="url" />}
          </Field>
        </div>
        {insecure && <Alert variant="warn" compact><Icon name="alert" /><span>{t('profile.apikey.insecure')}</span></Alert>}
        {!game.process?.trim() && <Alert variant="warn" compact><Icon name="alert" /><span>{rich(t('launcher.noProcess'))}</span></Alert>}
        <Tabs label={t('launcher.tabsAria')} value={tab} onChange={setTab} tabs={LAUNCHERS.map((id) => ({ id, label: t(`launcher.tab.${id}`) }))}>
          <small className="muted launcher-note" id={hintId}>{t(`launcher.where.${tab}`)} {t('launcher.closeNote')}</small>
          {cmds && cmds.map((c) => (
            <div key={`${tab}-${c.id}`} className="launcher-cmd">
              {cmds.length > 1 && <span className="launcher-cmd-title">{t(`launcher.cmd.${c.id}`)}</span>}
              <CopyBox value={c.text} label={t('launcher.cmdAria', { launcher: t(`launcher.tab.${tab}`) })} describedBy={hintId}
                what={t(cmds.length > 1 ? 'launcher.copyWhatCmd' : 'launcher.copyWhat', { launcher: t(`launcher.tab.${tab}`), cmd: t(`launcher.cmd.${c.id}`) })} />
            </div>
          ))}
        </Tabs>
      </>
    );
  }
  return (
    <div className="launcher">
      <small className="muted">{t('launcher.hint')}</small>
      {game && (
        <Field label={t('launcher.game')}>
          {(p) => <Select {...p} value={game.sel} onChange={(e) => onSelect(e.target.value)} options={games.map((g) => ({ value: g.sel, label: g.name || t('common.unnamed') }))} />}
        </Field>
      )}
      {body}
      {game && gameId && lines.length > 0 && (
        <div>
          <span className="launcher-cmd-title">{t('launcher.lastTitle')}</span>
          <ul className="launcher-last" aria-live="polite">{lines}</ul>
        </div>
      )}
    </div>
  );
}
