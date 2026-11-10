// Vigilante de cierre en la UI: salud del latido y agrupación. Puro (sin DOM) para poder probarlo.
export const STALE_FACTOR = 3; // sin sondeo en 3 intervalos -> «sin latido»
export const DEFAULT_POLL_S = 15;

const ms = (iso) => { const n = iso ? Date.parse(iso) : NaN; return Number.isNaN(n) ? null : n; };

// Estado a pintar: 'waiting' | 'running' | 'settling' | 'stale'. `now` es la hora del servidor (ISO), no la del navegador.
export function watchHealth(w, now) {
  const last = ms(w.last_poll);
  const cur = ms(now);
  const poll = w.poll > 0 ? w.poll : DEFAULT_POLL_S;
  if (last !== null && cur !== null && cur - last > STALE_FACTOR * poll * 1000) return 'stale';
  return ['waiting', 'running', 'settling'].includes(w.state) ? w.state : 'waiting';
}

// {juego -> [vigilancias]} (orden estable por dispositivo).
export function groupByGame(list) {
  const out = {};
  for (const w of list || []) (out[w.game] ||= []).push(w);
  for (const k of Object.keys(out)) out[k].sort((a, b) => String(a.device).localeCompare(String(b.device)));
  return out;
}

// Hora local HH:MM de una fecha ISO; '—' si no se puede interpretar.
export function clock(iso, locale) {
  const n = ms(iso);
  return n === null ? '—' : new Date(n).toLocaleTimeString(locale, { hour: '2-digit', minute: '2-digit' });
}
