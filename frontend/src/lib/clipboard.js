// Copia al portapapeles. Sin la API moderna (p. ej. HTTP en la LAN) usa un campo y execCommand; `area` es un campo
// ya en pantalla (se selecciona y copia sin crear otro). Devuelve true si copió.
export function copyText(text, area) {
  return (async () => {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      /* HTTP en LAN: sin API de portapapeles */
    }
    const ta = area || document.createElement('textarea');
    if (!area) {
      ta.value = text;
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
    }
    ta.select();
    let ok = false;
    try {
      ok = document.execCommand('copy');
    } catch {
      ok = false;
    }
    if (!area) document.body.removeChild(ta);
    return ok;
  })();
}
