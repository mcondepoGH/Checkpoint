// Service worker (la app sigue siendo instalable desde el menú del navegador; el hub no ofrece botón propio).

// Service worker solo en contexto seguro (HTTPS o localhost); en http plano el navegador no lo permite.
export function registerServiceWorker(win = window) {
  if (!win.isSecureContext || !('serviceWorker' in win.navigator)) return;
  win.addEventListener('load', () => {
    win.navigator.serviceWorker.register('/sw.js').catch(() => {});
  });
}
