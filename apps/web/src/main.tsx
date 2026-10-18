import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

import { App } from './App';
import { applyColorMode, getInitialColorMode } from './lib/colorMode';
import './theme/index.scss';

// Set the theme before the first paint to avoid a light flash in dark mode.
applyColorMode(getInitialColorMode());

const root = document.getElementById('root');
if (!root) throw new Error('Missing #root element');

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
