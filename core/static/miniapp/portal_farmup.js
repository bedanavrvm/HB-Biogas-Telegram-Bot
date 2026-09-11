(() => {
  'use strict';

  const api = window.PortalMiniAppApi || {};
  const utils = window.MiniAppUtils || {};
  const tg = window.Telegram?.WebApp;
  const editableFields = ['Customer Name', 'National ID', 'Primary Phone', 'Secondary Phone', 'Application Action', 'Additional Unit Reason', 'County', 'HBG Visit Date', 'Deposit Paid to HB', 'HB Sales Person'];
  const requiredFields = ['Customer Name', 'National ID', 'Primary Phone', 'Secondary Phone', 'County', 'HBG Visit Date', 'Deposit Paid to HB', 'HB Sales Person'];
  let batches = [], active = null, gridApi = null, gridAssetPromise = null;
  let search = '', needsReviewOnly = false, mappingOpen = false, commitRequestKey = '';

  function node(id) { return document.getElementById(id); }
  function activeScreen() { return node('portal-screen')?.dataset.screen === 'farmup'; }
  function can(key) { return window.PortalAppShell?.hasCapability?.(key) !== false; }
  function escapeHtml(value) { return String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
  function requestId(prefix) { return utils.createRequestId?.(prefix) || `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`; }
  function setLoading(button, loading, label = 'Working') {
    if (utils.setButtonLoading) return utils.setButtonLoading(button, loading, label);
    if (!button) return;
    if (loading) { button.dataset.label = button.textContent; button.disabled = true; button.textContent = label; }
    else { button.disabled = false; button.textContent = button.dataset.label || button.textContent; }
  }
  function feedback(message, tone = 'info') {
    const target = node('portal-farmup-feedback'); if (!target) return;
    target.className = `portal-import-feedback ${tone}`; target.textContent = message;
  }
  function isBlank(value) { return !String(value ?? '').trim(); }
  function localIssues(row) {
    const issues = [];
    requiredFields.forEach(field => { if (isBlank(row[field])) issues.push({severity:'blocker', message:`${field} is required`}); });
    if (!['update_existing', 'create_additional_unit'].includes(row['Application Action'] || 'update_existing')) issues.push({severity:'blocker', message:'Choose a valid application action'});
    if (row['Application Action'] === 'create_additional_unit' && isBlank(row['Additional Unit Reason'])) issues.push({severity:'blocker', message:'Additional Unit Reason is required'});
    const nationalId = String(row['National ID'] || '').trim();
    if (nationalId && !/^\d+$/.test(nationalId)) issues.push({severity:'blocker', message:'National ID must contain digits only'});
    else if (nationalId && !/^\d{7,9}$/.test(nationalId)) issues.push({severity:'warning', message:'National ID is outside the usual 7-9 digit range'});
    return issues;
  }
  function applyIssues(row, issues) {
    row._issues = Array.isArray(issues) ? issues : localIssues(row);
    const blocker = row._issues.some(item => item.severity === 'blocker');
    const warning = row._issues.some(item => item.severity === 'warning');
    row._state = blocker ? 'needs_correction' : (warning ? 'warning' : 'ready');
    if (blocker || (warning && !row.warning_acknowledged)) row.approved = false;
  }
  function prepareRows() {
    (active?.rows || []).forEach(row => {
      row.warning_acknowledged = Boolean(row.warning_acknowledged);
      const validation = (active.validation || []).find(item => String(item.row_id) === String(row.row_id));
      row.disposition = validation?.disposition || row.disposition || (row.approved ? 'commit_now' : 'hold');
      row.approved = row.disposition === 'commit_now';
      row.update_acknowledged = Boolean(validation?.update_acknowledged ?? row.update_acknowledged);
      row._match = validation?.match || row._match || {kind:'unknown', changed_fields:[]};
      applyIssues(row, validation?.issues || localIssues(row));
    });
  }
  function rowSelectable(row) { if (['unchanged','identity_conflict'].includes(row?._match?.kind)) return false; if (!['commit_now','hold'].includes(row?.disposition)) return false; return row?._state === 'ready' || (row?._state === 'warning' && row.warning_acknowledged); }
  function reviewCounts() {
    const rows = active?.rows || [], visibleIds = new Set();
    gridApi?.forEachNodeAfterFilter(n => visibleIds.add(String(n.data.row_id)));
    const filterActive = Boolean(search.trim() || needsReviewOnly);
    return {
      selected: rows.filter(r => r.approved && rowSelectable(r)).length,
      creates: rows.filter(r => r.approved && ['new','additional_unit'].includes(r._match?.kind)).length,
      updates: rows.filter(r => r.approved && r._match?.kind === 'update').length,
      unchanged: rows.filter(r => r._match?.kind === 'unchanged' || r.disposition === 'already_committed').length,
      warnings: rows.filter(r => r.approved && r._state === 'warning' && r.warning_acknowledged).length,
      held: rows.filter(r => r.disposition === 'hold').length,
      excluded: rows.filter(r => ['exclude','excluded'].includes(r.disposition)).length,
      removed: rows.filter(r => r._source_state === 'removed').length,
      unresolved: rows.filter(r => r._state !== 'ready' && !r.approved).length,
      hidden: rows.filter(r => r.approved && filterActive && !visibleIds.has(String(r.row_id))).length,
      valid: rows.filter(r => rowSelectable(r)).length,
    };
  }
  function updateSummary() {
    const c = reviewCounts(), target = node('farmup-selection-summary');
    if (target) target.innerHTML = `<span class="selected"><strong>${c.selected}</strong> commit now</span><span><strong>${c.creates}</strong> new</span><span><strong>${c.updates}</strong> updates</span><span><strong>${c.unchanged}</strong> already unchanged</span><span><strong>${c.held}</strong> held</span><span><strong>${c.excluded}</strong> excluded</span><span class="warning"><strong>${c.removed}</strong> removed from latest</span><span class="danger"><strong>${c.unresolved}</strong> unresolved</span>${c.hidden ? `<span><strong>${c.hidden}</strong> selected but hidden by filter</span>` : ''}`;
    if (node('farmup-select-all')) node('farmup-select-all').textContent = `Select all eligible (${c.valid})`;
    if (node('farmup-commit')) node('farmup-commit').disabled = !c.selected;
  }
  function loadGridAssets() {
    if (window.agGrid) return Promise.resolve();
    if (gridAssetPromise) return gridAssetPromise;
    const config = window.PORTAL_CONFIG || {};
    (config.farmupAgGridStyles || []).forEach(href => {
      if (document.querySelector(`link[href="${href}"]`)) return;
      const link = document.createElement('link'); link.rel = 'stylesheet'; link.href = href; document.head.append(link);
    });
    gridAssetPromise = new Promise((resolve, reject) => {
      const script = document.createElement('script'); script.src = config.farmupAgGridScript;
      script.onload = resolve; script.onerror = () => reject(new Error('The FarmUp table could not be loaded.')); document.head.append(script);
    });
    return gridAssetPromise;
  }
  function archiveBadge(batch) {
    if (batch.archive_state === 'archived') return '<span class="badge badge-green">Drive archived</span>';
    if (batch.archive_state === 'needs_attention') return '<span class="badge badge-orange">Drive needs attention</span>';
    return '<span class="badge badge-blue">Archive pending</span>';
  }
  function publicationBadge(batch) {
    const status = batch.publication?.status;
    if (status === 'synced') return '<span class="badge badge-green">Sheet synced</span>';
    if (status === 'needs_attention') return '<span class="badge badge-orange">Sheet needs retry</span>';
    if (status === 'pending') return '<span class="badge badge-blue">Sheet sync queued</span>';
    return '';
  }
  function renderBatches() {
    const target = node('portal-farmup-list'); if (!target) return;
    if (!batches.length) { target.innerHTML = '<div class="empty-state"><div class="es-title">No FarmUp batches</div><div class="es-sub">Upload a Farmers CSV to begin a reviewed intake.</div></div>'; return; }
    target.innerHTML = batches.map(batch => `<article class="portal-import-card"><div class="portal-import-card-title"><div><span class="settings-eyebrow">${escapeHtml(batch.period_label || 'FARMUP')} · VERSION ${Number(batch.version_number || 1)}</span><h3>${escapeHtml(batch.source_filename || 'Farmers CSV')}</h3><p>${escapeHtml(batch.created_at || '')}</p></div><div>${batch.is_portal_archived ? '<span class="badge">Worklist archived</span>' : ''}${archiveBadge(batch)}${publicationBadge(batch)}</div></div><div class="portal-import-stats"><span><strong>${Number(batch.total_rows || 0)}</strong> current rows</span><span class="${batch.review_needed ? 'warning' : ''}"><strong>${Number(batch.remaining_count || 0)}</strong> remaining</span><span><strong>${Number(batch.committed_count || 0)}</strong> committed</span></div>${batch.mapping_state === 'needs_mapping' ? '<p class="farmup-mapping-alert">Column mapping needs attention before row review.</p>' : ''}<div class="portal-import-actions"><button class="btn btn-primary farmup-open" data-batch-id="${escapeHtml(batch.id)}">${batch.mapping_state === 'needs_mapping' ? 'Map columns' : (batch.status === 'committed' ? 'View result' : 'Review rows')}</button>${batch.archive_state === 'needs_attention' && can('portal.farmup.stage') ? `<button class="btn btn-secondary farmup-drive-retry" data-batch-id="${escapeHtml(batch.id)}">Retry Drive archive</button>` : ''}${can('portal.farmup.stage') && !batch.is_portal_archived ? `<button class="btn btn-secondary farmup-archive" data-batch-id="${escapeHtml(batch.id)}">Archive worklist</button>` : ''}</div></article>`).join('');
  }
  async function load({silent = false} = {}) {
    if (!activeScreen()) return;
    const target = node('portal-farmup-list');
    if (!silent && target) target.innerHTML = '<div class="empty-state"><div class="spinner-inline"></div><div class="es-sub">Loading FarmUp batches...</div></div>';
    const result = await api.apiFetch('/farmup/', {}, tg);
    if (!activeScreen()) return;
    if (!result.ok || !result.data?.ok) throw new Error(result.data?.error || 'FarmUp batches could not be loaded.');
    const receivedBatches = Array.isArray(result.data.batches) ? result.data.batches : [];
    batches = receivedBatches.filter(batch => batch && typeof batch === 'object');
    batches.forEach(batch => api.schedulePublication?.(batch.publication || {}, tg));
    renderBatches();
    if (node('portal-farmup-upload')) node('portal-farmup-upload').hidden = !can('portal.farmup.stage');
  }
  function statusRenderer(params) {
    const wrap = document.createElement('div'); wrap.className = 'farmup-grid-status';
    const match = params.data._match?.kind;
    const label = params.data.disposition === 'committed' ? 'Committed' : (match === 'unchanged' || params.data.disposition === 'already_committed') ? 'Already committed' : match === 'update' ? 'Will update' : match === 'new' ? 'New' : params.data._state === 'needs_correction' ? 'Needs correction' : (params.data._state === 'warning' ? 'Warning' : 'Ready');
    const badge = document.createElement('span'); badge.className = `farmup-row-state ${params.data._state}`; badge.textContent = label; wrap.append(badge);
    if (params.data._state === 'warning') {
      const button = document.createElement('button'); button.type = 'button'; button.className = 'farmup-acknowledge'; button.textContent = params.data.warning_acknowledged ? 'Acknowledged' : (params.data._match?.kind === 'update' ? 'Acknowledge update' : 'Acknowledge'); button.setAttribute('aria-pressed', String(Boolean(params.data.warning_acknowledged)));
      button.addEventListener('click', event => { event.stopPropagation(); params.data.warning_acknowledged = !params.data.warning_acknowledged; if (params.data._match?.kind === 'update') params.data.update_acknowledged = params.data.warning_acknowledged; if (!params.data.warning_acknowledged) { params.data.approved = false; params.data.disposition = 'hold'; params.node.setSelected(false); } params.api.refreshCells({rowNodes:[params.node], force:true}); updateSummary(); });
      wrap.append(button);
    }
    return wrap;
  }
  function statusTooltip(params) { const changes = params.data?._match?.changed_fields || []; return [(params.data?._issues || []).map(item => item.message).join('; '), changes.length ? `Changes: ${changes.join(', ')}` : ''].filter(Boolean).join('; ') || 'This row is ready to commit.'; }
  function mobileCardRenderer(params) {
    const row = params.data, card = document.createElement('article'); card.className = `farmup-mobile-card ${row._state}`;
    const header = document.createElement('div'); header.className = 'farmup-mobile-card-head';
    const checkbox = document.createElement('input'); checkbox.type = 'checkbox'; checkbox.checked = Boolean(row.approved); checkbox.disabled = !rowSelectable(row); checkbox.setAttribute('aria-label', `Commit source row ${row['Source Row'] || row.row_id}`);
    checkbox.addEventListener('change', () => { row.disposition = checkbox.checked ? 'commit_now' : 'hold'; row.approved = checkbox.checked; params.node.setSelected(checkbox.checked); updateSummary(); });
    const identity = document.createElement('div'); identity.innerHTML = `<strong>${escapeHtml(row['Customer Name'] || 'Unnamed farmer')}</strong><span>Row ${escapeHtml(row['Source Row'] || row.row_id)} · ${escapeHtml(row['National ID'] || 'No ID')}</span>`;
    const badge = document.createElement('b'); badge.textContent = row._match?.kind === 'update' ? 'Will update' : row._match?.kind === 'unchanged' ? 'Already committed' : row._state === 'needs_correction' ? 'Needs correction' : row._match?.kind === 'new' ? 'New' : 'Ready';
    header.append(checkbox, identity, badge); card.append(header);
    const note = document.createElement('p'); note.textContent = statusTooltip({data:row}); card.append(note);
    const details = document.createElement('details'); details.open = Boolean(row._mobileExpanded); const summary = document.createElement('summary'); summary.textContent = 'Review and edit fields'; details.append(summary);
    const fields = document.createElement('div'); fields.className = 'farmup-mobile-fields';
    (active.editable_fields || editableFields).forEach(field => { const label = document.createElement('label'); const title = document.createElement('span'); title.textContent = field; const input = document.createElement('input'); input.value = row[field] || ''; input.disabled = !can('portal.farmup.commit'); input.addEventListener('change', () => { row[field] = input.value; applyIssues(row, localIssues(row)); active.validation = []; if (!rowSelectable(row)) { row.disposition = 'hold'; row.approved = false; checkbox.checked = false; params.node.setSelected(false); } updateSummary(); }); label.append(title, input); fields.append(label); });
    details.append(fields); details.addEventListener('toggle', () => { row._mobileExpanded = details.open; params.api.resetRowHeights(); }); card.append(details); return card;
  }
  function initializeGrid() {
    if (gridApi || !window.agGrid || !node('farmup-grid')) return;
    const mobile = window.matchMedia('(max-width: 700px)').matches;
    window.agGrid.ModuleRegistry.registerModules([window.agGrid.AllCommunityModule]);
    const textColumn = (field, width = 150) => ({field, headerName:field, width, editable:can('portal.farmup.commit'), tooltipValueGetter:p => String(p.value || '')});
    gridApi = window.agGrid.createGrid(node('farmup-grid'), {
      theme:'legacy', rowData:active.rows || [], animateRows:false, ensureDomOrder:true, rowHeight:38, headerHeight:mobile ? 0 : 38, suppressMovableColumns:true, enableBrowserTooltips:true,
      isFullWidthRow:() => mobile, fullWidthCellRenderer:mobileCardRenderer, getRowHeight:p => mobile ? (p.data._mobileExpanded ? 520 : 150) : 38,
      getRowId:p => String(p.data.row_id), rowSelection:'multiple', suppressRowClickSelection:true,
      isExternalFilterPresent:() => needsReviewOnly, doesExternalFilterPass:p => !needsReviewOnly || p.data._state !== 'ready',
      defaultColDef:{sortable:true, resizable:true, suppressHeaderMenuButton:true},
      columnDefs:[
        {headerName:'', colId:'selected', width:48, minWidth:48, maxWidth:48, pinned:'left', sortable:false, resizable:false, checkboxSelection:p => rowSelectable(p.data), cellClass:'farmup-selection-cell'},
        {headerName:'State', colId:'state', width:155, pinned:'left', sortable:false, cellRenderer:statusRenderer, tooltipValueGetter:statusTooltip},
        {field:'Source Row', headerName:'Row', width:72, editable:false}, textColumn('Customer Name',190), textColumn('National ID',130), textColumn('Primary Phone',145), textColumn('Secondary Phone',145),
        {field:'Application Action', headerName:'Application Action', width:190, editable:can('portal.farmup.commit'), cellEditor:'agSelectCellEditor', cellEditorParams:{values:['update_existing','create_additional_unit']}},
        textColumn('Additional Unit Reason',210), textColumn('County',130), textColumn('HBG Visit Date',145), textColumn('Deposit Paid to HB',150), textColumn('HB Sales Person',165),
        {colId:'validation_notes', headerName:'Validation notes', width:300, editable:false, valueGetter:p => (p.data._issues || []).map(i => i.message).join('; '), tooltipValueGetter:statusTooltip},
      ],
      rowClassRules:{'farmup-grid-row-blocked':p => p.data._state === 'needs_correction','farmup-grid-row-warning':p => p.data._state === 'warning','farmup-grid-row-unselected':p => p.data._state === 'ready' && !p.data.approved},
      onGridReady:event => { event.api.forEachNode(n => n.setSelected(Boolean(n.data.approved && rowSelectable(n.data)))); updateSummary(); },
      onSelectionChanged:event => { event.api.forEachNode(n => { if (['exclude','committed','already_committed','excluded'].includes(n.data.disposition)) return; n.data.approved = n.isSelected() && rowSelectable(n.data); n.data.disposition = n.data.approved ? 'commit_now' : 'hold'; }); event.api.redrawRows(); updateSummary(); },
      onCellValueChanged:event => { applyIssues(event.data, localIssues(event.data)); if (!rowSelectable(event.data)) event.node.setSelected(false); active.validation = []; event.api.refreshCells({rowNodes:[event.node], force:true}); event.api.redrawRows({rowNodes:[event.node]}); updateSummary(); },
    });
  }
  function mappingSummary(mapping) { return `${(mapping?.columns || []).filter(i => i.target_field).length} mapped · ${(mapping?.columns || []).filter(i => !i.target_field && i.resolution !== 'unresolved').length} ignored`; }
  function renderMapping() {
    const target = node('farmup-mapping-panel'); if (!target) return;
    const mapping = active.mapping || {}, mustMap = mapping.state === 'needs_mapping'; target.hidden = false;
    if (!mappingOpen && !mustMap) { target.innerHTML = `<div class="farmup-mapping-summary"><div><strong>Column mapping</strong><span>${escapeHtml(mappingSummary(mapping))}. Column order does not matter.</span></div>${can('portal.farmup.stage') && !active.committed_count ? '<button type="button" class="btn btn-secondary" id="farmup-review-mapping">Review column mapping</button>' : ''}</div>`; return; }
    const options = mapping.canonical_fields || [];
    const rows = (mapping.columns || []).map(column => `<div class="farmup-mapping-row" data-source-id="${escapeHtml(column.source_id)}"><div><strong>${column.column_number}. ${escapeHtml(column.source_header || '(blank header)')}</strong><span>${(column.sample_values || []).map(escapeHtml).join(' · ') || 'No sample values'}</span></div><label><span>Maps to</span><select class="farmup-mapping-target"><option value="">Ignore this column</option>${options.map(option => `<option value="${escapeHtml(option.key)}"${option.key === column.target_field ? ' selected' : ''}>${escapeHtml(option.label)}${option.required ? ' *' : ''}</option>`).join('')}</select></label></div>`).join('');
    const missing = (mapping.missing_required_fields || []).map(key => options.find(item => item.key === key)?.label || key);
    target.innerHTML = `<div class="farmup-mapping-heading"><div><strong>${mustMap ? 'Match CSV columns before review' : 'Review column mapping'}</strong><span>Choose a system field or explicitly ignore each source column. The original CSV is never changed.</span></div></div>${missing.length ? `<div class="farmup-mapping-missing"><strong>Not supplied by the current mapping:</strong> ${missing.map(escapeHtml).join(', ')}. You can enter these values row by row after mapping.</div>` : ''}<div class="farmup-mapping-list">${rows}</div><div class="portal-import-actions"><button type="button" class="btn btn-secondary" id="farmup-cancel-mapping"${mustMap ? ' hidden' : ''}>Cancel</button><button type="button" class="btn btn-primary" id="farmup-save-mapping">Apply mapping and parse rows</button></div>`;
  }
  async function renderEditor() {
    const target = node('portal-farmup-review'); if (!target || !active) return;
    if (gridApi) { gridApi.destroy(); gridApi = null; } prepareRows(); target.hidden = false;
    const review = active.mapping?.state === 'needs_mapping' ? '' : `<div class="farmup-toolbar"><input id="farmup-search" type="search" value="${escapeHtml(search)}" placeholder="Search all rows..."><button class="btn btn-secondary ${needsReviewOnly ? 'active' : ''}" id="farmup-review-filter" aria-pressed="${needsReviewOnly}">Needs review</button><button class="btn btn-secondary" id="farmup-select-all">Select all eligible</button><button class="btn btn-secondary" id="farmup-clear-all">Hold all</button><button class="btn btn-secondary" id="farmup-exclude-selected">Exclude selected</button><button class="btn btn-secondary" id="farmup-restore-excluded">Restore exclusions</button></div><div id="farmup-selection-summary" class="farmup-selection-summary" aria-live="polite"></div><div class="farmup-grid-wrap" role="region" aria-label="FarmUp editable review table. Scroll horizontally to reach all fields." tabindex="0"><div id="farmup-grid" class="ag-theme-quartz farmup-grid"></div></div>${can('portal.farmup.commit') && active.status !== 'committed' ? '<div class="farmup-commit-bar"><span>Selected rows commit now. Unselected rows are held safely for later; only Exclude removes a row from active work.</span><button class="btn btn-primary" id="farmup-commit">Review commit</button></div>' : ''}`;
    target.innerHTML = `<div class="portal-import-review-heading"><div><span class="settings-eyebrow">${escapeHtml(active.period_label || 'FARMUP')} · VERSION ${Number(active.version_number || 1)}</span><h2>${escapeHtml(active.source_filename || 'FarmUp')}</h2><p>Correct highlighted cells and explicitly choose what commits now. ${(active.versions || []).length} immutable upload version${(active.versions || []).length === 1 ? '' : 's'} retained.</p></div><button class="btn btn-secondary" id="farmup-close">Close</button></div>${can('portal.farmup.stage') && active.is_current_version ? '<form id="farmup-version-upload" class="farmup-version-upload"><label><span>Updated monthly CSV</span><input type="file" name="file" accept=".csv,text/csv" required></label><button class="btn btn-secondary" type="submit">Upload updated version</button></form>' : ''}<div id="farmup-commit-receipt" class="farmup-commit-receipt" hidden></div><section id="farmup-mapping-panel" class="farmup-mapping-panel"></section>${review}`;
    renderMapping();
    const priorReceipt = node('farmup-commit-receipt');
    if (priorReceipt && active.publication?.status && active.publication.status !== 'not_required') { priorReceipt.hidden = false; priorReceipt.textContent = active.publication.status === 'synced' ? `Master Data Sheet synchronized for ${active.publication.synced || 0} committed change(s).` : active.publication.status === 'needs_attention' ? 'Portal data is saved. Master Data Sheet synchronization needs retry.' : 'Portal data is saved. Master Data Sheet synchronization is queued.'; }
    if (active.mapping?.state !== 'needs_mapping') { try { await loadGridAssets(); if (active && activeScreen()) initializeGrid(); } catch (error) { feedback(error.message, 'error'); } }
  }
  async function openBatch(batchId) {
    const result = await api.apiFetch(`/farmup/${encodeURIComponent(batchId)}/`, {}, tg);
    if (!result.ok || !result.data?.ok) throw new Error(result.data?.error || 'FarmUp preview could not be loaded.');
    active = result.data.batch; commitRequestKey = ''; search = ''; needsReviewOnly = false; mappingOpen = active.mapping?.state === 'needs_mapping'; await renderEditor();
  }
  async function upload(form) {
    const button = form.querySelector('button[type="submit"]'); setLoading(button, true, 'Uploading');
    try { const body = new FormData(form); body.set('client_request_id', requestId('portal-farmup-stage')); const result = await api.postForm('/farmup/stage/', body, tg); if (!result.ok || !result.data?.ok) throw new Error(result.data?.error || 'FarmUp upload failed.'); form.reset(); await load({silent:true}); await openBatch(result.data.batch.id); const message = result.data.replayed ? 'This CSV was already uploaded. Its current monthly worklist was reopened.' : (result.data.message || 'FarmUp staged.'); window.PortalAppShell?.showToast?.(message, 'success'); feedback(message, 'success'); if (result.data.archive_operation_id) await attemptDrive(result.data.archive_operation_id, true); } finally { setLoading(button, false); }
  }
  async function uploadVersion(form) {
    const button = form.querySelector('button[type="submit"]'); setLoading(button, true, 'Reconciling');
    try { const body = new FormData(form); body.set('client_request_id', requestId('portal-farmup-version')); const result = await api.postForm(`/farmup/${encodeURIComponent(active.id)}/versions/`, body, tg); if (!result.ok || !result.data?.ok) throw new Error(result.data?.error || 'Updated FarmUp CSV could not be reconciled.'); const message = result.data.replayed ? 'This version already exists. The current worklist was reopened.' : result.data.message; window.PortalAppShell?.showToast?.(message, 'success'); await load({silent:true}); await openBatch(result.data.batch.id); if (result.data.archive_operation_id) await attemptDrive(result.data.archive_operation_id, true); } finally { setLoading(button, false); }
  }
  function submittedRows() { gridApi?.stopEditing(); return (active.rows || []).map(row => ({row_id:row.row_id, approved:Boolean(row.approved), disposition:row.disposition || (row.approved ? 'commit_now' : 'hold'), warning_acknowledged:Boolean(row.warning_acknowledged), update_acknowledged:Boolean(row.update_acknowledged), ...Object.fromEntries((active.editable_fields || editableFields).map(field => [field, row[field] || '']))})); }
  async function validateReview() {
    const result = await api.postJson(`/farmup/${encodeURIComponent(active.id)}/validate/`, {revision_token:active.revision_token, rows:submittedRows()}, tg);
    if (!result.ok || !result.data?.ok) throw new Error(result.data?.error || 'FarmUp rows could not be validated.');
    active.validation = result.data.rows || []; prepareRows(); gridApi?.forEachNode(n => n.setSelected(Boolean(n.data.approved && rowSelectable(n.data)))); gridApi?.refreshCells({force:true}); gridApi?.redrawRows(); updateSummary(); return result.data;
  }
  function confirmCommit(counts) {
    const dialog = document.createElement('dialog'); dialog.className = 'farmup-confirm-dialog';
    dialog.innerHTML = `<form method="dialog"><h2>Commit selected FarmUp rows?</h2><div class="farmup-counters"><span><strong>${counts.selected}</strong>Commit now</span><span><strong>${counts.new}</strong>New</span><span class="warning"><strong>${counts.updates}</strong>Updates</span><span><strong>${counts.unchanged}</strong>Unchanged</span><span><strong>${counts.held}</strong>Held for later</span><span><strong>${counts.excluded}</strong>Excluded</span><span class="warning"><strong>${counts.removed}</strong>Removed from latest</span><span class="danger"><strong>${counts.unresolved}</strong>Unresolved</span></div><p>Django is committed first. Configured Master Data Sheet publication is queued and tracked separately. Held rows remain available in this monthly worklist.</p><div class="portal-import-actions"><button value="cancel" class="btn btn-secondary">Go back</button><button value="confirm" class="btn btn-primary"${counts.selected ? '' : ' disabled'}>Commit ${counts.selected} selected</button></div></form>`;
    document.body.append(dialog); dialog.showModal(); return new Promise(resolve => dialog.addEventListener('close', () => { const confirmed = dialog.returnValue === 'confirm'; dialog.remove(); resolve(confirmed); }, {once:true}));
  }
  async function commit() {
    const button = node('farmup-commit'); setLoading(button, true, 'Validating');
    try {
      const validation = await validateReview();
      const invalid = (validation.rows || []).some(row => row.selected && (row.issues.some(i => i.severity === 'blocker') || (row.issues.some(i => i.severity === 'warning') && !row.warning_acknowledged)));
      if (invalid) { feedback('Some selected rows still need correction or warning acknowledgement.', 'error'); return; }
      if (!await confirmCommit(validation.counts)) return;
      setLoading(button, true, 'Committing'); const key = commitRequestKey || requestId('portal-farmup-commit'); commitRequestKey = key;
      const result = await api.postJson(`/farmup/${encodeURIComponent(active.id)}/commit/`, {revision_token:active.revision_token, rows:submittedRows(), client_request_id:key}, tg);
      if (!result.ok || !result.data?.ok) throw new Error(result.data?.error || 'FarmUp commit failed.');
      commitRequestKey = ''; const receipt = result.data.result || {}; const message = `${receipt.committed || 0} committed to Portal — ${receipt.created || 0} created, ${receipt.updated || 0} updated${receipt.unchanged ? `, ${receipt.unchanged} already unchanged` : ''}. ${receipt.held || 0} held for later.${receipt.publications?.length ? ' Master Data Sheet sync queued.' : ''}`; window.PortalAppShell?.showToast?.(message, receipt.success ? 'success' : 'error'); feedback(message, receipt.success ? 'success' : 'error'); await load({silent:true}); await openBatch(active.id); const receiptNode = node('farmup-commit-receipt'); if (receiptNode) { receiptNode.hidden = false; receiptNode.textContent = message; }
    } catch (error) { feedback(error.message, 'error'); window.PortalAppShell?.showToast?.(error.message, 'error'); } finally { setLoading(button, false); }
  }
  async function saveMapping() {
    const button = node('farmup-save-mapping');
    const decisions = [...document.querySelectorAll('.farmup-mapping-row')].map(row => ({source_id:row.dataset.sourceId, target_field:row.querySelector('.farmup-mapping-target')?.value || ''}));
    const chosen = decisions.map(i => i.target_field).filter(Boolean);
    if (new Set(chosen).size !== chosen.length) { feedback('Each system field can be matched to only one CSV column.', 'error'); return; }
    if ((active.rows || []).length && !window.confirm('Applying this mapping will reparse the original CSV and clear current row edits and selections. Continue?')) return;
    setLoading(button, true, 'Applying');
    try { const result = await api.postJson(`/farmup/${encodeURIComponent(active.id)}/mapping/`, {revision_token:active.revision_token, mapping:decisions}, tg); if (!result.ok || !result.data?.ok) throw new Error(result.data?.error || 'Column mapping could not be applied.'); active = result.data.batch; active.validation = []; mappingOpen = false; commitRequestKey = ''; await renderEditor(); await load({silent:true}); feedback('Column mapping applied. Review the parsed rows.', 'success'); } catch (error) { feedback(error.message, 'error'); } finally { setLoading(button, false); }
  }
  async function attemptDrive(operationId, silent = false) { if (!operationId) throw new Error('The Drive archive operation is unavailable.'); const result = await api.postJson('/farmup/archive-attempt/', {operation_id:operationId}, tg); if (!result.ok || !result.data?.ok) { if (silent) return; throw new Error(result.data?.error || 'Drive archive retry failed.'); } if (!silent) feedback('FarmUp source archived to Drive.', 'success'); await load({silent:true}); }

  document.addEventListener('submit', event => { if (event.target.matches('#portal-farmup-upload')) { event.preventDefault(); return upload(event.target).catch(error => { feedback(error.message, 'error'); window.PortalAppShell?.showToast?.(error.message, 'error'); }); } if (event.target.matches('#farmup-version-upload')) { event.preventDefault(); return uploadVersion(event.target).catch(error => { feedback(error.message, 'error'); window.PortalAppShell?.showToast?.(error.message, 'error'); }); } });
  document.addEventListener('input', event => { if (event.target.id !== 'farmup-search') return; search = event.target.value; gridApi?.setGridOption('quickFilterText', search); updateSummary(); });
  document.addEventListener('click', event => {
    const open = event.target.closest('.farmup-open'); if (open) return openBatch(open.dataset.batchId).catch(error => feedback(error.message, 'error'));
    if (event.target.closest('#portal-farmup-refresh')) return load().catch(error => feedback(error.message, 'error'));
    if (event.target.closest('#farmup-close')) { gridApi?.destroy(); gridApi = null; node('portal-farmup-review').hidden = true; active = null; return; }
    if (event.target.closest('#farmup-review-filter')) { needsReviewOnly = !needsReviewOnly; gridApi?.onFilterChanged(); event.target.classList.toggle('active', needsReviewOnly); event.target.setAttribute('aria-pressed', String(needsReviewOnly)); updateSummary(); return; }
    if (event.target.closest('#farmup-select-all')) { gridApi?.forEachNodeAfterFilter(n => { if (rowSelectable(n.data)) { n.data.disposition = 'commit_now'; n.data.approved = true; n.setSelected(true); } }); updateSummary(); return; }
    if (event.target.closest('#farmup-clear-all')) { gridApi?.forEachNode(n => { if (!['committed','already_committed','excluded'].includes(n.data.disposition)) { n.data.disposition = 'hold'; n.data.approved = false; n.setSelected(false); } }); updateSummary(); return; }
    if (event.target.closest('#farmup-exclude-selected')) { gridApi?.getSelectedNodes().forEach(n => { n.data.disposition = 'exclude'; n.data.approved = false; n.setSelected(false); }); gridApi?.redrawRows(); updateSummary(); return; }
    if (event.target.closest('#farmup-restore-excluded')) { gridApi?.forEachNode(n => { if (n.data.disposition === 'exclude') n.data.disposition = 'hold'; }); gridApi?.redrawRows(); updateSummary(); return; }
    if (event.target.closest('#farmup-review-mapping')) { mappingOpen = true; renderMapping(); return; }
    if (event.target.closest('#farmup-cancel-mapping')) { mappingOpen = false; renderMapping(); return; }
    if (event.target.closest('#farmup-save-mapping')) return saveMapping();
    if (event.target.closest('#farmup-commit')) return commit();
    const retry = event.target.closest('.farmup-drive-retry'); if (retry) { const batch = batches.find(item => item.id === retry.dataset.batchId); return attemptDrive(batch?.archive_operation_id).catch(error => feedback(error.message, 'error')); }
    const archive = event.target.closest('.farmup-archive'); if (archive && window.confirm('Archive this batch from the FarmUp working list? Retained evidence will remain available.')) api.postJson(`/farmup/${encodeURIComponent(archive.dataset.batchId)}/archive/`, {}, tg).then(result => { if (!result.ok) throw new Error(result.data?.error); return load({silent:true}); }).catch(error => feedback(error.message, 'error'));
  });
  window.PortalMiniAppFarmUp = {load};
})();
