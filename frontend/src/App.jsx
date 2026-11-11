import React, { useCallback, useEffect, useState } from 'react';
import { api, ApiError } from '#src/lib/api.js';
import AppIcon from '#src/components/AppIcon.jsx';
import UpdateBadge from '#src/components/UpdateBadge.jsx';
import ProfileMenu from '#src/components/ProfileMenu.jsx';
import WatchSummary from '#src/components/WatchSummary.jsx';
import { useWatches } from './useWatches.js';
import UpdateDialog from '#src/components/UpdateDialog.jsx';
import { installedVersion, updatesApplicable } from '#src/lib/updates.js';
import Login from '#src/pages/Login.jsx';
import Settings from '#src/pages/Settings.jsx';
import Sync from '#src/pages/Sync.jsx';
import Versions from '#src/pages/Versions.jsx';
import { errText, initDefaultLang, useI18n } from './useI18n.js';
import { Alert } from '#src/components/ui/index.js';

// Pestañas: el id es estable; las etiquetas (completa y corta, para móvil) son claves `app.tab.<id>.full|short`.
const TABS = ['sync', 'versions', 'settings'];

function useTheme() {
  const [theme, setTheme] = useState(() => {
    try { return localStorage.getItem('theme') || 'auto'; } catch { return 'auto'; }
  });
  useEffect(() => {
    if (theme === 'auto') document.documentElement.removeAttribute('data-theme');
    else document.documentElement.setAttribute('data-theme', theme);
    try { localStorage.setItem('theme', theme); } catch { /* ignorar */ }
  }, [theme]);
  // Tema efectivo (para el icono): en «auto» manda la preferencia del sistema.
  const [systemDark, setSystemDark] = useState(() => { try { return window.matchMedia('(prefers-color-scheme: dark)').matches; } catch { return false; } });
  useEffect(() => {
    let mq = null;
    try { mq = window.matchMedia('(prefers-color-scheme: dark)'); } catch { return undefined; }
    const on = (e) => setSystemDark(e.matches);
    mq.addEventListener('change', on);
    return () => mq.removeEventListener('change', on);
  }, []);
  const next = { auto: 'light', light: 'dark', dark: 'auto' }[theme];
  const effective = theme === 'auto' ? (systemDark ? 'dark' : 'light') : theme;
  return [theme, () => setTheme(next), effective];
}

