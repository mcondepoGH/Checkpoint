// Service worker mínimo: existe para cumplir los criterios de instalación de la PWA y NO cachea nada.
// La app solo funciona con el servidor (API autenticada, SSE) y el HTML nunca se cachea (ver backend), así que
// no hay modo sin conexión que ofrecer y no puede quedarse una interfaz vieja ni datos sensibles en caché.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()));
// Sin respondWith: todas las peticiones (incluida /api) van directas a la red.
self.addEventListener('fetch', () => {});
