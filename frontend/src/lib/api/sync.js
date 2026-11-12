// Sincronización: estado, vigilancia, ejecución, hook de un juego y sincronización automática.
import { api } from '../api.js';

export const getStatus = () => api('/api/status');
export const getWatches = () => api('/api/watches');
export const runSync = (game, body) => api(`/api/sync/${encodeURIComponent(game)}`, { method: 'POST', body });
export const hookStatus = (gameId, call = api) => call(`/api/games/${encodeURIComponent(gameId)}/hook-status`);
export const getScheduler = () => api('/api/scheduler');
export const putScheduler = (body) => api('/api/scheduler', { method: 'PUT', body });
export const schedulerHistory = (limit = 200) => api(`/api/scheduler/history?limit=${limit}`);
