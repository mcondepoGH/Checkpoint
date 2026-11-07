// Lógica pura de la comprobación de actualizaciones (sin React): fácil de probar.

// La insignia solo aparece si la comprobación está activa y el backend dice que hay versión nueva.
export function showBadge(info) {
  return !!(info && info.habilitado !== false && info.hay_actualizacion === true);
}

// Solo se enlazan URLs https (las notas vienen de fuera: nunca se confía en el esquema).
export function safeUrl(u) {
  return typeof u === 'string' && /^https:\/\//i.test(u) ? u : null;
}

export const CHANNEL_OPTIONS = [{ value: 'stable', label: 'Estable' }, { value: 'beta', label: 'Pruebas' }];
export const CHANNEL_HELP = 'Estable: solo versiones publicadas como definitivas. Pruebas: incluye también versiones preliminares, que pueden fallar.';

export function channelOf(info) {
  return info && info.canal === 'beta' ? 'beta' : 'stable';
}

// «preliminar» solo cuando el backend lo marca para la versión ofrecida.
export function isPrerelease(info) {
  return !!(info && info.prerelease === true);
}

export function versionLabel(info) {
  return info && info.ultima ? `${info.ultima}${isPrerelease(info) ? ' (preliminar)' : ''}` : '';
}

export function updateSummary(info) {
  if (!info) return '';
  if (info.habilitado === false) return 'Comprobación desactivada: no se hace ninguna petición a internet.';
  if (info.hay_actualizacion) return `Hay una versión nueva${isPrerelease(info) ? ' preliminar' : ''}: ${info.ultima} (instalada: ${info.actual}).`;
  if (info.ultima) return `Estás al día (versión ${info.actual}).`;
  return `Versión instalada: ${info.actual}. Aún no hay datos de la última versión.`;
}
