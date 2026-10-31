import React,{useEffect,useState} from 'react';
import AddIcon from '@atlaskit/icon/core/add';
import SearchIcon from '@atlaskit/icon/core/search';
import FilterIcon from '@atlaskit/icon/core/filter';
import SortIcon from '@atlaskit/icon/core/arrow-down';
import NextIcon from '@atlaskit/icon/core/chevron-right';
import PreviousIcon from '@atlaskit/icon/core/chevron-left';
import MoreIcon from '@atlaskit/icon/core/show-more-vertical';
import SuccessIcon from '@atlaskit/icon/core/status-success';
import WarningIcon from '@atlaskit/icon/core/status-warning';
import CommentIcon from '@atlaskit/icon/core/comment';
import AttachmentIcon from '@atlaskit/icon/core/attachment';
import LocationIcon from '@atlaskit/icon/core/location';
import {ActionMenu,statusLabel} from './complaints-ui';
import {SlaDisplay,LoadingSkeletons} from './complaints-publication';
import {CopyButton} from './complaints-copy-button';
import type {Queue,QueueItem} from './complaints-operations-transport';
import './complaints-queue.css';

const statuses=[['all','All complaints','total'],['pending','Open','pending'],['needs_details','Needs details','needs_details'],['resolved','Resolved','resolved']];
const orders={newest:'Newest first',oldest:'Oldest first',priority:'Highest priority',overdue:'Overdue first'};
function reported(value:string){
  const date=new Date(value);if(Number.isNaN(date.valueOf()))return 'Date unavailable';
  const format=new Intl.DateTimeFormat('en-GB',{day:'numeric',month:'short',timeZone:'Africa/Nairobi'});
  const day=new Intl.DateTimeFormat('en-CA',{year:'numeric',month:'2-digit',day:'2-digit',timeZone:'Africa/Nairobi'});
  return day.format(date)===day.format(new Date())?'Today':format.format(date);
}
export function ComplaintsQueuePage({data,counts,status,order,query,filterLabels,workspace,workspaceKey,canCreate,error,search,filter,sort,changeStatus,changePage,create,open,act,refresh,clear}:{
  data?:Queue;counts:Record<string,number>;status:string;order:string;query:string;filterLabels:string[];workspace:string;workspaceKey:string;canCreate:boolean;error:boolean;
  search:(value:string)=>void;filter:()=>void;sort:(value:string)=>void;changeStatus:(value:string)=>void;changePage:(value:number)=>void;create:()=>void;open:(key:string)=>void;act:(item:QueueItem,action:string)=>void;refresh:()=>void;clear:()=>void;
}){
  const [expanded,setExpanded]=useState<string|null>(null);
  useEffect(()=>setExpanded(null),[status,order,data?.pagination.page,data?.items[0]?.key]);
  const page=data?.pagination,first=page&&page.total?(page.page-1)*(page.page_size||5)+1:0,last=page?Math.min(page.total,page.page*(page.page_size||5)):0;
  return <div className="complaints-main-page">
    <section className="cmp-queue-intro" aria-label="Complaints overview"><div className="cmp-queue-title"><div><h1>Complaints <span>{counts.total??'—'}</span></h1><p>Triage and SLA queue resolution</p></div>{canCreate&&<button type="button" className="cmp-new" onClick={create}><AddIcon label="" size="small"/>New complaint</button>}</div>
      <div className="cmp-status-pills" aria-label="Complaint status">{statuses.map(([value,label,count])=><button type="button" key={value} aria-pressed={status===value} title={value==='pending'?'Open includes reopened complaints and records awaiting details.':undefined} data-status={value} onClick={()=>changeStatus(value)}>{label}<span>{counts[count]??0}</span></button>)}</div>
    </section>
    <section className="cmp-queue-tools" aria-label="Search and sort complaints"><div className="cmp-search-row"><div className="cmp-search"><SearchIcon label="" size="small"/><input id="complaints-queue-search" aria-label="Search complaints, IDs, customers" type="search" placeholder="Search complaints, IDs, customers…" value={query} onChange={event=>search(event.currentTarget.value)}/></div><button type="button" className="cmp-filter" onClick={filter}><FilterIcon label="" size="small"/><span>Filters</span>{filterLabels.length>0&&<b>{filterLabels.length}</b>}</button></div>
      <div className="cmp-sort-row"><label><SortIcon label="" size="small"/><span>Sorted by:</span><select aria-label="Queue order" value={order} onChange={event=>sort(event.currentTarget.value)}>{Object.entries(orders).map(([value,label])=><option value={value} key={value}>{label}</option>)}</select></label><span title={filterLabels.length?filterLabels.join(', '):workspace}>{filterLabels.length?filterLabels.join(', '):'Queue: '+workspace}</span></div>
    </section>
    <section className="cmp-ticket-deck" aria-label="Complaint queue">
      {!data&&!error&&<LoadingSkeletons label="Loading complaints"/>}
      {data?.items.map((item,index)=>{
        const showing=expanded===null?index===0:expanded===item.key,label=statusLabel(item.status,item.needs_details),closed=item.status==='CLOSED';
        return <article className="cmp-ticket" key={item.key} data-expanded={showing} data-status={label} onClick={event=>{if(event.target instanceof Element&&!event.target.closest('a,button,input,select,[role="menu"],[role="tooltip"]')&&!window.getSelection()?.toString())open(item.key);}}>
          <div className="cmp-ticket-top"><div><a href={`/staff/app/complaints/cases/${item.key}/?workspace=${workspaceKey}&status=${status}&page=${page?.page||1}&order=${order}`} onClick={event=>{event.preventDefault();open(item.key);}}>{item.reference}</a><i aria-hidden="true">•</i><span className="cmp-ticket-status">{label==='Closed'?'Resolved':label}</span>{item.priority==='high'&&!closed&&<span className="cmp-ticket-priority" title="High priority"><WarningIcon label="High priority" size="small"/></span>}</div><time dateTime={item.reported_at}>{reported(item.reported_at)}</time></div>
          <a className="cmp-ticket-name" href={`/staff/app/complaints/cases/${item.key}/?workspace=${workspaceKey}&status=${status}&page=${page?.page||1}&order=${order}`} onClick={event=>{event.preventDefault();open(item.key);}}>{item.customer_name||'Unnamed customer'}</a>
          <p className="cmp-ticket-meta">{item.category||'Type not recorded'}<span aria-hidden="true"> • </span>{item.branch||item.description||'Branch not recorded'}</p>
          {showing&&<div className="cmp-ticket-expanded"><div className="cmp-contact-facts"><div><span>National ID</span><div>{item.customer_id||'Not recorded'}{item.customer_id&&<CopyButton label={`Copy National ID for ${item.reference}`} value={()=>item.customer_id} message="National ID copied"/>}</div></div><div><span>Contact phone</span>{item.customer_phone?<a href={'tel:'+item.customer_phone}>{item.customer_phone}</a>:<span>Not recorded</span>}</div></div></div>}
          {!showing&&item.map_url&&<div className="cmp-location"><span><LocationIcon label="" size="small"/>{item.county||item.village||'Recorded location'}</span><a href={item.map_url} target="_blank" rel="noopener noreferrer">Open map</a></div>}
          <div className="cmp-ticket-bottom"><div className="cmp-ticket-badges">{item.hb_comment_count>0&&<span className="cmp-comment-count"><CommentIcon label="" size="small"/>{item.hb_comment_count} HB {item.hb_comment_count===1?'comment':'comments'}</span>}{item.evidence_count>0&&<span className="cmp-file-count"><AttachmentIcon label="" size="small"/>{item.evidence_count} {item.evidence_count===1?'file':'files'}</span>}{showing&&!item.needs_details&&<span className="cmp-sla-badge"><SlaDisplay value={item.sla} compact/></span>}{item.needs_details&&<span className="cmp-needs"><WarningIcon label="" size="small"/>Awaiting customer details</span>}</div>
            <div className="cmp-ticket-actions">{showing&&item.actions.includes('resolve')&&!closed&&!item.needs_details&&<button type="button" className="cmp-resolve" onClick={()=>act(item,'resolve')}><SuccessIcon label="" size="small"/>Resolve</button>}<ActionMenu label={`More options for ${item.reference}`} icon={MoreIcon} items={[{label:'Open complaint',run:()=>open(item.key)},{label:showing?'Hide contact details':'Show contact details',run:()=>setExpanded(showing?'':item.key)},...(item.needs_details&&item.actions.includes('complete-details')?[{label:'Complete missing details',run:()=>act(item,'complete-details')}]:[]),...(!closed&&!item.needs_details&&item.actions.includes('comment')?[{label:'HB Feedback',run:()=>act(item,'comment')}]:[]),...(!showing&&!closed&&!item.needs_details&&item.actions.includes('resolve')?[{label:'Resolve complaint',run:()=>act(item,'resolve')}]:[]),...(item.actions.includes('verification-comment')?[{label:'JBL Verification Comment',run:()=>act(item,'verification-comment')}]:[]),...(closed&&item.actions.includes('reopen')?[{label:'Reopen complaint',run:()=>act(item,'reopen')}]:[])]}/></div>
          </div>
        </article>;
      })}
      {data&&!data.items.length&&<div className="stitch-empty" role="status"><h2>{query||filterLabels.length?'No matching complaints':'No complaints in this queue'}</h2><p>{query||filterLabels.length?'Try clearing your search and filters.':'New complaints will appear here.'}</p><button type="button" className="cmp-filter" onClick={query||filterLabels.length?clear:refresh}>{query||filterLabels.length?'Clear search and filters':'Refresh queue'}</button></div>}
    </section>
    {page&&<footer className="cmp-pagination"><div><span>Showing <strong>{first}–{last}</strong> of {page.total} complaints</span><div><button type="button" disabled={page.page<=1} onClick={()=>changePage(page.page-1)}><PreviousIcon label="" size="small"/>Prev</button><button type="button" disabled={page.page>=page.pages} onClick={()=>changePage(page.page+1)}>Next<NextIcon label="" size="small"/></button></div></div>{page.pages>1&&<nav aria-label="Complaint pages">{Array.from({length:Math.min(5,page.pages)},(_,i)=>Math.max(1,Math.min(page.page-2,page.pages-4))+i).map(number=><button key={number} type="button" aria-label={`Page ${number}`} aria-current={page.page===number?'page':undefined} onClick={()=>changePage(number)}/>)}</nav>}</footer>}
  </div>;
}
