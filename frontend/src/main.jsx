import React from 'react';
import { createRoot } from 'react-dom/client';
import App from './App.jsx';
import '#src/styles/main.scss';
import { registerServiceWorker } from '#src/lib/pwa.js';

registerServiceWorker();

createRoot(document.getElementById('root')).render(<App />);
