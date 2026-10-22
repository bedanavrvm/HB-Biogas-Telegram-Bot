import React, { useEffect, useState } from 'react';
import Button from '@atlaskit/button/default/button';
import Form, { Label } from '@atlaskit/form';
import Heading from '@atlaskit/heading';
import { Box } from '@atlaskit/primitives/compiled/box';
import { Inline } from '@atlaskit/primitives/compiled/inline';
import { Stack } from '@atlaskit/primitives/compiled/stack';
import { Text } from '@atlaskit/primitives/compiled/text';
import Select from '@atlaskit/select';
import { operation, OperationError } from './complaints-operations-transport';

type Preferences = { default_screen: string; default_filters: Record<string, string>; compact_cards: boolean; alert_mode: string };
type Issue = { key: string; reference: string; status: string; can_retry: boolean };
export function WorkspaceSettings({ group, select, close }: { group: string; select: (key: string) => void; close: () => void }) {
  const [preferences, setPreferences] = useState<Preferences>(), [issues, setIssues] = useState<Issue[]>([]), [error, setError] = useState(''), [notice, setNotice] = useState(''), [busy, setBusy] = useState(false);
  useEffect(() => { const controller = new AbortController(); void Promise.all([
    operation<Preferences>(group, 'preferences/', controller.signal), operation<{ issues: Issue[] }>(group, 'recovery/', controller.signal),
  ]).then(([prefs, result]) => { setPreferences(prefs); setIssues(result.issues); }).catch(() => { if (!controller.signal.aborted) setError('Settings could not be loaded. Close this section and try again.'); }); return () => controller.abort(); }, [group]);
  const save = async () => { if (!preferences || busy) return; setBusy(true); setError(''); try { setPreferences(await operation<Preferences>(group, 'preferences/', new AbortController().signal, { preferences })); setNotice('Preferences saved.'); } catch (issue) { setError(issue instanceof OperationError ? issue.message : 'Settings could not be saved. Try again.'); } finally { setBusy(false); } };
  return <Stack space="space.150"><Inline alignBlock="center" spread="space-between" space="space.100"><Heading as="h2" size="medium">Settings</Heading><Button onClick={close}>Close</Button></Inline>{error && <Box role="alert"><Text color="color.text.danger">{error}</Text></Box>}{notice && <Box role="status"><Text>{notice}</Text></Box>}{preferences && <Form onSubmit={save}>{({ formProps }) => <Box as="form" {...formProps}><Stack space="space.150"><Text size="small" color="color.text.subtle">These Complaints preferences apply on your devices.</Text><Box><Label htmlFor="default-status">Default queue</Label><Select inputId="default-status" options={[{ value: 'pending', label: 'Not resolved' }, { value: 'resolved', label: 'Resolved' }, { value: 'all', label: 'All complaints' }]} value={[{ value: preferences.default_filters.status || 'pending', label: preferences.default_filters.status === 'resolved' ? 'Resolved' : preferences.default_filters.status === 'all' ? 'All complaints' : 'Not resolved' }]} onChange={value => setPreferences({ ...preferences, default_filters: { ...preferences.default_filters, status: value?.value || 'pending' } })} /></Box><Inline space="space.100"><Button type="submit" appearance="primary" isLoading={busy}>Save preferences</Button></Inline></Stack></Box>}</Form>}
    <Heading as="h3" size="small">Publication status</Heading>{issues.length === 0 && <Text>There are no pending complaint updates.</Text>}{issues.map(issue => <Inline key={issue.key} spread="space-between" shouldWrap space="space.100"><Stack space="space.050"><Text weight="medium">{issue.reference}</Text><Text size="small">{issue.status === 'failed' ? 'Changes saved. Sheet update needs a retry.' : issue.status === 'suspended' ? 'Changes saved. Ask Complaint IT to enable Sheet updates.' : 'Changes saved. Sheet update is pending.'}</Text></Stack><Button onClick={() => select(issue.key)}>{issue.can_retry ? 'Open to retry' : 'View complaint'}</Button></Inline>)}
  </Stack>;
}
