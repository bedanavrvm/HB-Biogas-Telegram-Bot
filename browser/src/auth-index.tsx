import React from 'react';
import { createRoot } from 'react-dom/client';
import '@atlaskit/css-reset';
import { AppProvider } from '@atlaskit/app-provider/app-provider';
import { setGlobalTheme } from '@atlaskit/tokens/set-global-theme';
import { StaffAccess } from './staff-access';

const root = document.getElementById('root');
if (!root) throw new Error('Staff access needs its root element.');
void setGlobalTheme({ colorMode: 'auto' }).then(stopListening => {
  stopListening();
  createRoot(root).render(
    <React.StrictMode>
      <AppProvider defaultColorMode="auto"><StaffAccess /></AppProvider>
    </React.StrictMode>,
  );
});
