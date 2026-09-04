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
    personalPreference: {},
    report: {
      view: 'current', page: 1, pageSize: 25, sort: '-created_at', sequence: 0,
      abortController: null, gridApi: null, charts: {}, count: 0, loaded: false,
      display: (() => { try { return localStorage.getItem('tat-report-chart-display') === 'list' ? 'list' : 'carousel'; } catch (error) { return 'carousel'; } })(),
      activeSlide: 0, touchStart: null, insightPayloads: {},
      filterSheetOpen: false, filterSheetReturnFocus: null,
      defaultValues: {},
    },
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

  function kickUpdateDispatches(dispatchIds) {
    if (!Array.isArray(dispatchIds) || !dispatchIds.length || !window.fetch) return;
    const requestId = newRequestId();
    const payload = basePayload({ dispatch_ids: dispatchIds, request_id: requestId });
    window.fetch('/api/tat-tracker/update/process-dispatches/', {
      method: 'POST',
      keepalive: true,
      headers: {
        'Content-Type': 'application/json',
        'X-Request-ID': requestId,
        'Idempotency-Key': requestId,
      },
      body: JSON.stringify(payload),
    }).catch(() => {
      // This only accelerates durable work. The scheduled processor remains
      // responsible if the WebView closes or connectivity drops.
    });
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
    if (view !== 'dashboard' && state.report.filterSheetOpen) closeTatReportFilters({ restoreFocus: false });
    state.currentView = view;
    document.querySelectorAll('.view').forEach((node) => node.classList.remove('active'));
    document.querySelectorAll('.tabs button').forEach((node) => node.classList.toggle('active', node.dataset.view === view));
    const dashboard = view === 'dashboard';
    $('trackerTabs').hidden = dashboard;
    $('casesWorkspaceBtn').classList.toggle('active', !dashboard);
    $('casesWorkspaceBtn').setAttribute('aria-pressed', String(!dashboard));
    $('dashboardWorkspaceBtn').classList.toggle('active', dashboard);
    $('dashboardWorkspaceBtn').setAttribute('aria-pressed', String(dashboard));
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

  function renderCaseButton(item, position) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'case-card';
    const next = item.next_stage ? `<span class="next-chip">Next: ${escapeHtml(item.next_stage)}</span>` : '';
    button.innerHTML = `
      <div class="case-header">
        <div class="case-primary">
          <div class="case-title"><span class="case-number">#${Number(position || 0) + 1}</span><strong class="case-name">${escapeHtml(item.client_name || 'Unnamed client')}</strong></div>
          <div class="case-details">
            <span class="case-id-badge">${escapeHtml(item.case_id)}</span>
            <span class="case-meta-dot"></span>
            <span class="case-meta-text">${escapeHtml(item.product || '')}</span>
            <span class="case-meta-dot"></span>
            <span class="case-meta-text">${escapeHtml(item.branch || '')}</span>
          </div>
        </div>
        <div class="case-side"><span class="case-amount">KES ${escapeHtml(formatMoney(item.amount || ''))}</span><span class="status-chip ${statusClass(item.status)}">${escapeHtml(item.status || 'Active')}</span></div>
      </div>
      ${caseIdentifierMarkup(item)}
      <div class="case-tags">
        ${next}
        <span class="case-time">
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" width="10" height="10">
            <circle cx="12" cy="12" r="10"/>
            <polyline points="12 6 12 12 16 14"/>
          </svg>
          ${escapeHtml(formatTatDateTime(item.updated_at))}
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

  function renderList(id, items, emptyTitle, emptyDetail, startIndex) {
    const list = $(id);
    list.innerHTML = '';
    if (!items || !items.length) {
      list.appendChild(renderEmpty(emptyTitle, emptyDetail));
      return;
    }
    items.forEach((item, index) => list.appendChild(renderCaseButton(item, Number(startIndex || 0) + index)));
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

  function renderHomeQueueSelection(queue, loading) {
    const presentation = queuePresentation(queue);
    document.querySelectorAll('[data-home-queue]').forEach((button) => {
      const selected = button.dataset.homeQueue === queue;
      button.classList.toggle('active', selected);
      button.setAttribute('aria-pressed', selected ? 'true' : 'false');
      button.toggleAttribute('aria-busy', selected && Boolean(loading));
    });
    $('activeQueueHeading').textContent = presentation[0];
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
    Object.entries(values).forEach(([id, value]) => { if ($(id)) $(id).textContent = Number(value || 0); });
    renderHomeQueueSelection(state.homeQueue, false);
    const presentation = queuePresentation(state.homeQueue);
    const total = Number(state.home.pagination.total ?? state.home.items.length);
    $('activeQueueCount').textContent = `${total} ${total === 1 ? 'case' : 'cases'}`;
    renderList('queueList', state.home.items, presentation[1], presentation[2], Number(state.home.pagination.offset || 0));
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
    const operationalWriteInFlight = state.creatingCase || state.pendingStageUpdate || state.pendingCorrection || correctionOpen;
    if (state.currentView === 'queue') {
      // Queue responses only replace metrics, tabs, filters and queue cards.
      // Hidden Create/Settings drafts must not freeze explicit queue changes.
      return !state.filterSheetOpen && !operationalWriteInFlight;
    }
    return !state.filterSheetOpen
      && !state.creatingCase
      && !state.pendingStageUpdate
      && !state.pendingCorrection
      && !correctionOpen
      && !newCaseProtection?.isDirty?.()
      && !personalSettingsProtection?.isDirty?.()
      && !targetSettingsProtection?.isDirty?.()
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
    return Object.assign({ page_size: 10 }, currentHomeFilters(), extra || {});
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
    state.pendingHome = null;
    state.homeQueue = queue;
    state.homePages[queue] = state.homePages[queue] || 1;
    renderHomeQueueSelection(queue, true);
    window.scrollTo(0, 0);
    try {
      await refresh({ requestedQueue: queue, forceHomeRender: true });
    } finally {
      renderHomeQueueSelection(state.homeQueue, false);
    }
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
    if (utils.renderSettingsAccount) utils.renderSettingsAccount($('tatSettingsAccount'), result.data.account || {});
    if ($('tatSettingsRelease')) $('tatSettingsRelease').textContent = result.data.account?.app_release || 'Current release';
    const workflowMode = result.data.workflow_mode || state.workflowMode || {};
    if ($('tatSettingsDataMode')) {
      $('tatSettingsDataMode').textContent = workflowMode.is_pilot ? 'Pilot (test records)' : 'Production';
    }
    const dispatchAttention = $('tatDispatchAttention');
    if (dispatchAttention) {
      const attentionCount = Number(result.data.dispatch_attention_count || 0);
      dispatchAttention.textContent = attentionCount === 1
        ? '1 background update needs administrator attention.'
        : `${attentionCount} background updates need administrator attention.`;
      dispatchAttention.classList.toggle('hidden', attentionCount < 1);
    }
    $('preferenceDefaultScreen').value = personal.default_screen || 'home';
    $('preferenceCompactCards').checked = Boolean(personal.compact_cards);
    const targetCard = (configuration.cards || {}).tat_targets || {};
    $('targetSettingsForm').classList.toggle('hidden', !targetCard.can_propose);
    if (targetCard.can_propose) renderTargetSettings(configuration.targets || []);
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
    const savedFilters = personal.default_filters || {};
    setCheckedFilterValues('queueProductFilters', savedFilters.product_keys || savedFilters.product_key || []);
    setCheckedFilterValues('queueBranchFilters', savedFilters.branches || savedFilters.branch || []);
    setCheckedFilterValues('queueStatusFilters', savedFilters.statuses || savedFilters.status || []);
    const canCreate = (((state.data || {}).user || {}).capabilities || []).includes('tat.case.create');
    return personal.default_screen === 'new' && canCreate ? 'new' : 'queue';
  }

  function bootstrap(data) {
    state.data = data;
    state.workflowMode = data.workflow_mode || null;
    if (!data.authorized) throw new Error(data.reason || 'Unauthorized.');
    $('loadingBrand').classList.add('hidden');
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
    const controls = `${requirementRows}${attributeRows}${feeRows}`;
    container.innerHTML = controls ? `<h3>${escapeHtml(product.label)} details</h3>${controls}` : '';
    container.hidden = !controls;
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
    const requestedQueue = ['assigned', 'role', 'all'].includes(options && options.requestedQueue)
      ? options.requestedQueue
      : state.homeQueue;
    const forceHomeRender = Boolean(options && options.forceHomeRender);
    if (periodic && state.homeRequestsInFlight > 0) return null;
    const requestNumber = (state.homeRequestNumber || 0) + 1;
    state.homeRequestNumber = requestNumber;
    state.homeRequestsInFlight += 1;
    if (!background) setStatus('Refreshing queue...', 'busy');
    try {
      const result = await api('/api/tat-tracker/home/', homePayload({
        queue: requestedQueue,
        page: state.homePages[requestedQueue] || 1,
      }));
      const nextHome = result && result.data;
      if (!nextHome || typeof nextHome !== 'object') {
        throw new Error('Queue refresh returned an invalid response. Tap Refresh to retry.');
      }
      if (String(nextHome.queue || '') !== requestedQueue) {
        throw new Error('The requested queue could not be loaded. Tap the queue again to retry.');
      }
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
      if (forceHomeRender || queueRenderIsSafe()) {
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
        </div>
        <div class="fact fact-activity">
          <small>Activity</small>
          <div class="activity-times">
            <div><small>Created</small><span>${escapeHtml(formatTatDateTime(summary.created_at))}</span></div>
            <div><small>Updated</small><span>${escapeHtml(formatTatDateTime(summary.updated_at))}</span></div>
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
      const targetText = formatMinutes(field.target_minutes);
      const slaText = slaLabel(field.sla_status);
      const hasTat = Number.isFinite(Number(field.elapsed_seconds)) || Boolean(formatMinutes(field.wall_clock_minutes || field.tat_minutes));
      const tatMeta = hasTat ? `
        <div class="stage-tat-row">
          <span class="tat-badge ${escapeHtml(field.sla_status || '')}">${tatCounterMarkup(field, `stage:${summary.case_id}:${field.key}`)}</span>
          ${targetText ? `<span class="tat-target">Target ${escapeHtml(targetText)}</span>` : ''}
          ${slaText ? `<span class="tat-target live-tat-sla-label">${escapeHtml(slaText)}</span>` : ''}
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

    // The server projection omits only duplicate technical transition receipts.
    const events = $('eventList');
    if (!events) return;
    events.innerHTML = '';
    const timelineEvents = detail.timeline || detail.events || [];
    if ($('activityCount')) $('activityCount').textContent = String(timelineEvents.length);
    if (!timelineEvents.length) {
      events.appendChild(renderEmpty('No audit events yet', 'Updates will appear here after the case starts moving.'));
    } else {
      timelineEvents.forEach((event) => {
        const eventTitle = event.stage || event.title || 'Case event';
        const eventValue = event.detail || event.value || '';
        const eventActor = [event.actor, event.authority && `Authority: ${event.authority}`].filter(Boolean).join(' · ');
        const eventAt = formatTatDateTime(event.occurred_at || event.at);
        const row = document.createElement('div');
        row.className = 'event-item';
        row.innerHTML = `
          <div class="event-dot"></div>
          <div class="event-body">
            <div class="event-header">
              <strong class="event-stage">${escapeHtml(eventTitle)}</strong>
            </div>
            ${eventValue ? `<div class="event-detail">${escapeHtml(eventValue)}</div>` : ''}
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
    actionWrap.classList.add('correction-open');
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
      utils.haptic?.('light');
      if (isButton) setButtonLoading(control, true, 'Stamping');
      else control.disabled = true;
      await submitUpdate([{ field: field.key, value }], {
        caseId: pending.caseId,
        workflowRevision: pending.workflowRevision,
        requestId: pending.requestId,
      });
      state.pendingStageUpdate = null;
      loadTaskInbox().catch(() => {});
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
    kickUpdateDispatches(result.dispatch_ids || []);
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

  function setDefaultReportDates() {
    const form = $('tatReportFilters');
    const end = new Date(); const start = new Date(end); start.setDate(start.getDate() - 29);
    const localIso = value => `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, '0')}-${String(value.getDate()).padStart(2, '0')}`;
    form.elements.date_from.value = localIso(start); form.elements.date_to.value = localIso(end);
    state.report.defaultValues.date_from = form.elements.date_from.value;
    state.report.defaultValues.date_to = form.elements.date_to.value;
    syncReportDateDisplays();
  }

  function reportPayload(extra) {
    const form = $('tatReportFilters');
    const values = Object.fromEntries(new FormData(form).entries());
    return basePayload(Object.assign(values, {
      view: state.report.view, page: state.report.page, page_size: state.report.pageSize,
      sort: state.report.sort,
    }, extra || {}));
  }

  async function reportFetch(path, payload, signal) {
    const requestId = newRequestId();
    payload.client_request_id = requestId;
    const response = await fetch(path, {
      method: 'POST', signal,
      headers: { 'Content-Type': 'application/json', 'X-Request-ID': requestId, 'Idempotency-Key': requestId, 'X-MiniApp-Message-Contract': '2' },
      body: JSON.stringify(payload),
    });
    const raw = await response.json().catch(() => ({}));
    const data = utils.normalizeResponsePayload ? utils.normalizeResponsePayload(response, raw) : raw;
    if (!response.ok || !data.ok) throw new Error(data.error || data.message || 'The TAT report could not be loaded.');
    return data.data;
  }

  function formatReportDate(value) {
    if (!value) return '';
    const text = String(value).trim();
    const dateOnly = text.match(/^(\d{4})-(\d{2})-(\d{2})/);
    if (dateOnly) return `${dateOnly[3]}-${dateOnly[2]}-${dateOnly[1].slice(-2)}`;
    const numeric = text.match(/^(\d{1,2})[-/](\d{1,2})[-/](\d{2}|\d{4})/);
    if (numeric) return `${numeric[1].padStart(2, '0')}-${numeric[2].padStart(2, '0')}-${numeric[3].slice(-2)}`;
    const named = text.match(/^(\d{1,2})-([A-Za-z]{3,9})-(\d{4})/);
    if (named) {
      const month = ['jan','feb','mar','apr','may','jun','jul','aug','sep','oct','nov','dec'].indexOf(named[2].slice(0, 3).toLowerCase()) + 1;
      if (month) return `${named[1].padStart(2, '0')}-${String(month).padStart(2, '0')}-${named[3].slice(-2)}`;
    }
    const date = new Date(text);
    if (Number.isNaN(date.getTime())) return String(value);
    const pad = number => String(number).padStart(2, '0');
    return `${pad(date.getDate())}-${pad(date.getMonth() + 1)}-${String(date.getFullYear()).slice(-2)}`;
  }

  function formatTatDateTime(value) {
    if (!value) return '';
    const date = formatReportDate(value);
    const time = String(value).match(/(?:T|\s)(\d{1,2}):(\d{2})/);
    return `${date}${time ? ` ${time[1].padStart(2, '0')}:${time[2]}` : ''}`;
  }

  function syncReportDateDisplays() {
    const form = $('tatReportFilters');
    if (!form) return;
    ['date_from', 'date_to'].forEach(name => {
      const display = form.querySelector(`[data-date-display="${name}"]`);
      if (display) display.textContent = formatReportDate(form.elements[name].value) || 'dd-mm-yy';
    });
  }

  const reportControlDefaults = {
    search: '', group: '', branch: '', product: '', stage: '', role: '', status: '', sla_state: '',
    granularity: 'month', chart_dimension: 'stage', chart_metric: 'workload',
    heatmap_pair: 'stage_branch', heatmap_metric: 'sla_met',
  };

  function reportFilterIsActive(key) {
    const control = $('tatReportFilters')?.elements?.[key];
    if (!control) return false;
    const expected = Object.prototype.hasOwnProperty.call(state.report.defaultValues, key)
      ? state.report.defaultValues[key]
      : (reportControlDefaults[key] || '');
    return String(control.value || '') !== String(expected);
  }

  function activeReportFilterKeys() {
    return [...document.querySelectorAll('#tatReportFilters [data-report-filter]')]
      .map(label => label.dataset.reportFilter)
      .filter(reportFilterIsActive);
  }

  function currentReportInsight() {
    const slides = visibleTatChartSlides();
    const panel = slides[state.report.activeSlide] || slides[0];
    const key = panel?.dataset.reportKey || '';
    return {
      key,
      panel,
      title: panel?.querySelector('h3')?.textContent?.trim() || 'Focused insight',
      payload: state.report.insightPayloads[key] || {},
    };
  }

  function setReportGuidanceDescription(label, text) {
    let description = label.querySelector('.report-filter-guidance-description');
    if (!description) {
      description = document.createElement('span');
      description.className = 'sr-only report-filter-guidance-description';
      description.id = `report-filter-guidance-${label.dataset.reportFilter}`;
      label.append(description);
      const control = label.querySelector('input, select');
      if (control) control.setAttribute('aria-describedby', description.id);
    }
    description.textContent = text;
  }

  function syncReportFilterGuidance() {
    const insight = currentReportInsight();
    const guidance = insight.payload.filter_guidance || {};
    const applicable = new Set(guidance.applicable_filters || []);
    const configuring = new Set(guidance.chart_controls || []);
    const changing = new Set(guidance.basis_changing_filters || []);
    const unavailable = new Map((guidance.unavailable_filters || []).map(item => [item.key, item.reason]));
    const notes = guidance.filter_notes || {};
    const active = activeReportFilterKeys();
    const mismatches = active.filter(key => unavailable.has(key));

    document.querySelectorAll('#tatReportFilters [data-report-filter]').forEach(label => {
      const key = label.dataset.reportFilter;
      label.removeAttribute('data-guidance');
      label.removeAttribute('data-guidance-symbol');
      label.removeAttribute('title');
      let description = '';
      if (changing.has(key)) {
        description = notes[key] || 'Changes what this insight represents.';
        label.dataset.guidance = 'changes'; label.dataset.guidanceSymbol = '⇄';
      } else if (configuring.has(key)) {
        description = notes[key] || 'Configures this insight.';
        label.dataset.guidance = 'configures'; label.dataset.guidanceSymbol = '⚙';
      } else if (applicable.has(key)) {
        description = notes[key] || 'Affects this insight.';
        label.dataset.guidance = 'affects'; label.dataset.guidanceSymbol = '✓';
      } else if (unavailable.has(key)) {
        description = unavailable.get(key);
        if (reportFilterIsActive(key)) {
          label.dataset.guidance = 'unavailable'; label.dataset.guidanceSymbol = '!';
        }
      }
      if (description) label.title = description;
      setReportGuidanceDescription(label, description || 'This control does not affect the focused insight.');
      let visibleNote = label.querySelector('.report-filter-guidance-note');
      if (!visibleNote) {
        visibleNote = document.createElement('small');
        visibleNote.className = 'report-filter-guidance-note';
        label.append(visibleNote);
      }
      const showNote = reportFilterIsActive(key) && (changing.has(key) || unavailable.has(key));
      visibleNote.hidden = !showNote;
      visibleNote.textContent = showNote ? description : '';
    });

    $('tatReportFocusedInsight').textContent = insight.title;
    const form = $('tatReportFilters');
    $('tatReportDateSummary').textContent = `${formatReportDate(form.elements.date_from.value)} – ${formatReportDate(form.elements.date_to.value)}`;
    const count = active.length;
    const badge = $('tatReportActiveFilterCount');
    badge.textContent = String(count); badge.hidden = count === 0;
    const warning = $('tatReportFilterWarning');
    warning.hidden = mismatches.length === 0;
    if (mismatches.length) {
      warning.textContent = `${mismatches.length} active ${mismatches.length === 1 ? 'filter does' : 'filters do'} not affect ${insight.title}. Tap to review.`;
    }
    $('tatReportFilterTitle').textContent = `Filters for ${insight.title}`;
    $('tatReportFilterHelp').textContent = 'Highlighted controls affect or configure this insight. Other controls remain available for the table and other insights.';
  }

  function reportFilterSheetElements() {
    return Array.from($('tatReportFilterSheet').querySelectorAll('button:not([disabled]), select:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex="-1"])'));
  }

  function openTatReportFilters(trigger) {
    state.report.filterSheetOpen = true;
    state.report.filterSheetReturnFocus = trigger || document.activeElement;
    syncReportFilterGuidance();
    $('tatReportFilterOverlay').hidden = false;
    $('tatReportFilterOverlay').setAttribute('aria-hidden', 'false');
    document.body.classList.add('tat-sheet-open');
    $('tatReportFilterSheet').focus();
    if (trigger?.id === 'tatReportFilterWarning') {
      window.requestAnimationFrame(() => {
        $('tatReportFilters').querySelector('[data-guidance="unavailable"]')?.scrollIntoView?.({ block: 'center' });
      });
    }
    tg?.BackButton?.show?.();
    utils.haptic?.('light');
  }

  function closeTatReportFilters(options) {
    if (!state.report.filterSheetOpen) return;
    state.report.filterSheetOpen = false;
    $('tatReportFilterOverlay').hidden = true;
    $('tatReportFilterOverlay').setAttribute('aria-hidden', 'true');
    document.body.classList.remove('tat-sheet-open');
    if (state.currentView !== 'detail') tg?.BackButton?.hide?.();
    if (!(options && options.restoreFocus === false)) state.report.filterSheetReturnFocus?.focus?.();
    state.report.filterSheetReturnFocus = null;
  }

  function trapReportFilterSheetFocus(event) {
    if (event.key !== 'Tab') return;
    const focusable = reportFilterSheetElements();
    if (!focusable.length) return event.preventDefault();
    const first = focusable[0]; const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  }

  function formatMinutes(value) {
    if (value == null || value === '') return '—';
    const minutes = Number(value);
    if (!Number.isFinite(minutes)) return '—';
    if (minutes < 60) return `${Math.round(minutes)}m`;
    if (minutes < 1440) return `${(minutes / 60).toFixed(1)}h`;
    return `${(minutes / 1440).toFixed(1)}d`;
  }

  function initTatReportGrid() {
    if (state.report.gridApi || !window.agGrid) return;
    window.agGrid.ModuleRegistry.registerModules([window.agGrid.AllCommunityModule]);
    const touch = window.matchMedia('(pointer: coarse)').matches;
    const columns = [
      {
        headerName: '#', colId: 'row_number', pinned: 'left', lockPinned: true,
        width: 48, minWidth: 48, maxWidth: 48, sortable: false, resizable: false,
        suppressMovable: true,
        valueGetter: params => ((state.report.page - 1) * state.report.pageSize) + Number(params.node.rowIndex || 0) + 1,
      },
      { headerName: 'Reference', field: 'case_id', width: 125 },
      { headerName: 'Customer', field: 'client_name', width: 180 },
      { headerName: 'TAT Group', field: 'group', width: 145 },
      { headerName: 'Branch', field: 'branch', width: 120 },
      { headerName: 'Product', field: 'product_label', width: 145 },
      { headerName: 'Status', field: 'status', width: 105 },
      { headerName: 'Stage', field: 'current_stage', width: 165 },
      { headerName: 'Role', field: 'responsible_role', width: 115 },
      { headerName: 'Created', field: 'created_at', width: 105, valueFormatter: p => formatReportDate(p.value) },
      { headerName: 'Finished', field: 'finished_at', width: 105, valueFormatter: p => formatReportDate(p.value) },
      { headerName: 'Elapsed', field: 'elapsed_minutes', width: 95, valueFormatter: p => formatMinutes(p.value) },
      { headerName: 'Target', field: 'target_minutes', width: 90, valueFormatter: p => formatMinutes(p.value) },
      { headerName: 'Variance', field: 'variance_minutes', width: 90, valueFormatter: p => formatMinutes(p.value) },
      { headerName: 'SLA', field: 'sla_state', width: 125, valueFormatter: p => String(p.value || '').replaceAll('_', ' '), cellClass: p => `sla-${p.value || ''}` },
    ];
    if ((((state.data || {}).user || {}).capabilities || []).includes('tat.reports.people.view')) columns.splice(9, 0, { headerName: 'Responsible Person', field: 'responsible_person', width: 160, sortable: false });
    state.report.gridApi = window.agGrid.createGrid($('tatReportGrid'), {
      theme: 'legacy', rowData: [], animateRows: false, suppressMovableColumns: touch,
      defaultColDef: { sortable: true, resizable: !touch, suppressMovable: touch },
      columnDefs: columns,
      overlayLoadingTemplate: '<span>Loading TAT report…</span>',
      overlayNoRowsTemplate: '<span>No cases match these filters.</span>',
      onSortChanged(event) {
        const selected = event.api.getColumnState().find(column => column.sort);
        if (!selected) return;
        state.report.sort = `${selected.sort === 'desc' ? '-' : ''}${selected.colId}`;
        state.report.page = 1;
        refreshTatReport({ summary: false });
      },
    });
  }

  function setReportSelect(name, options, valueKey, labelKey) {
    const select = $('tatReportFilters').elements[name];
    const selected = select.value;
    while (select.options.length > 1) select.remove(1);
    (options || []).forEach(item => {
      const option = document.createElement('option');
      option.value = typeof item === 'string' ? item : item[valueKey];
      option.textContent = typeof item === 'string' ? item : item[labelKey];
      select.append(option);
    });
    if ([...select.options].some(option => option.value === selected)) select.value = selected;
  }

  function renderReportMetrics(metrics, metricBasis) {
    const current = state.report.view === 'current';
    const items = current ? [
      ['active', 'Active', ''], ['near_target', 'Near Target', 'warn'], ['overdue', 'Overdue', 'bad'],
      ['stalled', 'Marked Stalled', 'bad'], ['target_unavailable', 'Target Unavailable', ''],
    ] : [
      ['created', metricBasis === 'completed_stage_actions' ? 'Cases' : 'Created', ''],
      ['finished', metricBasis === 'completed_stage_actions' ? 'Completed Actions' : 'Finished', ''], ['disbursed', 'Disbursed', 'good'],
      ['rejected', 'Rejected', 'bad'], ['declined', 'Declined', 'bad'],
      ['sla_met_percent', 'SLA Met %', 'good'],
      ['median_tat_minutes', metricBasis === 'completed_stage_actions' ? 'Median Stage Time' : 'Median TAT', ''],
      ['p90_tat_minutes', metricBasis === 'completed_stage_actions' ? 'P90 Stage Time' : 'P90 TAT', 'warn'],
    ];
    $('tatReportMetrics').innerHTML = items.map(([key, label, tone]) => {
      let value = metrics[key];
      if (key.endsWith('_minutes')) value = formatMinutes(value);
      else if (key === 'sla_met_percent') value = value == null ? '—' : `${value}%`;
      else value = Number(value || 0).toLocaleString();
      return `<div class="report-metric ${tone}"><strong>${escapeHtml(value)}</strong><span>${escapeHtml(label)}</span></div>`;
    }).join('');
  }

  function chartColors(count) {
    const palette = ['#3390ec', '#23a67a', '#ef9b36', '#8b6ee8', '#e45858', '#29a4b8', '#6a7a89'];
    return Array.from({ length: count }, (_, index) => palette[index % palette.length]);
  }

  function renderExplorerDetails(payload) {
    const target = $('tatExplorerDetails');
    if (!target) return;
    const details = [];
    if (payload.metric === 'duration') {
      Object.entries(payload.iqr_minutes || {}).forEach(([label, range]) => {
        details.push(`<div><strong>${escapeHtml(label)}:</strong> middle 50% ${escapeHtml(formatMinutes(range.q1))} to ${escapeHtml(formatMinutes(range.q3))}</div>`);
      });
    }
    if (payload.metric === 'load_per_assignee') {
      Object.entries(payload.assignee_counts || {}).forEach(([label, count]) => {
        details.push(`<div><strong>${escapeHtml(label)}:</strong> ${Number(count).toLocaleString()} configured assignee${Number(count) === 1 ? '' : 's'}</div>`);
      });
      if (payload.unassigned_case_count) details.push(`<div class="warning">${Number(payload.unassigned_case_count).toLocaleString()} cases have no matching configured assignee.</div>`);
    }
    target.innerHTML = details.join('');
  }

  function formatHeatmapValue(value, metric) {
    if (value == null) return 'No data';
    if (metric === 'duration') return formatMinutes(value);
    if (metric === 'sla_met' || metric === 'target_usage') return `${Number(value).toLocaleString(undefined, { maximumFractionDigits: 1 })}%`;
    return Number(value).toLocaleString();
  }

  function renderTatHeatmap(payload) {
    const panel = $('tatHeatmapPanel');
    const target = $('tatHeatmap');
    if (!panel || !target) return;
    panel.hidden = !payload.id;
    if (!payload.id) return;
    $('tatHeatmapTitle').textContent = payload.title || 'Operational Heatmap';
    const notes = [payload.subtitle || ''];
    if (payload.excluded_count) notes.push(`${Number(payload.excluded_count).toLocaleString()} excluded: ${payload.exclusion_reason || 'not eligible'}.`);
    $('tatHeatmapBasis').textContent = notes.filter(Boolean).join(' ');
    const rows = payload.rows || []; const columns = payload.columns || []; const cells = payload.cells || [];
    if (!rows.length || !columns.length) {
      target.innerHTML = '<p class="chart-empty-static">No heatmap data matches these filters.</p>';
      return;
    }
    const lookup = new Map(cells.map(cell => [`${cell.row}\u0000${cell.column}`, cell]));
    const values = cells.map(cell => Number(cell.value)).filter(Number.isFinite);
    const minimum = values.length ? Math.min(...values) : 0; const maximum = values.length ? Math.max(...values) : 0;
    const body = rows.map((row, rowIndex) => `<tr><th scope="row">${escapeHtml(row)}</th>${columns.map((column, columnIndex) => {
      const cell = lookup.get(`${row}\u0000${column}`) || { value: null, sample_count: 0, excluded_count: 0 };
      const value = Number(cell.value); const intensity = Number.isFinite(value) && maximum > minimum ? Math.round(((value - minimum) / (maximum - minimum)) * 100) : (Number.isFinite(value) ? 55 : 0);
      const shown = formatHeatmapValue(cell.value, payload.metric);
      const description = `${row}, ${column}: ${shown}; ${Number(cell.sample_count || 0)} samples; ${Number(cell.excluded_count || 0)} excluded`;
      return `<td><button type="button" data-heat-row="${rowIndex}" data-heat-column="${columnIndex}" style="--heat-intensity:${intensity}%" aria-label="${escapeHtml(description)}" title="${escapeHtml(description)}"><strong>${escapeHtml(shown)}</strong><small>n=${Number(cell.sample_count || 0)}</small></button></td>`;
    }).join('')}</tr>`).join('');
    target.innerHTML = `<table><caption class="sr-only">${escapeHtml(payload.title || 'Operational heatmap')}</caption><thead><tr><th scope="col">${escapeHtml((payload.row_dimension || 'Row').replaceAll('_', ' '))}</th>${columns.map(column => `<th scope="col">${escapeHtml(column)}</th>`).join('')}</tr></thead><tbody>${body}</tbody></table>`;
  }

  function renderTargetReviewSignals(payload) {
    const target = $('tatTargetSignals');
    if (!target) return;
    const signals = payload.items || [];
    const notes = [payload.subtitle || ''];
    if (payload.excluded_count) notes.push(`${Number(payload.excluded_count).toLocaleString()} excluded: ${payload.exclusion_reason || 'not eligible'}.`);
    $('tatSignalsBasis').textContent = notes.filter(Boolean).join(' ');
    if (!signals.length) {
      target.innerHTML = '<p class="chart-empty-static">No target performance data is available for this selection.</p>';
      return;
    }
    target.innerHTML = signals.map(signal => {
      const stats = signal.baseline || {}; const tone = signal.classification === 'review_recommended' ? 'bad' : (signal.classification === 'none' ? '' : 'warn');
      const raw = stats.over_percent == null ? 'No valid target samples' : `${stats.over_percent}% over target, n=${Number(stats.valid_samples || 0).toLocaleString()}, 95% lower bound ${stats.wilson_lower_bound}%`;
      const selected = signal.selected_scope || {};
      const selectedRaw = signal.classification === 'selected_scope_high' && selected.over_percent != null
        ? `<small>Selected scope: ${escapeHtml(selected.over_percent)}% over, n=${Number(selected.valid_samples || 0).toLocaleString()}</small>` : '';
      const heading = signal.group ? `${signal.stage} - ${signal.group}` : signal.stage;
      return `<section class="tat-signal ${tone}"><div><strong>${escapeHtml(heading)}</strong><span>${escapeHtml(raw)}</span></div>${selectedRaw}${signal.message ? `<p>${escapeHtml(signal.message)}</p>` : '<p>No review signal at the current evidence threshold.</p>'}</section>`;
    }).join('');
  }

  function renderOldestCases(payload) {
    const target = $('tatOldestCases');
    if (!target) return;
    const rows = payload.items || [];
    $('tatOldestBasis').textContent = payload.subtitle || '';
    if (!rows.length) {
      target.innerHTML = '<p class="chart-empty-static">No active cases match these filters.</p>';
      return;
    }
    target.innerHTML = rows.map((row, index) => `<button type="button" class="tat-oldest-case" data-oldest-case="${escapeHtml(row.case_id)}"><span class="tat-oldest-rank">${index + 1}</span><span><strong>${escapeHtml(row.case_id)}</strong><small>${escapeHtml(row.client_name || 'Customer not provided')} - ${escapeHtml(row.current_stage || 'Stage not set')}</small></span><span class="${row.sla_state === 'overdue' ? 'bad' : row.sla_state === 'near_target' ? 'warn' : 'good'}">${escapeHtml(formatMinutes(row.elapsed_minutes))}</span></button>`).join('');
  }

  function visibleTatChartSlides() {
    return [...document.querySelectorAll('#tatReportCharts [data-report-slide]')].filter(panel => !panel.hidden);
  }

  function syncTatChartDisplay() {
    const container = $('tatReportCharts');
    if (!container) return;
    const slides = visibleTatChartSlides();
    state.report.activeSlide = Math.max(0, Math.min(state.report.activeSlide, Math.max(0, slides.length - 1)));
    container.classList.toggle('carousel', state.report.display === 'carousel');
    container.classList.toggle('list', state.report.display === 'list');
    slides.forEach((panel, index) => {
      panel.classList.toggle('carousel-inactive', state.report.display === 'carousel' && index !== state.report.activeSlide);
      panel.classList.toggle('filter-focus', index === state.report.activeSlide);
    });
    document.querySelectorAll('[data-chart-display]').forEach(button => {
      const active = button.dataset.chartDisplay === state.report.display;
      button.classList.toggle('active', active); button.setAttribute('aria-pressed', String(active));
    });
    const paging = document.querySelector('.tat-chart-pagination');
    if (paging) paging.hidden = state.report.display !== 'carousel';
    $('tatChartPosition').textContent = slides.length ? `${state.report.activeSlide + 1} of ${slides.length}` : '0 of 0';
    $('tatChartPrevious').disabled = slides.length < 2 || state.report.activeSlide === 0;
    $('tatChartNext').disabled = slides.length < 2 || state.report.activeSlide === slides.length - 1;
    if (state.report.display === 'carousel') {
      const active = slides[state.report.activeSlide];
      const canvas = active?.querySelector('canvas');
      const chart = canvas && window.Chart?.getChart?.(canvas); chart?.resize?.();
    }
    syncReportFilterGuidance();
  }

  function setTatChartDisplay(display) {
    state.report.display = display === 'list' ? 'list' : 'carousel';
    state.report.activeSlide = 0;
    try { localStorage.setItem('tat-report-chart-display', state.report.display); } catch (error) {}
    syncTatChartDisplay(); utils.haptic?.('light');
  }

  function moveTatChart(direction) {
    if (state.report.display !== 'carousel') return;
    const slides = visibleTatChartSlides();
    const next = Math.max(0, Math.min(slides.length - 1, state.report.activeSlide + direction));
    if (next === state.report.activeSlide) return;
    state.report.activeSlide = next; syncTatChartDisplay(); utils.haptic?.('light');
  }

  function recordTatCarouselGesture(action) {
    window.MiniAppDiagnostics?.record?.('carousel_gesture', { action, statusBucket: 'ok' });
  }

  function renderTatReportCharts(summary) {
    Object.values(state.report.charts).forEach(chart => chart && chart.destroy());
    state.report.charts = {};
    const charts = summary.charts || {};
    state.report.insightPayloads = Object.assign({}, charts, {
      heatmap: summary.heatmap || {},
      target_review_signals: summary.target_review_signals || {},
      oldest_cases: summary.oldest_cases || {},
    });
    renderExplorerDetails(charts.explorer || {});
    renderTatHeatmap(summary.heatmap || {});
    renderTargetReviewSignals(summary.target_review_signals || {});
    renderOldestCases(summary.oldest_cases || {});
    if (!window.Chart) { syncTatChartDisplay(); return; }
    const text = getComputedStyle(document.body).getPropertyValue('--tat-text').trim() || '#222';
    const grid = getComputedStyle(document.body).getPropertyValue('--tat-line').trim() || '#ddd';
    const colors = ['#3390ec', '#23a67a', '#ef9b36', '#8b6ee8', '#e45858', '#29a4b8', '#6a7a89'];
    const definitions = {
      trend: ['tatTrend', 'line'], backlog_age: ['tatBacklog', 'bar'],
      sla_compliance: ['tatSla', 'line'], tat_percentiles: ['tatPercentiles', 'line'],
      stage_target: ['tatTarget', 'bar-horizontal'], explorer: ['tatExplorer', 'bar-horizontal'],
    };
    const currentOnly = new Set(['backlog_age']);
    const performanceOnly = new Set(['sla_compliance', 'tat_percentiles', 'stage_target']);
    Object.entries(definitions).forEach(([key, [prefix, kind]]) => {
      const panel = $(`${prefix}Panel`);
      const payload = charts[key];
      const allowed = !currentOnly.has(key) || state.report.view === 'current';
      const performanceAllowed = !performanceOnly.has(key) || state.report.view === 'performance';
      if (panel) panel.hidden = !payload || !allowed || !performanceAllowed;
      if (!payload || !allowed || !performanceAllowed) return;
      $(`${prefix}Title`).textContent = payload.title || '';
      const notes = [payload.subtitle || ''];
      if (payload.excluded_count) notes.push(`${Number(payload.excluded_count).toLocaleString()} excluded: ${payload.exclusion_reason || 'not eligible'}.`);
      if ((payload.unavailable_filters || []).length) notes.push(`Not applicable: ${payload.unavailable_filters.join(', ').replaceAll('_', ' ')}.`);
      $(`${prefix}Basis`).textContent = notes.filter(Boolean).join(' ');
      const empty = $(`${prefix}Empty`);
      const hasData = Boolean(payload.sample_count) && (payload.labels || []).length;
      empty.hidden = hasData;
      if (!hasData) {
        empty.textContent = payload.excluded_count
          ? `No eligible data. ${payload.excluded_count} excluded because ${payload.exclusion_reason || 'required data is unavailable'}.`
          : (key === 'stage_target'
            ? 'No target performance data is available for this selection.'
            : 'No chart data is available for this selection.');
        return;
      }
      const horizontal = kind === 'bar-horizontal';
      const line = kind === 'line';
      const dateLabels = line ? (payload.labels || []).map(formatReportDate) : (payload.labels || []);
      const options = {
        responsive: true, maintainAspectRatio: false, indexAxis: horizontal ? 'y' : 'x',
        interaction: { mode: 'index', intersect: false },
        plugins: { legend: { labels: { color: text, boxWidth: 10, font: { size: 9 } } } },
        scales: {
          x: { beginAtZero: !line || undefined, ticks: { color: text, maxRotation: 0, autoSkip: true, maxTicksLimit: 8, font: { size: 8 } }, grid: { color: grid } },
          y: { beginAtZero: true, ticks: { color: text, precision: 0, font: { size: 8 } }, grid: { color: grid } },
        },
      };
      if (key === 'tat_percentiles') options.scales.y.ticks.callback = value => formatMinutes(value);
      if (key === 'sla_compliance') { options.scales.y.max = 100; options.scales.y.title = { display: true, text: 'SLA met %', color: text }; }
      if (key === 'stage_target') options.scales.x.title = { display: true, text: payload.axis_title || '% of target', color: text };
      if (key === 'explorer' && payload.metric === 'duration') options.scales.x.ticks.callback = value => formatMinutes(value);
      if (key === 'explorer' && payload.metric === 'sla_state') { options.scales.x.stacked = true; options.scales.y.stacked = true; }
      if (key === 'explorer' && ['target_usage', 'sla_met', 'correction_rate'].includes(payload.metric)) {
        options.scales.x.title = { display: true, text: payload.axis_title || '%', color: text };
      }
      const semanticColors = { within_target: '#23a67a', near_target: '#ef9b36', overdue: '#e45858', target_unavailable: '#6a7a89' };
      const datasets = (payload.series || []).map((item, index) => ({
        label: item.label, data: item.values || [], borderColor: colors[index % colors.length],
        backgroundColor: semanticColors[item.key] || (horizontal && (payload.series || []).length === 1 ? chartColors((payload.labels || []).length) : colors[index % colors.length]),
        tension: .25, spanGaps: false,
      }));
      const plugins = [];
      if (['stage_target', 'explorer'].includes(key) && payload.reference_line != null) plugins.push({
        id: 'tatTargetReference',
        afterDraw(chart) {
          const x = chart.scales.x.getPixelForValue(payload.reference_line);
          if (!Number.isFinite(x)) return;
          const context = chart.ctx; context.save(); context.strokeStyle = '#e45858'; context.setLineDash([4, 3]);
          context.beginPath(); context.moveTo(x, chart.chartArea.top); context.lineTo(x, chart.chartArea.bottom); context.stroke(); context.restore();
        },
      });
      state.report.charts[key] = new Chart($(`${prefix}Chart`), { type: line ? 'line' : 'bar', data: { labels: dateLabels, datasets }, options, plugins });
    });
    const details = $('tatTargetDetails');
    if (details) {
      const rows = (charts.stage_target || {}).single_product_details || [];
      details.innerHTML = rows.length ? rows.map(item => {
        const target = item.target_days != null ? `${item.target_days}d target` : `${(item.target_versions_days || []).join('d / ')}d targets`;
        return `<div><strong>${escapeHtml(item.label)}:</strong> ${escapeHtml(item.median_days)}d median · ${escapeHtml(item.p90_days)}d P90 · ${escapeHtml(target)}</div>`;
      }).join('') : '';
    }
    syncTatChartDisplay();
  }

  function renderReportFreshness(freshness) {
    const parts = [];
    if (freshness.latest_snapshot) {
      parts.push(`History updated through ${formatReportDate(freshness.latest_snapshot)}.`);
      if (freshness.earliest_snapshot) parts.push(`Reliable workload history begins ${formatReportDate(freshness.earliest_snapshot)}.`);
    }
    else parts.push('Historical snapshots are not available yet.');
    if (freshness.pending_rebuilds) parts.push(`${freshness.pending_rebuilds} history rebuild${freshness.pending_rebuilds === 1 ? '' : 's'} pending.`);
    if (freshness.failed_rebuilds) parts.push(`${freshness.failed_rebuilds} history rebuild${freshness.failed_rebuilds === 1 ? '' : 's'} need${freshness.failed_rebuilds === 1 ? 's' : ''} administrator attention.`);
    parts.push(`Near Target starts at ${freshness.near_target_percent}%.`);
    $('tatReportFreshness').textContent = parts.join(' ');
    $('tatReportFreshness').classList.toggle('warning', !freshness.latest_snapshot || Boolean(freshness.pending_rebuilds) || Boolean(freshness.failed_rebuilds));
  }

  async function refreshTatReport(options) {
    const settings = Object.assign({ summary: true, table: true }, options || {});
    const sequence = ++state.report.sequence;
    state.report.abortController?.abort();
    const controller = new AbortController(); state.report.abortController = controller;
    initTatReportGrid();
    if (settings.table) state.report.gridApi?.showLoadingOverlay();
    try {
      const [summary, table] = await Promise.all([
        settings.summary ? reportFetch('/api/tat-tracker/reports/summary/', reportPayload(), controller.signal) : Promise.resolve(null),
        settings.table ? reportFetch('/api/tat-tracker/reports/cases/', reportPayload(), controller.signal) : Promise.resolve(null),
      ]);
      if (sequence !== state.report.sequence) return;
      if (summary) {
        renderReportMetrics(summary.metrics || {}, summary.metric_basis || ''); renderTatReportCharts(summary); renderReportFreshness(summary.freshness || {});
        setReportSelect('group', summary.filters?.groups || [], 0, 1);
        setReportSelect('branch', summary.filters?.branches || []);
        setReportSelect('product', summary.filters?.products || [], 0, 1);
        setReportSelect('stage', summary.filters?.stages || [], 0, 1);
        setReportSelect('role', summary.filters?.roles || []);
        syncReportFilterGuidance();
      }
      if (table) {
        state.report.count = Number(table.count || 0); state.report.gridApi?.setGridOption('rowData', table.results || []);
        if (table.results?.length) state.report.gridApi?.hideOverlay(); else state.report.gridApi?.showNoRowsOverlay();
        const pages = Math.max(1, Math.ceil(state.report.count / state.report.pageSize));
        $('tatReportPage').textContent = `Page ${state.report.page} of ${pages}`;
        $('tatReportPrevious').disabled = state.report.page <= 1; $('tatReportNext').disabled = state.report.page >= pages;
      }
      state.report.loaded = true;
    } catch (error) {
      if (error.name === 'AbortError' || sequence !== state.report.sequence) return;
      state.report.gridApi?.hideOverlay(); setStatus(error.message, 'error');
    } finally {
      if (state.report.abortController === controller) state.report.abortController = null;
    }
  }

  function setTatReportView(view) {
    state.report.view = view; state.report.page = 1;
    document.querySelectorAll('[data-report-view]').forEach(button => { const active = button.dataset.reportView === view; button.classList.toggle('active', active); button.setAttribute('aria-pressed', String(active)); });
    $('tatTrendTitle').textContent = view === 'current' ? 'Workload over Time' : 'Created, Finished and Disbursed';
    $('tatReportPeriod').textContent = view === 'current' ? 'Current workload and attention indicators.' : 'Finished cases and outcomes for the selected period.';
    refreshTatReport(); utils.haptic?.('light');
  }

  async function exportTatReport() {
    const button = $('tatReportExport'); button.disabled = true;
    const requestId = newRequestId(); const payload = reportPayload({ request_id: requestId, client_request_id: requestId });
    try {
      const response = await fetch('/api/tat-tracker/reports/export/', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Request-ID': requestId, 'Idempotency-Key': requestId, 'X-MiniApp-Message-Contract': '2' }, body: JSON.stringify(payload) });
      if (!response.ok) { const data = await response.json().catch(() => ({})); throw new Error(data.error || 'The report could not be downloaded.'); }
      const blob = await response.blob(); const url = URL.createObjectURL(blob); const anchor = document.createElement('a'); anchor.href = url; anchor.download = `tat-report-${new Date().toISOString().slice(0, 10)}.xlsx`; anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 30000);
      setStatus('TAT report downloaded.', 'ok'); utils.haptic?.('success');
    } catch (error) { setStatus(error.message, 'error'); utils.haptic?.('error'); } finally { button.disabled = false; }
  }

  document.querySelectorAll('.tabs button').forEach((button) => button.addEventListener('click', () => {
    show(button.dataset.view);
    if (button.dataset.view === 'settings') loadSettings().catch((error) => setStatus(error.message, 'error'));
  }));
  $('casesWorkspaceBtn').addEventListener('click', () => show('queue'));
  $('dashboardWorkspaceBtn').addEventListener('click', () => {
    show('dashboard');
    if (!state.report.loaded) refreshTatReport();
  });
  document.querySelectorAll('[data-report-view]').forEach(button => button.addEventListener('click', () => setTatReportView(button.dataset.reportView)));
  document.querySelectorAll('[data-chart-display]').forEach(button => button.addEventListener('click', () => setTatChartDisplay(button.dataset.chartDisplay)));
  $('tatChartPrevious').addEventListener('click', () => moveTatChart(-1));
  $('tatChartNext').addEventListener('click', () => moveTatChart(1));
  $('tatReportCharts').addEventListener('keydown', event => {
    if (event.target.matches('[data-heat-row]') && ['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) {
      const current = event.target; const row = Number(current.dataset.heatRow); const column = Number(current.dataset.heatColumn);
      const nextRow = row + (event.key === 'ArrowUp' ? -1 : event.key === 'ArrowDown' ? 1 : 0);
      const nextColumn = column + (event.key === 'ArrowLeft' ? -1 : event.key === 'ArrowRight' ? 1 : 0);
      const next = document.querySelector(`[data-heat-row="${nextRow}"][data-heat-column="${nextColumn}"]`);
      if (next) { event.preventDefault(); next.focus(); }
      return;
    }
    if (event.target.closest('button, input, select, textarea, a')) return;
    if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
      event.preventDefault(); moveTatChart(event.key === 'ArrowLeft' ? -1 : 1);
    }
  });
  ['click', 'focusin'].forEach(eventName => $('tatReportCharts').addEventListener(eventName, event => {
    if (state.report.display !== 'list') return;
    const panel = event.target.closest('[data-report-slide]');
    const slides = visibleTatChartSlides();
    const index = slides.indexOf(panel);
    if (index >= 0 && index !== state.report.activeSlide) {
      state.report.activeSlide = index;
      syncReportFilterGuidance();
    }
  }));
  $('tatReportCharts').addEventListener('touchstart', event => {
    if (state.report.display !== 'carousel' || event.touches.length !== 1) return;
    const touch = event.touches[0]; state.report.touchStart = { x: touch.clientX, y: touch.clientY };
    tg?.disableVerticalSwipes?.(); recordTatCarouselGesture('gesture_started');
  }, { passive: true });
  $('tatReportCharts').addEventListener('touchend', event => {
    if (!state.report.touchStart || state.report.display !== 'carousel' || !event.changedTouches.length) return;
    const touch = event.changedTouches[0]; const deltaX = touch.clientX - state.report.touchStart.x; const deltaY = touch.clientY - state.report.touchStart.y;
    state.report.touchStart = null;
    if (Math.abs(deltaX) < 45 || Math.abs(deltaX) <= Math.abs(deltaY) * 1.2) return;
    moveTatChart(deltaX < 0 ? 1 : -1); recordTatCarouselGesture('gesture_completed');
  }, { passive: true });
  $('tatReportCharts').addEventListener('touchcancel', () => { state.report.touchStart = null; }, { passive: true });
  $('tatOldestCases').addEventListener('click', event => {
    const button = event.target.closest('[data-oldest-case]');
    if (button) openCase(button.dataset.oldestCase).catch(error => setStatus(error.message, 'error'));
  });
  $('tatReportFilters').addEventListener('submit', event => {
    event.preventDefault(); state.report.page = 1; closeTatReportFilters(); refreshTatReport();
  });
  let tatReportFilterTimer = null;
  $('tatReportFilters').elements.search.addEventListener('input', () => {
    clearTimeout(tatReportFilterTimer); syncReportFilterGuidance();
    tatReportFilterTimer = setTimeout(() => { state.report.page = 1; refreshTatReport(); }, 350);
  });
  $('tatReportReset').addEventListener('click', () => {
    $('tatReportFilters').reset(); setDefaultReportDates(); state.report.page = 1;
    syncReportFilterGuidance(); refreshTatReport(); utils.haptic?.('light');
  });
  const immediateReportFilters = [
    'group', 'branch', 'product', 'stage', 'role', 'status', 'sla_state',
    'date_from', 'date_to', 'granularity',
    'chart_dimension', 'chart_metric', 'heatmap_pair', 'heatmap_metric',
  ];
  immediateReportFilters.forEach(name => $('tatReportFilters').elements[name].addEventListener('change', () => {
    if (name === 'date_from' || name === 'date_to') syncReportDateDisplays();
    state.report.page = 1; syncReportFilterGuidance();
    refreshTatReport();
  }));
  $('openTatReportFiltersBtn').addEventListener('click', event => openTatReportFilters(event.currentTarget));
  $('tatReportFilterWarning').addEventListener('click', event => openTatReportFilters(event.currentTarget));
  $('closeTatReportFiltersBtn').addEventListener('click', () => closeTatReportFilters());
  $('tatReportFilterOverlay').addEventListener('click', event => {
    if (event.target === event.currentTarget) closeTatReportFilters();
  });
  $('tatReportFilterSheet').addEventListener('keydown', trapReportFilterSheetFocus);
  $('tatReportPrevious').addEventListener('click', () => { if (state.report.page > 1) { state.report.page -= 1; refreshTatReport({ summary: false }); } });
  $('tatReportNext').addEventListener('click', () => { if (state.report.page * state.report.pageSize < state.report.count) { state.report.page += 1; refreshTatReport({ summary: false }); } });
  $('tatReportExport').addEventListener('click', exportTatReport);
  $('refreshBtn').addEventListener('click', async () => {
    if (state.refreshing) return;
    state.refreshing = true;
    try {
      const caseId = state.detail && state.detail.summary && state.detail.summary.case_id;
      if (state.currentView === 'detail' && caseId) await openCase(caseId);
      else if (state.currentView === 'dashboard') await refreshTatReport();
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
      const result = await api('/api/tat-tracker/settings/personal/', {
        preferences,
      });
      applyPersonalPreference(result.data || {
        compact_cards: $('preferenceCompactCards').checked,
        default_screen: $('preferenceDefaultScreen').value,
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
  setDefaultReportDates();
  bindCollapsingHeader();
  document.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape') return;
    if (state.report.filterSheetOpen) closeTatReportFilters();
    else if (state.filterSheetOpen) closeQueueFilters();
  });
  if (tg && tg.BackButton && typeof tg.BackButton.onClick === 'function') {
    tg.BackButton.onClick(() => {
      if (state.report.filterSheetOpen) return closeTatReportFilters();
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
