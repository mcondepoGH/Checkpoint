// Texto de un error de la API (o de un resultado {ok:false, code, params, message}) en el idioma activo.
// El backend manda `code` + `params`; sin code (errores antiguos u otro origen) se muestra el texto recibido.
// Si hay code pero falta su traducción: `params.reason` (texto del origen) o el propio code.
export function errorText(e, t) {
  if (e?.code) {
    const s = t(e.code, e.params);
    if (s !== e.code) return s;
    return e.params?.reason ?? e.code;
  }
  return e?.message ?? String(e);
}
