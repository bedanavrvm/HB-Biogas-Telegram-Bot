(() => {
  'use strict';

  const api = window.PortalMiniAppApi || {};
  const utils = window.MiniAppUtils || {};
  const tg = window.Telegram?.WebApp;
  const editableFields = ['Customer Name', 'National ID', 'Primary Phone', 'Secondary Phone', 'Application Action', 'Additional Unit Reason', 'County', 'HBG Visit Date', 'Deposit Paid to HB', 'HB Sales Person'];
  const requiredFields = ['Customer Name', 'National ID', 'Primary Phone', 'Secondary Phone', 'County', 'HBG Visit Date', 'Deposit Paid to HB', 'HB Sales Person'];
  let batches = [], active = null, gridApi = null, gridAssetPromise = null;
  let search = '', needsReviewOnly = false, mappingOpen = false, commitRequestKey = '';
  let reviewMode = 'table';
  try { reviewMode = sessionStorage.getItem('portal-farmup-review-mode') === 'carousel' ? 'carousel' : 'table'; } catch (_) {}
  let carouselIndex = 0, pickerActive = false, pickerHadSelection = false;
  let repairProgress = null;
  let gridLayoutFrame = 0;

  function node(id) { return document.getElementById(id); }
  function activeScreen() { return node('portal-screen')?.dataset.screen === 'farmup'; }
  function can(key) { return window.PortalAppShell?.hasCapability?.(key) !== false; }
  function escapeHtml(value) { return String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
  function requestId(prefix) { return utils.createRequestId?.(prefix) || `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`; }
  function icon(name) { return `<i data-lucide="${name}" aria-hidden="true"></i>`; }
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
  function normalized(value) { return String(value ?? '').trim().replace(/\s+/g, ' ').toLocaleLowerCase(); }
  function fieldEdited(row, field) { return normalized(row[field]) !== String(row._baseline?.[field] ?? ''); }
  function editedFields(row) { return (active?.editable_fields || editableFields).filter(field => fieldEdited(row, field)); }
  function rowWorkflowChanged(row) { return row.disposition !== row._baselineDisposition || Boolean(row.approved) !== row._baselineApproved; }
  function syncDirtyProtection() {
    const dirty = (active?.rows || []).some(row => editedFields(row).length || rowWorkflowChanged(row));
    utils.setCloseProtection?.('portal-farmup-review-dirty', dirty);
  }
  function clearDirtyProtection() { utils.setCloseProtection?.('portal-farmup-review-dirty', false); }
  function localIssues(row) {
    const issues = [];
    requiredFields.forEach(field => { if (isBlank(row[field])) issues.push({severity:'blocker', field, message:`${field} is required`}); });
    if (!['update_existing', 'create_additional_unit'].includes(row['Application Action'] || 'update_existing')) issues.push({severity:'blocker', field:'Application Action', message:'Application Action must be selected'});
    if (row['Application Action'] === 'create_additional_unit' && isBlank(row['Additional Unit Reason'])) issues.push({severity:'blocker', field:'Additional Unit Reason', message:'Additional Unit Reason is required'});
    const nationalId = String(row['National ID'] || '').trim();
    if (nationalId && !/^\d+$/.test(nationalId)) issues.push({severity:'blocker', field:'National ID', message:'National ID must contain digits only'});
    else if (nationalId && !/^\d{7,9}$/.test(nationalId)) issues.push({severity:'warning', field:'National ID', message:'National ID is outside the usual 7-9 digit range'});
    return issues;
  }
  function fieldInvalid(row, field) {
    return (row._issues || []).some(issue => issue.severity === 'blocker' && (
      issue.field === field || String(issue.message || '').toLocaleLowerCase().startsWith(field.toLocaleLowerCase())
    ));
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
      if (!row._baseline) row._baseline = Object.fromEntries((active.editable_fields || editableFields).map(field => [field, normalized(row[field])]));
      if (row._baselineDisposition === undefined) row._baselineDisposition = row.disposition;
      if (row._baselineApproved === undefined) row._baselineApproved = Boolean(row.approved);
    });
  }
  function rowSelectable(row) { if (['unchanged','identity_conflict'].includes(row?._match?.kind)) return false; if (!['commit_now','hold'].includes(row?.disposition)) return false; return row?._state === 'ready' || (row?._state === 'warning' && row.warning_acknowledged); }
  function visibleReviewRows() {
    const term = search.trim().toLocaleLowerCase();
    return (active?.rows || []).filter(row => (!needsReviewOnly || row._state !== 'ready') && (!term || Object.values(row).some(value => typeof value !== 'object' && String(value ?? '').toLocaleLowerCase().includes(term))));
  }
  function reviewCounts() {
    const rows = active?.rows || [], visibleIds = new Set(visibleReviewRows().map(row => String(row.row_id)));
    const filterActive = Boolean(search.trim() || needsReviewOnly);
    return {
      selected: rows.filter(r => r.approved && rowSelectable(r)).length,
      creates: rows.filter(r => r.approved && ['new','additional_unit'].includes(r._match?.kind)).length,
      updates: rows.filter(r => r.approved && r._match?.kind === 'update').length,
      unchanged: rows.filter(r => r._match?.kind === 'unchanged' || r.disposition === 'already_committed').length,
      held: rows.filter(r => r.disposition === 'hold').length,
      excluded: rows.filter(r => ['exclude','excluded'].includes(r.disposition)).length,
      removed: rows.filter(r => r._source_state === 'removed').length,
      unresolved: rows.filter(r => r._state !== 'ready' && !r.approved).length,
      hidden: rows.filter(r => r.approved && filterActive && !visibleIds.has(String(r.row_id))).length,
      valid: rows.filter(r => rowSelectable(r)).length,
      editedCells: rows.reduce((total, row) => total + editedFields(row).length, 0),
      editedRows: rows.filter(row => editedFields(row).length).length,
    };
  }
  function updateSummary() {
    const c = reviewCounts(), target = node('farmup-selection-summary');
    if (target) target.innerHTML = `<span class="selected"><strong>${c.selected}</strong> commit</span><span class="edited"><strong>${c.editedCells}</strong> edits / ${c.editedRows} rows</span><span><strong>${c.creates}</strong> new</span><span><strong>${c.updates}</strong> updates</span><span><strong>${c.unchanged}</strong> unchanged</span><span><strong>${c.held}</strong> held</span><span><strong>${c.excluded}</strong> excluded</span><span class="danger"><strong>${c.unresolved}</strong> unresolved</span>${c.hidden ? `<span><strong>${c.hidden}</strong> selected hidden</span>` : ''}`;
    const selectAll = node('farmup-select-all'); if (selectAll) selectAll.title = `Select all ${c.valid} eligible cases`;
    if (node('farmup-commit')) node('farmup-commit').disabled = !c.selected;
    syncDirtyProtection();
  }
  function loadGridAssets() {
    if (window.agGrid) return Promise.resolve();
    if (gridAssetPromise) return gridAssetPromise;
    const config = window.PORTAL_CONFIG || {};
    (config.farmupAgGridStyles || []).forEach(href => { if (!document.querySelector(`link[href="${href}"]`)) { const link = document.createElement('link'); link.rel = 'stylesheet'; link.href = href; document.head.append(link); } });
    gridAssetPromise = new Promise((resolve, reject) => { const script = document.createElement('script'); script.src = config.farmupAgGridScript; script.onload = resolve; script.onerror = () => reject(new Error('The FarmUp table could not be loaded.')); document.head.append(script); });
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
    batches = (Array.isArray(result.data.batches) ? result.data.batches : []).filter(batch => batch && typeof batch === 'object');
    batches.forEach(batch => api.schedulePublication?.(batch.publication || {}, tg)); renderBatches();
    if (node('portal-farmup-upload')) node('portal-farmup-upload').hidden = !can('portal.farmup.stage');
  }
  function statusTooltip(params) { const changes = params.data?._match?.changed_fields || []; return [(params.data?._issues || []).map(item => item.message).join('; '), changes.length ? `Changes: ${changes.join(', ')}` : ''].filter(Boolean).join('; ') || 'This row is ready to commit.'; }
  function statusRenderer(params) {
    const wrap = document.createElement('div'); wrap.className = 'farmup-grid-status';
    const match = params.data._match?.kind;
    const label = params.data.disposition === 'committed' ? 'Committed' : (match === 'unchanged' || params.data.disposition === 'already_committed') ? 'Already committed' : match === 'update' ? 'Will update' : match === 'new' ? 'New' : params.data._state === 'needs_correction' ? 'Needs correction' : (params.data._state === 'warning' ? 'Warning' : 'Ready');
    const badge = document.createElement('span'); badge.className = `farmup-row-state ${params.data._state}`; badge.textContent = label; wrap.append(badge);
    if (params.data._state === 'warning') { const button = document.createElement('button'); button.type = 'button'; button.className = 'farmup-acknowledge'; button.textContent = params.data.warning_acknowledged ? 'Acknowledged' : (match === 'update' ? 'Acknowledge update' : 'Acknowledge'); button.setAttribute('aria-pressed', String(Boolean(params.data.warning_acknowledged))); button.addEventListener('click', event => { event.stopPropagation(); params.data.warning_acknowledged = !params.data.warning_acknowledged; if (match === 'update') params.data.update_acknowledged = params.data.warning_acknowledged; if (!params.data.warning_acknowledged) { params.data.approved = false; params.data.disposition = 'hold'; params.node.setSelected(false); } params.api.refreshCells({rowNodes:[params.node], force:true}); updateSummary(); }); wrap.append(button); }
    return wrap;
  }
  function applicationActionLabel(value) {
    return value === 'create_additional_unit' ? 'Additional unit (same farmer)' : 'New lead (first unit)';
  }
  function layoutGrid() {
    window.cancelAnimationFrame(gridLayoutFrame);
    gridLayoutFrame = window.requestAnimationFrame(() => {
      const grid = node('farmup-grid');
      if (!grid || reviewMode !== 'table' || grid.closest('[hidden]')) return;
      const viewport = window.visualViewport;
      const viewportBottom = (Number(viewport?.offsetTop) || 0) + (Number(viewport?.height) || window.innerHeight || 640);
      const top = grid.getBoundingClientRect().top;
      const commitHeight = node('farmup-commit')?.closest('.farmup-commit-bar')?.getBoundingClientRect().height || 0;
      const tabs = node('bottom-tabs');
      const tabsHeight = tabs && getComputedStyle(tabs).display !== 'none' ? tabs.getBoundingClientRect().height : 0;
      grid.style.height = `${Math.max(260, Math.min(680, Math.floor(viewportBottom - top - commitHeight - tabsHeight - 18)))}px`;
      try {
        gridApi?.setColumnsPinned?.(['state'], window.innerWidth > 700 ? 'left' : null);
        gridApi?.doLayout?.();
      } catch (_) { /* Element sizing still works on older AG Grid builds. */ }
    });
  }
  function setRowField(row, field, value, input) {
    row[field] = value; active.validation = []; applyIssues(row, localIssues(row));
    if (!rowSelectable(row)) { row.disposition = 'hold'; row.approved = false; gridApi?.getRowNode(String(row.row_id))?.setSelected(false); }
    if (input) { const label = input.closest('.farmup-carousel-field'); label?.classList.toggle('edited', fieldEdited(row, field)); label?.classList.toggle('invalid', fieldInvalid(row, field)); }
    gridApi?.refreshCells({force:true}); gridApi?.redrawRows(); updateSummary();
  }
  function initializeGrid() {
    if (gridApi || !window.agGrid || !node('farmup-grid')) return;
    window.agGrid.ModuleRegistry.registerModules([window.agGrid.AllCommunityModule]);
    const textColumn = (field, width = 150) => ({field, headerName:field, width, editable:can('portal.farmup.commit'), tooltipValueGetter:p => String(p.value || ''), cellClassRules:{'farmup-cell-edited':p => fieldEdited(p.data, field),'farmup-cell-invalid':p => fieldInvalid(p.data, field)}});
    gridApi = window.agGrid.createGrid(node('farmup-grid'), {
      theme:'legacy', rowData:active.rows || [], animateRows:false, ensureDomOrder:true, rowHeight:32, headerHeight:32, suppressMovableColumns:true, enableBrowserTooltips:true,
      getRowId:p => String(p.data.row_id), rowSelection:'multiple', suppressRowClickSelection:true,
      isExternalFilterPresent:() => needsReviewOnly, doesExternalFilterPass:p => !needsReviewOnly || p.data._state !== 'ready',
      defaultColDef:{sortable:true, resizable:true, suppressHeaderMenuButton:true},
      columnDefs:[
        {headerName:'', colId:'selected', width:40, minWidth:40, maxWidth:40, pinned:'left', sortable:false, resizable:false, checkboxSelection:p => rowSelectable(p.data), cellClass:'farmup-selection-cell'},
        {headerName:'State', colId:'state', width:142, pinned:window.innerWidth > 700 ? 'left' : null, sortable:false, cellRenderer:statusRenderer, tooltipValueGetter:statusTooltip},
        {field:'Source Row', headerName:'Row', width:62, editable:false}, textColumn('Customer Name',180), textColumn('National ID',120), textColumn('Primary Phone',135), textColumn('Secondary Phone',135),
        {field:'Application Action', headerName:'Unit type', width:210, editable:can('portal.farmup.commit'), cellEditor:'agSelectCellEditor', cellEditorParams:{values:['update_existing','create_additional_unit']}, valueFormatter:p => applicationActionLabel(p.value), cellClassRules:{'farmup-cell-edited':p => fieldEdited(p.data, 'Application Action'),'farmup-cell-invalid':p => fieldInvalid(p.data, 'Application Action')}},
        textColumn('Additional Unit Reason',190), textColumn('County',120), textColumn('HBG Visit Date',135), textColumn('Deposit Paid to HB',140), textColumn('HB Sales Person',150),
        {colId:'validation_notes', headerName:'Validation notes', width:280, editable:false, valueGetter:p => (p.data._issues || []).map(i => i.message).join('; '), tooltipValueGetter:statusTooltip},
      ],
      rowClassRules:{'farmup-grid-row-blocked':p => p.data._state === 'needs_correction','farmup-grid-row-warning':p => p.data._state === 'warning','farmup-grid-row-unselected':p => p.data._state === 'ready' && !p.data.approved},
      onGridReady:event => { event.api.forEachNode(n => n.setSelected(Boolean(n.data.approved && rowSelectable(n.data)))); updateSummary(); layoutGrid(); },
      onSelectionChanged:event => { event.api.forEachNode(n => { if (['exclude','committed','already_committed','excluded'].includes(n.data.disposition)) return; n.data.approved = n.isSelected() && rowSelectable(n.data); n.data.disposition = n.data.approved ? 'commit_now' : 'hold'; }); event.api.redrawRows(); if (reviewMode === 'carousel') renderCarousel(); updateSummary(); },
      onCellValueChanged:event => setRowField(event.data, event.colDef.field, event.newValue),
      onCellEditingStarted:event => setTimeout(() => event.event?.target?.scrollIntoView?.({block:'center', inline:'nearest'}), 80),
    });
  }
  function renderCarousel() {
    const target = node('farmup-carousel'); if (!target || !active) return;
    const rows = visibleReviewRows(); carouselIndex = Math.max(0, Math.min(carouselIndex, Math.max(0, rows.length - 1)));
    if (!rows.length) { target.innerHTML = '<div class="empty-state"><div class="es-title">No matching cases</div></div>'; return; }
    target.innerHTML = `<div class="farmup-carousel-track">${rows.map((row, index) => `<article class="farmup-carousel-card ${escapeHtml(row._state)}" data-row-id="${escapeHtml(row.row_id)}"><header><label><input type="checkbox" class="farmup-carousel-select" ${row.approved ? 'checked' : ''} ${rowSelectable(row) ? '' : 'disabled'}><span>Commit</span></label><div><strong>${escapeHtml(row['Customer Name'] || 'Unnamed farmer')}</strong><small>Row ${escapeHtml(row['Source Row'] || row.row_id)} · ${escapeHtml(row['National ID'] || 'No ID')}</small></div><b>${index + 1}/${rows.length}</b></header><p>${escapeHtml(statusTooltip({data:row}))}</p><div class="farmup-carousel-fields">${(active.editable_fields || editableFields).filter(field => field !== 'Additional Unit Reason' || row['Application Action'] === 'create_additional_unit').map(field => { const select = field === 'Application Action'; const label = select ? 'Unit type' : field; return `<label class="farmup-carousel-field${fieldEdited(row, field) ? ' edited' : ''}${fieldInvalid(row, field) ? ' invalid' : ''}"><span>${escapeHtml(label)}${fieldEdited(row, field) ? '<b title="Edited">●</b>' : ''}</span>${select ? `<select data-field="${escapeHtml(field)}" ${can('portal.farmup.commit') ? '' : 'disabled'}><option value="update_existing"${row[field] === 'update_existing' ? ' selected' : ''}>New lead (first unit)</option><option value="create_additional_unit"${row[field] === 'create_additional_unit' ? ' selected' : ''}>Additional unit (same farmer)</option></select>` : `<input data-field="${escapeHtml(field)}" value="${escapeHtml(row[field] || '')}" ${can('portal.farmup.commit') ? '' : 'disabled'}>`}</label>`; }).join('')}</div></article>`).join('')}</div><div class="farmup-carousel-nav"><button type="button" class="icon-button" id="farmup-carousel-prev" aria-label="Previous case" title="Previous case">${icon('chevron-left')}</button><span>${carouselIndex + 1} of ${rows.length}</span><button type="button" class="icon-button" id="farmup-carousel-next" aria-label="Next case" title="Next case">${icon('chevron-right')}</button></div>`;
    const track = target.querySelector('.farmup-carousel-track');
    requestAnimationFrame(() => track?.children[carouselIndex]?.scrollIntoView({behavior:'instant', inline:'start', block:'nearest'}));
    track?.addEventListener('scroll', () => { const width = track.clientWidth || 1; carouselIndex = Math.max(0, Math.min(rows.length - 1, Math.round(track.scrollLeft / width))); const counter = target.querySelector('.farmup-carousel-nav span'); if (counter) counter.textContent = `${carouselIndex + 1} of ${rows.length}`; }, {passive:true});
    target.querySelectorAll('[data-field]').forEach(input => input.addEventListener('input', () => { const row = rows.find(item => String(item.row_id) === input.closest('[data-row-id]').dataset.rowId); if (row) setRowField(row, input.dataset.field, input.value, input); }));
    target.querySelectorAll('.farmup-carousel-select').forEach(input => input.addEventListener('change', () => { const row = rows.find(item => String(item.row_id) === input.closest('[data-row-id]').dataset.rowId); if (!row) return; row.approved = input.checked; row.disposition = input.checked ? 'commit_now' : 'hold'; gridApi?.getRowNode(String(row.row_id))?.setSelected(input.checked); updateSummary(); }));
    window.lucide?.createIcons?.();
  }
  function setReviewMode(mode) {
    reviewMode = mode === 'carousel' ? 'carousel' : 'table'; try { sessionStorage.setItem('portal-farmup-review-mode', reviewMode); } catch (_) {}
    node('farmup-grid-wrap')?.toggleAttribute('hidden', reviewMode !== 'table'); node('farmup-carousel')?.toggleAttribute('hidden', reviewMode !== 'carousel');
    document.querySelectorAll('[data-farmup-mode]').forEach(button => { const selected = button.dataset.farmupMode === reviewMode; button.classList.toggle('active', selected); button.setAttribute('aria-pressed', String(selected)); });
    if (reviewMode === 'carousel') renderCarousel();
    else layoutGrid();
  }
  function mappingSummary(mapping) { return `${(mapping?.columns || []).filter(i => i.target_field).length} mapped · ${(mapping?.columns || []).filter(i => !i.target_field && i.resolution !== 'unresolved').length} ignored`; }
  function renderMapping() {
    const target = node('farmup-mapping-panel'); if (!target) return;
    const mapping = active.mapping || {}, mustMap = mapping.state === 'needs_mapping'; target.hidden = false;
    if (!mappingOpen && !mustMap) { target.innerHTML = `<div class="farmup-mapping-summary"><div><strong>Column mapping</strong><span>${escapeHtml(mappingSummary(mapping))}. Column order does not matter.</span></div>${can('portal.farmup.stage') && !active.committed_count ? '<button type="button" class="btn btn-secondary" id="farmup-review-mapping">Review mapping</button>' : ''}</div>`; return; }
    const options = mapping.canonical_fields || [];
    const rows = (mapping.columns || []).map(column => `<div class="farmup-mapping-row" data-source-id="${escapeHtml(column.source_id)}"><div><strong>${column.column_number}. ${escapeHtml(column.source_header || '(blank header)')}</strong><span>${(column.sample_values || []).map(escapeHtml).join(' · ') || 'No sample values'}</span></div><label><span>Maps to</span><select class="farmup-mapping-target"><option value="">Ignore this column</option>${options.map(option => `<option value="${escapeHtml(option.key)}"${option.key === column.target_field ? ' selected' : ''}>${escapeHtml(option.label)}${option.required ? ' *' : ''}</option>`).join('')}</select></label></div>`).join('');
    const missing = (mapping.missing_required_fields || []).map(key => options.find(item => item.key === key)?.label || key);
    target.innerHTML = `<div class="farmup-mapping-heading"><div><strong>${mustMap ? 'Match CSV columns before review' : 'Review column mapping'}</strong><span>Choose a system field or explicitly ignore each source column.</span></div></div>${missing.length ? `<div class="farmup-mapping-missing"><strong>Not supplied:</strong> ${missing.map(escapeHtml).join(', ')}. Enter these values during review.</div>` : ''}<div class="farmup-mapping-list">${rows}</div><div class="portal-import-actions"><button type="button" class="btn btn-secondary" id="farmup-cancel-mapping"${mustMap ? ' hidden' : ''}>Cancel</button><button type="button" class="btn btn-primary" id="farmup-save-mapping">Apply mapping</button></div>`;
  }
  async function renderEditor() {
    const target = node('portal-farmup-review'); if (!target || !active) return;
    if (gridApi) { gridApi.destroy(); gridApi = null; } prepareRows(); target.hidden = false;
    const tools = `<div class="farmup-toolbar"><input id="farmup-search" type="search" value="${escapeHtml(search)}" placeholder="Search all rows…"><div class="farmup-mode-toggle" role="group" aria-label="Review layout"><button type="button" data-farmup-mode="table" aria-label="Table review" title="Table review">${icon('table-2')}</button><button type="button" data-farmup-mode="carousel" aria-label="Swipe review" title="Swipe review">${icon('gallery-horizontal')}</button></div><button class="btn btn-secondary ${needsReviewOnly ? 'active' : ''}" id="farmup-review-filter" aria-pressed="${needsReviewOnly}">Needs review</button><button class="icon-button" id="farmup-select-all" aria-label="Select all eligible" title="Select all eligible">${icon('list-checks')}</button><button class="icon-button" id="farmup-clear-all" aria-label="Hold all" title="Hold all">${icon('pause')}</button><button class="icon-button" id="farmup-exclude-selected" aria-label="Exclude selected" title="Exclude selected">${icon('circle-minus')}</button><button class="icon-button" id="farmup-restore-excluded" aria-label="Restore exclusions" title="Restore exclusions">${icon('undo-2')}</button></div>`;
    const review = active.mapping?.state === 'needs_mapping' ? '' : `${tools}<div id="farmup-selection-summary" class="farmup-selection-summary" aria-live="polite"></div><div id="farmup-grid-wrap" class="farmup-grid-wrap" role="region" aria-label="FarmUp editable review table. Scroll horizontally to reach all fields." tabindex="0"><div id="farmup-grid" class="ag-theme-quartz farmup-grid"></div></div><div id="farmup-carousel" class="farmup-carousel" hidden></div>${can('portal.farmup.commit') && active.status !== 'committed' ? '<div class="farmup-commit-bar"><span>Selected rows commit now; other rows stay held.</span><button class="btn btn-primary" id="farmup-commit">Review commit</button></div>' : ''}`;
    target.innerHTML = `<div class="portal-import-review-heading"><div><span class="settings-eyebrow">${escapeHtml(active.period_label || 'FARMUP')} · VERSION ${Number(active.version_number || 1)}</span><h2>${escapeHtml(active.source_filename || 'FarmUp')}</h2><p>Edited cells are blue; invalid cells remain red. ${(active.versions || []).length} immutable upload version${(active.versions || []).length === 1 ? '' : 's'} retained.</p></div><div class="portal-import-actions">${can('portal.publication.retry') && active.committed_count ? `<button class="btn btn-secondary" id="farmup-repair">${icon('wrench')} Repair Sheet</button>` : ''}<button class="icon-button" id="farmup-close" aria-label="Close review" title="Close review">${icon('x')}</button></div></div>${can('portal.farmup.stage') && active.is_current_version ? '<form id="farmup-version-upload" class="farmup-version-upload"><label><span>Updated monthly CSV</span><input type="file" name="file" data-farmup-file required></label><button class="btn btn-secondary" type="submit">Upload version</button></form>' : ''}<div id="farmup-commit-receipt" class="farmup-commit-receipt" hidden></div><section id="farmup-mapping-panel" class="farmup-mapping-panel"></section>${review}`;
    renderMapping(); window.lucide?.createIcons?.();
    const priorReceipt = node('farmup-commit-receipt');
    if (priorReceipt && active.publication?.status && active.publication.status !== 'not_required') { priorReceipt.hidden = false; priorReceipt.textContent = active.publication.status === 'synced' ? `Master Data Sheet synchronized for ${active.publication.synced || 0} publication operation(s).` : active.publication.status === 'needs_attention' ? 'Portal data is saved. Master Data Sheet synchronization needs repair.' : 'Portal data is saved. Master Data Sheet synchronization is queued.'; }
    if (active.mapping?.state !== 'needs_mapping') { try { await loadGridAssets(); if (active && activeScreen()) { initializeGrid(); setReviewMode(reviewMode); updateSummary(); } } catch (error) { feedback(error.message, 'error'); } }
  }
  async function openBatch(batchId) {
    const result = await api.apiFetch(`/farmup/${encodeURIComponent(batchId)}/`, {}, tg);
    if (!result.ok || !result.data?.ok) throw new Error(result.data?.error || 'FarmUp preview could not be loaded.');
    clearDirtyProtection(); active = result.data.batch; commitRequestKey = ''; search = ''; needsReviewOnly = false; carouselIndex = 0; mappingOpen = active.mapping?.state === 'needs_mapping'; await renderEditor();
  }
  function validateFarmupFile(input) {
    const file = input?.files?.[0]; if (!file) return false;
    const maxMb = Number(window.PORTAL_CONFIG?.farmupMaxFileSizeMb || 5);
    if (!String(file.name || '').toLocaleLowerCase().endsWith('.csv')) { input.value = ''; throw new Error('Choose a CSV file. Android may label CSV files with a generic type; the filename must end in .csv.'); }
    if (file.size > maxMb * 1024 * 1024) { input.value = ''; throw new Error(`This CSV exceeds the ${maxMb} MB upload limit.`); }
    return true;
  }
  async function upload(form) {
    const input = form.querySelector('[data-farmup-file]'); validateFarmupFile(input);
    const button = form.querySelector('button[type="submit"]'); setLoading(button, true, 'Uploading');
    try { const body = new FormData(form); body.set('client_request_id', requestId('portal-farmup-stage')); const result = await api.postForm('/farmup/stage/', body, tg); if (!result.ok || !result.data?.ok) throw new Error(result.data?.error || 'FarmUp upload failed.'); form.reset(); utils.setCloseProtection?.('portal-farmup-file-selected', false); await load({silent:true}); await openBatch(result.data.batch.id); const message = result.data.replayed ? 'This CSV was already uploaded. Its current monthly worklist was reopened.' : (result.data.message || 'FarmUp staged.'); window.PortalAppShell?.showToast?.(message, 'success'); feedback(message, 'success'); if (result.data.archive_operation_id) await attemptDrive(result.data.archive_operation_id, true); } finally { setLoading(button, false); }
  }
  async function uploadVersion(form) {
    const input = form.querySelector('[data-farmup-file]'); validateFarmupFile(input);
    const button = form.querySelector('button[type="submit"]'); setLoading(button, true, 'Reconciling');
    try { const body = new FormData(form); body.set('client_request_id', requestId('portal-farmup-version')); const result = await api.postForm(`/farmup/${encodeURIComponent(active.id)}/versions/`, body, tg); if (!result.ok || !result.data?.ok) throw new Error(result.data?.error || 'Updated FarmUp CSV could not be reconciled.'); utils.setCloseProtection?.('portal-farmup-file-selected', false); const message = result.data.replayed ? 'This version already exists. The current worklist was reopened.' : result.data.message; window.PortalAppShell?.showToast?.(message, 'success'); await load({silent:true}); await openBatch(result.data.batch.id); if (result.data.archive_operation_id) await attemptDrive(result.data.archive_operation_id, true); } finally { setLoading(button, false); }
  }
  function submittedRows() { gridApi?.stopEditing(); return (active.rows || []).map(row => ({row_id:row.row_id, approved:Boolean(row.approved), disposition:row.disposition || (row.approved ? 'commit_now' : 'hold'), warning_acknowledged:Boolean(row.warning_acknowledged), update_acknowledged:Boolean(row.update_acknowledged), ...Object.fromEntries((active.editable_fields || editableFields).map(field => [field, row[field] || '']))})); }
  async function validateReview() {
    const result = await api.postJson(`/farmup/${encodeURIComponent(active.id)}/validate/`, {revision_token:active.revision_token, rows:submittedRows()}, tg);
    if (!result.ok || !result.data?.ok) throw new Error(result.data?.error || 'FarmUp rows could not be validated.');
    active.validation = result.data.rows || []; prepareRows(); gridApi?.forEachNode(n => n.setSelected(Boolean(n.data.approved && rowSelectable(n.data)))); gridApi?.refreshCells({force:true}); gridApi?.redrawRows(); if (reviewMode === 'carousel') renderCarousel(); updateSummary(); return result.data;
  }
  function confirmDialog(title, counts, message, confirmLabel) {
    const dialog = document.createElement('dialog'); dialog.className = 'farmup-confirm-dialog';
    dialog.innerHTML = `<form method="dialog"><h2>${escapeHtml(title)}</h2><div class="farmup-counters">${Object.entries(counts).map(([label,value]) => `<span><strong>${Number(value || 0)}</strong>${escapeHtml(label.replaceAll('_',' '))}</span>`).join('')}</div><p>${escapeHtml(message)}</p><div class="portal-import-actions"><button value="cancel" class="btn btn-secondary">Go back</button><button value="confirm" class="btn btn-primary">${escapeHtml(confirmLabel)}</button></div></form>`;
    document.body.append(dialog); dialog.showModal(); return new Promise(resolve => dialog.addEventListener('close', () => { const confirmed = dialog.returnValue === 'confirm'; dialog.remove(); resolve(confirmed); }, {once:true}));
  }
  async function commit() {
    const button = node('farmup-commit'); setLoading(button, true, 'Validating');
    try {
      const validation = await validateReview();
      const invalid = (validation.rows || []).some(row => row.selected && (row.issues.some(i => i.severity === 'blocker') || (row.issues.some(i => i.severity === 'warning') && !row.warning_acknowledged)));
      if (invalid) { feedback('Some selected rows still need correction or warning acknowledgement.', 'error'); return; }
      const edits = reviewCounts(); const counts = {...validation.counts, edited_cells:edits.editedCells, edited_rows:edits.editedRows};
      if (!await confirmDialog('Commit selected FarmUp rows?', counts, 'Django commits first. Held and unresolved rows remain in this monthly worklist; Sheet publication is queued separately.', `Commit ${counts.selected || 0} selected`)) return;
      setLoading(button, true, 'Committing'); const key = commitRequestKey || requestId('portal-farmup-commit'); commitRequestKey = key;
      const result = await api.postJson(`/farmup/${encodeURIComponent(active.id)}/commit/`, {revision_token:active.revision_token, rows:submittedRows(), client_request_id:key}, tg);
      if (!result.ok || !result.data?.ok) throw new Error(result.data?.error || 'FarmUp commit failed.');
      commitRequestKey = ''; clearDirtyProtection(); const receipt = result.data.result || {}; const message = `${receipt.committed || 0} committed to Portal — ${receipt.created || 0} created, ${receipt.updated || 0} updated. ${receipt.held || 0} held.${receipt.publications?.length ? ' Master Data Sheet sync queued.' : ''}`; window.PortalAppShell?.showToast?.(message, receipt.success ? 'success' : 'error'); feedback(message, receipt.success ? 'success' : 'error'); (result.data.publications || []).forEach(publication => api.schedulePublication?.(publication, tg)); const batchId = active.id; await load({silent:true}); await openBatch(batchId); const receiptNode = node('farmup-commit-receipt'); if (receiptNode) { receiptNode.hidden = false; receiptNode.textContent = message; }
    } catch (error) { feedback(error.message, 'error'); window.PortalAppShell?.showToast?.(error.message, 'error'); } finally { setLoading(button, false); }
  }
  async function repairSheet() {
    const button = node('farmup-repair'); setLoading(button, true, 'Checking');
    try {
      const previewResult = await api.apiFetch(`/farmup/${encodeURIComponent(active.id)}/repair-preview/?revision_token=${encodeURIComponent(active.revision_token)}`, {}, tg);
      if (!previewResult.ok || !previewResult.data?.ok) throw new Error(previewResult.data?.error || 'Sheet repair preview could not be loaded.');
      const preview = previewResult.data.preview, counts = preview.counts || {};
      if (!preview.sheet_enabled) throw new Error('Master Data Sheet synchronization is not enabled for this Jawabu group.');
      if (!await confirmDialog(`Repair ${preview.period_label || 'this month'}?`, counts, 'Current Django farmer data will be republished. Review rows and selections will not change; invalid deposits are skipped per farmer.', `Repair ${counts.repairable || 0} farmers`)) return;
      setLoading(button, true, 'Queuing'); const key = requestId('portal-farmup-repair');
      const result = await api.postJson(`/farmup/${encodeURIComponent(active.id)}/repair/`, {revision_token:active.revision_token, client_request_id:key}, tg);
      if (!result.ok || !result.data?.ok) throw new Error(result.data?.error || 'Sheet repair could not be queued.');
      (result.data.publications || []).forEach(publication => api.schedulePublication?.(publication, tg));
      const repaired = result.data.result?.repairable || 0, skipped = result.data.result?.skipped_invalid_deposits || 0;
      repairProgress = { pending: new Set(result.data.result?.pending_operation_ids || []), total: (result.data.result?.pending_operation_ids || []).length, failed: 0 };
      const message = `${repaired} farmer Sheet repair${repaired === 1 ? '' : 's'} queued${skipped ? `; ${skipped} invalid deposit${skipped === 1 ? '' : 's'} skipped` : ''}.`;
      window.PortalAppShell?.showToast?.(message, 'success'); feedback(message, 'success'); await load({silent:true});
    } catch (error) { feedback(error.message, 'error'); window.PortalAppShell?.showToast?.(error.message, 'error'); } finally { setLoading(button, false); }
  }
  async function saveMapping() {
    const button = node('farmup-save-mapping');
    const decisions = [...document.querySelectorAll('.farmup-mapping-row')].map(row => ({source_id:row.dataset.sourceId, target_field:row.querySelector('.farmup-mapping-target')?.value || ''}));
    const chosen = decisions.map(i => i.target_field).filter(Boolean); if (new Set(chosen).size !== chosen.length) { feedback('Each system field can be matched to only one CSV column.', 'error'); return; }
    if ((active.rows || []).length && !window.confirm('Applying this mapping will reparse the original CSV and discard current edits and selections. Continue?')) return;
    setLoading(button, true, 'Applying');
    try { const result = await api.postJson(`/farmup/${encodeURIComponent(active.id)}/mapping/`, {revision_token:active.revision_token, mapping:decisions}, tg); if (!result.ok || !result.data?.ok) throw new Error(result.data?.error || 'Column mapping could not be applied.'); clearDirtyProtection(); active = result.data.batch; active.validation = []; mappingOpen = false; commitRequestKey = ''; await renderEditor(); await load({silent:true}); feedback('Column mapping applied. Review the parsed rows.', 'success'); } catch (error) { feedback(error.message, 'error'); } finally { setLoading(button, false); }
  }
  async function attemptDrive(operationId, silent = false) { if (!operationId) throw new Error('The Drive archive operation is unavailable.'); const result = await api.postJson('/farmup/archive-attempt/', {operation_id:operationId}, tg); if (!result.ok || !result.data?.ok) { if (silent) return; throw new Error(result.data?.error || 'Drive archive retry failed.'); } if (!silent) feedback('FarmUp source archived to Drive.', 'success'); await load({silent:true}); }
  function moveCarousel(delta) { const track = node('farmup-carousel')?.querySelector('.farmup-carousel-track'); if (!track) return; carouselIndex = Math.max(0, Math.min(track.children.length - 1, carouselIndex + delta)); track.children[carouselIndex]?.scrollIntoView({behavior:'smooth', inline:'start', block:'nearest'}); }
  function finishPicker() { pickerActive = false; utils.setCloseProtection?.('portal-farmup-file-picker', false); }

  document.addEventListener('submit', event => { if (event.target.matches('#portal-farmup-upload')) { event.preventDefault(); return upload(event.target).catch(error => { feedback(error.message, 'error'); window.PortalAppShell?.showToast?.(error.message, 'error'); }); } if (event.target.matches('#farmup-version-upload')) { event.preventDefault(); return uploadVersion(event.target).catch(error => { feedback(error.message, 'error'); window.PortalAppShell?.showToast?.(error.message, 'error'); }); } });
  document.addEventListener('input', event => { if (event.target.id !== 'farmup-search') return; search = event.target.value; gridApi?.setGridOption('quickFilterText', search); carouselIndex = 0; if (reviewMode === 'carousel') renderCarousel(); updateSummary(); });
  document.addEventListener('click', event => {
    const open = event.target.closest('.farmup-open'); if (open) return openBatch(open.dataset.batchId).catch(error => feedback(error.message, 'error'));
    if (event.target.closest('#portal-farmup-refresh')) return load().catch(error => feedback(error.message, 'error'));
    if (event.target.closest('#farmup-close')) { if ((active?.rows || []).some(row => editedFields(row).length || rowWorkflowChanged(row)) && !window.confirm('Discard uncommitted FarmUp edits and selections?')) return; clearDirtyProtection(); gridApi?.destroy(); gridApi = null; node('portal-farmup-review').hidden = true; active = null; return; }
    const mode = event.target.closest('[data-farmup-mode]'); if (mode) return setReviewMode(mode.dataset.farmupMode);
    if (event.target.closest('#farmup-review-filter')) { needsReviewOnly = !needsReviewOnly; gridApi?.onFilterChanged(); event.target.closest('button').classList.toggle('active', needsReviewOnly); event.target.closest('button').setAttribute('aria-pressed', String(needsReviewOnly)); carouselIndex = 0; if (reviewMode === 'carousel') renderCarousel(); updateSummary(); return; }
    if (event.target.closest('#farmup-select-all')) { gridApi?.forEachNodeAfterFilter(n => { if (rowSelectable(n.data)) { n.data.disposition = 'commit_now'; n.data.approved = true; n.setSelected(true); } }); updateSummary(); return; }
    if (event.target.closest('#farmup-clear-all')) { gridApi?.forEachNode(n => { if (!['committed','already_committed','excluded'].includes(n.data.disposition)) { n.data.disposition = 'hold'; n.data.approved = false; n.setSelected(false); } }); updateSummary(); return; }
    if (event.target.closest('#farmup-exclude-selected')) { gridApi?.getSelectedNodes().forEach(n => { n.data.disposition = 'exclude'; n.data.approved = false; n.setSelected(false); }); gridApi?.redrawRows(); updateSummary(); return; }
    if (event.target.closest('#farmup-restore-excluded')) { gridApi?.forEachNode(n => { if (n.data.disposition === 'exclude') n.data.disposition = 'hold'; }); gridApi?.redrawRows(); updateSummary(); return; }
    if (event.target.closest('#farmup-carousel-prev')) return moveCarousel(-1); if (event.target.closest('#farmup-carousel-next')) return moveCarousel(1);
    if (event.target.closest('#farmup-review-mapping')) { mappingOpen = true; renderMapping(); return; } if (event.target.closest('#farmup-cancel-mapping')) { mappingOpen = false; renderMapping(); return; }
    if (event.target.closest('#farmup-save-mapping')) return saveMapping(); if (event.target.closest('#farmup-commit')) return commit(); if (event.target.closest('#farmup-repair')) return repairSheet();
    const retry = event.target.closest('.farmup-drive-retry'); if (retry) { const batch = batches.find(item => item.id === retry.dataset.batchId); return attemptDrive(batch?.archive_operation_id).catch(error => feedback(error.message, 'error')); }
    const archive = event.target.closest('.farmup-archive'); if (archive && window.confirm('Archive this batch from the FarmUp working list? Retained evidence will remain available.')) api.postJson(`/farmup/${encodeURIComponent(archive.dataset.batchId)}/archive/`, {}, tg).then(result => { if (!result.ok) throw new Error(result.data?.error); return load({silent:true}); }).catch(error => feedback(error.message, 'error'));
  });
  document.addEventListener('click', event => { if (!event.target.matches('[data-farmup-file]')) return; pickerActive = true; pickerHadSelection = false; utils.setCloseProtection?.('portal-farmup-file-picker', true); }, true);
  document.addEventListener('cancel', event => { if (event.target.matches('[data-farmup-file]')) finishPicker(); }, true);
  document.addEventListener('change', event => { if (!event.target.matches('[data-farmup-file]')) return; pickerHadSelection = Boolean(event.target.files?.length); finishPicker(); if (!pickerHadSelection) return; try { validateFarmupFile(event.target); utils.setCloseProtection?.('portal-farmup-file-selected', true); } catch (error) { utils.setCloseProtection?.('portal-farmup-file-selected', false); feedback(error.message, 'error'); } }, true);
  function pickerReturned() { if (pickerActive) setTimeout(() => { if (pickerActive && !pickerHadSelection) finishPicker(); }, 80); if (document.visibilityState === 'visible') tg?.disableVerticalSwipes?.(); }
  window.addEventListener('focus', pickerReturned); document.addEventListener('visibilitychange', pickerReturned);
  function onViewportChange() { layoutGrid(); const editor = document.querySelector('.farmup-grid .ag-cell-inline-editing input, .farmup-grid .ag-cell-inline-editing select, .farmup-carousel :focus'); editor?.scrollIntoView?.({block:'center', inline:'nearest'}); }
  window.visualViewport?.addEventListener('resize', onViewportChange);
  window.addEventListener('resize', layoutGrid);
  window.addEventListener('orientationchange', layoutGrid);
  tg?.onEvent?.('viewportChanged', layoutGrid);
  window.addEventListener('portal:publication-updated', event => {
    if (!repairProgress || !repairProgress.pending.has(String(event.detail?.operationId || ''))) return;
    if (event.detail?.needsAttention) { repairProgress.pending.delete(String(event.detail.operationId)); repairProgress.failed += 1; }
    else if (event.detail?.ok && !event.detail?.retryable) repairProgress.pending.delete(String(event.detail.operationId));
    const completed = repairProgress.total - repairProgress.pending.size - repairProgress.failed;
    const message = `${completed} Sheet repair operation${completed === 1 ? '' : 's'} synchronized · ${repairProgress.pending.size} remaining · ${repairProgress.failed} failed.`;
    feedback(message, repairProgress.failed ? 'error' : 'success');
    if (!repairProgress.pending.size) { window.PortalAppShell?.showToast?.(message, repairProgress.failed ? 'error' : 'success'); load({silent:true}).catch(() => {}); }
  });
  window.PortalMiniAppFarmUp = {load};
})();
