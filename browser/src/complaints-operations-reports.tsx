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
import Select from '@atlaskit/select';
import Textfield from '@atlaskit/textfield';
import { token } from '@atlaskit/tokens';
import { operation, OperationError, download } from './complaints-operations-transport';
import { ReportCharts, ReportSummary, ReportSelection } from './complaints-report-charts';
import { type ReportLocation } from './workspace-navigation';

const styles = cssMap({
  columns: { gridTemplateColumns: 'repeat(1, minmax(0, 1fr))', '@media (min-width: 48rem)': { gridTemplateColumns: 'repeat(2, minmax(0, 1fr))' }, alignItems: 'start' },
  filters: { gridTemplateColumns: 'repeat(1, minmax(0, 1fr))', '@media (min-width: 48rem)': { gridTemplateColumns: 'repeat(4, minmax(0, 1fr))' }, alignItems: 'end' },
  panel: { minWidth: 0, padding: token('space.200'), borderStyle: 'solid', borderWidth: token('border.width'), borderColor: token('color.border'), borderRadius: token('radius.medium'), overflowWrap: 'anywhere' },
  metrics: { gridTemplateColumns: 'repeat(1, minmax(0, 1fr))', '@media (min-width: 30rem)': { gridTemplateColumns: 'repeat(3, minmax(0, 1fr))' } },
  row: { borderBlockEndStyle: 'solid', borderBlockEndWidth: token('border.width'), borderBlockEndColor: token('color.border'), paddingBlock: token('space.100') },
});
type Result = { summary: ReportSummary; table: { results: { complaint_id: string; customer_name: string; complaint_category: string; branch_region: string; status: string; date_reported: string }[]; count: number; page: number; page_size: number } };

