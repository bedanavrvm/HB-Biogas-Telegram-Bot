import React, { useEffect, useRef } from 'react';
import { cssMap } from '@atlaskit/css';
import { Box } from '@atlaskit/primitives/compiled/box';
import { Text } from '@atlaskit/primitives/compiled/text';
import { Stack } from '@atlaskit/primitives/compiled/stack';
import { MetricText } from '@atlaskit/primitives/compiled/metric-text';
import { Pressable } from '@atlaskit/primitives/compiled/pressable';
import SectionMessage from '@atlaskit/section-message';
import { token } from '@atlaskit/tokens';
import { duration, type ReportSummary, type ReportSelection } from './complaints-report-charts';

export type PreviousSummary = Pick<ReportSummary, 'total'|'pending'|'resolved'|'card_timing'|'card_coverage'>;
const styles = cssMap({
  metrics: { display:'grid', gap:token('space.150'), gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', '@media (min-width: 48rem)': { gridTemplateColumns: 'repeat(3, minmax(0, 1fr))' }, '@media (min-width: 90rem)': { gridTemplateColumns: 'repeat(6, minmax(0, 1fr))' } },
  card: { minWidth: 0, display: 'grid', gridTemplateRows: 'auto 1fr auto', gap: token('space.100'), padding: token('space.150'), textAlign: 'start', backgroundColor: token('elevation.surface'), border: `${token('border.width')} solid ${token('color.border')}`, borderRadius: token('radius.medium'), overflowWrap: 'anywhere', '&:hover': { backgroundColor: token('color.background.neutral.subtle.hovered') } },
});
function comparison(current: number|null, previous: number|null, direction: number, unit = '') {
  if(current === null || previous === null) return {text:'No earlier data yet', color:'color.text.subtle' as const};
  const difference=current-previous, change=Number(Math.abs(difference).toFixed(unit===' pts'?0:1));
  const word=difference===0?'Unchanged':direction===0?'Change':difference*direction>0?'Better':'Worse';
  const color=word==='Better'?'color.text.success':word==='Worse'?'color.text.danger':'color.text.subtle';
  return {text:`${difference>0?'↑':difference<0?'↓':'→'} ${change}${unit} · ${word} · was ${Number(previous.toFixed(unit===' pts'?0:1))}${unit===' pts'?'%':unit}`,color} as const;
}
export function ReportMetrics({summary,previous,basis,select}:{summary:ReportSummary;previous:PreviousSummary|null;basis:string;select:(value:ReportSelection)=>void}) {
  const root=useRef<HTMLDivElement>(null);
  useEffect(()=>{const node=root.current!;const measure=()=>{const em=parseFloat(getComputedStyle(document.documentElement).fontSize),width=node.clientWidth;node.style.gridTemplateColumns=`repeat(${width>=72*em?6:width>=40*em?3:width>=16*em?2:1},minmax(0,1fr))`;};const resize=new ResizeObserver(measure),text=new MutationObserver(measure);resize.observe(node);text.observe(document.documentElement,{attributes:true,attributeFilter:['style']});measure();return()=>{resize.disconnect();text.disconnect();};},[]);
  const timing=summary.card_timing, before=previous?.card_timing, coverage=summary.card_coverage;
  const metrics: {label:string;value:string;current:number|null;previous:number|null;direction:number;unit:string;coverage?:{eligible:number;contributing:number};filters:Record<string,string>}[]=[
    {label:'Resolved on time',value:timing.on_time_percent===null?'Not available':`${Math.round(timing.on_time_percent)}%`,current:timing.on_time_percent,previous:before?.on_time_percent??null,direction:1,unit:' pts',coverage:coverage.on_time,filters:{metric:'on_time'}},
    ...([{label:'Median resolution',key:'median_resolution_hours',coverage:coverage.resolution,metric:'resolution'}, {label:'Median first response',key:'median_response_hours',coverage:coverage.first_response,metric:'hb_response'}] as const).map(item=>{
      const hours=timing[item.key],old=before?.[item.key]??null,days=hours!==null&&hours>=48;
      return {label:item.label,value:duration(hours),current:hours===null?null:hours/(days?24:1),previous:old===null?null:old/(days?24:1),direction:-1,unit:days?' days':' hours',coverage:item.coverage,filters:{metric:item.metric}};
    }),
    ...([{label:basis==='resolved'?'Resolved in range':'Reported in range',key:'total',direction:0,status:''},{label:'Still open',key:'pending',direction:-1,status:'open'},{label:'Closed',key:'resolved',direction:1,status:'resolved'}] as const).map(item=>({label:item.label,value:String(summary[item.key]),current:summary[item.key],previous:previous?.[item.key]??null,direction:item.direction,unit:'',coverage:undefined,filters:Object.fromEntries(item.status?[['status',item.status]]:[])})),
  ];
  const warnings=([{name:'first response',counts:coverage.first_response},{name:'resolution time',counts:coverage.resolution},{name:'resolution target',counts:coverage.on_time}]).filter(item=>item.counts.eligible>0&&item.counts.contributing/item.counts.eligible<0.5);
  return <Stack space="space.200"><Box ref={root} role="group" aria-label="Report metrics" xcss={styles.metrics}>{metrics.map(item=>{
    const delta=comparison(item.current,item.previous,item.direction,item.unit);
    const drill= !item.coverage;
    const Card=drill?Pressable:Box;
    return <Card key={item.label} xcss={styles.card} aria-label={`${drill?'View ':''}${item.label.toLowerCase()}${drill?' complaints':''}`} {...(drill?{onClick:()=>select({label:item.label,filters:{...item.filters,date_basis:basis}})}:{})}>
      <Text size="small" weight="medium" color="color.text.subtle">{item.label}</Text>
      <Stack space="space.050"><MetricText size="medium">{item.value}</MetricText>{item.coverage&&<Text size="small" color="color.text.subtle">Based on {item.coverage.contributing} of {item.coverage.eligible}</Text>}</Stack>
      <Text size="small" color={delta.color}>{delta.text}</Text>
    </Card>;
  })}</Box>{warnings.length>0&&<SectionMessage appearance="warning" title="Some timing is missing" headingLevel="h3">{warnings.map(item=><Text as="p" key={item.name}>{item.counts.eligible-item.counts.contributing} of {item.counts.eligible} complaints have no recorded {item.name}. This metric does not describe every eligible complaint.</Text>)}</SectionMessage>}</Stack>;
}
