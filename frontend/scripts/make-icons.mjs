// Genera los iconos PNG de la PWA (public/icon-192.png, icon-512.png, icon-maskable-512.png, apple-touch-icon.png)
// a partir de la geometría de public/favicon.svg, sin dependencias (zlib de Node). Es un rasterizador propio y
// sencillo: sin brillo (filtro de desenfoque) del SVG. Uso: node scripts/make-icons.mjs
import fs from 'node:fs';
import zlib from 'node:zlib';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const OUT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'public');
const BG = [0x0b, 0x10, 0x20];
const HEX_FILL = [0x11, 0x1a, 0x33];
const STOPS = [
  [0, [0x22, 0xd3, 0xee]],
  [0.5, [0x8b, 0x5c, 0xf6]],
  [1, [0xe8, 0x79, 0xf9]],
];
const HEX = [
  [64, 8],
  [112.5, 36],
  [112.5, 92],
  [64, 120],
  [15.5, 92],
  [15.5, 36],
];
const ARROW = [
  [96.8, 91.8],
  [99.3, 71.1],
  [79.0, 75.7],
];
const ARC = { cx: 65.94, cy: 64, r: 29.5, half: (41.9 * Math.PI) / 180, w: 12 }; // abierto por la derecha

function grad(x, y) {
  // degradado diagonal (0,0)->(128,128)
  const t = Math.min(1, Math.max(0, (x + y) / 256));
  for (let i = 1; i < STOPS.length; i++) {
    if (t <= STOPS[i][0]) {
      const [t0, c0] = STOPS[i - 1];
      const [t1, c1] = STOPS[i];
      const k = (t - t0) / (t1 - t0);
      return c0.map((v, j) => v + (c1[j] - v) * k);
    }
  }
  return STOPS[2][1];
}
function distSeg(px, py, a, b) {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const k = Math.max(0, Math.min(1, ((px - a[0]) * dx + (py - a[1]) * dy) / (dx * dx + dy * dy)));
  return Math.hypot(px - a[0] - k * dx, py - a[1] - k * dy);
}
function inPoly(px, py, P) {
  let c = false;
  for (let i = 0, j = P.length - 1; i < P.length; j = i++) {
    if (P[i][1] > py !== P[j][1] > py && px < ((P[j][0] - P[i][0]) * (py - P[i][1])) / (P[j][1] - P[i][1]) + P[i][0]) c = !c;
  }
  return c;
}
const edgeDist = (px, py, P) => Math.min(...P.map((p, i) => distSeg(px, py, p, P[(i + 1) % P.length])));

// Color (o null = transparente) en coordenadas del lienzo 128x128. scale: tamaño del logo; rounded: esquinas del fondo.
function shade(x, y, scale, rounded) {
  if (rounded) {
    // rect 128 con rx 28
    const qx = Math.max(Math.abs(x - 64) - 36, 0);
    const qy = Math.max(Math.abs(y - 64) - 36, 0);
    if (Math.hypot(qx, qy) > 28) return null;
  }
  const s = 0.9 * scale; // el logo del SVG ya va al 90 %
  const u = (x - 64) / s + 64;
  const v = (y - 64) / s + 64; // a coordenadas del hexágono original
  const sw = 1 / s; // un trazo de n unidades del SVG mide n*s; trabajamos en unidades del SVG
  let col = BG;
  if (inPoly(u, v, HEX)) col = HEX_FILL;
  if (Math.abs(edgeDist(u, v, HEX)) <= 2.5 + 0 * sw) col = grad(u, v);
  const ang = Math.atan2(v - ARC.cy, u - ARC.cx);
  const dr = Math.abs(Math.hypot(u - ARC.cx, v - ARC.cy) - ARC.r);
  const onArc = Math.abs(ang) >= ARC.half && dr <= ARC.w / 2;
  const cap = [-1, 1].some(
    (sgn) => Math.hypot(u - (ARC.cx + ARC.r * Math.cos(ARC.half)), v - (ARC.cy + sgn * ARC.r * Math.sin(ARC.half))) <= ARC.w / 2,
  );
  if (onArc || cap) col = grad(u, v);
  if (inPoly(u, v, ARROW) || edgeDist(u, v, ARROW) <= 1) col = grad(u, v);
  return col;
}

function render(size, { scale = 1, rounded = false }) {
  const N = 3;
  const px = Buffer.alloc(size * size * 4);
  for (let j = 0; j < size; j++)
    for (let i = 0; i < size; i++) {
      let r = 0;
      let g = 0;
      let b = 0;
      let a = 0;
      for (let sy = 0; sy < N; sy++)
        for (let sx = 0; sx < N; sx++) {
          const c = shade(((i + (sx + 0.5) / N) / size) * 128, ((j + (sy + 0.5) / N) / size) * 128, scale, rounded);
          if (c) {
            r += c[0];
            g += c[1];
            b += c[2];
            a++;
          }
        }
      const o = (j * size + i) * 4;
      if (a) {
        px[o] = r / a;
        px[o + 1] = g / a;
        px[o + 2] = b / a;
        px[o + 3] = Math.round((255 * a) / (N * N));
      }
    }
  return px;
}

const crcT = Array.from({ length: 256 }, (_, n) => {
  let c = n;
  for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
  return c >>> 0;
});
const crc = (buf) => {
  let c = 0xffffffff;
  for (const b of buf) c = crcT[(c ^ b) & 255] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
};
function chunk(type, data) {
  const t = Buffer.from(type);
  const len = Buffer.alloc(4);
  len.writeUInt32BE(data.length);
  const c = Buffer.alloc(4);
  c.writeUInt32BE(crc(Buffer.concat([t, data])));
  return Buffer.concat([len, t, data, c]);
}
function png(size, rgba) {
  const raw = Buffer.alloc((size * 4 + 1) * size);
  for (let j = 0; j < size; j++) rgba.copy(raw, j * (size * 4 + 1) + 1, j * size * 4, (j + 1) * size * 4);
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(size, 0);
  ihdr.writeUInt32BE(size, 4);
  ihdr[8] = 8;
  ihdr[9] = 6;
  return Buffer.concat([
    Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]),
    chunk('IHDR', ihdr),
    chunk('IDAT', zlib.deflateSync(raw, { level: 9 })),
    chunk('IEND', Buffer.alloc(0)),
  ]);
}

const JOBS = [
  ['icon-192.png', 192, { rounded: true }],
  ['icon-512.png', 512, { rounded: true }],
  ['icon-maskable-512.png', 512, { scale: 0.7 }], // zona segura: el SO recorta hasta un 20 % por lado
  ['apple-touch-icon.png', 180, { scale: 0.9 }], // iOS pone sus propias esquinas: fondo opaco a sangre
];
for (const [name, size, opt] of JOBS) fs.writeFileSync(path.join(OUT, name), png(size, render(size, opt)));
console.log('iconos generados en', OUT);
