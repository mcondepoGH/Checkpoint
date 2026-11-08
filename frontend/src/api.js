// `code`/`params`: contrato de error del backend (detail = {code, params}); sin ellos, `message` es el texto recibido.
export class ApiError extends Error {
  constructor(status, message, data, code, params) {
    super(message); this.status = status; this.data = data;
    if (code) { this.code = code; this.params = params ?? {}; }
  }
}

function msg(detail) {
  if (typeof detail === 'string') return detail;
  if (detail && typeof detail.code === 'string') return detail.code;
  return JSON.stringify(detail);
}

export async function api(path, { method = 'GET', body } = {}) {
  const res = await fetch(path, {
    method,
    credentials: 'same-origin',
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  let data = null;
  try { data = await res.json(); } catch { /* sin cuerpo */ }
  if (!res.ok) {
    const d = data?.detail;
    const coded = d && typeof d === 'object' && typeof d.code === 'string';
    throw new ApiError(res.status, msg(d ?? res.statusText), data, coded ? d.code : undefined, coded ? d.params : undefined);
  }
  return data;
}
