(function () {
  const utils = window.MiniAppUtils || {};
  const tatApi = window.TatMiniAppApi || {};
  const tg = window.MiniAppTelegram ? window.MiniAppTelegram.init() : (utils.initTelegram ? utils.initTelegram() : null);
  const body = document.body;
  const state = {
    groupId: body.dataset.groupId || '',
    token: body.dataset.token || '',
    taskToken: body.dataset.taskToken || '',
    initData: tg ? tg.initData || '' : '',
    data: null,
    detail: null,
    currentView: 'queue',
    pendingCreateRequestId: readPendingCreateRequestId(),
    creatingCase: false,
    refreshing: false,
    home: { queue: 'role', items: [], metrics: {}, visibility: {}, pagination: {} },
    homeQueue: 'role',
    homePages: { assigned: 1, role: 1, all: 1 },
    autoSelectHomeQueue: true,
    // Keep the last server-confirmed queue so a transient return request
    // cannot leave the user looking at an empty list.
    lastSuccessfulHome: null,
    homeRequestNumber: 0,
    homeRequestsInFlight: 0,
    pendingHome: null,
    lastSuccessfulRefreshAt: null,
    lastSuccessfulRefreshPerformance: null,
    consecutiveRefreshFailures: 0,
    counterDisplayedSeconds: {},
    businessTimeEnabled: true,
    detailRequestNumber: 0,
    detailRequestsInFlight: 0,
    pendingDetail: null,
    loadingHomePage: false,
    identityContextRequestNumber: 0,
    identityContextTimer: null,
    pendingCorrection: null,
    workflowMode: null,
    taskInbox: { items: [], unread_count: 0, total: 0 },
    pendingStageUpdate: null,
    directTask: null,
    filterSheetOpen: false,
    filterSheetReturnFocus: null,
    personalPreference: { show_business_hours_time: true },
  };

  const $ = (id) => document.getElementById(id);
  let statusTimeout = null;
  let noticeTimeout = null;

  function bindCollapsingHeader() {
    const header = $('appHeader');
    if (!header) return;
    let previousY = Math.max(0, window.scrollY || 0);
    let scheduled = false;
    const update = () => {
      scheduled = false;
      const currentY = Math.max(0, window.scrollY || 0);
      const delta = currentY - previousY;
      if (currentY <= 12 || delta < -4 || header.contains(document.activeElement)) {
        header.classList.remove('header-hidden');
      } else if (currentY > header.offsetHeight && delta > 4) {
        header.classList.add('header-hidden');
      }
      previousY = currentY;
    };
    window.addEventListener('scroll', () => {
      if (!scheduled) {
        scheduled = true;
        window.requestAnimationFrame(update);
      }
    }, { passive: true });
    header.addEventListener('focusin', () => header.classList.remove('header-hidden'));
  }

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
    return Object.assign({
      group_id: state.groupId,
      token: state.token,
      init_data: state.initData,
      workflow_mode_version: state.workflowMode ? state.workflowMode.mode_version : '',
    }, extra || {});
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
    const body = basePayload(payload);
    const requestId = utils.ensureRequestId
      ? utils.ensureRequestId(body, 'tat')
      : (body.client_request_id || `tat-${Date.now()}-${Math.random().toString(16).slice(2)}`);
    const headers = {
      'Content-Type': 'application/json',
      'X-Request-ID': requestId,
      'Idempotency-Key': requestId,
    };
    try {
      if (tatApi.postJson) return await tatApi.postJson(path, body, utils);
      if (utils.fetchJson) {
        return await utils.fetchJson(path, {
          method: 'POST',
          headers,
          body: JSON.stringify(body),
        });
      }
      const response = await fetch(path, {
        method: 'POST',
        headers,
        body: JSON.stringify(body),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data.ok) {
        const error = new Error(data.error || 'Request failed.');
        error.code = data.code || '';
        throw error;
      }
      return data;
    } catch (error) {
      if (error && error.code === 'WORKFLOW_MODE_CHANGED') {
        setStatus('Workflow mode changed. Reloading the current operational queue…', 'error');
        window.setTimeout(() => window.location.reload(), 900);
      }
      throw error;
    }
  }

  async function fragmentPost(path, payload) {
    const body = basePayload(payload);
    const requestId = utils.ensureRequestId
      ? utils.ensureRequestId(body, 'tat-fragment')
      : (body.client_request_id || `tat-fragment-${Date.now()}-${Math.random().toString(16).slice(2)}`);
    const headers = {
      'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8',
      'X-Request-ID': requestId,
      'Idempotency-Key': requestId,
    };
    if (tatApi.postFragment) return tatApi.postFragment(path, body, utils);
    if (utils.fetchHtml && utils.formBody) {
      return utils.fetchHtml(path, {
        method: 'POST',
        headers,
        body: utils.formBody(body),
      });
    }
    const response = await fetch(path, {
      method: 'POST',
      headers,
      body: new URLSearchParams(body).toString(),
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
    if (tone === 'ok' || tone === 'error') utils.haptic?.(tone === 'ok' ? 'success' : 'error');
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
    if (tg && tg.BackButton) {
      if (view === 'detail') tg.BackButton.show();
      else tg.BackButton.hide();
    }
  }

  function escapeHtml(value) {
    if (utils.escapeHtml) return utils.escapeHtml(value);
    return String(value == null ? '' : value).replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[char]));
  }

  function normalizePastedFieldValue(input, value) {
    const text = String(value == null ? '' : value).replace(/\r\n?/g, '\n').trim();
    if (input.dataset.pasteNormalize === 'digits') return text.replace(/\D/g, '');
    if (input.dataset.pasteNormalize === 'amount') {
      // Keep the decimal sign and digits, while accepting values copied as
      // "KES 10,000" or "10,000" from another operational system.
      return text.replace(/[^\d.,-]/g, '').replace(/,/g, '');
    }
    return text;
  }

  function insertPastedFieldValue(input, value) {
    if (input.type === 'number') {
      input.value = value;
    } else {
      const start = typeof input.selectionStart === 'number' ? input.selectionStart : input.value.length;
      const end = typeof input.selectionEnd === 'number' ? input.selectionEnd : input.value.length;
      if (typeof input.setRangeText === 'function') {
        input.setRangeText(value, start, end, 'end');
      } else {
        input.value = input.value.slice(0, start) + value + input.value.slice(end);
      }
    }
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
  }

  function configureClipboardFields() {
    // Delegation also covers the stage-correction input created on demand.
    document.addEventListener('paste', (event) => {
      const input = event.target && event.target.closest ? event.target.closest('.tat-paste-field') : null;
      if (!input || input.disabled || input.readOnly) return;
      const clipboard = event.clipboardData || window.clipboardData;
      const text = clipboard && clipboard.getData ? clipboard.getData('text/plain') : '';
      if (!text) return;
      event.preventDefault();
      insertPastedFieldValue(input, normalizePastedFieldValue(input, text));
    });
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
    const raw = String(value == null ? '' : value).replace(/,/g, '').trim();
    if (!raw) return '';
    const number = Number(raw);
    if (!Number.isFinite(number)) return '';
    let minutes = Math.max(0, Math.round(number));
    const days = Math.floor(minutes / 1440);
    minutes %= 1440;
    const hours = Math.floor(minutes / 60);
    minutes %= 60;
    const parts = [];
    if (days) parts.push(`${days} day${days === 1 ? '' : 's'}`);
    if (hours) parts.push(`${hours} hr${hours === 1 ? '' : 's'}`);
    if (minutes || !parts.length) parts.push(`${minutes} min`);
    return parts.join(' + ');
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
          ${escapeHtml(utils.formatDateTime ? utils.formatDateTime(item.updated_at) : (item.updated_at || ''))}
        </span>
      </div>`;
    button.addEventListener('click', () => openCase(item.case_id, item.stage_key || ''));
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

  function queuePresentation(queue) {
    const metrics = state.home.metrics || {};
    const visibility = state.home.visibility || {};
    const accessibleTotal = Number(metrics.total || 0);
    if (!accessibleTotal && visibility.message) {
      return ['All cases', 'No cases available', visibility.message];
    }
    if (queue === 'assigned') {
      return [
        'Assigned to me',
        'No assigned tasks',
        accessibleTotal
          ? `${accessibleTotal} accessible ${accessibleTotal === 1 ? 'case is' : 'cases are'} still available under All cases.`
          : 'Direct primary and backup work will appear here.',
      ];
    }
    if (queue === 'all') {
      return [
        'All cases',
        'No cases found',
        visibility.filters_active ? visibility.message : 'No accessible cases have been created yet.',
      ];
    }
    return [
      'Ready for my role',
      'No role actions',
      accessibleTotal
        ? `${accessibleTotal} accessible ${accessibleTotal === 1 ? 'case is' : 'cases are'} visible under All cases, but none currently require your roles.`
        : 'Cases your current roles can action will appear here.',
    ];
  }

  function formatElapsedSeconds(value) {
    if (window.MiniAppRuntime?.formatElapsedSeconds) {
      return window.MiniAppRuntime.formatElapsedSeconds(value);
    }
    let seconds = Math.max(0, Math.floor(Number(value) || 0));
    const days = Math.floor(seconds / 86400);
    seconds %= 86400;
    const hours = Math.floor(seconds / 3600);
    seconds %= 3600;
    const minutes = Math.floor(seconds / 60);
    seconds %= 60;
    const parts = [];
    if (days) parts.push(`${days}d`);
    if (hours || days) parts.push(`${hours}h`);
    parts.push(`${minutes}m`);
    parts.push(`${String(seconds).padStart(2, '0')}s`);
    return parts.join(' ');
  }

  function tatCounterMarkup(record, key) {
    const elapsed = Number(record && record.elapsed_seconds);
    if (!Number.isFinite(elapsed)) return escapeHtml(formatMinutes(record && (record.wall_clock_minutes || record.tat_minutes)) || 'Not started');
    const previous = state.counterDisplayedSeconds[key];
    const reconciled = Number.isFinite(previous) && Math.abs(previous - elapsed) >= 5;
    return `<span class="live-tat-counter${reconciled ? ' reconciled' : ''}" data-counter-key="${escapeHtml(key)}" data-elapsed-seconds="${elapsed}" data-calculated-at="${escapeHtml(record.calculated_at || record.server_now || '')}" data-running="${record.running ? 'true' : 'false'}" data-target-seconds="${record.target_seconds == null ? '' : escapeHtml(record.target_seconds)}">${escapeHtml(formatElapsedSeconds(elapsed))}</span>${reconciled ? '<small class="tat-reconciled-note">Updated from server</small>' : ''}`;
  }

  function hydrateTatCounters(root) {
    const scope = root || document;
    scope.querySelectorAll('[data-counter-key]').forEach((node) => {
      window.setTimeout(() => node.classList.remove('reconciled'), 1600);
      const note = node.parentElement?.querySelector('.tat-reconciled-note');
      if (note) window.setTimeout(() => note.remove(), 2200);
    });
    if (window.MiniAppRuntime?.hydrateServerCounters) {
      window.MiniAppRuntime.hydrateServerCounters(scope, {
        selector: '[data-counter-key]',
        onTick: updateTatCounterPresentation,
      });
    } else {
      scope.querySelectorAll('[data-counter-key]').forEach((node) => {
        node._serverClock = window.MiniAppRuntime?.createServerClock(node.dataset.calculatedAt);
      });
      tickTatCounters();
    }
  }

  function updateTatCounterPresentation(node, elapsed) {
    state.counterDisplayedSeconds[node.dataset.counterKey] = elapsed;
      const target = Number(node.dataset.targetSeconds);
      const badge = node.closest('.tat-badge');
      if (badge && Number.isFinite(target) && target > 0) {
        badge.classList.remove('within', 'near', 'over');
        const status = elapsed > target ? 'over' : elapsed >= target * 0.8 ? 'near' : 'within';
        badge.classList.add(status);
        const label = badge.parentElement?.querySelector('.live-tat-sla-label');
        if (label) label.textContent = slaLabel(status);
      }
  }

  function tickTatCounters() {
    if (window.MiniAppRuntime?.tickServerCounters) {
      window.MiniAppRuntime.tickServerCounters(document, {
        selector: '[data-counter-key]',
        onTick: updateTatCounterPresentation,
      });
      return;
    }
    document.querySelectorAll('[data-counter-key]').forEach((node) => {
      let elapsed = Math.max(0, Number(node.dataset.elapsedSeconds) || 0);
      if (node.dataset.running === 'true' && node._serverClock) {
        elapsed += Math.max(0, Math.floor((node._serverClock.nowMs() - node._serverClock.serverEpochMs) / 1000));
      }
      node.textContent = formatElapsedSeconds(elapsed);
      updateTatCounterPresentation(node, elapsed);
    });
  }

  function renderActiveFilters() {
    const filters = currentHomeFilters();
    const chips = [];
    const products = (state.data || {}).products || [];
    filters.product_keys.forEach((value) => {
      const product = products.find((item) => item.key === value);
      chips.push(['product_keys', value, product ? product.label : value]);
    });
    filters.branches.forEach((value) => chips.push(['branches', value, value]));
    filters.statuses.forEach((value) => chips.push(['statuses', value, value]));
    const container = $('activeQueueFilters');
    container.hidden = !chips.length;
    container.innerHTML = chips.map(([key, value, label]) => (
      `<button type="button" class="filter-chip" data-remove-filter="${escapeHtml(key)}" data-filter-value="${escapeHtml(value)}"><span>${escapeHtml(label)}</span><span aria-hidden="true">&times;</span></button>`
    )).join('');
    container.querySelectorAll('[data-remove-filter]').forEach((button) => button.addEventListener('click', async () => {
      const group = {
        product_keys: 'queueProductFilters',
        branches: 'queueBranchFilters',
        statuses: 'queueStatusFilters',
      }[button.dataset.removeFilter];
      const input = group && Array.from($(group)?.querySelectorAll('input[type="checkbox"]') || [])
        .find((candidate) => candidate.value === button.dataset.filterValue);
      if (input) input.checked = false;
      await applyQueueFilters();
    }));
    $('openQueueFiltersBtn').classList.toggle('active', Boolean(chips.length));
    $('openQueueFiltersBtn').querySelector('b').hidden = !chips.length;
  }

  function renderHome(data) {
    const page = data || {};
    const legacyItems = state.homeQueue === 'all' ? (page.recent || []) : (page.action_required || []);
    state.home = {
      queue: page.queue || state.homeQueue,
      items: page.items || legacyItems,
      metrics: page.metrics || {},
      visibility: page.visibility || {},
      pagination: page.pagination || {},
    };
    state.homeQueue = state.home.queue;
    state.homePages[state.homeQueue] = Number(state.home.pagination.page || state.homePages[state.homeQueue] || 1);
    const metrics = state.home.metrics;
    const values = {
      statAssigned: metrics.assigned,
      statRoleQueue: metrics.role,
      statTotal: metrics.total,
      statCompleted: metrics.completed,
      statStalled: metrics.stalled,
      assignedTabCount: metrics.assigned,
      roleTabCount: metrics.role,
      allTabCount: metrics.total,
    };
    Object.entries(values).forEach(([id, value]) => { $(id).textContent = Number(value || 0); });
    document.querySelectorAll('[data-home-queue]').forEach((button) => {
      button.classList.toggle('active', button.dataset.homeQueue === state.homeQueue);
    });
    const presentation = queuePresentation(state.homeQueue);
    $('activeQueueHeading').textContent = presentation[0];
    const total = Number(state.home.pagination.total ?? state.home.items.length);
    $('activeQueueCount').textContent = `${total} ${total === 1 ? 'case' : 'cases'}`;
    renderList('queueList', state.home.items, presentation[1], presentation[2]);
    const pages = Number(state.home.pagination.pages || 1);
    const currentPage = Number(state.home.pagination.page || 1);
    $('queuePagination').hidden = pages <= 1;
    $('queuePageLabel').textContent = `Page ${currentPage} of ${pages}`;
    $('queuePreviousBtn').disabled = currentPage <= 1;
    $('queueNextBtn').disabled = currentPage >= pages;
    renderActiveFilters();
  }

  function renderTaskInbox(inbox) {
    const data = inbox || { items: [], unread_count: 0, total: 0 };
    state.taskInbox = data;
    const section = $('privateTaskSection');
    const list = $('privateTaskList');
    if (!section || !list) return;
    const items = data.items || [];
    $('privateTaskCount').textContent = data.unread_count || data.total || items.length;
    section.hidden = !items.length;
    list.replaceChildren();
    items.forEach((item) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = `task-inbox-card${item.unread ? ' unread' : ''}`;
      button.innerHTML = `
        <span class="task-card-copy">
          <strong>${escapeHtml(item.stage_label)}</strong>
          <small>${escapeHtml(item.case_id)} &middot; ${escapeHtml(item.product)} &middot; ${escapeHtml(item.branch)}</small>
        </span>
        <span class="task-card-meta">
          <span class="role-chip">${escapeHtml(item.kind === 'backup' ? 'Backup cover' : item.role)}</span>
          <span aria-hidden="true">&rsaquo;</span>
        </span>`;
      button.addEventListener('click', () => openCase(item.case_id, item.stage_key));
      list.appendChild(button);
    });
  }

  function renderPrivateAlertConnection(connection) {
    const data = connection || { status: 'unknown', connected: false };
    const button = $('connectPrivateAlertsBtn');
    const text = $('privateAlertStatusText');
    button.hidden = false;
    button.dataset.connected = data.connected ? 'true' : 'false';
    button.textContent = data.connected ? 'Disconnect private alerts' : 'Connect private alerts';
    if (data.connected) {
      text.textContent = 'Connected. Assigned TAT actions can be delivered to your private Telegram chat.';
    } else if (data.status === 'disconnected') {
      text.textContent = 'Disconnected. Assigned work remains available in this Mini App inbox, but private Telegram alerts are paused.';
    } else if (data.status === 'blocked') {
      text.textContent = 'The bot is blocked or private delivery was withdrawn. Unblock the bot, then reconnect.';
    } else if (data.status === 'temporary_failure') {
      text.textContent = 'Private delivery is temporarily failing. Your tasks remain available in this inbox.';
    } else {
      text.textContent = 'Not connected. Start the bot privately, then connect alerts so assigned work reaches your inbox.';
    }
  }

  function consumeTaskLaunchUrl() {
    state.taskToken = '';
    body.dataset.taskToken = '';
    try {
      const url = new URL(window.location.href);
      const keys = ['startapp', 'start_param', 'tgWebAppStartParam'];
      keys.forEach((key) => url.searchParams.delete(key));
      const rawHash = url.hash.replace(/^#/, '');
      if (rawHash.includes('=')) {
        const hashParams = new URLSearchParams(rawHash);
        let changed = false;
        keys.forEach((key) => {
          if (hashParams.has(key)) {
            hashParams.delete(key);
            changed = true;
          }
        });
        if (changed) url.hash = hashParams.toString() ? `#${hashParams.toString()}` : '';
      }
      window.history.replaceState(window.history.state, '', url.toString());
    } catch (error) {
      // The in-memory token is still consumed. History replacement is a UX
      // safeguard and must not block access in older Telegram WebViews.
    }
  }

  function returnToQueue() {
    state.directTask = null;
    show('queue');
    setStatus('');
    // The bootstrap queue is already usable. Reconcile it quietly so Back is
    // instant and a temporary network failure cannot replace navigation with
    // a misleading foreground error.
    refresh({ background: true }).catch(() => {});
  }

  async function loadTaskInbox() {
    const result = await api('/api/tat-tracker/tasks/', {});
    renderTaskInbox(result.data || {});
    renderPrivateAlertConnection((result.data || {}).private_alerts || {});
    return result.data || {};
  }

  function snapshotHome() {
    return {
      queue: state.home.queue,
      items: (state.home.items || []).slice(),
      metrics: Object.assign({}, state.home.metrics || {}),
      pagination: Object.assign({}, state.home.pagination || {}),
      filters: currentHomeFilters(),
    };
  }

  function restoreLastSuccessfulHome() {
    if (!state.lastSuccessfulHome) return false;
    renderHome(state.lastSuccessfulHome);
    return true;
  }

  function queueRenderIsSafe() {
    const correctionOpen = !$('caseCorrectionPanel')?.classList.contains('hidden');
    return !state.filterSheetOpen
      && !state.creatingCase
      && !state.pendingStageUpdate
      && !state.pendingCorrection
      && !correctionOpen
      && !newCaseProtection?.isDirty?.()
      && !personalSettingsProtection?.isDirty?.()
      && !targetSettingsProtection?.isDirty?.()
      && !holidaySettingsProtection?.isDirty?.()
      && !escalationSettingsProtection?.isDirty?.();
  }

  function detailRenderIsSafe() {
    const remarksDirty = Boolean(
      state.detail
      && $('remarksInput')
      && $('remarksInput').value !== String(state.detail.remarks || ''),
    );
    return !state.pendingStageUpdate
      && !state.pendingCorrection
      && $('caseCorrectionPanel')?.classList.contains('hidden')
      && !caseCorrectionProtection?.isDirty?.()
      && !remarksDirty;
  }

  function applyPendingDetail() {
    if (!state.pendingDetail || !detailRenderIsSafe()) return false;
    state.detail = state.pendingDetail;
    state.pendingDetail = null;
    renderDetail(state.detail);
    return true;
  }

  function applyPendingHome() {
    if (!state.pendingHome || !queueRenderIsSafe()) return false;
    const pending = state.pendingHome;
    state.pendingHome = null;
    renderHomePreservingScroll(pending);
    state.lastSuccessfulHome = snapshotHome();
    return true;
  }

  function renderHomePreservingScroll(home) {
    const scrollTop = window.scrollY || document.documentElement.scrollTop || 0;
    renderHome(home);
    window.requestAnimationFrame(() => window.scrollTo(0, scrollTop));
  }

  function markRefreshSuccess() {
    state.lastSuccessfulRefreshAt = new Date();
    state.lastSuccessfulRefreshPerformance = window.performance?.now?.() ?? null;
    state.consecutiveRefreshFailures = 0;
    updateQueueFreshness();
  }

  function markBackgroundRefreshFailure() {
    state.consecutiveRefreshFailures += 1;
    updateQueueFreshness();
  }

  function refreshAgeSeconds() {
    if (state.lastSuccessfulRefreshPerformance != null && window.performance?.now) {
      return Math.max(0, Math.floor((window.performance.now() - state.lastSuccessfulRefreshPerformance) / 1000));
    }
    if (!state.lastSuccessfulRefreshAt) return null;
    return Math.max(0, Math.floor((Date.now() - state.lastSuccessfulRefreshAt.getTime()) / 1000));
  }

  function relativeRefreshAge(seconds) {
    if (seconds == null || seconds < 10) return 'just now';
    if (seconds < 60) return `${seconds} seconds ago`;
    const minutes = Math.floor(seconds / 60);
    return `${minutes} minute${minutes === 1 ? '' : 's'} ago`;
  }

  function updateQueueFreshness() {
    const indicator = $('queueFreshness');
    if (!indicator) return;
    const age = relativeRefreshAge(refreshAgeSeconds());
    const failing = state.consecutiveRefreshFailures >= 2;
    indicator.classList.toggle('refresh-failing', failing);
    indicator.textContent = failing
      ? `Couldn’t refresh — showing data from ${age}`
      : `Updated ${age}`;
  }

  function homeHasItems(home) {
    return Boolean(home && home.items && home.items.length);
  }

  function sameHomeFilters(left, right) {
    return Boolean(left && right)
      && filterValuesEqual(left.product_keys, right.product_keys)
      && filterValuesEqual(left.branches, right.branches)
      && filterValuesEqual(left.statuses, right.statuses)
      && String(left.queue || '') === String(right.queue || '')
      && Number(left.page || 1) === Number(right.page || 1);
  }

  function filterValuesEqual(left, right) {
    return JSON.stringify([].concat(left || []).slice().sort()) === JSON.stringify([].concat(right || []).slice().sort());
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

  function renderFilterCheckboxes(container, items, valueKey, labelKey, groupName) {
    if (!container) return;
    container.innerHTML = (items || []).map((item) => (
      `<label class="filter-checkbox-option"><input type="checkbox" name="${escapeHtml(groupName)}" value="${escapeHtml(item[valueKey])}"><span>${escapeHtml(item[labelKey])}</span></label>`
    )).join('');
  }

  function checkedFilterValues(containerId) {
    return Array.from($(containerId)?.querySelectorAll('input[type="checkbox"]:checked') || []).map((input) => input.value);
  }

  function setCheckedFilterValues(containerId, values) {
    const selected = new Set([].concat(values || []).filter(Boolean).map(String));
    $(containerId)?.querySelectorAll('input[type="checkbox"]').forEach((input) => {
      input.checked = selected.has(input.value);
    });
  }

  function currentHomeFilters() {
    return {
      product_keys: checkedFilterValues('queueProductFilters'),
      branches: checkedFilterValues('queueBranchFilters'),
      statuses: checkedFilterValues('queueStatusFilters'),
      queue: state.homeQueue,
      page: state.homePages[state.homeQueue] || 1,
    };
  }

  function homePayload(extra) {
    return Object.assign({ page_size: 25 }, currentHomeFilters(), extra || {});
  }

  function focusableSheetElements() {
    return Array.from($('queueFilterSheet').querySelectorAll('button:not([disabled]), select:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex="-1"])'));
  }

  function openQueueFilters(trigger) {
    state.filterSheetOpen = true;
    state.filterSheetReturnFocus = trigger || document.activeElement;
    $('queueFilterOverlay').hidden = false;
    $('queueFilterOverlay').setAttribute('aria-hidden', 'false');
    document.body.classList.add('tat-sheet-open');
    $('queueFilterSheet').focus();
    tg?.BackButton?.show?.();
  }

  function closeQueueFilters(options) {
    if (!state.filterSheetOpen) return;
    state.filterSheetOpen = false;
    $('queueFilterOverlay').hidden = true;
    $('queueFilterOverlay').setAttribute('aria-hidden', 'true');
    document.body.classList.remove('tat-sheet-open');
    if (state.currentView !== 'detail') tg?.BackButton?.hide?.();
    if (!(options && options.restoreFocus === false)) state.filterSheetReturnFocus?.focus?.();
    state.filterSheetReturnFocus = null;
    applyPendingHome();
  }

  function trapFilterSheetFocus(event) {
    if (event.key !== 'Tab') return;
    const focusable = focusableSheetElements();
    if (!focusable.length) return event.preventDefault();
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  async function applyQueueFilters() {
    Object.keys(state.homePages).forEach((key) => { state.homePages[key] = 1; });
    closeQueueFilters({ restoreFocus: false });
    window.scrollTo(0, 0);
    await refresh();
    $('openQueueFiltersBtn').focus();
  }

  async function selectHomeQueue(queue) {
    if (!['assigned', 'role', 'all'].includes(queue) || queue === state.homeQueue) return;
    state.autoSelectHomeQueue = false;
    state.homeQueue = queue;
    window.scrollTo(0, 0);
    await refresh();
  }

  async function changeHomePage(delta) {
    const pagination = state.home.pagination || {};
    const current = Number(pagination.page || 1);
    const pages = Number(pagination.pages || 1);
    const next = Math.max(1, Math.min(pages, current + delta));
    if (next === current) return;
    state.homePages[state.homeQueue] = next;
    window.scrollTo(0, 0);
    await refresh();
  }

  function isTargetManager() {
    const capabilities = ((state.data || {}).user || {}).capabilities || [];
    return capabilities.includes('tat.settings.targets.propose');
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

  function canProposeSetting(configuration, settingKey) {
    return Boolean(((configuration.cards || {})[settingKey] || {}).can_propose);
  }

  function settingsRow(className) {
    const row = document.createElement('div');
    row.className = `settings-row ${className}`;
    return row;
  }

  function appendHolidaySetting(container, holiday) {
    const row = settingsRow('settings-holiday-row');
    const dateLabel = document.createElement('label');
    dateLabel.textContent = 'Date';
    const dateInput = document.createElement('input');
    dateInput.type = 'date';
    dateInput.value = holiday && holiday.date ? holiday.date : '';
    dateInput.required = true;
    dateLabel.appendChild(dateInput);
    const nameLabel = document.createElement('label');
    nameLabel.textContent = 'Holiday name';
    const nameInput = document.createElement('input');
    nameInput.type = 'text';
    nameInput.maxLength = 160;
    nameInput.value = holiday && holiday.name ? holiday.name : '';
    nameInput.required = true;
    nameLabel.appendChild(nameInput);
    const activeLabel = document.createElement('label');
    activeLabel.className = 'check-label';
    const activeInput = document.createElement('input');
    activeInput.type = 'checkbox';
    activeInput.checked = !holiday || holiday.active !== false;
    activeLabel.append(activeInput, document.createTextNode('Exclude from SLA'));
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'ghost-btn settings-remove-row';
    remove.textContent = 'Remove';
    remove.addEventListener('click', () => row.remove());
    row.append(dateLabel, nameLabel, activeLabel, remove);
    container.appendChild(row);
  }

  function renderHolidaySettings(holidays) {
    const list = $('holidaySettingsList');
    list.replaceChildren();
    (holidays || []).forEach((holiday) => appendHolidaySetting(list, holiday));
    if (!list.childElementCount) {
      const empty = document.createElement('p');
      empty.className = 'settings-empty-copy';
      empty.textContent = 'No future holidays are configured.';
      list.appendChild(empty);
    }
  }

  function holidaySettingsPayload() {
    return { holidays: [...document.querySelectorAll('#holidaySettingsList .settings-holiday-row')].map((row) => {
      const inputs = row.querySelectorAll('input');
      return { date: inputs[0].value, name: inputs[1].value.trim(), active: inputs[2].checked };
    }) };
  }

  function appendEscalationSetting(container, rule) {
    const row = settingsRow('settings-escalation-row');
    const thresholdLabel = document.createElement('label');
    thresholdLabel.textContent = 'Threshold %';
    const thresholdInput = document.createElement('input');
    thresholdInput.type = 'number';
    thresholdInput.inputMode = 'numeric';
    thresholdInput.min = '100';
    thresholdInput.max = '1000';
    thresholdInput.step = '1';
    thresholdInput.required = true;
    thresholdInput.value = rule && rule.threshold_percent ? String(rule.threshold_percent) : '';
    thresholdLabel.appendChild(thresholdInput);
    const recipientLabel = document.createElement('label');
    recipientLabel.textContent = 'Recipient role';
    const recipient = document.createElement('select');
    [
      ['RESPONSIBLE_ROLE', 'Responsible role'],
      ['BRANCH_MANAGER', 'Branch manager'],
      ['MANAGEMENT', 'Management'],
    ].forEach(([value, label]) => {
      const option = document.createElement('option');
      option.value = value; option.textContent = label; recipient.appendChild(option);
    });
    recipient.value = rule && rule.routing_role ? rule.routing_role : 'RESPONSIBLE_ROLE';
    recipientLabel.appendChild(recipient);
    const branchLabel = document.createElement('label');
    branchLabel.textContent = 'Branch scope';
    const branch = document.createElement('select');
    const all = document.createElement('option');
    all.value = ''; all.textContent = 'All branches'; branch.appendChild(all);
    ((state.data || {}).branches || []).forEach((name) => {
      const option = document.createElement('option'); option.value = name; option.textContent = name; branch.appendChild(option);
    });
    branch.value = rule && rule.branch ? rule.branch : '';
    branchLabel.appendChild(branch);
    const remove = document.createElement('button');
    remove.type = 'button'; remove.className = 'ghost-btn settings-remove-row'; remove.textContent = 'Remove';
    remove.addEventListener('click', () => row.remove());
    row.append(thresholdLabel, recipientLabel, branchLabel, remove);
    container.appendChild(row);
  }

  function renderEscalationSettings(rules) {
    const list = $('escalationSettingsList');
    list.replaceChildren();
    const defaults = [
      { threshold_percent: 100, routing_role: 'RESPONSIBLE_ROLE', branch: '' },
      { threshold_percent: 150, routing_role: 'BRANCH_MANAGER', branch: '' },
      { threshold_percent: 200, routing_role: 'MANAGEMENT', branch: '' },
    ];
    (rules && rules.length ? rules : defaults).forEach((rule) => appendEscalationSetting(list, rule));
  }

  function escalationSettingsPayload() {
    return { rules: [...document.querySelectorAll('#escalationSettingsList .settings-escalation-row')].map((row) => {
      const inputs = row.querySelectorAll('input');
      const selects = row.querySelectorAll('select');
      return { threshold_percent: inputs[0].value, routing_role: selects[0].value, branch: selects[1].value };
    }) };
  }

  function renderConfigurationReviews(configuration) {
    const list = $('configurationReviewList');
    const pending = configuration.pending || [];
    const canApprove = Object.values(configuration.cards || {}).some((card) => card.can_approve);
    if (!pending.length || !canApprove) {
      list.classList.add('hidden');
      list.innerHTML = '';
      return;
    }
    list.innerHTML = `<div class="form-heading"><h2>Pending configuration reviews</h2><p>Approve only changes you did not propose.</p></div>${pending.map((item) => `
      <article class="settings-review-item">
        <strong>${escapeHtml(item.setting_key.replace(/_/g, ' '))}</strong>
        <span>${escapeHtml(item.reason)}</span>
        <small>${escapeHtml(item.requested_by)} · ${escapeHtml(item.requested_at)}</small>
        <div class="form-actions"><button class="secondary" type="button" data-review-setting="${escapeHtml(item.id)}" data-review-approve="true">Approve</button><button class="ghost-btn" type="button" data-review-setting="${escapeHtml(item.id)}" data-review-approve="false">Reject</button></div>
      </article>`).join('')}`;
    list.classList.remove('hidden');
    list.querySelectorAll('[data-review-setting]').forEach((button) => button.addEventListener('click', async () => {
      try {
        setButtonLoading(button, true, button.dataset.reviewApprove === 'true' ? 'Approving' : 'Rejecting');
        await api('/api/tat-tracker/settings/proposals/review/', {
          proposal_id: button.dataset.reviewSetting,
          approve: button.dataset.reviewApprove,
        });
        setStatus('Configuration review recorded.', 'ok');
        await loadSettings();
      } catch (error) {
        setStatus(error.message, 'error');
      } finally {
        setButtonLoading(button, false);
      }
    }));
  }

  async function loadSettings() {
    const result = await api('/api/tat-tracker/settings/', {});
    const personal = result.data.personal || {};
    const configuration = result.data.configuration || {};
    applyBusinessPresentation((configuration.presentation || {}).business_time_enabled !== false);
    if (utils.renderSettingsAccount) utils.renderSettingsAccount($('tatSettingsAccount'), result.data.account || {});
    if ($('tatSettingsRelease')) $('tatSettingsRelease').textContent = result.data.account?.app_release || 'Current release';
    $('preferenceDefaultScreen').value = personal.default_screen || 'home';
    $('preferenceCompactCards').checked = Boolean(personal.compact_cards);
    $('preferenceBusinessHours').checked = state.businessTimeEnabled && personal.show_business_hours_time !== false;
    const targetCard = (configuration.cards || {}).tat_targets || {};
    $('targetSettingsForm').classList.toggle('hidden', !targetCard.can_propose);
    if (targetCard.can_propose) renderTargetSettings(configuration.targets || []);
    const holidayCard = (configuration.cards || {}).business_calendar || {};
    $('holidaySettingsForm').classList.toggle('hidden', !state.businessTimeEnabled || !holidayCard.can_propose);
    if (state.businessTimeEnabled && holidayCard.can_propose) renderHolidaySettings((configuration.holidays || {}).holidays || []);
    const escalationCard = (configuration.cards || {}).tat_escalation || {};
    $('escalationSettingsForm').classList.toggle('hidden', !escalationCard.can_propose);
    if (escalationCard.can_propose) renderEscalationSettings((configuration.escalation || {}).rules || []);
    renderConfigurationReviews(configuration);
  }

  async function saveTargetSettings() {
    const result = await api('/api/tat-tracker/target-settings/', {
      targets: targetSettingsPayload(), reason: $('targetSettingsReason').value.trim(),
    });
    $('targetSettingsReason').value = '';
    setStatus(`Target change proposed (${result.data.proposal_id}). Awaiting a different authorised Business Admin.`, 'ok');
    await loadSettings();
  }

  async function saveConfigurationSettings(settingKey, proposed, reason) {
    const result = await api('/api/tat-tracker/settings/proposals/', { setting_key: settingKey, proposed, reason });
    setStatus(`Configuration change proposed (${result.data.proposal_id}). Awaiting a different authorised Business Admin.`, 'ok');
    await loadSettings();
  }

  function applyPersonalPreference(preference) {
    const personal = preference || {};
    state.personalPreference = personal;
    document.body.classList.toggle('compact-cards', Boolean(personal.compact_cards));
    document.body.classList.toggle('hide-business-hours-time', !state.businessTimeEnabled || personal.show_business_hours_time === false);
    const savedFilters = personal.default_filters || {};
    setCheckedFilterValues('queueProductFilters', savedFilters.product_keys || savedFilters.product_key || []);
    setCheckedFilterValues('queueBranchFilters', savedFilters.branches || savedFilters.branch || []);
    setCheckedFilterValues('queueStatusFilters', savedFilters.statuses || savedFilters.status || []);
    const canCreate = (((state.data || {}).user || {}).capabilities || []).includes('tat.case.create');
    return personal.default_screen === 'new' && canCreate ? 'new' : 'queue';
  }

  function applyBusinessPresentation(enabled) {
    state.businessTimeEnabled = Boolean(enabled);
    const row = $('businessTimePreferenceRow');
    if (row) row.hidden = !state.businessTimeEnabled;
    if ($('preferenceBusinessHours')) $('preferenceBusinessHours').disabled = !state.businessTimeEnabled;
    document.body.classList.toggle(
      'hide-business-hours-time',
      !state.businessTimeEnabled || state.personalPreference.show_business_hours_time === false,
    );
    if (!state.businessTimeEnabled) $('holidaySettingsForm')?.classList.add('hidden');
  }

  function bootstrap(data) {
    state.data = data;
    state.workflowMode = data.workflow_mode || null;
    state.businessTimeEnabled = (data.presentation || {}).business_time_enabled !== false;
    applyBusinessPresentation(state.businessTimeEnabled);
    if (!data.authorized) throw new Error(data.reason || 'Unauthorized.');
    $('loadingBrand').classList.add('hidden');
    const modeBanner = $('workflowModeBanner');
    if (modeBanner && state.workflowMode) {
      modeBanner.hidden = !state.workflowMode.is_pilot;
      modeBanner.classList.toggle('pilot', Boolean(state.workflowMode.is_pilot));
      modeBanner.textContent = state.workflowMode.is_pilot
        ? 'PILOT MODE · Entries are test data in the active pilot cycle.'
        : 'PRODUCTION MODE · New entries are official operational records.';
    }
    const user = data.user || {};
    const capabilities = new Set(user.capabilities || []);
    document.querySelectorAll('[data-required-capability]').forEach((node) => {
      node.hidden = !capabilities.has(node.dataset.requiredCapability);
    });
    const roles = (user.roles || []).join(', ') || 'Staff';
    $('userLine').textContent = `${user.name || 'Staff'} | ${roles}`;
    fillSelect(document.querySelector('[name="product_key"]'), data.products, 'key', 'label');
    document.querySelector('[name="product_key"]')?.addEventListener('change', renderNewCaseProductConfiguration);
    renderNewCaseProductConfiguration();
    fillSelect(document.querySelector('[name="branch"]'), (data.branches || []).map((value) => ({ value, label: value })), 'value', 'label');
    renderFilterCheckboxes($('queueProductFilters'), data.products, 'key', 'label', 'product_keys');
    renderFilterCheckboxes($('queueBranchFilters'), (data.branches || []).map((value) => ({ value, label: value })), 'value', 'label', 'branches');
    renderFilterCheckboxes($('queueStatusFilters'), (data.statuses || []).map((value) => ({ value, label: value })), 'value', 'label', 'statuses');
    const broInput = document.querySelector('[name="bro_name"]');
    const taggedBroUsers = Array.isArray(data.bro_users)
      ? data.bro_users
      : (data.bro_names || []).map((name) => ({ name }));
    const broOptions = [{ value: '', label: 'Select BRO' }].concat(
      taggedBroUsers.map((user) => ({
        value: user.name || user.username || '',
        label: user.name || user.username || 'Unnamed BRO',
      })),
    );
    fillSelect(broInput, broOptions, 'value', 'label');
    if ((data.bro_names || []).includes(currentUserName())) broInput.value = currentUserName();
    const initialMetrics = data.metrics || {};
    const initialQueue = Number(initialMetrics.assigned || 0) > 0
      ? 'assigned'
      : Number(initialMetrics.role || 0) > 0 ? 'role' : 'all';
    state.homeQueue = initialQueue;
    state.homePages[initialQueue] = 1;
    renderHome(data);
    state.lastSuccessfulHome = snapshotHome();
    markRefreshSuccess();
    renderPrivateAlertConnection(data.private_alerts || {});
    $('trackerTabs').classList.add('has-settings');
    const initialView = applyPersonalPreference(data.personal || {});
    show(initialView);
    const initialFilters = currentHomeFilters();
    if (state.home.queue !== initialQueue || initialFilters.product_keys.length || initialFilters.branches.length || initialFilters.statuses.length) {
      state.homeQueue = initialQueue;
      refresh({ background: true }).catch(() => {});
    } else {
      state.lastSuccessfulHome = snapshotHome();
    }
    setStatus('');
  }

  function productConfigurationControl(item, value, dataName) {
    const data = `${dataName}="${escapeHtml(item.key)}"`;
    if (['boolean', 'checkbox', 'eligibility'].includes(item.type)) {
      return `<label class="checkbox-row"><input type="checkbox" ${data}${value === true ? ' checked' : ''}><span>Confirmed</span></label>`;
    }
    if (item.type === 'choice') {
      return `<select ${data}><option value="">Choose</option>${(item.options || []).map(option => `<option value="${escapeHtml(option)}"${value === option ? ' selected' : ''}>${escapeHtml(option)}</option>`).join('')}</select>`;
    }
    const type = item.type === 'date' ? 'date' : ['number', 'money', 'amount'].includes(item.type) ? 'number' : 'text';
    return `<input type="${type}" ${data} value="${escapeHtml(value ?? '')}"${type === 'number' ? ' step="any" inputmode="decimal"' : ''}${item.type === 'document' ? ' placeholder="Document reference or evidence note"' : ''}>`;
  }

  function renderNewCaseProductConfiguration() {
    const container = $('newCaseProductConfiguration');
    const selectedKey = document.querySelector('[name="product_key"]')?.value || '';
    const product = (state.data?.products || []).find(item => item.key === selectedKey);
    const terms = product?.terms || {};
    const requirements = (terms.requirements || []).filter(item => item.enforcement_stage === 'created' && (!item.workflow || item.workflow === 'tat_tracker'));
    const attributes = (terms.custom_attributes || []).filter(item => !(item.workflows || []).length || item.workflows.includes('tat_tracker'));
    const fees = (terms.fees || []).filter(item => !item.mandatory);
    if (!container || !product?.version_id) {
      if (container) { container.hidden = true; container.innerHTML = ''; }
      return;
    }
    const requirementRows = requirements.map(item => `<label>${escapeHtml(item.label)}${item.required ? ' *' : ''}${item.description ? `<small>${escapeHtml(item.description)}</small>` : ''}${productConfigurationControl(item, '', 'data-product-requirement')}</label>`).join('');
    const attributeRows = attributes.map(item => `<label>${escapeHtml(item.label)}${item.required ? ' *' : ''}${item.help_text ? `<small>${escapeHtml(item.help_text)}</small>` : ''}${productConfigurationControl(item, item.default, 'data-product-custom')}</label>`).join('');
    const feeRows = fees.map(item => `<label>${escapeHtml(item.label)}<label class="checkbox-row"><input type="checkbox" data-product-fee="${escapeHtml(item.key)}"><span>Include optional ${escapeHtml(item.collection_mode)} fee</span></label></label>`).join('');
    container.innerHTML = `<h3>${escapeHtml(product.label)} terms</h3><label>Tenor (${escapeHtml(terms.tenor_unit || 'month')}s)<input name="tenor" type="number" inputmode="numeric" min="${escapeHtml(terms.min_tenor || 1)}" max="${escapeHtml(terms.max_tenor || '')}" required></label>${requirementRows}${attributeRows}${feeRows}`;
    container.hidden = false;
  }

  function collectProductConfiguration(container) {
    const requirementEvidence = {};
    const customValues = {};
    const selectedFeeKeys = [];
    container?.querySelectorAll('[data-product-requirement]').forEach(input => {
      requirementEvidence[input.dataset.productRequirement] = input.type === 'checkbox' ? input.checked : input.value;
    });
    container?.querySelectorAll('[data-product-custom]').forEach(input => {
      customValues[input.dataset.productCustom] = input.type === 'checkbox' ? input.checked : input.value;
    });
    container?.querySelectorAll('[data-product-fee]:checked').forEach(input => selectedFeeKeys.push(input.dataset.productFee));
    return { requirementEvidence, customValues, selectedFeeKeys };
  }

  async function refresh(options) {
    const background = Boolean(options && options.background);
    const periodic = Boolean(options && options.periodic);
    if (periodic && state.homeRequestsInFlight > 0) return null;
    const requestNumber = (state.homeRequestNumber || 0) + 1;
    state.homeRequestNumber = requestNumber;
    state.homeRequestsInFlight += 1;
    if (!background) setStatus('Refreshing queue...', 'busy');
    try {
      const result = await api('/api/tat-tracker/home/', homePayload());
      const nextHome = result && result.data;
      if (!nextHome || typeof nextHome !== 'object') {
        throw new Error('Queue refresh returned an invalid response. Tap Refresh to retry.');
      }
      applyBusinessPresentation((nextHome.presentation || {}).business_time_enabled !== false);
      const cachedHome = state.lastSuccessfulHome;
      if (
        cachedHome
        && homeHasItems(cachedHome)
        && sameHomeFilters(cachedHome.filters, currentHomeFilters())
        && !homeHasItems(nextHome)
        && !nextHome.metrics
      ) {
        throw new Error('Queue refresh returned no cases. Showing the last loaded queue; tap Refresh to retry.');
      }
      // A slower request started before this one must not overwrite the
      // current queue with stale (or empty) data.
      if (requestNumber !== state.homeRequestNumber) return result;
      if (queueRenderIsSafe()) {
        // A newer response applied immediately supersedes any older snapshot
        // that was held while a form or dialog was unsafe to re-render.
        state.pendingHome = null;
        renderHomePreservingScroll(nextHome);
      } else {
        state.pendingHome = nextHome;
      }
      if (
        state.autoSelectHomeQueue
        && String(nextHome.queue || state.homeQueue) === 'assigned'
        && Number((nextHome.metrics || {}).assigned || 0) === 0
        && Number((nextHome.metrics || {}).role || 0) > 0
      ) {
        state.autoSelectHomeQueue = false;
        state.homeQueue = 'role';
        return refresh(options);
      }
      state.autoSelectHomeQueue = false;
      if (!state.pendingHome) state.lastSuccessfulHome = snapshotHome();
      markRefreshSuccess();
      if (!background) setStatus('Queue updated.', 'ok');
      return result;
    } catch (error) {
      if (requestNumber === state.homeRequestNumber && background) markBackgroundRefreshFailure();
      if (requestNumber === state.homeRequestNumber && !background) {
        const restored = restoreLastSuccessfulHome();
        setStatus(
          restored
            ? 'Queue refresh failed. Showing the last loaded queue; tap Refresh to retry.'
            : (error.message || 'Queue refresh failed. Tap Refresh to retry.'),
          'error',
        );
      }
      throw error;
    } finally {
      state.homeRequestsInFlight = Math.max(0, state.homeRequestsInFlight - 1);
    }
  }

  async function refreshDetailBackground() {
    const caseId = state.detail?.summary?.case_id;
    if (!caseId || state.detailRequestsInFlight > 0) return null;
    const requestNumber = ++state.detailRequestNumber;
    state.detailRequestsInFlight += 1;
    try {
      const result = await api('/api/tat-tracker/detail/', { case_id: caseId });
      if (requestNumber !== state.detailRequestNumber || !result.data?.summary) return result;
      if (detailRenderIsSafe()) {
        state.pendingDetail = null;
        state.detail = result.data;
        renderDetail(result.data);
      } else {
        state.pendingDetail = result.data;
      }
      return result;
    } finally {
      state.detailRequestsInFlight = Math.max(0, state.detailRequestsInFlight - 1);
    }
  }

  async function openCase(caseId, focusStageKey) {
    const requestNumber = ++state.detailRequestNumber;
    state.detailRequestsInFlight += 1;
    setStatus('Opening case...', 'busy');
    let result;
    try {
      result = await api('/api/tat-tracker/detail/', { case_id: caseId });
    } finally {
      state.detailRequestsInFlight = Math.max(0, state.detailRequestsInFlight - 1);
    }
    if (requestNumber !== state.detailRequestNumber) return;
    if (state.pendingCorrection && state.pendingCorrection.caseId !== caseId) {
      state.pendingCorrection = null;
    }
    state.detail = result.data;
    state.pendingDetail = null;
    renderDetail(result.data);
    show('detail');
    setStatus('Case opened.', 'ok');
    if (focusStageKey) {
      const field = (result.data.fields || []).find((item) => item.key === focusStageKey);
      const row = [...document.querySelectorAll('[data-stage-key]')].find((node) => node.dataset.stageKey === focusStageKey);
      row?.scrollIntoView({ block: 'center', behavior: 'smooth' });
      if (field && field.editable) {
        window.setTimeout(() => row?.querySelector('.stage-action-wrap button, .stage-action-wrap select')?.focus(), 180);
      }
      else if (field) setStatus(field.value ? 'This task has already been completed.' : (field.locked_reason || 'This task is no longer actionable.'), 'error');
    }
  }

  function renderDetail(detail) {
    const summary = detail.summary;
    const escalation = detail.escalation || null;
    const correctionButton = $('correctCaseDetailsBtn');
    if (correctionButton) {
      correctionButton.classList.toggle('hidden', !detail.can_correct_details);
      fillCaseCorrectionForm(summary, detail.correction_branches || []);
    }
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
      ${summary.read_only ? `<div class="closed-pilot-notice" role="status"><strong>Closed Pilot cycle</strong><span>This case is retained for reference and can no longer be edited. Reload the queue to continue with current work.</span></div>` : ''}
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
          <small>Official TAT (wall clock)</small>
          <span class="tat-badge ${escapeHtml(summary.sla_status || '')}">${tatCounterMarkup(summary, `case:${summary.case_id}`)}</span>
          ${state.businessTimeEnabled && summary.business_minutes && state.personalPreference.show_business_hours_time !== false ? `<details class="tat-business-time"><summary>Show business-hours time</summary><small>${escapeHtml(formatMinutes(summary.business_minutes))}</small></details>` : ''}
        </div>
        <div class="fact fact-activity">
          <small>Activity</small>
          <div class="activity-times">
            <div><small>Created</small><span>${escapeHtml(utils.formatDateTime ? utils.formatDateTime(summary.created_at) : (summary.created_at || ''))}</span></div>
            <div><small>Updated</small><span>${escapeHtml(utils.formatDateTime ? utils.formatDateTime(summary.updated_at) : (summary.updated_at || ''))}</span></div>
          </div>
        </div>
      </div>
      ${escalation ? `<div class="tat-escalation level-${escapeHtml(escalation.escalation_level)}"><strong>SLA escalation: ${escapeHtml(escalation.routing_role)}</strong><span>${escapeHtml(formatMinutes(escalation.overdue_minutes))} overdue at ${escapeHtml(escalation.threshold_percent)}% threshold</span></div>` : ''}`;

    $('remarksInput').value = detail.remarks || '';
    const fields = $('stageFields');
    fields.innerHTML = '';
    detail.fields.forEach((field) => {
      const row = document.createElement('div');
      const hasValue = Boolean(field.value);
      row.className = 'stage-row' + (hasValue ? ' done' : field.editable ? ' editable' : ' locked');
      row.dataset.stageKey = field.key;
      
      let indicatorHtml = '';
      if (hasValue) {
        indicatorHtml = `<span class="indicator-icon check-done"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round" width="11" height="11"><polyline points="20 6 9 17 4 12"/></svg></span>`;
      } else if (field.editable) {
        indicatorHtml = `<span class="indicator-icon pulse-active"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" width="12" height="12"><circle cx="12" cy="12" r="10"/><path d="M12 8v4l3 3"/></svg></span>`;
      } else {
        indicatorHtml = `<span class="indicator-icon lock-locked"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" width="11" height="11"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg></span>`;
      }

      const valueText = field.value || (field.locked_reason ? 'Pending previous stages' : 'Not started');
      const businessText = formatMinutes(field.business_minutes);
      const targetText = formatMinutes(field.target_minutes);
      const slaText = slaLabel(field.sla_status);
      const hasTat = Number.isFinite(Number(field.elapsed_seconds)) || Boolean(formatMinutes(field.wall_clock_minutes || field.tat_minutes));
      const tatMeta = hasTat ? `
        <div class="stage-tat-row">
          <span class="tat-badge ${escapeHtml(field.sla_status || '')}">${tatCounterMarkup(field, `stage:${summary.case_id}:${field.key}`)}</span>
          ${targetText ? `<span class="tat-target">Target ${escapeHtml(targetText)}</span>` : ''}
          ${slaText ? `<span class="tat-target live-tat-sla-label">${escapeHtml(slaText)}</span>` : ''}
          ${state.businessTimeEnabled && businessText && state.personalPreference.show_business_hours_time !== false ? `<details class="tat-business-time"><summary>Business-hours time</summary><span class="tat-target">${escapeHtml(businessText)}</span></details>` : ''}
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
        const stageRequirements = (detail.product_requirements || []).filter(item => item.stage === field.key);
        if (stageRequirements.length) {
          const requirements = document.createElement('div');
          requirements.className = 'product-configuration-panel stage-product-requirements';
          requirements.innerHTML = `<strong>Product requirements</strong>${stageRequirements.map(item => `<label>${escapeHtml(item.label)}${item.required ? ' *' : ''}${item.description ? `<small>${escapeHtml(item.description)}</small>` : ''}${productConfigurationControl(item, item.value, 'data-product-requirement')}</label>`).join('')}`;
          actionWrap.appendChild(requirements);
        }
        if (field.kind === 'dropdown') {
          const select = document.createElement('select');
          select.setAttribute('aria-label', 'Update ' + field.label);
          select.innerHTML = '<option value="">Select outcome...</option>' + (field.options || []).map((option) => `<option value="${escapeHtml(option)}">${escapeHtml(option)}</option>`).join('');
          select.value = field.value || '';
          select.addEventListener('change', async () => {
            const selected = select.value;
            if (selected) await updateStageOnce(select, field, selected);
          });
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
          button.addEventListener('click', () => updateStageOnce(button, field, 'STAMP'));
          actionWrap.appendChild(button);
        }
        row.querySelector('.stage-content').appendChild(actionWrap);
      } else if (field.can_correct) {
        const actionWrap = document.createElement('div');
        actionWrap.className = 'stage-action-wrap';
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'secondary compact-btn';
        button.textContent = 'Correct';
        button.addEventListener('click', () => openStageCorrection(actionWrap, field));
        actionWrap.appendChild(button);
        row.querySelector('.stage-content').appendChild(actionWrap);
      } else if (field.locked_reason) {
        const note = document.createElement('div');
        note.className = 'lock-note';
        note.textContent = field.locked_reason;
        row.querySelector('.stage-content').appendChild(note);
      }
      fields.appendChild(row);
    });
    hydrateTatCounters($('detailView'));

    // Raw audit events deliberately stay out of the staff-facing case screen.
    // They remain available to authorized administrators through the immutable
    // server-side audit/timeline records; workflow stages above are the useful
    // operational summary for an officer handling this case.
    const events = $('eventList');
    if (!events) return;
    events.innerHTML = '';
    const timelineEvents = detail.timeline || detail.events || [];
    if (!timelineEvents.length) {
      events.appendChild(renderEmpty('No audit events yet', 'Updates will appear here after the case starts moving.'));
    } else {
      timelineEvents.forEach((event) => {
        const eventTitle = event.title || event.stage || 'Case event';
        const eventValue = event.detail || event.value || '';
        const eventActor = [event.actor, event.authority && `Authority: ${event.authority}`, event.origin || event.source].filter(Boolean).join(' · ');
        const eventAt = event.occurred_at ? (utils.formatDateTime ? utils.formatDateTime(event.occurred_at) : event.occurred_at) : event.at;
        const row = document.createElement('div');
        row.className = 'event-item';
        row.innerHTML = `
          <div class="event-dot"></div>
          <div class="event-body">
            <div class="event-header">
              <strong class="event-stage">${escapeHtml(eventTitle)}</strong>
              ${eventValue ? `<span class="event-value-badge">${escapeHtml(eventValue)}</span>` : ''}
            </div>
            <div class="event-meta">${escapeHtml(eventActor || 'System')} &middot; ${escapeHtml(eventAt || '')}</div>
            ${event.artifact?.url ? `<a class="event-artifact-link" href="${escapeHtml(event.artifact.url)}" target="_blank" rel="noopener">${escapeHtml(event.artifact.name || 'Open linked document')} ↗</a>` : ''}
          </div>
        `;
        events.appendChild(row);
      });
    }
  }

  function fillCaseCorrectionForm(summary, branches) {
    const form = $('caseCorrectionForm');
    if (!form || !summary) return;
    ['client_name', 'national_id', 'primary_phone', 'branch', 'bro_name', 'amount'].forEach((field) => {
      const input = form.elements[field];
      if (!input) return;
      if (field === 'branch' && input.tagName === 'SELECT') {
        input.innerHTML = (branches || []).map((branch) => `<option value="${escapeHtml(branch)}">${escapeHtml(branch)}</option>`).join('');
      }
      input.value = summary[field] || '';
    });
  }

  function renderExistingLoanContext(context) {
    const container = $('existingLoanContext');
    if (!container) return;
    const matches = context && Array.isArray(context.matches) ? context.matches : [];
    if (!matches.length) {
      container.classList.add('hidden');
      container.innerHTML = '';
      return;
    }
    const matchedOn = (context.matched_on || []).join(' and ') || 'the supplied details';
    const caseLabel = matches.length === 1 ? 'case' : 'cases';
    container.innerHTML = `
      <strong>${matches.length} existing loan ${caseLabel} found by ${escapeHtml(matchedOn)}</strong>
      <p>Creating this form still makes a separate loan case. Open an existing case if you meant to correct it.</p>
      <div class="identity-context-list">
        ${matches.map((item) => `
          <button type="button" class="identity-context-case" data-existing-tat-case="${escapeHtml(item.case_id)}">
            <span>${escapeHtml(item.case_id)} · ${escapeHtml(item.product || 'Loan')}</span>
            <strong>${escapeHtml(item.client_name || 'Existing client')}</strong>
          </button>
        `).join('')}
      </div>
    `;
    container.classList.remove('hidden');
    container.querySelectorAll('[data-existing-tat-case]').forEach((button) => {
      button.addEventListener('click', () => openCase(button.dataset.existingTatCase));
    });
  }

  function scheduleExistingLoanContext() {
    window.clearTimeout(state.identityContextTimer);
    state.identityContextTimer = window.setTimeout(loadExistingLoanContext, 280);
  }

  async function loadExistingLoanContext() {
    const form = $('newCaseForm');
    if (!form) return;
    const nationalId = String(form.elements.national_id?.value || '').trim();
    const phone = String(form.elements.primary_phone?.value || '').trim();
    const digits = phone.replace(/\D/g, '');
    if (nationalId.length < 7 && digits.length < 9) {
      renderExistingLoanContext(null);
      return;
    }
    const requestNumber = state.identityContextRequestNumber + 1;
    state.identityContextRequestNumber = requestNumber;
    try {
      const result = await api('/api/tat-tracker/identity-context/', {
        national_id: nationalId,
        primary_phone: phone,
      });
      if (requestNumber === state.identityContextRequestNumber) renderExistingLoanContext(result.data);
    } catch (error) {
      // Context is advisory only; a slow lookup must never block a valid new
      // loan submission or replace the form with a noisy transient error.
      if (requestNumber === state.identityContextRequestNumber) renderExistingLoanContext(null);
    }
  }

  function openStageCorrection(actionWrap, field) {
    const current = field.raw_value || '';
    const input = document.createElement('input');
    input.className = 'tat-paste-field';
    input.type = field.kind === 'timestamp' ? 'datetime-local' : 'text';
    input.value = field.kind === 'timestamp' ? correctionDateTimeValue(current) : current;
    input.setAttribute('aria-label', 'Correct ' + field.label);
    const save = document.createElement('button');
    save.type = 'button';
    save.className = 'primary compact-btn';
    save.textContent = 'Save';
    const cancel = document.createElement('button');
    cancel.type = 'button';
    cancel.className = 'ghost-btn compact-btn';
    cancel.textContent = 'Cancel';
    actionWrap.innerHTML = '';
    actionWrap.append(input, save, cancel);
    input.focus();
    cancel.addEventListener('click', () => renderDetail(state.detail));
    save.addEventListener('click', async () => {
      if (!input.value.trim()) {
        setStatus('Enter a correction value first.', 'error');
        return;
      }
      save.disabled = true;
      try {
        await submitUpdate([{ field: field.key, value: input.value.trim(), correction: true }]);
      } catch (error) {
        setStatus(error.message, 'error');
        save.disabled = false;
      }
    });
  }

  function correctionDateTimeValue(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '';
    const pad = (number) => String(number).padStart(2, '0');
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
  }

  async function submitCaseCorrection(event) {
    event.preventDefault();
    if (!state.detail || !state.detail.can_correct_details) return;
    const form = event.currentTarget;
    const fields = ['client_name', 'national_id', 'primary_phone', 'branch', 'bro_name', 'amount'];
    const current = state.detail.summary || {};
    const updates = fields
      .map((field) => ({ field, value: String(form.elements[field]?.value || '').trim(), correction: true }))
      .filter((item) => String(current[item.field] || '').trim() !== item.value);
    if (!updates.length) {
      setStatus('No case detail changes were entered.', 'error');
      return;
    }
    const button = $('saveCaseCorrectionBtn');
    const caseId = state.detail.summary.case_id;
    const workflowRevision = Number(state.detail.summary.workflow_revision || 1);
    const fingerprint = JSON.stringify(updates.map((item) => [item.field, item.value]));
    if (!state.pendingCorrection
      || state.pendingCorrection.caseId !== caseId
      || state.pendingCorrection.workflowRevision !== workflowRevision
      || state.pendingCorrection.fingerprint !== fingerprint) {
      state.pendingCorrection = {
        caseId,
        workflowRevision,
        fingerprint,
        requestId: newRequestId(),
      };
    }
    setButtonLoading(button, true, 'Saving');
    try {
      await submitUpdate(updates, {
        caseId,
        workflowRevision,
        requestId: state.pendingCorrection.requestId,
      });
      state.pendingCorrection = null;
      caseCorrectionProtection?.markClean();
      $('caseCorrectionPanel').classList.add('hidden');
    } catch (error) {
      setStatus(`${error.message} Retry will safely check the same correction.`, 'error');
    } finally {
      setButtonLoading(button, false);
    }
  }

  async function updateStageOnce(control, field, value) {
    if (!state.detail || !field || !field.editable || control.disabled || !value) return;
    const caseId = state.detail.summary.case_id;
    const workflowRevision = Number(state.detail.summary.workflow_revision || 1);
    if (!state.pendingStageUpdate
      || state.pendingStageUpdate.caseId !== caseId
      || state.pendingStageUpdate.fieldKey !== field.key
      || state.pendingStageUpdate.value !== value
      || state.pendingStageUpdate.workflowRevision !== workflowRevision) {
      state.pendingStageUpdate = {
        caseId,
        fieldKey: field.key,
        value,
        workflowRevision,
        requestId: newRequestId(),
      };
    }
    const pending = state.pendingStageUpdate;
    const isButton = control.tagName === 'BUTTON';
    try {
      if (isButton) setButtonLoading(control, true, 'Stamping');
      else control.disabled = true;
      await submitUpdate([{ field: field.key, value }], {
        caseId: pending.caseId,
        workflowRevision: pending.workflowRevision,
        requestId: pending.requestId,
      });
      state.pendingStageUpdate = null;
      await loadTaskInbox();
      refresh({ background: true }).catch(() => {});
      setStatus(value === 'STAMP' ? `${field.label} stamped.` : `${field.label} recorded.`, 'ok');
    } catch (error) {
      if (!isButton) control.value = field.value || '';
      setStatus(`${error.message} Retry will safely check the same update.`, 'error');
    } finally {
      if (isButton) setButtonLoading(control, false);
      else control.disabled = false;
    }
  }

  async function submitUpdate(updates, options) {
    if (!state.detail) return;
    const settings = options || {};
    setStatus('Saving update...', 'busy');
    const result = await api('/api/tat-tracker/update/', {
      case_id: settings.caseId || state.detail.summary.case_id,
      workflow_revision: settings.workflowRevision || Number(state.detail.summary.workflow_revision || 1),
      request_id: settings.requestId || newRequestId(),
      updates,
      product_requirement_evidence: collectProductConfiguration($('stageFields')).requirementEvidence,
      product_custom_values: collectProductConfiguration($('stageFields')).customValues,
    });
    state.detail = result.data;
    renderDetail(result.data);
    setStatus('Saved.', 'ok');
    return result.data;
  }

  async function saveDropdownStageUpdate(select, field) {
    const previousValue = field.value || '';
    if (!select.value || select.value === previousValue) return;
    select.disabled = true;
    try {
      await submitUpdate([{ field: field.key, value: select.value, correction: Boolean(field.value) }]);
    } catch (error) {
      select.value = previousValue;
      setStatus(error.message, 'error');
    } finally {
      select.disabled = false;
    }
  }

  document.querySelectorAll('.tabs button').forEach((button) => button.addEventListener('click', () => {
    show(button.dataset.view);
    if (button.dataset.view === 'settings') loadSettings().catch((error) => setStatus(error.message, 'error'));
  }));
  $('refreshBtn').addEventListener('click', async () => {
    if (state.refreshing) return;
    state.refreshing = true;
    try {
      const caseId = state.detail && state.detail.summary && state.detail.summary.case_id;
      if (state.currentView === 'detail' && caseId) await openCase(caseId);
      else await refresh();
    } catch (error) {
      // The invoked loader already presents a safe, contextual error.
    } finally {
      state.refreshing = false;
    }
  });
  $('backBtn').addEventListener('click', returnToQueue);
  document.querySelectorAll('[data-home-queue]').forEach((button) => button.addEventListener('click', () => {
    selectHomeQueue(button.dataset.homeQueue).catch((error) => setStatus(error.message, 'error'));
  }));
  $('queuePreviousBtn').addEventListener('click', () => changeHomePage(-1).catch((error) => setStatus(error.message, 'error')));
  $('queueNextBtn').addEventListener('click', () => changeHomePage(1).catch((error) => setStatus(error.message, 'error')));
  $('openQueueFiltersBtn').addEventListener('click', (event) => openQueueFilters(event.currentTarget));
  $('closeQueueFiltersBtn').addEventListener('click', () => closeQueueFilters());
  $('queueFilterOverlay').addEventListener('click', (event) => {
    if (event.target === event.currentTarget) closeQueueFilters();
  });
  $('queueFilterSheet').addEventListener('keydown', trapFilterSheetFocus);
  $('queueFilterForm').addEventListener('submit', (event) => {
    event.preventDefault();
    applyQueueFilters().catch((error) => setStatus(error.message, 'error'));
  });
  $('resetQueueFiltersBtn').addEventListener('click', () => {
    ['queueProductFilters', 'queueBranchFilters', 'queueStatusFilters'].forEach((id) => setCheckedFilterValues(id, []));
    applyQueueFilters().catch((error) => setStatus(error.message, 'error'));
  });
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
  $('correctCaseDetailsBtn').addEventListener('click', () => {
    $('caseCorrectionPanel').classList.remove('hidden');
    $('caseCorrectionForm').elements.client_name?.focus();
  });
  $('cancelCaseCorrectionBtn').addEventListener('click', () => {
    $('caseCorrectionPanel').classList.add('hidden');
    applyPendingHome();
    applyPendingDetail();
  });
  $('caseCorrectionForm').addEventListener('submit', submitCaseCorrection);
  const caseCorrectionProtection = utils.bindFormCloseProtection?.($('caseCorrectionForm'), 'tat-case-correction');
  const targetSettingsProtection = utils.bindFormCloseProtection?.($('targetSettingsForm'), 'tat-target-settings');
  const holidaySettingsProtection = utils.bindFormCloseProtection?.($('holidaySettingsForm'), 'tat-holiday-settings');
  const escalationSettingsProtection = utils.bindFormCloseProtection?.($('escalationSettingsForm'), 'tat-escalation-settings');
  const newCaseProtection = utils.bindFormCloseProtection?.($('newCaseForm'), 'tat-new-case');
  const personalSettingsProtection = utils.bindFormCloseProtection?.($('personalSettingsForm'), 'tat-personal-settings');
  $('targetSettingsForm').addEventListener('submit', async (event) => {
    event.preventDefault();
    if (state.savingTargets) return;
    try {
      state.savingTargets = true;
      setButtonLoading($('saveTargetSettingsBtn'), true, 'Saving');
      setStatus('Saving TAT targets...', 'busy');
      await saveTargetSettings();
      targetSettingsProtection?.markClean();
    } catch (error) {
      setStatus(error.message, 'error');
    } finally {
      state.savingTargets = false;
      setButtonLoading($('saveTargetSettingsBtn'), false);
    }
  });
  $('addHolidaySettingBtn').addEventListener('click', () => {
    const list = $('holidaySettingsList');
    list.querySelector('.settings-empty-copy')?.remove();
    appendHolidaySetting(list, null);
  });
  $('holidaySettingsForm').addEventListener('submit', async (event) => {
    event.preventDefault();
    const button = $('saveHolidaySettingsBtn');
    try {
      setButtonLoading(button, true, 'Saving');
      await saveConfigurationSettings('business_calendar', holidaySettingsPayload(), $('holidaySettingsReason').value.trim());
      $('holidaySettingsReason').value = '';
      holidaySettingsProtection?.markClean();
    } catch (error) {
      setStatus(error.message, 'error');
    } finally {
      setButtonLoading(button, false);
    }
  });
  $('addEscalationSettingBtn').addEventListener('click', () => appendEscalationSetting($('escalationSettingsList'), null));
  $('escalationSettingsForm').addEventListener('submit', async (event) => {
    event.preventDefault();
    const button = $('saveEscalationSettingsBtn');
    try {
      setButtonLoading(button, true, 'Saving');
      await saveConfigurationSettings('tat_escalation', escalationSettingsPayload(), $('escalationSettingsReason').value.trim());
      $('escalationSettingsReason').value = '';
      escalationSettingsProtection?.markClean();
    } catch (error) {
      setStatus(error.message, 'error');
    } finally {
      setButtonLoading(button, false);
    }
  });

  $('closeNoticeBtn').addEventListener('click', closeNotice);
  $('connectPrivateAlertsBtn').addEventListener('click', async (event) => {
    const button = event.currentTarget;
    const disconnecting = button.dataset.connected === 'true';
    let connection = null;
    try {
      setButtonLoading(button, true, disconnecting ? 'Disconnecting' : 'Connecting');
      if (!disconnecting && tg && typeof tg.requestWriteAccess === 'function') {
        await new Promise((resolve) => tg.requestWriteAccess(() => resolve()));
      }
      const path = disconnecting
        ? '/api/tat-tracker/private-alerts/disconnect/'
        : '/api/tat-tracker/private-alerts/connect/';
      const result = await api(path, { request_id: newRequestId() });
      connection = result.data || {};
      setStatus(
        disconnecting ? 'Private Telegram alerts disconnected. In-app tasks remain available.' : 'Private TAT alerts connected.',
        'ok',
      );
    } catch (error) {
      setStatus(error.message, 'error');
    } finally {
      setButtonLoading(button, false);
      if (connection) renderPrivateAlertConnection(connection);
    }
  });
  configureClipboardFields();

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
      const productConfiguration = collectProductConfiguration($('newCaseProductConfiguration'));
      payload.product_requirement_evidence = productConfiguration.requirementEvidence;
      payload.product_custom_values = productConfiguration.customValues;
      payload.product_selected_fee_keys = productConfiguration.selectedFeeKeys;
      payload.creation_intent = 'new_loan';
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
      newCaseProtection?.markClean();
      renderNewCaseProductConfiguration();
      renderExistingLoanContext(null);
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
  $('personalSettingsForm').addEventListener('submit', async (event) => {
    event.preventDefault();
    const button = $('savePersonalSettingsBtn');
    try {
      setButtonLoading(button, true, 'Saving');
      const preferences = {
        default_screen: $('preferenceDefaultScreen').value,
        compact_cards: $('preferenceCompactCards').checked,
      };
      if (state.businessTimeEnabled) {
        preferences.show_business_hours_time = $('preferenceBusinessHours').checked;
      }
      const result = await api('/api/tat-tracker/settings/personal/', {
        preferences,
      });
      applyPersonalPreference(result.data || {
        compact_cards: $('preferenceCompactCards').checked,
        default_screen: $('preferenceDefaultScreen').value,
        show_business_hours_time: $('preferenceBusinessHours').checked,
      });
      personalSettingsProtection?.markClean();
      setStatus($('preferenceCompactCards').checked
        ? 'Compact cards saved. Queue cards now hide identifiers and timestamps; open a case for full detail.'
        : 'Standard case cards restored.', 'ok');
    } catch (error) {
      setStatus(error.message, 'error');
    } finally {
      setButtonLoading(button, false);
    }
  });

  $('preferenceCompactCards').addEventListener('change', () => {
    const enabled = $('preferenceCompactCards').checked;
    document.body.classList.toggle('compact-cards', enabled);
    setStatus(enabled
      ? 'Compact queue preview on. Save my settings to keep it.'
      : 'Standard queue preview on. Save my settings to keep it.', 'ok');
  });

  $('preferenceBusinessHours').addEventListener('change', () => {
    const enabled = $('preferenceBusinessHours').checked;
    state.personalPreference.show_business_hours_time = enabled;
    document.body.classList.toggle('hide-business-hours-time', !enabled);
    if (state.detail) renderDetail(state.detail);
    setStatus(`${enabled ? 'Business-hours comparison shown' : 'Business-hours comparison hidden'}. Save my settings to keep it.`, 'ok');
  });

  ['national_id', 'primary_phone'].forEach((fieldName) => {
    const input = $('newCaseForm')?.elements[fieldName];
    input?.addEventListener('input', scheduleExistingLoanContext);
    input?.addEventListener('blur', scheduleExistingLoanContext);
  });

  async function startApp() {
    if (state.taskToken) {
      const resolved = await api('/api/tat-tracker/tasks/resolve/', { task_token: state.taskToken });
      state.groupId = resolved.data.group_id;
      state.token = '';
      state.directTask = resolved.data;
      consumeTaskLaunchUrl();
      if (resolved.data.message) setStatus(resolved.data.message, resolved.data.link_status === 'current' ? 'ok' : 'error');
    }
    const result = await api('/api/tat-tracker/bootstrap/', {});
    bootstrap(result.data);
    if (state.directTask && state.directTask.case_id) {
      await openCase(state.directTask.case_id, state.directTask.stage_key);
    }
  }

  function startRuntimeTimers() {
    const runtime = window.MiniAppRuntime;
    if (runtime) {
      runtime.createVisibleInterval(function () {
        if (!state.data) return null;
        const requests = [refresh({ background: true, periodic: true }).catch(() => {})];
        if (state.currentView === 'detail') requests.push(refreshDetailBackground().catch(() => {}));
        return Promise.all(requests);
      }, 30000, { immediateOnResume: true });
      runtime.createVisibleInterval(function () {
        tickTatCounters();
        applyPendingHome();
        applyPendingDetail();
      }, 1000);
      runtime.createVisibleInterval(updateQueueFreshness, 10000);
      return;
    }
    window.setInterval(function () {
      if (document.visibilityState !== 'hidden' && state.data) {
        refresh({ background: true, periodic: true }).catch(() => {});
        if (state.currentView === 'detail') refreshDetailBackground().catch(() => {});
      }
    }, 30000);
    window.setInterval(function () {
      if (document.visibilityState !== 'hidden') {
        tickTatCounters();
        applyPendingHome();
        applyPendingDetail();
      }
    }, 1000);
    window.setInterval(updateQueueFreshness, 10000);
  }

  configureHtmx();
  bindCollapsingHeader();
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && state.filterSheetOpen) closeQueueFilters();
  });
  if (tg && tg.BackButton && typeof tg.BackButton.onClick === 'function') {
    tg.BackButton.onClick(() => {
      if (state.filterSheetOpen) return closeQueueFilters();
      if (state.currentView === 'detail') {
        returnToQueue();
      }
    });
  }
  startApp()
    .then(startRuntimeTimers)
    .catch((error) => setStatus(error.message, 'error'));
})();
