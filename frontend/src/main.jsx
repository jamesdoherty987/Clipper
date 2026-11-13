import React from 'react';
import { createRoot } from 'react-dom/client';
import GTAClipperApp from './StudioApp';
import './styles.css';

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <GTAClipperApp />
  </React.StrictMode>
);
