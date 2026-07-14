(function () {
  const tg = window.MiniAppTelegram ? window.MiniAppTelegram.init() : null;
  const body = document.body;
  const state = {
    groupId: body.dataset.groupId || '',
    token: body.dataset.token || '',
    initData: tg ? tg.initData || '' : '',
    data: null,
    detail: null,
    currentView: 'queue',
    pendingCreateRequestId: readPendingCreateRequestId(),
    creatingCase: false,
  };

  const $ = (id) => document.getElementById(id);
  let statusTimeout = null;

  function readPendingCreateRequestId() {
    try { return window.sessionStorage.getItem('tatPendingCreateRequestId') || ''; } catch (error) { return ''; }
  }

  function writePendingCreateRequestId(value) {
    try {
      if (value) window.sessionStorage.setItem('tatPendingCreateRequestId', value);
      else window.sessionStorage.removeItem('tatPendingCreateRequestId');
    } catch (error) {}
  }

  function newRequestId() {
    if (window.crypto && window.crypto.randomUUID) return window.crypto.randomUUID();
    return 'tat-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 10);
  }

  function basePayload(extra) {
    return Object.assign({ group_id: state.groupId, token: state.token, init_data: state.initData }, extra || {});
  }

  async function api(path, payload) {
    const response = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(basePayload(payload)),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data.ok) throw new Error(data.error || 'Request failed.');
    return data;
  }

  function setStatus(message, tone) {
    if (statusTimeout) {
      clearTimeout(statusTimeout);
      statusTimeout = null;
    }
    const el = $('status');
    if (!message) {
      el.innerHTML = '';
      el.className = 'status-bar hidden';
      return;
    }
    
    let icon = '';
    if (tone === 'busy') {
      icon = `
        <svg class="spinner" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
          <line x1="12" y1="2" x2="12" y2="6"></line>
          <line x1="12" y1="18" x2="12" y2="22"></line>
          <line x1="4.93" y1="4.93" x2="7.76" y2="7.76"></line>
          <line x1="16.24" y1="16.24" x2="19.07" y2="19.07"></line>
          <line x1="2" y1="12" x2="6" y2="12"></line>
          <line x1="18" y1="12" x2="22" y2="12"></line>
          <line x1="4.93" y1="19.07" x2="7.76" y2="16.24"></line>
          <line x1="16.24" y1="7.76" x2="19.07" y2="4.93"></line>
        </svg>
      `;
    } else if (tone === 'ok') {
      icon = `
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="20 6 9 17 4 12"></polyline>
        </svg>
      `;
    } else if (tone === 'error') {
      icon = `
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="12" cy="12" r="10"></circle>
          <line x1="12" y1="8" x2="12" y2="12"></line>
          <line x1="12" y1="16" x2="12.01" y2="16"></line>
        </svg>
      `;
    }
    el.innerHTML = `${icon}<span>${escapeHtml(message)}</span>`;
    el.className = 'status-bar' + (tone ? ' ' + tone : '');

    if (tone === 'ok') {
      statusTimeout = setTimeout(() => {
        setStatus('');
      }, 1500);
    }
  }

  function show(view) {
    state.currentView = view;
    document.querySelectorAll('.view').forEach((node) => node.classList.remove('active'));
    document.querySelectorAll('.tabs button').forEach((node) => node.classList.toggle('active', node.dataset.view === view));
    const target = view === 'queue' ? 'queueView' : view === 'new' ? 'newView' : view === 'search' ? 'searchView' : 'detailView';
    $(target).classList.add('active');
  }

  function escapeHtml(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[char]));
  }

  function statusClass(status) {
    return String(status || 'active').toLowerCase().replace(/\s+/g, '-').replace(/[^a-z0-9-]/g, '');
  }

  function formatMoney(value) {
    const raw = String(value || '').replace(/,/g, '').trim();
    const number = Number(raw);
    if (!Number.isFinite(number)) return value || '';
    return number.toLocaleString('en-KE', { maximumFractionDigits: 0 });
  }

  function currentUserName() {
    return (state.data && state.data.user && state.data.user.name) ? state.data.user.name : '';
  }

  function requireCaseDetail(detail) {
    if (!detail || !detail.summary) {
      throw new Error('Case was saved, but the app could not load its detail view. Tap Refresh or search for the case to continue.');
    }
    return detail;
  }

  function setButtonLoading(button, loading, label) {
    if (!button) return;
    if (loading) {
      button.dataset.originalText = button.innerHTML;
      button.innerHTML = `
        <svg class="spinner" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
          <line x1="12" y1="2" x2="12" y2="6"></line>
          <line x1="12" y1="18" x2="12" y2="22"></line>
          <line x1="4.93" y1="4.93" x2="7.76" y2="7.76"></line>
          <line x1="16.24" y1="16.24" x2="19.07" y2="19.07"></line>
          <line x1="2" y1="12" x2="6" y2="12"></line>
          <line x1="18" y1="12" x2="22" y2="12"></line>
          <line x1="4.93" y1="19.07" x2="7.76" y2="16.24"></line>
          <line x1="16.24" y1="7.76" x2="19.07" y2="4.93"></line>
        </svg>
        <span>${label || 'Working...'}</span>
      `;
      button.disabled = true;
    } else {
      button.innerHTML = button.dataset.originalText || button.innerHTML;
      button.disabled = false;
    }
  }

  function renderCaseButton(item) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'case-card';
    const next = item.next_stage ? `<span class="next-chip">Next: ${escapeHtml(item.next_stage)}</span>` : '';
    button.innerHTML = `
      <div class="case-header">
        <strong class="case-name">${escapeHtml(item.client_name || 'Unnamed client')}</strong>
        <span class="case-amount">KES ${escapeHtml(formatMoney(item.amount || ''))}</span>
      </div>
      <div class="case-details">
        <span class="case-id-badge">${escapeHtml(item.case_id)}</span>
        <span class="case-meta-dot"></span>
        <span class="case-meta-text">${escapeHtml(item.product || '')}</span>
        <span class="case-meta-dot"></span>
        <span class="case-meta-text">${escapeHtml(item.branch || '')}</span>
      </div>
      <div class="case-tags">
        <span class="status-chip ${statusClass(item.status)}">${escapeHtml(item.status || 'Active')}</span>
        ${next}
        <span class="case-time">
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" width="10" height="10">
            <circle cx="12" cy="12" r="10"/>
            <polyline points="12 6 12 12 16 14"/>
          </svg>
          ${escapeHtml(item.updated_at || '')}
        </span>
      </div>`;
    button.addEventListener('click', () => openCase(item.case_id));
    return button;
  }

  function renderEmpty(title, detail) {
    const empty = document.createElement('div');
    empty.className = 'empty-state';
    empty.innerHTML = `<strong>${escapeHtml(title)}</strong><span>${escapeHtml(detail || '')}</span>`;
    return empty;
  }

  function renderList(id, items, emptyTitle, emptyDetail) {
    const list = $(id);
    list.innerHTML = '';
    if (!items || !items.length) {
      list.appendChild(renderEmpty(emptyTitle, emptyDetail));
      return;
    }
    items.forEach((item) => list.appendChild(renderCaseButton(item)));
  }

  function renderHome(data) {
    const actionRequired = data.action_required || [];
    const recent = data.recent || [];
    $('queueCount').textContent = actionRequired.length;
    $('recentCount').textContent = recent.length;
    $('statQueue').textContent = actionRequired.length;
    $('statRecent').textContent = recent.length;
    renderList('queueList', actionRequired, 'No action needed', 'Cases that need your role will appear here.');
    renderList('recentList', recent, 'No recent cases', 'Create a case or search existing records.');
  }

  function fillSelect(select, items, valueKey, labelKey) {
    select.innerHTML = '';
    items.forEach((item) => {
      const option = document.createElement('option');
      option.value = item[valueKey];
      option.textContent = item[labelKey];
      select.appendChild(option);
    });
  }

  function bootstrap(data) {
    state.data = data;
    if (!data.authorized) throw new Error(data.reason || 'Unauthorized.');
    const user = data.user || {};
    const roles = (user.roles || []).join(', ') || 'Staff';
    $('userLine').textContent = `${user.name || 'Staff'} | ${roles}`;
    $('statRole').textContent = user.name || 'Staff';
    fillSelect(document.querySelector('[name="product_key"]'), data.products, 'key', 'label');
    fillSelect(document.querySelector('[name="branch"]'), (data.branches || []).map((value) => ({ value, label: value })), 'value', 'label');
    const broInput = document.querySelector('[name="bro_name"]');
    if (broInput) broInput.value = currentUserName();
    renderHome(data);
    setStatus('Ready.', 'ok');
  }

  async function refresh() {
    setStatus('Refreshing queue...', 'busy');
    const result = await api('/api/tat-tracker/home/', {});
    renderHome(result.data);
    setStatus('Queue updated.', 'ok');
  }

  async function openCase(caseId) {
    setStatus('Opening case...', 'busy');
    const result = await api('/api/tat-tracker/detail/', { case_id: caseId });
    state.detail = result.data;
    renderDetail(result.data);
    show('detail');
    setStatus('Case opened.', 'ok');
  }

  function renderDetail(detail) {
    const summary = detail.summary;
    $('detailSummary').innerHTML = `
      <div class="detail-header-block">
        <div class="detail-title-row">
          <h2 class="detail-client-name">${escapeHtml(summary.client_name || 'Unnamed client')}</h2>
          <span class="status-chip ${statusClass(summary.status)}">${escapeHtml(summary.status || 'Active')}</span>
        </div>
        <div class="detail-meta-row">
          <span class="detail-case-id">${escapeHtml(summary.case_id)}</span>
          <span class="divider">•</span>
          <span class="detail-product">${escapeHtml(summary.product || '')}</span>
          <span class="divider">•</span>
          <span class="detail-branch">${escapeHtml(summary.branch || '')}</span>
        </div>
      </div>
      <div class="summary-facts">
        <div class="fact">
          <small>Amount</small>
          <span class="highlight-val">KES ${escapeHtml(formatMoney(summary.amount || ''))}</span>
        </div>
        <div class="fact">
          <small>Next Action</small>
          <span>${escapeHtml(summary.next_stage || 'No pending action')}</span>
        </div>
        <div class="fact">
          <small>Created</small>
          <span>${escapeHtml(summary.created_at || '')}</span>
        </div>
        <div class="fact">
          <small>Updated</small>
          <span>${escapeHtml(summary.updated_at || '')}</span>
        </div>
      </div>`;

    $('remarksInput').value = detail.remarks || '';
    const fields = $('stageFields');
    fields.innerHTML = '';
    detail.fields.forEach((field) => {
      const row = document.createElement('div');
      const hasValue = Boolean(field.value);
      row.className = 'stage-row' + (field.editable ? ' editable' : hasValue ? ' done' : ' locked');
      
      let indicatorHtml = '';
      if (field.editable) {
        indicatorHtml = `<span class="indicator-icon pulse-active"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" width="12" height="12"><circle cx="12" cy="12" r="10"/><path d="M12 8v4l3 3"/></svg></span>`;
      } else if (hasValue) {
        indicatorHtml = `<span class="indicator-icon check-done"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round" width="11" height="11"><polyline points="20 6 9 17 4 12"/></svg></span>`;
      } else {
        indicatorHtml = `<span class="indicator-icon lock-locked"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" width="11" height="11"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg></span>`;
      }

      const valueText = field.value || (field.locked_reason ? 'Pending previous stages' : 'Not started');
      
      row.innerHTML = `
        <div class="stage-left-rail">
          ${indicatorHtml}
          <div class="stage-connector"></div>
        </div>
        <div class="stage-content">
          <div class="stage-top">
            <span class="stage-label">${escapeHtml(field.label)}</span>
            <span class="role-chip">${escapeHtml(field.role)}</span>
          </div>
          <div class="stage-value ${hasValue ? 'value-filled' : 'value-empty'}">${escapeHtml(valueText)}</div>
        </div>`;

      if (field.editable) {
        const actionWrap = document.createElement('div');
        actionWrap.className = 'stage-action-wrap';
        if (field.kind === 'dropdown') {
          const select = document.createElement('select');
          select.innerHTML = '<option value="">Select outcome...</option>' + (field.options || []).map((option) => `<option value="${escapeHtml(option)}">${escapeHtml(option)}</option>`).join('');
          select.addEventListener('change', () => { if (select.value) submitUpdate([{ field: field.key, value: select.value }]); });
          actionWrap.appendChild(select);
        } else {
          const button = document.createElement('button');
          button.type = 'button';
          button.className = 'primary compact-btn';
          button.innerHTML = `
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" width="14" height="14">
              <path d="M20 11.08V12a10 10 0 1 1-5.93-9.14"/>
              <polyline points="22 4 12 14.01 9 11.01"/>
            </svg>
            <span>Stamp Approval</span>
          `;
          button.addEventListener('click', () => submitUpdate([{ field: field.key, value: 'STAMP' }]));
          actionWrap.appendChild(button);
        }
        row.querySelector('.stage-content').appendChild(actionWrap);
      } else if (field.locked_reason) {
        const note = document.createElement('div');
        note.className = 'lock-note';
        note.textContent = field.locked_reason;
        row.querySelector('.stage-content').appendChild(note);
      }
      fields.appendChild(row);
    });

    const events = $('eventList');
    events.innerHTML = '';
    if (!detail.events || !detail.events.length) {
      events.appendChild(renderEmpty('No audit events yet', 'Updates will appear here after the case starts moving.'));
    } else {
      detail.events.forEach((event) => {
        const row = document.createElement('div');
        row.className = 'event-item';
        row.innerHTML = `
          <div class="event-dot"></div>
          <div class="event-body">
            <div class="event-header">
              <strong class="event-stage">${escapeHtml(event.stage)}</strong>
              <span class="event-value-badge">${escapeHtml(event.value)}</span>
            </div>
            <div class="event-meta">${escapeHtml(event.actor)} • ${escapeHtml(event.at)}</div>
          </div>
        `;
        events.appendChild(row);
      });
    }
  }

  async function submitUpdate(updates) {
    if (!state.detail) return;
    setStatus('Saving update...', 'busy');
    const result = await api('/api/tat-tracker/update/', { case_id: state.detail.summary.case_id, updates });
    state.detail = result.data;
    renderDetail(result.data);
    setStatus('Saved.', 'ok');
  }

  document.querySelectorAll('.tabs button').forEach((button) => button.addEventListener('click', () => show(button.dataset.view)));
  $('refreshBtn').addEventListener('click', async (event) => {
    try {
      setButtonLoading(event.currentTarget, true, 'Refreshing');
      await refresh();
    } catch (error) {
      setStatus(error.message, 'error');
    } finally {
      setButtonLoading(event.currentTarget, false);
    }
  });
  $('backBtn').addEventListener('click', () => { show('queue'); refresh().catch(() => {}); });
  $('saveRemarksBtn').addEventListener('click', async (event) => {
    try {
      setButtonLoading(event.currentTarget, true, 'Saving');
      await submitUpdate([{ field: 'remarks', value: $('remarksInput').value }]);
    } catch (error) {
      setStatus(error.message, 'error');
    } finally {
      setButtonLoading(event.currentTarget, false);
    }
  });
  $('searchBtn').addEventListener('click', runSearch);
  $('searchInput').addEventListener('keydown', (event) => {
    if (event.key === 'Enter') runSearch();
  });

  async function runSearch() {
    try {
      const query = $('searchInput').value.trim();
      if (query.length < 2) {
        setStatus('Type at least 2 characters to search.', 'error');
        return;
      }
      setStatus('Searching...', 'busy');
      const result = await api('/api/tat-tracker/search/', { query });
      renderList('searchList', result.results, 'No matching cases', 'Try a case ID, client name, branch, or BRO name.');
      setStatus('Search complete.', 'ok');
    } catch (error) {
      setStatus(error.message, 'error');
    }
  }

  $('newCaseForm').addEventListener('submit', async (event) => {
    event.preventDefault();
    if (state.creatingCase) return;
    const formElement = event.currentTarget;
    const submitButton = formElement ? formElement.querySelector('button[type="submit"]') : null;
    try {
      state.creatingCase = true;
      setButtonLoading(submitButton, true, 'Creating');
      setStatus('Creating case...', 'busy');
      const form = new FormData(formElement);
      const payload = Object.fromEntries(form.entries());
      state.pendingCreateRequestId = state.pendingCreateRequestId || newRequestId();
      writePendingCreateRequestId(state.pendingCreateRequestId);
      payload.client_request_id = state.pendingCreateRequestId;
      const result = await api('/api/tat-tracker/create/', payload);
      const detail = requireCaseDetail(result.data);
      state.detail = detail;
      renderDetail(detail);
      show('detail');
      state.pendingCreateRequestId = '';
      writePendingCreateRequestId('');
      if (formElement && typeof formElement.reset === 'function') formElement.reset();
      const broInput = document.querySelector('[name="bro_name"]');
      if (broInput) broInput.value = currentUserName() || payload.bro_name || '';
      setStatus('Case created. Continue from the highlighted stage.', 'ok');
      refresh().catch(() => {});
    } catch (error) {
      setStatus(error.message, 'error');
    } finally {
      state.creatingCase = false;
      setButtonLoading(submitButton, false);
    }
  });

  api('/api/tat-tracker/bootstrap/', {})
    .then((result) => bootstrap(result.data))
    .catch((error) => setStatus(error.message, 'error'));
})();
