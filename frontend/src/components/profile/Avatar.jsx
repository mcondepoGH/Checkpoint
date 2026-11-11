import React, { useEffect, useState } from 'react';
import Icon from '#src/components/ui/Icon.jsx';

// Foto de perfil o, si no hay (o falla al cargar), la silueta de usuario. `size`: 'sm' (botón de la cabecera) | 'lg' (popup).
export default function Avatar({ src, size = 'sm' }) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [src]);
  return (
    <span className={`avatar avatar-${size}`}>
      {src && !failed ? (
        <img src={src} alt="" aria-hidden="true" width="256" height="256" onError={() => setFailed(true)} />
      ) : (
        <Icon name="user" />
      )}
    </span>
  );
}
