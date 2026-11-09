// Foto de perfil: validación y recorte (lógica pura).
import test from 'node:test';
import assert from 'node:assert/strict';
import { PHOTO_MAX_BYTES, PHOTO_SIZE, photoUrl, squareCrop, targetSide, validatePhotoFile } from '../src/photo.js';

test('validatePhotoFile: tipos permitidos, vacío y tamaño máximo', () => {
  assert.equal(validatePhotoFile({ type: 'image/jpeg', size: 1000 }), null);
  assert.equal(validatePhotoFile({ type: 'image/png', size: 1000 }), null);
  assert.equal(validatePhotoFile({ type: 'image/webp', size: PHOTO_MAX_BYTES }), null);
  assert.equal(validatePhotoFile({ type: 'image/webp', size: PHOTO_MAX_BYTES + 1 }), 'profile.photo.tooLarge');
  assert.equal(validatePhotoFile({ type: 'image/gif', size: 10 }), 'profile.photo.type');
  assert.equal(validatePhotoFile({ type: 'image/svg+xml', size: 10 }), 'profile.photo.type');
  assert.equal(validatePhotoFile({ type: '', size: 10 }), 'profile.photo.type');
  assert.equal(validatePhotoFile(null), 'profile.photo.type');
  assert.equal(validatePhotoFile({ type: 'image/png', size: 0 }), 'profile.photo.empty');
});

test('squareCrop: cuadrado central en apaisada, vertical y cuadrada', () => {
  assert.deepEqual(squareCrop(400, 200), { sx: 100, sy: 0, side: 200 });
  assert.deepEqual(squareCrop(200, 400), { sx: 0, sy: 100, side: 200 });
  assert.deepEqual(squareCrop(300, 300), { sx: 0, sy: 0, side: 300 });
  assert.deepEqual(squareCrop(101, 50), { sx: 25, sy: 0, side: 50 });
});

test('targetSide: reduce a 256 y no amplía', () => {
  assert.equal(PHOTO_SIZE, 256);
  assert.equal(targetSide(4000), 256);
  assert.equal(targetSide(256), 256);
  assert.equal(targetSide(100), 100);
  assert.equal(targetSide(0), 1);
});

test('photoUrl: versión como parámetro; sin foto, null', () => {
  assert.equal(photoUrl(null), null);
  assert.equal(photoUrl({ version: 'a b' }), '/api/profile/photo?v=a%20b');
  assert.equal(photoUrl({ version: 'abc123' }), '/api/profile/photo?v=abc123');
});
