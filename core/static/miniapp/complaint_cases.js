(function () {
  'use strict';

  const apiClient = window.ComplaintCasesMiniAppApi;
  const utils = window.MiniAppUtils || {};
  const telegram = utils.initTelegram ? utils.initTelegram() : window.Telegram?.WebApp;
  const $ = id => document.getElementById(id);
  const state = {
    groupId: document.body.dataset.groupId || '',
    initData: telegram?.initData || '',
    status: 'pending', query: '', page: 1, pages: 1,
    capabilities: new Set(), currentCase: null, submitting: false,
    debounce: null, suggestionTimer: null, suggestionSequence: 0,
    suggestedCategory: null, latitude: '', longitude: '',
    workspace: 'queue', returnWorkspace: 'queue', globalLoaded: false,
    globalOverview: null, globalPage: 1, globalPages: 1, globalStartIndex: 1,
    evidence: { create: [], resolve: [] },
    categoryDescriptions: new Map(),
    evidenceLimits: { max_files: 10, max_file_size_mb: 10, max_total_upload_mb: 30 },
    cameraStream: null, cameraTarget: '',
    mediaViewerObjectUrl: '', mediaViewerRestoreFocus: null,
  };

  function requestId(prefix) {
    return utils.createRequestId
      ? utils.createRequestId(prefix || 'complaint')
      : `${prefix || 'complaint'}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }
  function can(key) { return state.capabilities.has(key); }
  function notify(message, error) {
    const node = $('toast');
    node.textContent = message || '';
    node.classList.toggle('error', !!error);
    node.classList.add('visible');
    clearTimeout(node._timer);
    node._timer = setTimeout(() => node.classList.remove('visible'), 4000);
  }
  function json(path, payload) {
    return apiClient.postJson(path, Object.assign({ group_id: state.groupId }, payload || {}), state.initData, utils);
  }
  function form(path, data, groupId) {
    return apiClient.postForm(path, data, state.initData, groupId || state.groupId, utils);
  }
  function textNode(tag, value, className) {
    const node = document.createElement(tag);
    node.textContent = value == null ? '' : String(value);
    if (className) node.className = className;
    return node;
  }
  function loadingNode(label) {
    const node = document.createElement('span'); node.className = 'inline-loading'; node.setAttribute('role', 'status');
    const spinner = document.createElement('span'); spinner.className = 'spinner-inline'; spinner.setAttribute('aria-hidden', 'true');
    node.append(spinner, textNode('span', label || 'Loading...')); return node;
  }
  function setActionLoading(button, loading, label) {
    if (utils.setButtonLoading) utils.setButtonLoading(button, loading, label);
    else if (button) button.disabled = !!loading;
  }
  function statusStack(item) {
    const stack = document.createElement('div');
    stack.className = 'status-stack';
    stack.appendChild(textNode('span', item.status, `status-pill ${item.status === 'Resolved' ? 'resolved' : ''}`));
    if (item.needs_details) stack.appendChild(textNode('span', 'Needs details', 'needs-details-pill'));
    return stack;
  }

  function setView(name) {
    if (!$('cameraOverlay').hidden) closeCamera();
    if (!$('mediaViewerOverlay').hidden) closeMediaViewer();
    ['queueView', 'globalView', 'createView', 'detailView'].forEach(id => { $(id).hidden = id !== name; });
    $('loadingState').hidden = true;
    const workspaceView = name === 'queueView' || name === 'globalView';
    $('workspaceTabs').hidden = !workspaceView;
    if (workspaceView) {
      state.workspace = name === 'globalView' ? 'global' : 'queue';
      $('queueWorkspaceBtn').classList.toggle('active', state.workspace === 'queue');
      $('globalWorkspaceBtn').classList.toggle('active', state.workspace === 'global');
    }
    telegram?.BackButton?.[workspaceView ? 'hide' : 'show']();
    window.scrollTo({ top: 0, behavior: 'instant' });
  }

  function selectOptions(select, values, placeholder) {
    select.replaceChildren(textNode('option', placeholder));
    select.firstElementChild.value = '';
    (values || []).forEach(item => {
      const option = textNode('option', typeof item === 'string' ? item : item.label);
      option.value = typeof item === 'string' ? item : item.value;
      select.appendChild(option);
    });
  }
  function updateCounts(counts) {
    $('pendingCount').textContent = counts.pending || 0;
    $('resolvedCount').textContent = counts.resolved || 0;
    $('totalCount').textContent = counts.total || 0;
  }

  async function bootstrap() {
    try {
      const response = await json('bootstrap/');
      const data = response.data;
      state.capabilities = new Set(data.actor.capabilities || []);
      state.evidenceLimits = Object.assign(state.evidenceLimits, data.evidence_limits || {});
      $('actorLine').textContent = `${data.actor.name} · ${data.actor.role}`;
      updateCounts(data.counts || {});
      $('newCaseBtn').hidden = !can('complaint.case.create');
      $('exportAllBtn').hidden = !can('complaint.case.export');
      selectOptions($('createCaseForm').elements.branch_region, data.branches, 'Select branch');
      selectOptions($('createCaseForm').elements.complaint_category, data.categories, 'Select complaint type');
      selectOptions($('completeDetailsForm').elements.complaint_category, data.categories, 'Select complaint type');
      state.categoryDescriptions = new Map((data.category_catalogue || []).map(item => [item.label, item.description]));
      updateEvidenceHints();
      setView('queueView');
      await loadCases();
    } catch (error) {
      $('loadingState').textContent = error.message || 'Biogas Complaints could not be opened.';
      notify(error.message, true);
    }
  }

  async function loadCases() {
    $('caseList').replaceChildren(loadingNode('Loading complaints...'));
    try {
      const response = await json('cases/', { status: state.status, query: state.query, page: state.page });
      const pagination = response.pagination || { page: 1, pages: 1, total: response.cases.length };
      state.page = pagination.page; state.pages = pagination.pages;
      $('queueResultCount').textContent = `${pagination.total} complaint${pagination.total === 1 ? '' : 's'}`;
      renderCases(response.cases || [], response.start_index || 0);
      $('queuePagination').hidden = pagination.pages <= 1;
      $('queuePageLabel').textContent = `Page ${pagination.page} of ${pagination.pages}`;
      $('queuePreviousBtn').disabled = pagination.page <= 1;
      $('queueNextBtn').disabled = pagination.page >= pagination.pages;
    } catch (error) {
      $('caseList').replaceChildren(textNode('p', 'Complaints could not be loaded.', 'empty'));
      notify(error.message, true);
    }
  }

  function renderCases(cases, start) {
    const list = $('caseList'); list.replaceChildren();
    if (!cases.length) { list.appendChild(textNode('p', 'No complaints match this view.', 'empty')); return; }
    cases.forEach((item, index) => {
      const button = document.createElement('button');
      button.type = 'button'; button.className = 'case-row'; button.dataset.caseId = item.case_id;
      const body = document.createElement('div');
      body.append(
        textNode('p', `#${start + index} · ${item.case_id}`, 'case-reference'),
        textNode('h2', item.customer_name || 'Unnamed customer'),
        textNode('p', `${item.customer_phone || item.customer_id || 'Customer details required'} · ${item.category || 'Other Complaint'} · ${item.branch || 'Branch not provided'}`, 'case-subtitle'),
        textNode('p', item.age_label || '', 'case-age'),
      );
      button.append(body, statusStack(item));
      button.addEventListener('click', () => openCase(item.case_id));
      list.appendChild(button);
    });
  }

  async function openCase(caseId) {
    const source = document.querySelector(`[data-case-id="${CSS.escape(caseId)}"]`);
    setActionLoading(source, true, 'Opening');
    try {
      const response = await json(`cases/${encodeURIComponent(caseId)}/`);
      response.case.group_id = state.groupId; response.case.global_read = false;
      state.returnWorkspace = 'queue'; renderDetail(response.case); setView('detailView');
    } catch (error) { notify(error.message, true); }
    finally { setActionLoading(source, false); }
  }
  async function openGlobalCase(caseUuid) {
    try {
      const response = await json(`global/cases/${encodeURIComponent(caseUuid)}/`);
      response.case.global_read = true; state.returnWorkspace = 'global';
      renderDetail(response.case); setView('detailView');
    } catch (error) { notify(error.message, true); }
  }
  function syncLabel(value) {
    return ({ success: 'Synced', pending: 'Pending', failed: 'Failed', not_required: 'Django only', suspended: 'Suspended — Sheet projection disabled' })[value] || value || 'Not recorded';
  }

  function renderDetail(item, preserveDraft) {
    state.currentCase = item;
    $('detailCaseId').textContent = item.case_id;
    $('detailName').textContent = item.customer_name || 'Unnamed customer';
    $('detailGroup').textContent = item.group_label || '';
    $('detailStatus').textContent = item.status;
    $('detailStatus').className = `status-pill ${item.status === 'Resolved' ? 'resolved' : ''}`;
    $('detailNeedsDetails').hidden = !item.needs_details;
    const ids = $('detailIdentifiers'); ids.replaceChildren();
    [item.customer_phone, item.customer_id].filter(Boolean).forEach(value => ids.appendChild(textNode('span', value)));
    $('detailDescription').textContent = item.description || 'No description recorded.';
    const meta = $('detailMeta'); meta.replaceChildren();
    [item.category, item.branch, item.reported_at].filter(Boolean).forEach(value => meta.appendChild(textNode('span', value)));
    const source = item.source_attribution || {};
    $('detailSource').textContent = item.global_read
      ? 'Organization-wide operational view'
      : (source.type === 'batch' ? `${source.label} · ${source.actor} · ${source.created_at}` : (source.label || 'Source unavailable'));
    $('detailSync').textContent = `Sheet: ${syncLabel(item.sync_status)}`;
    renderHistory(item); renderEvidence(item.evidence || []); renderActivity(item.updates || []);
    $('evidencePanel').hidden = !!item.global_read; $('activityPanel').hidden = !!item.global_read;
    const actions = item.global_read ? (item.actions || {}) : {
      close: can('complaint.case.close'), reopen: can('complaint.case.reopen'),
      complete_details: can('complaint.case.details.complete'), sync_retry: can('complaint.case.sync.retry'),
    };
    $('completeDetailsForm').hidden = !item.needs_details || !actions.complete_details;
    $('resolveForm').hidden = item.status !== 'Pending' || !actions.close;
    $('reopenForm').hidden = item.status !== 'Resolved' || !actions.reopen;
    $('retrySyncBtn').hidden = !actions.sync_retry || !['pending', 'failed'].includes(item.sync_status) || item.sheet_projection_enabled === false;
    $('detailBackBtn').textContent = state.returnWorkspace === 'global' ? '← All Complaints' : '← Complaint Queue';
    if (!preserveDraft) {
      $('completeDetailsForm').reset(); $('resolveForm').reset(); $('reopenForm').reset();
      clearEvidence('resolve'); $('conflictPanel').hidden = true;
      const complete = $('completeDetailsForm').elements;
      complete.customer_phone.value = item.customer_phone || '';
      complete.customer_phone.readOnly = !!item.customer_phone;
      complete.customer_id.value = item.customer_id || '';
      complete.customer_id.readOnly = !!item.customer_id && /^\d+$/.test(item.customer_id);
      complete.complaint_category.value = item.category || '';
    }
  }

  function renderHistory(item) {
    const resolution = item.latest_resolution || (item.resolution_details ? { note: item.resolution_details, updated_by: '', created_at: item.resolved_at || '' } : null);
    $('previousResolution').hidden = !resolution;
    if (!resolution) return;
    $('previousResolutionText').textContent = resolution.note || 'No resolution note recorded.';
    $('previousResolutionMeta').textContent = [resolution.updated_by, resolution.created_at].filter(Boolean).join(' · ');
    const reopened = item.latest_reopen; $('previousReopen').hidden = !reopened;
    if (reopened) {
      $('previousReopenText').textContent = reopened.note || '';
      $('previousReopenMeta').textContent = `${reopened.updated_by || 'Staff'} · ${reopened.created_at || ''}`;
    }
  }
  function renderEvidence(items) {
    const node = $('evidenceList'); node.replaceChildren();
    if (!items.length) { node.appendChild(textNode('p', 'No supporting files attached.', 'muted')); return; }
    items.forEach(item => {
      const row = document.createElement('div'); row.className = 'item evidence-item'; row.appendChild(textNode('strong', item.name));
      if (item.preview_url) {
        const button = textNode('button', 'View in app', 'media-link'); button.type = 'button';
        button.dataset.previewUrl = item.preview_url; button.dataset.mimeType = item.mime_type || '';
        button.dataset.name = item.name || 'Complaint evidence'; button.addEventListener('click', openPersistedEvidence);
        row.appendChild(button);
      } else if (item.status === 'success') {
        row.appendChild(textNode('small', 'In-app preview unavailable for this older file.', 'muted'));
      }
      node.appendChild(row);
    });
  }
  function mediaHeaders(accessRequestId) {
    return { 'X-Telegram-Init-Data': state.initData, 'X-Request-ID': accessRequestId || requestId('complaint-evidence') };
  }
  function closeMediaViewer() {
    $('mediaViewerOverlay').hidden = true; $('mediaViewerContent').replaceChildren();
    window.SecureMediaViewer?.revoke(state.mediaViewerObjectUrl); state.mediaViewerObjectUrl = '';
    const restore = state.mediaViewerRestoreFocus; state.mediaViewerRestoreFocus = null; restore?.focus?.();
  }
  function showMediaViewer(name, restoreFocus) {
    closeMediaViewer(); state.mediaViewerRestoreFocus = restoreFocus || null;
    $('mediaViewerTitle').textContent = 'File Preview'; $('mediaViewerSub').textContent = name || '';
    $('mediaViewerContent').replaceChildren(loadingNode('Loading secure file...')); $('mediaViewerOverlay').hidden = false;
  }
  async function openPersistedEvidence(event) {
    const button = event.currentTarget; showMediaViewer(button.dataset.name, button);
    try {
      const viewer = window.SecureMediaViewer;
      if (!viewer) throw new Error('The secure evidence viewer is unavailable. Refresh and retry.');
      const groupId = state.currentCase.group_id || state.groupId; const accessRequestId = requestId('complaint-evidence');
      const blob = await viewer.fetchAuthorizedBlob(button.dataset.previewUrl, {
        method: 'POST',
        headers: { ...mediaHeaders(accessRequestId), 'Content-Type': 'application/json', 'Idempotency-Key': accessRequestId },
        body: JSON.stringify({ group_id: groupId, client_request_id: accessRequestId }),
      });
      state.mediaViewerObjectUrl = viewer.renderBlob($('mediaViewerContent'), blob, {
        mimeType: button.dataset.mimeType, name: button.dataset.name,
      });
    } catch (error) {
      $('mediaViewerContent').replaceChildren(textNode('p', `${error.message || 'The evidence could not be opened.'} Close this view and retry.`, 'media-viewer-error'));
    }
  }
  function renderActivity(items) {
    const node = $('activityList'); node.replaceChildren();
    if (!items.length) { node.appendChild(textNode('p', 'No activity recorded.', 'muted')); return; }
    items.forEach(item => {
      const row = document.createElement('div'); row.className = 'item';
      row.append(textNode('strong', `${item.status || 'Update'} · ${item.updated_by || 'Staff'}`), textNode('p', item.note || ''), textNode('small', item.created_at || '', 'muted'));
      node.appendChild(row);
    });
  }

  function showConflict(error) {
    const current = error.payload?.current_case;
    if (!current) { notify(error.message, true); return; }
    const draft = $('resolveForm').elements.resolution_text.value || $('reopenForm').elements.reason.value || (current.needs_details ? 'Your entered complaint details remain in the form.' : '');
    current.group_id = state.currentCase.group_id; current.global_read = state.currentCase.global_read;
    state.currentCase = current; $('conflictMessage').textContent = error.message;
    const resolution = current.latest_resolution;
    $('conflictWinningNote').textContent = resolution ? `${resolution.note}\n— ${resolution.updated_by}, ${resolution.created_at}` : 'Review the latest complaint before trying again.';
    $('conflictDraft').textContent = draft || 'No draft text was entered.';
    $('copyConflictDraftBtn').disabled = !draft || draft.startsWith('Your entered complaint details');
    renderDetail(current, true); $('conflictPanel').hidden = false;
    $('conflictPanel').scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
  async function copyConflictDraft() {
    const draft = $('conflictDraft').textContent;
    if (!draft || $('copyConflictDraftBtn').disabled) return;
    try { await navigator.clipboard.writeText(draft); notify('Your draft was copied.'); }
    catch (_) { notify('Copy was unavailable. Select and copy the retained draft above.', true); }
  }

  function appendEvidence(data, target) {
    state.evidence[target].forEach(item => data.append('evidence', item.file, item.file.name));
  }
  async function submitTransition(event, action) {
    event.preventDefault(); if (!state.currentCase || state.submitting) return;
    const formNode = event.currentTarget; const data = new FormData(formNode);
    const targetGroup = state.currentCase.group_id || state.groupId;
    data.set('expected_revision', state.currentCase.revision);
    data.set('client_request_id', requestId('complaint-transition'));
    if (action === 'resolve') appendEvidence(data, 'resolve');
    const button = formNode.querySelector('button[type="submit"]');
    state.submitting = true; setActionLoading(button, true, action === 'resolve' ? 'Resolving' : 'Reopening'); utils.setCloseProtection?.('complaint-operation', true);
    try {
      const response = await form(`cases/${encodeURIComponent(state.currentCase.case_id)}/${action}/`, data, targetGroup);
      response.case.group_id = targetGroup; notify(response.message); clearEvidence('resolve');
      utils.setCloseProtection?.('complaint-transition-draft', false); await refreshCounts();
      if (state.returnWorkspace === 'global') { await refreshGlobal(); await openGlobalCase(response.case.id); }
      else { response.case.global_read = false; renderDetail(response.case); }
    } catch (error) { if (error.status === 409) showConflict(error); else notify(error.message, true); }
    finally { state.submitting = false; setActionLoading(button, false); utils.setCloseProtection?.('complaint-operation', false); }
  }

  async function submitCompleteDetails(event) {
    event.preventDefault(); if (!state.currentCase || state.submitting) return;
    const formNode = event.currentTarget; const data = new FormData(formNode);
    const idError = validateCustomerId(formNode.elements.customer_id);
    if (idError) return notify(idError, true);
    const targetGroup = state.currentCase.group_id || state.groupId;
    data.set('expected_revision', state.currentCase.revision);
    data.set('client_request_id', requestId('complaint-details'));
    const button = formNode.querySelector('button[type="submit"]');
    state.submitting = true; setActionLoading(button, true, 'Saving details'); utils.setCloseProtection?.('complaint-operation', true);
    try {
      const response = await form(`cases/${encodeURIComponent(state.currentCase.case_id)}/complete-details/`, data, targetGroup);
      response.case.group_id = targetGroup; notify(response.message);
      utils.setCloseProtection?.('complaint-transition-draft', false); await refreshCounts();
      if (state.returnWorkspace === 'global') { await refreshGlobal(); await openGlobalCase(response.case.id); }
      else { response.case.global_read = false; renderDetail(response.case); }
    } catch (error) { if (error.status === 409) showConflict(error); else notify(error.message, true); }
    finally { state.submitting = false; setActionLoading(button, false); utils.setCloseProtection?.('complaint-operation', false); }
  }

  async function refreshCounts() {
    try { const response = await json('bootstrap/'); updateCounts(response.data.counts || {}); }
    catch (_) { /* Keep the last confirmed counts. */ }
  }
  async function submitCreate(event) {
    event.preventDefault(); if (state.submitting) return;
    const formNode = event.currentTarget; const data = new FormData(formNode);
    const idError = validateCustomerId(formNode.elements.customer_id);
    if (idError) return notify(idError, true);
    data.set('client_request_id', requestId('complaint-create')); appendEvidence(data, 'create');
    if (state.latitude) { data.set('latitude', state.latitude); data.set('longitude', state.longitude); }
    const button = $('createSaveBtn'); state.submitting = true; setActionLoading(button, true, 'Creating');
    utils.setCloseProtection?.('complaint-operation', true); $('createSaveState').textContent = 'Saving…';
    try {
      const response = await form('cases/create/', data); formNode.reset(); clearEvidence('create');
      state.latitude = ''; state.longitude = ''; hideSuggestion();
      utils.setCloseProtection?.('complaint-create-draft', false); $('createSaveState').textContent = 'Saved';
      notify(response.message); await refreshCounts(); state.returnWorkspace = 'queue';
      response.case.group_id = state.groupId; response.case.global_read = false;
      renderDetail(response.case); setView('detailView');
    } catch (error) { $('createSaveState').textContent = 'Not Saved'; notify(error.message, true); }
    finally { state.submitting = false; setActionLoading(button, false); utils.setCloseProtection?.('complaint-operation', false); }
  }
  function validateCustomerId(input) {
    const value = String(input?.value || '').trim();
    if (value && !/^\d+$/.test(value)) {
      input?.setCustomValidity?.('Customer ID must contain numbers only.'); input?.reportValidity?.();
      return 'Customer ID must contain numbers only.';
    }
    input?.setCustomValidity?.(''); return '';
  }
  function captureLocation() {
    if (!navigator.geolocation) return notify('Location is unavailable on this device.', true);
    $('captureState').textContent = 'Capturing…';
    navigator.geolocation.getCurrentPosition(position => {
      state.latitude = position.coords.latitude.toFixed(6); state.longitude = position.coords.longitude.toFixed(6);
      $('captureState').textContent = 'Location captured';
    }, () => { $('captureState').textContent = 'Location not captured'; notify('Location permission was not available.', true); }, { enableHighAccuracy: true, timeout: 12000 });
  }

  function updateEvidenceHints() {
    const limits = state.evidenceLimits;
    const text = `Up to ${limits.max_files} files · ${limits.max_file_size_mb} MB each · ${limits.max_total_upload_mb} MB total`;
    $('createEvidenceHint').textContent = text; $('resolveEvidenceHint').textContent = text;
  }
  function acceptedEvidence(file) {
    const name = String(file.name || '').toLowerCase();
    return ['image/jpeg', 'image/png', 'image/webp', 'application/pdf'].includes(file.type)
      || name.endsWith('.jpg') || name.endsWith('.jpeg') || name.endsWith('.png') || name.endsWith('.webp') || name.endsWith('.pdf');
  }
  function addFiles(target, files) {
    let added = false;
    for (const file of Array.from(files || [])) {
      const queued = state.evidence[target];
      const total = queued.reduce((sum, item) => sum + item.file.size, 0);
      if (!acceptedEvidence(file)) { notify(`${file.name || 'That file'} is not a supported evidence type.`, true); continue; }
      if (file.size > state.evidenceLimits.max_file_size_mb * 1024 * 1024) { notify(`${file.name} exceeds the ${state.evidenceLimits.max_file_size_mb} MB file limit.`, true); continue; }
      if (queued.length >= state.evidenceLimits.max_files) { notify(`You can attach up to ${state.evidenceLimits.max_files} files.`, true); continue; }
      if (total + file.size > state.evidenceLimits.max_total_upload_mb * 1024 * 1024) { notify(`These files would exceed the ${state.evidenceLimits.max_total_upload_mb} MB total limit.`, true); continue; }
      queued.push({ id: requestId('evidence-file'), file, preview: URL.createObjectURL(file) });
      added = true;
    }
    renderSelectedEvidence(target);
    if (added) utils.setCloseProtection?.(`complaint-${target}-evidence`, true);
    return added;
  }
  function removeEvidence(target, id) {
    const index = state.evidence[target].findIndex(item => item.id === id);
    if (index < 0) return;
    const [removed] = state.evidence[target].splice(index, 1);
    if (removed.preview) URL.revokeObjectURL(removed.preview);
    renderSelectedEvidence(target);
    if (!state.evidence[target].length) utils.setCloseProtection?.(`complaint-${target}-evidence`, false);
  }
  function clearEvidence(target) {
    state.evidence[target].forEach(item => { if (item.preview) URL.revokeObjectURL(item.preview); });
    state.evidence[target] = []; renderSelectedEvidence(target);
    utils.setCloseProtection?.(`complaint-${target}-evidence`, false);
  }
  function renderSelectedEvidence(target) {
    const list = $(`${target}SelectedEvidence`); list.replaceChildren();
    state.evidence[target].forEach(item => {
      const row = document.createElement('li');
      if (item.file.type.startsWith('image/')) { const image = document.createElement('img'); image.src = item.preview; image.alt = ''; row.appendChild(image); }
      else row.appendChild(textNode('span', item.file.name.split('.').pop()?.toUpperCase() || 'FILE', 'file-icon'));
      row.appendChild(textNode('span', item.file.name, 'file-name'));
      const view = textNode('button', 'View', 'view-file'); view.type = 'button';
      view.addEventListener('click', () => openSelectedEvidence(item, view)); row.appendChild(view);
      const remove = textNode('button', 'Remove', 'remove-file'); remove.type = 'button';
      remove.addEventListener('click', () => removeEvidence(target, item.id)); row.appendChild(remove); list.appendChild(row);
    });
  }
  function openSelectedEvidence(item, button) {
    const viewer = window.SecureMediaViewer; showMediaViewer(item.file.name, button);
    if (!viewer) {
      $('mediaViewerContent').replaceChildren(textNode('p', 'The secure evidence viewer is unavailable. Refresh and retry.', 'media-viewer-error'));
      return;
    }
    state.mediaViewerObjectUrl = viewer.renderBlob($('mediaViewerContent'), item.file, { mimeType: item.file.type, name: item.file.name });
  }

  function stopCamera() {
    state.cameraStream?.getTracks?.().forEach(track => track.stop());
    state.cameraStream = null;
    if ($('cameraVideo')) $('cameraVideo').srcObject = null;
  }
  function closeCamera(options) {
    stopCamera(); $('cameraOverlay').hidden = true; document.body.classList.remove('camera-open');
    const focusTarget = options?.focusTarget || (state.cameraTarget ? document.querySelector(`[data-camera-target="${state.cameraTarget}"]`) : null);
    state.cameraTarget = ''; if (options?.restoreFocus !== false) focusTarget?.focus?.();
  }
  async function openCamera(target) {
    if (!navigator.mediaDevices?.getUserMedia) return notify('This Telegram WebView cannot open the camera directly. Use Upload Files instead.', true);
    state.cameraTarget = target; $('cameraOverlay').hidden = false; document.body.classList.add('camera-open');
    try {
      state.cameraStream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: 'environment' } }, audio: false });
      $('cameraVideo').srcObject = state.cameraStream; await $('cameraVideo').play(); $('cameraCaptureBtn').focus();
    } catch (_) { closeCamera({ restoreFocus: true }); notify('Camera access was unavailable. Allow permission or use Upload Files.', true); }
  }
  async function captureCameraPhoto() {
    const video = $('cameraVideo'); const button = $('cameraCaptureBtn');
    if (!video.videoWidth || !video.videoHeight) return notify('The camera is still starting. Try again.', true);
    button.disabled = true;
    const canvas = $('cameraCanvas'); const maximum = 2000;
    const scale = Math.min(1, maximum / Math.max(video.videoWidth, video.videoHeight));
    canvas.width = Math.max(1, Math.round(video.videoWidth * scale)); canvas.height = Math.max(1, Math.round(video.videoHeight * scale));
    canvas.getContext('2d')?.drawImage(video, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg', .88));
    button.disabled = false;
    if (!blob) return notify('The photo could not be captured. Try again.', true);
    const target = state.cameraTarget;
    const file = new File([blob], `complaint-evidence-${Date.now()}.jpg`, { type: 'image/jpeg' });
    if (addFiles(target, [file])) { closeCamera({ restoreFocus: false }); notify('Photo added. Submit the form when ready.'); }
  }

  function hideSuggestion() { state.suggestedCategory = null; $('categorySuggestion').hidden = true; $('categorySuggestion').classList.remove('checking', 'ambiguous'); }
  async function requestCategorySuggestion(description) {
    const sequence = ++state.suggestionSequence;
    const chip = $('categorySuggestion'); chip.hidden = false; chip.disabled = true; chip.className = 'category-suggestion checking'; chip.textContent = 'Checking category...';
    try {
      const response = await json('categories/suggest/', { description });
      if (sequence !== state.suggestionSequence) return;
      const result = response.data || {}; state.suggestedCategory = result.suggestion || null;
      chip.disabled = !result.suggestion; chip.className = 'category-suggestion';
      if (result.state === 'ambiguous') {
        chip.hidden = false; chip.disabled = true; chip.classList.add('ambiguous'); chip.textContent = 'Choose category';
      } else if (result.suggestion) {
        chip.hidden = false; chip.textContent = `Suggested: ${result.suggestion.label}`;
      } else hideSuggestion();
    } catch (_) { if (sequence === state.suggestionSequence) hideSuggestion(); }
  }
  function scheduleCategorySuggestion(event) {
    clearTimeout(state.suggestionTimer); const description = event.target.value.trim();
    if (description.length < 3) { hideSuggestion(); return; }
    state.suggestionTimer = setTimeout(() => requestCategorySuggestion(description), 450);
  }
  function updateCategoryGuidance() {
    const label = $('createCaseForm').elements.complaint_category.value.trim();
    $('categoryGuidance').textContent = state.categoryDescriptions.get(label) || 'What is the complaint about?';
  }

  function renderMetrics(metrics) {
    const labels = [['total', 'Total'], ['pending', 'Pending'], ['resolved', 'Resolved'], ['needs_details', 'Needs details']];
    const node = $('globalMetrics'); node.replaceChildren();
    labels.forEach(([key, label]) => {
      const card = document.createElement('div'); card.className = `metric-card ${key === 'needs_details' && metrics[key] ? 'attention' : ''}`;
      card.append(textNode('strong', metrics[key] || 0), textNode('span', label)); node.appendChild(card);
    });
  }
  function populateGlobalFilters(filters) {
    const formNode = $('globalFilters'); const selected = formNode.elements.category.value;
    selectOptions(formNode.elements.category, filters.categories || [], 'All complaint types');
    if (Array.from(formNode.elements.category.options).some(option => option.value === selected)) formNode.elements.category.value = selected;
  }
  async function loadGlobalOverview() {
    const response = await json('global/overview/'); state.globalOverview = response.data;
    renderMetrics(response.data.metrics); populateGlobalFilters(response.data.filters); state.globalLoaded = true; return response.data;
  }
  function globalFilterPayload() {
    const values = {}; for (const [key, value] of new FormData($('globalFilters')).entries()) if (value) values[key] = value; return values;
  }
  async function loadGlobalCases() {
    const rows = $('globalCaseRows'); rows.replaceChildren();
    const loading = document.createElement('tr'); const cell = document.createElement('td'); cell.colSpan = 13; cell.appendChild(loadingNode('Loading global register...')); loading.appendChild(cell); rows.appendChild(loading);
    try {
      const response = await json('global/cases/', { filters: globalFilterPayload(), page: state.globalPage });
      const pagination = response.pagination; state.globalPage = pagination.page; state.globalPages = pagination.pages; state.globalStartIndex = response.start_index || 1;
      $('globalResultCount').textContent = `${pagination.total} complaint${pagination.total === 1 ? '' : 's'} match the table filters`;
      renderGlobalRows(response.items || []); $('globalPagination').hidden = pagination.pages <= 1;
      $('globalPageLabel').textContent = `Page ${pagination.page} of ${pagination.pages}`;
      $('globalPreviousBtn').disabled = pagination.page <= 1; $('globalNextBtn').disabled = pagination.page >= pagination.pages;
    } catch (error) {
      rows.replaceChildren(); const row = document.createElement('tr'); const errorCell = textNode('td', 'The global register could not be loaded.');
      errorCell.colSpan = 13; row.appendChild(errorCell); rows.appendChild(row); notify(error.message, true);
    }
  }
  function renderGlobalRows(items) {
    const body = $('globalCaseRows'); body.replaceChildren();
    if (!items.length) { const row = document.createElement('tr'); const cell = textNode('td', 'No complaints match these filters.'); cell.colSpan = 13; row.appendChild(cell); body.appendChild(row); return; }
    items.forEach((item, index) => {
      const row = document.createElement('tr'); const open = textNode('button', item.case_id, 'row-button');
      open.type = 'button'; open.addEventListener('click', () => openGlobalCase(item.id));
      const numberCell = textNode('td', state.globalStartIndex + index, 'row-number-cell');
      const caseCell = document.createElement('td'); caseCell.appendChild(open); const statusCell = document.createElement('td'); statusCell.appendChild(statusStack(item));
      [numberCell, caseCell, textNode('td', item.customer_name), textNode('td', item.customer_phone), textNode('td', item.customer_id), textNode('td', item.branch), textNode('td', item.category), textNode('td', item.description), statusCell, textNode('td', item.reported_at), textNode('td', item.resolved_at), textNode('td', item.days_open), textNode('td', item.resolution_details)].forEach(tableCell => row.appendChild(tableCell));
      body.appendChild(row);
    });
  }
  async function openGlobalWorkspace() { setView('globalView'); try { if (!state.globalLoaded) await loadGlobalOverview(); await loadGlobalCases(); } catch (error) { notify(error.message, true); } }
  async function refreshGlobal() { await loadGlobalOverview(); await loadGlobalCases(); }

  async function prepareExport() {
    try {
      const overview = await loadGlobalOverview(); const count = overview.metrics.total || 0;
      $('exportConfirmText').textContent = `This exports all ${count} complaints across all complaint groups, not only your current filters. Continue?`;
      $('exportConfirm').hidden = false; $('cancelExportBtn').focus();
    } catch (error) { notify(error.message, true); }
  }
  function cancelExport() { $('exportConfirm').hidden = true; $('exportAllBtn').focus(); }
  async function confirmExport() {
    const button = $('confirmExportBtn'); setActionLoading(button, true, 'Exporting');
    try {
      const result = await apiClient.postBlob('global/export/', { group_id: state.groupId, confirm_all: true, client_request_id: requestId('complaint-export') }, state.initData, utils);
      const url = URL.createObjectURL(result.blob); const link = document.createElement('a');
      link.href = url; link.download = result.filename; document.body.appendChild(link); link.click(); link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 30000); $('exportConfirm').hidden = true; notify('The complete complaint register was exported.');
    } catch (error) { notify(error.message, true); }
    finally { setActionLoading(button, false); }
  }
  async function retrySync() {
    if (!state.currentCase) return; const button = $('retrySyncBtn'); setActionLoading(button, true, 'Retrying');
    const targetGroup = state.currentCase.group_id || state.groupId;
    try {
      const response = await json(`cases/${encodeURIComponent(state.currentCase.case_id)}/sync-retry/`, { group_id: targetGroup, client_request_id: requestId('complaint-sync') });
      notify(response.message);
      if (state.currentCase.global_read) { await refreshGlobal(); await openGlobalCase(state.currentCase.id); }
      else { response.case.group_id = targetGroup; response.case.global_read = false; renderDetail(response.case); }
    } catch (error) { notify(error.message, true); }
    finally { setActionLoading(button, false); }
  }
  function returnPrevious() { if (state.returnWorkspace === 'global') { setView('globalView'); loadGlobalCases(); } else { setView('queueView'); loadCases(); } }

  document.querySelectorAll('[data-status]').forEach(button => button.addEventListener('click', () => {
    state.status = button.dataset.status; state.page = 1;
    document.querySelectorAll('[data-status]').forEach(item => item.classList.toggle('active', item === button)); loadCases();
  }));
  $('caseSearch').addEventListener('input', event => { state.query = event.target.value; state.page = 1; clearTimeout(state.debounce); state.debounce = setTimeout(loadCases, state.query ? 250 : 0); });
  $('queuePreviousBtn').addEventListener('click', () => { if (state.page > 1) { state.page -= 1; loadCases(); } });
  $('queueNextBtn').addEventListener('click', () => { if (state.page < state.pages) { state.page += 1; loadCases(); } });
  $('globalPreviousBtn').addEventListener('click', () => { if (state.globalPage > 1) { state.globalPage -= 1; loadGlobalCases(); } });
  $('globalNextBtn').addEventListener('click', () => { if (state.globalPage < state.globalPages) { state.globalPage += 1; loadGlobalCases(); } });
  $('queueWorkspaceBtn').addEventListener('click', () => { setView('queueView'); loadCases(); });
  $('globalWorkspaceBtn').addEventListener('click', openGlobalWorkspace);
  $('globalFilters').addEventListener('submit', event => { event.preventDefault(); state.globalPage = 1; loadGlobalCases(); });
  $('clearGlobalFiltersBtn').addEventListener('click', () => { $('globalFilters').reset(); state.globalPage = 1; loadGlobalCases(); });
  $('exportAllBtn').addEventListener('click', prepareExport); $('cancelExportBtn').addEventListener('click', cancelExport); $('confirmExportBtn').addEventListener('click', confirmExport);
  $('retrySyncBtn').addEventListener('click', retrySync);
  $('newCaseBtn').addEventListener('click', () => { state.returnWorkspace = 'queue'; setView('createView'); });
  document.querySelectorAll('[data-back]').forEach(button => button.addEventListener('click', returnPrevious));
  $('refreshBtn').addEventListener('click', () => {
    if (!$('queueView').hidden) { state.page = 1; loadCases(); refreshCounts(); }
    else if (!$('globalView').hidden) refreshGlobal();
    else if (state.currentCase?.global_read) openGlobalCase(state.currentCase.id);
    else if (state.currentCase) openCase(state.currentCase.case_id);
  });
  $('captureLocationBtn').addEventListener('click', captureLocation);
  document.querySelectorAll('[data-files-target]').forEach(button => button.addEventListener('click', () => $(`${button.dataset.filesTarget}EvidenceInput`).click()));
  document.querySelectorAll('[data-camera-target]').forEach(button => button.addEventListener('click', () => openCamera(button.dataset.cameraTarget)));
  ['create', 'resolve'].forEach(target => $(`${target}EvidenceInput`).addEventListener('change', event => { addFiles(target, event.target.files); event.target.value = ''; }));
  $('cameraCloseBtn').addEventListener('click', () => closeCamera()); $('cameraCancelBtn').addEventListener('click', () => closeCamera()); $('cameraCaptureBtn').addEventListener('click', captureCameraPhoto);
  $('cameraOverlay').addEventListener('click', event => { if (event.target === event.currentTarget) closeCamera(); });
  $('mediaViewerClose').addEventListener('click', closeMediaViewer);
  $('mediaViewerOverlay').addEventListener('click', event => { if (event.target === event.currentTarget) closeMediaViewer(); });
  $('createCaseForm').elements.complaint_description.addEventListener('input', scheduleCategorySuggestion);
  $('createCaseForm').elements.complaint_category.addEventListener('input', updateCategoryGuidance);
  document.querySelectorAll('input[name="customer_id"]').forEach(input => input.addEventListener('input', () => validateCustomerId(input)));
  $('categorySuggestion').addEventListener('click', () => {
    if (!state.suggestedCategory) return;
    $('createCaseForm').elements.complaint_category.value = state.suggestedCategory.label;
    updateCategoryGuidance();
    $('categorySuggestion').textContent = `${state.suggestedCategory.label} selected`;
    $('categorySuggestion').disabled = true;
  });
  $('createCaseForm').addEventListener('submit', submitCreate);
  $('completeDetailsForm').addEventListener('submit', submitCompleteDetails);
  $('resolveForm').addEventListener('submit', event => submitTransition(event, 'resolve'));
  $('reopenForm').addEventListener('submit', event => submitTransition(event, 'reopen'));
  $('copyConflictDraftBtn').addEventListener('click', copyConflictDraft);
  $('reviewConflictBtn').addEventListener('click', () => state.currentCase.global_read ? openGlobalCase(state.currentCase.id) : openCase(state.currentCase.case_id));
  $('createCaseForm').addEventListener('input', () => utils.setCloseProtection?.('complaint-create-draft', true));
  $('createCaseForm').addEventListener('change', () => utils.setCloseProtection?.('complaint-create-draft', true));
  ['completeDetailsForm', 'resolveForm', 'reopenForm'].forEach(id => $(id).addEventListener('input', () => utils.setCloseProtection?.('complaint-transition-draft', true)));
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'hidden') closeCamera({ restoreFocus: false }); });
  window.addEventListener('pagehide', () => { closeCamera({ restoreFocus: false }); closeMediaViewer(); });
  window.addEventListener('beforeunload', () => { stopCamera(); window.SecureMediaViewer?.revoke(state.mediaViewerObjectUrl); });
  telegram?.onEvent?.('deactivated', () => closeCamera({ restoreFocus: false }));
  telegram?.BackButton?.onClick(returnPrevious);
  bootstrap();
}());
