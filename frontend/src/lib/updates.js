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

// `label` y CHANNEL_HELP son claves del catálogo (se traducen al pintar); `value` es el valor estable del backend.
export const CHANNEL_OPTIONS = [{ value: 'stable', label: 'updates.channel.stable' }, { value: 'beta', label: 'updates.channel.beta' }];
export const CHANNEL_HELP = 'updates.channel.help';

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

// Resumen del estado de la comprobación, traducido con `t`.
export function updateSummary(info, t) {
  if (!info) return '';
  if (info.habilitado === false) return t('updates.summary.disabled');
  if (info.hay_actualizacion) return t(isPrerelease(info) ? 'updates.summary.newerPre' : 'updates.summary.newer', { latest: info.ultima, current: info.actual });
  if (info.ultima) return t('updates.summary.upToDate', { current: info.actual });
  return t('updates.summary.noData', { current: info.actual });
}
