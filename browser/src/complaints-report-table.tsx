import React, { useEffect, useRef } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { AllCommunityModule, ModuleRegistry, createGrid, themeQuartz, type ColDef, type GridApi } from 'ag-grid-community';
import { Box } from '@atlaskit/primitives/compiled/box';
import { cssMap } from '@atlaskit/css';
import { token } from '@atlaskit/tokens';
import { ComplaintStatus, displayDate } from './complaints-ui';

ModuleRegistry.registerModules([AllCommunityModule]);
export type ReportRow = { complaint_id: string; customer_name: string; complaint_category: string; branch_region: string; status: string; date_reported: string; days_open: number | null; key?: string };
const styles = cssMap({ grid: { minWidth: 0, width: '100%' } });
export function ReportTable({ rows, open, sort, setSort }: { rows: ReportRow[]; open: (key: string) => void; sort: string; setSort: (sort: string) => void }) {
  const root = useRef<HTMLDivElement>(null), api = useRef<GridApi<ReportRow>>();
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
    const columns: ColDef<ReportRow>[] = [
      { field: 'complaint_id', headerName: 'Reference', minWidth: 115 },
      { field: 'customer_name', headerName: 'Customer', minWidth: 190, flex: 2 },
      { field: 'branch_region', headerName: 'Branch', minWidth: 150 },
      { field: 'complaint_category', headerName: 'Type', minWidth: 170 },
      { field: 'date_reported', headerName: 'Reported', minWidth: 145, valueFormatter: params => displayDate(params.value) },
      { field: 'days_open', headerName: 'Age (days)', minWidth: 115, valueFormatter: params => params.value === null || params.value === undefined ? '—' : String(params.value) },
      { field: 'status', headerName: 'Status', minWidth: 130, cellRenderer: StatusCell },
    ];
    api.current = createGrid(root.current!, { columnDefs: columns, rowData: rows,
      theme: themeQuartz.withParams({ backgroundColor: token('elevation.surface'), foregroundColor: token('color.text'), headerBackgroundColor: token('elevation.surface.sunken'), borderColor: token('color.border'), accentColor: token('color.border.focused'), fontFamily: token('font.family.body'), fontSize: 14, rowHeight: 48, headerHeight: 44 }),
      domLayout: 'autoHeight', animateRows: false, ensureDomOrder: true, suppressColumnVirtualisation: true,
      defaultColDef: { sortable: true, resizable: true, flex: 1, sortingOrder: ['asc', 'desc'] },
      getRowId: params => params.data.complaint_id, suppressCellFocus: false,
      onRowClicked: event => { if (event.data?.key) callbacks.current.open(event.data.key); },
      onCellKeyDown: event => { const key = event.event as KeyboardEvent; if (key.key === 'Enter' && event.data?.key) callbacks.current.open(event.data.key); },
      onSortChanged: event => { const column = event.api.getColumnState().find(item => item.sort); if (column) { const next=(column.sort === 'desc' ? '-' : '') + column.colId; if(next!==callbacks.current.sort) callbacks.current.setSort(next); } },
      overlayNoRowsTemplate: '<span>No complaints match these filters.</span>',
    });
    api.current.applyColumnState({ state: [{ colId: sort.replace(/^-/, ''), sort: sort.startsWith('-') ? 'desc' : 'asc' }], defaultState: { sort: null } });
    api.current.setGridAriaProperty('label', 'Complaint results');
    return () => { api.current?.destroy(); api.current = undefined; };
    // AG Grid owns its DOM; data updates below do not recreate focused controls.
  }, []);
  useEffect(() => { api.current?.setGridOption('rowData', rows); }, [rows]);
  return <Box ref={root} xcss={styles.grid} />;
}
