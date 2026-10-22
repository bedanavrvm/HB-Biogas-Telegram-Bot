/** Address-bar state is allowlisted; customer searches and form answers stay in memory. */
export type WorkspaceRoute = { view: 'queue' | 'new' | 'reports'; group: string; selected: string; status: string; page: number };
export function readRoute(): WorkspaceRoute {
  const url = new URL(window.location.href), path = url.pathname;
  const selected = /^\/staff\/app\/complaints\/cases\/([a-f\d-]{36})\/$/.exec(path)?.[1] || '';
  return { view: path === '/staff/app/complaints/new/' ? 'new' : path === '/staff/app/complaints/reports/' ? 'reports' : 'queue',
    group: /^\d+$/.test(url.searchParams.get('workspace') || '') ? url.searchParams.get('workspace')! : '', selected,
    status: ['pending', 'resolved', 'all'].includes(url.searchParams.get('status') || '') ? url.searchParams.get('status')! : 'pending',
    page: Math.max(1, Math.min(100000, Number(url.searchParams.get('page')) || 1)) };
}
export function writeRoute(route: WorkspaceRoute, replace = false) {
  const path = '/staff/app/complaints/' + (route.view === 'queue' ? (route.selected ? 'cases/' + route.selected + '/' : '') : route.view + '/');
  const params = new URLSearchParams({ workspace: route.group, status: route.status, page: String(route.page) });
  window.history[replace ? 'replaceState' : 'pushState'](null, '', path + '?' + params);
}