type Schedule = { id: string; revision?: number; title: string; preset: string; frequency: string; send_time: string; active: boolean; skip_empty: boolean; recipients: string[]; group_configuration: number; branch: string };
type EmailSettings = { schedules: Schedule[]; preset_options: { value: string; label: string }[]; branches_by_group: Record<string, { value: string; label: string }[]> };
function errorText(error: unknown) { return error instanceof OperationError ? error.message : 'Check your connection and try again. Your entries are retained.'; }
function Selection({ id, label, value, options, change }: { id: string; label: string; value: string; options: { value: string; label: string }[]; change: (value: string) => void }) {
  return <Box><Label htmlFor={id}>{label}</Label><Select inputId={id} value={options.find(item => item.value === value) || null} options={options} onChange={item => change(item?.value || '')} /></Box>;
}
function DateInput({ id, label, value, change, type = 'date' }: { id: string; label: string; value: string; change: (value: string) => void; type?: string }) {
  return <Box><Label htmlFor={id}>{label}</Label><Textfield id={id} type={type} value={value} onChange={event => change(event.currentTarget.value)} /></Box>;
}
function endOfMonth(year: number, month: number) { return new Date(Date.UTC(year, month, 0)).toISOString().slice(0, 10); }
export function Reports({ group, refresh, location, change }: { group: string; refresh: number; location: ReportLocation; change: (location: ReportLocation) => void }) {
  const { view, grouping: granularity, status, from: dateFrom, to: dateTo, category, branch, basis, page } = location;
  const latest = useRef(location); latest.current = location;
  const update = <K extends keyof ReportLocation>(key: K, value: ReportLocation[K]) => { const next = { ...latest.current, [key]: value }; latest.current = next; change(next); };
  const setView = (value: string) => update('view', value), setGranularity = (value: string) => update('grouping', value), setStatus = (value: string) => update('status', value), setDateFrom = (value: string) => update('from', value), setDateTo = (value: string) => update('to', value), setCategory = (value: string) => update('category', value), setBranch = (value: string) => update('branch', value), setBasis = (value: string) => update('basis', value), setPage = (value: number) => update('page', value);
  const [selection, setSelection] = useState<(ReportSelection & { source: string })>(), [options, setOptions] = useState<ReportSummary['filter_options']>();
  const [retry, setRetry] = useState(0);
  const [loading, setLoading] = useState(true);
  const resultSource = useRef('');
  const [scope, setScope] = useState(''), [error, setError] = useState<unknown>(), [busy, setBusy] = useState(false), [result, setResult] = useState<Result>(), [emailOpen, setEmailOpen] = useState(false), [address, setAddress] = useState(''), [delivery, setDelivery] = useState(''), [message, setMessage] = useState(''), [settingsOpen, setSettingsOpen] = useState(false);
  const table = useRef<HTMLDivElement>(null), focusTable = useRef(false), emailKey = useRef({ address: '', filters: '', key: '' });
  const baseFilters = { status, category, branch, date_from: dateFrom, date_to: dateTo, date_basis: basis };
  const source = JSON.stringify([group, baseFilters, granularity, view]);
  const applied = selection?.source === source ? selection : undefined;
  const filters = { ...baseFilters, ...applied?.filters }, key = JSON.stringify([source, applied, page, refresh, retry]);
  useEffect(() => { setSelection(undefined); focusTable.current = false; }, [source]);
  useEffect(() => {
    const controller = new AbortController(); let active = true; const timer = setTimeout(() => controller.abort(), 20000);
    if (resultSource.current !== source) setResult(undefined);
    setLoading(true); setError(undefined);
    void operation<Result>(group, 'reports/', controller.signal, { ...baseFilters, selection: applied?.filters || {}, granularity, page }).then(data => { if (active) { resultSource.current = source; setResult(data); setLoading(false); setOptions(data.summary.filter_options); if (focusTable.current) { requestAnimationFrame(() => { table.current?.scrollIntoView({ block: 'start', behavior: 'smooth' }); table.current?.focus({ preventScroll: true }); }); focusTable.current = false; } } }).catch(issue => { if (active) { setResult(undefined); setLoading(false); setError(issue); focusTable.current = false; } }).finally(() => clearTimeout(timer));
    return () => { active = false; controller.abort(); clearTimeout(timer); };
    // Serialized primitive filters are the request identity, not mutable form objects.
  }, [group, key]);
  const exportFile = async (selectedScope: string) => { if (busy) return; setBusy(true); setError(undefined); try { await download(group, 'reports/export/', { scope: selectedScope, filters, client_request_id: crypto.randomUUID() }); setScope(''); } catch (issue) { setError(issue); } finally { setBusy(false); } };
  const sendEmail = async (check = false) => {
    if (busy) return; setBusy(true); setError(undefined);
    const digest = JSON.stringify(filters);
    if (emailKey.current.address !== address || emailKey.current.filters !== digest) emailKey.current = { address, filters: digest, key: crypto.randomUUID() };
    try { const result = await operation<{ delivery_id: string; status: string; issue: string }>(group, 'reports/email/', new AbortController().signal, check ? { action: 'status', delivery_id: delivery } : { email: address, filters, client_request_id: emailKey.current.key }); setDelivery(result.delivery_id); setMessage(result.issue || (result.status === 'delivered' ? 'Report delivered.' : result.status === 'failed' ? 'Report delivery failed. Check the address and retry.' : 'Report queued for email delivery.')); } catch (issue) { setError(issue); } finally { setBusy(false); }
  };
  const changeDates = (mode: string) => {
    const now = new Date(), year = now.getFullYear(), month = now.getMonth() + 1;
    if (mode === 'month') { setDateFrom(`${year}-${String(month).padStart(2, '0')}-01`); setDateTo(endOfMonth(year, month)); }
    if (mode === 'quarter') { const first = Math.floor((month - 1) / 3) * 3 + 1; setDateFrom(`${year}-${String(first).padStart(2, '0')}-01`); setDateTo(endOfMonth(year, first + 2)); }
    if (mode === 'year') { setDateFrom(`${year}-01-01`); setDateTo(`${year}-12-31`); }
    if (mode === 'all') { setDateFrom(''); setDateTo(''); } setPage(1);
  };
  return <Stack space="space.200">
    <Inline shouldWrap spread="space-between" space="space.100"><Heading as="h2" size="medium">Reports</Heading><Inline shouldWrap space="space.100"><Button onClick={() => setScope('filtered')}>Download Excel</Button><Button onClick={() => setEmailOpen(value => !value)}>Email report</Button><Button onClick={() => setSettingsOpen(value => !value)}>Email settings</Button></Inline></Inline>
    <Selection id="report-view" label="Report" value={view} options={[{ value: "overview", label: "Complaints overview" }, { value: "turnaround", label: "Turnaround performance" }, { value: "follow-up", label: "Open-case follow-up" }]} change={value => { setView(value); setPage(1); }} />
    <Grid xcss={styles.filters} gap="space.150"><Selection id="report-status" label="Status" value={status} options={[{ value: '', label: 'All complaints' }, { value: 'open', label: 'Open' }, { value: 'reopened', label: 'Reopened' }, { value: 'resolved', label: 'Resolved' }]} change={value => { setStatus(value); setPage(1); }} /><Selection id="report-basis" label="Dates apply to" value={basis} options={[{ value: 'reported', label: 'Reported complaints' }, { value: 'resolved', label: 'Resolved complaints' }]} change={value => { setBasis(value); setPage(1); }} /><Selection id="report-time" label="View by" value={granularity} options={['day', 'week', 'month', 'year'].map(value => ({ value, label: value[0].toUpperCase() + value.slice(1) }))} change={value => { setGranularity(value); setPage(1); }} /><Selection id="report-period" label="Period" value="" options={[{ value: '', label: 'Custom dates' }, { value: 'all', label: 'All dates' }, { value: 'month', label: 'This month' }, { value: 'quarter', label: 'This quarter' }, { value: 'year', label: 'This year' }]} change={changeDates} /><DateInput id="date-from" label="From" value={dateFrom} change={value => { setDateFrom(value); setPage(1); }} /><DateInput id="date-to" label="To" value={dateTo} change={value => { setDateTo(value); setPage(1); }} /><Selection id="report-branch" label="Branch" value={branch} options={[{ value: '', label: 'All branches' }, ...(options?.branches || []).map(row => ({ value: row.label, label: row.label }))]} change={value => { setBranch(value); setPage(1); }} /><Selection id="report-category" label="Complaint type" value={category} options={[{ value: '', label: 'All types' }, ...(options?.categories || []).map(row => ({ value: row.label, label: row.label }))]} change={value => { setCategory(value); setPage(1); }} /></Grid>
    {Boolean(error) && <Box role="alert"><SectionMessage appearance="error" title="Report action could not be completed" headingLevel="h3"><Text as="p">{errorText(error)}</Text><Button onClick={() => setRetry(value => value + 1)}>Retry report</Button></SectionMessage></Box>}{message && <Box role="status"><Text>{message}</Text></Box>}
    {scope && <Box role="region" aria-label="Download complaints" xcss={styles.panel}><Stack space="space.150"><Heading as="h3" size="small">Download complaints</Heading><Text>Select the data to include in the Excel file.</Text><Inline shouldWrap space="space.100"><Button appearance="primary" isLoading={busy} onClick={() => { void exportFile('filtered'); }}>Download filtered results</Button><Button isDisabled={busy} onClick={() => { void exportFile('all'); }}>Download all complaints</Button><Button isDisabled={busy} onClick={() => setScope('')}>Cancel</Button></Inline></Stack></Box>}
    {emailOpen && <Box xcss={styles.panel}><Form onSubmit={() => sendEmail()}>{({ formProps }) => <Box as="form" {...formProps}><Stack space="space.150"><Heading as="h3" size="small">Email report</Heading><DateInput id="report-email" label="Email address" type="email" value={address} change={setAddress} /><Inline space="space.100" shouldWrap><Button type="submit" appearance="primary" isLoading={busy}>Send report</Button>{delivery && <Button isDisabled={busy} onClick={() => { void sendEmail(true); }}>Check delivery</Button>}<Button isDisabled={busy} onClick={() => setEmailOpen(false)}>Cancel</Button></Inline></Stack></Box>}</Form></Box>}
    {settingsOpen && <EmailSchedules group={group} close={() => setSettingsOpen(false)} />}
    {(!result || resultSource.current !== source) && !error && <Box role="status"><Text>Loading report...</Text></Box>}
    {result && resultSource.current === source && <>
      <Text size="small" color="color.text.subtle">Dates apply to the totals and table below. Each chart explains its own reporting, resolution or response dates.</Text>
      <Grid xcss={styles.metrics} gap="space.200">{[['Total', result.summary.total], ['Not resolved', result.summary.pending], ['Resolved', result.summary.resolved]].map(([label, value]) => <Box key={String(label)} xcss={styles.panel}><Stack space="space.050"><Text>{label}</Text><Heading as="h3" size="large">{value}</Heading></Stack></Box>)}</Grid>
      <ReportCharts summary={result.summary} view={view} grouping={granularity} from={dateFrom} to={dateTo} select={value => { if (applied && JSON.stringify(applied.filters) === JSON.stringify(value.filters)) { table.current?.scrollIntoView({ block: 'start', behavior: 'smooth' }); table.current?.focus({ preventScroll: true }); } else { setSelection({ ...value, source }); setPage(1); focusTable.current = true; } }} />
      <Box xcss={styles.panel} ref={table} tabIndex={-1} aria-label="Filtered report complaints" aria-busy={loading}><Stack space="space.100">
        <Inline shouldWrap spread="space-between" space="space.100"><Heading as="h3" size="small">Complaints</Heading>{applied && <Button appearance="subtle" onClick={() => { setSelection(undefined); setPage(1); focusTable.current = true; }}>Clear chart selection</Button>}</Inline>
        {applied && <Box role="status"><Text weight="medium">{applied.label}</Text></Box>}
        <Text size="small" color="color.text.subtle">{applied ? 'Table and filtered Excel use this chart selection. Totals and charts keep the report filters above.' : 'Table and filtered Excel use the report filters above.'}</Text>
        {loading ? <Box role="status"><Text>Loading matching complaints...</Text></Box> : <>
          {result.table.results.map(row => <Box key={row.complaint_id} xcss={styles.row}><Inline spread="space-between" space="space.150" shouldWrap><Stack space="space.050"><Text weight="medium">{row.customer_name || 'Name not recorded'}</Text><Text size="small" color="color.text.subtle">{[row.complaint_id, row.branch_region, row.complaint_category].filter(Boolean).join(' · ')}</Text></Stack><Text>{row.status}</Text></Inline></Box>)}
          {result.table.results.length === 0 && <Text>No complaints match the selected filters.</Text>}
          <Inline spread="space-between" shouldWrap space="space.100"><Text>Page {result.table.page} · {result.table.count} complaints</Text><Inline space="space.100"><Button isDisabled={result.table.page <= 1} onClick={() => setPage(result.table.page - 1)}>Previous</Button><Button isDisabled={result.table.page * result.table.page_size >= result.table.count} onClick={() => setPage(result.table.page + 1)}>Next</Button></Inline></Inline>
        </>}
      </Stack></Box>
    </>}
  </Stack>;
}

