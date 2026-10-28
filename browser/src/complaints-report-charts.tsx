import React, { useEffect, useRef, useState } from 'react';
import Button from '@atlaskit/button/default/button';
import { cssMap } from '@atlaskit/css';
import { Label } from '@atlaskit/form';
import Heading from '@atlaskit/heading';
import { Box } from '@atlaskit/primitives/compiled/box';
import { Grid } from '@atlaskit/primitives/compiled/grid';
import { Inline } from '@atlaskit/primitives/compiled/inline';
import { Stack } from '@atlaskit/primitives/compiled/stack';
import { Text } from '@atlaskit/primitives/compiled/text';
import { AdaptiveSelect as Select } from './complaints-ui';
import { IconButton } from '@atlaskit/button/new';
import InfoIcon from '@atlaskit/icon/core/information-circle';
import { displayDate, complaintCount, TaskDialog, ActionMenu } from './complaints-ui';
import { token } from '@atlaskit/tokens';

type Count = { label: string; count: number };
type TimingRow = Count & { hours: number | null };
export type ReportSummary = {
  total: number; pending: number; resolved: number; calculated_at: string;
  by_category: Count[]; by_time: Count[];
  filter_options: { branches: Count[]; categories: Count[] };
  activity: { label: string; received: number; resolved: number }[];
  reported_outcomes: { label: string; closed: number; open: number }[];
  open_age: (Count & { key: string })[];
  resolution_trend: TimingRow[]; resolution_by_category: TimingRow[];
  response_trend: TimingRow[]; reopenings: Count[];
  card_coverage: {resolution:{eligible:number;contributing:number};first_response:{eligible:number;contributing:number};on_time:{eligible:number;contributing:number}};
  card_timing: Timing;
  timing: Timing;
};
export type Timing = {
    median_resolution_hours: number | null; resolution_count: number;
    resolution_excluded: number; median_response_hours: number | null;
    response_count: number; response_unavailable: number; age_unavailable: number;
    on_time: number; late: number; on_time_percent: number | null; target_unavailable: number;
};
export type ReportSelection = { label: string; filters: Record<string, string> };
type Point = { label: string; values: (number | null)[]; count?: number };
type Series = { label: string; color: string };
type ChartSpec = {
  id: string; title: string; help: string; note?: string; rows: Point[];
  series: Series[]; hours?: boolean; horizontal?: boolean; temporal?: boolean;
  select: (index: number, series: number) => ReportSelection;
};
const styles = cssMap({
  columns: { gridTemplateColumns: 'repeat(1, minmax(0, 1fr))', '@media (min-width: 48rem)': { gridTemplateColumns: 'repeat(2, minmax(0, 1fr))' }, alignItems: 'stretch' },
  full: { gridColumn: '1 / -1' },
  panel: { height:'100%', minWidth: 0, boxSizing: 'border-box', backgroundColor:token('elevation.surface'), padding: token('space.200'), borderStyle: 'solid', borderWidth: token('border.width'), borderColor: token('color.border'), borderRadius: token('radius.medium'), overflowWrap: 'anywhere' },
  chart: { width: '100%', font: token('font.body.small'), overflowX: 'auto' },
  hint: {minHeight:'1.25rem',overflowWrap:'anywhere'},
});
export function duration(hours: number | null) {
  if (hours === null) return 'Not available';
  if (hours > 0 && hours < 1) return 'Under 1 hour';
  const days=hours>=48, value=Number((hours/(days?24:1)).toFixed(1));
  return `${value} ${days?(value===1?'day':'days'):(value===1?'hour':'hours')}`;
}
function date(value: string) { return displayDate(value, value.length === 7); }
function period(label: string, grouping: string, from: string, to: string) {
  const [year, month = 1, day = 1] = label.split('-').map(Number);
  const start = `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
  const end = new Date(Date.UTC(year, grouping === 'year' ? 12 : grouping === 'month' ? month : month - 1, grouping === 'year' || grouping === 'month' ? 0 : day + (grouping === 'week' ? 6 : 0))).toISOString().slice(0, 10);
  // A week touching the chosen range must not include cases outside that range.
  return { date_from: from && from > start ? from : start, date_to: to && to < end ? to : end };
}
const blue = token('color.chart.brand'), green = token('color.chart.success');

export function ReportCharts({ summary, view, grouping, from, to, select }: {
  summary: ReportSummary; view: string; grouping: string; from: string; to: string;
  select: (selection: ReportSelection) => void;
}) {
  const timing = summary.timing;
  const temporal = (label: string, metric: string, basis: string) => ({ ...period(label, grouping, from, to), metric, date_basis: basis });
  const countSeries = [{ label: 'Complaints', color: blue }];
  const specifications: ChartSpec[] = view === 'turnaround' ? [
    { id: 'resolution', title: 'How long do resolutions take?', help: 'Median time from reporting to final resolution, grouped by resolution date. Only complaints currently closed are included.',
      note: timing.resolution_excluded ? `${timing.resolution_excluded} closed complaints have no usable resolution time.` : '',
      rows: summary.resolution_trend.map(row => ({ ...row, values: [row.hours] })), series: [{ label: 'Median resolution', color: blue }], hours: true, temporal: true,
      select: index => ({ label: `Resolved: ${date(summary.resolution_trend[index].label)}`, filters: temporal(summary.resolution_trend[index].label, 'resolution', 'resolved') }) },
    { id: 'category-time', title: 'Resolution by complaint type', help: 'Median time to final resolution for each complaint type. Uses resolution dates and only complaints currently closed.',
      rows: summary.resolution_by_category.map(row => ({ ...row, values: [row.hours] })), series: [{ label: 'Median resolution', color: blue }], hours: true, horizontal: true,
      select: index => ({ label: `Resolved: ${summary.resolution_by_category[index].label}`, filters: { category: summary.resolution_by_category[index].label, date_basis: 'resolved', metric: 'resolution' } }) },
    { id: 'response', title: 'First response time', help: 'Median wait from reporting to the first recorded HomeBiogas comment or resolution. Grouped by first response date.',
      note: 'Uses first response dates. KPI cards use the selected complaint cohort.',
      rows: summary.response_trend.map(row => ({ ...row, values: [row.hours] })), series: [{ label: 'Median first response', color: blue }], hours: true, temporal: true,
      select: index => ({ label: `First response: ${date(summary.response_trend[index].label)}`, filters: temporal(summary.response_trend[index].label, 'hb_response', 'response') }) },
  ] : view === 'follow-up' ? [
    { id: 'age', title: 'Open-case age', help: 'Age since the original report, including reopened complaints. Only unresolved complaints reported in the selected dates are included.',
      note: timing.age_unavailable ? `${timing.age_unavailable} complaints have no usable age.` : '',
      rows: summary.open_age.map(row => ({ ...row, label: row.label.replace(/[\u2013\u2014]/g, '-'), values: [row.count] })), series: countSeries, horizontal: true,
      select: index => ({ label: `Open: ${summary.open_age[index].label}`, filters: { date_basis: 'reported', metric: 'open_age', metric_value: summary.open_age[index].key } }) },
    { id: 'reopened', title: 'Complaints reopened', help: 'Complaints returned to open after resolution, grouped by reopening date. A complaint counts once per period even if reopened repeatedly.',
      rows: summary.reopenings.map(row => ({ ...row, values: [row.count] })), series: [{ label: 'Reopened', color: token('color.chart.warning') }], temporal: true,
      select: index => ({ label: `Reopened: ${date(summary.reopenings[index].label)}`, filters: temporal(summary.reopenings[index].label, 'reopened', 'reopened') }) },
  ] : [
    { id: 'activity', title: 'Reported vs resolved', help: 'New complaints reported and complaints resolved in each period. Resolutions may include complaints reported earlier; they are not a subtraction from new reports.',
      rows: summary.activity.map(row => ({ label: row.label, values: [row.received, row.resolved] })), series: [{ label: 'Reported', color: blue }, { label: 'Resolved', color: green }], temporal: true,
      select: (index, series) => ({ label: `${series ? 'Resolved' : 'Reported'}: ${date(summary.activity[index].label)}`, filters: temporal(summary.activity[index].label, series ? 'closures' : 'received', series ? 'closures' : 'reported') }) },
    { id: 'category', title: 'Complaint types', help: 'Complaints reported in the selected dates, grouped by complaint type. Totals and results can use a different date basis; this chart uses the date each complaint was reported.',
      rows: summary.by_category.map(row => ({ ...row, values: [row.count] })), series: countSeries, horizontal: true,
      select: index => ({ label: summary.by_category[index].label, filters: { category: summary.by_category[index].label, metric: 'received', date_basis: 'reported' } }) },
  ];
  const charts = specifications.filter(spec => !(spec.id==='response'&&spec.rows.length===0) && !(spec.id==='category'&&spec.rows.length<2));
  const grouped=charts.filter(spec=>spec.rows.filter(row=>row.values.some(value=>value!==null)).length>1),single=charts.filter(spec=>!grouped.includes(spec));
  return <Stack space="space.200">
    {view === 'overview' && summary.by_category.length === 1 && <Text size="small" color="color.text.subtle">Complaint type: {summary.by_category[0].label}</Text>}
    <Grid xcss={styles.columns} gap="space.200">{grouped.map((spec, index) => <Box key={spec.id} xcss={grouped.length % 2 === 1 && index === grouped.length - 1 ? styles.full : undefined}><Chart spec={spec} select={select} grouping={grouping} /></Box>)}</Grid>{single.map(spec=><Chart key={spec.id} spec={spec} select={select} grouping={grouping}/>)}
  </Stack>;
}

/** Chart geometry is first-party; controls and presentation use the pinned ADS graph. */
function RadialChart({spec,doughnut,select}:{spec:ChartSpec;doughnut:boolean;select:(index:number,series:number)=>void}) {
  const values=spec.rows.map(row=>row.values.reduce<number>((sum,value)=>sum+(value||0),0)),total=values.reduce((sum,value)=>sum+value,0);
  const outside=values.map((value,index)=>{const start=values.slice(0,index).reduce((sum,n)=>sum+n,0),middle=-Math.PI/2+(start+value/2)/Math.max(1,total)*Math.PI*2;return {x:Math.cos(middle)<0?22:338,y:130+Math.sin(middle)*112,small:value/Math.max(1,total)*Math.PI*2<0.4};});
  for(const side of [22,338]){const labels=outside.filter(item=>item.small&&item.x===side).sort((a,b)=>a.y-b.y);let previous=10;labels.forEach(item=>{item.y=Math.max(item.y,previous+18);previous=item.y;});const overflow=Math.max(0,previous-246);labels.forEach(item=>{item.y-=overflow;});}
  let angle=-Math.PI/2;
  const colors=[token('color.chart.categorical.1'),token('color.chart.categorical.2'),token('color.chart.categorical.3'),token('color.chart.categorical.4'),token('color.chart.categorical.5'),token('color.chart.categorical.6'),token('color.chart.categorical.7'),token('color.chart.categorical.8')];
  return <Stack space="space.100"><svg viewBox="0 0 360 260" width="100%" role="group" aria-label={spec.title}>{values.map((value,index)=>{
    const start=angle,end=start+(total?value/total:0)*Math.PI*2;angle=end;if(!value)return null;const point=(a:number,r=90)=>[180+Math.cos(a)*r,130+Math.sin(a)*r];const [x,y]=point(start),[ex,ey]=point(end),[mx,my]=point(start+Math.PI);
    const path=value===total?`M180 130 L${x} ${y} A90 90 0 1 1 ${mx} ${my} A90 90 0 1 1 ${x} ${y} Z`:`M180 130 L${x} ${y} A90 90 0 ${end-start>Math.PI?1:0} 1 ${ex} ${ey} Z`;
    const middle=(start+end)/2,small=end-start<0.4,[lx,ly]=small?[outside[index].x,outside[index].y]:point(middle,doughnut?70:56),series=spec.rows[index].values.findIndex(v=>v!==null&&v>0);
    return <g key={index} role="button" tabIndex={0} aria-label={`${spec.rows[index].label}: ${complaintCount(value)}. Filter results.`} onClick={()=>select(index,Math.max(0,series))} onKeyDown={event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();select(index,Math.max(0,series));}}}><title>{spec.rows[index].label}: {value}</title><path d={path} fill={colors[index%colors.length]}/>{small&&<line x1={point(middle)[0]} y1={point(middle)[1]} x2={lx} y2={ly} stroke={token('color.border.bold')}/>}<text x={lx} y={ly} textAnchor="middle" dominantBaseline="middle" fill={small?token('color.text'):token('color.text.inverse')}>{value}</text></g>;
  })}{doughnut&&<circle cx="180" cy="130" r="48" fill={token('elevation.surface')}/>}</svg><Inline shouldWrap space="space.150">{spec.rows.map((row,index)=><Inline key={row.label} alignBlock="center" space="space.050"><svg width="14" height="14" aria-hidden="true"><rect width="14" height="14" fill={colors[index%colors.length]}/></svg><Text size="small">{row.label}: {values[index]} ({total?Math.round(values[index]/total*100):0}%)</Text></Inline>)}</Inline></Stack>;
}
function Chart({ spec, select, grouping }: { spec: ChartSpec; select: (selection: ReportSelection) => void; grouping: string }) {
  const root=useRef<HTMLDivElement>(null);
  const [width,setWidth]=useState(500),[chosen,setChosen]=useState(''),[hover,setHover]=useState(''),[help,setHelp]=useState(false);
  const original=spec.horizontal?spec.rows.slice(0,10):spec.rows;
  const comparable=original.filter(row=>row.values.some(value=>value!==null)).length;
  const choices=['bar',...(spec.hours?['dot']:[]),...(spec.temporal&&comparable>=8?['line']:[]),...(!spec.hours&&spec.horizontal&&spec.rows.length>1&&spec.rows.length<=8?['doughnut','pie']:[])];
  const mode=choices.includes(chosen)?chosen:spec.hours?'dot':'bar',radial=mode==='pie'||mode==='doughnut';
  const rows:{point:Point;index:number}[]=original.map((point,index)=>({point,index}));
  // Insert missing temporal observations as gaps, never invented zero durations.
  if(spec.temporal&&original.length>1){
    const labels=new Map(rows.map(row=>[row.point.label,row]));
    const first=original[0].label,last=original[original.length-1].label;
    let cursor=new Date(first+(first.length===4?'-01-01':first.length===7?'-01':'')+'T00:00:00Z');
    rows.length=0;
    while(true){
      const label=cursor.toISOString().slice(0,grouping==='year'?4:grouping==='month'?7:10);
      if(label>last)break;
      rows.push(labels.get(label)||{point:{label,values:spec.series.map(()=>spec.hours?null:0)},index:-1});
      if(grouping==='year')cursor.setUTCFullYear(cursor.getUTCFullYear()+1);
      else if(grouping==='month')cursor.setUTCMonth(cursor.getUTCMonth()+1);
      else cursor.setUTCDate(cursor.getUTCDate()+(grouping==='week'?7:1));
    }
  }
  const hasData=original.some(row=>row.values.some(value=>value!==null&&(spec.hours||value>0)));
  useEffect(()=>{const observer=new ResizeObserver(entries=>setWidth(Math.max(230,entries[0].contentRect.width)));if(root.current)observer.observe(root.current);return()=>observer.disconnect();},[hasData,mode]);
  const rawMax=Math.max(0,...rows.flatMap(row=>row.point.values.filter((value):value is number=>value!==null)));
  const days=Boolean(spec.hours&&rawMax>=48),factor=days?24:1,unit=spec.hours?(days?'days':'hours'):'complaints';
  const nice=(value:number)=>{const power=10**Math.floor(Math.log10(Math.max(value,0.1))),scaled=value/power;return (scaled<=1?1:scaled<=2?2:scaled<=5?5:10)*power;};
  const step=spec.hours?days?Math.max(1,nice(rawMax/24/4)):rawMax>24?24:Math.max(0.5,nice(rawMax/4)):Math.max(1,nice(rawMax/4));
  const maximum=Math.max(step*2,Math.ceil(rawMax/factor/step)*step);
  const left=spec.horizontal?Math.min(160,width*0.38):64,right=width-24,top=spec.series.length>1?48:32,bottom=spec.horizontal?top+rows.length*36:184,height=bottom+(spec.horizontal?44:rows.length>3?84:48);
  const x=(index:number)=>left+(index+0.5)*(right-left)/Math.max(1,rows.length);
  const y=(value:number)=>bottom-value/factor/maximum*(bottom-top);
  const tick=(label:string)=>spec.temporal?displayDate(label,grouping==='month'):label;
  const number=(value:number)=>{const rounded=Number((value/factor).toFixed(1));return value>0&&rounded===0?'<0.1':String(rounded);};
  const text=(point:Point,series:number)=>`${tick(point.label)} · ${spec.series[series].label}: ${spec.hours?number(point.values[series]!)+' '+unit:complaintCount(point.values[series]!)}${point.count!==undefined?' · '+complaintCount(point.count):''}`;
  const activate=(index:number,series:number)=>{if(index>=0)select(spec.select(index,series));};
  const dateTitle=spec.id==='activity'?'Date reported / resolved':spec.id==='resolution'?'Date resolved':spec.id==='response'?'Date first response':spec.id==='reopened'?'Date reopened':'Period';
  const valueTitle=spec.hours?`Median time (${unit})`:'Complaints';
  const categoryTitle=spec.id==='age'?'Time open':spec.id==='category-time'||spec.id==='category'?'Complaint type':'Outcome';
  const maxTicks=Math.max(2,Math.floor((right-left)/100)),stride=Math.max(1,Math.ceil(rows.length/maxTicks));
  const valueStride=Math.max(1,Math.ceil(rows.length*spec.series.length*(Math.max(...rows.flatMap(row=>row.point.values.filter((value):value is number=>value!==null).map(value=>number(value).length)),1)*7+12)/(right-left)));
  const label=(row:Point,s:number)=>`${text(row,s)}. Filter results.`;
  const count=rows.filter(row=>row.point.values.some(value=>value!==null)).length;
  return <Box xcss={styles.panel} role="region" aria-label={spec.title+' chart'}><Stack space="space.150">
    <Inline shouldWrap spread="space-between" alignBlock="center" space="space.100"><Inline shouldWrap alignBlock="center" space="space.050"><Heading as="h3" size="small">{spec.title}</Heading><IconButton label={'About '+spec.title} appearance="subtle" icon={InfoIcon} onClick={()=>setHelp(true)}/></Inline>{count>1&&<ActionMenu label="Chart options" items={choices.map(value=>({label:value[0].toUpperCase()+value.slice(1)+' chart',selected:mode===value,run:()=>setChosen(value)}))}/>}</Inline>
    {help&&<TaskDialog title={spec.title} compact close={()=>setHelp(false)}><Text>{spec.help} {spec.hours?'Values are shown in '+unit+'.':''}</Text></TaskDialog>}
    {!hasData?<Text>{spec.hours?'No recorded timing in this period.':'No matching complaints.'}</Text>:count===1?<Stack space="space.100">{original.flatMap((point,index)=>point.values.map((value,s)=>value===null?null:<Box key={s}><Stack space="space.100"><Text weight="medium">{tick(point.label)}</Text><Text>{spec.series[s].label}: {spec.hours?duration(value):complaintCount(value)}{spec.hours&&point.count!==undefined?` · ${complaintCount(point.count)} recorded`:""}</Text><Inline><Button onClick={()=>activate(index,s)}>View complaints</Button></Inline></Stack></Box>))}</Stack>:<Box ref={root} xcss={styles.chart}>
      {spec.series.length>1&&<Inline shouldWrap space="space.150">{spec.series.map(series=><Inline key={series.label} alignBlock="center" space="space.050"><svg width="14" height="14" aria-hidden="true"><rect x="2" y="2" width="10" height="10" fill={series.color}/></svg><Text size="small">{series.label}</Text></Inline>)}</Inline>}
      {radial?<RadialChart spec={spec} doughnut={mode==='doughnut'} select={activate}/>:<svg viewBox={`0 0 ${width} ${height}`} width="100%" role="group" aria-label={spec.title+'. '+valueTitle}>
        {Array.from({length:Math.round(maximum/step)+1},(_,i)=>i*step).map(value=>{const ratio=value/maximum;return <g key={value}><line x1={spec.horizontal?left+ratio*(right-left):left} x2={spec.horizontal?left+ratio*(right-left):right} y1={spec.horizontal?top:bottom-ratio*(bottom-top)} y2={spec.horizontal?bottom:bottom-ratio*(bottom-top)} stroke={token('color.border')}/><text x={spec.horizontal?left+ratio*(right-left):left-8} y={spec.horizontal?bottom+20:bottom-ratio*(bottom-top)+4} textAnchor={spec.horizontal?'middle':'end'} fill={token('color.text.subtle')}>{Number(value.toFixed(1))}{spec.hours?(days?' d':' h'):''}</text></g>;})}
        <line x1={left} x2={left} y1={top} y2={bottom} stroke={token('color.border.bold')} strokeWidth={1.5}/><line x1={left} x2={right} y1={bottom} y2={bottom} stroke={token('color.border.bold')} strokeWidth={1.5}/>
        <text x={(left+right)/2} y={height-8} textAnchor="middle" fill={token('color.text.subtle')}>{spec.horizontal?valueTitle:spec.temporal?dateTitle:categoryTitle}</text>
        <text x={14} y={(top+bottom)/2} transform={`rotate(-90 14 ${(top+bottom)/2})`} textAnchor="middle" fill={token('color.text.subtle')}>{spec.horizontal?categoryTitle:valueTitle}</text>
        {mode==='line'&&spec.series.map((series,s)=>{let connected=false;const path=rows.map((row,i)=>{const value=row.point.values[s];if(value===null){connected=false;return '';}const part=`${connected?'L':'M'}${x(i)} ${y(value)}`;connected=true;return part;}).join(' ');return <path key={s} d={path} fill="none" stroke={series.color} strokeWidth={2} strokeDasharray={s?'6 4':undefined}/>;})}
        {rows.map(({point,index},i)=><g key={point.label}>
          {point.values.map((value,s)=>{if(value===null)return null;const band=Math.min(34,(right-left)/Math.max(1,rows.length)/spec.series.length*0.7),px=x(i)+(mode==='bar'?(s-(spec.series.length-1)/2)*band:0),py=y(value),length=value/factor/maximum*(right-left),inside=spec.horizontal?length>number(value).length*8+18:bottom-py>30&&band>number(value).length*7+6;
            const active=()=>activate(index,s),mark=spec.horizontal?(mode==='dot'?<circle cx={left+length} cy={top+i*36+19} r={5} fill={spec.series[s].color}/>:<rect x={left} y={top+i*36+8} width={Math.max(2,length)} height={22} fill={spec.series[s].color}/>):mode==='bar'?<rect x={px-band/2} y={py} width={band} height={Math.max(2,bottom-py)} fill={spec.series[s].color}/>:<circle cx={px} cy={py} r={5} fill={spec.series[s].color}/>;
            const near=s>0&&point.values[0]!==null&&Math.abs(py-y(point.values[0]))<18;
            return <g key={s} role={index>=0?'button':undefined} tabIndex={index>=0?0:undefined} aria-label={index>=0?label(point,s):undefined} onClick={active} onKeyDown={event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();active();}}} onMouseEnter={()=>setHover(text(point,s))} onMouseLeave={()=>setHover('')} onFocus={()=>setHover(text(point,s))} onBlur={()=>setHover('')}>
              {mark}{(spec.horizontal||i%valueStride===0)&&<text x={spec.horizontal?left+length+(mode==='dot'?0:inside?-6:6):px} y={spec.horizontal?top+i*36+(mode==='dot'?6:23):mode==='bar'&&inside?py+16:py-10-(near?18:0)} textAnchor={spec.horizontal&&mode!=='dot'?(inside?'end':'start'):'middle'} fill={inside&&mode==='bar'?token('color.text.inverse'):token('color.text')}>{number(value)}</text>}
            </g>;
          })}
          {spec.horizontal?<text x={left-8} y={top+i*36+23} textAnchor="end" fill={token('color.text')}>{point.label.length>Math.floor(left/7)?point.label.slice(0,Math.floor(left/7)-3)+'…':point.label}</text>:i%stride===0&&<text x={x(i)} y={bottom+20} transform={rows.length>3?`rotate(-40 ${x(i)} ${bottom+20})`:undefined} textAnchor={rows.length>3?'end':'middle'} fill={token('color.text.subtle')}>{tick(point.label)}</text>}
        </g>)}
      </svg>}
      <Box xcss={styles.hint} aria-live="polite"><Text size="small" color="color.text.subtle">{hover||'Select a value to see its complaints below.'}</Text></Box>
    </Box>}
    {spec.note&&<Text size="small" color="color.text.subtle">{spec.note}</Text>}
    {spec.rows.length>10&&spec.horizontal&&<Box><Label htmlFor={spec.id+'-cases'}>All complaint types</Label><Select inputId={spec.id+'-cases'} value={null} options={spec.rows.map((row,index)=>({value:String(index),label:row.label+' · '+row.values.filter(value=>value!==null).join(', ')}))} onChange={option=>{if(option)activate(Number(option.value),0);}}/></Box>}
  </Stack></Box>;
}
