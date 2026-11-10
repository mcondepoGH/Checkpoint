import { useEffect, useState } from 'react';
import { api } from './api.js';

export const WATCH_POLL_MS = 5000; // el backend no emite eventos de vigilancia: se consulta /api/watches (los SSE existentes son de config y de ejecuciones)
export const NO_WATCHES = { now: null, watches: [] };

// Lo que guarda el estado a partir de la respuesta de /api/watches (tolerante a respuestas raras).
export const watchState = (r) => ({ now: (r && r.now) || null, watches: Array.isArray(r && r.watches) ? r.watches : [] });

// Una sola consulta periódica de /api/watches para toda la app (la usan la cabecera y las tarjetas de Sincronizar).
// Solo con la pestaña visible; al volver a verla refresca al momento. Sin sesión (`enabled` falso) no consulta.
// Un fallo de red nunca molesta: se conserva el último estado.
export function useWatches(enabled = true) {
  const [watch, setWatch] = useState(NO_WATCHES);
  useEffect(() => {
    if (!enabled) { setWatch(NO_WATCHES); return undefined; }
    let alive = true;
    const load = () => {
      if (typeof document !== 'undefined' && document.hidden) return;
      api('/api/watches').then((r) => alive && setWatch(watchState(r))).catch(() => {});
    };
    load();
    const timer = setInterval(load, WATCH_POLL_MS);
    document.addEventListener('visibilitychange', load);
    return () => { alive = false; clearInterval(timer); document.removeEventListener('visibilitychange', load); };
  }, [enabled]);
  return watch;
}
