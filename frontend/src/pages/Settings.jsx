import React, { useEffect, useMemo, useRef, useState } from 'react';
import { diffConfig, testDevice as testDeviceApi, validateConfig } from '#src/lib/api/config.js';
import {
  MAX_VERSIONS_LIMIT, VERSIONS_HINT, blankDevice, blankGame, canOfferLocal, deviceId, baseKeyOf, errorsFor, fromConfig, gamesUsing, hasChanges, idOf, localErrors, nameOf, pathsOf, removeDevice, renamed, toConfig,
} from '#src/components/config/draft.js';
import Field from '#src/components/ui/Field.jsx';
import DeviceCard from '#src/components/config/DeviceCard.jsx';
import GameCard from '#src/components/config/GameCard.jsx';
import LaunchersPanel from '#src/components/launchers/LaunchersPanel.jsx';
import { loadGameSel, saveGameSel } from '#src/components/launchers/launchers.js';
import PublicKey from '#src/components/keyhelp/PublicKey.jsx';
import AutoSync from '#src/components/autosync/AutoSync.jsx';
import UpdateCheck from '#src/components/updates/UpdateCheck.jsx';
import { updatesApplicable } from '#src/lib/updates.js';
import SaveDialog from '#src/components/config/SaveDialog.jsx';
import YamlDialog from '#src/components/config/YamlDialog.jsx';
import BackupsDialog from '#src/components/config/BackupsDialog.jsx';
import Icon from '#src/components/ui/Icon.jsx';
import EmptyState from '#src/components/ui/EmptyState.jsx';
import DiffView from '#src/components/config/DiffView.jsx';
import { errText, useI18n } from '#src/hooks/useI18n.js';
import { errorText, fieldErrorText, ui } from '#src/lib/errors.js';
import { Alert, Button, Input } from '#src/components/ui/index.js';

