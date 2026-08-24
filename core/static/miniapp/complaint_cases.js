(function () {
  const utils = window.MiniAppUtils || {};
  const complaintApi = window.ComplaintCasesMiniAppApi || {};
  const telegram = utils.initTelegram ? utils.initTelegram({ closingConfirmation: false }) : (window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null);
  if (telegram && !utils.initTelegram) { telegram.ready(); telegram.expand(); }
  const uiContext = utils.createUiContext ? utils.createUiContext('complaint-cases') : null;
  const restoredUi = uiContext?.read?.() || {};

  const state = {
    groupId: document.body.dataset.groupId || '',
    initData: telegram ? telegram.initData || '' : '',
    status: String(restoredUi.status || 'active'), branch: String(restoredUi.branch || ''), query: String(restoredUi.query || ''),
    priority: String(restoredUi.priority || ''), assignment: String(restoredUi.assignment || ''), sla: String(restoredUi.sla || ''),
    page: Math.max(1, Number(restoredUi.page || 1)), pages: 1, total: 0, startIndex: 0,
    currentCase: null, map: null, marker: null,
    capturedLocation: null, createCapturedLocation: null, debounce: null,
    capabilities: new Set(),
    personal: null,
    pendingCreateRequestId: '',
    pendingUpdateRequestId: '', nextCursor: '', assignees: [], submitting: false,
    queueRequestSequence: 0, queueScrollY: 0, queueDirty: false,
    filterSheetOpen: false, filterSheetReturnFocus: null,
  };
  const $ = (id) => document.getElementById(id);
  const escapeHtml = utils.escapeHtml || ((value) => String(value == null ? '' : value).replace(/[&<>"']/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[character])));
  const requestId = () => window.crypto && window.crypto.randomUUID ? window.crypto.randomUUID() : `complaint-${Date.now()}-${Math.random().toString(36).slice(2)}`;

  function rememberUi() {
    uiContext?.write?.({
      status: state.status, branch: state.branch, query: state.query,
      priority: state.priority, assignment: state.assignment, sla: state.sla, page: state.page,
    });
  }

  function hasUnsavedFormWork() {
    const createDirty = Array.from($('createCaseForm')?.elements || []).some((field) => {
      if (!field.name && field.id !== 'createEvidenceInput') return false;
      return field.type === 'file' ? Boolean(field.files?.length) : Boolean(String(field.value || '').trim());
    });
    const updateDirty = Boolean(String($('noteInput')?.value || '').trim() || $('evidenceInput')?.files?.length || state.capturedLocation);
    return (!$('createView')?.hidden && createDirty) || (!$('detailView')?.hidden && updateDirty);
  }

  function syncClosingConfirmation() {
    if (!telegram) return;
    if (hasUnsavedFormWork()) telegram.enableClosingConfirmation?.();
    else telegram.disableClosingConfirmation?.();
  }

  async function returnToQueue() {
    if (hasUnsavedFormWork() && !window.confirm('Discard the unsaved complaint changes?')) return;
    const restoreScroll = state.queueScrollY;
    showComplaintView('queue');
    syncClosingConfirmation();
    if (state.queueDirty) {
      state.queueDirty = false;
      await loadCases({ restoreScroll: true });
    } else {
      window.requestAnimationFrame(() => window.scrollTo(0, restoreScroll));
    }
  }

  function configureHtmx() {
    if (!window.htmx) return;
    document.body.addEventListener('htmx:configRequest', (event) => {
      event.detail.headers['X-Telegram-Init-Data'] = state.initData;
    });
    document.body.addEventListener('htmx:afterSwap', (event) => {
      if (event.detail.target && event.detail.target.id === 'caseList') {
        hydrateCaseRows(event.detail.target);
        $('emptyState').hidden = true;
      }
    });
  }

  async function api(path, payload, formData) {
    const data = formData || Object.assign({ group_id: state.groupId }, payload || {});
    if (formData && complaintApi.postForm) return complaintApi.postForm(path, formData, state.initData, state.groupId, utils);
    if (!formData && complaintApi.postJson) return complaintApi.postJson(path, data, state.initData, utils);
    if (formData) formData.set('group_id', state.groupId);
    const options = { method: 'POST', headers: { 'X-Telegram-Init-Data': state.initData } };
    if (formData) options.body = formData;
    else { options.headers['Content-Type'] = 'application/json'; options.body = JSON.stringify(data); }
    if (utils.fetchJson) return utils.fetchJson(`/api/complaints/${path}`, options);
    const response = await fetch(`/api/complaints/${path}`, options);
    const result = await response.json().catch(() => ({}));
    if (!response.ok || !result.ok) throw new Error(result.error || 'Request failed.');
    return result;
  }

  async function fragmentPost(path, payload) {
    if (complaintApi.postFragment) return complaintApi.postFragment(path, payload, state.initData, utils);
    if (utils.fetchHtml && utils.formBody) {
      return utils.fetchHtml(path, {
        method: 'POST',
        headers: Object.assign({ 'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8' }, utils.initDataHeader ? utils.initDataHeader(state.initData) : { 'X-Telegram-Init-Data': state.initData }),
        body: utils.formBody(payload || {}),
      });
    }
    const response = await fetch(path, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8',
        'X-Telegram-Init-Data': state.initData,
      },
      body: new URLSearchParams(payload || {}).toString(),
    });
    const html = await response.text();
    if (!response.ok) throw new Error(html || 'Could not load cases.');
    return html;
  }

  function notify(message, error) {
    const toast = $('toast');
    utils.haptic?.(error ? 'error' : 'success');
    if (utils.showToast) {
      utils.showToast(toast, message, { error, timeout: 5000, className: `toast visible${error ? ' error' : ''}`, resetClassName: 'toast' });
      return;
    }
    toast.textContent = message;
    toast.className = `toast visible${error ? ' error' : ''}`;
    window.clearTimeout(notify.timer);
    notify.timer = window.setTimeout(() => { toast.className = 'toast'; }, 5000);
  }

  function setLoading(loading) {
    $('loadingState').hidden = !loading;
    if (loading) { $('listView').hidden = true; $('createView').hidden = true; $('settingsView').hidden = true; $('detailView').hidden = true; }
  }

  function statusClass(status) { return `status-${String(status || 'Open').toLowerCase().replace(/\s+/g, '-')}`; }

  function callHref(phone) {
    const digits = String(phone || '').replace(/\D/g, '');
    if (!digits) return '';
    if (digits.startsWith('254')) return `tel:+${digits}`;
    if (digits.startsWith('0')) return `tel:+254${digits.slice(1)}`;
    return `tel:+${digits}`;
  }

  function renderCounts(counts) {
    $('openCount').textContent = counts.open || 0;
    $('progressCount').textContent = counts.in_progress || 0;
    $('closedCount').textContent = counts.closed || 0;
    $('totalCount').textContent = counts.total || 0;
    $('overdueCount').textContent = counts.overdue || 0;
  }

  function renderCases(cases, startIndex) {
    const list = $('caseList');
    list.innerHTML = cases.map((caseItem) => `
      <button type="button" class="case-row ${statusClass(caseItem.status)}" data-case-id="${escapeHtml(caseItem.case_id)}">
        <div><p class="case-id">${escapeHtml(caseItem.case_id)}</p><h2>${escapeHtml(caseItem.customer_name || 'Unnamed client')}</h2><p>${escapeHtml(caseItem.category || 'Complaint')} · ${escapeHtml(caseItem.branch || 'Branch not set')}</p><p>${escapeHtml(caseItem.customer_phone || caseItem.customer_id || 'No client identifier')}</p></div>
        <span class="status-pill">${escapeHtml(caseItem.status)}</span>
      </button>`).join('');
    $('emptyState').hidden = cases.length > 0;
    list.querySelectorAll('[data-case-id]').forEach((button, index) => {
      const caseItem = cases.find((item) => item.case_id === button.dataset.caseId);
      const caseIdNode = button.querySelector('.case-id');
      if (caseIdNode) caseIdNode.insertAdjacentHTML('afterbegin', `<span class="queue-number">#${Number(startIndex || 0) + index}</span> `);
      if (caseItem && caseItem.recorded_at) {
        const recorded = document.createElement('p');
        recorded.className = 'case-recorded';
        recorded.textContent = `Recorded ${caseItem.recorded_at}`;
        button.querySelector('div').append(recorded);
      }
      if (caseItem) {
        const controlLine = document.createElement('p');
        controlLine.className = 'case-control-line';
        controlLine.textContent = `${caseItem.assigned_to?.name || 'Unassigned'} · ${caseItem.priority || 'normal'} priority${caseItem.sla?.state === 'overdue' ? ' · Overdue' : ''}`;
        button.querySelector('div').append(controlLine);
      }
      button.addEventListener('click', () => loadDetail(button.dataset.caseId));
    });
  }

  function applyCapabilities() {
    document.querySelectorAll('[data-required-capability]').forEach((node) => {
      node.hidden = !state.capabilities.has(node.dataset.requiredCapability);
    });
  }

  function hydrateCaseRows(root) {
    root.querySelectorAll('[data-case-id]').forEach((button) => {
      button.onclick = () => loadDetail(button.dataset.caseId);
    });
  }

  async function renderCasesFragment() {
    if (!window.htmx) return false;
    try {
      const html = await fragmentPost('/api/complaints/cases/fragment/', {
        group_id: state.groupId,
        query: state.query,
        status: state.status,
        branch: state.branch,
        priority: state.priority,
        assignment: state.assignment,
        sla: state.sla,
        page: state.page,
      });
      const list = $('caseList');
      list.innerHTML = html;
      hydrateCaseRows(list);
      $('emptyState').hidden = !list.querySelector('[data-case-id]');
      $('queuePagination').hidden = true;
      return true;
    } catch (error) {
      return false;
    }
  }

  function activeFilterEntries() {
    const labels = {
      branch: state.branch,
      priority: state.priority ? `${state.priority} priority` : '',
      assignment: state.assignment === 'mine' ? 'Assigned to me' : (state.assignment === 'unassigned' ? 'Unassigned' : ''),
      sla: state.sla === 'overdue' ? 'Overdue' : (state.sla === 'due_soon' ? 'Due soon' : ''),
    };
    return Object.entries(labels).filter(([, value]) => value);
  }

  function renderActiveFilters() {
    const entries = activeFilterEntries();
    const root = $('activeQueueFilters');
    root.hidden = entries.length === 0;
    root.innerHTML = entries.map(([key, label]) => `<button type="button" class="filter-chip" data-remove-filter="${escapeHtml(key)}"><span>${escapeHtml(label)}</span><span aria-hidden="true">&times;</span></button>`).join('');
    $('openQueueFiltersBtn').classList.toggle('active', entries.length > 0);
    $('openQueueFiltersBtn').querySelector('b').hidden = entries.length === 0;
  }

  function renderQueueState() {
    const pages = Math.max(1, Number(state.pages || 1));
    $('queueResultCount').textContent = `${state.total} ${state.total === 1 ? 'case' : 'cases'}`;
    $('queuePageLabel').textContent = `Page ${state.page} of ${pages}`;
    $('queuePreviousBtn').disabled = state.page <= 1;
    $('queueNextBtn').disabled = state.page >= pages;
    $('queuePagination').hidden = pages <= 1;
    document.querySelectorAll('.filter-tabs button').forEach((node) => node.classList.toggle('active', node.dataset.status === state.status));
    renderActiveFilters();
  }

  async function loadCases(options) {
    const settings = options || {};
    const requestSequence = ++state.queueRequestSequence;
    const list = $('caseList');
    if (list && !settings.silent) {
      list.innerHTML = `<div class="mini-skeleton-list" role="status" aria-label="Loading complaint cases">${utils.skeletonCards ? utils.skeletonCards(3) : ''}</div>`;
      $('emptyState').hidden = true;
    }
    try {
      const response = await api('cases/', {
        query: state.query, status: state.status, branch: state.branch,
        priority: state.priority, assignment: state.assignment, sla: state.sla,
        page: state.page,
      });
      if (requestSequence !== state.queueRequestSequence) return false;
      state.nextCursor = response.next_cursor || '';
      state.page = Number(response.pagination?.page || 1);
      state.pages = Number(response.pagination?.pages || 1);
      state.total = Number(response.pagination?.total || 0);
      state.startIndex = Number(response.start_index || 0);
      renderCases(response.cases || [], state.startIndex);
      renderQueueState();
      rememberUi();
      if (settings.restoreScroll) window.requestAnimationFrame(() => window.scrollTo(0, state.queueScrollY));
      else if (settings.scrollTop) window.scrollTo(0, 0);
      return true;
    } catch (error) {
      if (requestSequence !== state.queueRequestSequence) return false;
      if (!settings.silent && await renderCasesFragment()) return true;
      notify(error.message, true);
      return false;
    }
  }

  async function bootstrap() {
    if (!state.groupId) { setLoading(false); notify('This launcher is missing its Telegram group. Open it from the group pin.', true); return; }
    setLoading(true);
    try {
      const response = await api('bootstrap/');
      const data = response.data || {};
      state.capabilities = new Set((data.actor && data.actor.capabilities) || []);
      state.assignees = data.assignees || [];
      applyCapabilities();
      $('actorLine').textContent = `${data.actor && data.actor.name || 'Staff'} · ${data.actor && data.actor.is_manager ? 'Case manager' : 'Case officer'}`;
      renderCounts(data.counts || {});
      renderCreateOptions(data);
      applyPersonalFilters(data.personal || {});
      renderBranchFilter(data.branches || []);
      renderPersonalSettings(data);
      renderAssignees();
      $('caseSearch').value = state.query;
      $('listView').hidden = false;
      await loadCases();
    } catch (error) {
      $('listView').hidden = false;
      window.requestAnimationFrame(() => window.scrollTo(0, state.queueScrollY));
      notify(error.message, true);
    }
    finally { setLoading(false); }
  }

  function renderDetail(caseItem) {
    state.currentCase = caseItem;
    $('detailCaseId').textContent = caseItem.case_id;
    $('detailName').textContent = caseItem.customer_name || 'Unnamed client';
    $('detailStatus').textContent = caseItem.status;
    $('detailStatus').className = `status-pill ${statusClass(caseItem.status)}`;
    $('detailDescription').textContent = caseItem.description || 'No complaint description was captured.';
    $('detailIdentifiers').innerHTML = detailIdentifiersMarkup(caseItem);
    $('detailMeta').textContent = [caseItem.category, caseItem.branch, caseItem.reported_at, caseItem.days_open != null ? `${caseItem.days_open} days open` : ''].filter(Boolean).join(' · ');
    $('statusInput').value = caseItem.status || 'Open';
    $('priorityInput').value = caseItem.priority || 'normal';
    $('assigneeInput').value = caseItem.assigned_to?.id || '';
    $('detailPriority').textContent = `${caseItem.priority || 'normal'} priority`;
    $('detailAssignment').textContent = caseItem.assigned_to?.name || 'Unassigned';
    $('detailSla').textContent = caseItem.sla?.state === 'overdue' ? `Overdue by ${Math.abs(caseItem.sla.remaining_hours || 0)}h` : `${caseItem.sla?.remaining_hours ?? '—'}h remaining`;
    $('detailSla').className = `control-chip sla-${caseItem.sla?.state || 'on_track'}`;
    $('detailSync').textContent = caseItem.sync_status === 'success' ? 'Register synced' : 'Register pending';
    $('detailSync').className = `control-chip sync-${caseItem.sync_status || 'pending'}`;
    $('claimBtn').hidden = !state.capabilities.has('complaint.case.claim') || Boolean(caseItem.assigned_to);
    $('syncRetryBtn').hidden = !state.capabilities.has('complaint.case.sync.retry') || caseItem.sync_status === 'success';
    renderMap(caseItem.location || {});
    renderEvidence(caseItem.evidence || []);
    renderActivity(caseItem.updates || []);
    $('activityDescription').textContent = caseItem.raw_message ? 'Full audit, including the original captured message.' : 'Case updates recorded by staff.';
  }

  function renderCreateOptions(data) {
    [['createBranchOptions', data.branches || []], ['createCategoryOptions', data.categories || []]].forEach(([id, values]) => {
      const list = $(id); list.replaceChildren();
      values.forEach((value) => { const option = document.createElement('option'); option.value = value; list.append(option); });
    });
  }

  function renderAssignees() {
    const select = $('assigneeInput');
    if (!select) return;
    select.innerHTML = '<option value="">Unassigned</option>' + state.assignees.map((item) => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.name)}</option>`).join('');
  }

  function renderBranchFilter(branches) {
    const select = $('branchFilter');
    const selected = state.branch;
    select.innerHTML = '<option value="">All branches</option>' + (branches || []).map((branch) => `<option value="${escapeHtml(branch)}">${escapeHtml(branch)}</option>`).join('');
    select.value = selected;
  }

  function filterSheetFocusable() {
    return Array.from($('queueFilterSheet').querySelectorAll('button:not([disabled]), select:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex="-1"])'));
  }

  function syncFilterControls() {
    $('branchFilter').value = state.branch;
    $('priorityFilter').value = state.priority;
    $('assignmentFilter').value = state.assignment;
    $('slaFilter').value = state.sla;
  }

  function openQueueFilters(trigger) {
    syncFilterControls();
    state.filterSheetOpen = true;
    state.filterSheetReturnFocus = trigger || document.activeElement;
    $('queueFilterOverlay').hidden = false;
    $('queueFilterOverlay').setAttribute('aria-hidden', 'false');
    document.body.classList.add('complaint-sheet-open');
    $('queueFilterSheet').focus();
    telegram?.BackButton?.show?.();
  }

  function closeQueueFilters(options) {
    if (!state.filterSheetOpen) return;
    state.filterSheetOpen = false;
    $('queueFilterOverlay').hidden = true;
    $('queueFilterOverlay').setAttribute('aria-hidden', 'true');
    document.body.classList.remove('complaint-sheet-open');
    if ($('detailView').hidden && $('createView').hidden && $('settingsView').hidden) telegram?.BackButton?.hide?.();
    if (!(options && options.restoreFocus === false)) state.filterSheetReturnFocus?.focus?.();
    state.filterSheetReturnFocus = null;
  }

  function trapFilterSheetFocus(event) {
    if (event.key !== 'Tab') return;
    const controls = filterSheetFocusable();
    if (!controls.length) return;
    const first = controls[0];
    const last = controls[controls.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  }

  async function applyQueueFilters() {
    state.branch = $('branchFilter').value;
    state.priority = $('priorityFilter').value;
    state.assignment = $('assignmentFilter').value;
    state.sla = $('slaFilter').value;
    state.page = 1;
    rememberUi();
    closeQueueFilters({ restoreFocus: false });
    await loadCases({ scrollTop: true });
    $('openQueueFiltersBtn').focus();
  }

  async function clearQueueFilters() {
    $('branchFilter').value = '';
    $('priorityFilter').value = '';
    $('assignmentFilter').value = '';
    $('slaFilter').value = '';
    await applyQueueFilters();
  }

  function renderPersonalSettings(data) {
    const personal = data.personal || {};
    state.personal = personal;
    const branch = $('complaintPreferenceBranch');
    branch.innerHTML = '<option value="">All branches</option>' + (data.branches || []).map((item) => `<option value="${escapeHtml(item)}">${escapeHtml(item)}</option>`).join('');
    $('complaintPreferenceStatus').value = personal.default_filters?.status || 'active';
    branch.value = personal.default_filters?.branch || '';
    $('complaintPreferenceCompact').checked = Boolean(personal.compact_cards);
    document.body.classList.toggle('complaint-compact-cards', Boolean(personal.compact_cards));
    if (utils.renderSettingsAccount) utils.renderSettingsAccount($('complaintSettingsAccount'), data.account || {});
    if ($('complaintSettingsRelease')) $('complaintSettingsRelease').textContent = data.account?.app_release || 'Current release';
  }

  function applyPersonalFilters(personal) {
    const filters = personal?.default_filters || {};
    // An interrupted session is more important than a default for the next
    // fresh launch, so only apply saved defaults when there is no local state.
    if (!restoredUi.status && filters.status) state.status = String(filters.status);
    if (!restoredUi.branch && filters.branch) state.branch = String(filters.branch);
  }

  function detailIdentifiersMarkup(caseItem) {
    const items = [];
    const phoneLink = callHref(caseItem.customer_phone);
    if (caseItem.customer_phone) {
      items.push(`
        <span class="identifier phone-identifier">
          <span>Phone: ${escapeHtml(caseItem.customer_phone)}</span>
          ${phoneLink ? `<a class="call-button" href="${escapeHtml(phoneLink)}" aria-label="Call ${escapeHtml(caseItem.customer_phone)}">
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" width="13" height="13" aria-hidden="true"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.8 19.8 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.12 4.18 2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.12.9.33 1.77.63 2.6a2 2 0 0 1-.45 2.11L8.02 9.7a16 16 0 0 0 6.28 6.28l1.27-1.27a2 2 0 0 1 2.11-.45c.83.3 1.7.51 2.6.63A2 2 0 0 1 22 16.92Z"/></svg>
            <span>Call</span>
          </a>` : ''}
        </span>
      `);
    }
    if (caseItem.customer_id) items.push(`<span class="identifier">ID: ${escapeHtml(caseItem.customer_id)}</span>`);
    return items.join('') || '<span class="identifier">No client ID or phone captured</span>';
  }

  function renderMap(location) {
    const mapNode = $('caseMap'); const mapLink = $('mapsLink'); const noLocation = $('noLocation');
    const latitude = Number(location.latitude); const longitude = Number(location.longitude);
    const hasCoordinates = Number.isFinite(latitude) && Number.isFinite(longitude) && (latitude || longitude);
    mapNode.hidden = !hasCoordinates; noLocation.hidden = hasCoordinates;
    mapLink.hidden = !location.url; mapLink.href = location.url || '#';
    if (!hasCoordinates || !window.L) return;
    if (!state.map) {
      state.map = window.L.map(mapNode, { zoomControl: false, attributionControl: false });
      window.L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19, attribution: '© OpenStreetMap' }).addTo(state.map);
    }
    state.map.setView([latitude, longitude], 15);
    if (state.marker) state.marker.setLatLng([latitude, longitude]); else state.marker = window.L.marker([latitude, longitude]).addTo(state.map);
    window.setTimeout(() => state.map.invalidateSize(), 10);
  }

  function renderEvidence(evidence) {
    $('evidenceList').innerHTML = evidence.length ? evidence.map((item) => `<div class="evidence-row"><span>${escapeHtml(item.name || 'Evidence file')}<br><small>${escapeHtml(utils.formatDateTime ? utils.formatDateTime(item.created_at) : item.created_at)} · ${escapeHtml(item.status)}</small></span>${item.url ? `<a href="${escapeHtml(item.url)}" target="_blank" rel="noopener">Open ↗</a>` : ''}</div>`).join('') : '<p class="empty-copy">No evidence has been uploaded yet.</p>';
  }

  function renderActivity(updates) {
    $('activityList').innerHTML = updates.length ? updates.map((item) => `<article class="activity-row"><strong>${escapeHtml(item.status || 'Case updated')} · ${escapeHtml(item.updated_by || 'Staff')}</strong>${item.note ? `<p>${escapeHtml(item.note)}</p>` : ''}<small>${escapeHtml(utils.formatDateTime ? utils.formatDateTime(item.created_at) : item.created_at)}</small></article>`).join('') : '<p class="empty-copy">No staff updates have been recorded yet.</p>';
  }

  async function loadDetail(caseId) {
    state.queueScrollY = window.scrollY;
    setLoading(true);
    try {
      const response = await api(`cases/${encodeURIComponent(caseId)}/`);
      renderDetail(response.case);
      $('listView').hidden = true; $('detailView').hidden = false;
      window.scrollTo({ top: 0, behavior: 'instant' });
      telegram?.BackButton?.show();
    } catch (error) {
      $('listView').hidden = false;
      window.requestAnimationFrame(() => window.scrollTo(0, state.queueScrollY));
      notify(error.message, true);
    }
    finally { setLoading(false); }
  }

  function selectedFiles() {
    const files = Array.from($('evidenceInput').files || []);
    $('selectedEvidence').innerHTML = files.map((file) => `<li>${escapeHtml(file.name)} · ${Math.ceil(file.size / 1024)} KB</li>`).join('');
  }

  function selectedCreateFiles() {
    const files = Array.from($('createEvidenceInput').files || []);
    $('createSelectedEvidence').innerHTML = files.map((file) => `<li>${escapeHtml(file.name)} &middot; ${Math.ceil(file.size / 1024)} KB</li>`).join('');
  }

  function captureLocation() {
    if (!navigator.geolocation) { notify('Location capture is not available in this browser.', true); return; }
    const button = $('captureLocationBtn'); button.disabled = true; button.textContent = 'Capturing location…';
    navigator.geolocation.getCurrentPosition((position) => {
      state.capturedLocation = { latitude: position.coords.latitude.toFixed(6), longitude: position.coords.longitude.toFixed(6) };
      $('captureState').textContent = `Location ready: ${state.capturedLocation.latitude}, ${state.capturedLocation.longitude}`;
      button.disabled = false; button.textContent = 'Use my current location';
    }, () => { button.disabled = false; button.textContent = 'Use my current location'; notify('We could not access your location. Check Telegram and browser permissions.', true); }, { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 });
  }

  function captureCreateLocation() {
    if (!navigator.geolocation) { notify('Location capture is not available in this browser.', true); return; }
    const button = $('createCaptureLocationBtn'); button.disabled = true; button.textContent = 'Capturing location…';
    navigator.geolocation.getCurrentPosition((position) => {
      state.createCapturedLocation = { latitude: position.coords.latitude.toFixed(6), longitude: position.coords.longitude.toFixed(6) };
      $('createCaptureState').textContent = `Location ready: ${state.createCapturedLocation.latitude}, ${state.createCapturedLocation.longitude}`;
      button.disabled = false; button.textContent = 'Use my current location';
    }, () => { button.disabled = false; button.textContent = 'Use my current location'; notify('We could not access your location. Check Telegram and browser permissions.', true); }, { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 });
  }

  async function submitUpdate(event) {
    event.preventDefault();
    if (!state.currentCase || state.submitting) return;
    state.submitting = true;
    const button = $('saveBtn'); button.setAttribute('aria-busy', 'true'); button.querySelector('span').textContent = 'Saving…';
    const formData = new FormData();
    state.pendingUpdateRequestId = state.pendingUpdateRequestId || requestId();
    formData.set('status', $('statusInput').value); formData.set('resolution_text', $('noteInput').value); formData.set('client_request_id', state.pendingUpdateRequestId);
    formData.set('expected_revision', state.currentCase.revision);
    if (state.capabilities.has('complaint.case.assign')) {
      formData.set('assigned_to', $('assigneeInput').value);
      formData.set('priority', $('priorityInput').value);
      if (!$('assigneeInput').value && state.currentCase.assigned_to) formData.set('assignment_action', 'unassign');
    }
    if (state.capturedLocation) { formData.set('latitude', state.capturedLocation.latitude); formData.set('longitude', state.capturedLocation.longitude); }
    Array.from($('evidenceInput').files || []).forEach((file) => formData.append('evidence', file));
    try {
      const response = await api(`cases/${encodeURIComponent(state.currentCase.case_id)}/update/`, null, formData);
      renderDetail(response.case); $('noteInput').value = ''; $('evidenceInput').value = ''; $('selectedEvidence').innerHTML = ''; state.capturedLocation = null; $('captureState').textContent = 'No new location selected';
      syncClosingConfirmation();
      state.pendingUpdateRequestId = '';
      state.queueDirty = true;
      notify(response.message || 'Case update saved.'); await refreshCounts();
    } catch (error) { notify(error.message, true); }
    finally { state.submitting = false; button.disabled = false; button.removeAttribute('aria-busy'); button.querySelector('span').textContent = 'Save update'; }
  }

  async function submitCreate(event) {
    event.preventDefault();
    const form = $('createCaseForm');
    if (!form.reportValidity()) return;
    if (state.submitting) return;
    state.submitting = true;
    const button = $('createSaveBtn'); button.setAttribute('aria-busy', 'true'); button.querySelector('span').textContent = 'Creating…';
    const formData = new FormData(form);
    state.pendingCreateRequestId = state.pendingCreateRequestId || requestId();
    formData.set('client_request_id', state.pendingCreateRequestId);
    if (state.createCapturedLocation) {
      formData.set('latitude', state.createCapturedLocation.latitude);
      formData.set('longitude', state.createCapturedLocation.longitude);
    }
    try {
      const response = await api('cases/create/', null, formData);
      renderDetail(response.case);
      state.pendingCreateRequestId = '';
      form.reset(); $('createSelectedEvidence').innerHTML = ''; state.createCapturedLocation = null;
      syncClosingConfirmation();
      $('createCaptureState').textContent = 'Location is optional';
      $('createView').hidden = true; $('detailView').hidden = false;
      state.queueDirty = true;
      notify(response.message || 'Complaint created.');
      await refreshCounts();
    } catch (error) { notify(error.message, true); }
    finally { state.submitting = false; button.disabled = false; button.removeAttribute('aria-busy'); button.querySelector('span').textContent = 'Create complaint'; }
  }

  async function refreshCounts() {
    const response = await api('bootstrap/'); renderCounts((response.data || {}).counts || {});
  }

  async function refreshWorkspace() {
    const button = $('refreshBtn');
    if (button.disabled) return;
    button.disabled = true;
    button.setAttribute('aria-busy', 'true');
    try {
      await refreshCounts();
      const loaded = await loadCases({ silent: true, restoreScroll: true });
      if (loaded) notify('Complaint queue refreshed.');
    } catch (error) {
      notify(error.message, true);
    } finally {
      button.disabled = false;
      button.removeAttribute('aria-busy');
    }
  }

  function showComplaintView(view) {
    if (state.filterSheetOpen) closeQueueFilters({ restoreFocus: false });
    const showCreate = view === 'create';
    const showSettings = view === 'settings';
    $('listView').hidden = !(view === 'queue' || view === 'find');
    $('createView').hidden = !showCreate;
    $('settingsView').hidden = !showSettings;
    $('detailView').hidden = true;
    if (view === 'queue' || view === 'find') telegram?.BackButton?.hide(); else telegram?.BackButton?.show();
    document.querySelectorAll('#complaintTabs [data-view]').forEach((button) => {
      button.classList.toggle('active', button.dataset.view === view);
    });
    if (view === 'find') {
      $('caseSearch').focus();
    }
  }

  function applyStatusFilter(status) {
    state.status = status || 'active';
    state.page = 1;
    rememberUi();
    document.querySelectorAll('.filter-tabs button').forEach((node) => node.classList.toggle('active', node.dataset.status === state.status));
    showComplaintView('queue');
    loadCases({ scrollTop: true });
  }

  function applyMetricFilter(metric) {
    state.sla = '';
    if (metric === 'open') state.status = 'Open';
    else if (metric === 'in_progress') state.status = 'In Progress';
    else if (metric === 'closed') state.status = 'Closed';
    else if (metric === 'overdue') { state.status = 'active'; state.sla = 'overdue'; }
    else state.status = 'all';
    state.page = 1;
    showComplaintView('queue');
    rememberUi();
    loadCases({ scrollTop: true });
  }

  async function claimCurrentCase() {
    if (!state.currentCase || state.submitting) return;
    state.submitting = true;
    const button = $('claimBtn'); button.disabled = true;
    const formData = new FormData();
    formData.set('status', state.currentCase.status || 'Open');
    formData.set('assignment_action', 'claim');
    formData.set('expected_revision', state.currentCase.revision);
    formData.set('client_request_id', requestId());
    try {
      const response = await api(`cases/${encodeURIComponent(state.currentCase.case_id)}/update/`, null, formData);
      renderDetail(response.case); state.queueDirty = true; notify('Case assigned to you.');
    } catch (error) { notify(error.message, true); }
    finally { state.submitting = false; button.disabled = false; }
  }

  async function retryCurrentSync() {
    if (!state.currentCase || state.submitting) return;
    state.submitting = true;
    const button = $('syncRetryBtn'); button.disabled = true;
    try {
      const response = await api(`cases/${encodeURIComponent(state.currentCase.case_id)}/sync-retry/`, { client_request_id: requestId() });
      renderDetail(response.case); notify(response.message || 'Register sync retried.');
    } catch (error) { notify(error.message, true); }
    finally { state.submitting = false; button.disabled = false; }
  }

  document.querySelectorAll('.filter-tabs button').forEach((button) => button.addEventListener('click', () => applyStatusFilter(button.dataset.status)));
  document.querySelectorAll('[data-metric-filter]').forEach((button) => button.addEventListener('click', () => applyMetricFilter(button.dataset.metricFilter)));
  $('openQueueFiltersBtn').addEventListener('click', (event) => openQueueFilters(event.currentTarget));
  $('closeQueueFiltersBtn').addEventListener('click', () => closeQueueFilters());
  $('queueFilterOverlay').addEventListener('click', (event) => { if (event.target === event.currentTarget) closeQueueFilters(); });
  $('queueFilterSheet').addEventListener('keydown', trapFilterSheetFocus);
  $('queueFilterForm').addEventListener('submit', (event) => { event.preventDefault(); applyQueueFilters(); });
  $('resetQueueFiltersBtn').addEventListener('click', clearQueueFilters);
  $('activeQueueFilters').addEventListener('click', (event) => {
    const chip = event.target.closest('[data-remove-filter]');
    if (!chip) return;
    state[chip.dataset.removeFilter] = '';
    state.page = 1;
    rememberUi();
    loadCases({ scrollTop: true });
  });
  $('queuePreviousBtn').addEventListener('click', () => {
    if (state.page <= 1) return;
    state.page -= 1;
    loadCases({ scrollTop: true });
  });
  $('queueNextBtn').addEventListener('click', () => {
    if (state.page >= state.pages) return;
    state.page += 1;
    loadCases({ scrollTop: true });
  });
  $('caseSearch').addEventListener('input', (event) => {
    state.query = event.target.value;
    state.page = 1;
    rememberUi();
    window.clearTimeout(state.debounce);
    if (!state.query) loadCases({ scrollTop: true });
    else state.debounce = window.setTimeout(() => loadCases({ scrollTop: true }), 250);
  });
  $('refreshBtn').addEventListener('click', refreshWorkspace);
  document.querySelectorAll('#complaintTabs [data-view]').forEach((button) => button.addEventListener('click', () => showComplaintView(button.dataset.view)));
  $('cancelCreateBtn').addEventListener('click', returnToQueue);
  $('backBtn').addEventListener('click', returnToQueue);
  $('claimBtn').addEventListener('click', claimCurrentCase);
  $('syncRetryBtn').addEventListener('click', retryCurrentSync);
  $('captureLocationBtn').addEventListener('click', captureLocation);
  $('createCaptureLocationBtn').addEventListener('click', captureCreateLocation);
  $('evidenceInput').addEventListener('change', selectedFiles);
  $('evidenceList').addEventListener('click', async (event) => {
    const link = event.target.closest('a[href*="/api/complaints/evidence/"]');
    if (!link) return;
    event.preventDefault();
    const path = link.getAttribute('href').replace('/api/complaints/', '');
    try {
      const response = await api(path);
      if (telegram?.openLink) telegram.openLink(response.url); else window.open(response.url, '_blank', 'noopener');
    } catch (error) { notify(error.message, true); }
  });
  $('createEvidenceInput').addEventListener('change', selectedCreateFiles);
  $('updateForm').addEventListener('submit', submitUpdate);
  $('createCaseForm').addEventListener('submit', submitCreate);
  ['createCaseForm', 'updateForm'].forEach((id) => {
    $(id).addEventListener('input', syncClosingConfirmation);
    $(id).addEventListener('change', syncClosingConfirmation);
  });
  telegram?.BackButton?.onClick(() => {
    if (state.filterSheetOpen) return closeQueueFilters();
    if (!$('detailView').hidden || !$('createView').hidden || !$('settingsView').hidden) {
      returnToQueue();
    }
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && state.filterSheetOpen) closeQueueFilters();
  });
  const ensureFocusedInputVisible = () => {
    const focused = document.activeElement;
    if (!focused || !focused.matches('input, select, textarea')) return;
    const viewportHeight = window.visualViewport?.height || window.innerHeight;
    const action = focused.closest('form')?.querySelector('.sticky-actions');
    const lowerLimit = viewportHeight - (action?.getBoundingClientRect().height || 0) - 12;
    const rect = focused.getBoundingClientRect();
    if (rect.bottom > lowerLimit) window.scrollBy({ top: rect.bottom - lowerLimit + 10, behavior: 'smooth' });
  };
  const updateViewport = () => {
    const height = window.visualViewport?.height || window.innerHeight;
    document.documentElement.style.setProperty('--complaint-viewport-height', `${height}px`);
    window.requestAnimationFrame(ensureFocusedInputVisible);
  };
  window.visualViewport?.addEventListener('resize', updateViewport);
  telegram?.onEvent?.('viewportChanged', updateViewport);
  document.addEventListener('focusin', () => window.setTimeout(ensureFocusedInputVisible, 80));
  updateViewport();
  $('complaintSettingsForm').addEventListener('submit', async (event) => {
    event.preventDefault();
    const button = $('saveComplaintSettingsBtn');
    button.disabled = true;
    button.textContent = 'Saving…';
    try {
      const result = await api('settings/personal/', {
        preferences: {
          default_screen: 'queue',
          default_filters: {
            status: $('complaintPreferenceStatus').value,
            branch: $('complaintPreferenceBranch').value,
          },
          compact_cards: $('complaintPreferenceCompact').checked,
        },
      });
      state.personal = result.data || state.personal;
      document.body.classList.toggle('complaint-compact-cards', $('complaintPreferenceCompact').checked);
      notify('Your Complaint Case settings were saved.');
    } catch (error) {
      notify(error.message, true);
    } finally {
      button.disabled = false;
      button.textContent = 'Save my settings';
    }
  });
  configureHtmx();
  bootstrap();
}());
