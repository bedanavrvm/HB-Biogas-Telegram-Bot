import React from 'react';
import { createRoot } from 'react-dom/client';
import '@atlaskit/css-reset';
import { AppProvider } from '@atlaskit/app-provider/app-provider';
import { setGlobalTheme } from '@atlaskit/tokens/set-global-theme';
import { consumeInvitation } from './auth-transport';
import { StaffAccess } from './staff-access';
import { ComplaintsWorkspace } from './complaints-workspace';

const invitation = consumeInvitation();
const root = document.getElementById('root');
if (!root) throw new Error('Complaints needs its root element.');
void setGlobalTheme({ colorMode: 'auto' }).then(stopListening => {
  stopListening();
  createRoot(root).render(<React.StrictMode><AppProvider defaultColorMode="auto">
    <StaffAccess invitation={invitation} renderAuthenticated={actions => <ComplaintsWorkspace {...actions} />} />
  </AppProvider></React.StrictMode>);
});
