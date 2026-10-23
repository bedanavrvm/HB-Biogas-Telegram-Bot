import React, { useEffect, useRef, useState } from 'react';
import { cssMap, cx } from '@atlaskit/css';
import { Label } from '@atlaskit/form';
import Heading from '@atlaskit/heading';
import { Box } from '@atlaskit/primitives/compiled/box';
import { Grid } from '@atlaskit/primitives/compiled/grid';
import { Inline } from '@atlaskit/primitives/compiled/inline';
import { Stack } from '@atlaskit/primitives/compiled/stack';
import { Text } from '@atlaskit/primitives/compiled/text';
import { AdaptiveSelect as Select } from './complaints-ui';
import { IconButton } from '@atlaskit/button/new';
import BarChartIcon from '@atlaskit/icon/core/chart-bar';
import LineChartIcon from '@atlaskit/icon/core/chart-trend-up';
import PieChartIcon from '@atlaskit/icon/core/chart-pie';
import InfoIcon from '@atlaskit/icon/core/information-circle';
import { displayDate, complaintCount, TaskDialog } from './complaints-ui';
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
  timing: {
    median_resolution_hours: number | null; resolution_count: number;
    resolution_excluded: number; median_response_hours: number | null;
    response_count: number; response_unavailable: number; age_unavailable: number;
    on_time: number; late: number; on_time_percent: number | null; target_unavailable: number;
  };
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
  metrics: { display: 'grid', gap: token('space.100'), gridTemplateColumns: 'repeat(3, minmax(0, 1fr))' },
  metricsStacked: { gridTemplateColumns: 'repeat(1, minmax(0, 1fr))' },
  panel: { minWidth: 0, height: '100%', boxSizing: 'border-box', padding: token('space.200'), borderStyle: 'solid', borderWidth: token('border.width'), borderColor: token('color.border'), borderRadius: token('radius.medium'), overflowWrap: 'anywhere' },
  metric: { minWidth: 0, padding: token('space.100'), borderStyle: 'solid', borderWidth: token('border.width'), borderColor: token('color.border'), borderRadius: token('radius.medium'), overflowWrap: 'anywhere', display: 'grid', gridTemplateRows: 'auto 1fr auto', gap: token('space.050') },
  chart: { width: '100%', font: token('font.body.small'), overflowX: 'auto' },
});
export function duration(hours: number | null) {
  if (hours === null) return 'Not available';
  if (hours > 0 && hours < 1) return 'Under 1 hour';
  const value = Number(hours.toFixed(1));
  return `${value} ${value === 1 ? 'hour' : 'hours'}${hours >= 24 ? ` (${Number((hours / 24).toFixed(1))} days)` : ''}`;
}
function date(value: string) { return displayDate(value, value.length === 7); }
function period(label: string, grouping: string, from: string, to: string) {
  const [year, month = 1, day = 1] = label.split('-').map(Number);
  const start = `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
  const end = new Date(Date.UTC(year, grouping === 'year' ? 12 : grouping === 'month' ? month : month - 1, grouping === 'year' || grouping === 'month' ? 0 : day + (grouping === 'week' ? 6 : 0))).toISOString().slice(0, 10);
  // A week touching the chosen range must not include cases outside that range.
  return { date_from: from && from > start ? from : start, date_to: to && to < end ? to : end };
}
const blue = token('color.chart.brand'), green = token('color.chart.success'), red = token('color.chart.danger');

export function ReportCharts({ summary, view, grouping, from, to, select }: {
  summary: ReportSummary; view: string; grouping: string; from: string; to: string;
  select: (selection: ReportSelection) => void;
}) {
  const [stackMetrics,setStackMetrics]=useState(false);
  useEffect(()=>{const measure=()=>setStackMetrics(innerWidth<20*parseFloat(getComputedStyle(document.documentElement).fontSize));const observer=new MutationObserver(measure);observer.observe(document.documentElement,{attributes:true,attributeFilter:['style']});window.addEventListener('resize',measure);measure();return()=>{observer.disconnect();window.removeEventListener('resize',measure);};},[]);
  const timing = summary.timing;
  const temporal = (label: string, metric: string, basis: string) => ({ ...period(label, grouping, from, to), metric, date_basis: basis });
  const countSeries = [{ label: 'Complaints', color: blue }];
  const specifications: ChartSpec[] = view === 'turnaround' ? [
    { id: 'resolution', title: 'Resolution time', help: 'Median time from reporting to final resolution, grouped by resolution date. Only complaints currently closed are included.',
      note: timing.resolution_excluded ? `${timing.resolution_excluded} closed complaints have no usable resolution time.` : '',
      rows: summary.resolution_trend.map(row => ({ ...row, values: [row.hours] })), series: [{ label: 'Median resolution', color: blue }], hours: true, temporal: true,
      select: index => ({ label: `Resolved: ${date(summary.resolution_trend[index].label)}`, filters: temporal(summary.resolution_trend[index].label, 'resolution', 'resolved') }) },
    { id: 'targets', title: 'Resolution targets', help: 'Complaints currently closed, compared with their recorded target. Uses resolution dates, not reporting dates.',
      note: `${timing.on_time + timing.late} of ${timing.resolution_count} timed resolutions had a target set.${timing.target_unavailable ? ` ${timing.target_unavailable} had no target.` : ''}`,
      rows: [{ label: 'On time', values: [timing.on_time, null] }, { label: 'Late', values: [null, timing.late] }], series: [{ label: 'On time', color: green }, { label: 'Late', color: red }], horizontal: true,
      select: index => ({ label: index ? 'Resolved late' : 'Resolved on time', filters: { date_basis: 'resolved', metric: index ? 'late' : 'on_time' } }) },
    { id: 'category-time', title: 'Resolution by complaint type', help: 'Median time to final resolution for each complaint type. Uses resolution dates and only complaints currently closed.',
      rows: summary.resolution_by_category.map(row => ({ ...row, values: [row.hours] })), series: [{ label: 'Median resolution', color: blue }], hours: true, horizontal: true,
      select: index => ({ label: `Resolved: ${summary.resolution_by_category[index].label}`, filters: { category: summary.resolution_by_category[index].label, date_basis: 'resolved', metric: 'resolution' } }) },
    { id: 'response', title: 'Home Based response time', help: 'Median wait from reporting to the first recorded Home Based comment or resolution. Grouped by first response date.',
      note: timing.response_unavailable ? `${timing.response_unavailable} complaints reported in these dates have no recorded Home Based response.` : '',
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
  const charts = specifications.filter(spec => spec.id !== 'category' || spec.rows.length > 1);
  return <Stack space="space.200">
    {view === 'overview' && summary.by_category.length === 1 && <Text size="small" color="color.text.subtle">Complaint type: {summary.by_category[0].label}</Text>}
    {view === 'turnaround' && <Box xcss={cx(styles.metrics,stackMetrics&&styles.metricsStacked)} role="group" aria-label="Turnaround metrics">{[
      ['Resolved on time', timing.on_time_percent === null ? 'No targets set' : `${Math.round(timing.on_time_percent)}%`, `${timing.on_time} of ${timing.on_time + timing.late} resolutions with targets`],
      ['Median resolution', duration(timing.median_resolution_hours), `${timing.resolution_count} timed resolutions`],
      ['Median first response', duration(timing.median_response_hours), `${timing.response_count} first ${timing.response_count === 1 ? 'response' : 'responses'}`],
    ].map(([label, value, note]) => <Box key={label} xcss={styles.metric}><Text size="small" color="color.text.subtle" weight="medium">{label}</Text><Heading as="h3" size="small">{value}</Heading><Text size="small" color="color.text.subtle">{note}</Text></Box>)}</Box>}
    <Grid xcss={styles.columns} gap="space.200">{charts.map((spec, index) => <Box key={spec.id} xcss={charts.length % 2 === 1 && index === charts.length - 1 ? styles.full : undefined}><Chart spec={spec} select={select} grouping={grouping} /></Box>)}</Grid>
  </Stack>;
}

/** Chart geometry is first-party; controls and presentation use the pinned ADS graph. */
/* eslint-disable @atlaskit/design-system/no-html-button -- Interactive SVG marks have keyboard semantics and a textual alternative; ADS cannot render an SVG mark. See DESIGN.md. */
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
    return <g key={index} role="button" tabIndex={0} aria-label={`${spec.rows[index].label}: ${complaintCount(value)}. Filter results.`} onClick={()=>select(index,Math.max(0,series))} onKeyDown={event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();select(index,Math.max(0,series));}}}><title>{spec.rows[index].label}: {value}</title><path d={path} fill={spec.id==='targets'?spec.series[Math.max(0,series)].color:colors[index%colors.length]}/>{small&&<line x1={point(middle)[0]} y1={point(middle)[1]} x2={lx} y2={ly} stroke={token('color.border.bold')}/>}<text x={lx} y={ly} textAnchor="middle" dominantBaseline="middle" fill={small?token('color.text'):token('color.text.inverse')}>{value}</text></g>;
  })}{doughnut&&<circle cx="180" cy="130" r="48" fill={token('elevation.surface')}/>}</svg><Inline shouldWrap space="space.150">{spec.rows.map((row,index)=><Text key={row.label} size="small">{row.label}: {values[index]} ({total?Math.round(values[index]/total*100):0}%)</Text>)}</Inline></Stack>;
}
function Chart({ spec, select, grouping }: { spec: ChartSpec; select: (selection: ReportSelection) => void; grouping: string }) {
  const root = useRef<HTMLDivElement>(null);
  const [measuredWidth, setWidth] = useState(500), [chosenMode, setChosenMode] = useState(''), [selected, setSelected] = useState(''), [hover, setHover] = useState(''), [helpOpen,setHelpOpen]=useState(false);
  const hasData = spec.rows.some(row => row.values.some(value => value !== null && (spec.hours || value > 0)));
  useEffect(() => { const observer = new ResizeObserver(entries => setWidth(Math.max(230, entries[0].contentRect.width))); if (root.current) observer.observe(root.current); return () => observer.disconnect(); }, [hasData]);
  const rows = spec.horizontal ? spec.rows.slice(0, 10) : spec.rows;
  const mode = chosenMode || (spec.temporal && rows.length >= 8 ? 'line' : 'bar');
  const radial=mode==='pie'||mode==='doughnut';
  const width=spec.temporal?Math.max(measuredWidth,rows.length*44+76):measuredWidth;
  const maximumValue = Math.max(0, ...rows.flatMap(row => row.values.filter((value): value is number => value !== null)));
  const maximum = spec.hours ? Math.max(1, Math.ceil(maximumValue * 1.2 * 2) / 2) : Math.max(2, Math.ceil(maximumValue * 1.2 / 2) * 2);
  const left = spec.horizontal ? Math.min(150, width * 0.38) : rows.length>5?76:48, right = width - 18, top = 40;
  const bottom = spec.horizontal ? top + Math.max(1, rows.length) * 40 : 206, height = bottom + (rows.length>5?100:55);
  const stamp = (label: string) => Date.parse(`${label.length === 4 ? label + '-01-01' : label.length === 7 ? label + '-01' : label}T00:00:00Z`);
  const stamps = spec.temporal ? rows.map(row => stamp(row.label)) : [];
  const span = stamps.length > 1 ? stamps[stamps.length - 1] - stamps[0] : 0;
  const baseX = (index: number) => spec.temporal && span > 0 && mode === 'line' ? left + 16 + (stamps[index] - stamps[0]) / span * Math.max(1, right - left - 32) : left + (index + 0.5) * (right - left) / Math.max(1, rows.length);
  const tick = (label: string) => spec.temporal ? displayDate(label, grouping === 'month') : label;
  const valueText = (row: Point, series: number) => `${spec.series[series].label}: ${spec.hours ? duration(row.values[series]) : complaintCount(row.values[series]!)}${spec.hours && row.count !== undefined ? `; ${row.count} complaints` : ''}`;
  const choose = (index: number, series: number) => { setSelected(''); select(spec.select(index, series)); };
  const options = spec.rows.flatMap((row, index) => row.values.flatMap((value, series) => value === null ? [] : [{ value: `${index}:${series}`, label: `${tick(row.label)} - ${valueText(row, series)}` }]));
  return <Box xcss={styles.panel} role="region" aria-label={`${spec.title} chart`}><Stack space="space.150"><Inline spread="space-between" alignBlock="center" space="space.100"><Heading as="h3" size="small">{spec.title}</Heading>{spec.temporal && rows.length > 1 && <Inline space="space.050"><IconButton label="Bar chart" appearance="subtle" icon={BarChartIcon} isSelected={mode === 'bar'} onClick={() => setChosenMode('bar')}/><IconButton label="Line chart" appearance="subtle" icon={LineChartIcon} isSelected={mode === 'line'} onClick={() => setChosenMode('line')}/></Inline>}{((spec.id==='category'&&spec.rows.length<=8)||spec.id==='targets')&&<Inline space="space.050"><IconButton label="Bar chart" icon={BarChartIcon} appearance="subtle" isSelected={!radial} onClick={()=>setChosenMode('bar')}/><IconButton label="Doughnut chart" icon={PieChartIcon} appearance="subtle" isSelected={mode==='doughnut'} onClick={()=>setChosenMode('doughnut')}/>{spec.id==='category'&&<IconButton label="Pie chart" icon={PieChartIcon} appearance="subtle" isSelected={mode==='pie'} onClick={()=>setChosenMode('pie')}/>}</Inline>}<IconButton label={`About ${spec.title}`} icon={InfoIcon} appearance="subtle" onClick={()=>setHelpOpen(true)}/></Inline>{helpOpen&&<TaskDialog title={spec.title} compact close={()=>setHelpOpen(false)}><Text>{spec.help}</Text></TaskDialog>}
    {spec.id === 'category' && rows.length === 1 ? <Text>{rows[0].label}: {rows[0].values[0]} complaints</Text> : !hasData ? <Text>{spec.hours ? 'No recorded timing in this period.' : 'No matching complaints.'}</Text> : <Box ref={root} xcss={styles.chart}>
      <Inline shouldWrap space="space.150">{spec.series.map((series, i) => <Inline key={series.label} alignBlock="center" space="space.050"><svg width="14" height="14" aria-hidden="true">{mode === 'line' && !i ? <circle cx="7" cy="7" r="5" fill={series.color} /> : <rect x="2" y="2" width="10" height="10" fill={series.color} />}</svg><Text size="small">{series.label}{spec.series.length > 1 && mode === 'line' ? ` (${i ? 'dashed' : 'solid'})` : ''}</Text></Inline>)}</Inline>
      {radial ? <RadialChart spec={spec} doughnut={mode==='doughnut'} select={choose}/> : <svg viewBox={`0 0 ${width} ${height}`} width={width} role="group" aria-label={`${spec.title}. ${spec.hours ? 'Hours' : 'Complaints'}.`}>
        {[0, 0.5, 1].map(ratio => <g key={ratio}><line x1={spec.horizontal ? left + ratio * (right - left) : left} x2={spec.horizontal ? left + ratio * (right - left) : right} y1={spec.horizontal ? top : bottom - ratio * (bottom - top)} y2={spec.horizontal ? bottom : bottom - ratio * (bottom - top)} stroke={token('color.border')} /><text x={spec.horizontal ? left + ratio * (right - left) : left - 8} y={spec.horizontal ? bottom + 20 : bottom - ratio * (bottom - top) + 4} textAnchor={spec.horizontal ? 'middle' : 'end'} fill={token('color.text.subtle')}>{Number((ratio * maximum).toFixed(spec.hours ? 1 : 0))}</text></g>)}
        <line x1={left} x2={left} y1={top} y2={bottom} stroke={token('color.border.bold')} /><line x1={left} x2={right} y1={bottom} y2={bottom} stroke={token('color.border.bold')} />
        <text x={left} y={16} fill={token('color.text.subtle')}>{spec.hours ? 'Hours' : 'Complaints'}</text>
        {mode === 'line' && !spec.horizontal && spec.series.map((series, s) => <polyline key={series.label} points={rows.flatMap((row, i) => row.values[s] === null ? [] : [`${baseX(i)},${bottom - (row.values[s]! / maximum) * (bottom - top)}`]).join(' ')} fill="none" stroke={series.color} strokeWidth={2} strokeDasharray={s ? '6 4' : undefined} />)}
        {rows.map((row, i) => <g key={`${row.label}-${i}`}>
          {row.values.map((value, s) => {
            if (value === null) return null;
            const x = baseX(i) + (mode === 'bar' ? (s - (spec.series.length - 1) / 2) * Math.min(38, (right - left) / rows.length / spec.series.length) : 0);
            const y = bottom - value / maximum * (bottom - top), band = Math.min(36, (right - left) / Math.max(1, rows.length) / spec.series.length * 0.65);
            const key = `${i}:${s}`, label = `${tick(row.label)}: ${valueText(row, s)}`;
            return <g key={s} role="button" tabIndex={0} aria-label={`${label}. Filter results.`} onMouseEnter={() => setHover(key)} onMouseLeave={() => setHover('')} onFocus={() => setHover(key)} onBlur={() => setHover('')} onClick={() => choose(i, s)} onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); choose(i, s); } }}>
              <title>{label}</title>{spec.horizontal ? <rect x={left} y={top + i * 40 + 8} width={Math.max(2, value / maximum * (right - left))} height={20} fill={spec.series[s].color} opacity={hover && hover !== key ? token('opacity.disabled') : 1} /> : mode === 'line' ? (s ? <rect x={x - 5} y={y - 5} width={10} height={10} fill={spec.series[s].color} /> : <circle cx={x} cy={y} r={5} fill={spec.series[s].color} />) : <rect x={x - band / 2} y={y} width={band} height={Math.max(2, bottom - y)} fill={spec.series[s].color} opacity={hover && hover !== key ? token('opacity.disabled') : 1} />}
              {value > 0 && <text x={spec.horizontal ? left + value / maximum * (right-left) + (value/maximum*(right-left)>String(value).length*8+12 ? -6 : 6) : x} y={spec.horizontal ? top+i*40+22 : mode==='bar'&&bottom-y>=24&&band>=String(value).length*7 ? y+16 : y-8-(mode==='line'&&s>0&&Math.abs((row.values[0]||0)-value)/maximum*(bottom-top)<18?16:0)} textAnchor={spec.horizontal ? (value/maximum*(right-left)>String(value).length*8+12?'end':'start'):'middle'} fill={(spec.horizontal&&value/maximum*(right-left)>String(value).length*8+12)||(mode==='bar'&&!spec.horizontal&&bottom-y>=24&&band>=String(value).length*7)?token('color.text.inverse'):token('color.text')}>{Number(value.toFixed(2))}</text>}
            </g>;
          })}
          {spec.horizontal ? <text x={left - 8} y={top + i * 40 + 22} textAnchor="end" fill={token('color.text')}><title>{row.label}</title>{row.label.length > Math.floor(left / 7) ? `${row.label.slice(0, Math.max(4, Math.floor(left / 7) - 2))}...` : row.label}</text> : (i === 0 || i === rows.length - 1 || i % Math.max(1, Math.ceil(rows.length / Math.max(2, Math.floor(width / 105)))) === 0) && <text x={baseX(i)} y={bottom + 20} transform={rows.length>5?`rotate(-40 ${baseX(i)} ${bottom+20})`:undefined} textAnchor={rows.length>5?'end':'middle'} fill={token('color.text.subtle')}>{tick(row.label)}</text>}
        </g>)}
      </svg>}

    </Box>}
    {spec.note && <Text size="small" color="color.text.subtle">{spec.note}</Text>}
    {spec.horizontal && spec.rows.length > 10 && <Text size="small">Showing the first 10. Use Select cases for all complaint types.</Text>}
    {spec.horizontal && spec.rows.length > 10 && <Box><Label htmlFor={`${spec.id}-cases`}>Find a complaint type</Label><Select inputId={`${spec.id}-cases`} value={options.find(option => option.value === selected) || null} options={options} onChange={option => { if(option){const [index, series]=option.value.split(':').map(Number);choose(index,series);} }}/></Box>}
  </Stack></Box>;
}
/* eslint-enable @atlaskit/design-system/no-html-button */