// Pantalla única de Configuración: dispositivos y juegos como tarjetas, validación en vivo con el
// validador del backend, vista previa de cambios antes de guardar.
export default function Settings({ loaded, stale, configError, runtime, platform, onApplied, onReload, onDirty, updates, onUpdates }) {
  const { t } = useI18n(); // re-renderiza al cambiar de idioma: errores y mensajes se guardan sin traducir y se traducen al pintar
  const fe = (v) => fieldErrorText(v, t);
  const [draft, setDraft] = useState(() => fromConfig(loaded.config));
  const [errors, setErrors] = useState({});
  const [validating, setValidating] = useState(false);
  const [tests, setTests] = useState({});
  const [dialog, setDialog] = useState(null); // {kind:'save'|'yaml'|'backups', ...}
  const [msg, setMsg] = useState(null); // {ok?, body}: `body` es un error de la API o un mensaje {code} (se traduce al pintar)
  const [busy, setBusy] = useState(false);
  const [staleDiff, setStaleDiff] = useState(null);
  const [launchersOpen, setLaunchersOpen] = useState(false); // sección «Lanzadores»: plegada por defecto
  const [launcherGame, setLauncherGame] = useState(() => { try { return loadGameSel(window.localStorage); } catch { return ''; } });
  const chooseLauncherGame = (sel) => { setLauncherGame(sel); try { saveGameSel(window.localStorage, sel); } catch { /* sin almacenamiento */ } };

  // Cada versión nueva cargada (inicio, guardado, recarga) reinicia el borrador. Se hace durante el render
  // (no en un efecto): así nunca se compara un borrador viejo (p. ej. el vacío previo a la carga) con la
  // config nueva, lo que marcaba "Cambios sin guardar" sin tocar nada.
  const [draftVersion, setDraftVersion] = useState(loaded.version);
  if (draftVersion !== loaded.version) {
    setDraftVersion(loaded.version);
    setDraft(fromConfig(loaded.config));
    setStaleDiff(null);
  }

  const local = useMemo(() => localErrors(draft, runtime), [draft, runtime]);
  // Juegos para el panel de lanzadores: dispositivos con nombre e id (los que el lanzador puede indicar en ?device=).
  const launcherGames = useMemo(() => draft.games.map((g) => ({
    sel: g.id || g.key, id: g.id, name: g.name, process: g.process, enabled: g.enabled !== false,
    devices: [g.a, g.b].map((k) => ({ id: deviceId(draft, k), name: nameOf(draft, k) })).filter((d) => d.id && d.name),
  })), [draft]);
  const showLaunchers = (g) => {
    chooseLauncherGame(g.id || g.key);
    setLaunchersOpen(true);
    setTimeout(() => document.getElementById('launchers-section')?.scrollIntoView({ block: 'start', behavior: 'smooth' }), 0);
  };
  const payload = useMemo(() => toConfig(draft), [draft]);
  const payloadKey = JSON.stringify(payload);
  const baseKey = useMemo(() => baseKeyOf(loaded.config), [loaded.config]);
  const dirty = hasChanges(payloadKey, baseKey, local);
  const hasLocal = Object.keys(local).length > 0;

  const dirtyRef = useRef(dirty);
  useEffect(() => { dirtyRef.current = dirty; onDirty(dirty); }, [dirty]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const h = (e) => { if (dirtyRef.current) { e.preventDefault(); e.returnValue = ''; } };
    window.addEventListener('beforeunload', h);
    return () => window.removeEventListener('beforeunload', h);
  }, []);

  // Validación en vivo (con retardo) contra el mismo validador del backend.
  const seq = useRef(0);
  useEffect(() => {
    const n = ++seq.current;
    setValidating(true);
    const timer = setTimeout(async () => {
      try {
        const r = await validateConfig(JSON.parse(payloadKey));
        if (n === seq.current) { setErrors(r.errors); setValidating(false); }
      } catch (e) {
        if (n === seq.current) { setErrors({ '': e }); setValidating(false); }
      }
    }, 300);
    return () => clearTimeout(timer);
  }, [payloadKey]);

  const patch = (list, key, p) => setDraft((d) => ({ ...d, [list]: d[list].map((x) => (x.key === key ? { ...x, ...p } : x)) }));

  const delDevice = (dev) => {
    const used = gamesUsing(draft, dev.key);
    if (used.length && !window.confirm(
      t('settings.delDevice', { device: dev.name || t('common.unnamed'), games: used.map((n) => n || t('common.unnamed')).join(', ') }))) return;
    setDraft((d) => removeDevice(d, dev.key));
  };

  const testDevice = async (dev) => {
    setTests((prev) => ({ ...prev, [dev.key]: { busy: true } }));
    let r;
    try {
      // «Este equipo»: sin SSH; se comprueban las carpetas de saves de los juegos que lo usan.
      r = await testDeviceApi(dev.local
        ? { device: { name: dev.name || 'prueba', local: true, os: dev.os }, paths: pathsOf(draft, dev.key) }
        : { device: { name: dev.name || 'prueba', host: dev.host, user: dev.user, os: dev.os, port: Number(dev.port) || dev.port } });
    } catch (e) { r = { ok: false, code: e.code, params: e.params, message: e.message }; }
    setTests((prev) => ({ ...prev, [dev.key]: r }));
  };

  const hasErrors = Object.keys(errors).length > 0 || hasLocal;
  const canSave = dirty && !hasErrors && !validating && !busy && !stale;

  const openSave = async () => {
    setBusy(true);
    setMsg(null);
    try {
      const r = await diffConfig({ config: payload });
      setDialog({ kind: 'save', diff: r.diff, version: r.version, config: payload });
    } catch (e) { setMsg({ body: e }); } finally { setBusy(false); }
  };

  const applied = (r, text) => {
    setDialog(null);
    setMsg({ ok: true, body: text });
    onApplied({ version: r.version, config: r.config });
  };

  const showStaleDiff = async () => {
    try { setStaleDiff((await diffConfig({ config: payload })).diff); }
    catch (e) { setMsg({ body: e }); }
  };

  // Los errores del backend cuelgan del id interno: devices.<id>.<campo>
  const devErrs = (d) => errorsFor(errors, `devices.${idOf(d, 'dispositivo')}`, fe);
  const gameErrs = (g) => errorsFor(errors, `games.${idOf(g, 'juego')}`, fe);
  const generalError = fe(errors['']);

  // Chip de errores de la barra: salta al primer campo con error (o a la alerta general) y le da el foco.
  const rootRef = useRef(null);
  const errorCount = Math.max(Object.keys(errors).length, Object.keys(local).length);
  const jumpToError = () => {
    const el = rootRef.current?.querySelector('.field.has-error :is(input, select), .alert.error[role="alert"]');
    if (!el) return;
    el.scrollIntoView({ block: 'center', behavior: 'smooth' });
    if (typeof el.focus === 'function' && el.matches('input, select')) el.focus({ preventScroll: true });
  };

  return (
    <section aria-labelledby="cfg-title" ref={rootRef}>
      <h2 id="cfg-title">{t('settings.title')}</h2>

      {configError && <Alert variant="error" role="alert">
        {t('settings.invalid', { cause: errorText(configError, t) })}
      </Alert>}
      {stale && (
        <Alert variant="warn" role="alert">
          <strong>{t('settings.stale.lead')}</strong> {t('settings.stale.text')}
          <div className="row">
            <Button onClick={onReload}>{t('settings.stale.reload')}</Button>
            <Button onClick={showStaleDiff}>{t('settings.stale.diff')}</Button>
          </div>
          {staleDiff && <DiffBox diff={staleDiff} />}
        </Alert>
      )}
      {generalError && <Alert variant="error" role="alert">{generalError}</Alert>}
      <div role="status" aria-live="polite">{msg && <Alert variant={msg.ok ? 'ok' : 'error'}>{errText(msg.body)}</Alert>}</div>

      {/* La clave SSH solo importa si hay (o puede haber) dispositivos remotos. */}
      {(draft.devices.length === 0 || draft.devices.some((d) => !d.local)) && <PublicKey />}

      <AutoSync />

      {updatesApplicable(updates) && <UpdateCheck info={updates} onInfo={onUpdates} />}

      <fieldset className="card cfg-card">
        <legend className="cfg-title">{t('settings.versions.legend')}</legend>
        <Field label={t('settings.versions.max')} hint={t(VERSIONS_HINT)} error={local.maxVersions || fe(errors.max_versions)}>
          {(p) => <Input {...p} type="number" inputMode="numeric" min="0" max={MAX_VERSIONS_LIMIT} step="1"
            value={draft.maxVersions} onChange={(e) => setDraft((d) => ({ ...d, maxVersions: e.target.value }))} />}
        </Field>
      </fieldset>

      <div className="row between section-head">
        <h3>{t('settings.devices')}</h3>
        <Button onClick={() => setDraft((d) => ({ ...d, devices: [...d.devices, blankDevice()] }))}>
          {t('settings.addDevice')}
        </Button>
      </div>
      <div className="grid">
        {draft.devices.map((d) => (
          <DeviceCard key={d.key} dev={d} errors={devErrs(d)} localError={local[d.key]} localFlagError={local[`local-${d.key}`]}
            canLocal={canOfferLocal(draft, runtime, d.key)} runtime={runtime} platform={platform} test={tests[d.key]}
            idText={idOf(d, 'dispositivo')} renamed={renamed(d)}
            onChange={(p) => patch('devices', d.key, p)} onTest={() => testDevice(d)} onRemove={() => delDevice(d)} />
        ))}
      </div>
      {draft.devices.length === 0 && (
        <EmptyState icon="💻" title={t('settings.noDevices.title')}
          text={t('settings.noDevices.text')}
          action={<Button variant="primary" onClick={() => setDraft((d) => ({ ...d, devices: [...d.devices, blankDevice()] }))}>{t('settings.addDevice')}</Button>} />
      )}

      <div className="row between section-head">
        <h3>{t('settings.games')}</h3>
        <Button disabled={draft.devices.filter((d) => d.name).length < 1}
          onClick={() => setDraft((d) => ({ ...d, games: [...d.games, blankGame()] }))}>
          {t('settings.addGame')}
        </Button>
      </div>
      {draft.devices.filter((d) => d.name).length < 1 && <p className="muted">{t('settings.needOne')}</p>}
      <div className="grid">
        {draft.games.map((g) => (
          <GameCard key={g.key} game={g} devices={draft.devices} errors={gameErrs(g)} localError={local[g.key]} keepError={local[`keep-${g.key}`]} globalMax={draft.maxVersions}
            nameA={nameOf(draft, g.a)} nameB={nameOf(draft, g.b)} idA={deviceId(draft, g.a)} idB={deviceId(draft, g.b)}
            idText={idOf(g, 'juego')} renamed={renamed(g)}
            onChange={(p) => patch('games', g.key, p)} onShowLaunchers={() => showLaunchers(g)}
            onRemove={() => setDraft((d) => ({ ...d, games: d.games.filter((x) => x.key !== g.key) }))} />
        ))}
      </div>

      <LaunchersPanel id="launchers-section" open={launchersOpen} onToggle={() => setLaunchersOpen((o) => !o)}
        games={launcherGames} selected={launcherGame} onSelect={chooseLauncherGame} />

      <div className="actionbar" role="group" aria-label={t('settings.bar.aria')}>
        {hasErrors && !validating ? (
          <button type="button" className="ab-chip error" onClick={jumpToError}
            aria-label={t('settings.bar.errorsAria', { count: errorCount || 1 })}>
            <Icon name="alert" /><b>{errorCount || 1}</b><span className="ab-long">{t('settings.bar.errors')}</span>
          </button>
        ) : (
          <span className={`ab-chip${dirty ? ' dirty' : ''}`} aria-live="polite">
            {validating ? t('settings.bar.validating') : dirty ? <><span className="ab-long">{t('settings.bar.dirty')}</span><span className="ab-short">{t('settings.bar.dirtyShort')}</span></> : t('settings.bar.clean')}
          </span>
        )}
        <span className="spacer" />
        <Button variant="ghost" className="ab-tool" title={t('settings.bar.backups')} aria-label={t('settings.bar.backups')} onClick={() => setDialog({ kind: 'backups' })}>
          <Icon name="history" /><span className="lbl">{t('settings.bar.backups')}</span>
        </Button>
        <Button variant="ghost" className="ab-tool" title={t('settings.bar.yaml')} aria-label={t('settings.bar.yaml')} onClick={() => setDialog({ kind: 'yaml', config: payload })} disabled={hasErrors}>
          <Icon name="code" /><span className="lbl">{t('settings.bar.yaml')}</span>
        </Button>
        <Button className="ab-tool" title={t('settings.bar.discardTitle')} aria-label={t('settings.bar.discardTitle')} disabled={!dirty} onClick={() => { setDraft(fromConfig(loaded.config)); setMsg(null); }}>
          <Icon name="undo" /><span className="lbl">{t('settings.bar.discard')}</span>
        </Button>
        <Button variant="primary" disabled={!canSave} onClick={openSave}>{t('settings.bar.save')}</Button>
      </div>

      {dialog?.kind === 'save' && (
        <SaveDialog config={dialog.config} diff={dialog.diff} baseVersion={loaded.version}
          onSaved={(r) => applied(r, ui('settings.saved'))}
          onReload={() => { setDialog(null); onReload(); }} onClose={() => setDialog(null)} />
      )}
      {dialog?.kind === 'yaml' && <YamlDialog config={dialog.config} onClose={() => setDialog(null)} />}
      {dialog?.kind === 'backups' && (
        <BackupsDialog baseVersion={loaded.version} dirty={dirty}
          onRestored={(r) => applied(r, ui('settings.restored'))} onClose={() => setDialog(null)} />
      )}
    </section>
  );
}

function DiffBox({ diff }) { return <div className="diffbox"><DiffView diff={diff} /></div>; }
