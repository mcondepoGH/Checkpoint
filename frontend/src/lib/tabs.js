// Lógica de teclado de las pestañas (sin React, se prueba sin navegador).
// Pestañas (patrón WAI-ARIA): índice al que mueve una tecla, o null si no es de navegación.
export function nextTabIndex(count, index, key) {
  switch (key) {
    case 'ArrowRight':
    case 'ArrowDown':
      return (index + 1) % count;
    case 'ArrowLeft':
    case 'ArrowUp':
      return (index - 1 + count) % count;
    case 'Home':
      return 0;
    case 'End':
      return count - 1;
    default:
      return null;
  }
}
