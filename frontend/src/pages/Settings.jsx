import React, { useEffect, useMemo, useRef, useState } from 'react';
import { diffConfig, testDevice as testDeviceApi } from '#src/lib/api/config.js';
import { deviceId, errorsFor, fromConfig, gamesUsing, idOf, nameOf, pathsOf, removeDevice } from '#src/components/config/draft.js';
import useConfigDraft from '#src/components/config/useConfigDraft.js';
import SaveDialog from '#src/components/config/SaveDialog.jsx';
import YamlDialog from '#src/components/config/YamlDialog.jsx';
import BackupsDialog from '#src/components/config/BackupsDialog.jsx';
import DiffView from '#src/components/config/DiffView.jsx';
import { errText, useI18n } from '#src/hooks/useI18n.js';
import { errorText, fieldErrorText, ui } from '#src/lib/errors.js';
import { Alert, Button, Tabs } from '#src/components/ui/index.js';
import General from './settings/General.jsx';
import Library from './settings/Library.jsx';
import Launchers from './settings/Launchers.jsx';

const SUBTABS = ['general', 'library', 'launchers'];

// Configuración con tres subpestañas (General, Biblioteca, Lanzadores; estado en memoria). Biblioteca edita el borrador de config.yaml
// (dispositivos y juegos como tarjetas, validación en vivo con el validador del backend, vista previa antes de guardar) y es la única con
// barra de guardar. Los paneles se conservan montados (el borrador sobrevive al cambiar de subpestaña) salvo Lanzadores, que solo se monta
// al abrirla (sus peticiones no se hacen antes). Abre General; Biblioteca en el primer uso (`firstUse`: aún sin dispositivos).
export default function Settings({
  loaded,
  stale,
  configError,
  runtime,
  platform,
  onApplied,
  onReload,
  onDirty,
  updates,
  onUpdates,
  firstUse = false,
}) {
  const { t } = useI18n(); // re-renderiza al cambiar de idioma: errores y mensajes se guardan sin traducir y se traducen al pintar
  const fe = (v) => fieldErrorText(v, t);
  const [tests, setTests] = useState({});
  const [dialog, setDialog] = useState(null); // {kind:'save'|'yaml'|'backups', ...}
  const [msg, setMsg] = useState(null); // {ok?, body}: `body` es un error de la API o un mensaje {code} (se traduce al pintar)
  const [busy, setBusy] = useState(false);
  const [staleDiff, setStaleDiff] = useState(null);
  const { draft, setDraft, errors, validating, local, hasLocal, payload, dirty, patch } = useConfigDraft({
    loaded,
    runtime,
    onDirty,
    onVersionChange: () => setStaleDiff(null),
  });
  const [sub, setSub] = useState(firstUse ? 'library' : 'general');
  useEffect(() => {
    if (firstUse) setSub('library'); // el primer uso se conoce al cargar la configuración, con Settings ya montado
  }, [firstUse]);
  // Juegos para Lanzadores (una fila por juego): dispositivos con nombre e id (los que el lanzador puede indicar en ?device=).
  const launcherGames = useMemo(
    () =>
      draft.games.map((g) => ({
        sel: g.id || g.key,
        id: g.id,
        name: g.name,
        process: g.process,
        enabled: g.enabled !== false,
        devices: [g.a, g.b]
          .map((k) => ({ id: deviceId(draft, k), name: nameOf(draft, k), http: draft.devices.find((d) => d.key === k)?.http === true }))
          .filter((d) => d.id && d.name),
      })),
    [draft],
  );
  const delDevice = (dev) => {
    const used = gamesUsing(draft, dev.key);
    if (
      used.length &&
      !window.confirm(
        t('settings.delDevice', { device: dev.name || t('common.unnamed'), games: used.map((n) => n || t('common.unnamed')).join(', ') }),
      )
    )
      return;
    setDraft((d) => removeDevice(d, dev.key));
  };

  const testDevice = async (dev) => {
    setTests((prev) => ({ ...prev, [dev.key]: { busy: true } }));
    let r;
    try {
      // «Este equipo»: sin SSH; se comprueban las carpetas de saves de los juegos que lo usan.
      r = await testDeviceApi(
        dev.local
          ? { device: { name: dev.name || 'prueba', local: true, os: dev.os }, paths: pathsOf(draft, dev.key) }
          : { device: { name: dev.name || 'prueba', host: dev.host, user: dev.user, os: dev.os, port: Number(dev.port) || dev.port } },
      );
    } catch (e) {
      r = { ok: false, code: e.code, params: e.params, message: e.message };
    }
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
    } catch (e) {
      setMsg({ body: e });
    } finally {
      setBusy(false);
    }
  };

  const applied = (r, text) => {
    setDialog(null);
    setMsg({ ok: true, body: text });
    onApplied({ version: r.version, config: r.config });
  };

  const showStaleDiff = async () => {
    try {
      setStaleDiff((await diffConfig({ config: payload })).diff);
    } catch (e) {
      setMsg({ body: e });
    }
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

      {configError && (
        <Alert variant="error" role="alert">
          {t('settings.invalid', { cause: errorText(configError, t) })}
        </Alert>
      )}
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
      {generalError && (
        <Alert variant="error" role="alert">
          {generalError}
        </Alert>
      )}
      <div role="status" aria-live="polite">
        {msg && <Alert variant={msg.ok ? 'ok' : 'error'}>{errText(msg.body)}</Alert>}
      </div>

      <Tabs
        variant="subnav"
        keepMounted
        label={t('settings.subtabs.aria')}
        value={sub}
        onChange={setSub}
        tabs={SUBTABS.map((id) => ({
          id,
          label: t(`settings.subtabs.${id}.full`),
          short: t(`settings.subtabs.${id}.short`),
          dot: id === 'library' && dirty ? t('settings.subtabs.dirty') : undefined,
        }))}
        panels={{
          general: <General updates={updates} onUpdates={onUpdates} />,
          library: (
            <Library
              draft={draft}
              setDraft={setDraft}
              patch={patch}
              errors={errors}
              local={local}
              fe={fe}
              devErrs={devErrs}
              gameErrs={gameErrs}
              runtime={runtime}
              platform={platform}
              tests={tests}
              onTest={testDevice}
              onDelDevice={delDevice}
              bar={{
                hasErrors,
                validating,
                dirty,
                canSave,
                errorCount,
                jumpToError,
                onBackups: () => setDialog({ kind: 'backups' }),
                onYaml: () => setDialog({ kind: 'yaml', config: payload }),
                onDiscard: () => {
                  setDraft(fromConfig(loaded.config));
                  setMsg(null);
                },
                onSave: openSave,
              }}
            />
          ),
          launchers: sub === 'launchers' ? <Launchers games={launcherGames} /> : null,
        }}
      />

      {dialog?.kind === 'save' && (
        <SaveDialog
          config={dialog.config}
          diff={dialog.diff}
          baseVersion={loaded.version}
          onSaved={(r) => applied(r, ui('settings.saved'))}
          onReload={() => {
            setDialog(null);
            onReload();
          }}
          onClose={() => setDialog(null)}
        />
      )}
      {dialog?.kind === 'yaml' && <YamlDialog config={dialog.config} onClose={() => setDialog(null)} />}
      {dialog?.kind === 'backups' && (
        <BackupsDialog
          baseVersion={loaded.version}
          dirty={dirty}
          onRestored={(r) => applied(r, ui('settings.restored'))}
          onClose={() => setDialog(null)}
        />
      )}
    </section>
  );
}

function DiffBox({ diff }) {
  return (
    <div className="diffbox">
      <DiffView diff={diff} />
    </div>
  );
}
