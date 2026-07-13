(function () {
  const tg = window.MiniAppTelegram ? window.MiniAppTelegram.init() : null;
  const body = document.body;
  const state = {
    groupId: body.dataset.groupId || '',
    token: body.dataset.token || '',
    initData: tg ? tg.initData || '' : '',
    data: null,
    detail: null,
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
    document.querySelectorAll('.view').forEach((node) => node.classList.remove('active'));
    document.querySelectorAll('.tabs button').forEach((node) => node.classList.toggle('active', node.dataset.view === view));
    const target = view === 'queue' ? 'queueView' : view === 'new' ? 'newView' : view === 'search' ? 'searchView' : 'detailView';
    $(target).classList.add('active');
  }

  function escapeHtml(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[char]));
  }

  function renderCaseButton(item) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'case-card';
    const next = item.next_stage ? `<span class="pill">Next: ${escapeHtml(item.next_stage)}</span>` : '';
    button.innerHTML = `<strong>${escapeHtml(item.case_id)} - ${escapeHtml(item.client_name)}</strong><span>${escapeHtml(item.product)} | ${escapeHtml(item.branch)} | ${escapeHtml(item.status)}</span>${next}<span>Updated ${escapeHtml(item.updated_at || '')}</span>`;
    button.addEventListener('click', () => openCase(item.case_id));
    return button;
  }

  function renderList(id, items, emptyText) {
    const list = $(id);
    list.innerHTML = '';
    if (!items || !items.length) {
      const empty = document.createElement('div');
      empty.className = 'empty';
      empty.textContent = emptyText;
      list.appendChild(empty);
      return;
    }
    items.forEach((item) => list.appendChild(renderCaseButton(item)));
  }

  function renderHome(data) {
    $('queueCount').textContent = (data.action_required || []).length;
    $('recentCount').textContent = (data.recent || []).length;
    renderList('queueList', data.action_required, 'No cases currently assigned to your role.');
    renderList('recentList', data.recent, 'No recent cases yet.');
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
    $('userLine').textContent = `${data.user.name} | ${(data.user.roles || []).join(', ')}`;
    fillSelect(document.querySelector('[name="product_key"]'), data.products, 'key', 'label');
    fillSelect(document.querySelector('[name="branch"]'), (data.branches || []).map((value) => ({ value, label: value })), 'value', 'label');
    document.querySelector('[name="bro_name"]').value = data.user.name || '';
    renderHome(data);
    setStatus('Ready', 'ok');
  }

  async function refresh() {
    setStatus('Refreshing...');
    const result = await api('/api/tat-tracker/home/', {});
    renderHome(result.data);
    setStatus('Queue updated', 'ok');
  }

  async function openCase(caseId) {
    setStatus('Opening case...');
    const result = await api('/api/tat-tracker/detail/', { case_id: caseId });
    state.detail = result.data;
    renderDetail(result.data);
    show('detail');
    setStatus('Case opened', 'ok');
  }

  function renderDetail(detail) {
    const summary = detail.summary;
    $('detailSummary').innerHTML = `<div class="summary-title"><strong>${escapeHtml(summary.case_id)} - ${escapeHtml(summary.client_name)}</strong><span>${escapeHtml(summary.product)} | ${escapeHtml(summary.branch)} | ${escapeHtml(summary.status)} | KES ${escapeHtml(summary.amount || '')}</span><span class="pill">${escapeHtml(summary.next_stage || 'No pending action')}</span></div>`;
    $('remarksInput').value = detail.remarks || '';
    const fields = $('stageFields');
    fields.innerHTML = '';
    detail.fields.forEach((field) => {
      const row = document.createElement('div');
      row.className = 'stage-row';
      const valueText = field.value || 'Not set';
      row.innerHTML = `<div class="stage-top"><strong>${escapeHtml(field.label)}</strong><small>${escapeHtml(field.role)}</small></div><div>${escapeHtml(valueText)}</div>`;
      if (field.editable) {
        if (field.kind === 'dropdown') {
          const select = document.createElement('select');
          select.innerHTML = '<option value="">Select...</option>' + (field.options || []).map((option) => `<option value="${escapeHtml(option)}">${escapeHtml(option)}</option>`).join('');
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
      events.innerHTML = '<div class="empty">No audit events yet.</div>';
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
    setStatus('Saving...');
    const result = await api('/api/tat-tracker/update/', { case_id: state.detail.summary.case_id, updates });
    state.detail = result.data;
    renderDetail(result.data);
    setStatus('Saved', 'ok');
  }

  document.querySelectorAll('.tabs button').forEach((button) => button.addEventListener('click', () => show(button.dataset.view)));
  $('refreshBtn').addEventListener('click', () => refresh().catch((error) => setStatus(error.message, 'error')));
  $('backBtn').addEventListener('click', () => { show('queue'); refresh().catch(() => {}); });
  $('saveRemarksBtn').addEventListener('click', () => submitUpdate([{ field: 'remarks', value: $('remarksInput').value }]).catch((error) => setStatus(error.message, 'error')));
  $('searchBtn').addEventListener('click', async () => {
    try {
      setStatus('Searching...');
      const result = await api('/api/tat-tracker/search/', { query: $('searchInput').value });
      renderList('searchList', result.results, 'No matching cases found.');
      setStatus('Search complete', 'ok');
    } catch (error) { setStatus(error.message, 'error'); }
  });
  $('newCaseForm').addEventListener('submit', async (event) => {
    event.preventDefault();
    try {
      setStatus('Creating case...');
      const form = new FormData(event.currentTarget);
      const payload = Object.fromEntries(form.entries());
      const result = await api('/api/tat-tracker/create/', payload);
      event.currentTarget.reset();
      document.querySelector('[name="bro_name"]').value = state.data.user.name || '';
      state.detail = result.data;
      renderDetail(result.data);
      show('detail');
      setStatus('Case created', 'ok');
    } catch (error) { setStatus(error.message, 'error'); }
  });

  api('/api/tat-tracker/bootstrap/', {})
    .then((result) => bootstrap(result.data))
    .catch((error) => setStatus(error.message, 'error'));
})();
