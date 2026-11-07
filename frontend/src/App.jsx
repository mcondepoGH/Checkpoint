import React, { useCallback, useEffect, useState } from 'react';
import { api, ApiError } from './api.js';
import logo from './assets/logo-icon.svg';
import Icon from './components/Icon.jsx';
import UpdateBadge from './components/UpdateBadge.jsx';
import UpdateDialog from './components/UpdateDialog.jsx';
import { installedVersion, updatesApplicable } from './updates.js';
import Login from './pages/Login.jsx';
import Settings from './pages/Settings.jsx';
import Sync from './pages/Sync.jsx';
import Versions from './pages/Versions.jsx';

// [id, etiqueta completa, etiqueta corta para móvil]
const TABS = [
  ['sync', 'Sincronizar', 'Sync'],
  ['versions', 'Versiones', 'Versiones'],
  ['settings', 'Configuración', 'Ajustes'],
];

function useTheme() {
  const [theme, setTheme] = useState(() => {
    try { return localStorage.getItem('theme') || 'auto'; } catch { return 'auto'; }
  });
  useEffect(() => {
    if (theme === 'auto') document.documentElement.removeAttribute('data-theme');
    else document.documentElement.setAttribute('data-theme', theme);
    try { localStorage.setItem('theme', theme); } catch { /* ignorar */ }
  }, [theme]);
  const next = { auto: 'light', light: 'dark', dark: 'auto' }[theme];
  return [theme, () => setTheme(next)];
}

export default function App() {
  const [authed, setAuthed] = useState(null);
  const [tab, setTab] = useState('sync');
  const [loaded, setLoaded] = useState({ version: '', config: { devices: {}, games: {} }, error: null });
  const [latest, setLatest] = useState(null); // última versión de config.yaml anunciada por el servidor (SSE)
  const [dirty, setDirty] = useState(false); // borrador de Configuración con cambios sin guardar
  const [error, setError] = useState('');
  const [updates, setUpdates] = useState(null); // estado de /api/updates; un fallo aquí nunca molesta
  const [showUpdate, setShowUpdate] = useState(false);
  const [theme, cycleTheme] = useTheme();
  const config = loaded.config;

  const loadConfig = useCallback(async (first = false) => {
    try {
      const r = await api('/api/config');
      setLoaded(r);
      setError('');
      if (first && Object.keys(r.config.devices).length === 0) setTab('settings');
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) setAuthed(false);
      else setError(e.message);
    }
  }, []);

  useEffect(() => {
    api('/api/session').then((s) => {
      setAuthed(s.authenticated);
      if (s.authenticated) loadConfig(true);
    }).catch(() => setAuthed(false));
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
    let t = null;
    const check = () => api('/api/updates').then((r) => {
      setUpdates(r);
      if (r && r.aplicable === false && t) { clearInterval(t); t = null; } // no aplica (Docker): sin más consultas
    }).catch(() => {});
    check();
    t = setInterval(check, 6 * 3600 * 1000);
    return () => { if (t) clearInterval(t); };
  }, [authed]);

  const stale = latest !== null && latest !== loaded.version;
  // Sin borrador pendiente se recarga solo; con borrador, Configuración avisa y no pisa nada.
  useEffect(() => { if (stale && !dirty) loadConfig(); }, [stale, dirty, loadConfig]);

  const logout = async () => { await api('/api/logout', { method: 'POST' }); setAuthed(false); };

  if (authed === null) return <div className="center muted">Cargando…</div>;
  if (!authed) {
    return <Login onDone={() => { setAuthed(true); loadConfig(true); }} theme={theme} cycleTheme={cycleTheme} />;
  }

  return (
    <div className="app">
      <header className="topbar">
        <strong className="brand"><img src={logo} alt="" aria-hidden="true" className="brand-logo" /><span className="brand-name">Checkpoint</span></strong>
        <nav className="tabs" aria-label="Secciones">
          {TABS.map(([id, label, short]) => (
            <button key={id} className={tab === id ? 'tab active' : 'tab'} aria-current={tab === id ? 'page' : undefined} aria-label={label} onClick={() => setTab(id)}>
              <span className="full" aria-hidden="true">{label}</span><span className="short" aria-hidden="true">{short}</span>
            </button>
          ))}
        </nav>
        <div className="spacer" />
        <UpdateBadge info={updates} onOpen={() => setShowUpdate(true)} />
        <button className="btn ghost tool" onClick={cycleTheme} title="Cambiar tema" aria-label={`Cambiar tema (actual: ${theme})`}>
          <Icon name="theme" /><span className="lbl">Tema: {theme}</span>
        </button>
        <button className="btn ghost tool" onClick={logout} title="Salir" aria-label="Salir">
          <Icon name="logout" /><span className="lbl">Salir</span>
        </button>
      </header>
      <main className="content">
        {error && <div className="alert error" role="alert">{error}</div>}
        <div hidden={tab !== 'settings'}>
          <Settings loaded={loaded} stale={stale && dirty} configError={loaded.error} runtime={loaded.runtime} platform={loaded.platform}
            onApplied={(r) => { setLoaded((l) => ({ ...l, version: r.version, config: r.config, error: null })); setLatest(r.version); }}
            onReload={() => loadConfig()} onDirty={setDirty} updates={updates} onUpdates={setUpdates} />
        </div>
        {tab === 'sync' && <Sync config={config} onGoSettings={() => setTab('settings')} />}
        {tab === 'versions' && <Versions config={config} onGoSettings={() => setTab('settings')} />}
      </main>
      {installedVersion(updates) && <footer className="app-footer muted">Checkpoint {installedVersion(updates)}</footer>}
      {showUpdate && updatesApplicable(updates) && <UpdateDialog info={updates} onClose={() => setShowUpdate(false)} />}
    </div>
  );
}
