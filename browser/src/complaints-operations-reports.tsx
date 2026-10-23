import React, { useEffect, useRef, useState } from 'react';
import Button from '@atlaskit/button/default/button';
import { cssMap } from '@atlaskit/css';
import Form, { Label } from '@atlaskit/form';
import Heading from '@atlaskit/heading';
import { Box } from '@atlaskit/primitives/compiled/box';
import { Grid } from '@atlaskit/primitives/compiled/grid';
import { Inline } from '@atlaskit/primitives/compiled/inline';
import { Stack } from '@atlaskit/primitives/compiled/stack';
import { Text } from '@atlaskit/primitives/compiled/text';
import SectionMessage from '@atlaskit/section-message';
import { AdaptiveSelect as Select, ActionButton } from './complaints-ui';
import Textfield from '@atlaskit/textfield';
import { token } from '@atlaskit/tokens';
import { operation, OperationError, download } from './complaints-operations-transport';
import { ReportCharts, type ReportSummary, type ReportSelection } from './complaints-report-charts';
import { ReportTable, type ReportRow } from './complaints-report-table';
import { ReportMetrics, type PreviousSummary } from './complaints-report-metrics';
import { ActionMenu, DialogFooter, DialogStatus, DraftStatus } from './complaints-ui';
import { TaskDialog, complaintCount, confirmAction } from './complaints-ui';
import { reportLocation, type ReportLocation } from './workspace-navigation';
import { ReportFilters } from './complaints-report-filters';
import { notify } from './browser-interactions';
import { useRetainedValue, type RecoverySlot } from './workspace-recovery';
import { TaskRecovery, TaskSession, useWorkspaceTask } from './workspace-task';
const styles = cssMap({
    full: { width: '100%', minWidth: 0 },
  columns: { gridTemplateColumns: 'repeat(1, minmax(0, 1fr))', '@media (min-width: 48rem)': { gridTemplateColumns: 'repeat(2, minmax(0, 1fr))' }, alignItems: 'start' },
  table: { minWidth: 0 }, form: { width: '100%', maxWidth: '30rem' },
});
type Result = { summary: ReportSummary; previous: PreviousSummary | null; table: {results: ReportRow[]; count: number; page: number; page_size: number} };
type Schedule = { id: string; revision?: number; title: string; preset: string; frequency: string; send_time: string; active: boolean; skip_empty: boolean; recipients: string[]; group_configuration: number; branch: string };
type EmailSettings = { schedules: Schedule[]; preset_options: {value: string; label: string}[]; branches_by_group: Record<string, {value: string; label: string}[]> };
function errorText(error: unknown) { return error instanceof OperationError ? error.message : 'Check your connection and try again. Your entries are retained.'; }
function Selection({ id, label, value, options, change }: {id: string; label: string; value: string; options: {value: string; label: string}[]; change: (value: string) => void}) {
  const hint=id==='report-basis'?'Changes the totals and results table. Each chart explains its dates under About this chart.':'';
  return <Box><Label htmlFor={id}>{hint?<Box as="span" title={hint}>{label}</Box>:label}</Label><Select inputId={id} aria-describedby={hint?id+'-help':undefined} value={options.find(item=>item.value===value)||null} options={options} onChange={item=>change(item?.value||'')}/>{hint&&<Box as="span" hidden id={id+'-help'}>{hint}</Box>}</Box>;
}
function DateInput({ id, label, value, change, type = 'text' }: {id: string; label: string; value: string; change: (value: string)=>void; type?: string}) {
  return <Box><Label htmlFor={id}>{label}</Label><Textfield id={id} type={type} value={value} onChange={event=>change(event.currentTarget.value)}/></Box>;
}
const reportViews=['overview','turnaround','follow-up'];
export function Reports({group,refresh,location,change,open,slot,markDirty}:{group:string;refresh:number;location:ReportLocation;change:(value:ReportLocation)=>void;open:(key:string)=>void;slot:RecoverySlot;markDirty:(dirty:boolean,pending?:boolean)=>void}) {
  const emailFormId=React.useId();
  const {view,grouping,status,from,to,branch,category,basis,page,range}=location;
  const latest=useRef(location); latest.current=location;
  const update=(values:Partial<ReportLocation>)=>{const next={...latest.current,...values};latest.current=next;change(next);};
  const [selection,setSelection]=useState<(ReportSelection & {source:string})>(),[result,setResult]=useState<Result>(),[error,setError]=useState<unknown>(),[loading,setLoading]=useState(true),[retry,setRetry]=useState(0);
  const [exportOpen,setExportOpen]=useRetainedValue(slot,'exportOpen',false),[emailOpen,setEmailOpen]=useRetainedValue(slot,'emailOpen',false),[address,setAddress]=useRetainedValue(slot,'emailAddress',''),[delivery,setDelivery]=useRetainedValue(slot,'delivery',''),[message,setMessage]=useRetainedValue(slot,'emailMessage',''),[busy,setBusy]=useState(false),[sort,setSort]=useState('-date_reported');
  const [emailKey,setEmailKey]=useRetainedValue(slot,'emailKey','');
  const [emailFilters,setEmailFilters]=useRetainedValue<Record<string,unknown>|undefined>(slot,'emailFilters',undefined);
  const signIn=React.useContext(TaskSession);
  const emailTask=useWorkspaceTask<{delivery_id:string;status:string;issue:string}>(group,slot,'reportEmail',data=>{setDelivery(data.delivery_id);const text=data.issue||(data.status==='delivered'?'Report delivered.':data.status==='failed'?'Report delivery failed. Check delivery for details.':'Report queued for email delivery.');setMessage(text);notify(text,data.status==='failed'?'error':data.status==='delivered'?'success':'information');});
  useEffect(()=>markDirty(emailOpen&&Boolean(address)&&!delivery,busy||emailTask.busy||emailTask.uncertain),[emailOpen,address,delivery,busy,emailTask.busy,emailTask.uncertain]);
  const table=useRef<HTMLDivElement>(null), focusTable=useRef(false), sourceRef=useRef('');
  const [typedSearch,setTypedSearch]=useState(''),[search,setSearch]=useState(''),[actionError,setActionError]=useState<unknown>();
  useEffect(()=>{const timer=setTimeout(()=>setSearch(typedSearch.trim()),350);return()=>clearTimeout(timer);},[typedSearch]);
  const baseFilters={status,category,branch,date_from:from,date_to:to,date_basis:basis},source=JSON.stringify([group,baseFilters,grouping,view]),applied=selection?.source===source?selection:undefined;
  const filters={...baseFilters,...applied?.filters,...(search?{search}:{})},requestKey=JSON.stringify([source,applied,page,refresh,retry,sort,search]);
  useEffect(()=>{const controller=new AbortController();let active=true;const timer=setTimeout(()=>controller.abort(),20000);
    if(sourceRef.current!==source)setResult(undefined);setLoading(true);setError(undefined);
    void operation<Result>(group,'reports/',controller.signal,{...baseFilters,selection:applied?.filters||{},granularity:grouping,page,sort,table_search:search}).then(data=>{if(active){sourceRef.current=source;setResult(data);setLoading(false);if(focusTable.current){requestAnimationFrame(()=>{table.current?.focus({preventScroll:true});table.current?.scrollIntoView({block:'start',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});});focusTable.current=false;}}}).catch(issue=>{if(active){setLoading(false);setError(issue);notify(errorText(issue),'error');}}).finally(()=>clearTimeout(timer));
    return()=>{active=false;controller.abort();clearTimeout(timer);};
  },[group,requestKey]);
  const exportFile=async(scope:string)=>{if(busy||emailTask.busy||emailTask.uncertain)return;setBusy(true);setActionError(undefined);try{await download(group,'reports/export/',{scope,filters,client_request_id:crypto.randomUUID()});setExportOpen(false);notify('Excel file ready. Your browser handles the download.','information');}catch(issue){setActionError(issue);notify(errorText(issue),'error');}finally{setBusy(false);}};
  const sendEmail=async(check=false)=>{if(busy||emailTask.busy||emailTask.uncertain)return;setActionError(undefined);
    if(!check){if(delivery)return;const key=emailKey||crypto.randomUUID(),scope=emailFilters||structuredClone(filters);setEmailKey(key);setEmailFilters(scope);await emailTask.save('reports/email/',{email:address,filters:scope,client_request_id:key});return;}
    setBusy(true);const control=new AbortController(),timer=setTimeout(()=>control.abort(),20000);
    try{const data=await operation<{delivery_id:string;status:string;issue:string}>(group,'reports/email/',control.signal,{action:'status',delivery_id:delivery});const text=data.issue||(data.status==='delivered'?'Report delivered.':data.status==='failed'?'Report delivery failed. Check delivery for details.':`Report ${data.status}.`);setMessage(text);notify(text,data.status==='failed'?'error':data.status==='delivered'?'success':'information');}catch(issue){setActionError(issue);notify(errorText(issue),'error');}finally{clearTimeout(timer);setBusy(false);}
  };
  const select=(value:ReportSelection)=>{setSelection({...value,source});update({page:1});focusTable.current=true;};
  const reportKey=(event:React.KeyboardEvent)=>{
    const index=reportViews.indexOf(view),next=event.key==='ArrowRight'?(index+1)%3:event.key==='ArrowLeft'?(index+2)%3:event.key==='Home'?0:event.key==='End'?2:-1;
    if(next<0)return;event.preventDefault();update({view:reportViews[next],page:1});requestAnimationFrame(()=>document.getElementById('report-view-'+reportViews[next])?.focus());
  };
  const content = <Stack xcss={styles.full} space="space.300">
    {Boolean(error)&&<Box role="alert"><SectionMessage appearance="error" title="Report could not be loaded" headingLevel="h2"><Text>{errorText(error)}</Text><Button onClick={()=>setRetry(value=>value+1)}>Retry report</Button></SectionMessage></Box>}
    {loading&&<Box role="status"><Text>Loading report…</Text></Box>}
    {result&&sourceRef.current===source&&<>
      <ReportMetrics summary={result.summary} previous={result.previous} basis={basis} select={select}/>
      <ReportCharts summary={result.summary} view={view} grouping={grouping} from={from} to={to} select={select}/>
      <Box xcss={styles.table} ref={table} tabIndex={-1} aria-label="Filtered report complaints" aria-busy={loading}><Stack space="space.150"><Inline spread="space-between" alignBlock="center" space="space.100"><Heading as="h3" size="medium">{complaintCount(result.table.count)}</Heading>{applied&&<Button appearance="subtle" onClick={()=>{setSelection(undefined);update({page:1});}}>Clear chart selection</Button>}</Inline>{applied&&<Text weight="medium">{applied.label}</Text>}<ReportTable search={typedSearch} setSearch={value=>{setTypedSearch(value);if(page!==1)update({page:1});}} offset={(result.table.page-1)*result.table.page_size} rows={result.table.results} open={open} sort={sort} setSort={value=>{setSort(value);update({page:1});}}/>{result.table.count>result.table.page_size&&<Inline spread="space-between" shouldWrap space="space.100"><Text size="small">Page {result.table.page} of {Math.ceil(result.table.count/result.table.page_size)}</Text><Inline space="space.100"><Button isDisabled={page<=1} onClick={()=>update({page:page-1})}>Previous page</Button><Button isDisabled={page*result.table.page_size>=result.table.count} onClick={()=>update({page:page+1})}>Next page</Button></Inline></Inline>}</Stack></Box>
    </>}
  </Stack>;
  return <Stack xcss={styles.full} space="space.300">
    <ReportFilters location={location} change={value=>{latest.current=value;change(value);}} options={result?.summary.filter_options} actions={<ActionMenu label="Export" items={[{label:'Download filtered Excel',run:()=>exportFile('filtered')},{label:'Download all complaints',run:()=>exportFile('all')},{label:'Email report',run:()=>{setExportOpen(true);setEmailOpen(true);if(!emailFilters)setEmailFilters(structuredClone(filters));}}]}/>}/>
    <Inline space="space.050" shouldWrap role="tablist" aria-label="Report view">{reportViews.map(value=><Button key={value} id={'report-view-'+value} onKeyDown={reportKey} appearance="subtle" role="tab" tabIndex={value===view?0:-1} aria-controls="complaint-report-content" aria-selected={value===view} isSelected={value===view} onClick={()=>update({view:value,page:1})}>{value==='overview'?'Overview':value==='turnaround'?'Turnaround':'Open follow-up'}</Button>)}</Inline><Box role="tabpanel" id="complaint-report-content" aria-labelledby={'report-view-'+view}>{content}</Box>
    {exportOpen&&<TaskDialog title="Export report" compact hasStatus close={async()=>{if(!busy&&!emailTask.busy&&!emailTask.uncertain&&(!emailOpen||!address||delivery||await confirmAction('Close email report? Unsent entries will be discarded.'))){setExportOpen(false);setEmailOpen(false);setAddress('');setEmailKey('');setEmailFilters(undefined);setDelivery('');setMessage('');}}}><DialogStatus><DraftStatus state={busy||emailTask.busy?'saving':emailTask.error||actionError?'error':delivery?'saved':!navigator.onLine?'offline':'draft'}/></DialogStatus><Text>Use the current report filters or export the full register.</Text><Stack space="space.150"><Button isLoading={busy} isDisabled={emailTask.busy||emailTask.uncertain} onClick={async()=>{void exportFile('filtered');}}>Download filtered Excel</Button><Button isDisabled={busy||emailTask.busy||emailTask.uncertain} onClick={async()=>{void exportFile('all');}}>Download all complaints</Button><Button isDisabled={busy||emailTask.busy||emailTask.uncertain} onClick={async()=>{if(!emailOpen&&!emailFilters)setEmailFilters(structuredClone(filters));setEmailOpen(value=>!value);}}>Email report</Button></Stack>{emailOpen&&<Form onSubmit={()=>sendEmail()}>{({formProps})=><Box as="form" {...formProps} id={emailFormId}><Stack space="space.150"><DateInput id="report-email" label="Email address" type="email" value={address} change={value=>{if(!emailTask.busy&&!emailTask.uncertain&&!delivery){setAddress(value);setEmailKey('');}}}/><DialogFooter><ActionButton type="submit" form={emailFormId} isDisabled={Boolean(delivery)||emailTask.uncertain} isLoading={emailTask.busy}>Send report</ActionButton>{delivery&&<><Button isLoading={busy} onClick={async()=>{void sendEmail(true);}}>Check delivery</Button><Button onClick={async()=>{setDelivery('');setMessage('');setEmailKey('');setEmailFilters(structuredClone(filters));}}>Email another report</Button></>}</DialogFooter>{message&&<Box role="status"><Text>{message}</Text></Box>}<TaskRecovery state={emailTask}/>{emailTask.uncertain&&<Button isDisabled={emailTask.busy} onClick={async()=>{if(await confirmAction('A report may already be queued. Close and check your email before sending another?')){emailTask.reset();setEmailOpen(false);setExportOpen(false);setAddress('');setEmailKey('');setEmailFilters(undefined);setDelivery('');setMessage('');}}}>Close and check email later</Button>}</Stack></Box>}</Form>}{Boolean(actionError)&&<Box role="alert"><Text color="color.text.danger">{errorText(actionError)}</Text>{actionError instanceof OperationError&&[401,403].includes(actionError.status)&&<Button onClick={signIn}>Sign in again</Button>}</Box>}</TaskDialog>}
  </Stack>;
}

