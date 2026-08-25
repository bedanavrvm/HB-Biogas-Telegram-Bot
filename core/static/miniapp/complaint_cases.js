(function () {
  'use strict';
  const telegram = window.Telegram && window.Telegram.WebApp;
  const apiClient = window.ComplaintCasesMiniAppApi;
  const utils = window.MiniAppUtils || {};
  const $ = (id) => document.getElementById(id);
  const state = { groupId: document.body.dataset.groupId || '', initData: telegram?.initData || '', status: 'pending', query: '', page: 1, pages: 1, capabilities: new Set(), currentCase: null, submitting: false, debounce: null, latitude: '', longitude: '' };

  function requestId() { return utils.createRequestId ? utils.createRequestId('complaint') : `complaint-${Date.now()}-${Math.random().toString(16).slice(2)}`; }
  function can(key) { return state.capabilities.has(key); }
  function notify(message, error) { const node = $('toast'); node.textContent = message || ''; node.classList.toggle('error', !!error); node.classList.add('visible'); clearTimeout(node._timer); node._timer = setTimeout(() => node.classList.remove('visible'), 3500); }
  function json(path, payload) { return apiClient.postJson(path, Object.assign({ group_id: state.groupId }, payload || {}), state.initData, utils); }
  function form(path, data) { return apiClient.postForm(path, data, state.initData, state.groupId, utils); }
  function setView(name) { ['queueView', 'createView', 'detailView'].forEach((id) => { $(id).hidden = id !== name; }); $('loadingState').hidden = true; telegram?.BackButton?.[name === 'queueView' ? 'hide' : 'show'](); window.scrollTo({ top: 0, behavior: 'instant' }); }
  function optionList(id, values) { const list = $(id); list.replaceChildren(); (values || []).forEach((value) => { const option = document.createElement('option'); option.value = value; list.appendChild(option); }); }

  async function bootstrap() {
    telegram?.ready(); telegram?.expand();
    try {
      const response = await json('bootstrap/'); const data = response.data;
      state.capabilities = new Set(data.actor.capabilities || []);
      $('actorLine').textContent = `${data.actor.name} · ${data.actor.role}`;
      $('pendingCount').textContent = data.counts.pending || 0; $('resolvedCount').textContent = data.counts.resolved || 0; $('totalCount').textContent = data.counts.total || 0;
      $('newCaseBtn').hidden = !can('complaint.case.create');
      optionList('branchOptions', data.branches); optionList('categoryOptions', data.categories);
      setView('queueView'); await loadCases();
    } catch (error) { $('loadingState').textContent = error.message || 'Complaint Cases could not be opened.'; notify(error.message, true); }
  }

  async function loadCases() {
    $('caseList').replaceChildren(Object.assign(document.createElement('p'), { className: 'empty', textContent: 'Loading cases...' }));
    try {
      const response = await json('cases/', { status: state.status, query: state.query, page: state.page });
      const pagination = response.pagination || { page: 1, pages: 1, total: response.cases.length };
      state.page = pagination.page; state.pages = pagination.pages;
      $('queueResultCount').textContent = `${pagination.total} case${pagination.total === 1 ? '' : 's'}`;
      renderCases(response.cases || [], response.start_index || 0);
      $('queuePagination').hidden = pagination.pages <= 1; $('queuePageLabel').textContent = `Page ${pagination.page} of ${pagination.pages}`;
      $('queuePreviousBtn').disabled = pagination.page <= 1; $('queueNextBtn').disabled = pagination.page >= pagination.pages;
    } catch (error) { $('caseList').replaceChildren(Object.assign(document.createElement('p'), { className: 'empty', textContent: 'Cases could not be loaded.' })); notify(error.message, true); }
  }

  function renderCases(cases, start) {
    const list = $('caseList'); list.replaceChildren();
    if (!cases.length) { list.appendChild(Object.assign(document.createElement('p'), { className: 'empty', textContent: 'No cases match this view.' })); return; }
    cases.forEach((item, index) => {
      const button = document.createElement('button'); button.type = 'button'; button.className = 'case-row'; button.dataset.caseId = item.case_id;
      const text = document.createElement('div');
      const reference = Object.assign(document.createElement('p'), { className: 'case-reference', textContent: `#${start + index} · ${item.case_id}` });
      const name = Object.assign(document.createElement('h2'), { textContent: item.customer_name || 'Unnamed customer' });
      const identifier = item.customer_phone || item.customer_id || 'No customer identifier';
      const subtitle = Object.assign(document.createElement('p'), { className: 'case-subtitle', textContent: `${identifier} · ${item.category || 'Complaint'} · ${item.branch || 'Branch not set'}` });
      const age = Object.assign(document.createElement('p'), { className: 'case-age', textContent: item.age_label || '' });
      text.append(reference, name, subtitle, age);
      const status = Object.assign(document.createElement('span'), { className: `status-pill ${item.status === 'Resolved' ? 'resolved' : ''}`, textContent: item.status });
      button.append(text, status); button.addEventListener('click', () => openCase(item.case_id)); list.appendChild(button);
    });
  }

  async function openCase(caseId) {
    try { const response = await json(`cases/${encodeURIComponent(caseId)}/`); renderDetail(response.case); setView('detailView'); } catch (error) { notify(error.message, true); }
  }

  function renderDetail(item, preserveDraft) {
    state.currentCase = item; $('detailCaseId').textContent = item.case_id; $('detailName').textContent = item.customer_name || 'Unnamed customer';
    $('detailStatus').textContent = item.status; $('detailStatus').className = `status-pill ${item.status === 'Resolved' ? 'resolved' : ''}`;
    const ids = $('detailIdentifiers'); ids.replaceChildren(); [item.customer_phone, item.customer_id].filter(Boolean).forEach((value) => ids.appendChild(Object.assign(document.createElement('span'), { textContent: value })));
    $('detailDescription').textContent = item.description || 'No description recorded.';
    const meta = $('detailMeta'); meta.replaceChildren(); [item.category, item.branch, item.reported_at].filter(Boolean).forEach((value) => meta.appendChild(Object.assign(document.createElement('span'), { textContent: value })));
    const source = item.source_attribution || {}; $('detailSource').textContent = source.type === 'batch' ? `${source.label} · ${source.actor} · ${source.created_at}` : (source.label || 'Source unavailable');
    renderHistory(item); renderEvidence(item.evidence || []); renderActivity(item.updates || []);
    $('resolveForm').hidden = item.status !== 'Pending' || !can('complaint.case.close'); $('reopenForm').hidden = item.status !== 'Resolved' || !can('complaint.case.reopen');
    if (!preserveDraft) { $('resolveForm').reset(); $('reopenForm').reset(); $('conflictPanel').hidden = true; }
  }

  function renderHistory(item) {
    const resolution = item.latest_resolution; $('previousResolution').hidden = !resolution;
    if (!resolution) return;
    $('previousResolutionText').textContent = resolution.note || 'No resolution note recorded.'; $('previousResolutionMeta').textContent = `${resolution.updated_by || 'Staff'} · ${resolution.created_at || ''}`;
    const reopened = item.latest_reopen; $('previousReopen').hidden = !reopened;
    if (reopened) { $('previousReopenText').textContent = reopened.note || ''; $('previousReopenMeta').textContent = `${reopened.updated_by || 'Staff'} · ${reopened.created_at || ''}`; }
  }

  function renderEvidence(items) {
    const node = $('evidenceList'); node.replaceChildren();
    if (!items.length) { node.appendChild(Object.assign(document.createElement('p'), { className: 'muted', textContent: 'No evidence attached.' })); return; }
    items.forEach((item) => { const row = document.createElement('div'); row.className = 'item'; const name = Object.assign(document.createElement('strong'), { textContent: item.name }); row.appendChild(name); if (item.url) { const link = Object.assign(document.createElement('a'), { href: item.url, textContent: 'Open evidence' }); link.addEventListener('click', openEvidence); row.appendChild(link); } node.appendChild(row); });
  }
  async function openEvidence(event) { event.preventDefault(); try { const path = event.currentTarget.getAttribute('href').replace('/api/complaints/', ''); const response = await json(path); if (telegram?.openLink) telegram.openLink(response.url); else window.open(response.url, '_blank', 'noopener'); } catch (error) { notify(error.message, true); } }
  function renderActivity(items) { const node = $('activityList'); node.replaceChildren(); if (!items.length) { node.appendChild(Object.assign(document.createElement('p'), { className: 'muted', textContent: 'No activity recorded.' })); return; } items.forEach((item) => { const row = document.createElement('div'); row.className = 'item'; row.append(Object.assign(document.createElement('strong'), { textContent: `${item.status || 'Update'} · ${item.updated_by || 'Staff'}` }), Object.assign(document.createElement('p'), { textContent: item.note || '' }), Object.assign(document.createElement('small'), { className: 'muted', textContent: item.created_at || '' })); node.appendChild(row); }); }

  function showConflict(error) {
    const current = error.payload?.current_case; if (!current) { notify(error.message, true); return; }
    const draft = $('resolveForm').elements.resolution_text.value || $('reopenForm').elements.reason.value || '';
    state.currentCase = current; $('conflictPanel').hidden = false; $('conflictMessage').textContent = error.message;
    const resolution = current.latest_resolution; $('conflictWinningNote').textContent = resolution ? `${resolution.note}\n— ${resolution.updated_by}, ${resolution.created_at}` : 'Review the latest case before trying again.';
    $('conflictDraft').textContent = draft || 'No draft text was entered.';
    $('copyConflictDraftBtn').disabled = !draft;
    renderDetail(current, true); $('conflictPanel').hidden = false; $('conflictPanel').scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  async function copyConflictDraft() {
    const draft = $('conflictDraft').textContent;
    if (!draft || $('copyConflictDraftBtn').disabled) return;
    try { await navigator.clipboard.writeText(draft); notify('Your draft was copied.'); }
    catch (_) { notify('Copy was unavailable. Select and copy the retained draft above.', true); }
  }

  async function submitTransition(event, action) {
    event.preventDefault(); if (!state.currentCase || state.submitting) return;
    const formNode = event.currentTarget; const data = new FormData(formNode); data.set('expected_revision', state.currentCase.revision); data.set('client_request_id', requestId());
    const button = formNode.querySelector('button[type="submit"]'); state.submitting = true; button.disabled = true;
    try { const response = await form(`cases/${encodeURIComponent(state.currentCase.case_id)}/${action}/`, data); renderDetail(response.case); notify(response.message); await refreshCounts(); }
    catch (error) { if (error.status === 409) showConflict(error); else notify(error.message, true); }
    finally { state.submitting = false; button.disabled = false; }
  }

  async function refreshCounts() { try { const response = await json('bootstrap/'); const counts = response.data.counts; $('pendingCount').textContent = counts.pending; $('resolvedCount').textContent = counts.resolved; $('totalCount').textContent = counts.total; } catch (_) {} }
  async function submitCreate(event) { event.preventDefault(); if (state.submitting) return; const formNode = event.currentTarget; const data = new FormData(formNode); data.set('client_request_id', requestId()); if (state.latitude) { data.set('latitude', state.latitude); data.set('longitude', state.longitude); } const button = $('createSaveBtn'); state.submitting = true; button.disabled = true; $('createSaveState').textContent = 'Saving...'; try { const response = await form('cases/create/', data); formNode.reset(); state.latitude = ''; state.longitude = ''; $('createSelectedEvidence').replaceChildren(); $('createSaveState').textContent = 'Saved'; notify(response.message); await refreshCounts(); renderDetail(response.case); setView('detailView'); } catch (error) { $('createSaveState').textContent = 'Not saved'; notify(error.message, true); } finally { state.submitting = false; button.disabled = false; } }
  function captureLocation() { if (!navigator.geolocation) return notify('Location is unavailable on this device.', true); $('captureState').textContent = 'Capturing...'; navigator.geolocation.getCurrentPosition((position) => { state.latitude = position.coords.latitude.toFixed(6); state.longitude = position.coords.longitude.toFixed(6); $('captureState').textContent = 'Location captured'; }, () => { $('captureState').textContent = 'Location not captured'; notify('Location permission was not available.', true); }, { enableHighAccuracy: true, timeout: 12000 }); }
  function showFiles(event) { const list = $('createSelectedEvidence'); list.replaceChildren(); Array.from(event.target.files || []).forEach((file) => list.appendChild(Object.assign(document.createElement('li'), { textContent: file.name }))); }
  function returnQueue() { setView('queueView'); loadCases(); }

  document.querySelectorAll('[data-status]').forEach((button) => button.addEventListener('click', () => { state.status = button.dataset.status; state.page = 1; document.querySelectorAll('[data-status]').forEach((item) => item.classList.toggle('active', item === button)); loadCases(); }));
  $('caseSearch').addEventListener('input', (event) => { state.query = event.target.value; state.page = 1; clearTimeout(state.debounce); state.debounce = setTimeout(loadCases, state.query ? 250 : 0); });
  $('queuePreviousBtn').addEventListener('click', () => { if (state.page > 1) { state.page -= 1; loadCases(); } }); $('queueNextBtn').addEventListener('click', () => { if (state.page < state.pages) { state.page += 1; loadCases(); } });
  $('newCaseBtn').addEventListener('click', () => setView('createView')); document.querySelectorAll('[data-back]').forEach((button) => button.addEventListener('click', returnQueue)); $('refreshBtn').addEventListener('click', () => { if (!$('queueView').hidden) { state.page = 1; loadCases(); refreshCounts(); } else if (state.currentCase) openCase(state.currentCase.case_id); });
  $('captureLocationBtn').addEventListener('click', captureLocation); $('createEvidenceInput').addEventListener('change', showFiles); $('createCaseForm').addEventListener('submit', submitCreate); $('resolveForm').addEventListener('submit', (event) => submitTransition(event, 'resolve')); $('reopenForm').addEventListener('submit', (event) => submitTransition(event, 'reopen')); $('copyConflictDraftBtn').addEventListener('click', copyConflictDraft); $('reviewConflictBtn').addEventListener('click', () => openCase(state.currentCase.case_id));
  telegram?.BackButton?.onClick(returnQueue); bootstrap();
}());
