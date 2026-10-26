import React, { useState } from 'react';
import Button from '@atlaskit/button/default/button';
import { Label } from '@atlaskit/form';
import { AdaptiveSelect as Select, DialogFooter, Section } from './complaints-ui';
import Textfield from '@atlaskit/textfield';
import { cssMap } from '@atlaskit/css';
import { Box } from '@atlaskit/primitives/compiled/box';
import { Grid } from '@atlaskit/primitives/compiled/grid';
import { Inline } from '@atlaskit/primitives/compiled/inline';
import { Text } from '@atlaskit/primitives/compiled/text';
import { TaskDialog, displayDate } from './complaints-ui';
import { formDate, reportLocation, type ReportLocation } from './workspace-navigation';
import { DateControl } from './complaints-date-control';
import { ControlRow } from './complaints-ui';

const styles=cssMap({ fields:{gridTemplateColumns:'repeat(auto-fit, minmax(min(100%, 14rem), 1fr))',alignItems:'end'} });
type Options={branches:{label:string}[];categories:{label:string}[]};
export function ReportFilters({location:appliedLocation,change:applyChange,options,actions}:{location:ReportLocation;change:(value:ReportLocation)=>void;options?:Options;actions?:React.ReactNode}){
 const [draft,setDraft]=useState<ReportLocation>(appliedLocation),[fromValid,setFromValid]=useState(true),[toValid,setToValid]=useState(true);
 const [opened,setOpened]=useState(false),[mode,setMode]=useState(''),[year,setYear]=useState(appliedLocation.from.slice(0,4)||String(new Date().getFullYear())),[month,setMonth]=useState(appliedLocation.from.slice(5,7)||'01'),[quarter,setQuarter]=useState(String(Math.floor((Number(appliedLocation.from.slice(5,7)||1)-1)/3)+1)),[start,setStart]=useState(appliedLocation.from),[end,setEnd]=useState(appliedLocation.to);
 const location=opened?draft:appliedLocation;
 const change=(value:ReportLocation)=>{if(opened)setDraft(value);else applyChange(value);};
 const patch=(values:Partial<ReportLocation>)=>change({...location,...values,page:1});
 const pick=(id:string,label:string,value:string,items:{value:string;label:string}[],onChange:(value:string)=>void)=><Box><Label htmlFor={id}>{label}</Label><Select inputId={id} value={items.find(item=>item.value===value)||null} options={items} onChange={item=>onChange(item?.value||'')}/></Box>;
 const calendar=(kind:string,y=year,m=month,q=quarter)=>{setMode(kind);if(!/^\d{4}$/.test(y)||Number(y)<1900||Number(y)>9998)return;const first=kind==='specific-year'?1:kind==='specific-quarter'?(Number(q)-1)*3+1:Number(m),span=kind==='specific-year'?12:kind==='specific-quarter'?3:1;patch({range:kind,from:`${y}-${String(first).padStart(2,'0')}-01`,to:new Date(Date.UTC(Number(y),first-1+span,0)).toISOString().slice(0,10)});};
 const period=(value:string)=>{setMode(value);if(value.startsWith('specific-')){calendar(value);return;}if(value==='custom'){const defaults=reportLocation(new URL(window.location.origin));setStart(location.from||defaults.from);setEnd(location.to||defaults.to);setFromValid(true);setToValid(true);patch({range:'custom',from:location.from||defaults.from,to:location.to||defaults.to});return;}const defaults=reportLocation(new URL(window.location.origin));const today=new Date(defaults.to+'T12:00:00Z'),y=today.getUTCFullYear(),m=today.getUTCMonth();patch({range:value,from:value==='all'?'':value==='month'?`${y}-${String(m+1).padStart(2,'0')}-01`:value==='quarter'?`${y}-${String(Math.floor(m/3)*3+1).padStart(2,'0')}-01`:value==='year'?`${y}-01-01`:defaults.from,to:value==='all'?'':defaults.to});};
 const dates=(a:string,b:string)=>{setStart(a);setEnd(b);if(formDate(a)&&formDate(b)&&a<=b)patch({range:'custom',from:a,to:b});};
 const facets=(rows:{label:string}[]|undefined,value:string,all:string)=>[{value:'',label:all},...Array.from(new Set([value,...(rows||[]).map(row=>row.label)].filter(Boolean))).map(value=>({value,label:value}))];
 const chips=[{key:'status',label:location.status==='open'?'Not resolved':location.status==='resolved'?'Resolved':location.status==='reopened'?'Reopened':''},{key:'branch',label:location.branch},{key:'category',label:location.category},{key:'basis',label:location.basis==='resolved'?'Resolved dates':''},{key:'range',label:location.range!=='last30'?'Selected dates':''}].filter(item=>item.label);
 const show=()=>{setDraft({...appliedLocation});setMode(appliedLocation.range);setStart(appliedLocation.from);setEnd(appliedLocation.to);setYear(appliedLocation.from.slice(0,4)||String(new Date().getFullYear()));setMonth(appliedLocation.from.slice(5,7)||'01');setQuarter(String(Math.floor((Number(appliedLocation.from.slice(5,7)||1)-1)/3)+1));setFromValid(true);setToValid(true);setOpened(true);};
 const invalidDates=mode==='custom'&&(!fromValid||!toValid||!formDate(start)||!formDate(end)||start>end);
 const invalidYear=mode.startsWith('specific-')&&(!/^\d{4}$/.test(year)||Number(year)<1900||Number(year)>9998);
 const dateLabel=location.range==='last30'?'Last 30 days':!location.from&&!location.to?'All dates':`${displayDate(location.from)} - ${displayDate(location.to)}`;
 return <><ControlRow><Button aria-label="Change report date range" onClick={show}>{dateLabel}</Button><Button id="report-filters-open" onClick={show}>Filters{chips.length?` · ${chips.length}`:''}</Button>{actions}</ControlRow>{chips.length>0&&<Inline shouldWrap space="space.050">{chips.map(item=><Button key={item.key} onClick={()=>{if(item.key==='range')period('last30');else patch({[item.key]:item.key==='basis'?'reported':''});}}>{item.label} ×</Button>)}</Inline>}{opened&&<TaskDialog title="Filter reports" size="medium" close={()=>setOpened(false)}><Section title="Period"><Grid xcss={styles.fields} gap="space.150">
 {pick('report-period','Date range',mode||location.range,[['last30','Last 30 days'],['month','This month'],['quarter','This quarter'],['year','This year'],['specific-month','Specific month'],['specific-quarter','Specific quarter'],['specific-year','Specific year'],['all','All dates'],['custom','Custom dates']].map(([value,label])=>({value,label})),period)}
 {pick('report-basis','Count by',location.basis,[{value:'reported',label:'Reported date'},{value:'resolved',label:'Resolved date'}],basis=>patch({basis}))}
 {pick('report-time','Group by',location.grouping,['day','week','month','year'].map(value=>({value,label:value[0].toUpperCase()+value.slice(1)})),grouping=>patch({grouping}))}
 </Grid>{mode.startsWith('specific-')&&<Grid xcss={styles.fields} gap="space.150"><Box><Label htmlFor="report-year">Year</Label><Textfield id="report-year" type="number" value={year} onChange={event=>{setYear(event.currentTarget.value);calendar(mode,event.currentTarget.value);}}/></Box>{mode==='specific-month'&&pick('report-month','Month',month,Array.from({length:12},(_,i)=>({value:String(i+1).padStart(2,'0'),label:new Intl.DateTimeFormat('en-GB',{month:'long',timeZone:'UTC'}).format(new Date(Date.UTC(2026,i,1)))})),value=>{setMonth(value);calendar(mode,year,value);})}{mode==='specific-quarter'&&pick('report-quarter','Quarter',quarter,[1,2,3,4].map(value=>({value:String(value),label:`Q${value}`})),value=>{setQuarter(value);calendar(mode,year,month,value);})}</Grid>}
 {mode==='custom'&&<Grid xcss={styles.fields} gap="space.150"><DateControl id="date-from" label="From" value={start} change={value=>dates(value,end)} validity={setFromValid}/><DateControl id="date-to" label="To" value={end} change={value=>dates(start,value)} validity={setToValid}/></Grid>}{invalidDates&&<Text color="color.text.danger">Enter valid dates. The end date must be on or after the start date.</Text>}
 {invalidYear&&<Text color="color.text.danger">Enter a year from 1900 to 9998.</Text>}</Section><Section title="Complaints"><Grid xcss={styles.fields} gap="space.150">
 {pick('report-status','Status',location.status,[{value:'',label:'All complaints'},{value:'open',label:'Not resolved'},{value:'reopened',label:'Reopened only'},{value:'resolved',label:'Resolved'}],status=>patch({status}))}
 {pick('report-branch','Branch',location.branch,facets(options?.branches,location.branch,'All branches'),branch=>patch({branch}))}
 {pick('report-category','Complaint type',location.category,facets(options?.categories,location.category,'All types'),category=>patch({category}))}
 </Grid></Section><Button appearance="subtle" onClick={()=>{change(reportLocation(new URL(window.location.origin)));setMode('last30');setFromValid(true);setToValid(true);}}>Reset filters</Button><DialogFooter><Button shouldFitContainer onClick={()=>setOpened(false)}>Cancel</Button><Button shouldFitContainer appearance="primary" isDisabled={invalidDates||invalidYear} onClick={()=>{if(!invalidDates&&!invalidYear){applyChange(draft);setOpened(false);}}}>Apply filters</Button></DialogFooter></TaskDialog>}</>;
}