function EmailSchedules({ group, close }: { group: string; close: () => void }) {
  const [data, setData] = useState<EmailSettings>(), [error, setError] = useState<unknown>(), [draft, setDraft] = useState<Schedule>(), [recipients, setRecipients] = useState(''), [busy, setBusy] = useState(false), [message, setMessage] = useState('');
  useEffect(() => { const controller = new AbortController(); void operation<{ data: EmailSettings }>(group, 'reports/email-settings/', controller.signal, { action: 'list' }).then(result => setData(result.data)).catch(setError); return () => controller.abort(); }, [group]);
  const edit = (schedule?: Schedule) => { const value = schedule || { id: crypto.randomUUID(), title: '', preset: 'complaints', frequency: 'monthly', send_time: '08:00', active: true, skip_empty: true, recipients: [], group_configuration: Number(group), branch: '' }; setDraft(value); setRecipients(value.recipients.join(', ')); setMessage(''); };
  const submit = async () => { if (!draft || busy) return; setBusy(true); setError(undefined); try { const result = await operation<{ data: EmailSettings }>(group, 'reports/email-settings/', new AbortController().signal, { ...draft, action: 'save', recipients: recipients.split(/[,;\n]+/).map(value => value.trim()).filter(Boolean) }); setData(result.data); setDraft(undefined); setMessage('Email schedule saved.'); } catch (issue) { setError(issue); } finally { setBusy(false); } };
  return <Box xcss={styles.panel}><Stack space="space.150"><Inline spread="space-between" shouldWrap space="space.100"><Heading as="h3" size="small">Email settings</Heading><Button onClick={close}>Close</Button></Inline>{Boolean(error) && <Box role="alert"><Text color="color.text.danger">{errorText(error)}</Text></Box>}{message && <Box role="status"><Text>{message}</Text></Box>}{data && <><Inline space="space.100"><Button onClick={() => edit()}>New schedule</Button></Inline>{data.schedules.map(schedule => <Inline key={schedule.id} spread="space-between" shouldWrap space="space.100"><Text>{schedule.title} · {schedule.frequency} · {schedule.active ? 'Active' : 'Paused'}</Text><Button onClick={() => edit(schedule)}>Edit</Button></Inline>)}</>}{draft && <Form onSubmit={submit}>{({ formProps }) => <Box as="form" {...formProps}><Stack space="space.150"><Grid xcss={styles.columns} gap="space.150"><DateInput id="schedule-title" label="Schedule name" type="text" value={draft.title} change={title => setDraft({ ...draft, title })} /><Selection id="schedule-preset" label="Report" value={draft.preset} options={data?.preset_options || []} change={preset => setDraft({ ...draft, preset })} /><Selection id="schedule-frequency" label="Frequency" value={draft.frequency} options={['daily', 'weekly', 'monthly', 'quarterly', 'yearly'].map(value => ({ value, label: value[0].toUpperCase() + value.slice(1) }))} change={frequency => setDraft({ ...draft, frequency })} /><DateInput id="schedule-time" label="Send time (Nairobi)" type="time" value={draft.send_time} change={send_time => setDraft({ ...draft, send_time })} /><Selection id="schedule-active" label="Delivery" value={draft.active ? 'active' : 'paused'} options={[{ value: 'active', label: 'Active' }, { value: 'paused', label: 'Paused' }]} change={value => setDraft({ ...draft, active: value === 'active' })} /><Selection id="schedule-branch" label="Branch" value={draft.branch} options={data?.branches_by_group[String(draft.group_configuration)] || []} change={branch => setDraft({ ...draft, branch })} /></Grid><DateInput id="schedule-recipients" label="Recipient email addresses (comma separated)" type="text" value={recipients} change={setRecipients} /><Inline space="space.100"><Button type="submit" appearance="primary" isLoading={busy}>Save schedule</Button><Button isDisabled={busy} onClick={() => setDraft(undefined)}>Cancel</Button></Inline></Stack></Box>}</Form>}</Stack></Box>;
}
