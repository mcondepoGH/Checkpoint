// Nombre visible de un juego/dispositivo. Las claves de config.games/devices son ids internos: solo sirven
// como clave y ruta; en pantalla siempre el nombre (el id solo si el elemento no tiene nombre).
export const labelOf = (items, id) => (items?.[id]?.name || '').trim() || id;
