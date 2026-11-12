// Comandos de lanzador, sin React (se prueba sin navegador). `url` = origen del hub, `key` = API key, `game` = id del juego,
// `device` = id del dispositivo. El hub vigila el cierre solo tras `opened`: ningún lanzador necesita hook de cierre.
export const LAUNCHERS = ['steam', 'lutris', 'heroic', 'windows'];

const STORE = 'checkpoint.hubUrl';

// encodeURIComponent deja sin codificar ! ' ( ) *; se codifican también para que nada se interprete dentro de comillas.
const enc = (s) => encodeURIComponent(String(s)).replace(/[!'()*]/g, (c) => `%${c.charCodeAt(0).toString(16).toUpperCase()}`);

// URL base del hub: http(s), sin espacios ni caracteres que el shell interpretaría; sin barras finales. null si no vale.
export function normalizeHubUrl(raw) {
  const s = String(raw ?? '')
    .trim()
    .replace(/\/+$/, '');
  return /^https?:\/\/[^\s"'`$\\;&|<>^%]+$/.test(s) ? s : null;
}

export const hookUrl = ({ url, game, device }) => `${url}/api/hook/${enc(game)}/opened?device=${enc(device)}`;

const curl = (o) => `curl -fsS -m 60 --retry 3 -X POST -H "Authorization: Bearer ${o.key}" "${hookUrl(o)}"`;

// Comandos de un lanzador: [{ id, text }]; el primero es el principal. null si la URL del hub no es válida.
export function commandsFor(launcher, opts) {
  const url = normalizeHubUrl(opts.url);
  if (!url) return null;
  const o = { ...opts, url };
  switch (launcher) {
    case 'steam':
      return [{ id: 'main', text: `${curl(o)}; %command%` }];
    case 'lutris':
    case 'heroic':
      return [{ id: 'main', text: curl(o) }];
    case 'windows':
      return [
        {
          id: 'powershell',
          text: `Invoke-WebRequest -Method Post -Uri "${hookUrl(o)}" -Headers @{Authorization='Bearer ${o.key}'} -TimeoutSec 60 -UseBasicParsing`,
        },
        { id: 'curl', text: `curl.exe${curl(o).slice('curl'.length)}` },
      ];
    default:
      return [];
  }
}

// URL del hub recordada por el viewer (localStorage inyectable; nunca lanza).
export function loadHubUrl(storage, fallback) {
  try {
    return storage?.getItem(STORE) || fallback;
  } catch {
    return fallback;
  }
}
export function saveHubUrl(storage, url) {
  try {
    storage?.setItem(STORE, url);
  } catch {
    /* sin almacenamiento: no se recuerda */
  }
}

// «hace 3 minutos» en el idioma pedido; '' si la fecha no es válida. Un instante futuro (reloj desfasado) cuenta como ahora.
export function ago(iso, now, locale) {
  const ms = new Date(iso).getTime();
  if (!Number.isFinite(ms)) return '';
  const s = Math.max(0, Math.round((now.getTime() - ms) / 1000));
  const [v, unit] =
    s < 60
      ? [s, 'second']
      : s < 3600
        ? [Math.round(s / 60), 'minute']
        : s < 86400
          ? [Math.round(s / 3600), 'hour']
          : [Math.round(s / 86400), 'day'];
  return new Intl.RelativeTimeFormat(locale, { numeric: 'always' }).format(-v, unit);
}
