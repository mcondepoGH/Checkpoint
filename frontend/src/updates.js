// Lógica pura de la comprobación de actualizaciones (sin React): fácil de probar.

// El backend dice `aplicable: false` cuando la comprobación no va con este entorno (Docker, salvo forzado).
// Mientras no hay respuesta (info null) tampoco se muestra nada: así la tarjeta no parpadea.
export function updatesApplicable(info) {
  return !!info && info.aplicable !== false;
}

// La insignia solo aparece si la comprobación es aplicable y está activa, y el backend dice que hay versión nueva.
export function showBadge(info) {
  return !!(info && info.aplicable !== false && info.habilitado !== false && info.hay_actualizacion === true);
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

// Versión instalada para el pie de página ('' si aún no se conoce o es una compilación de desarrollo).
export function installedVersion(info) {
  const v = info && typeof info.actual === 'string' ? info.actual.trim() : '';
  return v && v !== 'desconocida' ? v : '';
}

export function updateSummary(info) {
  if (!info) return '';
  if (info.habilitado === false) return 'Comprobación desactivada: no se hace ninguna petición a internet.';
  if (info.hay_actualizacion) return `Hay una versión nueva${isPrerelease(info) ? ' preliminar' : ''}: ${info.ultima} (instalada: ${info.actual}).`;
  if (info.ultima) return `Estás al día (versión ${info.actual}).`;
  return `Versión instalada: ${info.actual}. Aún no hay datos de la última versión.`;
}
