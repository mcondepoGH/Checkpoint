// Versiones guardadas de un juego.
import { api } from '../api.js';

const base = (game) => `/api/versions/${encodeURIComponent(game)}`;
export const listVersions = (game) => api(base(game));
export const getVersionsLimit = (game) => api(`${base(game)}/limit`);
export const restoreVersion = (game, version, source) => api(`${base(game)}/restore`, { method: 'POST', body: { version, source } });
