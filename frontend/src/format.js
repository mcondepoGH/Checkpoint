// Formato y lectura de estados que comparten varias pantallas.

// Ganador y dispositivos de una ejecución: campos winner/targets del estado (ids de dispositivo).
export function parseRun(s) {
  const winner = s.winner || '';
  const list = Array.isArray(s.targets) ? s.targets : [];
  const planned = !!s.dry_run || s.result === 'dry-run';
  return { winner, list, planned, structured: !!(winner || list.length) };
}

// Fecha ISO -> texto local; '—' si falta.
export const fmtDateTime = (iso) => (iso ? new Date(iso).toLocaleString() : '—');

// Resultado de una sincronización: clase del distintivo y texto en español.
export const RESULT_CLASS = { ok: 'ok', error: 'error', aborted: 'aborted', skipped: 'aborted', conflict: 'conflict', partial: 'aborted' };
export const RESULT_TEXT = { ok: 'correcta', error: 'con errores', aborted: 'abortada', skipped: 'omitida', conflict: 'con conflictos', partial: 'parcial' };

// Política ante conflictos de la sync automática: [valor, etiqueta].
export const ON_CONFLICT_OPTIONS = [['skip', 'Omitir el guardado (seguro)'], ['newest', 'Gana el más reciente']];
