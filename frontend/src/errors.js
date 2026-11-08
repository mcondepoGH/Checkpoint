// Texto de un error de la API (o de un resultado {ok:false, code, params, message}) en el idioma activo.
// El backend manda `code` + `params`; sin code (errores antiguos u otro origen) se muestra el texto recibido.
// Si hay code pero falta su traducción: `params.reason` (texto del origen) o el propio code.
//
// Causas anidadas (contrato de la fase 3): un param puede ser
//   - un cuerpo de error {code, params}  -> se traduce y se inserta como texto (p. ej. `cause`);
//   - una lista de [{path?, code, params}] -> cada elemento se traduce («ruta: texto») y se unen con «; » (p. ej. `causes`).
// Así `{cause}`/`{causes}` en el catálogo funcionan a cualquier profundidad.
const isBody = (v) => v && typeof v === 'object' && typeof v.code === 'string';

function resolveParams(params, t) {
  if (!params) return params;
  const out = {};
  for (const [k, v] of Object.entries(params)) {
    if (isBody(v)) out[k] = errorText(v, t);
    else if (Array.isArray(v) && v.length && v.every(isBody)) {
      out[k] = v.map((c) => (c.path ? `${c.path}: ` : '') + errorText(c, t)).join('; ');
    } else out[k] = v;
  }
  return out;
}

export function errorText(e, t) {
  if (e?.code) {
    const s = t(e.code, resolveParams(e.params, t));
    if (s !== e.code) return s;
    return e.params?.reason ?? e.code;
  }
  return e?.message ?? String(e);
}

// Error de un campo del formulario: puede llegar como {code, params} (actual) o como texto (antiguo).
export const fieldErrorText = (v, t) => (v && typeof v === 'object' ? errorText(v, t) : v);
