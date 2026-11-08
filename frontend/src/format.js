// Formato y lectura de estados que comparten varias pantallas.

// Ganador y dispositivos de una ejecución: campos winner/targets del estado (ids de dispositivo).
export function parseRun(s) {
  const winner = s.winner || '';
  const list = Array.isArray(s.targets) ? s.targets : [];
  const planned = !!s.dry_run || s.result === 'dry-run';
  return { winner, list, planned, structured: !!(winner || list.length) };
}

// Fecha ISO -> texto local en el idioma activo (`locale`); '—' si falta.
export const fmtDateTime = (iso, locale) => (iso ? new Date(iso).toLocaleString(locale) : '—');

// Resultado de una sincronización: clase del distintivo y clave de texto (se traduce con resultText o t()).
export const RESULT_CLASS = { ok: 'ok', error: 'error', aborted: 'aborted', skipped: 'aborted', conflict: 'conflict', partial: 'aborted' };
export const RESULT_TEXT = {
  ok: 'result.ok', error: 'result.error', aborted: 'result.aborted', skipped: 'result.skipped', conflict: 'result.conflict', partial: 'result.partial',
};
// Texto traducido de un resultado; uno desconocido se muestra tal cual.
export const resultText = (r, t) => (RESULT_TEXT[r] ? t(RESULT_TEXT[r]) : r);

// Política ante conflictos de la sync automática: [valor estable, clave de la etiqueta].
export const ON_CONFLICT_OPTIONS = [['skip', 'conflictPolicy.skip'], ['newest', 'conflictPolicy.newest']];

// Tamaño en bytes -> «1,5 MB» según el idioma; '—' si no es un número.
export function fmtSize(n, locale) {
  if (!Number.isFinite(n)) return '—';
  const num = (v, d) => new Intl.NumberFormat(locale, { maximumFractionDigits: d, minimumFractionDigits: 0 }).format(v);
  if (n < 1024) return `${num(n, 0)} B`;
  const u = ['KB', 'MB', 'GB'];
  let v = n / 1024;
  let i = 0;
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i += 1; }
  return `${num(v, v < 10 ? 1 : 0)} ${u[i]}`;
}

// Segundos Unix -> fecha y hora local del idioma activo; '—' si falta.
export function fmtWhen(sec, locale) {
  if (!sec) return '—';
  return new Date(sec * 1000).toLocaleString(locale, { dateStyle: 'medium', timeStyle: 'medium' });
}

// Duración en segundos -> «1,5 s» o «2 min 5 s»; '—' si no es un número.
export function fmtDuration(s, locale) {
  if (!Number.isFinite(s)) return '—';
  const nf = (v, d) => new Intl.NumberFormat(locale, { maximumFractionDigits: d, minimumFractionDigits: 0 }).format(v);
  if (s < 60) return `${nf(s, s < 10 ? 1 : 0)} s`;
  return `${Math.floor(s / 60)} min ${Math.round(s % 60)} s`;
}
