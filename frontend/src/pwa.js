// Instalación como app (PWA): detección de plataforma, decisión de qué aviso mostrar y captura de beforeinstallprompt.
// Lógica pura (sin tocar window al importar) para poder probarla en node.

export const DISMISS_KEY = 'pwa-install-dismissed';

// 'ios' | 'android' | 'other'. iPadOS se presenta como Macintosh con pantalla táctil.
export function detectPlatform({ userAgent = '', platform = '', maxTouchPoints = 0 } = {}) {
  if (/iPhone|iPad|iPod/i.test(userAgent) || (platform === 'MacIntel' && maxTouchPoints > 1)) return 'ios';
  if (/Android/i.test(userAgent)) return 'android';
  return 'other';
}

// Móvil = puntero principal táctil, o pantalla estrecha con user agent de móvil.
export function isMobileDevice({ coarse = false, narrow = false, platform = 'other', mobileUa = false } = {}) {
  return coarse || (narrow && (mobileUa || platform !== 'other'));
}

// Qué mostrar: 'none' | 'prompt' (botón Instalar, hay evento) | 'ios' (instrucciones de Safari).
// Sin evento y sin iOS no se muestra nada: en http plano Chrome nunca lanza beforeinstallprompt, y el aviso
// genérico («menú → Añadir a pantalla de inicio») solo crearía un acceso directo, no una app instalable.
export function installHint({ mobile, standalone, dismissed, platform, hasPrompt }) {
  if (!mobile || standalone || dismissed) return 'none';
  if (hasPrompt) return 'prompt';
  if (platform === 'ios') return 'ios';
  return 'none';
}

// Contexto del navegador; todo envuelto para que un fallo nunca rompa la app.
export function readEnv(win = globalThis.window) {
  const safe = (f, d) => { try { return f(); } catch { return d; } };
  const nav = win?.navigator || {};
  const platform = detectPlatform({ userAgent: nav.userAgent, platform: nav.platform, maxTouchPoints: nav.maxTouchPoints });
  return {
    platform,
    mobile: isMobileDevice({
      coarse: safe(() => win.matchMedia('(pointer: coarse)').matches, false),
      narrow: safe(() => win.matchMedia('(max-width: 640px)').matches, false),
      platform, mobileUa: /Mobi/i.test(nav.userAgent || ''),
    }),
    standalone: safe(() => win.matchMedia('(display-mode: standalone)').matches, false) || nav.standalone === true,
  };
}

export function isDismissed(storage) { try { return storage.getItem(DISMISS_KEY) === '1'; } catch { return false; } }
export function setDismissed(storage) { try { storage.setItem(DISMISS_KEY, '1'); } catch { /* ignorar */ } }

// beforeinstallprompt se dispara una sola vez y pronto: se captura desde el arranque (main.jsx) y los
// componentes se suscriben después.
let deferred = null;
const subs = new Set();
const emit = () => subs.forEach((f) => f(deferred));
export function captureInstallPrompt(win = window) {
  win.addEventListener('beforeinstallprompt', (e) => { e.preventDefault(); deferred = e; emit(); });
  win.addEventListener('appinstalled', () => { deferred = null; emit(); });
}
export function getInstallPrompt() { return deferred; }
export function subscribeInstallPrompt(fn) { subs.add(fn); return () => subs.delete(fn); }

// Service worker solo en contexto seguro (HTTPS o localhost); en http plano el navegador no lo permite.
export function registerServiceWorker(win = window) {
  if (!win.isSecureContext || !('serviceWorker' in win.navigator)) return;
  win.addEventListener('load', () => { win.navigator.serviceWorker.register('/sw.js').catch(() => {}); });
}
