// Lógica de la sección «API key» del perfil, sin React: estado, transiciones y llamadas a la API (se prueba sin navegador).
// La clave es una sola por usuario; el servidor la devuelve siempre (GET) y la regenera con POST (invalida la anterior).
export const initialState = { loaded: false, exists: false, key: null, confirm: null, busy: false, error: null };

// confirm: null | 'regenerate' | 'revoke' (confirmación en la propia sección, sin diálogo aparte).
export function reduce(s, a) {
  switch (a.type) {
    case 'start': return { ...s, busy: true, error: null };
    case 'loaded': return { ...s, loaded: true, busy: false, exists: !!a.exists, key: a.exists ? a.key : null, confirm: null };
    case 'failed': return { ...s, loaded: true, busy: false, confirm: null, error: a.error };
    case 'ask': return { ...s, confirm: a.what, error: null };
    case 'cancel': return { ...s, confirm: null };
    default: return s;
  }
}

const VERBS = { load: 'GET', create: 'POST', revoke: 'DELETE' };

// Ejecuta una acción contra la API y devuelve la acción del reductor. Un fallo guarda el error (se traduce al pintar).
export async function run(api, what) {
  try {
    const r = await api('/api/profile/apikey', { method: VERBS[what] });
    return { type: 'loaded', exists: r.exists, key: r.key };
  } catch (error) {
    return { type: 'failed', error };
  }
}

// ¿La URL es http:// (la key viaja en claro)? Se avisa salvo en localhost.
export const isInsecure = (loc) => !!loc && loc.protocol === 'http:' && !['localhost', '127.0.0.1', '[::1]'].includes(loc.hostname);
