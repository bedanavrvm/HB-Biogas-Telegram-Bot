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
      applyIssues(row, validation?.issues || localIssues(row));
    });
  }
  function rowSelectable(row) { return row?._state === 'ready' || (row?._state === 'warning' && row.warning_acknowledged); }
  function reviewCounts() {
    const rows = active?.rows || [], visibleIds = new Set();
    gridApi?.forEachNodeAfterFilter(n => visibleIds.add(String(n.data.row_id)));
    const filterActive = Boolean(search.trim() || needsReviewOnly);
    return {
      selected: rows.filter(r => r.approved && rowSelectable(r)).length,
      warnings: rows.filter(r => r.approved && r._state === 'warning' && r.warning_acknowledged).length,
      skipped: rows.filter(r => !r.approved && r._state === 'ready').length,
      unresolved: rows.filter(r => r._state !== 'ready' && !r.approved).length,
      hidden: rows.filter(r => r.approved && filterActive && !visibleIds.has(String(r.row_id))).length,
      valid: rows.filter(r => r._state === 'ready').length,
    };
  }
  function updateSummary() {
    const c = reviewCounts(), target = node('farmup-selection-summary');
    if (target) target.innerHTML = `<span class="selected"><strong>${c.selected}</strong> selected to commit</span><span class="warning"><strong>${c.warnings}</strong> warning overrides</span><span><strong>${c.skipped}</strong> not selected (will be skipped)</span><span class="danger"><strong>${c.unresolved}</strong> unresolved</span>${c.hidden ? `<span><strong>${c.hidden}</strong> selected but hidden by filter</span>` : ''}`;
    if (node('farmup-select-all')) node('farmup-select-all').textContent = `Select all valid (${c.valid})`;
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
  function renderBatches() {
    const target = node('portal-farmup-list'); if (!target) return;
    if (!batches.length) { target.innerHTML = '<div class="empty-state"><div class="es-title">No FarmUp batches</div><div class="es-sub">Upload a Farmers CSV to begin a reviewed intake.</div></div>'; return; }
    target.innerHTML = batches.map(batch => `<article class="portal-import-card"><div class="portal-import-card-title"><div><span class="settings-eyebrow">FARMUP</span><h3>${escapeHtml(batch.source_filename || 'Farmers CSV')}</h3><p>${escapeHtml(batch.created_at || '')}</p></div><div>${batch.is_portal_archived ? '<span class="badge">Working list archived</span>' : ''}${archiveBadge(batch)}</div></div><div class="portal-import-stats"><span><strong>${Number(batch.total_rows || 0)}</strong> source rows</span><span class="${batch.review_needed ? 'warning' : ''}"><strong>${Number(batch.review_needed || 0)}</strong> review needed</span><span><strong>${Number(batch.committed_count || 0)}</strong> committed</span></div>${batch.mapping_state === 'needs_mapping' ? '<p class="farmup-mapping-alert">Column mapping needs attention before row review.</p>' : ''}<div class="portal-import-actions"><button class="btn btn-primary farmup-open" data-batch-id="${escapeHtml(batch.id)}">${batch.mapping_state === 'needs_mapping' ? 'Map columns' : (batch.status === 'committed' ? 'View result' : 'Review rows')}</button>${batch.archive_state === 'needs_attention' && can('portal.farmup.stage') ? `<button class="btn btn-secondary farmup-drive-retry" data-batch-id="${escapeHtml(batch.id)}">Retry Drive archive</button>` : ''}${can('portal.farmup.stage') && !batch.is_portal_archived ? `<button class="btn btn-secondary farmup-archive" data-batch-id="${escapeHtml(batch.id)}">Archive from FarmUp</button>` : ''}</div></article>`).join('');
  }
  async function load({silent = false} = {}) {
    if (!activeScreen()) return;
    const target = node('portal-farmup-list');
    if (!silent && target) target.innerHTML = '<div class="empty-state"><div class="spinner-inline"></div><div class="es-sub">Loading FarmUp batches...</div></div>';
    const result = await api.apiFetch('/farmup/', {}, tg);
    if (!activeScreen()) return;
    if (!result.ok || !result.data?.ok) throw new Error(result.data?.error || 'FarmUp batches could not be loaded.');
    batches = result.data.batches || []; renderBatches();
    if (node('portal-farmup-upload')) node('portal-farmup-upload').hidden = !can('portal.farmup.stage');
  }
  function statusRenderer(params) {
    const wrap = document.createElement('div'); wrap.className = 'farmup-grid-status';
    const label = params.data._state === 'needs_correction' ? 'Needs correction' : (params.data._state === 'warning' ? 'Warning' : 'Ready');
    const badge = document.createElement('span'); badge.className = `farmup-row-state ${params.data._state}`; badge.textContent = label; wrap.append(badge);
    if (params.data._state === 'warning') {
      const button = document.createElement('button'); button.type = 'button'; button.className = 'farmup-acknowledge'; button.textContent = params.data.warning_acknowledged ? 'Acknowledged' : 'Acknowledge'; button.setAttribute('aria-pressed', String(Boolean(params.data.warning_acknowledged)));
      button.addEventListener('click', event => { event.stopPropagation(); params.data.warning_acknowledged = !params.data.warning_acknowledged; if (!params.data.warning_acknowledged) { params.data.approved = false; params.node.setSelected(false); } params.api.refreshCells({rowNodes:[params.node], force:true}); updateSummary(); });
      wrap.append(button);
    }
    return wrap;
  }
  function statusTooltip(params) { return (params.data?._issues || []).map(item => item.message).join('; ') || 'This row is ready to commit.'; }
  function initializeGrid() {
    if (gridApi || !window.agGrid || !node('farmup-grid')) return;
    window.agGrid.ModuleRegistry.registerModules([window.agGrid.AllCommunityModule]);
    const textColumn = (field, width = 150) => ({field, headerName:field, width, editable:can('portal.farmup.commit'), tooltipValueGetter:p => String(p.value || '')});
    gridApi = window.agGrid.createGrid(node('farmup-grid'), {
      theme:'legacy', rowData:active.rows || [], animateRows:false, ensureDomOrder:true, rowHeight:38, headerHeight:38, suppressMovableColumns:true, enableBrowserTooltips:true,
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
      onSelectionChanged:event => { event.api.forEachNode(n => { n.data.approved = n.isSelected() && rowSelectable(n.data); }); event.api.redrawRows(); updateSummary(); },
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
    const review = active.mapping?.state === 'needs_mapping' ? '' : `<div class="farmup-toolbar"><input id="farmup-search" type="search" value="${escapeHtml(search)}" placeholder="Search all rows..."><button class="btn btn-secondary ${needsReviewOnly ? 'active' : ''}" id="farmup-review-filter" aria-pressed="${needsReviewOnly}">Needs review</button><button class="btn btn-secondary" id="farmup-select-all">Select all valid</button><button class="btn btn-secondary" id="farmup-clear-all">Clear selection</button></div><div id="farmup-selection-summary" class="farmup-selection-summary" aria-live="polite"></div><div class="farmup-grid-wrap" role="region" aria-label="FarmUp editable review table. Scroll horizontally to reach all fields." tabindex="0"><div id="farmup-grid" class="ag-theme-quartz farmup-grid"></div></div>${can('portal.farmup.commit') && active.status !== 'committed' ? '<div class="farmup-commit-bar"><span>Only selected rows will commit. Ready unselected rows will be skipped; unresolved rows remain for correction.</span><button class="btn btn-primary" id="farmup-commit">Review commit</button></div>' : ''}`;
    target.innerHTML = `<div class="portal-import-review-heading"><div><span class="settings-eyebrow">FARMUP REVIEW</span><h2>${escapeHtml(active.source_filename || 'FarmUp')}</h2><p>Correct highlighted cells and explicitly select rows to commit.</p></div><button class="btn btn-secondary" id="farmup-close">Close</button></div><section id="farmup-mapping-panel" class="farmup-mapping-panel"></section>${review}`;
    renderMapping();
    if (active.mapping?.state !== 'needs_mapping') { try { await loadGridAssets(); if (active && activeScreen()) initializeGrid(); } catch (error) { feedback(error.message, 'error'); } }
  }
  async function openBatch(batchId) {
    const result = await api.apiFetch(`/farmup/${encodeURIComponent(batchId)}/`, {}, tg);
    if (!result.ok || !result.data?.ok) throw new Error(result.data?.error || 'FarmUp preview could not be loaded.');
    active = result.data.batch; commitRequestKey = ''; search = ''; needsReviewOnly = false; mappingOpen = active.mapping?.state === 'needs_mapping'; await renderEditor();
  }
  async function upload(form) {
    const button = form.querySelector('button[type="submit"]'); setLoading(button, true, 'Uploading');
    try { const body = new FormData(form); body.set('client_request_id', requestId('portal-farmup-stage')); const result = await api.postForm('/farmup/stage/', body, tg); if (!result.ok || !result.data?.ok) throw new Error(result.data?.error || 'FarmUp upload failed.'); form.reset(); await load({silent:true}); await openBatch(result.data.batch.id); feedback(result.data.message || 'FarmUp staged.', 'success'); if (result.data.archive_operation_id) await attemptDrive(result.data.archive_operation_id, true); } finally { setLoading(button, false); }
  }
  function submittedRows() { gridApi?.stopEditing(); return (active.rows || []).map(row => ({row_id:row.row_id, approved:Boolean(row.approved), warning_acknowledged:Boolean(row.warning_acknowledged), ...Object.fromEntries((active.editable_fields || editableFields).map(field => [field, row[field] || '']))})); }
  async function validateReview() {
    const result = await api.postJson(`/farmup/${encodeURIComponent(active.id)}/validate/`, {revision_token:active.revision_token, rows:submittedRows()}, tg);
    if (!result.ok || !result.data?.ok) throw new Error(result.data?.error || 'FarmUp rows could not be validated.');
    active.validation = result.data.rows || []; prepareRows(); gridApi?.forEachNode(n => n.setSelected(Boolean(n.data.approved && rowSelectable(n.data)))); gridApi?.refreshCells({force:true}); gridApi?.redrawRows(); updateSummary(); return result.data;
  }
  function confirmCommit(counts) {
    const dialog = document.createElement('dialog'); dialog.className = 'farmup-confirm-dialog';
    dialog.innerHTML = `<form method="dialog"><h2>Commit selected FarmUp rows?</h2><div class="farmup-counters"><span><strong>${counts.selected}</strong>Selected</span><span class="warning"><strong>${counts.warning_overrides}</strong>Warning overrides</span><span><strong>${counts.skipped}</strong>Skipped</span><span class="danger"><strong>${counts.unresolved}</strong>Unresolved</span></div><p>Selected rows will update Django workflow state and may synchronize to the configured Master Data Sheet. Ready rows not selected will be skipped.</p><div class="portal-import-actions"><button value="cancel" class="btn btn-secondary">Go back</button><button value="confirm" class="btn btn-primary"${counts.selected ? '' : ' disabled'}>Commit ${counts.selected} selected</button></div></form>`;
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
      commitRequestKey = ''; feedback(result.data.result?.message || 'FarmUp rows committed.', result.data.result?.success ? 'success' : 'error'); await load({silent:true}); await openBatch(active.id);
    } catch (error) { feedback(error.message, 'error'); } finally { setLoading(button, false); }
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

  document.addEventListener('submit', event => { if (!event.target.matches('#portal-farmup-upload')) return; event.preventDefault(); upload(event.target).catch(error => feedback(error.message, 'error')); });
  document.addEventListener('input', event => { if (event.target.id !== 'farmup-search') return; search = event.target.value; gridApi?.setGridOption('quickFilterText', search); updateSummary(); });
  document.addEventListener('click', event => {
    const open = event.target.closest('.farmup-open'); if (open) return openBatch(open.dataset.batchId).catch(error => feedback(error.message, 'error'));
    if (event.target.closest('#portal-farmup-refresh')) return load().catch(error => feedback(error.message, 'error'));
    if (event.target.closest('#farmup-close')) { gridApi?.destroy(); gridApi = null; node('portal-farmup-review').hidden = true; active = null; return; }
    if (event.target.closest('#farmup-review-filter')) { needsReviewOnly = !needsReviewOnly; gridApi?.onFilterChanged(); event.target.classList.toggle('active', needsReviewOnly); event.target.setAttribute('aria-pressed', String(needsReviewOnly)); updateSummary(); return; }
    if (event.target.closest('#farmup-select-all')) { gridApi?.forEachNode(n => { if (n.data._state === 'ready') n.setSelected(true); }); updateSummary(); return; }
    if (event.target.closest('#farmup-clear-all')) { gridApi?.deselectAll(); updateSummary(); return; }
    if (event.target.closest('#farmup-review-mapping')) { mappingOpen = true; renderMapping(); return; }
    if (event.target.closest('#farmup-cancel-mapping')) { mappingOpen = false; renderMapping(); return; }
    if (event.target.closest('#farmup-save-mapping')) return saveMapping();
    if (event.target.closest('#farmup-commit')) return commit();
    const retry = event.target.closest('.farmup-drive-retry'); if (retry) { const batch = batches.find(item => item.id === retry.dataset.batchId); return attemptDrive(batch?.archive_operation_id).catch(error => feedback(error.message, 'error')); }
    const archive = event.target.closest('.farmup-archive'); if (archive && window.confirm('Archive this batch from the FarmUp working list? Retained evidence will remain available.')) api.postJson(`/farmup/${encodeURIComponent(archive.dataset.batchId)}/archive/`, {}, tg).then(result => { if (!result.ok) throw new Error(result.data?.error); return load({silent:true}); }).catch(error => feedback(error.message, 'error'));
  });
  window.PortalMiniAppFarmUp = {load};
})();