export function EmailSchedules({ group, slot, markDirty }: { group: string; slot: RecoverySlot; markDirty: (dirty:boolean,pending?:boolean)=>void }) {
  const [data, setData] = useState<EmailSettings>(), [error, setError] = useState<unknown>(), [retry,setRetry]=useState(0);
  const [draft,setDraft]=useRetainedValue<Schedule|undefined>(slot,'schedule',undefined);
  const [recipients,setRecipients]=useRetainedValue(slot,'scheduleRecipients','');
  const state=useWorkspaceTask<{data:EmailSettings}>(group,slot,'scheduleSave',result=>{setData(result.data);setDraft(undefined);setRecipients('');notify('Email schedule saved.');});
  const locked=state.busy||state.uncertain;
  useEffect(()=>markDirty(Boolean(draft),locked),[draft,locked]);
  useEffect(() => { let active=true;const controller = new AbortController(),timer=setTimeout(()=>controller.abort(),20000);
    void operation<{ data: EmailSettings }>(group, 'reports/email-settings/', controller.signal, { action: 'list' }).then(result => {if(active){setData(result.data);setError(undefined);}}).catch(issue=>{if(active)setError(issue);}).finally(()=>clearTimeout(timer));
    return () => {active=false;controller.abort();clearTimeout(timer);}; }, [group,retry]);
  const edit = async (schedule?: Schedule) => {
    if(locked||(draft&&!await confirmAction('Discard the unfinished schedule?')))return;
    const value = schedule || { id: crypto.randomUUID(), title: '', preset: 'complaints', frequency: 'monthly', send_time: '08:00', active: true, skip_empty: true, recipients: [], group_configuration: Number(group), branch: '' };
    setDraft(value); setRecipients(value.recipients.join(', '));
  };
  const submit = () => { if(draft&&!locked)return state.save('reports/email-settings/',{...draft,action:'save',recipients:recipients.split(/[,;\n]+/).map(value=>value.trim()).filter(Boolean)}); };
  const change=(values:Partial<Schedule>)=>{if(draft&&!locked)setDraft({...draft,...values});};
  return <Box xcss={styles.form}><Stack space="space.150">
    <Heading as="h3" size="small">Scheduled reports</Heading>
    {Boolean(error)&&<Box role="alert"><SectionMessage appearance="error" title="Schedules unavailable" headingLevel="h3"><Text>{errorText(error)}</Text><Button onClick={()=>setRetry(value=>value+1)}>Retry schedules</Button></SectionMessage></Box>}
    {data&&<><Inline><Button isDisabled={locked} onClick={()=>edit()}>New schedule</Button></Inline>{data.schedules.map(schedule=><Inline key={schedule.id} spread="space-between" shouldWrap space="space.100"><Text>{schedule.title} · {schedule.frequency} · {schedule.active?'Active':'Paused'}</Text><Button isDisabled={locked} onClick={()=>edit(schedule)}>Edit</Button></Inline>)}</>}
    <TaskRecovery state={state}/>
    {draft&&Boolean(state.error)&&<Button isDisabled={state.busy} onClick={async()=>{if(!await confirmAction('Load the saved schedule? The previous save may already have completed; your unsaved edits will be discarded.'))return;const control=new AbortController();void operation<{data:EmailSettings}>(group,'reports/email-settings/',control.signal,{action:'list'}).then(result=>{setData(result.data);const current=result.data.schedules.find(item=>item.id===draft.id);state.reset();setDraft(current);setRecipients(current?.recipients.join(', ')||'');notify(current?'Saved schedule loaded.':'No saved schedule was found. Start a new schedule when ready.','information');}).catch(setError);}}>Load saved schedule</Button>}
    {draft&&<Form onSubmit={submit}>{({formProps})=><Box as="form" {...formProps}><Stack space="space.150">
      <Grid xcss={styles.columns} gap="space.150">
        <DateInput id="schedule-title" label="Schedule name" value={draft.title} change={title=>change({title})}/>
        <Selection id="schedule-preset" label="Scheduled report" value={draft.preset} options={data?.preset_options||[]} change={preset=>change({preset})}/>
        <Selection id="schedule-frequency" label="Frequency" value={draft.frequency} options={['daily','weekly','monthly','quarterly','yearly'].map(value=>({value,label:value[0].toUpperCase()+value.slice(1)}))} change={frequency=>change({frequency})}/>
        <DateInput id="schedule-time" label="Send time (Nairobi)" type="time" value={draft.send_time} change={send_time=>change({send_time})}/>
        <Selection id="schedule-active" label="Delivery" value={draft.active?'active':'paused'} options={[{value:'active',label:'Active'},{value:'paused',label:'Paused'}]} change={value=>change({active:value==='active'})}/>
        <Selection id="schedule-branch" label="Branch" value={draft.branch} options={data?.branches_by_group[String(draft.group_configuration)]||[]} change={branch=>change({branch})}/>
      </Grid>
      <DateInput id="schedule-recipients" label="Recipient email addresses (comma separated)" value={recipients} change={value=>{if(!locked)setRecipients(value);}}/>
      <Inline space="space.100"><ActionButton type="submit" isLoading={state.busy} isDisabled={state.uncertain}>Save schedule</ActionButton><Button isDisabled={locked} onClick={async()=>{if(await confirmAction('Discard the unfinished schedule?')){setDraft(undefined);setRecipients('');}}}>Cancel</Button></Inline>
    </Stack></Box>}</Form>}
  </Stack></Box>;
}
