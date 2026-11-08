import React, { useState } from 'react';
import logo from '../assets/logo-icon.svg';
import { api } from '../api.js';
import { errText, useI18n } from '../useI18n.js';
import LanguageSelect from '../components/LanguageSelect.jsx';

export default function Login({ onDone, theme, cycleTheme }) {
  const { t } = useI18n();
  const [user, setUser] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState(null); // error de la API (se traduce al pintar)
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true); setError(null);
    try { await api('/api/login', { method: 'POST', body: { user, password } }); onDone(); }
    catch (err) { setError(err); }
    finally { setBusy(false); setPassword(''); }
  };

  return (
    <div className="center">
      <form className="card login" onSubmit={submit}>
        <h1><img src={logo} alt="" aria-hidden="true" className="login-logo" />Checkpoint</h1>
        <label>{t('login.user')}
          <input value={user} onChange={(e) => setUser(e.target.value)} autoComplete="username" autoFocus required />
        </label>
        <label>{t('login.password')}
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required />
        </label>
        {error && <div className="alert error">{errText(error)}</div>}
        <button className="btn primary" disabled={busy}>{t('login.submit')}</button>
        <button type="button" className="btn ghost" onClick={cycleTheme}>{t('app.themeLabel', { theme: t(`app.theme.${theme}`) })}</button>
        <LanguageSelect />
      </form>
    </div>
  );
}
