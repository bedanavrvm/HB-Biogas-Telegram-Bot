export type Group = { key: string; label: string };
export type CaseSummary = { key: string; reference: string; customer_name: string; branch: string; category: string; status: string; reported_at: string };
export type CaseDetail = CaseSummary & { description: string; history: { action: string; status: string; created_at: string; updated_by: string; actor_affiliation: string }[]; history_truncated: boolean };
export type CasePage = { items: CaseSummary[]; pagination: { page: number; pages: number; total: number; page_size: number } };
export class ComplaintReadError extends Error {
  constructor(public readonly status: number) { super('Complaint read unavailable'); }
}
const base = '/api/staff/complaints/v1/';

export async function readComplaints<T>(path: string, signal: AbortSignal): Promise<T> {
  const response = await fetch(base + path, { method: 'GET', credentials: 'same-origin', cache: 'no-store', redirect: 'error', headers: { Accept: 'application/json' }, signal });
  if (!response.ok) throw new ComplaintReadError(response.status);
  if (!response.headers.get('Content-Type')?.startsWith('application/json')) throw new ComplaintReadError(502);
  return response.json() as Promise<T>;
}

export const groupPath = (key: string) => `groups/${encodeURIComponent(key)}/cases/`;
