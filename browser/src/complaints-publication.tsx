import React,{useContext,useEffect,useRef,useState} from 'react';
import Button from '@atlaskit/button/default/button';
import {operation,OperationError,type Publication,type Sla} from './complaints-operations-transport';
import {TaskSession} from './workspace-task';
import {notify,dismissNotice} from './browser-interactions';

export function LoadingSkeletons({label}:{label:string}){
  return <div className="stitch-loading" role="status" aria-label={label} aria-busy="true"><span>{label}…</span>{[0,1].map(index=><div key={index} className="stitch-skeleton" aria-hidden="true"><i/><i/><i/></div>)}</div>;
}

export function SlaDisplay({value,compact=false,refresh}:{value?:Sla;compact?:boolean;refresh?:()=>void}){
  const [anchor,setAnchor]=useState(()=>({server:value?Date.parse(value.server_now):0,local:performance.now()}));
  const [tick,setTick]=useState(performance.now());
  useEffect(()=>{setAnchor({server:value?Date.parse(value.server_now):0,local:performance.now()});},[value?.server_now]);
  useEffect(()=>{const update=()=>{setTick(performance.now());if(!document.hidden)refresh?.();},timer=setInterval(()=>{if(!document.hidden)setTick(performance.now());},60000);document.addEventListener('visibilitychange',update);return()=>{clearInterval(timer);document.removeEventListener('visibilitychange',update);};},[refresh]);
  let text='Timing unavailable',state=value?.state||'unavailable';
  if(value&&value.state!=='unavailable'){
    if(value.state==='closed')text=value.on_time===null?'Resolution timing unavailable':value.on_time?'Resolved on time':'Resolved late';
    else if(value.deadline_at){
      const seconds=(Date.parse(value.deadline_at)-anchor.server-Math.max(0,tick-anchor.local))/1000;
      const minutes=Math.ceil(Math.abs(seconds)/60),days=Math.floor(minutes/1440),hours=Math.floor(minutes%1440/60),remainder=minutes%60;
      text=[days?`${days}d`:'',hours?`${hours}h`:'',(!days&&remainder)||(!days&&!hours)?`${remainder}m`:''].filter(Boolean).join(' ')+(seconds<0?' overdue':' remaining');
      state=seconds<0?'overdue':seconds<=Math.max(1,value.target_hours/4)*3600?'due_soon':'on_track';
    }
  }
  if(compact)return <span className="stitch-sla-value" data-state={state}>{text}</span>;
  const stamp=value?.deadline_at?new Intl.DateTimeFormat('en-GB',{dateStyle:'medium',timeStyle:'short',timeZone:'Africa/Nairobi'}).format(new Date(value.deadline_at)):'';
  return <div className="stitch-sla"><span className="stitch-label">Resolution SLA</span><span className="stitch-sla-value" data-state={state}>{text}</span><details><summary aria-label="SLA information">ⓘ</summary><p>{value&&value.state!=='unavailable'?`Target: ${value.target_hours} elapsed calendar hours. ${stamp?'Deadline: '+stamp+' EAT. ':''}Reopening retains the original deadline.`:'The retained timing facts are incomplete or invalid; no deadline is inferred.'}</p></details></div>;
}

export const FilePublicationContext=React.createContext<Publication['files']>([]);
const ongoing=(value?:Publication)=>Boolean(value&&(value.files.some(file=>!['published','needs_attention'].includes(file.stage))||(value.sheet.tracked&&['pending','retryable_failure','running'].includes(value.sheet.status))));

export function usePublication(group:string,caseKey:string,initial:Publication|undefined,changed:()=>void){
  const [data,setData]=useState(initial),[refresh,setRefresh]=useState(0);
  const recheck=useContext(TaskSession),callback=useRef(changed);callback.current=changed;
  useEffect(()=>setData(initial),[initial]);
  useEffect(()=>{
    let active=true,timer:ReturnType<typeof setTimeout>|undefined,request:AbortController|undefined;
    let previous=initial?JSON.stringify([initial.files.map(file=>[file.id,file.stage]),initial.sheet.status]):'';
    const load=async()=>{
      if(document.hidden||!navigator.onLine)return;
      request?.abort();const controller=new AbortController();request=controller;
      try{
        const value=await operation<Publication>(group,`cases/${caseKey}/publication/`,controller.signal);
        if(!active)return;setData(value);
        const signature=JSON.stringify([value.files.map(file=>[file.id,file.stage]),value.sheet.status]);
        if(signature!==previous){previous=signature;callback.current();}
        if(ongoing(value))timer=setTimeout(()=>{void load();},2000);
      }catch(issue){if(active&&!controller.signal.aborted){if(issue instanceof OperationError&&issue.status===401)recheck();else timer=setTimeout(()=>{void load();},10000);}}
    };
    const resume=()=>{clearTimeout(timer);void load();};
    if(ongoing(initial)||refresh)void load();
    document.addEventListener('visibilitychange',resume);window.addEventListener('online',resume);
    return()=>{active=false;clearTimeout(timer);request?.abort();document.removeEventListener('visibilitychange',resume);window.removeEventListener('online',resume);};
  },[group,caseKey,refresh,initial]);
  const fileFailures=data?.files.filter(file=>file.stage==='needs_attention').map(file=>file.id).sort().join(',')||'';
  const sheetFailure=data?.sheet.tracked&&data.sheet.status==='dead_letter'?data.sheet.key||'register':'';
  useEffect(()=>{
    if(!fileFailures&&!sheetFailure)return;
    const text=fileFailures&&sheetFailure?'Your complaint is saved. Some files and the register update need Complaints IT attention.':fileFailures?'Your message is saved. Some files need Complaints IT attention.':'Your complaint is saved. The register update needs Complaints IT attention.';
    const id=notify(text,'warning',{dedupeKey:`publication:${caseKey}:${fileFailures}:${sheetFailure}`});return()=>dismissNotice(id);
  },[caseKey,fileFailures,sheetFailure]);
  return {data,refresh:()=>setRefresh(value=>value+1)};
}

