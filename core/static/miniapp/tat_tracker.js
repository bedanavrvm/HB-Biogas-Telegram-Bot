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
  };

  const $ = (id) => document.getElementById(id);

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
    const el = $('status');
    el.textContent = message || '';
    el.className = 'status-bar' + (tone ? ' ' + tone : '');
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

  function setButtonLoading(button, loading, label) {
    if (!button) return;
    if (loading) {
      button.dataset.originalText = button.textContent;
      button.textContent = label || 'Working...';
      button.disabled = true;
    } else {
      button.textContent = button.dataset.originalText || button.textContent;
      button.disabled = false;
    }
  }

  function renderCaseButton(item) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'case-card';
    const next = item.next_stage ? `<span class="next-chip">Next: ${escapeHtml(item.next_stage)}</span>` : '';
    button.innerHTML = `
      <div class="case-main">
        <div class="case-title">
          <span class="case-id">${escapeHtml(item.case_id)}</span>
          <strong>${escapeHtml(item.client_name || 'Unnamed client')}</strong>
        </div>
        <span class="status-chip ${statusClass(item.status)}">${escapeHtml(item.status || 'Active')}</span>
      </div>
      <div class="case-meta">
        <span>${escapeHtml(item.product || '')}</span>
        <span>${escapeHtml(item.branch || '')}</span>
        <span>KES ${escapeHtml(formatMoney(item.amount || ''))}</span>
        ${next}
        <span>${escapeHtml(item.updated_at || '')}</span>
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
    const roles = (data.user.roles || []).join(', ') || 'Staff';
    $('userLine').textContent = `${data.user.name} | ${roles}`;
    $('statRole').textContent = data.user.name || 'Staff';
    fillSelect(document.querySelector('[name="product_key"]'), data.products, 'key', 'label');
    fillSelect(document.querySelector('[name="branch"]'), (data.branches || []).map((value) => ({ value, label: value })), 'value', 'label');
    document.querySelector('[name="bro_name"]').value = data.user.name || '';
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
      <div class="summary-title">
        <span class="case-id">${escapeHtml(summary.case_id)}</span>
        <strong>${escapeHtml(summary.client_name || 'Unnamed client')}</strong>
        <span>${escapeHtml(summary.product || '')} | ${escapeHtml(summary.branch || '')} | ${escapeHtml(summary.status || '')}</span>
      </div>
      <div class="summary-facts">
        <div class="fact"><small>Amount</small><span>KES ${escapeHtml(formatMoney(summary.amount || ''))}</span></div>
        <div class="fact"><small>Next Action</small><span>${escapeHtml(summary.next_stage || 'No pending action')}</span></div>
        <div class="fact"><small>Created</small><span>${escapeHtml(summary.created_at || '')}</span></div>
        <div class="fact"><small>Updated</small><span>${escapeHtml(summary.updated_at || '')}</span></div>
      </div>`;

    $('remarksInput').value = detail.remarks || '';
    const fields = $('stageFields');
    fields.innerHTML = '';
    detail.fields.forEach((field) => {
      const row = document.createElement('div');
      const hasValue = Boolean(field.value);
      row.className = 'stage-row' + (field.editable ? ' editable' : hasValue ? ' done' : ' locked');
      const valueText = field.value || 'Not set';
      row.innerHTML = `
        <div class="stage-top">
          <strong>${escapeHtml(field.label)}</strong>
          <span class="role-chip">${escapeHtml(field.role)}</span>
        </div>
        <div class="stage-value">${escapeHtml(valueText)}</div>`;

      if (field.editable) {
        if (field.kind === 'dropdown') {
          const select = document.createElement('select');
          select.innerHTML = '<option value="">Select outcome...</option>' + (field.options || []).map((option) => `<option value="${escapeHtml(option)}">${escapeHtml(option)}</option>`).join('');
          select.addEventListener('change', () => { if (select.value) submitUpdate([{ field: field.key, value: select.value }]); });
          row.appendChild(select);
        } else {
          const button = document.createElement('button');
          button.type = 'button';
          button.className = 'primary';
          button.textContent = 'Stamp Now';
          button.addEventListener('click', () => submitUpdate([{ field: field.key, value: 'STAMP' }]));
          row.appendChild(button);
        }
      } else if (field.locked_reason) {
        const note = document.createElement('div');
        note.className = 'lock-note';
        note.textContent = field.locked_reason;
        row.appendChild(note);
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
        row.className = 'event';
        row.innerHTML = `<strong>${escapeHtml(event.stage)}: ${escapeHtml(event.value)}</strong><span>${escapeHtml(event.actor)} | ${escapeHtml(event.at)} | ${escapeHtml(event.source)}</span>`;
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
    const submitButton = event.currentTarget.querySelector('button[type="submit"]');
    try {
      setButtonLoading(submitButton, true, 'Creating');
      setStatus('Creating case...', 'busy');
      const form = new FormData(event.currentTarget);
      const payload = Object.fromEntries(form.entries());
      const result = await api('/api/tat-tracker/create/', payload);
      event.currentTarget.reset();
      document.querySelector('[name="bro_name"]').value = state.data.user.name || '';
      state.detail = result.data;
      renderDetail(result.data);
      show('detail');
      setStatus('Case created. Continue from the highlighted stage.', 'ok');
      refresh().catch(() => {});
    } catch (error) {
      setStatus(error.message, 'error');
    } finally {
      setButtonLoading(submitButton, false);
    }
  });

  api('/api/tat-tracker/bootstrap/', {})
    .then((result) => bootstrap(result.data))
    .catch((error) => setStatus(error.message, 'error'));
})();