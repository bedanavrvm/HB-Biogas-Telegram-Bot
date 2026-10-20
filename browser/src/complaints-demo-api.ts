import { ComplaintReadError, type CaseDetail } from './complaints-transport';

export type Option = { value: string; label: string };
export type DemoContext = { epoch: number; role: string; label: string; actor: string; personas: Option[]; can_create: boolean; groups: { key: string; label: string }[]; locations: { branch: string; county: string; constituency: string }[]; categories: string[] };
export type Evidence = { key: string; name: string; type: string; size: number; uploaded_by: string; created_at: string };
export type DemoCase = CaseDetail & { epoch: number; revision: number; group: string; customer_phone: string; customer_id: string; county: string; constituency: string; village: string; evidence: Evidence[]; actions: Option[]; source?: string };
export type Saved = { case: DemoCase; message: string };
export class DemoError extends ComplaintReadError {
  constructor(status: number, message: string, public readonly fields: Record<string, string> = {}) { super(status); this.message = message; }
}
const base = '/demo-api/complaints/v1/';

export async function demoJSON<T>(role: string, path: string, options: { signal?: AbortSignal; body?: unknown } = {}): Promise<T> {
  const response = await fetch(base + path, { method: options.body ? 'POST' : 'GET', credentials: 'omit', cache: 'no-store', redirect: 'error', signal: options.signal,
    headers: { Accept: 'application/json', 'X-Demo-Role': role, ...(options.body ? { 'Content-Type': 'application/json', 'X-Demo-Request': '1' } : {}) }, body: options.body ? JSON.stringify(options.body) : undefined });
  const data = await response.json() as { error?: string; fields?: Record<string, string> };
  if (!response.ok) throw new DemoError(response.status, data.error || 'Could not complete this demo request.', data.fields);
  return data as T;
}

export async function encodeFiles(files: File[]) {
  if (files.length > 10 || files.some(file => file.size > 10 * 1024 * 1024) || files.reduce((size, file) => size + file.size, 0) > 30 * 1024 * 1024) throw new DemoError(400, 'Choose up to ten files, 10 MB each and 30 MB total.');
  return Promise.all(files.map(async file => {
    const data = new Uint8Array(await file.arrayBuffer());
    let binary = '';
    for (let offset = 0; offset < data.length; offset += 8192) binary += String.fromCharCode(...data.subarray(offset, offset + 8192));
    return { name: file.name, content: btoa(binary) };
  }));
}

export async function exampleFile(role: string) {
  const sample = await demoJSON<{ name: string; content: string; type: string }>(role, 'sample-evidence/');
  return new File([Uint8Array.from(atob(sample.content), character => character.charCodeAt(0))], sample.name, { type: sample.type });
}

export async function evidenceBlob(role: string, key: string) {
  const response = await fetch(base + `evidence/${encodeURIComponent(key)}/`, { credentials: 'omit', cache: 'no-store', redirect: 'error', headers: { 'X-Demo-Role': role } });
  if (!response.ok) throw new DemoError(response.status, 'This evidence is no longer available to the selected role.');
  return response.blob();
}
