import React from 'react';
import { createRoot } from 'react-dom/client';
import App from './App.jsx';
import './styles/main.scss';
import { captureInstallPrompt, registerServiceWorker } from './pwa.js';

captureInstallPrompt();
registerServiceWorker();

createRoot(document.getElementById('root')).render(<App />);
