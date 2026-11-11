import { useEffect, useState } from 'react';

// Tema (auto/light/dark): persiste en localStorage y lo aplica con `data-theme`. Devuelve [tema, alternar, tema efectivo].
export function useTheme() {
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
