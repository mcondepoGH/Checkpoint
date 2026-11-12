import { recordText } from '#src/lib/errors.js';

// Lógica pura del registro automático (sin React): se prueba sin navegador.

// Origen (lo que se ve en el registro): 3 etiquetas que agrupan los disparadores (`trigger` del backend: manual, scheduled,
// startup, hook, hook_closed) sin tocar el valor guardado. El panel de Lanzadores sigue usando `autolog.trigger.hook|hook_closed`.
// Clave `autolog.origin.<origen>`; el color lo pone el tono `<origen>` de Pill.
export const ORIGINS = ['manual', 'scheduled', 'launcher'];
const ORIGIN_OF = { manual: 'manual', scheduled: 'scheduled', startup: 'scheduled', hook: 'launcher', hook_closed: 'launcher' };
export const originOf = (trigger) => ORIGIN_OF[trigger] || null; // null: disparador desconocido (se muestra tal cual)

// Filtro por origen del registro: 'all' o uno de ORIGINS. Un valor desconocido no filtra. Las entradas de disparador
// desconocido solo salen en «Todos».
export const FILTERS = ['all', ...ORIGINS];
export const filterEntries = (entries, filter) =>
  ORIGINS.includes(filter) ? entries.filter((e) => originOf(e.trigger) === filter) : entries;

// Entrada que explica por qué NO hubo checkpoint de cierre (códigos err.hook.*): omitida (`skipped`) o con error. Lleva icono además del texto.
export const isHookNote = (e) =>
  typeof e?.code === 'string' && e.code.startsWith('err.hook.') && (e.result === 'skipped' || e.result === 'error');

// Icono del mensaje según el resultado (omitida: salto; error, abortada, conflicto y parcial: alerta). `ok` y desconocidos, sin icono.
export const MSG_ICON = { error: 'alert', aborted: 'alert', conflict: 'alert', partial: 'alert', skipped: 'skip' };

// Más de este número de juegos: el detalle de los correctos se pliega (omitidos y errores siempre visibles).
export const FOLD_AFTER = 3;

// Resumen de resultados de una lista de juegos: «12 correctos, 1 error» (orden fijo; resultado desconocido tal cual).
const COUNT_ORDER = ['ok', 'error', 'aborted', 'skipped', 'conflict', 'partial'];
export function countSummary(games, t) {
  const n = {};
  for (const [, d] of games) n[d.result] = (n[d.result] || 0) + 1;
  const keys = [...COUNT_ORDER.filter((k) => n[k]), ...Object.keys(n).filter((k) => !COUNT_ORDER.includes(k))];
  return keys
    .map((k) => (COUNT_ORDER.includes(k) ? t(`autolog.count.${k}_${n[k] === 1 ? 'one' : 'other'}`, { n: n[k] }) : `${n[k]} ${k}`))
    .join(', ');
}

// Qué pintar en el detalle de una entrada (ver EntryDetail): mensaje propio solo si ningún juego lo dice ya,
// etiquetas si hay mezcla de resultados, y filas visibles (con pliegue de los `ok` si hay más de FOLD_AFTER juegos).
export function detailModel(e, t, open) {
  const games = Object.entries(e.games || {});
  const entryText = recordText(e, t);
  const gameTexts = games.map(([, d]) => recordText(d, t));
  const showEntryMsg = entryText && !gameTexts.some((x) => x && entryText.includes(x));
  const results = new Set([e.result, ...games.map(([, d]) => d.result)]);
  const labelled = results.size > 1; // algún juego difiere de la cabecera (o entre sí): todas las filas llevan etiqueta
  const fold = games.length > FOLD_AFTER;
  const rows = games.map(([g, d], i) => ({ g, d, text: gameTexts[i] })).filter((r) => !fold || open || r.d.result !== 'ok');
  return { games, entryText, showEntryMsg, labelled, fold, rows };
}
