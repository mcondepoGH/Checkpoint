// Comprobación de actualizaciones.
import { api } from '../api.js';

export const getUpdates = () => api('/api/updates');
export const refreshUpdates = () => api('/api/updates?refresh=true');
export const putUpdates = (body) => api('/api/updates', { method: 'PUT', body });
