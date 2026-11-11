// Configuración (config.yaml), copias, dispositivos y clave pública SSH.
import { api } from '../api.js';

export const getConfig = () => api('/api/config');
export const saveConfig = (config, baseVersion) => api('/api/config', { method: 'PUT', body: { config, base_version: baseVersion } });
export const validateConfig = (config) => api('/api/config/validate', { method: 'POST', body: { config } });
export const diffConfig = (body) => api('/api/config/diff', { method: 'POST', body }); // { config } o { backup }
export const configYaml = (config) => api('/api/config/yaml', { method: 'POST', body: { config } });
export const listBackups = () => api('/api/config/backups');
export const restoreBackup = (name, baseVersion) => api('/api/config/restore', { method: 'POST', body: { name, base_version: baseVersion } });
export const testDevice = (body) => api('/api/devices/test', { method: 'POST', body });
export const getPublicKey = () => api('/api/ssh/public-key');
