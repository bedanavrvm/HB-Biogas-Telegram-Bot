import React, { useEffect, useRef, useState } from 'react';
import Button from '@atlaskit/button/default/button';
import Form, { Label } from '@atlaskit/form';
import Heading from '@atlaskit/heading';
import { Grid } from '@atlaskit/primitives/compiled/grid';
import { Box } from '@atlaskit/primitives/compiled/box';
import { Inline } from '@atlaskit/primitives/compiled/inline';
import { Stack } from '@atlaskit/primitives/compiled/stack';
import { Text } from '@atlaskit/primitives/compiled/text';
import { cssMap } from '@atlaskit/css';
import SectionMessage from '@atlaskit/section-message';
import { AdaptiveSelect as Select, ActionButton } from './complaints-ui';
import { operation, OperationError } from './complaints-operations-transport';
import { EmailSchedules } from './complaints-operations-reports';
import { notify } from './browser-interactions';
import { useRetainedValue, type RecoverySlot } from './workspace-recovery';
import { TaskRecovery, useWorkspaceTask } from './workspace-task';
const styles = cssMap({ form: { width: '100%', maxWidth: '32rem' },layout:{gridTemplateColumns:'repeat(auto-fit, minmax(min(100%, 26rem), 1fr))',alignItems:'start'} });
type Preferences = { default_screen: string; default_filters: Record<string, string>; compact_cards: boolean; alert_mode: string };
export function WorkspaceSettings({ group, branches, reports, slot, markDirty }: { group: string; branches: string[]; reports: boolean; slot: RecoverySlot; markDirty: (dirty: boolean, pending?: boolean) => void }) {
  const [retry, setRetry] = useState(0), [error, setError] = useState(''), [notice, setNotice] = useState('');
  const [preferences, setPreferences] = useRetainedValue<Preferences | undefined>(slot, 'preferences', undefined);
  const [saved, setSaved] = useRetainedValue<Preferences | undefined>(slot, 'savedPreferences', undefined);
  const scheduleState = useRef({dirty:false,pending:false});
  const state = useWorkspaceTask<Preferences>(group, slot, 'preferencesSave', value=>{setPreferences(value);setSaved(value);setNotice('Preferences saved.');});
  const busy=state.busy||state.uncertain;
  const preferenceDirty=Boolean(preferences && JSON.stringify(preferences)!==JSON.stringify(saved));
  const updateDirty=()=>markDirty(preferenceDirty||scheduleState.current.dirty,state.busy||state.uncertain||scheduleState.current.pending);
  useEffect(updateDirty,[preferenceDirty,state.busy,state.uncertain]);
  useEffect(()=>{if(notice){notify(notice);setNotice('');}},[notice]);
  useEffect(()=>{if(error)notify(error,'error');},[error]);
  useEffect(() => { let active = true; const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 20000);
    setError(''); void operation<Preferences>(group, 'preferences/', controller.signal).then(value => { if (active && !slot.read().preferences) {setPreferences(value);setSaved(value);} }).catch(() => { if (active) setError('Preferences could not be loaded. Try again.'); }).finally(() => clearTimeout(timer));
    return () => { active = false; controller.abort(); clearTimeout(timer); };
  }, [group, retry]);
  const save = () => { if (preferences && !busy) return state.save('preferences/', {preferences, expected: saved}); };
  return <Grid xcss={styles.layout} gap="space.400"><Box xcss={styles.form}><Stack space="space.200"><Heading as="h2" size="medium">Your preferences</Heading><Text color="color.text.subtle">Saved to your account for this app.</Text>
    {error && <Box role="alert"><SectionMessage appearance="error" title="Preferences unavailable" headingLevel="h3"><Text>{error}</Text><Button onClick={() => setRetry(value => value + 1)}>Retry settings</Button></SectionMessage></Box>}
    {notice && <Box role="status"><SectionMessage appearance="success"><Text>{notice}</Text></SectionMessage></Box>}
    {!preferences && !error && <Text>Loading preferences…</Text>}
    <TaskRecovery state={state}/>
    {state.error instanceof OperationError&&state.error.status===409&&<Button onClick={()=>{void operation<Preferences>(group,'preferences/',new AbortController().signal).then(value=>{setSaved(value);state.reset();notify('Saved preferences reloaded. Your edits are retained; review them before saving.','information');}).catch(()=>setError('Saved preferences could not be loaded. Try again.'));}}>Reload saved preferences</Button>}
    {preferences && <Form onSubmit={save}>{({formProps}) => <Box as="form" {...formProps}><Stack space="space.250"><Box><Label htmlFor="default-status">Default status</Label><Select inputId="default-status" isDisabled={busy} options={[{value:'pending',label:'Open + Reopened'},{value:'resolved',label:'Closed'},{value:'all',label:'All complaints'}]} value={{value:preferences.default_filters.status||'pending',label:({pending:'Open + Reopened',resolved:'Closed',all:'All complaints'} as Record<string,string>)[preferences.default_filters.status||'pending']}} onChange={option=>{if(option)setPreferences({...preferences,default_filters:{...preferences.default_filters,status:option.value}});}}/></Box>
    <Box><Label htmlFor="default-branch">Default branch</Label><Select inputId="default-branch" isDisabled={busy} options={[{value:'',label:'All branches'},...Array.from(new Set([...branches,preferences.default_filters.branch || ''])).filter(Boolean).map(value=>({value,label:value}))]} value={{value:preferences.default_filters.branch||'',label:preferences.default_filters.branch||'All branches'}} onChange={option=>setPreferences({...preferences,default_filters:{...preferences.default_filters,branch:option?.value||''}})}/></Box><Text size="small" color="color.text.subtle">Defaults apply when you open Complaints. Links keep their selected status.</Text><Inline><ActionButton type="submit" isDisabled={state.uncertain} isLoading={state.busy}>Save preferences</ActionButton></Inline></Stack></Box>}</Form>}
  </Stack></Box>{reports && <EmailSchedules group={group} slot={slot} markDirty={(dirty,pending=false)=>{scheduleState.current={dirty,pending};updateDirty();}}/>}</Grid>;
}
