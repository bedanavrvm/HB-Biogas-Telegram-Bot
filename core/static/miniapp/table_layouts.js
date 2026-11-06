/* Shared by native Mini Apps and the browser client. Stores column IDs, never row values. */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.MiniAppTableLayouts = api;
}(typeof window === 'undefined' ? null : window, function () {
  'use strict';
  let config = {tables: [], layouts: {}};
  const grids = new Set();
  const discovered = new Map();
  const copy = value => JSON.parse(JSON.stringify(value));
  function configure(tables, layouts) {
    config = {tables: (tables || []).map(table => ({...table,columns:[...table.columns,
      ...(discovered.get(table.key)||[]).filter(column=>!table.columns.some(known=>known.id===column.id))]})), layouts: layouts || {}};
    grids.forEach(grid => grid.refresh());
  }
  function attach(key, api, element) {
    let disposed = false, applying = false, frame = 0;
    const original = api.getColumnState();
    const first = config.tables.find(table => table.key === key)?.numbering || (original.some(c => c.colId === 'row_number') ? 'row_number' : 'source_row');
    const defaults = [first, ...original.map(c => c.colId).filter(id => id !== first)];
    api.setGridOption('processUnpinnedColumns', params => params.columns.filter(column => column.getColId() !== first));
    let defaultFrozen = first;
    for (const id of defaults) { if (original.find(c => c.colId === id)?.pinned !== 'left') break; defaultFrozen = id; }
    const notice = document.createElement('p'); notice.className = 'table-layout-notice'; notice.setAttribute('role', 'status'); notice.hidden = true;
    element.before(notice);
    function refresh() {
      if (disposed || applying || api.isDestroyed?.()) return;
      const width = element.getBoundingClientRect().width;
      if (!width) return;
      const columns = api.getColumns() || [];
      discovered.set(key, columns.map(column=>({id:column.getColId(),label:column.getColDef().headerName||column.getColId()})));
      const ids = columns.map(c => c.getColId());
      const preference = config.layouts[key];
      const order = [first, ...new Set([...(preference?.order || defaults), ...ids].filter(id => id !== first && ids.includes(id)))];
      const frozen = preference?.freeze_through || defaultFrozen;
      const end = Math.max(0, order.indexOf(frozen));
      let used = 0, fits = true, shortened = false;
      const state = order.map((colId, index) => {
        const column = columns.find(c => c.getColId() === colId);
        const visible = colId === first || column?.isVisible();
        const requested = index <= end && visible;
        if (requested && used + column.getActualWidth() > width / 2 && index > 0) fits = false;
        const pinned = requested && (index === 0 || fits) ? 'left' : null;
        if (pinned) used += column.getActualWidth();
        if (requested && !pinned) shortened = true;
        return {colId, pinned, ...(colId === first ? {hide: false} : {})};
      });
      notice.hidden = !shortened;
      notice.textContent = shortened ? 'Frozen columns reduced to fit half the table. Your saved range is retained.' : '';
      const next = JSON.stringify(state);
      const current = api.getColumnState().map(column => ({colId:column.colId,pinned:column.pinned||null,...(column.colId===first?{hide:Boolean(column.hide)}:{})}));
      if (next === JSON.stringify(current)) return;
      applying = true;
      try { api.applyColumnState({state, applyOrder: true}); } finally { applying = false; }
    }
    const schedule = () => { cancelAnimationFrame(frame); frame = requestAnimationFrame(refresh); };
    const observer = new ResizeObserver(schedule); observer.observe(element);
    ['columnResized', 'columnVisible', 'columnPinned', 'newColumnsLoaded'].forEach(event => api.addEventListener(event, schedule));
    const handle = {refresh}; grids.add(handle);
    const dispose = () => {if (disposed) return; disposed = true; cancelAnimationFrame(frame); observer.disconnect(); grids.delete(handle); notice.remove();};
    api.addEventListener('gridPreDestroyed', dispose);
    refresh();
    return {refresh: handle.refresh, dispose};
  }
  function mount(element, {load, save}) {
    if (!element || element.dataset.layoutMounted) return;
    element.dataset.layoutMounted = 'true';
    const node = (tag, text) => {const value = document.createElement(tag); if (text) value.textContent = text; return value;};
    const details = node('details'), heading = node('summary', 'Table Layouts'); details.append(heading);
    const body = node('div'); body.className = 'table-layout-editor';
    const status = node('p', 'Loading table layouts…'); status.setAttribute('role', 'status');
    const picker = node('select'); picker.setAttribute('aria-label', 'Table');
    const list = node('ol'); list.setAttribute('aria-label', 'Column order');
    const freeze = node('select'); freeze.setAttribute('aria-label', 'Freeze through');
    const freezeLabel = node('label', 'Freeze Through '); freezeLabel.append(freeze);
    const actions = node('div'); actions.className = 'table-layout-actions';
    const button = text => {const b = node('button', text); b.type = 'button'; return b;};
    const submit = button('Save Layout'), reset = button('Reset This Table'), reload = button('Reload Saved Layouts');
    actions.append(submit, reset, reload);
    body.append(picker, node('p', 'Numbering stays first. Frozen columns use at most half the table width.'), list, freezeLabel, actions, status);
    details.append(body); element.replaceChildren(details);
    let tables = [], layouts = {}, drafts = {}, busy = false;
    function render(focus) {
      const table = tables.find(item => item.key === picker.value);
      picker.disabled = busy; submit.disabled = reset.disabled = freeze.disabled = busy || !table;
      if (!table) {list.replaceChildren(); return;}
      const ids = table.columns.map(c => c.id), saved = drafts[table.key] || layouts[table.key];
      const order = [table.numbering, ...new Set([...(saved?.order || ids), ...ids].filter(id => id !== table.numbering && ids.includes(id)))];
      const draft = drafts[table.key] = {order, freeze_through: saved?.freeze_through || table.numbering};
      list.replaceChildren(); freeze.replaceChildren();
      order.forEach((id, index) => {
        const label = table.columns.find(c => c.id === id)?.label || id;
        const row = node('li'), name = node('span', label); row.append(name);
        if (index) for (const [text, delta] of [['↑', -1], ['↓', 1]]) {
          const move = button(text); move.setAttribute('aria-label', `Move ${label} ${delta < 0 ? 'up' : 'down'}`);
          move.disabled = busy || index + delta < 1 || index + delta >= order.length;
          move.dataset.column = id; move.dataset.direction = String(delta);
          move.onclick = () => {const next = index + delta; [order[index], order[next]] = [order[next], order[index]]; render({id, delta});}; row.append(move);
        }
        list.append(row); const option = node('option', label); option.value = id; freeze.append(option);
      });
      freeze.value = draft.freeze_through;
      if (!freeze.value) freeze.value = draft.freeze_through = table.numbering;
      if (focus) list.querySelector(`[data-column="${CSS.escape(focus.id)}"][data-direction="${focus.delta}"]`)?.focus();
    }
    async function refresh() {
      reload.disabled = true;
      try {
        const data = await load(); tables = data.table_catalogue || []; layouts = data.personal?.table_layouts || data.table_layouts || {};
        if (!element.isConnected) return;
        configure(tables, layouts); tables = config.tables; picker.replaceChildren();
        for (const table of tables) {const option = node('option', table.label); option.value = table.key; picker.append(option);}
        status.textContent = tables.length ? 'Saved to your account for this app.' : 'No AG Grid tables are available for your current access.'; render();
      } catch (error) {status.textContent = error.message || 'Layouts could not load. Try again.';} finally {reload.disabled = false;}
    }
    picker.onchange = () => render(); freeze.onchange = () => {drafts[picker.value].freeze_through = freeze.value;};
    reload.onclick = () => refresh();
    async function persist(isReset) {
      if (busy || !picker.value) return;
      const key = picker.value, next = {...layouts};
      if (isReset) delete next[key]; else next[key] = copy(drafts[key]);
      busy = true; render(); status.textContent = 'Saving layout…';
      try {
        const data = await save({preferences: {table_layouts: next}, expected_table_layouts: layouts});
        layouts = data.table_layouts || {}; delete drafts[key]; if(element.isConnected)configure(tables, layouts);
        status.textContent = isReset ? 'Default layout restored.' : 'Layout saved.';
      } catch (error) {status.textContent = error.message || 'Layout could not save. Your edits are retained.';}
      finally {busy = false; render();}
    }
    submit.onclick = () => persist(false); reset.onclick = () => persist(true); void refresh();
  }
  return {configure, attach, mount};
}));
