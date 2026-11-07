import React, { useEffect, useMemo, useRef, useState } from 'react';
import { api } from '../api.js';
import {
  MAX_VERSIONS_LIMIT, VERSIONS_HINT, blankDevice, blankGame, deviceId, errorsFor, fromConfig, gamesUsing, idOf, localErrors, nameOf, removeDevice, renamed, toConfig,
} from '../draft.js';
import Field from '../components/Field.jsx';
import DeviceCard from '../components/DeviceCard.jsx';
import GameCard from '../components/GameCard.jsx';
import PublicKey from '../components/PublicKey.jsx';
import AutoSync from '../components/AutoSync.jsx';
import SaveDialog from '../components/SaveDialog.jsx';
import YamlDialog from '../components/YamlDialog.jsx';
import BackupsDialog from '../components/BackupsDialog.jsx';
import EmptyState from '../components/EmptyState.jsx';
import DiffView from '../components/DiffView.jsx';

// Pantalla única de Configuración: dispositivos y juegos como tarjetas, validación en vivo con el
// validador del backend, vista previa de cambios antes de guardar.
export default function Settings({ loaded, stale, configError, onApplied, onReload, onDirty }) {
  const [draft, setDraft] = useState(() => fromConfig(loaded.config));
  const [errors, setErrors] = useState({});
  const [validating, setValidating] = useState(false);
  const [tests, setTests] = useState({});
  const [dialog, setDialog] = useState(null); // {kind:'save'|'yaml'|'backups', ...}
  const [msg, setMsg] = useState('');
  const [busy, setBusy] = useState(false);
  const [staleDiff, setStaleDiff] = useState(null);

  // Cada versión nueva cargada (inicio, guardado, recarga) reinicia el borrador.
  useEffect(() => { setDraft(fromConfig(loaded.config)); setStaleDiff(null); }, [loaded.version]); // eslint-disable-line react-hooks/exhaustive-deps

  const local = useMemo(() => localErrors(draft), [draft]);
  const payload = useMemo(() => toConfig(draft), [draft]);
  const payloadKey = JSON.stringify(payload);
  const baseKey = useMemo(() => JSON.stringify(toConfig(fromConfig(loaded.config))), [loaded.config]);
  const dirty = payloadKey !== baseKey || Object.keys(local).length > 0;
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
    const t = setTimeout(async () => {
      try {
        const r = await api('/api/config/validate', { method: 'POST', body: { config: JSON.parse(payloadKey) } });
        if (n === seq.current) { setErrors(r.errors); setValidating(false); }
      } catch (e) {
        if (n === seq.current) { setErrors({ '': e.message }); setValidating(false); }
      }
    }, 300);
    return () => clearTimeout(t);
  }, [payloadKey]);

  const patch = (list, key, p) => setDraft((d) => ({ ...d, [list]: d[list].map((x) => (x.key === key ? { ...x, ...p } : x)) }));

  const delDevice = (dev) => {
    const used = gamesUsing(draft, dev.key);
    if (used.length && !window.confirm(
      `El dispositivo ${dev.name || '(sin nombre)'} lo usan: ${used.join(', ')}.\n` +
      'Esos juegos perderán este dispositivo y deberás elegir otro. ¿Eliminarlo?')) return;
    setDraft((d) => removeDevice(d, dev.key));
  };

  const testDevice = async (dev) => {
    setTests((t) => ({ ...t, [dev.key]: { busy: true } }));
    let r;
    try {
      r = await api('/api/devices/test', {
        method: 'POST',
        body: { device: { name: dev.name || 'prueba', host: dev.host, user: dev.user, os: dev.os, port: Number(dev.port) || dev.port } },
      });
    } catch (e) { r = { ok: false, message: e.message }; }
    setTests((t) => ({ ...t, [dev.key]: r }));
  };

  const hasErrors = Object.keys(errors).length > 0 || hasLocal;
  const canSave = dirty && !hasErrors && !validating && !busy && !stale;

  const openSave = async () => {
    setBusy(true);
    setMsg('');
    try {
      const r = await api('/api/config/diff', { method: 'POST', body: { config: payload } });
      setDialog({ kind: 'save', diff: r.diff, version: r.version, config: payload });
    } catch (e) { setMsg(e.message); } finally { setBusy(false); }
  };

  const applied = (r, text) => {
    setDialog(null);
    setMsg(text);
    onApplied({ version: r.version, config: r.config });
  };

  const showStaleDiff = async () => {
    try { setStaleDiff((await api('/api/config/diff', { method: 'POST', body: { config: payload } })).diff); }
    catch (e) { setMsg(e.message); }
  };

  // Los errores del backend cuelgan del id interno: devices.<id>.<campo>
  const devErrs = (d) => errorsFor(errors, `devices.${idOf(d, 'dispositivo')}`);
  const gameErrs = (g) => errorsFor(errors, `games.${idOf(g, 'juego')}`);
  const generalError = errors[''];

  return (
    <section aria-labelledby="cfg-title">
      <h2 id="cfg-title">Configuración</h2>

      {configError && <div className="alert error" role="alert">
        config.yaml no es válido: {configError}. Corrígelo a mano o restaura una copia anterior.
      </div>}
      {stale && (
        <div className="alert warn" role="alert">
          <strong>config.yaml cambió por fuera.</strong> Guardar está desactivado para no pisar esos cambios.
          <div className="row">
            <button type="button" className="btn" onClick={onReload}>Recargar (descarto mi borrador)</button>
            <button type="button" className="btn" onClick={showStaleDiff}>Ver diferencias</button>
          </div>
          {staleDiff && <DiffBox diff={staleDiff} />}
        </div>
      )}
      {generalError && <div className="alert error" role="alert">{generalError}</div>}
      <div role="status" aria-live="polite">{msg && <div className="alert ok">{msg}</div>}</div>

      <PublicKey />

      <AutoSync />

      <fieldset className="card cfg-card">
        <legend className="cfg-title">Versiones guardadas</legend>
        <Field label="Máx. de versiones por juego" hint={VERSIONS_HINT} error={local.maxVersions || errors.max_versions}>
          {(p) => <input {...p} type="number" inputMode="numeric" min="0" max={MAX_VERSIONS_LIMIT} step="1"
            value={draft.maxVersions} onChange={(e) => setDraft((d) => ({ ...d, maxVersions: e.target.value }))} />}
        </Field>
      </fieldset>

      <div className="row between section-head">
        <h3>Dispositivos</h3>
        <button type="button" className="btn" onClick={() => setDraft((d) => ({ ...d, devices: [...d.devices, blankDevice()] }))}>
          Añadir dispositivo
        </button>
      </div>
      <div className="grid">
        {draft.devices.map((d) => (
          <DeviceCard key={d.key} dev={d} errors={devErrs(d)} localError={local[d.key]} test={tests[d.key]}
            idText={idOf(d, 'dispositivo')} renamed={renamed(d)}
            onChange={(p) => patch('devices', d.key, p)} onTest={() => testDevice(d)} onRemove={() => delDevice(d)} />
        ))}
      </div>
      {draft.devices.length === 0 && (
        <EmptyState icon="💻" title="Sin dispositivos"
          text="Añade al menos dos dispositivos para poder sincronizar partidas entre ellos."
          action={<button type="button" className="btn primary" onClick={() => setDraft((d) => ({ ...d, devices: [...d.devices, blankDevice()] }))}>Añadir dispositivo</button>} />
      )}

      <div className="row between section-head">
        <h3>Juegos</h3>
        <button type="button" className="btn" disabled={draft.devices.filter((d) => d.name).length < 2}
          onClick={() => setDraft((d) => ({ ...d, games: [...d.games, blankGame()] }))}>
          Añadir juego
        </button>
      </div>
      {draft.devices.filter((d) => d.name).length < 2 && <p className="muted">Define (y nombra) al menos dos dispositivos para añadir juegos.</p>}
      <div className="grid">
        {draft.games.map((g) => (
          <GameCard key={g.key} game={g} devices={draft.devices} errors={gameErrs(g)} localError={local[g.key]} keepError={local[`keep-${g.key}`]} globalMax={draft.maxVersions}
            nameA={nameOf(draft, g.a)} nameB={nameOf(draft, g.b)} idA={deviceId(draft, g.a)} idB={deviceId(draft, g.b)}
            idText={idOf(g, 'juego')} renamed={renamed(g)}
            onChange={(p) => patch('games', g.key, p)}
            onRemove={() => setDraft((d) => ({ ...d, games: d.games.filter((x) => x.key !== g.key) }))} />
        ))}
      </div>

      <div className="actionbar" role="group" aria-label="Acciones de configuración">
        <span className="muted" aria-live="polite">
          {validating ? 'Validando…' : hasErrors ? 'Hay errores por corregir' : dirty ? 'Cambios sin guardar' : 'Sin cambios'}
        </span>
        <span className="spacer" />
        <button type="button" className="btn ghost" onClick={() => setDialog({ kind: 'backups' })}>Restaurar versión anterior</button>
        <button type="button" className="btn ghost" onClick={() => setDialog({ kind: 'yaml', config: payload })} disabled={hasErrors}>Ver YAML</button>
        <button type="button" className="btn" disabled={!dirty} onClick={() => { setDraft(fromConfig(loaded.config)); setMsg(''); }}>Descartar</button>
        <button type="button" className="btn primary" disabled={!canSave} onClick={openSave}>Guardar…</button>
      </div>

      {dialog?.kind === 'save' && (
        <SaveDialog config={dialog.config} diff={dialog.diff} baseVersion={loaded.version}
          onSaved={(r) => applied(r, 'Guardado y aplicado al instante.')}
          onReload={() => { setDialog(null); onReload(); }} onClose={() => setDialog(null)} />
      )}
      {dialog?.kind === 'yaml' && <YamlDialog config={dialog.config} onClose={() => setDialog(null)} />}
      {dialog?.kind === 'backups' && (
        <BackupsDialog baseVersion={loaded.version} dirty={dirty}
          onRestored={(r) => applied(r, 'Versión restaurada y aplicada.')} onClose={() => setDialog(null)} />
      )}
    </section>
  );
}

function DiffBox({ diff }) { return <div className="diffbox"><DiffView diff={diff} /></div>; }
