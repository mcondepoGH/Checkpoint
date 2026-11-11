import React, { useState } from 'react';
import AppIcon from '#src/components/ui/AppIcon.jsx';
import { errText, useI18n } from '#src/hooks/useI18n.js';
import { Alert, Button } from '#src/components/ui/index.js';
import { login } from '#src/lib/api/session.js';

export default function Login({ onDone }) {
  const { t } = useI18n();
  const [user, setUser] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState(null); // error de la API (se traduce al pintar)
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true); setError(null);
    try { await login(user, password); onDone(); }
    catch (err) { setError(err); }
    finally { setBusy(false); setPassword(''); }
  };

  return (
    <div className="center">
      <form className="card login" onSubmit={submit}>
        <h1><AppIcon className="login-logo" />Checkpoint</h1>
        <label>{t('login.user')}
          <input value={user} onChange={(e) => setUser(e.target.value)} autoComplete="username" autoFocus required />
        </label>
        <label>{t('login.password')}
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required />
        </label>
        {error && <Alert variant="error">{errText(error)}</Alert>}
        <Button type="submit" variant="primary" disabled={busy}>{t('login.submit')}</Button>
      </form>
    </div>
  );
}
