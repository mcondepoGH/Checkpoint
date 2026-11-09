import React from 'react';
import logo from '../assets/logo-icon.svg';

// Icono de la aplicación (el mismo del favicon y del manifest). Único sitio que lo pinta; `className` da el tamaño.
export default function AppIcon({ className }) {
  return <img src={logo} alt="" aria-hidden="true" className={className} />;
}
