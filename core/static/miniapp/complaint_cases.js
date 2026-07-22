(function () {
  const telegram = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
  if (telegram) { telegram.ready(); telegram.expand(); }

  const state = {
    groupId: document.body.dataset.groupId || '',
    initData: telegram ? telegram.initData || '' : '',
    status: 'active', branch: '', query: '', currentCase: null, map: null, marker: null,
    capturedLocation: null, createCapturedLocation: null, debounce: null,
  };
  const $ = (id) => document.getElementById(id);
  const escapeHtml = (value) => String(value == null ? '' : value).replace(/[&<>"']/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[character]));
  const requestId = () => window.crypto && window.crypto.randomUUID ? window.crypto.randomUUID() : `complaint-${Date.now()}-${Math.random().toString(36).slice(2)}`;

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
    if (formData) formData.set('group_id', state.groupId);
    const options = { method: 'POST', headers: { 'X-Telegram-Init-Data': state.initData } };
    if (formData) options.body = formData;
    else { options.headers['Content-Type'] = 'application/json'; options.body = JSON.stringify(data); }
    const response = await fetch(`/api/complaints/${path}`, options);
    const result = await response.json().catch(() => ({}));
    if (!response.ok || !result.ok) throw new Error(result.error || 'Request failed.');
    return result;
  }

  function notify(message, error) {
    const toast = $('toast');
    toast.textContent = message;
    toast.className = `toast visible${error ? ' error' : ''}`;
    window.clearTimeout(notify.timer);
    notify.timer = window.setTimeout(() => { toast.className = 'toast'; }, 5000);
  }

  function setLoading(loading) {
    $('loadingState').hidden = !loading;
    if (loading) { $('listView').hidden = true; $('createView').hidden = true; $('detailView').hidden = true; }
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
  }

  function renderCases(cases) {
    const list = $('caseList');
    list.innerHTML = cases.map((caseItem) => `
      <button type="button" class="case-row ${statusClass(caseItem.status)}" data-case-id="${escapeHtml(caseItem.case_id)}">
        <div><p class="case-id">${escapeHtml(caseItem.case_id)}</p><h2>${escapeHtml(caseItem.customer_name || 'Unnamed client')}</h2><p>${escapeHtml(caseItem.category || 'Complaint')} · ${escapeHtml(caseItem.branch || 'Branch not set')}</p><p>${escapeHtml(caseItem.customer_phone || caseItem.customer_id || 'No client identifier')}</p></div>
        <span class="status-pill">${escapeHtml(caseItem.status)}</span>
      </button>`).join('');
    $('emptyState').hidden = cases.length > 0;
    list.querySelectorAll('[data-case-id]').forEach((button) => {
      const caseItem = cases.find((item) => item.case_id === button.dataset.caseId);
      if (caseItem && caseItem.recorded_at) {
        const recorded = document.createElement('p');
        recorded.className = 'case-recorded';
        recorded.textContent = `Recorded ${caseItem.recorded_at}`;
        button.querySelector('div').append(recorded);
      }
      button.addEventListener('click', () => loadDetail(button.dataset.caseId));
    });
  }

  function hydrateCaseRows(root) {
    root.querySelectorAll('[data-case-id]').forEach((button) => {
      if (button.dataset.bound === '1') return;
      button.dataset.bound = '1';
      button.addEventListener('click', () => loadDetail(button.dataset.caseId));
    });
  }

  function renderCasesFragment() {
    if (!window.htmx) return false;
    window.htmx.ajax('POST', '/api/complaints/cases/fragment/', {
      target: '#caseList',
      swap: 'innerHTML',
      values: {
        group_id: state.groupId,
        query: state.query,
        status: state.status,
        branch: state.branch,
      },
    });
    return true;
  }

  async function loadCases() {
    if (renderCasesFragment()) return;
    try {
      const response = await api('cases/', { query: state.query, status: state.status, branch: state.branch });
      renderCases(response.cases || []);
    } catch (error) { notify(error.message, true); }
  }

  async function bootstrap() {
    if (!state.groupId) { setLoading(false); notify('This launcher is missing its Telegram group. Open it from the group pin.', true); return; }
    setLoading(true);
    try {
      const response = await api('bootstrap/');
      const data = response.data || {};
      $('actorLine').textContent = `${data.actor && data.actor.name || 'Staff'} · ${data.actor && data.actor.is_manager ? 'Case manager' : 'Case officer'}`;
      renderCounts(data.counts || {});
      renderCreateOptions(data);
      renderBranchFilter(data.branches || []);
      $('listView').hidden = false;
      await loadCases();
    } catch (error) { notify(error.message, true); }
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

  function renderBranchFilter(branches) {
    const select = $('branchFilter');
    const selected = state.branch;
    select.innerHTML = '<option value="">All branches</option>' + (branches || []).map((branch) => `<option value="${escapeHtml(branch)}">${escapeHtml(branch)}</option>`).join('');
    select.value = selected;
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
    $('evidenceList').innerHTML = evidence.length ? evidence.map((item) => `<div class="evidence-row"><span>${escapeHtml(item.name || 'Evidence file')}<br><small>${escapeHtml(item.created_at)} · ${escapeHtml(item.status)}</small></span>${item.url ? `<a href="${escapeHtml(item.url)}" target="_blank" rel="noopener">Open ↗</a>` : ''}</div>`).join('') : '<p class="empty-copy">No evidence has been uploaded yet.</p>';
  }

  function renderActivity(updates) {
    $('activityList').innerHTML = updates.length ? updates.map((item) => `<article class="activity-row"><strong>${escapeHtml(item.status || 'Case updated')} · ${escapeHtml(item.updated_by || 'Staff')}</strong>${item.note ? `<p>${escapeHtml(item.note)}</p>` : ''}<small>${escapeHtml(item.created_at)}</small></article>`).join('') : '<p class="empty-copy">No staff updates have been recorded yet.</p>';
  }

  async function loadDetail(caseId) {
    setLoading(true);
    try {
      const response = await api(`cases/${encodeURIComponent(caseId)}/`);
      renderDetail(response.case);
      $('listView').hidden = true; $('detailView').hidden = false;
    } catch (error) { notify(error.message, true); }
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
    if (!state.currentCase) return;
    const button = $('saveBtn'); button.setAttribute('aria-busy', 'true'); button.querySelector('span').textContent = 'Saving…';
    const formData = new FormData();
    formData.set('status', $('statusInput').value); formData.set('resolution_text', $('noteInput').value); formData.set('client_request_id', requestId());
    if (state.capturedLocation) { formData.set('latitude', state.capturedLocation.latitude); formData.set('longitude', state.capturedLocation.longitude); }
    Array.from($('evidenceInput').files || []).forEach((file) => formData.append('evidence', file));
    try {
      const response = await api(`cases/${encodeURIComponent(state.currentCase.case_id)}/update/`, null, formData);
      renderDetail(response.case); $('noteInput').value = ''; $('evidenceInput').value = ''; $('selectedEvidence').innerHTML = ''; state.capturedLocation = null; $('captureState').textContent = 'No new location selected';
      notify(response.message || 'Case update saved.'); await refreshCounts();
    } catch (error) { notify(error.message, true); }
    finally { button.removeAttribute('aria-busy'); button.querySelector('span').textContent = 'Save update'; }
  }

  async function submitCreate(event) {
    event.preventDefault();
    const form = $('createCaseForm');
    if (!form.reportValidity()) return;
    const button = $('createSaveBtn'); button.setAttribute('aria-busy', 'true'); button.querySelector('span').textContent = 'Creating…';
    const formData = new FormData(form);
    formData.set('client_request_id', requestId());
    if (state.createCapturedLocation) {
      formData.set('latitude', state.createCapturedLocation.latitude);
      formData.set('longitude', state.createCapturedLocation.longitude);
    }
    try {
      const response = await api('cases/create/', null, formData);
      renderDetail(response.case);
      form.reset(); $('createSelectedEvidence').innerHTML = ''; state.createCapturedLocation = null;
      $('createCaptureState').textContent = 'Location is optional';
      $('createView').hidden = true; $('detailView').hidden = false;
      notify(response.message || 'Complaint created.');
      await refreshCounts();
    } catch (error) { notify(error.message, true); }
    finally { button.removeAttribute('aria-busy'); button.querySelector('span').textContent = 'Create complaint'; }
  }

  async function refreshCounts() {
    const response = await api('bootstrap/'); renderCounts((response.data || {}).counts || {});
  }

  function showComplaintView(view) {
    const showCreate = view === 'create';
    $('listView').hidden = showCreate;
    $('createView').hidden = !showCreate;
    $('detailView').hidden = true;
    document.querySelectorAll('#complaintTabs [data-view]').forEach((button) => {
      button.classList.toggle('active', button.dataset.view === view);
    });
    if (view === 'find') {
      $('caseSearch').focus();
    }
  }

  function applyStatusFilter(status) {
    state.status = status || 'active';
    document.querySelectorAll('.filter-tabs button').forEach((node) => node.classList.toggle('active', node.dataset.status === state.status));
    showComplaintView('queue');
    loadCases();
  }

  document.querySelectorAll('.filter-tabs button').forEach((button) => button.addEventListener('click', () => applyStatusFilter(button.dataset.status)));
  document.querySelectorAll('[data-status-filter]').forEach((button) => button.addEventListener('click', () => applyStatusFilter(button.dataset.statusFilter)));
  $('branchFilter').addEventListener('change', (event) => { state.branch = event.target.value; loadCases(); });
  $('caseSearch').addEventListener('input', (event) => { state.query = event.target.value; window.clearTimeout(state.debounce); state.debounce = window.setTimeout(loadCases, 250); });
  $('refreshBtn').addEventListener('click', () => window.location.reload());
  document.querySelectorAll('#complaintTabs [data-view]').forEach((button) => button.addEventListener('click', () => showComplaintView(button.dataset.view)));
  $('cancelCreateBtn').addEventListener('click', () => { showComplaintView('queue'); loadCases(); });
  $('backBtn').addEventListener('click', () => { showComplaintView('queue'); loadCases(); });
  $('captureLocationBtn').addEventListener('click', captureLocation);
  $('createCaptureLocationBtn').addEventListener('click', captureCreateLocation);
  $('evidenceInput').addEventListener('change', selectedFiles);
  $('createEvidenceInput').addEventListener('change', selectedCreateFiles);
  $('updateForm').addEventListener('submit', submitUpdate);
  $('createCaseForm').addEventListener('submit', submitCreate);
  configureHtmx();
  bootstrap();
}());
