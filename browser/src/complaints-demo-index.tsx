import React, { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import '@atlaskit/css-reset';
import { AppProvider } from '@atlaskit/app-provider/app-provider';
import Button from '@atlaskit/button/default/button';
import { cssMap } from '@atlaskit/css';
import { Label } from '@atlaskit/form';
import Heading from '@atlaskit/heading';
import { Root } from '@atlaskit/navigation-system/layout/root';
import { Main } from '@atlaskit/navigation-system/layout/main';
import { TopNav, TopNavStart } from '@atlaskit/navigation-system/layout/top-nav';
import { Box } from '@atlaskit/primitives/compiled/box';
import { Inline } from '@atlaskit/primitives/compiled/inline';
import { Stack } from '@atlaskit/primitives/compiled/stack';
import { Text } from '@atlaskit/primitives/compiled/text';
import SectionMessage from '@atlaskit/section-message';
import Select from '@atlaskit/select';
import { setGlobalTheme } from '@atlaskit/tokens/set-global-theme';
import { ComplaintsWorkspace } from './complaints-workspace';
import { demoJSON, type DemoCase, type DemoContext, type Saved } from './complaints-demo-api';
import { CaseActions, CreateComplaint } from './complaints-demo-forms';

const styles = cssMap({ role: { minWidth: '15rem', maxWidth: '100%' } });
const purposes: Record<string, string> = {
  officer: 'Record complaints, complete missing details and attach evidence.',
  manager: 'Review cases, complete details, attach evidence and reopen resolved complaints.',
  hb: 'Add service feedback, attach evidence and resolve complaints.',
  it: 'Technical override within the assigned Complaints workspaces.',
  portal: 'Portal HB access supplies no Complaint Cases authority.',
};
function Demo() {
  const [role, setRole] = useState('officer');
  const [boot, setBoot] = useState<{ role: string; data: DemoContext } | null>(null);
  const [view, setView] = useState<'queue' | 'create' | 'closed'>('queue');
  const [error, setError] = useState<Error | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const [focus, setFocus] = useState('');
  const [group, setGroup] = useState('');
  const [version, setVersion] = useState(0);
  const context = boot?.role === role ? boot.data : null;
  const read = useMemo(() => <T,>(path: string, signal: AbortSignal) => demoJSON<T>(role, path, { signal }), [role]);
  useEffect(() => {
    const controller = new AbortController();
    setError(null);
    void demoJSON<DemoContext>(role, 'context/', { signal: controller.signal }).then(data => setBoot({ role, data })).catch(failure => { if (!controller.signal.aborted) setError(failure as Error); });
    return () => controller.abort();
  }, [role]);
  const saved = (result: Saved) => { setFocus(result.case.reference); setGroup(result.case.group); setNotice(result.message); setVersion(value => value + 1); setView('queue'); };
  const reset = async () => {
    if (!context || busy) return;
    setBusy(true); setError(null);
    try {
      const result = await demoJSON<{ epoch: number; message: string }>(role, 'reset/', { body: { epoch: context.epoch, request_key: crypto.randomUUID() } });
      setBoot({ role, data: { ...context, epoch: result.epoch } }); setFocus(''); setGroup(''); setNotice(result.message); setVersion(value => value + 1); setView('queue');
    } catch (failure) { setError(failure as Error); }
    finally { setBusy(false); }
  };
  const toolbar = <Stack space="space.100">
    <Inline space="space.150" spread="space-between" alignBlock="end" shouldWrap>
      <Box xcss={styles.role}><Label htmlFor="demo-role">Demo role</Label><Select inputId="demo-role" options={boot?.data.personas || []} value={boot?.data.personas.find(option => option.value === role)} isDisabled={busy} onChange={option => { setRole(option?.value || 'officer'); setView('queue'); setNotice(''); }} /></Box>
      <Text size="small" color="color.text.subtle">{purposes[role]}</Text>
      <Inline space="space.100" shouldWrap>{context?.can_create && view === 'queue' && <Button appearance="primary" isDisabled={busy} onClick={() => { setView('create'); setNotice(''); }}>New complaint</Button>}<Button appearance="subtle" isDisabled={busy || !context} onClick={() => void reset()}>Reset demo</Button></Inline>
    </Inline>
    {notice && <Box role="status"><SectionMessage title="Demo action saved" appearance="success" headingLevel="h2"><Text as="p">{notice}</Text></SectionMessage></Box>}
    {error && <Box role="alert"><SectionMessage title="Demo request unavailable" appearance="error" headingLevel="h2"><Text as="p">{error.message}</Text></SectionMessage></Box>}
  </Stack>;
  if (context && view === 'queue') return <ComplaintsWorkspace key={`${role}-${version}`} demo toolbar={toolbar} read={read} initialQuery={focus} initialStatus={focus ? 'all' : 'pending'} initialGroup={group}
    detailExtension={item => <CaseActions key={`${role}-${item.key}`} role={role} item={item as DemoCase} onSaved={saved} setBusy={setBusy} />} signOut={() => setView('closed')} recheck={() => setView('closed')} />;
  if (context && view === 'create') return <CreateComplaint key={role} role={role} context={context} toolbar={toolbar} onSaved={saved} onCancel={() => setView('queue')} setBusy={setBusy} />;
  return <Root><TopNav><TopNavStart sideNavToggleButton={null}><Text weight="bold">JBL Staff workspace</Text></TopNavStart></TopNav>
    <Main><Box padding="space.400"><Stack space="space.200"><Heading as="h1" size="large">Complaints demo</Heading>{toolbar}
      <Text>{context ? 'Synthetic role-based Complaints journeys. Changes and uploads reset on server restart.' : 'Loading demo roles...'}</Text>
      <Box><Button appearance="primary" isDisabled={!context} onClick={() => setView('queue')}>Open demo</Button></Box>
    </Stack></Box></Main>
  </Root>;
}
const root = document.getElementById('root');
if (!root) throw new Error('Complaints demo needs its root element.');
void setGlobalTheme({ colorMode: 'auto' }).then(stopListening => {
  stopListening();
  createRoot(root).render(<React.StrictMode><AppProvider defaultColorMode="auto"><Demo /></AppProvider></React.StrictMode>);
});
