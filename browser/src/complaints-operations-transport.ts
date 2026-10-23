import { ComplaintReadError, readComplaints, type Group } from './complaints-transport';

const prefix = '/api/staff/complaints/operations/v1/groups/';
export { type Group };
export type Complaint = {
  key: string; reference: string; customer_name: string; customer_phone: string; secondary_phone: string;
  customer_id: string; county: string; constituency: string; village: string; branch: string;
  category: string; description: string; status: string; needs_details: boolean; reported_at: string;
  age_label: string; days_open?: number; recorded_at?: string; revision: number; sync_status: string;
};
export type HistoryItem = { id: string; action: string; note: string; updated_by: string; actor_affiliation: string; created_at: string };
export type Evidence = { id: string; name: string; mime_type: string; status: string; size?:number; uploaded_by?:string; created_at_iso?:string; created_at?:string };
export type Detail = Complaint & { actions: string[]; evidence: Evidence[];
  history: HistoryItem[]; history_truncated: boolean; history_next_cursor: string };
export type Locations = Record<'branches' | 'counties' | 'sub_counties', { code: string; name: string; parent_code: string }[]>;
export type Bootstrap = { continuity_key: string; actor: { capabilities: string[] }; location_options: Locations; categories: string[]; counts: Record<string, number>; voice_input: { enabled: boolean; max_seconds: number; fields: string[] }; preferences?: { default_filters: Record<string, string> } };
export type QueueNeighbour = {key:string;page:number};
export type Queue = { items: Complaint[]; pagination: { page: number; pages: number; total: number; page_size?:number }; filter_options: Record<'branches' | 'categories', { label: string; count: number }[]>; navigation?:{position:number;total:number;previous:QueueNeighbour|null;next:QueueNeighbour|null}|null };
export class OperationError extends Error {
  constructor(public status: number, message: string, public fields: Record<string, string> = {}, public currentRevision?: number) { super(message); }
}
export function operationPath(group: string, path: string) {
  if (!/^\d+$/.test(group) || !/^[a-z0-9/-]+\/?(?:\?download=1)?$/.test(path)) throw new Error('Invalid workspace path.');
  return prefix + group + '/' + path;
}
export async function groups(signal: AbortSignal) {
  try { return await readComplaints<{ groups: Group[] }>('groups/', signal); }
  catch (error) { if (error instanceof ComplaintReadError) throw new OperationError(error.status, error.status === 401 ? 'Your session ended. Sign in again.' : 'Workspaces could not be loaded. Refresh to try again.'); throw error; }
}

async function csrf(signal: AbortSignal) {
  const response = await fetch('/api/staff/auth/v1/session/', { credentials: 'same-origin', mode: 'same-origin', redirect: 'error', cache: 'no-store', referrerPolicy: 'no-referrer', signal });
  const data = await response.json();
  if (!response.ok || !data.is_authenticated) throw new OperationError(401, 'Your session ended. Sign in again.');
  if (!/^[A-Za-z0-9]{32}(?:[A-Za-z0-9]{32})?$/.test(data.csrf_token || '')) throw new OperationError(0, 'Refresh your session before trying again.');
  return data.csrf_token as string;
}
export async function operation<T>(group: string, path: string, signal: AbortSignal, body?: Record<string, unknown> | FormData): Promise<T> {
  const response = await fetch(operationPath(group, path), {
    method: body ? 'POST' : 'GET', credentials: 'same-origin', mode: 'same-origin', redirect: 'error', cache: 'no-store', referrerPolicy: 'no-referrer', signal,
    headers: { Accept: 'application/json', 'X-Correlation-ID': crypto.randomUUID(),
      ...(body ? { 'X-CSRFToken': await csrf(signal) } : {}), ...(body && !(body instanceof FormData) ? { 'Content-Type': 'application/json' } : {}) },
    ...(body ? { body: body instanceof FormData ? body : JSON.stringify(body) } : {}),
  });
  const isJSON = response.headers.get('Content-Type')?.includes('application/json');
  const data = isJSON ? await response.json() : null;
  if (!response.ok) throw new OperationError(response.status,
    data?.error || (response.status === 403 ? 'Refresh your session and try again. If access is still denied, contact your administrator.' : 'The request could not be confirmed. Your entries are retained.'), data?.field_errors || {}, data?.current_revision);
  if (!isJSON) throw new OperationError(0, 'The response could not be confirmed. Refresh before retrying.');
  return data as T;
}
export async function download(group: string, path: string, body?: Record<string, unknown>) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 30000);
  try {
    const response = await fetch(operationPath(group, path), { method: body ? 'POST' : 'GET',
      credentials: 'same-origin', mode: 'same-origin', redirect: 'error', cache: 'no-store', referrerPolicy: 'no-referrer', signal: controller.signal,
      headers: body ? { 'Content-Type': 'application/json', 'X-CSRFToken': await csrf(controller.signal) } : {},
      ...(body ? { body: JSON.stringify(body) } : {}) });
    if (!response.ok) throw new OperationError(response.status, 'The file could not be downloaded. Refresh and try again.');
    const disposition = response.headers.get('Content-Disposition') || '';
    const encoded = /filename\*=utf-8''([^;]+)/i.exec(disposition)?.[1];
    const name = encoded ? decodeURIComponent(encoded) : /filename="?([^";]+)"?/i.exec(disposition)?.[1];
    if (!name?.trim()) throw new OperationError(0, 'The file name could not be confirmed. Try again.');
    const blob = await response.blob(), url = URL.createObjectURL(blob);
    const anchor = document.createElement('a'); anchor.href = url; anchor.download = name;
    document.body.append(anchor); anchor.click(); anchor.remove(); setTimeout(() => URL.revokeObjectURL(url), 30000);
  } finally { clearTimeout(timeout); }
}
