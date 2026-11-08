import React, { useCallback, useEffect, useState } from 'react';
import { api, ApiError } from './api.js';
import logo from './assets/logo-icon.svg';
import Icon from './components/Icon.jsx';
import UpdateBadge from './components/UpdateBadge.jsx';
import LanguageSelect from './components/LanguageSelect.jsx';
import UpdateDialog from './components/UpdateDialog.jsx';
import { installedVersion, updatesApplicable } from './updates.js';
import Login from './pages/Login.jsx';
import Settings from './pages/Settings.jsx';
import Sync from './pages/Sync.jsx';
import Versions from './pages/Versions.jsx';
import { errText, initDefaultLang, useI18n } from './useI18n.js';

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
  const next = { auto: 'light', light: 'dark', dark: 'auto' }[theme];
  return [theme, () => setTheme(next)];
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
  const [theme, cycleTheme] = useTheme();
  const config = loaded.config;

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
        <strong className="brand"><img src={logo} alt="" aria-hidden="true" className="brand-logo" /><span className="brand-name">Checkpoint</span></strong>
        <nav className="tabs" aria-label={t('app.sections')}>
          {TABS.map((id) => (
            <button key={id} className={tab === id ? 'tab active' : 'tab'} aria-current={tab === id ? 'page' : undefined} aria-label={t(`app.tab.${id}.full`)} onClick={() => setTab(id)}>
              <span className="full" aria-hidden="true">{t(`app.tab.${id}.full`)}</span><span className="short" aria-hidden="true">{t(`app.tab.${id}.short`)}</span>
            </button>
          ))}
        </nav>
        <div className="spacer" />
        <UpdateBadge info={updates} onOpen={() => setShowUpdate(true)} />
        <LanguageSelect />
        <button className="btn ghost tool" onClick={cycleTheme} title={t('app.themeTitle')} aria-label={t('app.themeAria', { theme: t(`app.theme.${theme}`) })}>
          <Icon name="theme" /><span className="lbl">{t('app.themeLabel', { theme: t(`app.theme.${theme}`) })}</span>
        </button>
        <button className="btn ghost tool" onClick={logout} title={t('app.logout')} aria-label={t('app.logout')}>
          <Icon name="logout" /><span className="lbl">{t('app.logout')}</span>
        </button>
      </header>
      <main className="content">
        {error && <div className="alert error" role="alert">{errText(error)}</div>}
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
