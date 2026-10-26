import React from 'react';
import { createRoot } from 'react-dom/client';
import '@atlaskit/css-reset';
import { AppProvider } from '@atlaskit/app-provider/app-provider';
import { setGlobalTheme } from '@atlaskit/tokens/set-global-theme';
import { AccessPreview } from './preview';

const root = document.getElementById('root');
if (!root) throw new Error('The access preview needs its root element.');
// Mount the theme before controls: async provider initialization otherwise
// paints light input backgrounds briefly with dark foreground tokens.
// AppProvider owns subsequent theme changes and the system preference listener.
void setGlobalTheme({ colorMode: 'auto' }).then(stopListening => {
  stopListening();
  createRoot(root).render(
  <React.StrictMode>
    <AppProvider defaultColorMode="auto">
      <AccessPreview />
    </AppProvider>
  </React.StrictMode>,
  );
});
