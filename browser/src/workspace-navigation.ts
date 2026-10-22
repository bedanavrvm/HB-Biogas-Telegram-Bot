/** Address-bar state is allowlisted; customer searches and form answers stay in memory. */
export type ReportLocation = { view: string; grouping: string; status: string; from: string; to: string; basis: string; page: number; branch: string; category: string };
export type WorkspaceRoute = { view: 'queue' | 'new' | 'reports'; group: string; selected: string; status: string; page: number; report: ReportLocation };
export type QueuePreferences = { default_filters: Record<string, string> };
const choose = (value: string | null, allowed: string[], fallback: string) => value && allowed.includes(value) ? value : fallback;
const pageNumber = (value: string | null) => /^\d{1,6}$/.test(value || '') ? Math.max(1, Math.min(100000, Number(value))) : 1;
function date(value: string | null) {
  if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return '';
  const parsed = new Date(value + 'T00:00:00Z');
  return !Number.isNaN(parsed.valueOf()) && parsed.toISOString().slice(0, 10) === value ? value : '';
}
export function reportLocation(url = new URL(window.location.href)): ReportLocation {
  const params = url.searchParams;
  return { view: choose(params.get('report'), ['overview', 'turnaround', 'follow-up'], 'overview'),
    grouping: choose(params.get('group_by'), ['day', 'week', 'month', 'year'], 'month'),
    status: choose(params.get('report_status'), ['open', 'reopened', 'resolved'], ''),
    basis: choose(params.get('date_basis'), ['reported', 'resolved'], 'reported'),
    from: date(params.get('from')), to: date(params.get('to')), page: pageNumber(params.get('report_page')),
    // Free-text facets stay in component memory, never the URL/history payload.
    branch: '', category: '' };
}
export function readRoute(): WorkspaceRoute {
  const url = new URL(window.location.href), path = url.pathname;
  const selected = /^\/staff\/app\/complaints\/cases\/([a-f\d-]{36})\/$/.exec(path)?.[1] || '';
  return { view: path === '/staff/app/complaints/new/' ? 'new' : path === '/staff/app/complaints/reports/' ? 'reports' : 'queue',
    group: /^\d+$/.test(url.searchParams.get('workspace') || '') ? url.searchParams.get('workspace')! : '', selected,
    status: ['pending', 'resolved', 'all'].includes(url.searchParams.get('status') || '') ? url.searchParams.get('status')! : 'pending',
    page: pageNumber(url.searchParams.get('page')), report: reportLocation(url) };
}
export function initialQueuePreferences(route: WorkspaceRoute, preferences: QueuePreferences, entryUrl: string) {
  const explicit = new URL(entryUrl).searchParams.has('status');
  return { ...route, status: explicit ? route.status : choose(preferences.default_filters.status, ['pending', 'resolved', 'all'], 'pending') };
}
export function writeRoute(route: WorkspaceRoute, replace = false) {
  const path = '/staff/app/complaints/' + (route.view === 'queue' ? (route.selected ? 'cases/' + route.selected + '/' : '') : route.view + '/');
  const params = new URLSearchParams({ workspace: route.group, status: route.status, page: String(route.page) });
  if (route.view === 'reports') {
    const report = route.report;
    params.set('report', choose(report.view, ['overview', 'turnaround', 'follow-up'], 'overview'));
    params.set('group_by', choose(report.grouping, ['day', 'week', 'month', 'year'], 'month'));
    params.set('date_basis', choose(report.basis, ['reported', 'resolved'], 'reported'));
    if (['open', 'reopened', 'resolved'].includes(report.status)) params.set('report_status', report.status);
    if (date(report.from)) params.set('from', report.from);
    if (date(report.to)) params.set('to', report.to);
    params.set('report_page', String(pageNumber(String(report.page))));
  }
  window.history[replace ? 'replaceState' : 'pushState'](null, '', path + '?' + params);
}
