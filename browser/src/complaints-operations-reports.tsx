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

const styles = cssMap({
  columns: { gridTemplateColumns: 'repeat(1, minmax(0, 1fr))', '@media (min-width: 48rem)': { gridTemplateColumns: 'repeat(2, minmax(0, 1fr))' }, alignItems: 'start' },
  filters: { gridTemplateColumns: 'repeat(1, minmax(0, 1fr))', '@media (min-width: 48rem)': { gridTemplateColumns: 'repeat(4, minmax(0, 1fr))' }, alignItems: 'end' },
  panel: { minWidth: 0, padding: token('space.200'), borderStyle: 'solid', borderWidth: token('border.width'), borderColor: token('color.border'), borderRadius: token('radius.medium'), overflowWrap: 'anywhere' },
  chart: { width: '100%', font: token('font.body.small') },
  chartTitle: { minHeight: '2rem' },
  row: { borderBlockEndStyle: 'solid', borderBlockEndWidth: token('border.width'), borderBlockEndColor: token('color.border'), paddingBlock: token('space.100') },
});
type Point = { label: string; count: number };
type Result = { summary: { total: number; pending: number; resolved: number; by_time: Point[]; by_category: Point[]; filter_options: { branches: Point[]; categories: Point[] } }; table: { results: { complaint_id: string; customer_name: string; complaint_category: string; branch_region: string; status: string; date_reported: string }[]; count: number; page: number; page_size: number } };
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
function period(label: string, granularity: string): [string, string] {
  const [year, month = 1, day = 1] = label.split('-').map(Number);
  const start = `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
  return [start, granularity === 'year' ? `${year}-12-31` : granularity === 'month' ? endOfMonth(year, month) : granularity === 'week' ? new Date(Date.UTC(year, month - 1, day + 6)).toISOString().slice(0, 10) : start];
}
function displayDate(value: string) { return /^\d{4}-\d\d-\d\d$/.test(value) ? value.slice(8) + '-' + value.slice(5, 7) + '-' + value.slice(2, 4) : value; }

/** First-party SVG data visualization: no new package, remote asset or hidden data. */
/* eslint-disable @atlaskit/design-system/no-html-image, @atlaskit/design-system/no-html-button -- Interactive chart geometry is not an image or an ADS control. Keyboard equivalents and text values are retained; candidate exception is recorded in DESIGN.md. */
function Chart({ title, rows, select, trend = false }: { title: string; rows: Point[]; select: (point: Point) => void; trend?: boolean }) {
  const [mode, setMode] = useState<'bar' | 'line'>(trend && rows.length > 7 ? 'line' : 'bar');
  const maximum = Math.max(2, Math.ceil(Math.max(1, ...rows.map(row => row.count)) / 2) * 2), width = 600, left = 42, right = 580, bottom = 190, top = 20;
  const points = rows.map((row, index) => ({ ...row, x: left + (index + 0.5) * (right - left) / Math.max(1, rows.length), y: bottom - (row.count / maximum) * (bottom - top) }));
  const action = (row: Point) => select(row);
  return <Box xcss={styles.panel}><Stack space="space.100"><Inline xcss={styles.chartTitle} shouldWrap alignBlock="center" spread="space-between" space="space.100"><Heading as="h3" size="small">{title}</Heading>{trend && <Button appearance="subtle" onClick={() => setMode(value => value === 'bar' ? 'line' : 'bar')}>{mode === 'bar' ? 'Line chart' : 'Bar chart'}</Button>}</Inline>
    <Text size="small" color="color.text.subtle">Select a value to filter the complaints below. Values are numbers of complaints.</Text>
    {rows.length === 0 ? <Text>No complaints in this period.</Text> : <Box xcss={styles.chart}><svg viewBox={`0 0 ${width} 240`} width="100%" role="img" aria-label={`${title}. ${rows.map(row => `${row.label}: ${row.count} complaints`).join('; ')}`}>
      {[0, 0.5, 1].map(ratio => <g key={ratio}><line x1={left} x2={right} y1={bottom - ratio * (bottom - top)} y2={bottom - ratio * (bottom - top)} stroke={token('color.border')} /><text x={left - 8} y={bottom - ratio * (bottom - top) + 4} textAnchor="end" fill={token('color.text.subtle')}>{Math.round(ratio * maximum)}</text></g>)}
      <line x1={left} x2={left} y1={top} y2={bottom} stroke={token('color.border.bold')} /><line x1={left} x2={right} y1={bottom} y2={bottom} stroke={token('color.border.bold')} />
      {mode === 'line' && <polyline points={points.map(point => `${point.x},${point.y}`).join(' ')} fill="none" stroke={token('color.chart.categorical.1')} strokeWidth={2} />}
      {points.map((point, index) => <g key={`${point.label}-${index}`} role="button" tabIndex={0} aria-label={`${point.label}: ${point.count} complaints. Filter results.`} onClick={() => action(point)} onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); action(point); } }}>
        <title>{point.label}: {point.count} complaints</title>{mode === 'bar' ? <rect x={point.x - Math.min(24, (right - left) / rows.length / 3)} y={point.y} width={Math.min(48, (right - left) / rows.length / 1.5)} height={Math.max(1, bottom - point.y)} fill={token('color.chart.categorical.1')} /> : <circle cx={point.x} cy={point.y} r={5} fill={token('color.chart.categorical.1')} />}
        {rows.length < 12 && <text x={point.x} y={point.y - 6} textAnchor="middle" fill={token('color.text')}>{point.count}</text>}
        {(rows.length <= 8 || index % Math.ceil(rows.length / 7) === 0) && <text x={point.x} y={bottom + 20} textAnchor="middle" fill={token('color.text.subtle')}>{displayDate(point.label).slice(0, 18)}</text>}
      </g>)}
      <text x={left} y={235} fill={token('color.text.subtle')}>Complaints</text>
    </svg></Box>}
  </Stack></Box>;
}
/* eslint-enable @atlaskit/design-system/no-html-image, @atlaskit/design-system/no-html-button */

export function Reports({ group, refresh }: { group: string; refresh: number }) {
  const [granularity, setGranularity] = useState('month'), [status, setStatus] = useState(''), [dateFrom, setDateFrom] = useState(''), [dateTo, setDateTo] = useState(''), [category, setCategory] = useState(''), [branch, setBranch] = useState(''), [basis, setBasis] = useState('reported'), [page, setPage] = useState(1), [scope, setScope] = useState(''), [error, setError] = useState<unknown>(), [busy, setBusy] = useState(false), [result, setResult] = useState<Result>(), [emailOpen, setEmailOpen] = useState(false), [address, setAddress] = useState(''), [delivery, setDelivery] = useState(''), [message, setMessage] = useState(''), [settingsOpen, setSettingsOpen] = useState(false);
  const table = useRef<HTMLDivElement>(null), focusTable = useRef(false), emailKey = useRef({ address: '', filters: '', key: '' });
  const filters = { status, category, branch, date_from: dateFrom, date_to: dateTo, date_basis: basis }, key = JSON.stringify([filters, granularity, page, refresh]);
  useEffect(() => {
    const controller = new AbortController(); let active = true; const timer = setTimeout(() => controller.abort(), 20000);
    setResult(undefined); setError(undefined);
    void operation<Result>(group, 'reports/', controller.signal, { ...filters, granularity, page }).then(data => { if (active) { setResult(data); if (focusTable.current) { requestAnimationFrame(() => { table.current?.scrollIntoView({ block: 'start', behavior: 'smooth' }); table.current?.focus({ preventScroll: true }); }); focusTable.current = false; } } }).catch(issue => { if (active) setError(issue); }).finally(() => clearTimeout(timer));
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
    <Grid xcss={styles.filters} gap="space.150"><Selection id="report-status" label="Status" value={status} options={[{ value: '', label: 'All complaints' }, { value: 'open', label: 'Open' }, { value: 'reopened', label: 'Reopened' }, { value: 'resolved', label: 'Resolved' }]} change={value => { setStatus(value); setPage(1); }} /><Selection id="report-basis" label="Dates apply to" value={basis} options={[{ value: 'reported', label: 'Reported complaints' }, { value: 'resolved', label: 'Resolved complaints' }]} change={value => { setBasis(value); setPage(1); }} /><Selection id="report-time" label="View by" value={granularity} options={['day', 'week', 'month', 'year'].map(value => ({ value, label: value[0].toUpperCase() + value.slice(1) }))} change={setGranularity} /><Selection id="report-period" label="Period" value="" options={[{ value: '', label: 'Custom dates' }, { value: 'all', label: 'All dates' }, { value: 'month', label: 'This month' }, { value: 'quarter', label: 'This quarter' }, { value: 'year', label: 'This year' }]} change={changeDates} /><DateInput id="date-from" label="From" value={dateFrom} change={value => { setDateFrom(value); setPage(1); }} /><DateInput id="date-to" label="To" value={dateTo} change={value => { setDateTo(value); setPage(1); }} /><Selection id="report-branch" label="Branch" value={branch} options={[{ value: '', label: 'All branches' }, ...(result?.summary.filter_options.branches || []).map(row => ({ value: row.label, label: row.label }))]} change={value => { setBranch(value); setPage(1); }} /><Selection id="report-category" label="Complaint type" value={category} options={[{ value: '', label: 'All types' }, ...(result?.summary.filter_options.categories || []).map(row => ({ value: row.label, label: row.label }))]} change={value => { setCategory(value); setPage(1); }} /></Grid>
    {Boolean(error) && <Box role="alert"><SectionMessage appearance="error" title="Report action could not be completed" headingLevel="h3"><Text as="p">{errorText(error)}</Text></SectionMessage></Box>}{message && <Box role="status"><Text>{message}</Text></Box>}
    {scope && <Box role="region" aria-label="Download complaints" xcss={styles.panel}><Stack space="space.150"><Heading as="h3" size="small">Download complaints</Heading><Text>Select the data to include in the Excel file.</Text><Inline shouldWrap space="space.100"><Button appearance="primary" isLoading={busy} onClick={() => { void exportFile('filtered'); }}>Download filtered results</Button><Button isDisabled={busy} onClick={() => { void exportFile('all'); }}>Download all complaints</Button><Button isDisabled={busy} onClick={() => setScope('')}>Cancel</Button></Inline></Stack></Box>}
    {emailOpen && <Box xcss={styles.panel}><Form onSubmit={() => sendEmail()}>{({ formProps }) => <Box as="form" {...formProps}><Stack space="space.150"><Heading as="h3" size="small">Email report</Heading><DateInput id="report-email" label="Email address" type="email" value={address} change={setAddress} /><Inline space="space.100" shouldWrap><Button type="submit" appearance="primary" isLoading={busy}>Send report</Button>{delivery && <Button isDisabled={busy} onClick={() => { void sendEmail(true); }}>Check delivery</Button>}<Button isDisabled={busy} onClick={() => setEmailOpen(false)}>Cancel</Button></Inline></Stack></Box>}</Form></Box>}
    {settingsOpen && <EmailSchedules group={group} close={() => setSettingsOpen(false)} />}
    {!result && !error && <Box role="status"><Text>Loading report...</Text></Box>}
    {result && <><Inline shouldWrap space="space.200">{[['Total', result.summary.total], ['Not resolved', result.summary.pending], ['Resolved', result.summary.resolved]].map(([label, value]) => <Box key={String(label)} xcss={styles.panel}><Stack space="space.050"><Text>{label}</Text><Heading as="h3" size="large">{value}</Heading></Stack></Box>)}</Inline>
      <Grid xcss={styles.columns} gap="space.200"><Chart title="Reported over time" rows={result.summary.by_time} trend select={row => { const [from, to] = period(row.label, granularity); setDateFrom(from); setDateTo(to); setBasis('reported'); setPage(1); focusTable.current = true; }} /><Chart title="Complaint types" rows={result.summary.by_category} select={row => { setCategory(row.label); setPage(1); focusTable.current = true; }} /></Grid>
      <Box xcss={styles.panel} ref={table} tabIndex={-1} aria-label="Filtered report complaints"><Stack space="space.100"><Inline shouldWrap spread="space-between" space="space.100"><Heading as="h3" size="small">Complaints</Heading>{(category || dateFrom || dateTo) && <Button appearance="subtle" onClick={() => { setCategory(''); setDateFrom(''); setDateTo(''); setPage(1); }}>Clear chart selection</Button>}</Inline>{result.table.results.map(row => <Box key={row.complaint_id} xcss={styles.row}><Inline spread="space-between" space="space.150" shouldWrap><Stack space="space.050"><Text weight="medium">{row.customer_name || 'Name not recorded'}</Text><Text size="small" color="color.text.subtle">{[row.complaint_id, row.branch_region, row.complaint_category].filter(Boolean).join(' · ')}</Text></Stack><Text>{row.status}</Text></Inline></Box>)}{result.table.results.length === 0 && <Text>No complaints match the selected filters.</Text>}<Inline spread="space-between" shouldWrap space="space.100"><Text>Page {result.table.page} · {result.table.count} complaints</Text><Inline space="space.100"><Button isDisabled={page <= 1} onClick={() => setPage(value => value - 1)}>Previous</Button><Button isDisabled={page * result.table.page_size >= result.table.count} onClick={() => setPage(value => value + 1)}>Next</Button></Inline></Inline></Stack></Box>
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
