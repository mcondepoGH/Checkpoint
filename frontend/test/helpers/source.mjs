// Lee un fichero de código con los espacios en blanco colapsados: los tests que comprueban el código fuente
// no dependen así de cómo Prettier reparta las líneas.
import fs from 'node:fs';

export const readFlat = (file) => fs.readFileSync(file, 'utf8').replace(/\s+/g, ' ');
