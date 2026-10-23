import React, { useEffect, useState } from 'react';
import Button from '@atlaskit/button/default/button';
import Form, { Label } from '@atlaskit/form';
import Heading from '@atlaskit/heading';
import { Box } from '@atlaskit/primitives/compiled/box';
import { Inline } from '@atlaskit/primitives/compiled/inline';
import { Stack } from '@atlaskit/primitives/compiled/stack';
import { Text } from '@atlaskit/primitives/compiled/text';
import { cssMap } from '@atlaskit/css';
import SectionMessage from '@atlaskit/section-message';
import Select from '@atlaskit/select';
import { operation, OperationError } from './complaints-operations-transport';
import { EmailSchedules } from './complaints-operations-reports';
import { notify } from './browser-interactions';
const styles = cssMap({ form: { width: '100%', maxWidth: '30rem' } });
type Preferences = { default_screen: string; default_filters: Record<string, string>; compact_cards: boolean; alert_mode: string };
export function WorkspaceSettings({ group, branches, reports }: { group: string; branches: string[]; reports: boolean }) {
  const [retry, setRetry] = useState(0), [preferences, setPreferences] = useState<Preferences>(), [error, setError] = useState(''), [notice, setNotice] = useState(''), [busy, setBusy] = useState(false);
  useEffect(()=>{if(notice){notify(notice);setNotice('');}},[notice]);
  useEffect(()=>{if(error)notify(error,'error');},[error]);
  useEffect(() => { let active = true; const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 20000);
    setError(''); void operation<Preferences>(group, 'preferences/', controller.signal).then(value => { if (active) setPreferences(value); }).catch(() => { if (active) setError('Preferences could not be loaded. Try again.'); }).finally(() => clearTimeout(timer));
    return () => { active = false; controller.abort(); clearTimeout(timer); };
  }, [group, retry]);
  const save = async () => { if (!preferences || busy) return; setBusy(true); setError(''); try { setPreferences(await operation<Preferences>(group, 'preferences/', new AbortController().signal, { preferences })); setNotice('Preferences saved.'); } catch (issue) { setError(issue instanceof OperationError ? issue.message : 'Preferences could not be saved. Try again.'); } finally { setBusy(false); } };
  return <Stack space="space.400"><Box xcss={styles.form}><Stack space="space.200"><Heading as="h2" size="medium">Your preferences</Heading><Text color="color.text.subtle">Saved to your account for this app.</Text>
    {error && <Box role="alert"><SectionMessage appearance="error" title="Preferences unavailable" headingLevel="h3"><Text>{error}</Text><Button onClick={() => setRetry(value => value + 1)}>Retry settings</Button></SectionMessage></Box>}
    {notice && <Box role="status"><SectionMessage appearance="success"><Text>{notice}</Text></SectionMessage></Box>}
    {!preferences && !error && <Text>Loading preferences…</Text>}
    {preferences && <Form onSubmit={save}>{({formProps}) => <Box as="form" {...formProps}><Stack space="space.250"><Box role="group" aria-labelledby="default-status-label"><Text id="default-status-label" weight="medium">Default status</Text><Inline shouldWrap space="space.050">{[{value:'pending',label:'Open + Reopened'},{value:'resolved',label:'Closed'},{value:'all',label:'All complaints'}].map(option => <Button key={option.value} isSelected={(preferences.default_filters.status || 'pending') === option.value} onClick={() => setPreferences({...preferences,default_filters:{...preferences.default_filters,status:option.value}})}>{option.label}</Button>)}</Inline></Box>
    <Box><Label htmlFor="default-branch">Default branch</Label><Select inputId="default-branch" options={[{value:'',label:'All branches'},...Array.from(new Set([...branches,preferences.default_filters.branch || ''])).filter(Boolean).map(value=>({value,label:value}))]} value={{value:preferences.default_filters.branch||'',label:preferences.default_filters.branch||'All branches'}} onChange={option=>setPreferences({...preferences,default_filters:{...preferences.default_filters,branch:option?.value||''}})}/></Box><Text size="small" color="color.text.subtle">Defaults apply when you open Complaints. Links keep their selected status.</Text><Inline><Button type="submit" appearance="primary" isLoading={busy}>Save preferences</Button></Inline></Stack></Box>}</Form>}
  </Stack></Box>{reports && <EmailSchedules group={group}/>}</Stack>;
}
