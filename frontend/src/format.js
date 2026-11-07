// Formato y lectura de estados que comparten varias pantallas.

// Ganador y dispositivos de una ejecución: campos winner/targets del estado (ids de dispositivo).
export function parseRun(s) {
  const winner = s.winner || '';
  const list = Array.isArray(s.targets) ? s.targets : [];
  const planned = !!s.dry_run || s.result === 'dry-run';
  return { winner, list, planned, structured: !!(winner || list.length) };
}
