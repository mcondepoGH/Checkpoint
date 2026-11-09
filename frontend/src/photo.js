// Foto de perfil: validación y recorte (lógica pura, sin tocar window al importar) y preparación con canvas en el navegador.

export const PHOTO_MAX_BYTES = 2 * 1024 * 1024; // entrada máxima; el servidor aplica la misma cota
export const PHOTO_SIZE = 256; // lado de la foto que se sube (px)
export const PHOTO_TYPES = ['image/jpeg', 'image/png', 'image/webp'];
export const PHOTO_ACCEPT = PHOTO_TYPES.join(',');

// Código de error del catálogo (`profile.photo.*`) o null si el fichero vale. Solo mira tipo y tamaño declarados.
export function validatePhotoFile(file) {
  if (!file || !PHOTO_TYPES.includes(file.type)) return 'profile.photo.type';
  if (!(file.size > 0)) return 'profile.photo.empty';
  if (file.size > PHOTO_MAX_BYTES) return 'profile.photo.tooLarge';
  return null;
}

// Cuadrado central de una imagen w x h: {sx, sy, side} (enteros).
export function squareCrop(w, h) {
  const side = Math.floor(Math.min(w, h));
  return { sx: Math.floor((w - side) / 2), sy: Math.floor((h - side) / 2), side };
}

// Lado final: PHOTO_SIZE, o el del recorte si es menor (nunca se amplía).
export function targetSide(side) {
  return Math.max(1, Math.min(PHOTO_SIZE, side));
}

// URL de la foto con la versión como parámetro (cache-busting al cambiarla).
export function photoUrl(photo) {
  return photo && photo.version ? `/api/profile/photo?v=${encodeURIComponent(photo.version)}` : null;
}

function loadBitmap(file) {
  if (typeof createImageBitmap === 'function') return createImageBitmap(file);
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => { URL.revokeObjectURL(url); resolve(img); };
    img.onerror = () => { URL.revokeObjectURL(url); reject(new Error('decode')); };
    img.src = url;
  });
}

const toBlob = (canvas, type, q) => new Promise((resolve) => canvas.toBlob(resolve, type, q));

// Recorta al centro, reduce a PHOTO_SIZE y codifica en WebP (o JPEG si el navegador no sabe WebP). Devuelve un Blob.
export async function prepareAvatar(file) {
  const img = await loadBitmap(file);
  const w = img.width; const h = img.height;
  const { sx, sy, side } = squareCrop(w, h);
  const out = targetSide(side);
  const canvas = document.createElement('canvas');
  canvas.width = out; canvas.height = out;
  const ctx = canvas.getContext('2d');
  ctx.drawImage(img, sx, sy, side, side, 0, 0, out, out);
  if (typeof img.close === 'function') img.close();
  let blob = await toBlob(canvas, 'image/webp', 0.85);
  if (!blob || blob.type !== 'image/webp') blob = await toBlob(canvas, 'image/jpeg', 0.85);
  if (!blob) throw new Error('encode');
  return blob;
}
