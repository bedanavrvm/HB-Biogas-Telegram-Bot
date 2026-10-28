/** Address-bar state is allowlisted; customer searches and form answers stay in memory. */
export type ReportLocation = { view: string; grouping: string; status: string; from: string; to: string; basis: string; page: number; branch: string; category: string; range: string; selected?: string };
export type WorkspaceRoute = { view: 'queue' | 'new' | 'reports' | 'settings'; group: string; selected: string; status: string; page: number; order?:string; report: ReportLocation };
export type QueuePreferences = { default_filters: Record<string, string> };
const choose = (value: string | null, allowed: string[], fallback: string) => value && allowed.includes(value) ? value : fallback;
const pageNumber = (value: string | null) => /^\d{1,6}$/.test(value || '') ? Math.max(1, Math.min(100000, Number(value))) : 1;
function date(value: string | null) {
  if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value) || Number(value.slice(0,4)) < 1) return '';
  const parsed = new Date(value + 'T00:00:00Z');
  return !Number.isNaN(parsed.valueOf()) && parsed.toISOString().slice(0, 10) === value ? value : '';
}
/** Human dates stay unambiguous; impossible calendar dates never reach the API. */
export function formDate(value: string) {
  const text=value.trim();
  if (/^\d{4}-\d{2}-\d{2}$/.test(text)) return date(text);
  const match=/^(\d{1,2}) (jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec) (\d{4})$/i.exec(text);
  if (!match) return '';
  const months: Record<string,number>={jan:1,feb:2,mar:3,apr:4,may:5,jun:6,jul:7,aug:8,sep:9,sept:9,oct:10,nov:11,dec:12};
  return date(`${match[3]}-${String(months[match[2].toLowerCase()]).padStart(2,'0')}-${match[1].padStart(2,'0')}`);
}
export function reportLocation(url = new URL(window.location.href)): ReportLocation {
  const params = url.searchParams;
  const today = new Intl.DateTimeFormat('en-CA', { timeZone: 'Africa/Nairobi', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date());
  const end = new Date(today + 'T12:00:00Z'), start = new Date(end); start.setUTCDate(start.getUTCDate() - 29);
  const range = choose(params.get('range'), ['last30', 'month', 'quarter', 'year', 'all', 'custom', 'specific-month', 'specific-quarter', 'specific-year'], params.has('from') || params.has('to') ? 'custom' : 'last30');
  if (range === 'month') start.setUTCFullYear(end.getUTCFullYear(), end.getUTCMonth(), 1);
  if (range === 'quarter') start.setUTCFullYear(end.getUTCFullYear(), Math.floor(end.getUTCMonth() / 3) * 3, 1);
  if (range === 'year') start.setUTCFullYear(end.getUTCFullYear(), 0, 1);
  const bounded = ['last30', 'month', 'quarter', 'year'].includes(range);
  return { view: choose(params.get('report'), ['overview', 'turnaround', 'follow-up'], 'overview'),
    grouping: choose(params.get('group_by'), ['day', 'week', 'month', 'year'], 'month'),
    status: choose(params.get('report_status'), ['open', 'reopened', 'resolved'], ''),
    basis: choose(params.get('date_basis'), ['reported', 'resolved'], 'reported'),
    from: params.has('from') ? date(params.get('from')) : bounded ? start.toISOString().slice(0, 10) : '', to: params.has('to') ? date(params.get('to')) : bounded ? today : '', page: pageNumber(params.get('report_page')), range,
    // Free-text facets stay in component memory, never the URL/history payload.
    branch: '', category: '', selected: /^[a-f\d]{8}(?:-[a-f\d]{4}){3}-[a-f\d]{12}$/.test(params.get('report_case') || '') ? params.get('report_case')! : '' };
}
export function readRoute(): WorkspaceRoute {
  const url = new URL(window.location.href), path = url.pathname;
  const selected = /^\/staff\/app\/complaints\/cases\/([a-f\d-]{36})\/$/.exec(path)?.[1] || '';
  return { view: path === '/staff/app/complaints/new/' ? 'new' : path === '/staff/app/complaints/settings/' ? 'settings' : path === '/staff/app/complaints/reports/' ? 'reports' : 'queue',
    group: /^\d+$/.test(url.searchParams.get('workspace') || '') ? url.searchParams.get('workspace')! : '', selected,
    status: ['pending', 'resolved', 'all'].includes(url.searchParams.get('status') || '') ? url.searchParams.get('status')! : 'pending',
    page: pageNumber(url.searchParams.get('page')), order:choose(url.searchParams.get('order'),['oldest','newest'],''), report: reportLocation(url) };
}
export function initialQueuePreferences(route: WorkspaceRoute, preferences: QueuePreferences, entryUrl: string) {
  const explicit = new URL(entryUrl).searchParams.has('status');
  return { ...route, status: explicit ? route.status : choose(preferences.default_filters.status, ['pending', 'resolved', 'all'], 'pending') };
}
export function writeRoute(route: WorkspaceRoute, replace = false) {
  const path = '/staff/app/complaints/' + (route.view === 'queue' ? (route.selected ? 'cases/' + route.selected + '/' : '') : route.view + '/');
  const params = new URLSearchParams({ workspace: route.group, status: route.status, page: String(route.page) });
  if(route.order==='oldest'||route.order==='newest')params.set('order',route.order);
  if (route.view === 'reports') {
    const report = route.report;
    params.set('report', choose(report.view, ['overview', 'turnaround', 'follow-up'], 'overview'));
    params.set('group_by', choose(report.grouping, ['day', 'week', 'month', 'year'], 'month'));
    params.set('date_basis', choose(report.basis, ['reported', 'resolved'], 'reported'));
    params.set('range', choose(report.range, ['last30', 'month', 'quarter', 'year', 'all', 'custom', 'specific-month', 'specific-quarter', 'specific-year'], 'custom'));
    if (['open', 'reopened', 'resolved'].includes(report.status)) params.set('report_status', report.status);
    if (date(report.from)) params.set('from', report.from);
    if (date(report.to)) params.set('to', report.to);
    params.set('report_page', String(pageNumber(String(report.page))));
    if (/^[a-f\d]{8}(?:-[a-f\d]{4}){3}-[a-f\d]{12}$/.test(report.selected || '')) params.set('report_case', report.selected!);
  }
  const position = historyPosition() + (replace ? 0 : 1);
  const hash = path === window.location.pathname && /^#comment-[a-f0-9-]{36}$/.test(window.location.hash) ? window.location.hash : '';
  window.history[replace ? 'replaceState' : 'pushState']({ complaints_position: position }, '', path + '?' + params + hash);
}

/** A numeric same-document cursor only; never form/customer values. */
export function historyPosition() {
  const value = window.history.state?.complaints_position;
  return Number.isSafeInteger(value) && value >= 0 ? value as number : 0;
}
