import React,{useContext,useEffect,useRef,useState} from 'react';
import Button from '@atlaskit/button/default/button';
import {operation,OperationError,type Publication,type Sla} from './complaints-operations-transport';
import {TaskSession} from './workspace-task';

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

const labels:Record<string,string>={waiting:'Waiting for receipt',received:'Received in Django',queued:'Queued for publication',publishing:'Publishing to Drive',retrying:'Retry scheduled',needs_attention:'Needs Complaints IT attention',published:'Published'};
const ongoing=(value?:Publication)=>Boolean(value&&(value.files.some(file=>!['published','needs_attention'].includes(file.stage))||(value.sheet.tracked&&['pending','retryable_failure','running'].includes(value.sheet.status))));

export function PublicationPanel({group,caseKey,initial,changed}:{group:string;caseKey:string;initial?:Publication;changed:()=>void}){
  const [data,setData]=useState(initial),[error,setError]=useState(''),[busy,setBusy]=useState(false),[refresh,setRefresh]=useState(0);
  const recheck=useContext(TaskSession),callback=useRef(changed);callback.current=changed;
  useEffect(()=>setData(initial),[initial]);
  useEffect(()=>{
    let active=true,timer:ReturnType<typeof setTimeout>|undefined,request:AbortController|undefined;
    let previous=initial?JSON.stringify([initial.files.map(file=>file.stage),initial.sheet.status]):'';
    const load=async()=>{
      if(document.hidden||!navigator.onLine)return;
      request?.abort();const controller=new AbortController();request=controller;
      try{
        const value=await operation<Publication>(group,`cases/${caseKey}/publication/`,controller.signal);
        if(!active)return;setData(value);setError('');
        const signature=JSON.stringify([value.files.map(file=>file.stage),value.sheet.status]);
        if(signature!==previous){previous=signature;callback.current();}
        if(ongoing(value))timer=setTimeout(()=>{void load();},2000);
      }catch(issue){if(active&&!controller.signal.aborted){if(issue instanceof OperationError&&issue.status===401)recheck();else setError(issue instanceof OperationError?issue.message:'Publication status could not be loaded. Your saved record is retained.');}}
    };
    const resume=()=>{clearTimeout(timer);void load();};
    if(ongoing(initial)||refresh)void load();
    document.addEventListener('visibilitychange',resume);window.addEventListener('online',resume);
    return()=>{active=false;clearTimeout(timer);request?.abort();document.removeEventListener('visibilitychange',resume);window.removeEventListener('online',resume);};
  },[group,caseKey,refresh,initial]);
  if(!data||(!data.files.length&&!data.sheet.tracked))return null;
  const attention=data.needs_attention||data.files.some(file=>file.stage==='needs_attention')||data.sheet.status==='dead_letter';
  return <section className="stitch-card stitch-publication" aria-label="Background publication"><header className="stitch-card-heading"><h2>Saved in Django</h2><Button appearance="subtle" onClick={()=>setRefresh(value=>value+1)}>Refresh publication</Button></header>
    <p>You can leave this page. Files and enabled register updates publish in the background.</p>
    {data.files.map(file=><div key={file.id} className="stitch-file-progress"><div><strong>{file.name}</strong><span>{file.percent}% · {labels[file.stage]||file.stage}</span></div><progress max={100} value={file.percent} aria-label={'Publication progress for '+file.name}/>{file.next_retry_at&&<small>Retry scheduled; {file.attempts} {file.attempts===1?'attempt':'attempts'} recorded.</small>}</div>)}
    {data.sheet.tracked&&<p>Google Sheets: {data.sheet.status==='succeeded'?'Published':data.sheet.status==='dead_letter'?'Needs Complaints IT attention':data.sheet.status==='retryable_failure'?'Retry scheduled':data.sheet.status==='running'?'Publishing':data.sheet.status==='paused'?'Paused by workspace configuration':'Queued'}.</p>}
    {ongoing(data)&&!data.runner_healthy&&<p role="status">The background publisher is not reporting. Ask Complaints IT to check it; your saved record and files are retained.</p>}
    {attention&&<p role="status">Publication needs Complaints IT attention. Your saved complaint and unpublished files are retained.</p>}
    {attention&&data.can_retry&&<Button isLoading={busy} onClick={async()=>{setBusy(true);setError('');try{await operation(group,`cases/${caseKey}/retry-publication/`,new AbortController().signal,{client_request_id:crypto.randomUUID()});setRefresh(value=>value+1);callback.current();}catch(issue){setError(issue instanceof OperationError?issue.message:'Retry could not be confirmed. Refresh publication before trying again.');}finally{setBusy(false);}}}>Retry failed publication</Button>}
    {error&&<div role="alert">{error}<Button onClick={()=>setRefresh(value=>value+1)}>Retry status</Button></div>}
  </section>;
}

export function PublicationAttention({group,open}:{group:string;open:(key:string)=>void}){
  const [data,setData]=useState<{key:string;reference:string;name:string}[]>(),[error,setError]=useState(''),[refresh,setRefresh]=useState(0);
  useEffect(()=>{const request=new AbortController();void operation<{items:{key:string;reference:string;name:string}[]}>(group,'publications/attention/',request.signal).then(value=>setData(value.items)).catch(issue=>{if(!request.signal.aborted)setError(issue instanceof OperationError?issue.message:'Publication attention could not be loaded.');});return()=>request.abort();},[group,refresh]);
  return <div className="stitch-attention"><p>Failed browser publications assigned to Complaints IT in this workspace. Saved complaint records are retained.</p><Button onClick={()=>{setError('');setRefresh(value=>value+1);}}>Refresh attention</Button>{!data&&!error&&<LoadingSkeletons label="Loading publication attention"/>}{error&&<p role="alert">{error}</p>}{data?.length===0&&<p>No browser publication failures need attention.</p>}{data?.map(row=><div key={row.key}><strong>{row.reference}</strong><span>{row.name}</span><Button onClick={()=>open(row.key)}>Review publication</Button></div>)}</div>;
}
