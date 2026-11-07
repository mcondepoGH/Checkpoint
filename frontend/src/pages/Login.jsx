import React, { useState } from 'react';
import { api } from '../api.js';

export default function Login({ onDone, theme, cycleTheme }) {
  const [user, setUser] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true); setError('');
    try { await api('/api/login', { method: 'POST', body: { user, password } }); onDone(); }
    catch (err) { setError(err.message); }
    finally { setBusy(false); setPassword(''); }
  };

  return (
    <div className="center">
      <form className="card login" onSubmit={submit}>
        <h1>savesync</h1>
        <label>Usuario
          <input value={user} onChange={(e) => setUser(e.target.value)} autoComplete="username" autoFocus required />
        </label>
        <label>Contraseña
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required />
        </label>
        {error && <div className="alert error">{error}</div>}
        <button className="btn primary" disabled={busy}>Entrar</button>
        <button type="button" className="btn ghost" onClick={cycleTheme}>Tema: {theme}</button>
      </form>
    </div>
  );
}
