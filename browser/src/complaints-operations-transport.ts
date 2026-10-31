import { ComplaintReadError, readComplaints, type Group } from './complaints-transport';

const prefix = '/api/staff/complaints/operations/v1/groups/';
export { type Group };
export type Sla = {state:'on_track'|'due_soon'|'overdue'|'closed'|'unavailable';target_hours:number;started_at:string|null;deadline_at:string|null;resolved_at:string|null;server_now:string;remaining_seconds:number|null;on_time:boolean|null;resolution_hours:number|null};
export type PublishedFile = {id:string;name:string;size:number;stage:string;percent:number;received:boolean;evidence:string;attempts:number;next_retry_at:string|null;origin?:'case'|'conversation';comment_key?:string};
export type Publication = {files:PublishedFile[];needs_attention:boolean;sheet:{key?:string;tracked:boolean;status:string;attempts:number;next_retry_at:string|null};runner_healthy:boolean;can_retry:boolean};
export type Complaint = {
  key: string; reference: string; customer_name: string; customer_phone: string; secondary_phone: string;
  customer_id: string; county: string; constituency: string; village: string; branch: string;
  category: string; description: string; status: string; needs_details: boolean; reported_at: string;
  age_label: string; priority?: 'high'|'normal'|'low'; sla?:Sla; days_open?: number; recorded_at?: string; revision: number; sync_status: string; hb_comment_count: number;
};
export type HistoryChange = { field: string; label: string; old_value?: string | number | boolean | null; new_value?: string | number | boolean | null; previous_recorded?: boolean; old_display?: string; new_display?: string };
export type HistoryItem = { id: string; action: string; note: string; updated_by: string; actor_affiliation: string; created_at: string; display_changes?: HistoryChange[]; evidence?:Evidence[] };
export type Evidence = { id: string; name: string; mime_type: string; status: string; size?:number; uploaded_by?:string; created_at_iso?:string; created_at?:string };
export type Detail = Complaint & { actions: string[]; evidence: Evidence[]; publication?:Publication; location: {latitude: string; longitude: string; url: string}; group_label?: string;
  history: HistoryItem[]; history_truncated: boolean; history_next_cursor: string };
export type Locations = Record<'branches' | 'counties' | 'sub_counties', { code: string; name: string; parent_code: string }[]>;
export type Bootstrap = { continuity_key: string; map?: MapConfig; actor: { name: string; roles?:string[]; capabilities: string[] }; location_options: Locations; categories: string[]; counts: Record<string, number>; voice_input: { enabled: boolean; max_seconds: number; fields: string[] }; preferences?: { default_filters: Record<string, string> } };
export type QueueNeighbour = {key:string;page:number};
export type MapConfig = {enabled:boolean;tile_url:string};
export type StaffComment = {id:string;body:string;author:string;affiliation:string;created_at:string;format:string;kind:string;
  reply_to:{id:string;author:string;excerpt:string}|null;mentions:{id:string;label:string}[];evidence:Evidence[];
  reaction:{count:number;active:boolean;revision:number}};
export type ConversationData = {items:StaffComment[];total:number;next_cursor:string;can_post:boolean;attachment_failure?:boolean;background_publication?:boolean};
export type QueueItem = Complaint & {actions:string[];evidence_count:number;map_url:string};
export type Queue = { items: QueueItem[]; pagination: { page: number; pages: number; total: number; page_size?:number }; filter_options: Record<'branches' | 'categories', { label: string; count: number }[]>; navigation?:{position:number;total:number;previous:QueueNeighbour|null;next:QueueNeighbour|null}|null };
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
  let uploadKey='';
  if(body instanceof FormData && body.getAll('evidence').length){
    const staged=await stageFiles(group,path,body,signal);
    uploadKey=staged.key;body=staged.fields;
  }
  const response = await fetch(operationPath(group, path), {
    method: body ? 'POST' : 'GET', credentials: 'same-origin', mode: 'same-origin', redirect: 'error', cache: 'no-store', referrerPolicy: 'no-referrer', signal,
    headers: { Accept: 'application/json', 'X-Correlation-ID': crypto.randomUUID(), ...(uploadKey?{'X-Complaint-Upload':uploadKey}:{}),
      ...(body ? { 'X-CSRFToken': await csrf(signal) } : {}), ...(body && !(body instanceof FormData) ? { 'Content-Type': 'application/json' } : {}) },
    ...(body ? { body: body instanceof FormData ? body : JSON.stringify(body) } : {}),
  });
  const isJSON = response.headers.get('Content-Type')?.includes('application/json');
  const data = isJSON ? await response.json() : null;
  if (!response.ok) throw new OperationError(response.status,
    data?.error==='access_denied'?'Your Complaints role does not allow this action. Contact Complaints IT if you need access.':data?.error==='session_required'?'Your session ended. Sign in again.':data?.error || (response.status === 403 ? 'Refresh your session and try again. If access is still denied, contact your administrator.' : 'The request could not be confirmed. Your entries are retained.'), data?.field_errors || {}, data?.current_revision);
  if (!isJSON) throw new OperationError(0, 'The response could not be confirmed. Refresh before retrying.');
  return data as T;
}

