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
import { Stack } from '@atlaskit/primitives/compiled/stack';
import { notify } from './browser-interactions';
import { useState } from 'react';

ModuleRegistry.registerModules([AllCommunityModule]);
export type ReportRow = { complaint_id: string; customer_name: string; complaint_category: string; branch_region: string; status: string; date_reported: string; days_open: number | null; key?: string; [field:string]:string|number|null|undefined };
const registerColumns: [string,string][] = [['row_number','#'],['complaint_id','Reference'],['customer_name','Customer'],['customer_id','National ID'],['phone_number','Primary phone'],['branch_region','Branch'],['complaint_category','Complaint type'],['date_reported','Reported'],['status','Status'],['days_open','Age (days)'],['secondary_phone_number','Alternative phone'],['county','County'],['constituency','Constituency'],['village','Village/Nearest Landmark'],['reported_by','Reported by'],['complaint_description','Complaint description'],['gps_link','Map pin'],['resolution_details','Resolution details'],['resolution_comments','Resolution comments'],['date_resolved','Resolved'],['resolution_hours','Resolution time (hours)'],['hb_response_hours','Home Based response (hours)'],['resolution_history_count','Resolution history']];
const defaultColumns = registerColumns.slice(0,10).map(([field])=>field);
const sortable = new Set(['complaint_id','customer_name','branch_region','complaint_category','date_reported','days_open','status','date_resolved']);
const styles = cssMap({ grid: { minWidth: 0, width: '100%', height: '45vh', minHeight: '18rem', maxHeight: '36rem' } });
export function ReportTable({ rows, open, sort, setSort, offset=0 }: { rows: ReportRow[]; open: (key: string) => void; sort: string; setSort: (sort: string) => void; offset?:number }) {
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
    const columns: ColDef<ReportRow>[] = registerColumns.map(([field,headerName])=>({field,headerName,colId:field,hide:!defaultColumns.includes(field),sortable:sortable.has(field),minWidth:field==='row_number'?60:field==='customer_name'?180:140,
      ...(field==='row_number'?{pinned:'left',flex:0,width:60,valueGetter:(params)=>rowOffset.current+(params.node?.rowIndex||0)+1}:{}),
      ...(field==='status'?{cellRenderer:StatusCell}:{}),
      ...(field==='date_reported'||field==='date_resolved'?{valueFormatter:(params)=>params.value?displayDate(params.value):'—'}:{}),
      ...(['phone_number','secondary_phone_number','gps_link','customer_id'].includes(field)?{cellRenderer:(params:{value:string})=>{if(!params.value)return '—';const link=document.createElement('a');link.textContent=params.value;link.href=field==='gps_link'?params.value:field==='customer_id'?'#':`tel:${params.value.replace(/[\s()-]/g,'')}`;if(field==='gps_link'){link.target='_blank';link.rel='noopener noreferrer';}if(field==='customer_id')link.onclick=event=>{event.preventDefault();void navigator.clipboard.writeText(params.value).then(()=>notify('National ID copied.')).catch(()=>notify('Copy was unavailable. Select the value and copy it.','warning'));};return link;}}:{}),
    }));
    api.current = createGrid(root.current!, { columnDefs: columns, rowData: rows,
      theme: themeQuartz.withParams({ backgroundColor: token('elevation.surface'), foregroundColor: token('color.text'), headerBackgroundColor: token('elevation.surface.sunken'), borderColor: token('color.border'), accentColor: token('color.border.focused'), fontFamily: token('font.family.body'), fontSize: 14, rowHeight: 48, headerHeight: 44 }),
      domLayout: 'normal', animateRows: false, ensureDomOrder: true,
      defaultColDef: { sortable: true, resizable: true, flex: 1, sortingOrder: ['asc', 'desc'] },
      getRowId: params => params.data.complaint_id, suppressCellFocus: false,
      onRowClicked: event => { if ((event.event?.target as HTMLElement)?.closest('a,button'))return;if (event.data?.key) callbacks.current.open(event.data.key); },
      onCellKeyDown: event => { const key = event.event as KeyboardEvent; if((key.target as HTMLElement)?.closest('a,button'))return;if (key.key === 'Enter' && event.data?.key) callbacks.current.open(event.data.key); },
      onSortChanged: event => { const column = event.api.getColumnState().find(item => item.sort); if (column) { const next=(column.sort === 'desc' ? '-' : '') + column.colId; if(next!==callbacks.current.sort) callbacks.current.setSort(next); } },
      overlayNoRowsTemplate: '<span>No complaints match these filters.</span>',
    });
    api.current.applyColumnState({ state: [{ colId: sort.replace(/^-/, ''), sort: sort.startsWith('-') ? 'desc' : 'asc' }], defaultState: { sort: null } });
    api.current.setGridAriaProperty('label', 'Complaint results');
    return () => { api.current?.destroy(); api.current = undefined; };
    // AG Grid owns its DOM; data updates below do not recreate focused controls.
  }, []);
  useEffect(() => { api.current?.setGridOption('rowData', rows); }, [rows]);
  useEffect(()=>{api.current?.applyColumnState({state:registerColumns.map(([colId])=>({colId,hide:!visible.includes(colId)}))});},[visible]);
  useEffect(()=>{api.current?.refreshCells({force:true});},[offset]);
  return <Stack space="space.100"><Box><Button onClick={()=>setColumnsOpen(true)}>Columns</Button></Box><Box ref={root} xcss={styles.grid}/>{columnsOpen&&<TaskDialog title="Report columns" compact close={()=>setColumnsOpen(false)}><Box><Label htmlFor="report-columns">Visible columns</Label><Select isMulti inputId="report-columns" options={registerColumns.map(([value,label])=>({value,label}))} value={registerColumns.filter(([field])=>visible.includes(field)).map(([value,label])=>({value,label}))} onChange={items=>setVisible(items.map(item=>item.value))}/></Box><DialogFooter><Button shouldFitContainer onClick={()=>setVisible(defaultColumns)}>Reset columns</Button><Button shouldFitContainer appearance="primary" onClick={()=>setColumnsOpen(false)}>Done</Button></DialogFooter></TaskDialog>}</Stack>;
}
