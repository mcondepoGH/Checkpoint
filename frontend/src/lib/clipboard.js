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
    // Se monta junto al elemento enfocado (no en body): al enfocarlo con select(), un contenedor con onBlur (popup del perfil) no ve salir el foco y no se cierra.
    const host = area ? null : document.activeElement?.parentElement || document.body;
    if (!area) {
      ta.value = text;
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      host.appendChild(ta);
    }
    ta.select();
    let ok = false;
    try {
      ok = document.execCommand('copy');
    } catch {
      ok = false;
    }
    if (!area) host.removeChild(ta);
    return ok;
  })();
}
