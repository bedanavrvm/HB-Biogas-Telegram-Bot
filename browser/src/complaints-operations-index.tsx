import React from 'react';
import { createRoot } from 'react-dom/client';
import '@atlaskit/css-reset';
import { AppProvider } from '@atlaskit/app-provider/app-provider';
import { setGlobalTheme } from '@atlaskit/tokens/set-global-theme';
import { consumeInvitation } from './auth-transport';
import { StaffAccess } from './staff-access';
import { ComplaintsOperationsWorkspace } from './complaints-operations-workspace';
import { WorkspaceRecovery } from './workspace-recovery';
import { initialColorMode, ToastHost } from './browser-interactions';

const invitation = consumeInvitation();
const recovery = new WorkspaceRecovery();
const clearRecovery = () => recovery.clear();
const root = document.getElementById('root');
if (!root) throw new Error('The staff workspace needs its root element.');
const colorMode = initialColorMode();
void setGlobalTheme({ colorMode }).then(stopListening => {
  stopListening();
  createRoot(root).render(<React.StrictMode><AppProvider defaultColorMode={colorMode}><ToastHost/><StaffAccess invitation={invitation} retainWorkspaceOnNetworkError onLogout={clearRecovery} renderAuthenticated={actions => <ComplaintsOperationsWorkspace {...actions} signOut={() => { recovery.clear(); actions.signOut(); }} recovery={recovery} />} /></AppProvider></React.StrictMode>);
});