export function FileProgress({evidence,commentKey}:{evidence:string;commentKey?:string}){
  const file=useContext(FilePublicationContext).find(file=>file.evidence===evidence&&(!commentKey||file.comment_key===commentKey));
  if(!file)return null;
  const label=file.stage==='published'?'Ready':file.stage==='needs_attention'?'Saved \u00b7 needs IT attention':file.stage==='retrying'?'Saved \u00b7 retrying file publication':file.stage==='publishing'?'Preparing file preview':'Saved \u00b7 preparing file';
  return <div className="stitch-file-progress" data-stage={file.stage} role="status"><span>{file.percent}% &middot; {label}</span>{file.stage!=='published'&&<progress value={file.percent} max={100} aria-label="File publication progress"/>}</div>;
}

export function RegisterStatus({group,caseKey,data,refresh}:{group:string;caseKey:string;data?:Publication;refresh:()=>void}){
  const [busy,setBusy]=useState(false),recheck=useContext(TaskSession);
  if(!data?.sheet.tracked)return null;
  const status=data.sheet.status,label=status==='succeeded'?'Register up to date':status==='dead_letter'?'Register update needs IT attention':status==='paused'?'Register sync paused':status==='retryable_failure'?'Register update retrying':'Register update pending';
  return <div className="stitch-register-status" data-state={status}><span role="status">{label}</span>{status==='dead_letter'&&data.can_retry&&<Button appearance="subtle" isLoading={busy} onClick={async()=>{setBusy(true);try{await operation(group,`cases/${caseKey}/retry-publication/`,new AbortController().signal,{client_request_id:crypto.randomUUID()});refresh();}catch(issue){if(issue instanceof OperationError&&issue.status===401)recheck();else notify(issue instanceof OperationError?issue.message:'Retry could not be confirmed. Refresh the complaint before retrying.','error');}finally{setBusy(false);}}}>Retry register update</Button>}</div>;
}

export function PublicationAttention({group,open}:{group:string;open:(key:string)=>void}){
  type Attention={key:string;reference:string;name:string;failed:boolean;state:Publication};
  const [data,setData]=useState<Attention[]>(),[error,setError]=useState(''),[refresh,setRefresh]=useState(0),[busy,setBusy]=useState('');
  const recheck=useContext(TaskSession);
  useEffect(()=>{const request=new AbortController();void operation<{items:Attention[]}>(group,'publications/attention/',request.signal).then(value=>setData(value.items)).catch(issue=>{if(!request.signal.aborted){if(issue instanceof OperationError&&issue.status===401)recheck();else setError(issue instanceof OperationError?issue.message:'Publication attention could not be loaded.');}});return()=>request.abort();},[group,refresh]);
  return <div className="stitch-attention"><p>Review register and file publication issues in this workspace. Saved records are retained.</p><Button onClick={()=>{setError('');setRefresh(value=>value+1);}}>Refresh attention</Button>{!data&&!error&&<LoadingSkeletons label="Loading publication attention"/>}{error&&<p role="alert">{error}</p>}{data?.length===0&&<p>No browser publication failures need attention.</p>}{data?.map(row=><div key={row.key}><strong>{row.reference}</strong><span>{row.name}</span>{!row.state.runner_healthy&&<p>The background publisher is not reporting. Check the scheduled worker.</p>}<Button onClick={()=>open(row.key)}>Open complaint</Button>{row.failed&&row.state.can_retry&&<Button isLoading={busy===row.key} isDisabled={Boolean(busy)} onClick={async()=>{setBusy(row.key);try{await operation(group,`cases/${row.key}/retry-publication/`,new AbortController().signal,{client_request_id:crypto.randomUUID()});setRefresh(value=>value+1);notify('Publication retry queued.');}catch(issue){if(issue instanceof OperationError&&issue.status===401)recheck();else notify(issue instanceof OperationError?issue.message:'Retry could not be confirmed.','error');}finally{setBusy('');}}}>Retry failed publication</Button>}</div>)}</div>;
}
