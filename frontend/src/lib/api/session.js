// Sesión y datos públicos: /api/session, /api/login, /api/logout, /api/public.
import { api } from '../api.js';

export const getSession = () => api('/api/session');
export const login = (user, password) => api('/api/login', { method: 'POST', body: { user, password } });
export const logout = () => api('/api/logout', { method: 'POST' });
export const getPublic = () => api('/api/public');
