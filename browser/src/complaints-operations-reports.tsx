import React, { useEffect, useRef, useState } from 'react';
import Button from '@atlaskit/button/default/button';
import { cssMap, cx } from '@atlaskit/css';
import Form, { Label } from '@atlaskit/form';
import Heading from '@atlaskit/heading';
import { Box } from '@atlaskit/primitives/compiled/box';
import { Grid } from '@atlaskit/primitives/compiled/grid';
import { Inline } from '@atlaskit/primitives/compiled/inline';
import { Stack } from '@atlaskit/primitives/compiled/stack';
import { Text } from '@atlaskit/primitives/compiled/text';
import { MetricText } from '@atlaskit/primitives/compiled/metric-text';
import { Pressable } from '@atlaskit/primitives/compiled/pressable';
import SectionMessage from '@atlaskit/section-message';
import { AdaptiveSelect as Select, ActionButton } from './complaints-ui';
import Textfield from '@atlaskit/textfield';
import Tabs, { Tab, TabList, TabPanel } from '@atlaskit/tabs';
import { token } from '@atlaskit/tokens';
import { operation, OperationError, download } from './complaints-operations-transport';
import { ReportCharts, type ReportSummary, type ReportSelection } from './complaints-report-charts';
import { ReportTable, type ReportRow } from './complaints-report-table';
import { TaskDialog, displayDate, complaintCount } from './complaints-ui';
import { reportLocation, type ReportLocation } from './workspace-navigation';
import { ReportFilters } from './complaints-report-filters';
import { notify } from './browser-interactions';
const styles = cssMap({
    full: { width: '100%', minWidth: 0 },
    tabsScroll: { width: '100%', overflowX: 'auto' },
    tabsWidth: { width: 'max-content', minWidth: '100%' },
  columns: { gridTemplateColumns: 'repeat(1, minmax(0, 1fr))', '@media (min-width: 48rem)': { gridTemplateColumns: 'repeat(2, minmax(0, 1fr))' }, alignItems: 'start' },
  panel: { minWidth: 0, padding: token('space.200'), borderStyle: 'solid', borderWidth: token('border.width'), borderColor: token('color.border'), borderRadius: token('radius.medium'), overflowWrap: 'anywhere' },
  metrics: { gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', '@media (min-width: 30rem)': { gridTemplateColumns: 'repeat(3, minmax(0, 1fr))' } },
  table: { minWidth: 0 }, form: { width: '100%', maxWidth: '30rem' },
  metric: { textAlign: 'start', backgroundColor: token('elevation.surface'), '&:hover': { backgroundColor: token('color.background.neutral.subtle.hovered') } },
  lastMetric: { gridColumn: '1 / -1', '@media (min-width: 30rem)': { gridColumn: 'auto' } },
});
type Result = { summary: ReportSummary; previous: {total: number; pending: number; resolved: number} | null; table: {results: ReportRow[]; count: number; page: number; page_size: number} };
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
export function Reports({group,refresh,location,change,open}:{group:string;refresh:number;location:ReportLocation;change:(value:ReportLocation)=>void;open:(key:string)=>void}) {
  const {view,grouping,status,from,to,branch,category,basis,page,range}=location;
  const latest=useRef(location); latest.current=location;
  const update=(values:Partial<ReportLocation>)=>{const next={...latest.current,...values};latest.current=next;change(next);};
  const [selection,setSelection]=useState<(ReportSelection & {source:string})>(),[result,setResult]=useState<Result>(),[error,setError]=useState<unknown>(),[loading,setLoading]=useState(true),[retry,setRetry]=useState(0);
  const [exportOpen,setExportOpen]=useState(false),[emailOpen,setEmailOpen]=useState(false),[address,setAddress]=useState(''),[delivery,setDelivery]=useState(''),[message,setMessage]=useState(''),[busy,setBusy]=useState(false),[sort,setSort]=useState('-date_reported');
  const table=useRef<HTMLDivElement>(null), focusTable=useRef(false), sourceRef=useRef(''), emailKey=useRef({address:'',filters:'',key:''});
  const [typedSearch,setTypedSearch]=useState(''),[search,setSearch]=useState(''),[actionError,setActionError]=useState<unknown>();
  useEffect(()=>{const timer=setTimeout(()=>setSearch(typedSearch.trim()),350);return()=>clearTimeout(timer);},[typedSearch]);
  const baseFilters={status,category,branch,search,date_from:from,date_to:to,date_basis:basis},source=JSON.stringify([group,baseFilters,grouping,view]),applied=selection?.source===source?selection:undefined;
  const filters={...baseFilters,...applied?.filters},requestKey=JSON.stringify([source,applied,page,refresh,retry,sort]);
  useEffect(()=>{const controller=new AbortController();let active=true;const timer=setTimeout(()=>controller.abort(),20000);
    if(sourceRef.current!==source)setResult(undefined);setLoading(true);setError(undefined);
    void operation<Result>(group,'reports/',controller.signal,{...baseFilters,selection:applied?.filters||{},granularity:grouping,page,sort}).then(data=>{if(active){sourceRef.current=source;setResult(data);setLoading(false);if(focusTable.current){requestAnimationFrame(()=>{table.current?.focus({preventScroll:true});table.current?.scrollIntoView({block:'start',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});});focusTable.current=false;}}}).catch(issue=>{if(active){setLoading(false);setError(issue);notify(errorText(issue),'error');}}).finally(()=>clearTimeout(timer));
    return()=>{active=false;controller.abort();clearTimeout(timer);};
  },[group,requestKey]);
  const exportFile=async(scope:string)=>{if(busy)return;setBusy(true);setActionError(undefined);try{await download(group,'reports/export/',{scope,filters,client_request_id:crypto.randomUUID()});setExportOpen(false);notify('Excel file ready. Your browser handles the download.','information');}catch(issue){setActionError(issue);notify(errorText(issue),'error');}finally{setBusy(false);}};
  const sendEmail=async(check=false)=>{if(busy)return;setBusy(true);setActionError(undefined);const digest=JSON.stringify(filters);if(emailKey.current.address!==address||emailKey.current.filters!==digest)emailKey.current={address,filters:digest,key:crypto.randomUUID()};
    try{const data=await operation<{delivery_id:string;status:string;issue:string}>(group,'reports/email/',new AbortController().signal,check?{action:'status',delivery_id:delivery}:{email:address,filters,client_request_id:emailKey.current.key});setDelivery(data.delivery_id);notify(data.issue||(data.status==='delivered'?'Report delivered.':data.status==='failed'?'Report delivery failed. Check the address and retry.':'Report queued for email delivery.'),data.status==='failed'?'error':data.status==='delivered'?'success':'information');setMessage(data.issue||(data.status==='delivered'?'Report delivered.':data.status==='failed'?'Report delivery failed. Check the address and retry.':'Report queued for email delivery.'));}catch(issue){setActionError(issue);notify(errorText(issue),'error');}finally{setBusy(false);}
  };
  const select=(value:ReportSelection)=>{setSelection({...value,source});update({page:1});focusTable.current=true;};
  const content = <Stack xcss={styles.full} space="space.300">
    <ReportFilters location={location} change={value=>{latest.current=value;change(value);}} options={result?.summary.filter_options} search={typedSearch} setSearch={value=>{setTypedSearch(value);if(page!==1)update({page:1});}}/>
    {Boolean(error)&&<Box role="alert"><SectionMessage appearance="error" title="Report could not be loaded" headingLevel="h2"><Text>{errorText(error)}</Text><Button onClick={()=>setRetry(value=>value+1)}>Retry report</Button></SectionMessage></Box>}
    {loading&&<Box role="status"><Text>Loading report…</Text></Box>}
    {result&&sourceRef.current===source&&<>
      <Grid xcss={styles.metrics} gap="space.200">{([{label:basis==='resolved'?'Closed in range':'Reported in range',key:'total',status:''},{label:'Still open',key:'pending',status:'open'},{label:'Closed',key:'resolved',status:'resolved'}] as const).map(item=><Pressable key={item.key} aria-label={`View ${item.label.toLowerCase()} complaints`} isDisabled={result.summary[item.key]===0} xcss={cx(styles.panel,styles.metric,item.key==='resolved'&&styles.lastMetric)} onClick={()=>select({label:item.label,filters:item.status?{status:item.status,date_basis:basis}:{}})}><Stack space="space.100"><Text color="color.text.subtle">{item.label}</Text><MetricText size="large">{result.summary[item.key]}</MetricText><Text size="small" color="color.text.subtle">{result.previous?`${result.summary[item.key]-result.previous[item.key]>0?'+':''}${result.summary[item.key]-result.previous[item.key]} vs previous period`:'All-time view'}</Text></Stack></Pressable>)}</Grid>
      <ReportCharts summary={result.summary} view={view} grouping={grouping} from={from} to={to} select={select}/>
      <Box xcss={styles.table} ref={table} tabIndex={-1} aria-label="Filtered report complaints" aria-busy={loading}><Stack space="space.150"><Inline spread="space-between" alignBlock="center" space="space.100"><Heading as="h3" size="medium">{complaintCount(result.table.count)}</Heading>{applied&&<Button appearance="subtle" onClick={()=>{setSelection(undefined);update({page:1});}}>Clear chart selection</Button>}</Inline>{applied&&<Text weight="medium">{applied.label}</Text>}<Text size="small" color="color.text.subtle">Select a column heading to sort. Open a complaint by clicking its row or pressing Enter.</Text><ReportTable offset={(result.table.page-1)*result.table.page_size} rows={result.table.results} open={open} sort={sort} setSort={value=>{setSort(value);update({page:1});}}/>{result.table.count>result.table.page_size&&<Inline spread="space-between" shouldWrap space="space.100"><Text size="small">Page {result.table.page} of {Math.ceil(result.table.count/result.table.page_size)}</Text><Inline space="space.100"><Button isDisabled={page<=1} onClick={()=>update({page:page-1})}>Previous page</Button><Button isDisabled={page*result.table.page_size>=result.table.count} onClick={()=>update({page:page+1})}>Next page</Button></Inline></Inline>}</Stack></Box>
    </>}
  </Stack>;
  return <Stack xcss={styles.full} space="space.300">
    <Inline spread="space-between" alignBlock="center" shouldWrap space="space.150"><Text color="color.text.subtle">{from||to?`${from?displayDate(from):'First report'} – ${to?displayDate(to):'Today'}`:'All dates'}</Text><Button onClick={()=>setExportOpen(true)}>Export report</Button></Inline>
    <Tabs id="report-views" selected={Math.max(0,reportViews.indexOf(view))} onChange={index=>update({view:reportViews[index],page:1})}><Box xcss={styles.tabsScroll}><Box xcss={styles.tabsWidth}><TabList><Tab>Overview</Tab><Tab>Turnaround</Tab><Tab>Open follow-up</Tab></TabList></Box></Box>{reportViews.map(value=><TabPanel key={value}>{value===view?content:null}</TabPanel>)}</Tabs>
    {exportOpen&&<TaskDialog title="Export report" compact close={()=>{if(!busy)setExportOpen(false);}}><Text>Use the current report filters or export the full register.</Text><Stack space="space.150"><Button isLoading={busy} onClick={()=>{void exportFile('filtered');}}>Download filtered Excel</Button><Button isDisabled={busy} onClick={()=>{void exportFile('all');}}>Download all complaints</Button><Button isDisabled={busy} onClick={()=>setEmailOpen(value=>!value)}>Email report</Button></Stack>{emailOpen&&<Form onSubmit={()=>sendEmail()}>{({formProps})=><Box as="form" {...formProps}><Stack space="space.150"><DateInput id="report-email" label="Email address" type="email" value={address} change={setAddress}/><Inline shouldWrap space="space.100"><Button type="submit" appearance="primary" isLoading={busy}>Send report</Button>{delivery&&<Button onClick={()=>{void sendEmail(true);}}>Check delivery</Button>}</Inline>{message&&<Box role="status"><Text>{message}</Text></Box>}</Stack></Box>}</Form>}{Boolean(actionError)&&<Box role="alert"><Text color="color.text.danger">{errorText(actionError)}</Text></Box>}</TaskDialog>}
  </Stack>;
}

export function EmailSchedules({ group }: { group: string }) {
  const [data, setData] = useState<EmailSettings>(), [error, setError] = useState<unknown>(), [draft, setDraft] = useState<Schedule>(), [recipients, setRecipients] = useState(''), [busy, setBusy] = useState(false), [message, setMessage] = useState('');
  useEffect(() => { const controller = new AbortController(); void operation<{ data: EmailSettings }>(group, 'reports/email-settings/', controller.signal, { action: 'list' }).then(result => setData(result.data)).catch(setError); return () => controller.abort(); }, [group]);
  const edit = (schedule?: Schedule) => { const value = schedule || { id: crypto.randomUUID(), title: '', preset: 'complaints', frequency: 'monthly', send_time: '08:00', active: true, skip_empty: true, recipients: [], group_configuration: Number(group), branch: '' }; setDraft(value); setRecipients(value.recipients.join(', ')); setMessage(''); };
  const submit = async () => { if (!draft || busy) return; setBusy(true); setError(undefined); try { const result = await operation<{ data: EmailSettings }>(group, 'reports/email-settings/', new AbortController().signal, { ...draft, action: 'save', recipients: recipients.split(/[,;\n]+/).map(value => value.trim()).filter(Boolean) }); setData(result.data); setDraft(undefined); setMessage('Email schedule saved.');notify('Email schedule saved.'); } catch (issue) { setError(issue); } finally { setBusy(false); } };
  return <Box xcss={styles.form}><Stack space="space.150"><Inline spread="space-between" shouldWrap space="space.100"><Heading as="h3" size="small">Scheduled reports</Heading></Inline>{Boolean(error) && <Box role="alert"><Text color="color.text.danger">{errorText(error)}</Text></Box>}{message && <Box role="status"><Text>{message}</Text></Box>}{data && <><Inline space="space.100"><Button onClick={() => edit()}>New schedule</Button></Inline>{data.schedules.map(schedule => <Inline key={schedule.id} spread="space-between" shouldWrap space="space.100"><Text>{schedule.title} · {schedule.frequency} · {schedule.active ? 'Active' : 'Paused'}</Text><Button onClick={() => edit(schedule)}>Edit</Button></Inline>)}</>}{draft && <Form onSubmit={submit}>{({ formProps }) => <Box as="form" {...formProps}><Stack space="space.150"><Grid xcss={styles.columns} gap="space.150"><DateInput id="schedule-title" label="Schedule name" type="text" value={draft.title} change={title => setDraft({ ...draft, title })} /><Selection id="schedule-preset" label="Scheduled report" value={draft.preset} options={data?.preset_options || []} change={preset => setDraft({ ...draft, preset })} /><Selection id="schedule-frequency" label="Frequency" value={draft.frequency} options={['daily', 'weekly', 'monthly', 'quarterly', 'yearly'].map(value => ({ value, label: value[0].toUpperCase() + value.slice(1) }))} change={frequency => setDraft({ ...draft, frequency })} /><DateInput id="schedule-time" label="Send time (Nairobi)" type="time" value={draft.send_time} change={send_time => setDraft({ ...draft, send_time })} /><Selection id="schedule-active" label="Delivery" value={draft.active ? 'active' : 'paused'} options={[{ value: 'active', label: 'Active' }, { value: 'paused', label: 'Paused' }]} change={value => setDraft({ ...draft, active: value === 'active' })} /><Selection id="schedule-branch" label="Branch" value={draft.branch} options={data?.branches_by_group[String(draft.group_configuration)] || []} change={branch => setDraft({ ...draft, branch })} /></Grid><DateInput id="schedule-recipients" label="Recipient email addresses (comma separated)" type="text" value={recipients} change={setRecipients} /><Inline space="space.100"><ActionButton type="submit" isLoading={busy}>Save schedule</ActionButton><Button isDisabled={busy} onClick={() => setDraft(undefined)}>Cancel</Button></Inline></Stack></Box>}</Form>}</Stack></Box>;
}
