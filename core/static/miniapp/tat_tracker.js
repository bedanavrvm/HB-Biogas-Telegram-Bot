(function () {
  const utils = window.MiniAppUtils || {};
  const tatApi = window.TatMiniAppApi || {};
  const tg = window.MiniAppTelegram ? window.MiniAppTelegram.init() : (utils.initTelegram ? utils.initTelegram() : null);
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
    refreshing: false,
    home: { action_required: [], recent: [], pagination: {} },
    loadingHomePage: { action_required: false, recent: false },
  };

  const $ = (id) => document.getElementById(id);
  let statusTimeout = null;
  let noticeTimeout = null;

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

  function configureHtmx() {
    if (!window.htmx) return;
    document.body.addEventListener('htmx:afterSwap', (event) => {
      if (event.detail.target && ['queueList', 'recentList', 'searchList'].includes(event.detail.target.id)) {
        hydrateHtmxCaseCards(event.detail.target);
      }
    });
  }

  async function api(path, payload) {
    if (tatApi.postJson) return tatApi.postJson(path, basePayload(payload), utils);
    if (utils.fetchJson) {
      return utils.fetchJson(path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(basePayload(payload)),
      });
    }
    const response = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(basePayload(payload)),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data.ok) throw new Error(data.error || 'Request failed.');
    return data;
  }

  async function fragmentPost(path, payload) {
    if (tatApi.postFragment) return tatApi.postFragment(path, basePayload(payload), utils);
    if (utils.fetchHtml && utils.formBody) {
      return utils.fetchHtml(path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8' },
        body: utils.formBody(basePayload(payload)),
      });
    }
    const response = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8' },
      body: new URLSearchParams(basePayload(payload)).toString(),
    });
    const html = await response.text();
    if (!response.ok) throw new Error(html || 'Request failed.');
    return html;
  }

  function closeNotice() {
    if (noticeTimeout) {
      clearTimeout(noticeTimeout);
      noticeTimeout = null;
    }
    $('noticeModal').classList.add('hidden');
  }

  function showNotice(message, tone) {
    if (noticeTimeout) clearTimeout(noticeTimeout);
    $('noticeTitle').textContent = tone === 'error' ? 'Action needed' : 'Success';
    $('noticeMessage').textContent = message;
    const toast = $('noticeModal');
    toast.dataset.tone = tone || 'ok';
    toast.classList.remove('hidden');
    noticeTimeout = setTimeout(closeNotice, 5000);
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
    if (tone === 'ok' || tone === 'error') showNotice(message, tone);

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
    const target = $(view + 'View');
    if (target) target.classList.add('active');
  }

  function escapeHtml(value) {
    if (utils.escapeHtml) return utils.escapeHtml(value);
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

  function formatMinutes(value) {
    const number = Number(String(value || '').replace(/,/g, '').trim());
    if (!Number.isFinite(number)) return '';
    return `${Math.round(number).toLocaleString('en-KE')} min`;
  }

  function slaLabel(status) {
    if (status === 'within') return 'Within target';
    if (status === 'near') return 'Near target';
    if (status === 'over') return 'Over target';
    return '';
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
      if (!button.dataset.originalText) button.dataset.originalText = button.innerHTML;
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
      delete button.dataset.originalText;
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
      ${caseIdentifierMarkup(item)}
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

  function caseIdentifierMarkup(item) {
    const identifiers = [];
    if (item.national_id) identifiers.push(`<span class="case-identifier"><small>ID</small>${escapeHtml(item.national_id)}</span>`);
    if (item.primary_phone) identifiers.push(`<span class="case-identifier"><small>Phone</small>${escapeHtml(item.primary_phone)}</span>`);
    return identifiers.length ? `<div class="case-identifiers">${identifiers.join('')}</div>` : '';
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

  function hydrateHtmxCaseCards(root) {
    root.querySelectorAll('.htmx-tat-case-card[data-case-id]').forEach((button) => {
      if (button.dataset.bound === '1') return;
      button.dataset.bound = '1';
      button.addEventListener('click', () => openCase(button.dataset.caseId));
    });
  }

  async function renderTatHomeFragment(listKey) {
    if (!window.htmx) return false;
    const target = $(listKey === 'action_required' ? 'queueList' : 'recentList');
    if (!target) return false;
    try {
      target.innerHTML = await fragmentPost('/api/tat-tracker/home/fragment/', Object.assign(homePayload(), { list: listKey }));
      hydrateHtmxCaseCards(target);
      return true;
    } catch (error) {
      return false;
    }
  }

  async function renderTatSearchFragment(query) {
    if (!window.htmx) return false;
    const target = $('searchList');
    if (!target) return false;
    try {
      target.innerHTML = await fragmentPost('/api/tat-tracker/search/fragment/', { query });
      hydrateHtmxCaseCards(target);
      return true;
    } catch (error) {
      return false;
    }
  }

  function renderHome(data, appendList) {
    const page = data || {};
    const pagination = page.pagination || {};
    if (appendList) {
      state.home[appendList] = state.home[appendList].concat(page[appendList] || []);
      state.home.pagination[appendList] = pagination[appendList] || {};
    } else {
      state.home = {
        action_required: page.action_required || [],
        recent: page.recent || [],
        pagination,
      };
    }
    const actionRequired = state.home.action_required;
    const recent = state.home.recent;
    const actionTotal = (state.home.pagination.action_required || {}).total;
    const recentTotal = (state.home.pagination.recent || {}).total;
    $('queueCount').textContent = actionTotal == null ? actionRequired.length : actionTotal;
    $('recentCount').textContent = recentTotal == null ? recent.length : recentTotal;
    $('statQueue').textContent = actionTotal == null ? actionRequired.length : actionTotal;
    $('statRecent').textContent = recentTotal == null ? recent.length : recentTotal;
    renderList('queueList', actionRequired, 'No action needed', 'Cases that need your role will appear here.');
    renderList('recentList', recent, 'No recent cases', 'Create a case or search existing records.');
    updateLoadMoreButton('loadMoreQueueBtn', state.home.pagination.action_required, 'Needs My Action');
    updateLoadMoreButton('loadMoreRecentBtn', state.home.pagination.recent, 'Recent Activity');
  }

  function updateLoadMoreButton(id, page, label) {
    const button = $(id);
    const total = Number((page || {}).total || 0);
    const shown = (page || {}).offset + (page || {}).page_size;
    button.hidden = !(page || {}).has_more;
    button.textContent = total ? `Load more ${label} (${Math.max(total - shown, 0)} remaining)` : `Load more ${label}`;
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

  function fillFilterSelect(select, items, valueKey, labelKey, allLabel) {
    const options = [{ value: '', label: allLabel }].concat(items || []);
    fillSelect(select, options, valueKey, labelKey);
  }

  function currentHomeFilters() {
    return {
      product_key: $('queueProductFilter') ? $('queueProductFilter').value : '',
      branch: $('queueBranchFilter') ? $('queueBranchFilter').value : '',
    };
  }

  function homePayload(extra) {
    return Object.assign({}, currentHomeFilters(), extra || {});
  }

  function isTargetManager() {
    const roles = ((state.data || {}).user || {}).roles || [];
    return roles.some((role) => String(role).toUpperCase() === 'IT');
  }

  function appendTargetInput(container, label, productKey, stageKey, minutes) {
    const field = document.createElement('label');
    field.textContent = label;
    const input = document.createElement('input');
    input.type = 'number';
    input.inputMode = 'numeric';
    input.min = '0';
    input.step = '1';
    input.placeholder = 'Not set';
    input.value = minutes || '';
    input.dataset.productKey = productKey;
    input.dataset.stageKey = stageKey || '';
    field.appendChild(input);
    container.appendChild(field);
  }

  function renderTargetSettings(targets) {
    const list = $('targetSettingsList');
    list.innerHTML = '';
    (targets || []).forEach((product) => {
      const section = document.createElement('section');
      section.className = 'target-product-card';
      const heading = document.createElement('h3');
      heading.textContent = product.label;
      section.appendChild(heading);
      const grid = document.createElement('div');
      grid.className = 'form-grid target-input-grid';
      if ((1 + (product.stages || []).length) % 2) grid.classList.add('target-input-grid--odd');
      appendTargetInput(grid, 'Overall target (minutes)', product.key, '', product.total_minutes);
      (product.stages || []).forEach((stage) => appendTargetInput(grid, stage.label + ' (minutes)', product.key, stage.key, stage.target_minutes));
      section.appendChild(grid);
      list.appendChild(section);
    });
  }

  function targetSettingsPayload() {
    const targets = {};
    document.querySelectorAll('#targetSettingsList input[data-product-key]').forEach((input) => {
      const productKey = input.dataset.productKey;
      const stageKey = input.dataset.stageKey;
      if (!targets[productKey]) targets[productKey] = { total_minutes: '', stages: {} };
      if (stageKey) targets[productKey].stages[stageKey] = input.value.trim();
      else targets[productKey].total_minutes = input.value.trim();
    });
    return targets;
  }

  async function loadTargetSettings() {
    if (!isTargetManager()) return;
    const result = await api('/api/tat-tracker/target-settings/', {});
    renderTargetSettings(result.data.targets);
  }

  async function saveTargetSettings() {
    const result = await api('/api/tat-tracker/target-settings/', { targets: targetSettingsPayload() });
    renderTargetSettings(result.data.targets);
    const savedMessage = result.data.changed ? 'TAT targets saved.' : 'No target changes to save.';
    const sheetSync = (result.data.sheet_sync || {}).status;
    setStatus(sheetSync === 'synced' ? savedMessage : savedMessage + ' Set up the TAT TARGETS support tab to update sheet colours.', sheetSync === 'synced' ? 'ok' : 'busy');
  }

  function bootstrap(data) {
    state.data = data;
    if (!data.authorized) throw new Error(data.reason || 'Unauthorized.');
    $('loadingBrand').classList.add('hidden');
    const user = data.user || {};
    const roles = (user.roles || []).join(', ') || 'Staff';
    $('userLine').textContent = `${user.name || 'Staff'} | ${roles}`;
    $('statRole').textContent = user.name || 'Staff';
    fillSelect(document.querySelector('[name="product_key"]'), data.products, 'key', 'label');
    fillSelect(document.querySelector('[name="branch"]'), (data.branches || []).map((value) => ({ value, label: value })), 'value', 'label');
    fillFilterSelect($('queueProductFilter'), data.products, 'key', 'label', 'All products');
    fillFilterSelect($('queueBranchFilter'), (data.branches || []).map((value) => ({ value, label: value })), 'value', 'label', 'All branches');
    const broInput = document.querySelector('[name="bro_name"]');
    const broOptions = [{ value: '', label: 'Select BRO' }].concat((data.bro_names || []).map((name) => ({ value: name, label: name })));
    fillSelect(broInput, broOptions, 'value', 'label');
    if ((data.bro_names || []).includes(currentUserName())) broInput.value = currentUserName();
    renderHome(data);
    if (isTargetManager()) {
      $('targetSettingsTab').classList.remove('hidden');
      $('trackerTabs').classList.add('has-settings');
    }
    setStatus('Ready.', 'ok');
  }

  async function refresh(options) {
    const background = Boolean(options && options.background);
    if (!background) setStatus('Refreshing queue...', 'busy');
    try {
      const result = await api('/api/tat-tracker/home/', homePayload());
      renderHome(result.data);
      if (!background) setStatus('Queue updated.', 'ok');
      return result;
    } catch (error) {
      if (!background) setStatus(error.message, 'error');
      throw error;
    }
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
          <span class="divider">&middot;</span>
          <span class="detail-product">${escapeHtml(summary.product || '')}</span>
          <span class="divider">&middot;</span>
          <span class="detail-branch">${escapeHtml(summary.branch || '')}</span>
        </div>
      </div>
      <div class="summary-facts">
        <div class="fact">
          <small>Amount</small>
          <span class="highlight-val">KES ${escapeHtml(formatMoney(summary.amount || ''))}</span>
        </div>
        <div class="fact">
          <small>ID Number</small>
          <span>${escapeHtml(summary.national_id || 'Not recorded')}</span>
        </div>
        <div class="fact">
          <small>Phone Number</small>
          <span>${escapeHtml(summary.primary_phone || 'Not recorded')}</span>
        </div>
        <div class="fact">
          <small>Next Action</small>
          <span>${escapeHtml(summary.next_stage || 'No pending action')}</span>
        </div>
        <div class="fact">
          <small>Total TAT</small>
          <span class="tat-badge ${escapeHtml(summary.sla_status || '')}">${escapeHtml(formatMinutes(summary.tat_minutes) || 'Not started')}</span>
        </div>
        <div class="fact fact-activity">
          <small>Activity</small>
          <div class="activity-times">
            <div><small>Created</small><span>${escapeHtml(summary.created_at || '')}</span></div>
            <div><small>Updated</small><span>${escapeHtml(summary.updated_at || '')}</span></div>
          </div>
        </div>
      </div>`;

    $('remarksInput').value = detail.remarks || '';
    const fields = $('stageFields');
    fields.innerHTML = '';
    detail.fields.forEach((field) => {
      const row = document.createElement('div');
      const hasValue = Boolean(field.value);
      row.className = 'stage-row' + (hasValue ? ' done' : field.editable ? ' editable' : ' locked');
      
      let indicatorHtml = '';
      if (hasValue) {
        indicatorHtml = `<span class="indicator-icon check-done"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round" width="11" height="11"><polyline points="20 6 9 17 4 12"/></svg></span>`;
      } else if (field.editable) {
        indicatorHtml = `<span class="indicator-icon pulse-active"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" width="12" height="12"><circle cx="12" cy="12" r="10"/><path d="M12 8v4l3 3"/></svg></span>`;
      } else {
        indicatorHtml = `<span class="indicator-icon lock-locked"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" width="11" height="11"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg></span>`;
      }

      const valueText = field.value || (field.locked_reason ? 'Pending previous stages' : 'Not started');
      const tatText = formatMinutes(field.tat_minutes);
      const targetText = formatMinutes(field.target_minutes);
      const slaText = slaLabel(field.sla_status);
      const tatMeta = tatText ? `
        <div class="stage-tat-row">
          <span class="tat-badge ${escapeHtml(field.sla_status || '')}">${escapeHtml(tatText)}</span>
          ${targetText ? `<span class="tat-target">Target ${escapeHtml(targetText)}</span>` : ''}
          ${slaText ? `<span class="tat-target">${escapeHtml(slaText)}</span>` : ''}
        </div>
      ` : '';
      const certificateMeta = field.certificate_status ? `<div class="stage-tat-row"><span class="tat-target">Certificate: ${escapeHtml(field.certificate_status.replace(/_/g, ' '))}</span></div>` : '';
      
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
          ${tatMeta}
          ${certificateMeta}
        </div>`;

      if (field.editable) {
        const actionWrap = document.createElement('div');
        actionWrap.className = 'stage-action-wrap';
        if (field.kind === 'dropdown') {
          const select = document.createElement('select');
          select.setAttribute('aria-label', 'Update ' + field.label);
          select.innerHTML = '<option value="">Select outcome...</option>' + (field.options || []).map((option) => `<option value="${escapeHtml(option)}">${escapeHtml(option)}</option>`).join('');
          select.value = field.value || '';
          select.addEventListener('change', () => saveDropdownStageUpdate(select, field));
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
            <div class="event-meta">${escapeHtml(event.actor)} &middot; ${escapeHtml(event.at)}</div>
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

  async function loadMoreHome(kind) {
    if (state.loadingHomePage[kind]) return;
    const buttonId = kind === 'action_required' ? 'loadMoreQueueBtn' : 'loadMoreRecentBtn';
    const button = $(buttonId);
    const offset = (state.home[kind] || []).length;
    try {
      state.loadingHomePage[kind] = true;
      setButtonLoading(button, true, 'Loading');
      const payload = kind === 'action_required'
        ? { action_offset: offset }
        : { recent_offset: offset };
      const result = await api('/api/tat-tracker/home/', homePayload(payload));
      renderHome(result.data, kind);
    } catch (error) {
      setStatus(error.message, 'error');
    } finally {
      state.loadingHomePage[kind] = false;
      setButtonLoading(button, false);
    }
  }

  async function saveDropdownStageUpdate(select, field) {
    const previousValue = field.value || '';
    if (!select.value || select.value === previousValue) return;
    select.disabled = true;
    try {
      await submitUpdate([{ field: field.key, value: select.value }]);
    } catch (error) {
      select.value = previousValue;
      setStatus(error.message, 'error');
    } finally {
      select.disabled = false;
    }
  }

  document.querySelectorAll('.tabs button').forEach((button) => button.addEventListener('click', () => {
    show(button.dataset.view);
    if (button.dataset.view === 'settings') loadTargetSettings().catch((error) => setStatus(error.message, 'error'));
  }));
  $('refreshBtn').addEventListener('click', () => {
    if (state.refreshing) return;
    state.refreshing = true;
    window.location.reload();
  });
  $('backBtn').addEventListener('click', () => { show('queue'); refresh().catch(() => {}); });
  $('loadMoreQueueBtn').addEventListener('click', () => loadMoreHome('action_required'));
  $('loadMoreRecentBtn').addEventListener('click', () => loadMoreHome('recent'));
  $('queueProductFilter').addEventListener('change', () => refresh().catch(() => {}));
  $('queueBranchFilter').addEventListener('change', () => refresh().catch(() => {}));
  $('saveRemarksBtn').addEventListener('click', async (event) => {
    const button = event.currentTarget;
    try {
      setButtonLoading(button, true, 'Saving');
      await submitUpdate([{ field: 'remarks', value: $('remarksInput').value }]);
    } catch (error) {
      setStatus(error.message, 'error');
    } finally {
      setButtonLoading(button, false);
    }
  });
  $('targetSettingsForm').addEventListener('submit', async (event) => {
    event.preventDefault();
    if (state.savingTargets) return;
    try {
      state.savingTargets = true;
      setButtonLoading($('saveTargetSettingsBtn'), true, 'Saving');
      setStatus('Saving TAT targets...', 'busy');
      await saveTargetSettings();
    } catch (error) {
      setStatus(error.message, 'error');
    } finally {
      state.savingTargets = false;
      setButtonLoading($('saveTargetSettingsBtn'), false);
    }
  });

  $('closeNoticeBtn').addEventListener('click', closeNotice);

  $('searchBtn').addEventListener('click', runSearch);
  $('searchInput').addEventListener('input', scheduleSearch);
  $('searchInput').addEventListener('keydown', (event) => {
    if (event.key === 'Enter') runSearch();
  });

  function scheduleSearch() {
    clearTimeout(state.searchTimer);
    const query = $('searchInput').value.trim();
    if (query.length < 2) {
      $('searchList').innerHTML = '';
      return;
    }
    state.searchTimer = setTimeout(runSearch, 220);
  }

  async function runSearch() {
    const query = $('searchInput').value.trim();
    if (query.length < 2) return;
    const requestNumber = (state.searchRequestNumber || 0) + 1;
    state.searchRequestNumber = requestNumber;
    try {
      const result = await api('/api/tat-tracker/search/', { query });
      if (requestNumber !== state.searchRequestNumber) return;
      if (!(await renderTatSearchFragment(query))) {
        renderList('searchList', result.results, 'No matching cases', 'Try a client name, ID number, phone, case ID, branch, or BRO.');
      }
    } catch (error) {
      if (requestNumber === state.searchRequestNumber) setStatus(error.message, 'error');
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
      if (broInput) broInput.value = payload.bro_name || '';
      setStatus('Case created. Continue from the highlighted stage.', 'ok');
      refresh({ background: true }).catch(() => {});
    } catch (error) {
      setStatus(error.message, 'error');
    } finally {
      state.creatingCase = false;
      setButtonLoading(submitButton, false);
    }
  });

  configureHtmx();
  api('/api/tat-tracker/bootstrap/', {})
    .then((result) => bootstrap(result.data))
    .catch((error) => setStatus(error.message, 'error'));
})();
