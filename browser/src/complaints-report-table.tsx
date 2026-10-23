/* eslint-disable @atlaskit/design-system/no-placeholder -- Spec #18: search placeholder plus accessible name, no redundant label row. */
import React, { useEffect, useRef } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { AllCommunityModule, ModuleRegistry, createGrid, themeQuartz, type ColDef, type GridApi } from 'ag-grid-community';
import { Box } from '@atlaskit/primitives/compiled/box';
import { cssMap } from '@atlaskit/css';
import { token } from '@atlaskit/tokens';
import { ComplaintStatus, displayDate } from './complaints-ui';
import { TaskDialog } from './complaints-ui';
import Button from '@atlaskit/button/default/button';
import { AdaptiveSelect as Select, DialogFooter } from './complaints-ui';
import { Label } from '@atlaskit/form';
import { Inline } from '@atlaskit/primitives/compiled/inline';
import { Text } from '@atlaskit/primitives/compiled/text';
import { Stack } from '@atlaskit/primitives/compiled/stack';
import { notify } from './browser-interactions';
import Textfield from '@atlaskit/textfield';
import { ControlRow } from './complaints-ui';
import { duration } from './complaints-report-charts';
import SearchIcon from '@atlaskit/icon/core/search';
import { useState } from 'react';

ModuleRegistry.registerModules([AllCommunityModule]);
export type ReportRow = { complaint_id: string; customer_name: string; complaint_category: string; branch_region: string; status: string; date_reported: string; days_open: number | null; key?: string; [field:string]:string|number|null|undefined };
const registerColumns: [string,string][] = [['row_number','#'],['complaint_id','Reference'],['customer_name','Customer'],['customer_id','National ID'],['phone_number','Primary phone'],['branch_region','Branch'],['complaint_category','Complaint type'],['date_reported','Reported'],['status','Status'],['days_open','Age (days)'],['secondary_phone_number','Alternative phone'],['county','County'],['constituency','Constituency'],['village','Village/Nearest Landmark'],['reported_by','Reported by'],['complaint_description','Complaint description'],['gps_link','Map pin'],['resolution_details','Resolution details'],['resolution_comments','Resolution comments'],['date_resolved','Resolved'],['resolution_hours','Time to resolve'],['hb_response_hours','First response'],['resolution_history_count','Resolution history'],['target_outcome','Target'],['target_hours','Target (hours)']];
const defaultColumns = ['complaint_id','customer_name','status','branch_region','complaint_category','date_reported','date_resolved','resolution_hours','target_outcome'];
const sortable = new Set(['complaint_id','customer_name','branch_region','complaint_category','date_reported','days_open','status','date_resolved']);
const styles = cssMap({ grid: { display:'none', minWidth: 0, width: '100%', overflowX: 'auto', '@media (min-width: 48rem)':{display:'block'} },mobile:{'@media (min-width: 48rem)':{display:'none'}},row:{paddingBlock:token('space.200'),borderBlockEnd:`${token('border.width')} solid ${token('color.border')}`} });
export function ReportTable({ rows, open, sort, setSort, offset=0, search, setSearch }: { rows: ReportRow[]; open: (key: string) => void; sort: string; setSort: (sort: string) => void; offset?:number;search:string;setSearch:(value:string)=>void }) {
  const root = useRef<HTMLDivElement>(null), api = useRef<GridApi<ReportRow>>();
  const [columnsOpen,setColumnsOpen]=useState(false),[visible,setVisible]=useState(defaultColumns);
  const rowOffset=useRef(offset);rowOffset.current=offset;
  const callbacks = useRef({ open, setSort, sort }); callbacks.current = { open, setSort, sort };
  useEffect(() => {
    const renderers = new Set<Root>();
    class StatusCell {
      private element = document.createElement('span');
      private reactRoot = createRoot(this.element);
      init(params: { value: string }) { renderers.add(this.reactRoot); this.reactRoot.render(<ComplaintStatus status={params.value} />); }
      getGui() { return this.element; }
      destroy() { const row = this.reactRoot; renderers.delete(row); queueMicrotask(() => row.unmount()); }
    }
    const columns: ColDef<ReportRow>[] = registerColumns.map(([field,headerName])=>({field,headerName,colId:field,hide:!defaultColumns.includes(field),sortable:sortable.has(field),minWidth:field==='row_number'?60:field==='complaint_id'?120:field==='customer_name'?200:field==='status'?110:160,width:field==='status'?110:field==='complaint_id'?120:field==='branch_region'?210:160,tooltipField:field,...(['customer_name','complaint_category'].includes(field)?{flex:1}:{}),
      ...(field==='row_number'?{pinned:'left',flex:0,width:60,valueGetter:(params)=>rowOffset.current+(params.node?.rowIndex||0)+1}:{}),
      ...(field==='status'?{cellRenderer:StatusCell}:{}),
      ...(field==='complaint_id'?{pinned:'left',flex:0}:{}),
      ...(['complaint_description','resolution_details','resolution_comments'].includes(field)?{wrapText:true,autoHeight:true}:{}),
      ...(['resolution_hours','hb_response_hours'].includes(field)?{valueFormatter:params=>duration(typeof params.value==='number'?params.value:null)}:{}),
      ...(field==='target_outcome'?{valueFormatter:params=>({on_time:'On time',late:'Late',no_target:'No target set',not_recorded:'Time not recorded',not_resolved:'Not resolved'}[String(params.value)]||'Not recorded')} : {}),
      ...(field==='date_reported'||field==='date_resolved'?{valueFormatter:(params)=>params.value?displayDate(params.value):'—'}:{}),
      ...(['phone_number','secondary_phone_number','gps_link','customer_id'].includes(field)?{cellRenderer:(params:{value:string})=>{if(!params.value)return '—';const link=document.createElement('a');link.textContent=params.value;link.href=field==='gps_link'?params.value:field==='customer_id'?'#':`tel:${params.value.replace(/[\s()-]/g,'')}`;if(field==='gps_link'){link.target='_blank';link.rel='noopener noreferrer';}if(field==='customer_id')link.onclick=event=>{event.preventDefault();void navigator.clipboard.writeText(params.value).then(()=>notify('National ID copied.')).catch(()=>notify('Copy was unavailable. Select the value and copy it.','warning'));};return link;}}:{}),
    }));
    api.current = createGrid(root.current!, { columnDefs: columns, rowData: rows,
      theme: themeQuartz.withParams({ backgroundColor: token('elevation.surface'), foregroundColor: token('color.text'), headerBackgroundColor: token('elevation.surface.sunken'), borderColor: token('color.border'), accentColor: token('color.border.focused'), fontFamily: token('font.family.body'), fontSize: '0.875rem', rowHeight: '3rem', headerHeight: '2.75rem' }),
      domLayout: 'autoHeight', enableBrowserTooltips:true, animateRows: false, ensureDomOrder: true,
      defaultColDef: { sortable: false, resizable: true, wrapText:false, autoHeight:false, sortingOrder: ['asc', 'desc'] },
      getRowId: params => params.data.complaint_id, suppressCellFocus: false,
      getRowStyle:params=>params.data?.key?{cursor:'pointer'}:undefined,
      onRowClicked: event => { if ((event.event?.target as HTMLElement)?.closest('a,button'))return;if (event.data?.key) callbacks.current.open(event.data.key); },
      onCellKeyDown: event => { const key = event.event as KeyboardEvent; if((key.target as HTMLElement)?.closest('a,button'))return;if (key.key === 'Enter' && event.data?.key) callbacks.current.open(event.data.key); },
      onSortChanged: event => { const column = event.api.getColumnState().find(item => item.sort); if (column) { const next=(column.sort === 'desc' ? '-' : '') + column.colId; if(next!==callbacks.current.sort) callbacks.current.setSort(next); } },
      overlayNoRowsTemplate: '<span>No complaints match these filters.</span>',
    });
    api.current.applyColumnState({ state: [{ colId: sort.replace(/^-/, ''), sort: sort.startsWith('-') ? 'desc' : 'asc' }], defaultState: { sort: null } });
    api.current.setGridAriaProperty('label', 'Complaint results');
    const grid=root.current!,header=grid.querySelector<HTMLElement>('.ag-header');
    const sticky=()=>{if(!header)return;const bounds=grid.getBoundingClientRect(),top=grid.closest('[role="main"]')?.getBoundingClientRect().top||0;header.style.transform=`translateY(${Math.min(Math.max(0,top-bounds.top),Math.max(0,bounds.height-header.offsetHeight))}px)`;header.style.zIndex='2';};
    window.addEventListener('scroll',sticky,true);window.addEventListener('resize',sticky);sticky();
    return () => {window.removeEventListener('scroll',sticky,true);window.removeEventListener('resize',sticky);api.current?.destroy(); api.current = undefined; };
    // AG Grid owns its DOM; data updates below do not recreate focused controls.
  }, []);
  useEffect(() => { api.current?.setGridOption('rowData', rows); }, [rows]);
  useEffect(()=>{api.current?.applyColumnState({state:registerColumns.map(([colId])=>({colId,hide:!visible.includes(colId)}))});},[visible]);
  useEffect(()=>{api.current?.refreshCells({force:true});},[offset]);
  useEffect(()=>{api.current?.applyColumnState({state:[{colId:sort.replace(/^-/,''),sort:sort.startsWith('-')?'desc':'asc'}],defaultState:{sort:null}});},[sort]);
  return <Stack space="space.100"><ControlRow><Textfield aria-label="Search report table" type="search" placeholder="Search table…" elemBeforeInput={<SearchIcon label=""/>} value={search} onChange={event=>setSearch(event.currentTarget.value)}/><Button onClick={()=>setColumnsOpen(true)}>Columns</Button></ControlRow><Box xcss={styles.mobile}><Stack space="space.100"><Box><Label htmlFor="report-mobile-sort">Sort complaints</Label><Select inputId="report-mobile-sort" options={registerColumns.filter(([field])=>sortable.has(field)).flatMap(([field,label])=>[{value:field,label:label+' · ascending'},{value:'-'+field,label:label+' · descending'}])} value={{value:sort,label:(registerColumns.find(([field])=>field===sort.replace(/^-/,'') )?.[1]||'Reported')+' · '+(sort.startsWith('-')?'descending':'ascending')}} onChange={option=>{if(option)setSort(option.value);}}/></Box><Box role="list" aria-label="Complaint results">{!rows.length&&<Text>No complaints match these filters.</Text>}{rows.map((row,index)=><Box key={row.complaint_id} role="listitem" xcss={styles.row}><Stack space="space.100"><Inline spread="space-between" alignBlock="center" space="space.100"><Button appearance="subtle" onClick={()=>{if(row.key)open(row.key);}} aria-label={'Open '+row.complaint_id}>{row.complaint_id}</Button>{visible.includes('status')&&<ComplaintStatus status={row.status}/>}</Inline>{visible.includes('customer_name')&&<Text weight="semibold">{row.customer_name}</Text>}<Text size="small">{[visible.includes('branch_region')?row.branch_region:'',visible.includes('complaint_category')?row.complaint_category:''].filter(Boolean).join(' · ')}</Text>{visible.includes('date_reported')&&<Text size="small" color="color.text.subtle">Reported {displayDate(row.date_reported)}</Text>}{visible.includes('date_resolved')&&row.date_resolved&&<Text size="small">Resolved {displayDate(String(row.date_resolved))}</Text>}{visible.includes('resolution_hours')&&typeof row.resolution_hours==='number'&&<Text size="small">Resolution time: {duration(row.resolution_hours)}</Text>}{visible.includes('target_outcome')&&row.target_outcome&&<Text size="small">Target: {({on_time:'On time',late:'Late',no_target:'No target set',not_recorded:'Time not recorded',not_resolved:'Not resolved'} as Record<string,string>)[String(row.target_outcome)]||'Not recorded'}</Text>}{registerColumns.filter(([field])=>visible.includes(field)&&!defaultColumns.includes(field)).map(([field,label])=><Text size="small" key={field}>{label}: {field==='row_number'?offset+index+1:String(row[field]??'Not recorded')}</Text>)}</Stack></Box>)}</Box></Stack></Box><Box ref={root} xcss={styles.grid}/>{columnsOpen&&<TaskDialog title="Report columns" compact close={()=>setColumnsOpen(false)}><Text size="small">Reference stays visible so each result can be identified.</Text><Box><Label htmlFor="report-columns">Visible columns</Label><Select isMulti inputId="report-columns" options={registerColumns.map(([value,label])=>({value,label}))} value={registerColumns.filter(([field])=>visible.includes(field)).map(([value,label])=>({value,label}))} onChange={items=>setVisible(Array.from(new Set(['complaint_id',...items.map(item=>item.value)])))}/></Box><DialogFooter><Button shouldFitContainer onClick={()=>setVisible(defaultColumns)}>Reset columns</Button><Button shouldFitContainer appearance="primary" onClick={()=>setColumnsOpen(false)}>Done</Button></DialogFooter></TaskDialog>}</Stack>;
}
