// Perfil del usuario: nombre, foto y API key.
import { api } from '../api.js';

export const getProfile = () => api('/api/profile');
export const putPhoto = (blob) => api('/api/profile/photo', { method: 'PUT', body: blob });
export const deletePhoto = () => api('/api/profile/photo', { method: 'DELETE' });
export const getApiKey = (call = api) => call('/api/profile/apikey');
