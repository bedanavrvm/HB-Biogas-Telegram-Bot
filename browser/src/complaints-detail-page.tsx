import React, {useEffect, useState} from 'react';
import BackIcon from '@atlaskit/icon/core/arrow-left';
import PersonIcon from '@atlaskit/icon/core/person-avatar';
import FileIcon from '@atlaskit/icon/core/file';
import LocationIcon from '@atlaskit/icon/core/location';
import AttachmentIcon from '@atlaskit/icon/core/attachment';
import LockIcon from '@atlaskit/icon/core/lock-locked';
import PhoneIcon from '@atlaskit/icon/core/phone';
import Tabs,{Tab,TabList,TabPanel} from '@atlaskit/tabs';
import type {Bootstrap,Detail} from './complaints-operations-transport';
import {statusLabel,displayDate} from './complaints-ui';
import {notify} from './browser-interactions';
import {DetailMap} from './complaints-detail-map';
import {EvidenceGallery} from './complaints-operations-media';
import {Activity} from './complaints-operations-history';
import {Conversation,Initials} from './complaints-conversation';
import type {RecoverySlot} from './workspace-recovery';
import './complaints-stitch.css';
import {SlaDisplay,usePublication,FilePublicationContext,RegisterStatus} from './complaints-publication';
import {CopyButton} from './complaints-copy-button';

let font:Promise<FontFace>|undefined;
export function useStitchFont(){
  useEffect(()=>{
    const entry=Array.from(document.scripts).find(script=>script.src&&new URL(script.src).origin===location.origin);
    if(!entry)return;
    font??=new FontFace('Inter',`url("${new URL('InterVariable.woff2',entry.src).href}")`,{weight:'100 900',style:'normal'}).load();
    void font.then(face=>document.fonts.add(face)).catch(()=>{font=undefined;});
  },[]);
}
function Card({title,icon,extra,children}:{title:string;icon:React.ReactNode;extra?:React.ReactNode;children:React.ReactNode}) {
  return <section className="stitch-card" aria-label={title}><header className="stitch-card-heading"><h2>{icon}{title}</h2>{extra}</header>{children}</section>;
}
export function ComplaintDetailPage({group,item,bootstrap,actions,navigation,back,slot,markDirty,changed,notice,dismissNotice}:{group:string;item:Detail;bootstrap?:Bootstrap;actions:React.ReactNode;navigation:React.ReactNode;back:()=>void;slot:RecoverySlot;markDirty:(value:boolean,pending?:boolean)=>void;changed:()=>void;notice:string;dismissNotice:()=>void}) {
  const [tab,setTab]=useState(0),[historyRefresh,setHistoryRefresh]=useState(0);
  const publication=usePublication(group,item.key,item.publication,changed);
  useEffect(()=>{if(notice){notify(notice);dismissNotice();}},[notice]);
  const label=statusLabel(item.status,item.needs_details);
  return <FilePublicationContext.Provider value={publication.data?.files||[]}><div className="complaints-stitch">
    <div className="stitch-ribbon"><button type="button" className="stitch-back" onClick={back}><BackIcon label="" size="small"/>Back to queue</button><div className="stitch-ticket"><span className="stitch-reference">{item.reference}</span><span className="stitch-status" data-status={label}>{label}</span>{navigation}</div></div>
    <h1>{item.customer_name||'Customer complaint'}</h1>
    <div className="stitch-toolbar"><div className="stitch-case-actions">{actions}</div><button type="button" onClick={()=>{setTab(0);requestAnimationFrame(()=>{const composer=document.querySelector<HTMLTextAreaElement>('textarea[name="staff-comment"]');if(composer){composer.scrollIntoView({block:'center'});composer.focus();}else document.getElementById('staff-conversation')?.scrollIntoView({block:'start'});});}}><LockIcon label="" size="small"/>Internal note</button><CopyButton label="Copy complaint link" message="Complaint link copied" value={()=>{const link=new URL(`/staff/app/complaints/cases/${item.key}/`,location.origin);link.searchParams.set('workspace',group);return link.href;}}/></div>
    <RegisterStatus group={group} caseKey={item.key} data={publication.data} refresh={publication.refresh}/>
    <div className="stitch-content">
      <Card title="Customer & ticket metadata" icon={<PersonIcon label="" size="small"/>} extra={<span className="stitch-age">Age: {item.age_label}</span>}><div className="stitch-facts">
        <div className="stitch-reporter"><Initials name={item.customer_name||'Customer'}/><div className="stitch-reporter-name"><span className="stitch-label">Customer / reporter</span><strong>{item.customer_name||'Not recorded'}</strong></div><div className="stitch-id"><span>{item.customer_id||'No ID'}</span>{item.customer_id&&<CopyButton label="Copy National ID" message="National ID copied" value={()=>item.customer_id}/>}</div></div>
        {[['Primary phone',item.customer_phone],['Alternative phone',item.secondary_phone]].map(([label,phone])=><div key={label} className="stitch-fact"><span className="stitch-label">{label}</span>{phone?<a href={'tel:'+phone}><PhoneIcon label="" size="small"/>{phone}</a>:<span>Not provided</span>}</div>)}
        {[['Branch',item.branch],['Complaint type',item.category],['Reported',displayDate(item.reported_at)]].map(([label,value])=><div key={label} className="stitch-fact"><span className="stitch-label">{label}</span><span>{value||'Not recorded'}</span></div>)}
        <div className="stitch-fact" data-priority={item.priority}><span className="stitch-label">Severity</span><span>{item.priority==='high'&&<span aria-hidden="true">↑ </span>}{item.priority?item.priority[0].toUpperCase()+item.priority.slice(1)+' priority':'Not recorded'}</span></div>
        <SlaDisplay value={item.sla} refresh={changed}/>
      </div></Card>
      <Card title="Description" icon={<FileIcon label="" size="small"/>}><p className="stitch-description">{item.description||'No description recorded.'}</p></Card>
      <Card title="Installation location" icon={<LocationIcon label="" size="small"/>}><DetailMap item={item} config={bootstrap?.map}/></Card>
      {item.evidence.length>0&&<Card title="Attachments" icon={<AttachmentIcon label="" size="small"/>} extra={<span className="stitch-age">{item.evidence.length} {item.evidence.length===1?'file':'files'}</span>}><EvidenceGallery group={group} items={item.evidence}/></Card>}
      <section id="staff-conversation" className="stitch-card stitch-discussion" aria-label="Staff conversation"><Tabs id="complaint-activity" selected={tab} onChange={setTab}><TabList><Tab>Conversation</Tab><Tab>History</Tab></TabList><TabPanel><Conversation key={item.key} group={group} item={item} slot={slot} markDirty={markDirty} changed={changed} saved={isReply=>{setHistoryRefresh(value=>value+1);notify(isReply?"Reply saved.":"Note saved.");}} evidenceAllowed={Boolean(bootstrap?.actor.capabilities.includes('complaint.case.evidence.manage'))}/></TabPanel><TabPanel><Activity refresh={historyRefresh} key={`${item.key}-${item.revision}-${item.history[0]?.id}`} group={group} caseKey={item.key} initial={item.history} next={item.history_next_cursor} reported={item.recorded_at||''}/></TabPanel></Tabs></section>
    </div>
  </div></FilePublicationContext.Provider>;
}
