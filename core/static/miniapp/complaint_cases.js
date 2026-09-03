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
    globalOverview: null, globalPage: 1, globalPages: 1, globalPageSize: 50,
    globalSort: '-date_reported', reportGridApi: null, reportGridLoading: false,
    categoryChart: null, timeChart: null, categoryChartType: 'bar', reportGranularity: 'month',
    reportSummarySequence: 0, reportTableSequence: 0, reportFilterTimer: null,
    reportTableAbortController: null,
    evidence: { create: [], resolve: [] },
    categoryDescriptions: new Map(),
    evidenceLimits: { max_files: 10, max_file_size_mb: 10, max_total_upload_mb: 30 },
    cameraStream: null, cameraTarget: '', cameraReplaceId: '', cameraSessionStartCount: 0,
    mediaViewerObjectUrl: '', mediaViewerRestoreFocus: null,
    mediaViewerMode: '', mediaViewerTarget: '', mediaViewerItemId: '',
    mediaViewerRequestSequence: 0, persistedEvidence: [],
    mediaViewerPointers: new Map(), mediaViewerSwipe: null,
    mediaViewerPinch: null, mediaViewerZoom: 100,
    exportObjectUrl: '', exportFilename: '', exportFile: null,
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
    utils.haptic?.(error ? 'error' : 'success');
    clearTimeout(node._timer);
    node._timer = setTimeout(() => node.classList.remove('visible'), 4000);
  }
  function json(path, payload) {
    return apiClient.postJson(path, Object.assign({ group_id: state.groupId }, payload || {}), state.initData, utils);
  }
  function getJson(path, params, requestSettings) {
    return apiClient.getJson(path, Object.assign({ group_id: state.groupId }, params || {}), state.initData, utils, requestSettings);
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
  function iconNode(name, className) {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('class', ['lucide', className || ''].filter(Boolean).join(' '));
    svg.setAttribute('aria-hidden', 'true');
    const use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
    use.setAttribute('href', `#lucide-${name}`);
    svg.appendChild(use);
    return svg;
  }
  function buttonWithIcon(label, icon, className) {
    const button = document.createElement('button');
    button.type = 'button';
    if (className) button.className = className;
    button.append(iconNode(icon), textNode('span', label));
    return button;
  }
  function metaItem(icon, value) {
    const node = document.createElement('span');
    node.append(iconNode(icon), textNode('span', value));
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
  function bindCollapsingHeader() {
    const header = $('appHeader');
    if (!header) return;
    let previousY = Math.max(0, window.scrollY || 0); let scheduled = false;
    const update = () => {
      scheduled = false;
      const currentY = Math.max(0, window.scrollY || 0); const delta = currentY - previousY;
      if (currentY <= 12 || delta < -4 || header.contains(document.activeElement)) header.classList.remove('header-hidden');
      else if (currentY > header.offsetHeight && delta > 4) header.classList.add('header-hidden');
      previousY = currentY;
    };
    window.addEventListener('scroll', () => {
      if (!scheduled) { scheduled = true; window.requestAnimationFrame(update); }
    }, { passive: true });
    header.addEventListener('focusin', () => header.classList.remove('header-hidden'));
  }
  function statusStack(item) {
    const stack = document.createElement('div');
    stack.className = 'status-stack';
    const resolved = item.status === 'Resolved' || item.status === 'Closed';
    const status = textNode('span', displayStatus(item.status), `status-pill ${resolved ? 'resolved' : ''}`);
    status.prepend(iconNode(resolved ? 'circle-check' : 'clock'));
    stack.appendChild(status);
    if (item.needs_details) stack.appendChild(textNode('span', 'Needs More Information', 'needs-details-pill'));
    return stack;
  }
  function displayStatus(status) {
    return ({ Pending: 'Pending', Open: 'Reopened', Closed: 'Resolved', 'Review Needed': 'Needs More Information' })[status] || status || 'Update';
  }

  function setView(name) {
    if (!$('cameraOverlay').hidden) closeCamera();
    if (!$('mediaViewerOverlay').hidden) closeMediaViewer();
    ['queueView', 'globalView', 'createView', 'detailView'].forEach(id => { $(id).hidden = id !== name; });
    $('loadingState').hidden = true;
    const queueWorkspace = name === 'queueView';
    $('workspaceTabs').hidden = !queueWorkspace;
    if (queueWorkspace) state.workspace = 'queue';
    $('queueWorkspaceBtn').classList.toggle('active', queueWorkspace);
    $('globalWorkspaceBtn').classList.remove('active');
    telegram?.BackButton?.[queueWorkspace ? 'hide' : 'show']();
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
      $('globalWorkspaceBtn').hidden = !can('complaint.reports.view');
      $('workspaceTabs').classList.toggle('single-tab', !can('complaint.reports.view'));
      $('exportAllBtn').hidden = !(can('complaint.reports.view') && can('complaint.case.export'));
      selectOptions($('createCaseForm').elements.branch_region, data.branches, 'Select branch');
      selectOptions($('createCaseForm').elements.complaint_category, data.categories, 'Select complaint type');
      selectOptions($('completeDetailsForm').elements.complaint_category, data.categories, 'Select complaint type');
      state.categoryDescriptions = new Map((data.category_catalogue || []).map(item => [item.label, item.description]));
      updateEvidenceHints();
      setView('queueView');
      await loadCases();
    } catch (error) {
      $('loadingState').textContent = error.message || 'Complaints could not be opened.';
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
      const meta = document.createElement('div'); meta.className = 'case-meta-line';
      meta.append(
        metaItem(item.customer_phone ? 'phone' : 'file', item.customer_phone || item.customer_id || 'Customer details required'),
        metaItem('tag', item.category || 'Other Complaint'),
        metaItem('map-pin', item.branch || 'Branch not provided'),
      );
      const resolved = item.status === 'Resolved' || item.status === 'Closed';
      const age = document.createElement('p');
      age.className = `case-age ${resolved ? 'resolved' : (item.needs_details ? 'attention' : 'pending')}`;
      age.append(iconNode(resolved ? 'circle-check' : 'clock'), textNode('span', item.age_label || ''));
      body.append(
        textNode('p', `#${start + index} · ${item.reference_number || item.case_id}`, 'case-reference'),
        textNode('h2', item.customer_name || 'Unnamed customer'),
        meta,
        age,
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
    return ({ success: 'Synced', pending: 'Pending', failed: 'Failed', not_required: 'Not enabled', suspended: 'Not enabled' })[value] || value || 'Not recorded';
  }

  function renderDetail(item, preserveDraft) {
    state.currentCase = item;
    $('detailCaseId').textContent = item.reference_number || item.case_id;
    $('detailName').textContent = item.customer_name || 'Unnamed customer';
    $('detailGroup').textContent = item.group_label || '';
    $('detailStatus').textContent = displayStatus(item.status);
    $('detailStatus').className = `status-pill ${item.status === 'Resolved' ? 'resolved' : ''}`;
    $('detailNeedsDetails').hidden = !item.needs_details;
    const ids = $('detailIdentifiers'); ids.replaceChildren();
    [item.customer_phone, item.customer_id].filter(Boolean).forEach(value => ids.appendChild(textNode('span', value)));
    $('detailDescription').textContent = item.description || 'No description recorded.';
    const meta = $('detailMeta'); meta.replaceChildren();
    [
      item.category ? `Complaint Type: ${item.category}` : '',
      item.branch ? `Branch: ${item.branch}` : 'Branch not provided',
      item.reported_at ? `Reported: ${item.reported_at}` : '',
    ].filter(Boolean).forEach(value => meta.appendChild(textNode('span', value)));
    const source = item.source_attribution || {};
    $('detailSource').textContent = item.global_read
      ? 'Available to authorized complaint staff'
      : (source.type === 'batch' ? `${source.label} · Uploaded by ${source.actor} · ${source.created_at}` : (source.label || 'Source unavailable'));
    $('detailSync').textContent = `Sheet Sync: ${syncLabel(item.sync_status)}`;
    renderHistory(item); renderEvidence(item.evidence || []); renderActivity(item.updates || []);
    $('evidencePanel').hidden = !!item.global_read; $('activityPanel').hidden = !!item.global_read;
    const actions = item.global_read ? (item.actions || {}) : {
      close: can('complaint.case.close'), reopen: can('complaint.case.reopen'),
      complete_details: can('complaint.case.details.complete'),
    };
    $('completeDetailsForm').hidden = !item.needs_details || !actions.complete_details;
    $('resolveForm').hidden = item.status !== 'Pending' || !actions.close;
    $('reopenForm').hidden = item.status !== 'Resolved' || !actions.reopen;
    $('detailBackLabel').textContent = state.returnWorkspace === 'global' ? 'Overview' : 'Complaints';
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
    $('previousResolutionText').textContent = displayHistoryNote(resolution.note) || 'No resolution note recorded.';
    $('previousResolutionMeta').textContent = [`Resolved by ${resolution.updated_by || 'Staff'}`, resolution.created_at].filter(Boolean).join(' · ');
    const reopened = item.latest_reopen; $('previousReopen').hidden = !reopened;
    if (reopened) {
      $('previousReopenText').textContent = displayHistoryNote(reopened.note) || '';
      $('previousReopenMeta').textContent = [`Reopened by ${reopened.updated_by || 'Staff'}`, reopened.created_at].filter(Boolean).join(' · ');
    }
  }
  function displayHistoryNote(note) {
    const value = String(note || '');
    const friendlyLegacyNotes = {
      'the case is now fully resolved': 'Complaint marked as resolved',
      'the case was resolved': 'Complaint resolved',
      'the customer is still complaining': 'Customer reported the issue again',
    };
    return friendlyLegacyNotes[value.trim().toLowerCase()] || value;
  }
  function renderEvidence(items) {
    const node = $('evidenceList'); node.replaceChildren();
    state.persistedEvidence = (items || []).filter(item => item.preview_url);
    if (!items.length) { node.appendChild(textNode('p', 'No attachments available.', 'muted')); return; }
    items.forEach(item => {
      const row = document.createElement('div'); row.className = 'item evidence-item'; row.appendChild(textNode('strong', item.name));
      if (item.preview_url) {
        const button = buttonWithIcon('View in app', 'eye', 'media-link');
        button.addEventListener('click', () => openPersistedEvidence(item, button));
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
  function mediaPointDistance(points) {
    return Math.hypot(points[0].x - points[1].x, points[0].y - points[1].y);
  }
  function mediaPointMidpoint(points) {
    return { x: (points[0].x + points[1].x) / 2, y: (points[0].y + points[1].y) / 2 };
  }
  function resetMediaViewerGestures() {
    state.mediaViewerPointers.clear(); state.mediaViewerSwipe = null;
    state.mediaViewerPinch = null; state.mediaViewerZoom = 100;
    const content = $('mediaViewerContent'); const image = content.querySelector('.media-viewer-image');
    content.classList.remove('image-gestures', 'zoomed'); delete content.dataset.zoom;
    content.removeAttribute('aria-label'); content.scrollLeft = 0; content.scrollTop = 0;
    if (image) image.style.width = '';
  }
  function activateMediaViewerGestures() {
    resetMediaViewerGestures();
    const content = $('mediaViewerContent'); const image = content.querySelector('.media-viewer-image');
    content.setAttribute('aria-label', image
      ? 'File preview. Swipe left or right to browse files. Pinch to zoom this image.'
      : 'File preview. Swipe left or right to browse files.');
    if (image) { content.classList.add('image-gestures'); content.dataset.zoom = '100'; image.style.width = '100%'; }
  }
  function setMediaViewerZoom(value, focalPoint) {
    const content = $('mediaViewerContent'); const image = content.querySelector('.media-viewer-image');
    if (!image) return;
    const previousZoom = state.mediaViewerZoom;
    const nextZoom = Math.max(50, Math.min(300, Math.round(value)));
    if (nextZoom === previousZoom) return;
    const bounds = content.getBoundingClientRect();
    const localX = (focalPoint?.x ?? (bounds.left + bounds.width / 2)) - bounds.left;
    const localY = (focalPoint?.y ?? (bounds.top + bounds.height / 2)) - bounds.top;
    const ratio = nextZoom / previousZoom;
    state.mediaViewerZoom = nextZoom; content.dataset.zoom = String(nextZoom);
    content.classList.toggle('zoomed', nextZoom !== 100); image.style.width = `${nextZoom}%`;
    content.scrollLeft = (content.scrollLeft + localX) * ratio - localX;
    content.scrollTop = (content.scrollTop + localY) * ratio - localY;
  }
  function mediaViewerPointerDown(event) {
    if (event.pointerType === 'mouse' || $('mediaViewerOverlay').hidden) return;
    state.mediaViewerPointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
    if (state.mediaViewerPointers.size === 1) {
      state.mediaViewerSwipe = { pointerId: event.pointerId, startX: event.clientX, startY: event.clientY, startedAt: Date.now(), cancelled: false };
    }
    if (state.mediaViewerPointers.size === 2 && $('mediaViewerContent').querySelector('.media-viewer-image')) {
      if (state.mediaViewerSwipe) state.mediaViewerSwipe.cancelled = true;
      const points = Array.from(state.mediaViewerPointers.values());
      state.mediaViewerPinch = { distance: mediaPointDistance(points), zoom: state.mediaViewerZoom };
    }
    try { event.currentTarget.setPointerCapture(event.pointerId); } catch (_) { /* Synthetic and older WebView events may not capture. */ }
    event.preventDefault();
  }
  function mediaViewerPointerMove(event) {
    const previous = state.mediaViewerPointers.get(event.pointerId);
    if (!previous) return;
    state.mediaViewerPointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
    if (state.mediaViewerPointers.size === 2 && state.mediaViewerPinch) {
      const points = Array.from(state.mediaViewerPointers.values());
      const distance = mediaPointDistance(points);
      if (state.mediaViewerPinch.distance) {
        setMediaViewerZoom(state.mediaViewerPinch.zoom * (distance / state.mediaViewerPinch.distance), mediaPointMidpoint(points));
      }
    } else if (state.mediaViewerPointers.size === 1) {
      event.currentTarget.scrollLeft -= event.clientX - previous.x;
      event.currentTarget.scrollTop -= event.clientY - previous.y;
    }
    event.preventDefault();
  }
  function finishMediaViewerPointer(event, cancelled) {
    if (!state.mediaViewerPointers.has(event.pointerId)) return;
    const swipe = state.mediaViewerSwipe;
    if (!cancelled && event.type === 'pointerup' && swipe && swipe.pointerId === event.pointerId && !swipe.cancelled && state.mediaViewerPointers.size === 1) {
      const deltaX = event.clientX - swipe.startX; const deltaY = event.clientY - swipe.startY;
      const threshold = Math.max(56, event.currentTarget.clientWidth * .16);
      const deliberateHorizontalSwipe = Math.abs(deltaX) >= threshold
        && Math.abs(deltaX) > Math.abs(deltaY) * 1.35
        && Date.now() - swipe.startedAt <= 900;
      if (deliberateHorizontalSwipe && navigateMediaViewer(deltaX < 0 ? 1 : -1)) utils.haptic?.('light');
    }
    state.mediaViewerPointers.delete(event.pointerId); state.mediaViewerPinch = null;
    if (!state.mediaViewerPointers.size || swipe?.pointerId === event.pointerId) state.mediaViewerSwipe = null;
  }
  function closeMediaViewer() {
    state.mediaViewerRequestSequence += 1;
    resetMediaViewerGestures();
    $('mediaViewerOverlay').hidden = true; $('mediaViewerContent').replaceChildren();
    $('mediaViewerActions').hidden = true;
    window.SecureMediaViewer?.revoke(state.mediaViewerObjectUrl); state.mediaViewerObjectUrl = '';
    state.mediaViewerMode = ''; state.mediaViewerTarget = ''; state.mediaViewerItemId = '';
    const restore = state.mediaViewerRestoreFocus; state.mediaViewerRestoreFocus = null; restore?.focus?.();
  }
  function showMediaViewer(restoreFocus) {
    resetMediaViewerGestures();
    if (!$('mediaViewerOverlay').hidden) {
      window.SecureMediaViewer?.revoke(state.mediaViewerObjectUrl); state.mediaViewerObjectUrl = '';
      $('mediaViewerContent').replaceChildren();
    } else {
      state.mediaViewerRestoreFocus = restoreFocus || null;
    }
    $('mediaViewerTitle').textContent = 'File Preview';
    $('mediaViewerContent').replaceChildren(loadingNode('Loading secure file...')); $('mediaViewerOverlay').hidden = false;
  }
  function mediaViewerEntries() {
    if (state.mediaViewerMode === 'selected') return state.evidence[state.mediaViewerTarget] || [];
    if (state.mediaViewerMode === 'persisted') return state.persistedEvidence || [];
    return [];
  }
  function updateMediaViewerControls(item) {
    const entries = mediaViewerEntries();
    const index = entries.findIndex(entry => state.mediaViewerMode === 'selected'
      ? entry.id === state.mediaViewerItemId
      : entry.preview_url === state.mediaViewerItemId);
    $('mediaViewerSub').textContent = index >= 0
      ? `${index + 1} of ${entries.length} · ${item?.file?.name || item?.name || 'Attachment'}`
      : (item?.file?.name || item?.name || 'Attachment');
    $('mediaViewerActions').hidden = entries.length === 0;
    $('mediaViewerPrevious').disabled = index <= 0;
    $('mediaViewerNext').disabled = index < 0 || index >= entries.length - 1;
    const selected = state.mediaViewerMode === 'selected';
    $('mediaViewerActions').dataset.mode = selected
      ? (String(item?.file?.type || '').startsWith('image/') ? 'selected-image' : 'selected-file')
      : 'persisted';
    $('mediaViewerDelete').hidden = !selected;
    $('mediaViewerRetake').hidden = !selected || !String(item?.file?.type || '').startsWith('image/');
  }
  async function openPersistedEvidence(item, button) {
    state.mediaViewerMode = 'persisted'; state.mediaViewerTarget = '';
    state.mediaViewerItemId = item.preview_url; showMediaViewer(button);
    updateMediaViewerControls(item);
    const requestSequence = ++state.mediaViewerRequestSequence;
    try {
      const viewer = window.SecureMediaViewer;
      if (!viewer) throw new Error('The secure evidence viewer is unavailable. Refresh and retry.');
      const groupId = state.currentCase.group_id || state.groupId; const accessRequestId = requestId('complaint-evidence');
      const blob = await viewer.fetchAuthorizedBlob(item.preview_url, {
        method: 'POST',
        headers: { ...mediaHeaders(accessRequestId), 'Content-Type': 'application/json', 'Idempotency-Key': accessRequestId },
        body: JSON.stringify({ group_id: groupId, client_request_id: accessRequestId }),
      });
      if (requestSequence !== state.mediaViewerRequestSequence || state.mediaViewerItemId !== item.preview_url) return;
      state.mediaViewerObjectUrl = viewer.renderBlob($('mediaViewerContent'), blob, {
        mimeType: item.mime_type || '', name: item.name || 'Complaint evidence',
      });
      activateMediaViewerGestures();
    } catch (error) {
      if (requestSequence !== state.mediaViewerRequestSequence) return;
      $('mediaViewerContent').replaceChildren(textNode('p', `${error.message || 'The evidence could not be opened.'} Close this view and retry.`, 'media-viewer-error'));
    }
  }
  function renderActivity(items) {
    const node = $('activityList'); node.replaceChildren();
    if (!items.length) { node.appendChild(textNode('p', 'No complaint history available.', 'muted')); return; }
    items.forEach(item => {
      const row = document.createElement('div'); row.className = 'item history-item';
      let action = 'Updated by';
      if (item.status === 'Closed') action = 'Resolved by';
      else if (item.status === 'Open' && item.old_status === 'Closed') action = 'Reopened by';
      else if (item.status === 'Open') action = 'Complaint recorded by';
      else if (item.status === 'Review Needed') action = 'More information requested by';
      const content = document.createElement('div');
      content.append(textNode('strong', `${action} ${item.updated_by || 'Staff'}`), textNode('p', displayHistoryNote(item.note)), textNode('small', item.created_at || '', 'muted'));
      row.append(iconNode(item.status === 'Closed' ? 'circle-check' : 'history', 'item-icon'), content);
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
    const formNode = event.currentTarget;
    normalizeCustomerNameInput(formNode.elements.client_name);
    const data = new FormData(formNode);
    const idError = validateCustomerId(formNode.elements.customer_id);
    if (idError) return notify(idError, true);
    data.set('client_request_id', requestId('complaint-create')); appendEvidence(data, 'create');
    if (state.latitude) { data.set('latitude', state.latitude); data.set('longitude', state.longitude); }
    const button = $('createSaveBtn'); state.submitting = true; setActionLoading(button, true, 'Creating');
    utils.setCloseProtection?.('complaint-operation', true); $('createSaveState').textContent = 'Saving…';
    try {
      const response = await form('cases/create/', data); formNode.reset(); clearEvidence('create');
      state.latitude = ''; state.longitude = ''; resetLocationCapture(); hideSuggestion();
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
  function normalizeCustomerNameInput(input) {
    if (!input) return;
    input.value = String(input.value || '').trim().replace(/\s+/g, ' ').split(/(\s+|[-'’])/).map(part => {
      if (!part || /^(\s+|[-'’])$/.test(part)) return part;
      const upper = part.toLocaleUpperCase(); const lower = part.toLocaleLowerCase();
      return part === upper || part === lower ? upper.charAt(0) + lower.slice(1) : part;
    }).join('');
  }
  function setLocationCaptureState(kind, buttonLabel, detail) {
    const button = $('captureLocationBtn'); const status = $('captureState');
    button.disabled = kind === 'capturing';
    button.classList.toggle('location-capturing', kind === 'capturing');
    button.classList.toggle('location-success', kind === 'success');
    button.classList.toggle('location-error', kind === 'error');
    const label = button.querySelector('span'); if (label) label.textContent = buttonLabel;
    status.classList.toggle('location-coordinate', kind === 'success');
    status.classList.toggle('location-error-text', kind === 'error');
    status.textContent = detail;
  }
  function resetLocationCapture() {
    setLocationCaptureState('idle', 'Use My Current Location', 'Location not added');
  }
  function captureLocation() {
    if (!navigator.geolocation) {
      setLocationCaptureState('error', 'Location Unavailable', 'This device cannot provide a GPS location.');
      notify('Location is unavailable on this device.', true); return;
    }
    setLocationCaptureState('capturing', 'Capturing Location…', 'Waiting for an accurate GPS position…');
    navigator.geolocation.getCurrentPosition(position => {
      state.latitude = position.coords.latitude.toFixed(6); state.longitude = position.coords.longitude.toFixed(6);
      setLocationCaptureState('success', 'Location Captured', `GPS: ${state.latitude}, ${state.longitude}`);
      utils.haptic?.('success');
    }, () => {
      setLocationCaptureState('error', 'Try Location Again', 'Location was not captured. Check location permission and try again.');
      notify('Location permission was not available.', true);
    }, { enableHighAccuracy: true, timeout: 12000 });
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
      const view = buttonWithIcon('View', 'eye', 'view-file');
      view.addEventListener('click', () => openSelectedEvidence(target, item.id, view)); row.appendChild(view);
      const remove = buttonWithIcon('Remove', 'trash-2', 'remove-file');
      remove.addEventListener('click', () => removeEvidence(target, item.id)); row.appendChild(remove); list.appendChild(row);
    });
  }
  function openSelectedEvidence(target, itemId, button) {
    const item = state.evidence[target].find(entry => entry.id === itemId);
    if (!item) return;
    state.mediaViewerMode = 'selected'; state.mediaViewerTarget = target; state.mediaViewerItemId = item.id;
    const viewer = window.SecureMediaViewer; showMediaViewer(button);
    updateMediaViewerControls(item);
    if (!viewer) {
      $('mediaViewerContent').replaceChildren(textNode('p', 'The secure evidence viewer is unavailable. Refresh and retry.', 'media-viewer-error'));
      return;
    }
    state.mediaViewerObjectUrl = viewer.renderBlob($('mediaViewerContent'), item.file, { mimeType: item.file.type, name: item.file.name });
    activateMediaViewerGestures();
  }

  function stopCamera() {
    state.cameraStream?.getTracks?.().forEach(track => track.stop());
    state.cameraStream = null;
    if ($('cameraVideo')) $('cameraVideo').srcObject = null;
  }
  function closeCamera(options) {
    stopCamera(); $('cameraOverlay').hidden = true; document.body.classList.remove('camera-open');
    const focusTarget = options?.focusTarget || (state.cameraTarget ? document.querySelector(`[data-camera-target="${state.cameraTarget}"]`) : null);
    state.cameraTarget = ''; state.cameraReplaceId = ''; if (options?.restoreFocus !== false) focusTarget?.focus?.();
  }
  function updateCameraCaptureState() {
    const count = Math.max(0, (state.evidence[state.cameraTarget]?.length || 0) - state.cameraSessionStartCount);
    $('cameraCaptureState').textContent = state.cameraReplaceId
      ? 'The original stays selected until the replacement is captured.'
      : (count ? `${count} photo${count === 1 ? '' : 's'} added this session` : 'No photos added yet');
  }
  async function openCamera(target, options) {
    if (!navigator.mediaDevices?.getUserMedia) return notify('This Telegram WebView cannot open the camera directly. Use Upload Files instead.', true);
    if (!options?.replaceId && state.evidence[target].length >= state.evidenceLimits.max_files) return notify(`You can attach up to ${state.evidenceLimits.max_files} files. Delete one before taking another photo.`, true);
    state.cameraTarget = target; state.cameraReplaceId = options?.replaceId || '';
    state.cameraSessionStartCount = state.evidence[target].length;
    $('cameraTitle').textContent = state.cameraReplaceId ? 'Retake Photo' : 'Take Photos';
    $('cameraHelp').textContent = state.cameraReplaceId
      ? 'The existing photo will be replaced only after a new photo is captured.'
      : 'Take as many photos as needed, then tap Done. Nothing uploads until you submit.';
    $('cameraCaptureBtn').textContent = state.cameraReplaceId ? 'Retake Photo' : 'Take Photo';
    updateCameraCaptureState(); $('cameraOverlay').hidden = false; document.body.classList.add('camera-open');
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
    const target = state.cameraTarget; const replaceId = state.cameraReplaceId;
    const file = new File([blob], `complaint-evidence-${Date.now()}.jpg`, { type: 'image/jpeg' });
    if (replaceId) {
      const items = state.evidence[target]; const index = items.findIndex(item => item.id === replaceId);
      if (index < 0) { closeCamera({ restoreFocus: false }); return notify('That photo is no longer selected.', true); }
      const oldItem = items[index];
      const totalBytes = items.reduce((sum, item) => sum + item.file.size, 0) - oldItem.file.size + file.size;
      if (file.size > state.evidenceLimits.max_file_size_mb * 1024 * 1024 || totalBytes > state.evidenceLimits.max_total_upload_mb * 1024 * 1024) {
        return notify('The replacement photo exceeds the configured attachment limits.', true);
      }
      if (oldItem.preview) URL.revokeObjectURL(oldItem.preview);
      const replacement = { id: requestId('evidence-file'), file, preview: URL.createObjectURL(file) };
      items.splice(index, 1, replacement); renderSelectedEvidence(target);
      closeCamera({ restoreFocus: false }); openSelectedEvidence(target, replacement.id, null);
      notify('Photo retaken. Review it or retake it again.');
      return;
    }
    if (addFiles(target, [file])) {
      updateCameraCaptureState();
      notify('Photo added. Take another photo or tap Done.');
    }
  }

  function navigateMediaViewer(offset) {
    const entries = mediaViewerEntries();
    const index = entries.findIndex(entry => state.mediaViewerMode === 'selected'
      ? entry.id === state.mediaViewerItemId
      : entry.preview_url === state.mediaViewerItemId);
    const target = entries[index + offset];
    if (!target) return false;
    if (state.mediaViewerMode === 'selected') openSelectedEvidence(state.mediaViewerTarget, target.id, null);
    else openPersistedEvidence(target, null);
    return true;
  }
  function deleteSelectedMediaFromViewer() {
    if (state.mediaViewerMode !== 'selected') return;
    const target = state.mediaViewerTarget; const entries = mediaViewerEntries();
    const index = entries.findIndex(item => item.id === state.mediaViewerItemId);
    if (index < 0) return;
    removeEvidence(target, state.mediaViewerItemId);
    const remaining = state.evidence[target];
    if (!remaining.length) { closeMediaViewer(); notify('Attachment deleted.'); return; }
    openSelectedEvidence(target, remaining[Math.min(index, remaining.length - 1)].id, null);
    notify('Attachment deleted.');
  }
  function retakeSelectedMediaFromViewer() {
    if (state.mediaViewerMode !== 'selected') return;
    const target = state.mediaViewerTarget; const itemId = state.mediaViewerItemId;
    const item = state.evidence[target]?.find(entry => entry.id === itemId);
    if (!item || !String(item.file.type || '').startsWith('image/')) return;
    closeMediaViewer(); openCamera(target, { replaceId: itemId });
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
    const labels = [['total', 'Total Complaints'], ['pending', 'Pending'], ['resolved', 'Resolved'], ['needs_details', 'Need More Information']];
    const icons = { total: 'list', pending: 'clock', resolved: 'circle-check', needs_details: 'history' };
    const node = $('globalMetrics'); node.replaceChildren();
    labels.forEach(([key, label]) => {
      const card = document.createElement('div'); card.className = `metric-card ${key === 'needs_details' && metrics[key] ? 'attention' : ''}`;
      card.append(iconNode(icons[key], 'metric-icon'), textNode('strong', metrics[key] || 0), textNode('span', label)); node.appendChild(card);
    });
  }
  function chartColor(token, fallback) {
    return getComputedStyle(document.documentElement).getPropertyValue(token).trim() || fallback;
  }
  function categoryColorMap(summary) {
    const labels = (summary.filter_options?.categories || summary.by_category || [])
      .map(item => item.label).sort((left, right) => left.localeCompare(right));
    return new Map(labels.map((label, index) => [label, `hsl(${Math.round((index * 137.508) % 360)} 65% 48%)`]));
  }
  function formatChartPeriodDate(value, granularity) {
    const raw = String(value || '').trim();
    let match;
    if (granularity === 'year' && (match = raw.match(/^(\d{4})$/))) return `01-01-${match[1].slice(-2)}`;
    if (granularity === 'month' && (match = raw.match(/^(\d{4})-(\d{2})$/))) return `01-${match[2]}-${match[1].slice(-2)}`;
    if ((match = raw.match(/^(\d{4})-(\d{2})-(\d{2})/))) return `${match[3]}-${match[2]}-${match[1].slice(-2)}`;
    return raw;
  }
  function setChartState(name, message) {
    const canvas = $(name === 'category' ? 'categoryChart' : 'timeChart');
    const status = $(name === 'category' ? 'categoryChartState' : 'timeChartState');
    status.textContent = message || ''; status.hidden = !message; canvas.hidden = !!message;
  }
  function renderReportCharts(summary) {
    if (!window.Chart) return;
    state.categoryChart?.destroy(); state.timeChart?.destroy(); state.categoryChart = null; state.timeChart = null;
    const categories = summary.by_category || []; const periods = summary.by_time || [];
    const textColor = chartColor('--muted', '#667085');
    setChartState('category', categories.length ? '' : 'No complaint types match these filters.');
    setChartState('time', periods.length ? '' : 'No complaints match this time period.');
    if (!categories.length && !periods.length) return;
    const colorMap = categoryColorMap(summary);
    const categoryColors = categories.map(item => colorMap.get(item.label) || 'hsl(210 65% 48%)');
    const categoryIsPie = state.categoryChartType === 'pie';
    if (categories.length) {
    state.categoryChart = new window.Chart($('categoryChart'), {
      type: state.categoryChartType, data: {
        labels: categories.map(item => item.label),
        datasets: [{ data: categories.map(item => item.count), backgroundColor: categoryColors, borderColor: categoryIsPie ? chartColor('--surface', '#fff') : categoryColors, borderWidth: categoryIsPie ? 2 : 0, borderRadius: categoryIsPie ? 0 : 4 }],
      }, options: {
        responsive: true, maintainAspectRatio: false, indexAxis: categoryIsPie ? 'x' : 'y',
        plugins: { legend: { display: categoryIsPie, position: 'bottom', labels: { color: textColor, boxWidth: 10, boxHeight: 10, font: { size: 9 } } } },
        scales: categoryIsPie ? {} : { x: { beginAtZero: true, ticks: { precision: 0, color: textColor } }, y: { ticks: { color: textColor } } },
      },
    });
    }
    if (periods.length) state.timeChart = new window.Chart($('timeChart'), {
      type: 'line', data: {
        labels: periods.map(item => formatChartPeriodDate(item.label, summary.time_granularity || state.reportGranularity)),
        datasets: [{ data: periods.map(item => item.count), borderColor: chartColor('--accent', '#087f5b'), backgroundColor: chartColor('--soft', 'rgba(8,127,91,.12)'), fill: true, tension: .25, pointRadius: 2 }],
      }, options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { x: { ticks: { color: textColor, autoSkip: true, autoSkipPadding: 8, maxTicksLimit: window.innerWidth <= 480 ? 4 : 8, maxRotation: 0, minRotation: 0, padding: 4, font: { size: 9 } } }, y: { beginAtZero: true, ticks: { precision: 0, color: textColor } } } },
    });
  }
  function preserveSelectOptions(select, items, placeholder) {
    const selected = select.value;
    selectOptions(select, items.map(item => item.label), placeholder);
    if (Array.from(select.options).some(option => option.value === selected)) select.value = selected;
  }
  function populateGlobalFilters(summary) {
    const formNode = $('globalFilters');
    preserveSelectOptions(formNode.elements.branch, summary.filter_options?.branches || [], 'Any Branch');
    preserveSelectOptions(formNode.elements.category, summary.filter_options?.categories || [], 'Any Category');
  }
  function showChartLoading() { setChartState('category', 'Loading complaint types...'); setChartState('time', 'Loading complaint history...'); }
  async function loadGlobalOverview(filters) {
    const sequence = ++state.reportSummarySequence; showChartLoading();
    try {
      const summary = await getJson('reports/summary/', Object.assign({}, filters, { granularity: state.reportGranularity }));
      if (sequence !== state.reportSummarySequence) return null;
      state.globalOverview = summary; renderMetrics(summary); populateGlobalFilters(summary); renderReportCharts(summary);
      state.globalLoaded = true; return summary;
    } catch (error) {
      if (sequence === state.reportSummarySequence) {
        setChartState('category', error.message); setChartState('time', error.message); notify(error.message, true);
      }
      return null;
    }
  }
  function updateReportDateControls() {
    const formNode = $('globalFilters'); const mode = formNode.elements.date_mode.value;
    $('reportMonthField').hidden = mode !== 'month'; $('reportCustomDates').hidden = mode !== 'custom';
    formNode.elements.report_month.disabled = mode !== 'month';
    formNode.elements.date_from.disabled = mode !== 'custom'; formNode.elements.date_to.disabled = mode !== 'custom';
  }
  function monthBoundaries(value) {
    const match = /^(\d{4})-(\d{2})$/.exec(value || '');
    if (!match) throw new Error('Select the month you want to report on.');
    const year = Number(match[1]); const month = Number(match[2]);
    const lastDay = new Date(Date.UTC(year, month, 0)).getUTCDate();
    return [`${value}-01`, `${value}-${String(lastDay).padStart(2, '0')}`];
  }
  function globalFilterPayload() {
    const formNode = $('globalFilters'); const values = {};
    for (const name of ['search', 'status', 'branch', 'category']) if (formNode.elements[name].value) values[name] = formNode.elements[name].value;
    const mode = formNode.elements.date_mode.value;
    if (mode === 'month') [values.date_from, values.date_to] = monthBoundaries(formNode.elements.report_month.value);
    if (mode === 'custom') {
      values.date_from = formNode.elements.date_from.value; values.date_to = formNode.elements.date_to.value;
      if (!values.date_from && !values.date_to) throw new Error('Select a start date, an end date, or both.');
      if (values.date_from && values.date_to && values.date_from > values.date_to) throw new Error('Start Date must be on or before End Date.');
    }
    return values;
  }
  function reportPeriodText(filters) {
    const formNode = $('globalFilters'); const mode = formNode.elements.date_mode.value;
    if (mode === 'month' && formNode.elements.report_month.value) {
      const [year, month] = formNode.elements.report_month.value.split('-').map(Number);
      return new Intl.DateTimeFormat(undefined, { month: 'long', year: 'numeric', timeZone: 'UTC' }).format(new Date(Date.UTC(year, month - 1, 1)));
    }
    if (mode === 'custom') {
      const format = value => value ? new Intl.DateTimeFormat(undefined, { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' }).format(new Date(`${value}T00:00:00Z`)) : '';
      if (filters.date_from && filters.date_to) return `Reported ${format(filters.date_from)} – ${format(filters.date_to)}`;
      return filters.date_from ? `Reported from ${format(filters.date_from)}` : `Reported through ${format(filters.date_to)}`;
    }
    return 'All reporting dates';
  }
  function currentReportFilters() {
    const filters = globalFilterPayload(); $('reportPeriodLabel').textContent = reportPeriodText(filters); return filters;
  }
  async function refreshReport(options) {
    let filters; try { filters = currentReportFilters(); } catch (error) { notify(error.message, true); return; }
    const settings = Object.assign({ summary: true, table: true }, options || {}); const requests = [];
    if (settings.summary) requests.push(loadGlobalOverview(filters));
    if (settings.table) requests.push(loadGlobalCases(filters));
    await Promise.all(requests);
  }
  function scheduleReportRefresh(delay) {
    clearTimeout(state.reportFilterTimer);
    state.reportFilterTimer = setTimeout(() => refreshReport(), delay == null ? 75 : delay);
  }
  function formatReportDate(value) {
    if (!value) return '';
    const match = String(value).match(/^(\d{4})-(\d{2})-(\d{2})/);
    if (match) return `${match[3]}-${match[2]}-${match[1].slice(-2)}`;
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return value;
    return [String(parsed.getDate()).padStart(2, '0'), String(parsed.getMonth() + 1).padStart(2, '0'), String(parsed.getFullYear()).slice(-2)].join('-');
  }
  function reportStatusRenderer(params) {
    const needsDetails = !!params.data?.needs_details;
    const label = needsDetails ? 'Needs More Information' : (params.value || 'Pending');
    return textNode('span', label, `report-status ${needsDetails ? 'needs-details' : String(params.value || 'pending').toLowerCase()}`);
  }
  function reportGpsRenderer(params) {
    if (!params.value) return '';
    const link = textNode('a', 'Open Map', 'report-gps');
    link.href = params.value; link.target = '_blank'; link.rel = 'noopener noreferrer';
    return link;
  }
  function initializeReportGrid() {
    if (state.reportGridApi || !window.agGrid) return;
    const touchManagedColumns = window.matchMedia('(max-width: 700px), (pointer: coarse)').matches;
    window.agGrid.ModuleRegistry.registerModules([window.agGrid.AllCommunityModule]);
    state.reportGridApi = window.agGrid.createGrid($('complaintReportGrid'), {
      theme: 'legacy', rowData: [], animateRows: false, suppressMultiSort: true,
      suppressMovableColumns: true, suppressColumnMoveAnimation: true,
      suppressCellFocus: false, ensureDomOrder: true, overlayNoRowsTemplate: 'No complaints match these filters.',
      defaultColDef: { sortable: true, resizable: !touchManagedColumns, suppressHeaderMenuButton: true, unSortIcon: true },
      columnDefs: [
        { headerName: '#', colId: 'row_number', width: 52, minWidth: 52, maxWidth: 52, sortable: false, resizable: false, pinned: 'left', valueGetter: p => ((state.globalPage - 1) * state.globalPageSize) + p.node.rowIndex + 1 },
        { headerName: 'Complaint ID', field: 'complaint_id', width: 125, sortable: false },
        { headerName: 'Date Reported', field: 'date_reported', width: 130, valueFormatter: p => formatReportDate(p.value) },
        { headerName: 'Status', field: 'status', width: 170, cellRenderer: reportStatusRenderer },
        { headerName: 'Customer Name', field: 'customer_name', width: 190, sortable: false },
        { headerName: 'Customer ID', field: 'customer_id', width: 125, sortable: false },
        { headerName: 'Phone Number', field: 'phone_number', width: 145, sortable: false },
        { headerName: 'Reported By', field: 'reported_by', width: 150, sortable: false },
        { headerName: 'Branch', field: 'branch_region', width: 145 },
        { headerName: 'Complaint Type', field: 'complaint_category', width: 180, sortable: false },
        { headerName: 'Complaint', field: 'complaint_description', width: 280, sortable: false },
        { headerName: 'Source', field: 'source', width: 130, sortable: false },
        { headerName: 'Location', field: 'gps_link', width: 105, sortable: false, cellRenderer: reportGpsRenderer },
        { headerName: 'Attachments', field: 'attachments', width: 105, sortable: false, type: 'numericColumn' },
        { headerName: 'Resolution', field: 'resolution_details', width: 260, sortable: false },
        { headerName: 'Date Resolved', field: 'date_resolved', width: 130, valueFormatter: p => formatReportDate(p.value) },
        { headerName: 'Days Open', field: 'days_open', width: 105, type: 'numericColumn' },
      ],
      onSortChanged: event => {
        if (state.reportGridLoading) return;
        const selected = event.api.getColumnState().find(column => column.sort);
        const allowed = { date_reported: 'date_reported', status: 'status', branch_region: 'branch_region', days_open: 'days_open', date_resolved: 'date_resolved' };
        state.globalSort = selected && allowed[selected.colId]
          ? `${selected.sort === 'desc' ? '-' : ''}${allowed[selected.colId]}` : '-date_reported';
        state.globalPage = 1; refreshReport({ summary: false });
      },
    });
  }
  async function loadGlobalCases(filters) {
    const sequence = ++state.reportTableSequence;
    state.reportTableAbortController?.abort();
    const controller = typeof AbortController === 'function' ? new AbortController() : null;
    state.reportTableAbortController = controller;
    let requestTimedOut = false;
    let timeout;
    const timeoutPromise = new Promise((resolve, reject) => {
      timeout = setTimeout(() => {
        requestTimedOut = true; controller?.abort();
        reject(new Error('The complaints table request timed out.'));
      }, 20000);
    });
    initializeReportGrid();
    state.reportGridLoading = true; state.reportGridApi?.showLoadingOverlay();
    try {
      const response = await Promise.race([getJson('reports/data/', Object.assign({}, filters, {
        page: state.globalPage, page_size: state.globalPageSize, sort: state.globalSort,
      }), controller ? { signal: controller.signal } : undefined), timeoutPromise]);
      if (sequence !== state.reportTableSequence) return;
      state.globalPage = response.page; state.globalPages = Math.max(1, Math.ceil(response.count / response.page_size));
      $('globalResultCount').textContent = `${response.count} complaint${response.count === 1 ? '' : 's'} found`;
      const rows = response.results || [];
      state.reportGridApi?.setGridOption('rowData', rows);
      if (rows.length) state.reportGridApi?.hideOverlay();
      else state.reportGridApi?.showNoRowsOverlay();
      $('globalPagination').hidden = state.globalPages <= 1;
      $('globalPageLabel').textContent = `Page ${state.globalPage} of ${state.globalPages}`;
      $('globalPreviousBtn').disabled = state.globalPage <= 1; $('globalNextBtn').disabled = state.globalPage >= state.globalPages;
    } catch (error) {
      if (sequence === state.reportTableSequence) {
        state.reportGridApi?.hideOverlay(); state.reportGridApi?.showNoRowsOverlay();
        notify(requestTimedOut ? 'The complaints table took too long to load. Please try the filter again.' : error.message, true);
      }
    } finally {
      clearTimeout(timeout);
      if (sequence === state.reportTableSequence) {
        state.reportGridLoading = false;
        if (state.reportTableAbortController === controller) state.reportTableAbortController = null;
      }
    }
  }
  async function openGlobalWorkspace() {
    if (!can('complaint.reports.view')) return notify('Management report access is not assigned to your account.', true);
    state.returnWorkspace = 'queue'; setView('globalView');
    await refreshReport();
  }
  async function refreshGlobal() { await refreshReport(); }

  async function prepareExport() {
    try {
      $('downloadResult').hidden = true;
      const overview = await getJson('reports/summary/', { granularity: 'year' }); const count = overview.total || 0;
      $('exportConfirmText').textContent = `This download includes all ${count} complaints across all complaint groups, not only your current filters. Continue?`;
      $('exportConfirm').hidden = false; $('cancelExportBtn').focus();
    } catch (error) { notify(error.message, true); }
  }
  function cancelExport() { $('exportConfirm').hidden = true; $('exportAllBtn').focus(); }
  function releaseExportDownload() {
    if (state.exportObjectUrl) URL.revokeObjectURL(state.exportObjectUrl);
    state.exportObjectUrl = ''; state.exportFilename = ''; state.exportFile = null;
  }
  function startExportDownload() {
    if (!state.exportObjectUrl || !state.exportFilename) return false;
    const link = document.createElement('a');
    link.href = state.exportObjectUrl; link.download = state.exportFilename;
    document.body.appendChild(link); link.click(); link.remove();
    return true;
  }
  function mobileNativeExportAvailable() {
    const platform = String(telegram?.platform || '').toLowerCase();
    const mobile = ['android', 'ios'].includes(platform) || /Android|iPhone|iPad|iPod/i.test(navigator.userAgent || '');
    if (!mobile || typeof navigator.share !== 'function' || typeof navigator.canShare !== 'function' || !state.exportFile) return false;
    try { return navigator.canShare({ files: [state.exportFile] }); } catch (_) { return false; }
  }
  function showExportDownload(filename, nativeAvailable) {
    $('downloadFilename').textContent = filename;
    $('downloadResultTitle').textContent = nativeAvailable ? 'Excel file ready' : 'Download started';
    const message = $('downloadResultMessage'); const filenameNode = $('downloadFilename');
    message.replaceChildren(filenameNode, document.createTextNode(nativeAvailable
      ? ' is ready. Choose Excel, Google Sheets, or another compatible app.'
      : ' was sent to your device. Check Downloads or your browser’s download list.'));
    $('openExportBtn').hidden = !nativeAvailable;
    $('downloadResult').hidden = false;
  }
  async function openExportNatively(options) {
    const settings = options || {};
    if (!mobileNativeExportAvailable()) {
      if (!settings.quiet) notify('This Telegram version cannot open Excel files directly. Use Download Again or open the Mini App in your phone browser.', true);
      return false;
    }
    try {
      await navigator.share({ files: [state.exportFile], title: 'Complaints Report', text: 'Open the JBL complaints report.' });
      if (!settings.quiet) notify('Choose your Excel or spreadsheet app to view the report.');
      return true;
    } catch (error) {
      if (!settings.quiet && error?.name !== 'AbortError') notify('The phone blocked the app chooser. Tap Open Excel File to try again.', true);
      return false;
    }
  }
  async function confirmExport() {
    const button = $('confirmExportBtn'); setActionLoading(button, true, 'Downloading');
    try {
      const result = await apiClient.postBlob('global/export/', { group_id: state.groupId, confirm_all: true, client_request_id: requestId('complaint-export') }, state.initData, utils);
      releaseExportDownload();
      state.exportObjectUrl = URL.createObjectURL(result.blob);
      state.exportFilename = result.filename || 'complaints.xlsx';
      state.exportFile = typeof File === 'function' ? new File([result.blob], state.exportFilename, {
        type: result.blob.type || 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      }) : null;
      const nativeAvailable = mobileNativeExportAvailable();
      showExportDownload(state.exportFilename, nativeAvailable);
      $('exportConfirm').hidden = true;
      if (nativeAvailable) {
        const opened = await openExportNatively({ quiet: true });
        notify(opened
          ? 'The phone app chooser is open. Select Excel, Google Sheets, or another spreadsheet app.'
          : 'Excel file ready. Tap Open Excel File to choose a spreadsheet app.');
      } else {
        startExportDownload(); notify(`Download started. Check Downloads for ${state.exportFilename}.`);
      }
    } catch (error) { notify(error.message, true); }
    finally { setActionLoading(button, false); }
  }
  function downloadAgain() {
    if (!startExportDownload()) return notify('That download is no longer available. Create a new complaints download.', true);
    notify(`Download started again. Check Downloads for ${state.exportFilename}.`);
  }
  function returnPrevious() {
    if (!$('exportConfirm').hidden) { cancelExport(); return; }
    if (!$('globalView').hidden) { setView('queueView'); loadCases(); return; }
    if (state.returnWorkspace === 'global') { setView('globalView'); refreshReport(); }
    else { setView('queueView'); loadCases(); }
  }

  document.querySelectorAll('[data-status]').forEach(button => button.addEventListener('click', () => {
    state.status = button.dataset.status; state.page = 1;
    document.querySelectorAll('[data-status]').forEach(item => item.classList.toggle('active', item === button)); loadCases();
  }));
  $('caseSearch').addEventListener('input', event => { state.query = event.target.value; state.page = 1; clearTimeout(state.debounce); state.debounce = setTimeout(loadCases, state.query ? 250 : 0); });
  $('queuePreviousBtn').addEventListener('click', () => { if (state.page > 1) { state.page -= 1; loadCases(); } });
  $('queueNextBtn').addEventListener('click', () => { if (state.page < state.pages) { state.page += 1; loadCases(); } });
  $('globalPreviousBtn').addEventListener('click', () => { if (state.globalPage > 1) { state.globalPage -= 1; refreshReport({ summary: false }); } });
  $('globalNextBtn').addEventListener('click', () => { if (state.globalPage < state.globalPages) { state.globalPage += 1; refreshReport({ summary: false }); } });
  $('queueWorkspaceBtn').addEventListener('click', () => { setView('queueView'); loadCases(); });
  $('globalWorkspaceBtn').addEventListener('click', openGlobalWorkspace);
  $('reportBackBtn').addEventListener('click', () => { setView('queueView'); loadCases(); });
  $('globalFilters').addEventListener('submit', event => { event.preventDefault(); clearTimeout(state.reportFilterTimer); state.globalPage = 1; refreshReport(); });
  $('clearGlobalFiltersBtn').addEventListener('click', () => { $('globalFilters').reset(); updateReportDateControls(); clearTimeout(state.reportFilterTimer); state.globalPage = 1; refreshReport(); });
  $('globalFilters').addEventListener('change', event => {
    updateReportDateControls(); state.globalPage = 1;
    if (event.target.name === 'date_mode' && event.target.value !== 'all') return;
    scheduleReportRefresh();
  });
  $('globalFilters').elements.search.addEventListener('input', () => {
    state.globalPage = 1; scheduleReportRefresh(300);
  });
  document.querySelectorAll('[data-category-chart]').forEach(button => button.addEventListener('click', () => {
    state.categoryChartType = button.dataset.categoryChart;
    document.querySelectorAll('[data-category-chart]').forEach(option => {
      const active = option === button; option.classList.toggle('active', active); option.setAttribute('aria-pressed', String(active));
    });
    if (state.globalOverview) renderReportCharts(state.globalOverview);
  }));
  $('reportGranularity').addEventListener('change', event => {
    state.reportGranularity = event.target.value; refreshReport({ table: false }); utils.haptic?.('light');
  });
  $('exportAllBtn').addEventListener('click', prepareExport); $('cancelExportBtn').addEventListener('click', cancelExport); $('confirmExportBtn').addEventListener('click', confirmExport);
  $('openExportBtn').addEventListener('click', () => openExportNatively());
  $('downloadAgainBtn').addEventListener('click', downloadAgain);
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
  $('mediaViewerPrevious').addEventListener('click', () => navigateMediaViewer(-1));
  $('mediaViewerNext').addEventListener('click', () => navigateMediaViewer(1));
  $('mediaViewerDelete').addEventListener('click', deleteSelectedMediaFromViewer);
  $('mediaViewerRetake').addEventListener('click', retakeSelectedMediaFromViewer);
  $('mediaViewerOverlay').addEventListener('click', event => { if (event.target === event.currentTarget) closeMediaViewer(); });
  $('mediaViewerContent').addEventListener('pointerdown', mediaViewerPointerDown);
  $('mediaViewerContent').addEventListener('pointermove', mediaViewerPointerMove);
  $('mediaViewerContent').addEventListener('pointerup', event => finishMediaViewerPointer(event, false));
  $('mediaViewerContent').addEventListener('pointercancel', event => finishMediaViewerPointer(event, true));
  $('mediaViewerContent').addEventListener('lostpointercapture', event => finishMediaViewerPointer(event, true));
  $('createCaseForm').elements.complaint_description.addEventListener('input', scheduleCategorySuggestion);
  $('createCaseForm').elements.complaint_category.addEventListener('input', updateCategoryGuidance);
  $('createCaseForm').elements.client_name.addEventListener('blur', event => normalizeCustomerNameInput(event.currentTarget));
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
  document.addEventListener('click', event => {
    const button = event.target.closest?.('button');
    if (button && !button.disabled) utils.haptic?.('light');
  }, { capture: true });
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'hidden') closeCamera({ restoreFocus: false }); });
  window.addEventListener('pagehide', () => { closeCamera({ restoreFocus: false }); closeMediaViewer(); });
  window.addEventListener('beforeunload', () => { stopCamera(); window.SecureMediaViewer?.revoke(state.mediaViewerObjectUrl); });
  telegram?.onEvent?.('deactivated', () => closeCamera({ restoreFocus: false }));
  telegram?.BackButton?.onClick(returnPrevious);
  updateReportDateControls();
  bindCollapsingHeader();
  bootstrap();
}());
