import React, { useCallback, useEffect, useState } from 'react';
import { api, ApiError } from './api.js';
import Login from './pages/Login.jsx';
import Settings from './pages/Settings.jsx';
import Sync from './pages/Sync.jsx';
import Versions from './pages/Versions.jsx';

const TABS = [
  ['sync', 'Sincronizar'],
  ['versions', 'Versiones'],
  ['settings', 'Configuración'],
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
        <strong className="brand">savesync</strong>
        <nav className="tabs" aria-label="Secciones">
          {TABS.map(([id, label]) => (
            <button key={id} className={tab === id ? 'tab active' : 'tab'} aria-current={tab === id ? 'page' : undefined} onClick={() => setTab(id)}>{label}</button>
          ))}
        </nav>
        <div className="spacer" />
        <button className="btn ghost" onClick={cycleTheme} title="Cambiar tema">Tema: {theme}</button>
        <button className="btn ghost" onClick={logout}>Salir</button>
      </header>
      <main className="content">
        {error && <div className="alert error" role="alert">{error}</div>}
        <div hidden={tab !== 'settings'}>
          <Settings loaded={loaded} stale={stale && dirty} configError={loaded.error}
            onApplied={(r) => { setLoaded({ version: r.version, config: r.config, error: null }); setLatest(r.version); }}
            onReload={() => loadConfig()} onDirty={setDirty} />
        </div>
        {tab === 'sync' && <Sync config={config} onGoSettings={() => setTab('settings')} />}
        {tab === 'versions' && <Versions config={config} onGoSettings={() => setTab('settings')} />}
      </main>
    </div>
  );
}
