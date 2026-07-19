(function () {
  const telegram = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
  if (telegram) { telegram.ready(); telegram.expand(); }

  const state = {
    groupId: document.body.dataset.groupId || '',
    initData: telegram ? telegram.initData || '' : '',
    status: 'active', query: '', currentCase: null, map: null, marker: null,
    capturedLocation: null, debounce: null,
  };
  const $ = (id) => document.getElementById(id);
  const escapeHtml = (value) => String(value == null ? '' : value).replace(/[&<>"']/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[character]));
  const requestId = () => window.crypto && window.crypto.randomUUID ? window.crypto.randomUUID() : `complaint-${Date.now()}-${Math.random().toString(36).slice(2)}`;

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
    if (loading) { $('listView').hidden = true; $('detailView').hidden = true; }
  }

  function statusClass(status) { return `status-${String(status || 'Open').toLowerCase().replace(/\s+/g, '-')}`; }

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
    list.querySelectorAll('[data-case-id]').forEach((button) => button.addEventListener('click', () => loadDetail(button.dataset.caseId)));
  }

  async function loadCases() {
    try {
      const response = await api('cases/', { query: state.query, status: state.status });
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
    $('detailIdentifiers').innerHTML = [caseItem.customer_phone && `Phone: ${caseItem.customer_phone}`, caseItem.customer_id && `ID: ${caseItem.customer_id}`].filter(Boolean).map((item) => `<span class="identifier">${escapeHtml(item)}</span>`).join('') || '<span class="identifier">No client ID or phone captured</span>';
    $('detailMeta').textContent = [caseItem.category, caseItem.branch, caseItem.reported_at, caseItem.days_open != null ? `${caseItem.days_open} days open` : ''].filter(Boolean).join(' · ');
    $('statusInput').value = caseItem.status || 'Open';
    renderMap(caseItem.location || {});
    renderEvidence(caseItem.evidence || []);
    renderActivity(caseItem.updates || []);
    $('activityDescription').textContent = caseItem.raw_message ? 'Full audit, including the original captured message.' : 'Case updates recorded by staff.';
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

  function captureLocation() {
    if (!navigator.geolocation) { notify('Location capture is not available in this browser.', true); return; }
    const button = $('captureLocationBtn'); button.disabled = true; button.textContent = 'Capturing location…';
    navigator.geolocation.getCurrentPosition((position) => {
      state.capturedLocation = { latitude: position.coords.latitude.toFixed(6), longitude: position.coords.longitude.toFixed(6) };
      $('captureState').textContent = `Location ready: ${state.capturedLocation.latitude}, ${state.capturedLocation.longitude}`;
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

  async function refreshCounts() {
    const response = await api('bootstrap/'); renderCounts((response.data || {}).counts || {});
  }

  document.querySelectorAll('.filter-tabs button').forEach((button) => button.addEventListener('click', () => { state.status = button.dataset.status; document.querySelectorAll('.filter-tabs button').forEach((node) => node.classList.toggle('active', node === button)); loadCases(); }));
  $('caseSearch').addEventListener('input', (event) => { state.query = event.target.value; window.clearTimeout(state.debounce); state.debounce = window.setTimeout(loadCases, 250); });
  $('refreshBtn').addEventListener('click', () => window.location.reload());
  $('backBtn').addEventListener('click', () => { $('detailView').hidden = true; $('listView').hidden = false; loadCases(); });
  $('captureLocationBtn').addEventListener('click', captureLocation);
  $('evidenceInput').addEventListener('change', selectedFiles);
  $('updateForm').addEventListener('submit', submitUpdate);
  bootstrap();
}());