export default function App() {
  const { t, locale } = useI18n(); // re-renderiza al cambiar de idioma
  useEffect(() => { document.documentElement.lang = locale; }, [locale]); // lector de pantalla y traductor del navegador
  const [authed, setAuthed] = useState(null);
  const [tab, setTab] = useState('sync');
  const [loaded, setLoaded] = useState({ version: '', config: { devices: {}, games: {} }, error: null });
  const [latest, setLatest] = useState(null); // última versión de config.yaml anunciada por el servidor (SSE)
  const [dirty, setDirty] = useState(false); // borrador de Configuración con cambios sin guardar
  const [error, setError] = useState(null); // error de la API (se traduce al pintar)
  const [updates, setUpdates] = useState(null); // estado de /api/updates; un fallo aquí nunca molesta
  const [showUpdate, setShowUpdate] = useState(false);
  const [profile, setProfile] = useState({ name: '', photo: null }); // nombre y foto (versión) del perfil; un fallo aquí nunca molesta
  const [theme, cycleTheme, effectiveTheme] = useTheme();
  const config = loaded.config;
  const watch = useWatches(authed === true); // una sola consulta de vigilancia: cabecera y tarjetas de Sincronizar

  const loadConfig = useCallback(async (first = false) => {
    try {
      const r = await api('/api/config');
      setLoaded(r);
      setError(null);
      if (first && Object.keys(r.config.devices).length === 0) setTab('settings');
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) setAuthed(false);
      else setError(e);
    }
  }, []);

  useEffect(() => {
    // El idioma por defecto del servidor se pide en paralelo y se espera antes de pintar (evita parpadeo es -> en).
    const pub = initDefaultLang();
    api('/api/session').then(async (s) => {
      await pub;
      setAuthed(s.authenticated);
      if (s.authenticated) loadConfig(true);
    }).catch(async () => { await pub; setAuthed(false); });
  }, [loadConfig]);

  // El backend vigila config.yaml y avisa de cambios (también ediciones a mano).
  useEffect(() => {
    if (!authed) return undefined;
    const es = new EventSource('/api/config/events');
    es.addEventListener('config', (ev) => { try { setLatest(JSON.parse(ev.data).version); } catch { /* ignorar */ } });
    es.onerror = () => {
      api('/api/session').then((s) => { if (!s.authenticated) { es.close(); setAuthed(false); } }).catch(() => {});
    };
    return () => es.close();
  }, [authed]);

  // Comprobación de versión nueva: al entrar y cada 6 h (el backend cachea y no repite peticiones a GitHub).
  useEffect(() => {
    if (!authed) return undefined;
    let timer = null;
    const check = () => api('/api/updates').then((r) => {
      setUpdates(r);
      if (r && r.aplicable === false && timer) { clearInterval(timer); timer = null; } // no aplica (Docker): sin más consultas
    }).catch(() => {});
    check();
    timer = setInterval(check, 6 * 3600 * 1000);
    return () => { if (timer) clearInterval(timer); };
  }, [authed]);

  useEffect(() => {
    if (authed) api('/api/profile').then(setProfile).catch(() => {});
  }, [authed]);

  const stale = latest !== null && latest !== loaded.version;
  // Sin borrador pendiente se recarga solo; con borrador, Configuración avisa y no pisa nada.
  useEffect(() => { if (stale && !dirty) loadConfig(); }, [stale, dirty, loadConfig]);

  const logout = async () => { await api('/api/logout', { method: 'POST' }); setAuthed(false); };

  if (authed === null) return <div className="center muted">{t('common.loading')}</div>;
  if (!authed) {
    return <Login onDone={() => { setAuthed(true); loadConfig(true); }} />;
  }

  return (
    <div className="app">
      <header className="topbar">
        <strong className="brand"><AppIcon className="brand-logo" /><span className="brand-name">Checkpoint</span></strong>
        <nav className="tabs" aria-label={t('app.sections')}>
          {TABS.map((id) => (
            <button key={id} className={tab === id ? 'tab active' : 'tab'} aria-current={tab === id ? 'page' : undefined} aria-label={t(`app.tab.${id}.full`)} onClick={() => setTab(id)}>
              <span className="full" aria-hidden="true">{t(`app.tab.${id}.full`)}</span><span className="short" aria-hidden="true">{t(`app.tab.${id}.short`)}</span>
            </button>
          ))}
        </nav>
        <div className="spacer" />
        <WatchSummary watch={watch} config={config} />
        <UpdateBadge info={updates} onOpen={() => setShowUpdate(true)} />
        <ProfileMenu profile={profile} theme={theme} effectiveTheme={effectiveTheme}
          updates={updates} onUpdate={() => setShowUpdate(true)} onCycleTheme={cycleTheme} onLogout={logout} onPhoto={(photo) => setProfile((p) => ({ ...p, photo }))} />
      </header>
      <main className="content">
        {error && <Alert variant="error" role="alert">{errText(error)}</Alert>}
        <div hidden={tab !== 'settings'}>
          <Settings loaded={loaded} stale={stale && dirty} configError={loaded.error} runtime={loaded.runtime} platform={loaded.platform}
            onApplied={(r) => { setLoaded((l) => ({ ...l, version: r.version, config: r.config, error: null })); setLatest(r.version); }}
            onReload={() => loadConfig()} onDirty={setDirty} updates={updates} onUpdates={setUpdates} />
        </div>
        {tab === 'sync' && <Sync config={config} watch={watch} onGoSettings={() => setTab('settings')} />}
        {tab === 'versions' && <Versions config={config} onGoSettings={() => setTab('settings')} />}
      </main>
      {installedVersion(updates) && <footer className="app-footer muted">Checkpoint {installedVersion(updates)}</footer>}
      {showUpdate && updatesApplicable(updates) && <UpdateDialog info={updates} onClose={() => setShowUpdate(false)} />}
    </div>
  );
}
