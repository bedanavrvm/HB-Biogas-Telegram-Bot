import {useEffect, useRef, useState} from 'react';
import {operation} from './complaints-operations-transport';

type Match = {key:string; reference:string; name:string; national_id:string; primary_phone:string; branch:string; location:string; matched_on:string; conflicts:string[]};
type Selection = {fields:Record<string,string>; warnings:string[];field_issues:Record<string,string>};
export function CustomerSuggestions({group,values,locked,select}:{group:string;values:Record<string,string>;locked:boolean;select:(fields:Record<string,string>,issues?:Record<string,string>)=>void}) {
  const [matches,setMatches]=useState<Match[]>([]),[status,setStatus]=useState(''),[warnings,setWarnings]=useState<string[]>([]),[retry,setRetry]=useState(0),[dismissed,setDismissed]=useState(false);
  const request=useRef<AbortController>(),generation=useRef(0);
  const signature=JSON.stringify([values.customer_id||'',values.customer_phone||'',values.client_name||'',values.portal_source_key||'',locked,retry]);
  useEffect(()=>{
    const current=++generation.current,controller=new AbortController(); request.current=controller;setMatches([]);setDismissed(false);setStatus('');
    if(locked)return()=>controller.abort();
    if(values.portal_source_key){
      void operation<{selection:Selection}>(group,'customers/suggest/',controller.signal,{source_key:values.portal_source_key}).then(data=>{
        if(current===generation.current&&!controller.signal.aborted)setWarnings(data.selection.warnings);
      }).catch(()=>{if(!controller.signal.aborted)setWarnings(['Portal source could not be checked. Clear the selection to use the entered details manually, or retry by selecting the customer again.']);});
      return()=>controller.abort();
    }
    if((values.customer_id||'').trim().length<3&&(values.customer_phone||'').replace(/\D/g,'').length<4&&(values.client_name||'').trim().length<3)return()=>controller.abort();
    const timer=setTimeout(()=>{setStatus('Searching Portal customers…');void operation<{matches:Match[]}>(group,'customers/suggest/',controller.signal,{customer_id:values.customer_id||'',customer_phone:values.customer_phone||'',client_name:values.client_name||''}).then(data=>{
      if(current!==generation.current||controller.signal.aborted)return;setMatches(data.matches);setStatus(data.matches.length?'Select a Portal customer to replace biodata.':'No matching Portal customer. Continue entering details manually.');
    }).catch(()=>{if(!controller.signal.aborted&&current===generation.current)setStatus('Customer lookup unavailable. Continue manually or retry.');});},300);
    return()=>{clearTimeout(timer);controller.abort();};
  },[group,signature]);
  useEffect(()=>{
    const escape=(event:KeyboardEvent)=>{
      if(event.key==='Escape'&&!values.portal_source_key&&!dismissed&&(matches.length||status)&&event.target instanceof HTMLInputElement&&['client_name','customer_id','customer_phone'].includes(event.target.name)){
        event.preventDefault();event.stopPropagation();setDismissed(true);++generation.current;request.current?.abort();
      }
    };
    document.addEventListener('keydown',escape,true);return()=>document.removeEventListener('keydown',escape,true);
  },[values.portal_source_key,dismissed,matches.length,status]);
  async function choose(key:string){
    const current=++generation.current,controller=request.current;if(!controller)return;
    setStatus('Loading customer biodata…');
    try{const data=await operation<{selection:Selection}>(group,'customers/suggest/',controller.signal,{source_key:key});
      if(current!==generation.current||controller.signal.aborted)return;setWarnings(data.selection.warnings);select(data.selection.fields,data.selection.field_issues);setMatches([]);setStatus('');
    }catch{if(!controller.signal.aborted)setStatus('Customer lookup unavailable. Continue manually or retry.');}
  }
  return <section className="cmp-customer-suggestions" aria-label="Portal customer suggestions" onKeyDown={event=>{
    if(event.key==='Escape'){event.preventDefault();event.stopPropagation();setDismissed(true);++generation.current;request.current?.abort();return;}
    if(!['ArrowDown','ArrowUp'].includes(event.key))return;
    const buttons=[...event.currentTarget.querySelectorAll<HTMLButtonElement>('[data-customer-choice]')],index=buttons.findIndex(button=>button===document.activeElement);
    if(buttons.length){event.preventDefault();buttons[(index+(event.key==='ArrowDown'?1:-1)+buttons.length)%buttons.length].focus();}
  }}>
    {values.portal_source_key&&<p role="status">Biodata copied from {values.portal_source_label||'Portal'}. You can edit these fields.</p>}
    {values.portal_source_key&&<button type="button" disabled={locked} onClick={()=>select({portal_source_key:'',portal_source_label:''})}>Clear Portal selection</button>}
    {values.portal_source_key&&warnings.map(message=><p className="cmp-customer-warning" key={message}>{message}</p>)}
    {!values.portal_source_key&&!dismissed&&status&&<><p role="status">{status}</p>{status.includes('unavailable')&&<button type="button" disabled={locked} onClick={()=>setRetry(n=>n+1)}>Retry customer lookup</button>}</>}
    {!dismissed&&matches.length>0&&<div role="group" aria-label="Matching Portal customers">{matches.map(item=><button type="button" data-customer-choice={item.key} key={item.key} disabled={locked} onClick={()=>void choose(item.key)}>
      <strong>{item.name||'Name not recorded'} · {item.reference}</strong><span>ID {item.national_id||'not recorded'} · {item.primary_phone||'Phone not recorded'} · {item.branch}</span><span>{item.location}</span><small>Matched by {item.matched_on}{item.conflicts.length?' · '+item.conflicts.join(' · '):''}</small>
    </button>)}</div>}
  </section>;
}