export type FileTransfer = {file:File;percent:number;stage:string};
const progressEvent='complaint-browser-file-progress';
const progressValues=new WeakMap<File,FileTransfer>();
export const fileTransfer=(file:File)=>progressValues.get(file);
export function watchFileTransfers(callback:(transfer:FileTransfer)=>void){
  const listener=(event:Event)=>callback((event as CustomEvent<FileTransfer>).detail);
  window.addEventListener(progressEvent,listener);return()=>window.removeEventListener(progressEvent,listener);
}
function progress(file:File,percent:number,stage:string){
  const value={file,percent,stage};progressValues.set(file,value);
  window.dispatchEvent(new CustomEvent<FileTransfer>(progressEvent,{detail:value}));
}
async function stageFiles(group:string,path:string,body:FormData,signal:AbortSignal){
  const files=body.getAll('evidence');
  if(files.some(file=>!(file instanceof File)))throw new OperationError(400,'Choose valid evidence files.');
  const selected=files as File[],fields:Record<string,string>={};
  body.forEach((value,key)=>{if(key!=='evidence')fields[key]=String(value);});
  const facts=await Promise.all(selected.map(async file=>({name:file.name,size:file.size,sha256:Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',await file.arrayBuffer()))).map(value=>value.toString(16).padStart(2,'0')).join('')})));
  const batch=await operation<{key:string;files:PublishedFile[]}>(group,'uploads/',signal,{path,fields,files:facts});
  for(let index=0;index<selected.length;index++){
    const file=selected[index],row=batch.files[index];
    if(row.received){progress(file,Math.max(50,row.percent),row.stage);continue;}
    const token=await csrf(signal);
    await new Promise<void>((resolve,reject)=>{
      const xhr=new XMLHttpRequest(),url=operationPath(group,`uploads/${batch.key}/${row.id}/`);
      const stop=()=>xhr.abort();
      const finish=()=>signal.removeEventListener('abort',stop);
      xhr.open('PUT',url);xhr.timeout=120000;xhr.withCredentials=true;
      xhr.setRequestHeader('X-CSRFToken',token);xhr.setRequestHeader('Content-Type','application/octet-stream');
      xhr.setRequestHeader('Accept','application/json');
      xhr.upload.onprogress=event=>progress(file,event.lengthComputable?Math.min(49,Math.floor(event.loaded/event.total*50)):0,'Receiving in Django');
      xhr.onload=()=>{finish();let result;try{result=JSON.parse(xhr.responseText);}catch{reject(new OperationError(0,'The file receipt could not be confirmed. Retry the same save.'));return;}
        if(xhr.status<200||xhr.status>=300||xhr.responseURL!==new URL(url,location.origin).href){reject(new OperationError(xhr.status,result?.error||'The file could not be received. Retry the same save.'));return;}
        progress(file,50,'Received in Django');resolve();};
      xhr.onerror=xhr.ontimeout=()=>{finish();progress(file,0,'Receipt interrupted');reject(new OperationError(0,'The file receipt was interrupted. Retry the same save.'));};
      xhr.onabort=()=>{finish();reject(new DOMException('Upload interrupted','AbortError'));};
      signal.addEventListener('abort',stop,{once:true});progress(file,0,'Receiving in Django');
      if(signal.aborted){stop();reject(new DOMException('Upload interrupted','AbortError'));return;}xhr.send(file);
    });
  }
  return {key:batch.key,fields};
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
