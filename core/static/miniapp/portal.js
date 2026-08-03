// portal.js - JBL Pipeline Portal Mini App

(() => {
  'use strict';
  // Init Telegram Web App
  const utils = window.MiniAppUtils || {};
  const portalHelpers = window.PortalMiniAppHelpers || {};
  const portalApi = window.PortalMiniAppApi || {};
  const portalQueues = window.PortalMiniAppQueues || {};
  const portalFarmerSheet = window.PortalMiniAppFarmerSheet || {};
  const portalFilters = window.PortalMiniAppFilters || {};
  const portalRequisitions = window.PortalMiniAppRequisitions || {};
  const portalInvoices = window.PortalMiniAppInvoices || {};
  const portalPayments = window.PortalMiniAppPayments || {};
  const portalImports = window.PortalMiniAppImports || {};
  const tg = utils.initTelegram ? utils.initTelegram({ closingConfirmation: false }) : window.Telegram?.WebApp;
  if (tg && !utils.initTelegram) {
    tg.ready();
    tg.expand();
  }
  // State
  const portalUiContext = utils.createUiContext ? utils.createUiContext('portal') : null;
  const restoredPortalUi = portalUiContext?.read?.() || {};
  let state = {
    activePage: document.getElementById('portal-screen')?.dataset.screen || 'dashboard',
    counts: {},
    queues: { jbl: [], credit: [], final: [], requisition: [], deferred: [], all: [], batches: [] },
    pagination: {},
    pages: { jbl: 1, credit: 1, final: 1, requisition: 1, deferred: 1, all: 1, batches: 1 },
    search: String(restoredPortalUi.search || ''),
    jblSearch: String(restoredPortalUi.jblSearch || ''),
    metaStatuses: [],
    metaDecisions: [],
    metaImabOptions: [],
    metaFinalDecisions: [],
    approvalDelegationGates: [],
    metaBranches: [],
    metaCounties: [],
    jblVisitMediaMaxBytes: 20 * 1024 * 1024,
    personalPreference: null,
    portalSettings: null,
    portalDelegationOptions: null,
    workspace: null,
    workspaceOrdering: 'queue_default',
    capabilities: new Set(),
    accessPolicyVersion: null,
    selectedFarmer: null,
    activeMode: null, // 'jbl_visit' | 'credit' | 'final_review' | 'requisition'
    filters: {
      county: String(restoredPortalUi.county || ''),
      branch: String(restoredPortalUi.branch || ''),
      reviewStage: String(restoredPortalUi.reviewStage || 'decision'),
    },
    selectedRequisitions: new Set(),
    selectedRequisitionRevisions: new Map(),
    pendingRequisitionPayload: null
  };
  let historyKind = 'orders';
  let lastShellScreen = null;

  function rememberPortalUi() {
    portalUiContext?.write?.({
      activePage: state.activePage,
      search: state.search,
      jblSearch: state.jblSearch,
      county: state.filters.county,
      branch: state.filters.branch,
      reviewStage: state.filters.reviewStage,
    });
  }

  const PAGE_CAPABILITIES = {
    dashboard: 'portal.dashboard.view',
    jbl: 'portal.jbl_queue.view',
    credit: 'portal.credit_queue.view',
    final: 'portal.final_review.view',
    requisition: 'portal.requisition.view',
    deferred: 'portal.deferred.view',
    all: 'portal.case.read',
    case_history: 'portal.case.read',
    batches: 'portal.batches.view',
    invoices: 'portal.invoice.view',
    payments: 'portal.payment.view',
    history: 'portal.documents.view',
    imports: 'portal.imports.view',
    settings: null,
  };

  // Workspace shortcuts are deliberately dormant during the production Portal
  // rollout.  This client-side gate also protects an already-open, cached
  // Portal page after the template controls have been removed.  It is not an
  // authorization decision: the retained API remains server-side IT-gated.
  const PORTAL_WORKSPACE_UI_ENABLED = false;

  // Helpers
  function el(id) { return document.getElementById(id); }

  function hasCapability(capability) {
    return !capability || state.capabilities.has(capability);
  }

  // The workspace feature can only return through an approved rollout.  Keep
  // its existing server-side capability check so re-enabling the UI never
  // broadens access by accident.
  function canManagePortalWorkspace() {
    return PORTAL_WORKSPACE_UI_ENABLED && hasCapability('portal.workspace.manage');
  }

  function applyWorkspaceVisibility() {
    const allowed = canManagePortalWorkspace();
    document.querySelectorAll('[data-portal-workspace]').forEach(node => {
      node.hidden = !allowed;
    });
    if (!allowed) state.workspace = null;
  }

  function applyCapabilityVisibility() {
    document.querySelectorAll('[data-required-capability]').forEach(node => {
      node.hidden = !hasCapability(node.dataset.requiredCapability);
    });
  }

  function firstPermittedPage() {
    return Object.keys(PAGE_CAPABILITIES).find(page => hasCapability(PAGE_CAPABILITIES[page])) || '';
  }

  function apiBase() { return portalApi.apiBase ? portalApi.apiBase() : '/api/portal'; }

  function initDataHeader() {
    if (portalApi.initDataHeader) return portalApi.initDataHeader(tg);
    const raw = tg?.initData || '';
    return utils.initDataHeader ? utils.initDataHeader(raw) : (raw ? { 'X-Telegram-Init-Data': raw } : {});
  }

  function configureHtmx() {
    if (!window.htmx) return;
    document.body.addEventListener('htmx:configRequest', event => {
      const raw = tg?.initData || '';
      if (raw) event.detail.headers['X-Telegram-Init-Data'] = raw;
    });
    document.body.addEventListener('htmx:afterSwap', event => {
      const qKey = queueKeyForList(event.detail.target?.id);
      if (qKey) {
        if (qKey === 'batches') hydrateHtmxBatchCards(event.detail.target);
        else hydrateHtmxFarmerCards(event.detail.target);
        const page = new URL(event.detail.xhr.responseURL).searchParams.get('page');
        state.pages[qKey] = parseInt(page || '1', 10) || 1;
        if (window.lucide) window.lucide.createIcons();
      }
    });
  }

  async function apiFetch(path, opts = {}) {
    if (portalApi.apiFetch) return portalApi.apiFetch(path, opts, tg);
    const headers = { 'Content-Type': 'application/json', ...initDataHeader(), ...(opts.headers || {}) };
    const requestOptions = { ...opts, headers };
    if (!requestOptions.method || String(requestOptions.method).toUpperCase() === 'GET') {
      requestOptions.cache = 'no-store';
    }
    const res = await fetch(apiBase() + path, requestOptions);
    const data = await res.json();
    return { ok: res.ok, status: res.status, data };
  }

  let _toastTimer = null;
  function showToast(msg, type = '') {
    const t = el('toast');
    if (utils.showToast) {
      utils.showToast(t, msg, {
        className: 'toast show' + (type ? ' ' + type + '-toast' : ''),
        resetClassName: 'toast',
        timeout: 3000,
      });
      return;
    }
    t.textContent = msg;
    t.className = 'toast show' + (type ? ' ' + type + '-toast' : '');
    clearTimeout(_toastTimer);
    _toastTimer = setTimeout(() => { t.classList.remove('show'); }, 3000);
  }

  // A local case change is committed before Google publication on the free
  // Render service.  Give staff a truthful outcome without blocking the case
  // action behind a slow register call.
  window.addEventListener('portal:publication-updated', event => {
    const status = event.detail?.publication?.status;
    if (status === 'synced') showToast('Case saved and registers updated.', 'success');
    if (status === 'needs_attention') {
      showToast('Case is saved, but register synchronization needs attention.', 'warning');
    }
  });

  function updateConnectionBanner() {
    const banner = el('portal-offline-banner');
    if (!banner) return;
    banner.style.display = navigator.onLine === false ? 'block' : 'none';
  }

  window.addEventListener('online', () => {
    updateConnectionBanner();
    showToast('Back online.', 'success');
  });
  window.addEventListener('offline', () => {
    updateConnectionBanner();
    showToast('Offline. Loaded data remains visible, but updates need a connection.', 'error');
  });

  function escapeHtml(value) {
    if (utils.escapeHtml) return utils.escapeHtml(value);
    return String(value ?? '').replace(/[&<>"']/g, ch => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;'
    }[ch]));
  }

  function setButtonLoading(button, loading, label) {
    if (utils.setButtonLoading) {
      utils.setButtonLoading(button, loading, label);
      return;
    }
    if (!button) return;
    if (loading) {
      if (!button.dataset.originalHtml) button.dataset.originalHtml = button.innerHTML;
      button.disabled = true;
      button.setAttribute('aria-busy', 'true');
      button.innerHTML = '<span class="spinner-inline" aria-hidden="true"></span><span>' + escapeHtml(label || 'Working') + '</span>';
    } else {
      button.disabled = false;
      button.removeAttribute('aria-busy');
      if (button.dataset.originalHtml) {
        button.innerHTML = button.dataset.originalHtml;
        delete button.dataset.originalHtml;
      }
    }
  }

  function fmt(v) { return portalHelpers.fmt ? portalHelpers.fmt(v) : (v || '-'); }
  function locationText(farmer) {
    if (portalHelpers.locationText) return portalHelpers.locationText(farmer);
    return [farmer?.county, farmer?.sub_county, farmer?.village]
      .map(value => String(value || '').trim()).filter(Boolean).join(' | ') || '-';
  }
  function fmtDate(v) {
    if (portalHelpers.fmtDate) return portalHelpers.fmtDate(v);
    if (!v) return '-';
    let d;
    if (/^\d{4}-\d{2}-\d{2}$/.test(String(v))) {
      const [year, month, day] = String(v).split('-').map(Number);
      d = new Date(year, month - 1, day);
    } else {
      d = new Date(v);
    }
    if (isNaN(d.getTime())) return String(v);
    const day = String(d.getDate()).padStart(2, '0');
    const months = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
    const month = months[d.getMonth()];
    const year = d.getFullYear();
    return `${day}-${month}-${year}`;
  }

  function fmtDateTime(v) {
    if (!v) return '-';
    if (utils.formatDateTime) return utils.formatDateTime(v);
    const text = String(v);
    const match = text.match(/(?:T|\s)(\d{1,2}):(\d{2})/);
    return `${fmtDate(v)}${match ? ` ${String(match[1]).padStart(2, '0')}:${match[2]}` : ''}`;
  }

  function stageBadge(farmer) {
    if (portalHelpers.stageBadge) return portalHelpers.stageBadge(farmer);
    const stage = farmer.pipeline_stage || 1;
    const labels = ['-', 'Awaiting JBL', 'JBL Visited', 'Credit Set', 'Ordered', '', '', 'Invoiced'];
    const styles = ['', 'badge-grey', 'badge-blue', 'badge-orange', 'badge-green', '', '', 'badge-green'];
    return `<span class="badge ${styles[stage] || ''}">${labels[stage] || 'Stage ' + stage}</span>`;
  }

  function creditBadge(farmer) {
    if (portalHelpers.creditBadge) return portalHelpers.creditBadge(farmer);
    if (!farmer.credit_decision) return '';
    const map = { Approved: 'badge-green', Rejected: 'badge-red', Deferred: 'badge-orange', Pending: 'badge-grey', 'Exemption Approved': 'badge-green' };
    return `<span class="badge ${map[farmer.credit_decision] || 'badge-grey'}">${farmer.credit_decision}</span>`;
  }

  function finalDecisionBadge(farmer) {
    if (portalHelpers.finalDecisionBadge) return portalHelpers.finalDecisionBadge(farmer);
    if (!farmer.final_decision) return '';
    const map = { Approved: 'badge-green', Rejected: 'badge-red', Deferred: 'badge-orange', 'Under Review': 'badge-blue' };
    return `<span class="badge ${map[farmer.final_decision] || 'badge-grey'}">Final: ${farmer.final_decision}</span>`;
  }

  function jblBadge(farmer) {
    if (portalHelpers.jblBadge) return portalHelpers.jblBadge(farmer);
    if (!farmer.jbl_visit_status) return '';
    const cls = farmer.jbl_visit_status.startsWith('Approved') ? 'badge-green'
      : farmer.jbl_visit_status === 'Awaiting Analysis' ? 'badge-blue'
      : farmer.jbl_visit_status.includes('Reject') || farmer.jbl_visit_status.includes('Cancel') ? 'badge-red'
      : 'badge-orange';
    return `<span class="badge ${cls}">${farmer.jbl_visit_status}</span>`;
  }
  // Tab navigation
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const page = btn.dataset.page;
      switchPage(page);
      loadPage(page);
    });
  });

  function switchPage(page) {
    state.activePage = page;
    rememberPortalUi();
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.toggle('active', b.dataset.page === page));
    document.querySelectorAll('.shell-nav-link').forEach(link => link.classList.toggle('active', link.dataset.screen === page));

    if (page !== 'requisition') {
      state.selectedRequisitions.clear();
      state.selectedRequisitionRevisions.clear();
      updateBatchPanel();
    }

    // Show filter bar on farmer list views.
    const filterBar = el('portal-filter-bar');
    if (filterBar) {
      if (page === 'dashboard' || page === 'batches' || page === 'invoices' || page === 'payments' || page === 'history' || page === 'case_history' || page === 'imports' || page === 'settings') {
        filterBar.style.display = 'none';
      } else {
        filterBar.style.display = 'flex';
        // Populate options based on new page's queues
        updateFilterOptions(state.queues[page] || []);
      }
    }

    document.querySelectorAll('.page').forEach(p => {
      const isTarget = p.id === 'page-' + page;
      if (isTarget) {
        p.style.display = 'block';
        p.offsetHeight; // force layout reflow for animation
        p.classList.add('active');
      } else {
        p.classList.remove('active');
        p.style.display = 'none';
      }
    });
  }
  // Dashboard
  async function loadDashboard() {
    const loading = el('dash-loading');
    loading.style.display = 'block';
    loading.setAttribute('aria-busy', 'true');
    el('dash-counts').style.display = 'none';
    const { ok, status, data } = await apiFetch('/dashboard/');
    if (!ok) {
      const message = data?.error || data?.message || 'The dashboard request failed.';
      const guidance = status === 403
        ? 'Ask an administrator to add your Telegram account to Users and grant Jawabu Portal access, then refresh.'
        : 'Check your connection and try again.';
      loading.innerHTML = '<strong>Dashboard unavailable</strong><span>'
        + escapeHtml(message) + '</span><span>' + escapeHtml(guidance) + '</span>';
      loading.setAttribute('aria-busy', 'false');
      loading.style.display = 'block';
      return;
    }
    loading.setAttribute('aria-busy', 'false');
    loading.style.display = 'none';
    state.counts = data.counts || {};
    renderDashboard();
    if (canManagePortalWorkspace()) {
      try { await loadPortalWorkspace({ includeSummary: true }); } catch (_) { /* Workspace shortcuts are non-critical to queue work. */ }
    }
  }

  function renderDashboard() {
    const c = state.counts;
    el('cnt-jbl').textContent = c.jbl_queue ?? '-';
    el('cnt-credit').textContent = c.credit_queue ?? '-';
    el('cnt-final').textContent = c.final_review_queue ?? '-';
    el('cnt-requisition').textContent = c.requisition_queue ?? '-';
    el('cnt-deferred').textContent = c.deferred ?? '-';
    el('cnt-total').textContent = c.total ?? '-';
    // Update tab badges
    setBadge('tab-badge-jbl', c.jbl_queue);
    setBadge('tab-badge-credit', c.credit_queue);
    setBadge('tab-badge-final', c.final_review_queue);
    setBadge('tab-badge-req', c.requisition_queue);
    el('dash-counts').style.display = 'grid';
    if (window.lucide) {
      window.lucide.createIcons();
    }
  }

  function setBadge(id, count) {
    const badge = el(id);
    if (!badge) return;
    if (count && count > 0) {
      badge.textContent = count > 99 ? '99+' : count;
      badge.style.display = 'inline-flex';
    } else {
      badge.style.display = 'none';
    }
  }

  // Clicking a count card navigates to that queue
  document.querySelectorAll('.count-card[data-page], .dashboard-total[data-page]').forEach(card => {
    card.addEventListener('click', () => {
      const page = card.dataset.page;
      switchPage(page);
      loadPage(page);
    });
  });
  // Generic queue loader
  const queueConfig = portalQueues.config ? portalQueues.config() : {
    jbl: { endpoint: '/jbl-queue/', fragmentEndpoint: '/queues/jbl/fragment/', listId: 'jbl-list', pageKey: 'jbl', mode: 'jbl_visit', emptyTitle: 'JBL visit queue is clear', emptySub: 'No farmer is waiting for a JBL visit.' },
    credit: { endpoint: '/credit-queue/', fragmentEndpoint: '/queues/credit/fragment/', listId: 'credit-list', pageKey: 'credit', mode: 'credit', emptyTitle: 'Credit queue is clear', emptySub: 'No farmer is waiting for credit analysis.' },
    final: { endpoint: '/final-review-queue/', fragmentEndpoint: '/queues/final/fragment/', listId: 'final-list', pageKey: 'final', mode: 'final_review', emptyTitle: 'Final review queue is clear', emptySub: 'No client is waiting for Head of Rural review.' },
    requisition: { endpoint: '/requisition-queue/', fragmentEndpoint: '/queues/requisition/fragment/', listId: 'req-list', pageKey: 'requisition', mode: 'requisition', emptyTitle: 'No orders to assign', emptySub: 'Approved cases awaiting an order number will appear here.' },
    deferred: { endpoint: '/deferred/', fragmentEndpoint: '/queues/deferred/fragment/', listId: 'deferred-list', pageKey: 'deferred', mode: null, emptyTitle: 'No deferred cases', emptySub: 'No farmers are deferred or flagged.' },
    all: { endpoint: '/farmers/', fragmentEndpoint: '/queues/all/fragment/', listId: 'all-list', pageKey: 'all', mode: null, emptyTitle: 'No farmers found', emptySub: 'Try a different search term.' },
    batches: { endpoint: '/requisition-batches/', fragmentEndpoint: '/requisition-batches/fragment/', listId: 'batches-list', pageKey: 'batches', mode: null, emptyTitle: 'No batches found', emptySub: 'No requisition batches have been generated yet.' },
  };

  const FINAL_REVIEW_STAGES = new Set(['decision', 'payment']);

  function normaliseFinalReviewStage(value) {
    const stage = String(value || '').trim().toLowerCase();
    return FINAL_REVIEW_STAGES.has(stage) ? stage : 'decision';
  }

  // The review queue is a two-way operational choice, not a filter with an
  // arbitrary third state. Keeping the active tab and request state together
  // prevents a fragment refresh from showing a different list than its tab.
  function syncFinalReviewStageTabs() {
    const stage = normaliseFinalReviewStage(state.filters.reviewStage);
    state.filters.reviewStage = stage;
    document.querySelectorAll('[data-final-review-stage]').forEach(tab => {
      const active = tab.dataset.finalReviewStage === stage;
      tab.classList.toggle('is-active', active);
      tab.setAttribute('aria-selected', String(active));
      tab.tabIndex = active ? 0 : -1;
    });
    const help = el('final-review-stage-help');
    if (help) {
      help.textContent = stage === 'payment'
        ? 'Review the exact cases captured in each pending payment file.'
        : 'Record the final decision before an approved case moves to Orders.';
    }
  }

  async function selectFinalReviewStage(value) {
    const stage = normaliseFinalReviewStage(value);
    if (state.filters.reviewStage === stage) {
      syncFinalReviewStageTabs();
      return;
    }
    state.filters.reviewStage = stage;
    syncFinalReviewStageTabs();
    rememberPortalUi();
    if (state.activePage === 'final') await loadQueue('final', 1);
  }

  function queueKeyForList(listId) {
    if (portalQueues.queueKeyForList) return portalQueues.queueKeyForList(listId);
    if (!listId) return null;
    const entry = Object.entries(queueConfig).find(([, cfg]) => cfg.listId === listId && cfg.fragmentEndpoint);
    return entry ? entry[0] : null;
  }

  async function loadQueue(qKey, page = 1) {
    const cfg = queueConfig[qKey];
    if (!cfg) return;
    const listEl = el(cfg.listId);
    listEl.innerHTML = '<div class="mini-skeleton-list" role="status" aria-label="Loading queue">'
      + (utils.skeletonCards ? utils.skeletonCards(3) : '<div class="empty-state"><div class="spinner-inline"></div></div>')
      + '</div>';

    const url = portalQueues.queueUrl ? portalQueues.queueUrl(qKey, page, state) : cfg.endpoint + '?page=' + page;

    const { ok, data, requestId } = await apiFetch(url);
    if (!ok) {
      const message = data?.error || 'The queue could not be loaded.';
      listEl.innerHTML = `<div class="empty-state queue-error" role="alert"><div class="es-icon">!</div><div class="es-title">Queue unavailable</div><div class="es-sub">${escapeHtml(message)}</div><button type="button" class="btn btn-secondary queue-retry" data-queue="${escapeHtml(qKey)}">Retry</button>${requestId ? `<div class="es-sub error-reference">Reference: ${escapeHtml(requestId)}</div>` : ''}</div>`;
      const retry = listEl.querySelector('.queue-retry');
      retry?.addEventListener('click', () => loadQueue(qKey, state.pages[qKey] || page));
      return;
    }

    if (qKey === 'batches') {
      const batches = data.batches || [];
      state.queues[qKey] = batches;
      state.pagination[qKey] = data.pagination || {};
      state.pages[qKey] = page;
      if (window.htmx) {
        const rendered = await renderQueueFragment(qKey, page);
        if (rendered) {
          const pgEl = el('pg-batches');
          if (pgEl) pgEl.innerHTML = '';
        } else {
          renderBatchesList(listEl, batches, cfg);
          renderPagination(qKey, data.pagination);
        }
      } else {
        renderBatchesList(listEl, batches, cfg);
        renderPagination(qKey, data.pagination);
      }
      return;
    }

    const farmers = data.farmers || [];
    state.queues[qKey] = farmers;
    state.pagination[qKey] = data.pagination || {};
    state.pages[qKey] = page;

    // Apply filtering
    if (cfg.fragmentEndpoint && window.htmx) {
      updateFilterOptions(farmers);
      const rendered = await renderQueueFragment(qKey, page);
      if (rendered) {
        const pgEl = el('pg-' + qKey);
        if (pgEl) pgEl.innerHTML = '';
      } else if (qKey !== 'dashboard' && qKey !== 'all') {
        applyFilters();
        renderPagination(qKey, data.pagination);
      } else {
        if (qKey === 'all') updateFilterOptions(farmers);
        renderFarmerList(listEl, farmers, cfg, qKey);
        renderPagination(qKey, data.pagination);
      }
    } else if (qKey !== 'dashboard' && qKey !== 'all') {
      updateFilterOptions(farmers);
      applyFilters();
    } else {
      if (qKey === 'all') updateFilterOptions(farmers);
      renderFarmerList(listEl, farmers, cfg, qKey);
    }
    if (!(cfg.fragmentEndpoint && window.htmx)) {
      renderPagination(qKey, data.pagination);
    }
  }

  async function renderQueueFragment(qKey, page = 1) {
    if (portalQueues.renderFragment) {
      return portalQueues.renderFragment(qKey, page, {
        el,
        fetchHtml: async (path) => {
          const response = await fetch(apiBase() + path, { headers: initDataHeader(), cache: 'no-store' });
          const text = await response.text();
          if (!response.ok) throw new Error(text || 'Could not load queue.');
          return text;
        },
        hydrateBatchCards: hydrateHtmxBatchCards,
        hydrateFarmerCards: hydrateHtmxFarmerCards,
        portalApi,
        state,
        tg,
      });
    }
    const cfg = queueConfig[qKey];
    const list = cfg ? el(cfg.listId) : null;
    if (!cfg?.fragmentEndpoint || !window.htmx || !list) return false;
    const params = new URLSearchParams({ page: String(page) });
    if (qKey === 'all' && state.search) params.set('search', state.search);
    if (state.filters.county) params.set('county', state.filters.county);
    if (state.filters.branch) params.set('branch', state.filters.branch);
    // Keep the payment/decision lens in the legacy fragment fallback too.
    // A stale or blocked queue helper must not silently revert HOR to the
    // final-decision queue after the user has changed the selector.
    if (qKey === 'final' && state.filters.reviewStage) params.set('stage', state.filters.reviewStage);
    try {
      const fragmentPath = cfg.fragmentEndpoint + '?' + params.toString();
      const html = portalApi.fetchHtml
        ? await portalApi.fetchHtml(fragmentPath, {}, tg)
        : utils.fetchHtml
          ? await utils.fetchHtml(apiBase() + fragmentPath, { headers: initDataHeader() })
        : await fetch(apiBase() + cfg.fragmentEndpoint + '?' + params.toString(), { headers: initDataHeader() }).then(async (response) => {
          const text = await response.text();
          if (!response.ok) throw new Error(text || 'Could not load queue.');
          return text;
        });
      list.innerHTML = html;
      if (qKey === 'batches') hydrateHtmxBatchCards(list);
      else hydrateHtmxFarmerCards(list);
      state.pages[qKey] = page;
      if (window.lucide) window.lucide.createIcons();
      return true;
    } catch (error) {
      return false;
    }
  }

  function hydrateHtmxFarmerCards(root) {
    root.querySelectorAll('.htmx-farmer-card[data-farmer-id]').forEach(card => {
      if (card.dataset.bound === '1') return;
      card.dataset.bound = '1';
      const requisitionCheckbox = card.querySelector('.farmer-card-checkbox');
      if (requisitionCheckbox && !hasCapability('portal.requisition.write')) {
        requisitionCheckbox.checked = false;
        requisitionCheckbox.disabled = true;
        requisitionCheckbox.setAttribute('aria-label', 'Order generation is not assigned to your role');
      }
      requisitionCheckbox?.addEventListener('change', event => {
        if (!hasCapability('portal.requisition.write')) {
          event.target.checked = false;
          return;
        }
        event.stopPropagation();
        const id = event.target.dataset.id;
        if (event.target.checked) {
          state.selectedRequisitions.add(id);
          state.selectedRequisitionRevisions.set(id, Number(event.target.dataset.revision || 1));
        } else {
          state.selectedRequisitions.delete(id);
          state.selectedRequisitionRevisions.delete(id);
        }
        updateBatchPanel();
      });
      card.addEventListener('click', async () => {
        await openCurrentFarmerSheet({ id: card.dataset.farmerId }, card.dataset.mode || null);
      });
    });
    root.querySelectorAll('.btn-open-payment-review').forEach(button => {
      if (button.dataset.bound === '1') return;
      button.dataset.bound = '1';
      button.addEventListener('click', event => {
        event.preventDefault();
        event.stopPropagation();
        openPaymentReviewDocument(button.dataset.paymentDocumentId);
      });
    });
  }

  function hydrateHtmxBatchCards(root) {
    if (!hasCapability('portal.invoice.write')) {
      root.querySelectorAll('.btn-upload-invoices').forEach(button => button.remove());
    }
    if (!hasCapability('portal.requisition.write')) {
      root.querySelectorAll('.btn-retry-batch').forEach(button => button.remove());
    }
    root.querySelectorAll('.btn-view-batch').forEach(btn => {
      if (btn.dataset.bound === '1') return;
      btn.dataset.bound = '1';
      btn.addEventListener('click', event => {
        event.preventDefault();
        event.stopPropagation();
        openBatchDetail(btn.dataset.order);
      });
    });
    root.querySelectorAll('.btn-download-batch').forEach(btn => {
      if (btn.dataset.bound === '1') return;
      btn.dataset.bound = '1';
      btn.addEventListener('click', event => {
        event.preventDefault();
        event.stopPropagation();
        const url = btn.dataset.url || '';
        if (!url) {
          showToast('This batch has no saved requisition file. Regenerate it first.', 'error');
          return;
        }
        openPortalLink(url);
      });
    });
    root.querySelectorAll('.btn-upload-invoices').forEach(btn => {
      if (btn.dataset.bound === '1') return;
      btn.dataset.bound = '1';
      btn.addEventListener('click', event => {
        event.preventDefault();
        event.stopPropagation();
        openInvoiceOverlay(btn.dataset.order);
      });
    });
  }

  function renderBatchesList(listEl, batches, cfg) {
    if (!batches.length) {
      listEl.innerHTML = `<div class="empty-state"><div class="es-icon">Box</div><div class="es-title">${cfg.emptyTitle}</div><div class="es-sub">${cfg.emptySub}</div></div>`;
      return;
    }

    listEl.innerHTML = batches.map((b) => {
      const invoicedCount = b.invoiced_count ?? b.invoice_summary?.invoiced_count ?? 0;
      const farmerCount = b.farmer_count || (b.farmers || []).length;
      const allInvoiced = farmerCount > 0 && invoicedCount === farmerCount;
      const invoiceProgress = farmerCount ? `${invoicedCount}/${farmerCount} invoiced` : '0 invoiced';
      const invoiceColor = allInvoiced ? 'badge-green' : invoicedCount > 0 ? 'badge-orange' : 'badge-grey';
      const amounts = b.amount_summary || {};
      const amountBadges = [
        ['HB deposit', amounts.deposit_hb], ['JBL deposit', amounts.deposit_jbl],
        ['Invoice', amounts.invoice_amount], ['Discount', amounts.discount],
        ['Balance due', amounts.balance_due],
      ].map(([label, value]) => `<span class="badge badge-grey">${label}: ${value == null ? '—' : 'KES ' + escapeHtml(value)}</span>`).join('');
      const syncBadge = b.drive_sync_status === 'retryable_failure'
        ? '<span class="badge badge-red" title="Drive upload failed; retry generation">Drive retry needed</span>'
        : b.drive_sync_status === 'pending'
          ? '<span class="badge badge-orange">Drive syncing</span>'
          : (b.drive_url || b.has_requisition_file)
            ? '<span class="badge badge-green">Form saved</span>'
            : '<span class="badge badge-grey">No generated form yet</span>';
      const clients = (b.farmers || []).slice(0, 8).map(f => `
        <span class="badge ${f.invoiced ? 'badge-green' : 'badge-grey'}" title="${escapeHtml(f.invoice_number ? ('Invoice ' + f.invoice_number) : 'No invoice uploaded')}">
          ${escapeHtml(f.customer_name || 'Unnamed')} (${escapeHtml(f.county || 'N/A')})
        </span>
      `).join('');
      const extra = (b.farmers || []).length > 8 ? `<span class="badge badge-grey">+${(b.farmers || []).length - 8} more</span>` : '';
      return `
        <div class="farmer-card batch-card" style="cursor: default;">
          <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:10px;flex-wrap:wrap;">
            <div>
              <div class="fc-name">Order ${escapeHtml(b.order_number)}</div>
              <div class="fc-sub">
                ${escapeHtml(b.requisition_date ? fmtDate(b.requisition_date) : 'No date')} - ${farmerCount} client(s)
                <span class="badge ${invoiceColor}" style="margin-left:4px;">${invoiceProgress}</span>
                ${syncBadge}
              </div>
              ${b.generated_by ? `<div class="fc-sub">Generated by ${escapeHtml(b.generated_by)}</div>` : ''}
            </div>
            <div style="display:flex;gap:8px;flex-wrap:wrap;">
              <button class="btn btn-secondary btn-view-batch" data-order="${escapeHtml(b.order_number)}">View</button>
              <button class="btn btn-primary btn-download-batch" data-url="${escapeHtml(b.drive_url || '')}" ${b.drive_url ? '' : 'disabled'}>Open in Drive</button>
              ${b.drive_sync_status === 'retryable_failure' && hasCapability('portal.requisition.write') ? `<button class="btn btn-secondary btn-retry-batch" data-order="${escapeHtml(b.order_number)}">Retry storage</button>` : ''}
              ${hasCapability('portal.invoice.write') ? `<button class="btn btn-secondary btn-upload-invoices" data-order="${escapeHtml(b.order_number)}">Upload Invoices</button>` : ''}
            </div>
          </div>
          <div style="border-top:1px solid var(--border-color);padding-top:8px;margin-top:8px;display:flex;gap:4px;flex-wrap:wrap;">
            ${amountBadges}
          </div>
          <div style="border-top:1px solid var(--border-color);padding-top:8px;margin-top:8px;display:flex;gap:4px;flex-wrap:wrap;">
            ${clients || '<span class="fc-sub">No clients linked to this batch.</span>'}${extra}
          </div>
        </div>
      `;
    }).join('');

    listEl.querySelectorAll('.btn-view-batch').forEach(btn => {
      btn.addEventListener('click', e => {
        e.preventDefault();
        e.stopPropagation();
        openBatchDetail(btn.dataset.order);
      });
    });

    listEl.querySelectorAll('.btn-download-batch').forEach(btn => {
      btn.addEventListener('click', e => {
        e.preventDefault();
        e.stopPropagation();
        const url = btn.dataset.url || '';
        if (!url) {
          showToast('This batch has no saved requisition file. Regenerate it first.', 'error');
          return;
        }
        openPortalLink(url);
      });
    });

    listEl.querySelectorAll('.btn-upload-invoices').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        openInvoiceOverlay(btn.dataset.order);
      });
    });

    listEl.querySelectorAll('.btn-retry-batch').forEach(btn => {
      btn.addEventListener('click', async (e) => {
        e.preventDefault();
        e.stopPropagation();
        btn.disabled = true;
        btn.textContent = 'Retrying…';
        const result = await portalApi.postJson(
          `/requisition-batches/${encodeURIComponent(btn.dataset.order)}/retry-sync/`,
          {}, tg,
        );
        if (!result.ok) {
          showToast(result.data?.error || 'Storage retry failed.', 'error');
          btn.disabled = false;
          btn.textContent = 'Retry storage';
          return;
        }
        showToast('Requisition workbook stored successfully.', 'success');
        await loadQueue('batches', state.pages.batches || 1);
      });
    });

    if (window.lucide) window.lucide.createIcons();
  }


  function openPortalLink(url) {
    if (!url) return;
    if (tg?.openLink) tg.openLink(url);
    else window.open(url, '_blank', 'noopener');
  }

  function summaryGrid(items) {
    if (portalHelpers.summaryGrid) return portalHelpers.summaryGrid(items);
    return items.map(item => `
      <div class="batch-summary-item">
        <strong>${escapeHtml(item.value)}</strong>
        <span>${escapeHtml(item.label)}</span>
      </div>
    `).join('');
  }

  function batchClientRows(farmers, blockedById = {}) {
    if (portalHelpers.batchClientRows) return portalHelpers.batchClientRows(farmers, blockedById);
    if (!farmers.length) return '<div class="empty-state"><div class="es-title">No clients</div></div>';
    return farmers.map(f => {
      const missing = blockedById[f.id] || [];
      const invoice = f.invoice_number ? `Invoice ${escapeHtml(f.invoice_number)}` : 'No invoice';
      return `
        <div class="batch-client-row">
          <div class="name">${escapeHtml(f.customer_name || 'Unnamed client')}</div>
          <div class="meta">ID ${escapeHtml(f.national_id || '-')} | ${escapeHtml(f.primary_phone || '-')} | ${escapeHtml(f.county || '-')}</div>
          <div class="meta">${escapeHtml(invoice)}${f.invoice_amount ? ' | KES ' + escapeHtml(f.invoice_amount) : ''}</div>
          ${missing.length ? `<div class="batch-warning" style="margin-top:8px;">Missing: ${missing.map(escapeHtml).join(', ')}</div>` : ''}
        </div>
      `;
    }).join('');
  }

  function renderWarnings(container, warnings) {
    if (portalHelpers.renderWarnings) {
      portalHelpers.renderWarnings(container, warnings);
      return;
    }
    if (!container) return;
    if (!warnings || !warnings.length) {
      container.innerHTML = '';
      return;
    }
    container.innerHTML = `<div class="batch-warning-list">${warnings.map(w => `<div class="batch-warning">${escapeHtml(w.message || w)}</div>`).join('')}</div>`;
  }

  function openInvoiceOverlay(orderNumber) {
    if (portalRequisitions.openInvoiceOverlay) {
      portalRequisitions.openInvoiceOverlay(orderNumber);
    }
  }

  function openPaymentReviewDocument(documentId) {
    if (!documentId) return;
    if (portalRequisitions.openFinalPaymentHistory) {
      portalRequisitions.openFinalPaymentHistory(documentId);
    } else {
      showToast('Payment review is unavailable. Refresh the portal and try again.', 'error');
    }
  }

  function paymentReviewMarkup(farmer) {
    if (state.filters.reviewStage !== 'payment' || !farmer.payment_review_document_id) return '';
    return `<span class="badge badge-orange">Payment #${escapeHtml(farmer.payment_review_payment_number || '-')} awaiting HOR review</span><span class="badge badge-grey">Order ${escapeHtml(farmer.payment_review_order_number || '-')}</span>
      <button type="button" class="btn btn-secondary btn-open-payment-review" data-payment-document-id="${escapeHtml(farmer.payment_review_document_id)}">Open payment review</button>`;
  }

  function reviewCardMode(cfg, qKey) {
    if (qKey !== 'final') return cfg.mode;
    if (state.filters.reviewStage === 'payment') return null;
    return cfg.mode;
  }

  async function openBatchDetail(orderNumber) {
    if (portalRequisitions.openBatchDetail) {
      return portalRequisitions.openBatchDetail(orderNumber);
    }
  }


  function renderFarmerList(listEl, farmers, cfg, qKey) {
    if (!farmers.length) {
      listEl.innerHTML = `<div class="empty-state queue-empty-state"><div class="es-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="m5 12 4.2 4.2L19 6.5"/></svg></div><div class="es-title">${cfg.emptyTitle}</div><div class="es-sub">${cfg.emptySub}</div></div>`;
      return;
    }
    listEl.innerHTML = farmers.map((f, i) => `
      <div class="farmer-card${qKey === 'requisition' ? ' requisition-card' : ''}" data-qkey="${qKey}" data-farmer-id="${escapeHtml(f.id || '')}" data-idx="${i}" id="fc-${qKey}-${i}">
        ${qKey === 'requisition' ? `
          <input type="checkbox" class="farmer-card-checkbox" data-id="${escapeHtml(f.id || '')}" data-revision="${escapeHtml(String(f.workflow_revision || 1))}" ${state.selectedRequisitions.has(f.id) ? 'checked' : ''} onclick="event.stopPropagation();">
        ` : ''}
        <div style="flex: 1;">
          <div class="fc-name">${f.display_number ? `<span class="farmer-card-number" aria-label="Queue position ${escapeHtml(String(f.display_number))}">${escapeHtml(String(f.display_number))}</span>` : ''}${escapeHtml(f.customer_name || f.national_id || f.primary_phone || 'Unknown')}</div>
          <div class="fc-sub">${escapeHtml(locationText(f))}</div>
          <div class="fc-sub">${escapeHtml(f.primary_phone || '')}</div>
          ${qKey === 'jbl' && f.sign_date ? `<div class="fc-sub fc-visit-date">HB visit: ${escapeHtml(fmtDate(f.sign_date))}</div>` : ''}
          <div class="fc-badges">
            ${stageBadge(f)}
            ${jblBadge(f)}
            ${creditBadge(f)}
            ${paymentReviewMarkup(f)}
            ${f.order_number ? `<span class="badge badge-green">Order: ${f.order_number}</span>` : ''}
          </div>
        </div>
      </div>
    `).join('');

    listEl.querySelectorAll('.farmer-card').forEach(card => {
      card.addEventListener('click', () => {
        const qKey = card.dataset.qkey;
        const farmerId = card.dataset.farmerId;
        const farmer = (state.queues[qKey] || []).find(item => String(item.id) === String(farmerId)) || { id: farmerId };
        openCurrentFarmerSheet(farmer, reviewCardMode(cfg, qKey));
      });
    });

    listEl.querySelectorAll('.btn-open-payment-review').forEach(button => {
      button.addEventListener('click', event => {
        event.preventDefault();
        event.stopPropagation();
        openPaymentReviewDocument(button.dataset.paymentDocumentId);
      });
    });

    if (qKey === 'requisition') {
      listEl.querySelectorAll('.farmer-card-checkbox').forEach(cb => {
        cb.addEventListener('change', () => {
          const id = cb.dataset.id;
          if (cb.checked) {
            state.selectedRequisitions.add(id);
            state.selectedRequisitionRevisions.set(id, Number(cb.dataset.revision || 1));
          } else {
            state.selectedRequisitions.delete(id);
            state.selectedRequisitionRevisions.delete(id);
          }
          updateBatchPanel();
        });
      });
    }
  }

  function updateFilterOptions(farmers) {
    if (portalFilters.updateFilterOptions) portalFilters.updateFilterOptions(farmers);
  }

  function applyFilters() {
    if (portalFilters.applyFilters) portalFilters.applyFilters();
  }

  function renderPagination(qKey, pg) {
    const pgEl = el('pg-' + qKey);
    if (!pgEl || !pg || pg.pages <= 1) { if (pgEl) pgEl.innerHTML = ''; return; }
    const prev = pg.page > 1;
    const next = pg.page < pg.pages;
    pgEl.innerHTML = `
      <button id="pg-prev-${qKey}" ${prev ? '' : 'disabled'}>Prev</button>
      <span class="pg-info">Page ${pg.page} of ${pg.pages} (${pg.total} total)</span>
      <button id="pg-next-${qKey}" ${next ? '' : 'disabled'}>Next</button>
    `;
    if (prev) pgEl.querySelector('#pg-prev-' + qKey).addEventListener('click', () => loadQueue(qKey, pg.page - 1));
    if (next) pgEl.querySelector('#pg-next-' + qKey).addEventListener('click', () => loadQueue(qKey, pg.page + 1));
  }
  // Detail sheet
  function openFarmerSheet(farmer, mode) {
    if (portalFarmerSheet.openFarmerSheet) {
      portalFarmerSheet.openFarmerSheet(farmer, mode);
      appendWorkspacePinControl(farmer);
    }
  }

  // Queue responses are intentionally compact and may have been loaded before
  // a field visit or correction changed the farmer's location.  Always resolve
  // the selected card against the canonical detail endpoint before rendering.
  async function openCurrentFarmerSheet(farmer, mode) {
    if (!farmer || !farmer.id) return;
    try {
      const requestOptions = canManagePortalWorkspace()
        ? { headers: { 'X-Portal-Workspace-Open-Key': newWorkspaceOpenKey() } }
        : undefined;
      const { ok, data } = await apiFetch('/farmers/' + encodeURIComponent(farmer.id) + '/', requestOptions);
      if (!ok || !data || !data.ok || !data.farmer) {
        showToast((data && data.error) || 'Could not load current farmer details.', 'error');
        return;
      }
      openFarmerSheet(data.farmer, mode);
    } catch (error) {
      showToast('Could not load current farmer details. Check your connection and retry.', 'error');
    }
  }

  function reloadCurrentQueue() {
    const p = state.activePage;
    if (queueConfig[p]) loadQueue(p, state.pages[p] || 1);
  }

  // An assigned order leaves the "Ready for order" queue by design.  Take the
  // operator straight to the durable batch view so the newly assigned client
  // and its in-app requisition preview remain visible instead of appearing to
  // vanish after the form is submitted.
  async function openAssignedOrder(orderNumber) {
    if (!orderNumber) return;
    switchPage('batches');
    await loadQueue('batches', 1);
    await openBatchDetail(orderNumber);
  }
  // Search (All Cases tab)
  let searchTimer;
  el('all-search')?.addEventListener('input', e => {
    clearTimeout(searchTimer);
    state.search = e.target.value.trim();
    rememberPortalUi();
    searchTimer = setTimeout(() => loadQueue('all', 1), 400);
  });
  // Meta (dropdown values)
  async function loadMeta() {
    const { ok, data } = await apiFetch('/meta/');
    if (!ok) return;
    state.metaStatuses = data.jbl_visit_statuses || [];
    state.metaDecisions = data.credit_decisions || [];
    state.metaImabOptions = data.imab_created_options || [];
    state.metaFinalDecisions = data.final_decisions || [];
    state.approvalDelegationGates = data.approval_delegation_gates || [];
    state.metaBranches = data.branches || [];
    state.metaCounties = data.counties || [];
    state.jblVisitMediaMaxBytes = Number(data.jbl_visit_media_max_bytes || state.jblVisitMediaMaxBytes);
    if (portalApi.schedulePublication && Array.isArray(data.due_publication_operation_ids)) {
      portalApi.schedulePublication({ pending_operation_ids: data.due_publication_operation_ids }, tg);
    }
    const nextPolicyVersion = data.access_policy_version || null;
    if (state.accessPolicyVersion && nextPolicyVersion && state.accessPolicyVersion !== nextPolicyVersion) {
      window.location.reload();
      return;
    }
    state.accessPolicyVersion = nextPolicyVersion;
    state.capabilities = new Set(data.capabilities || []);
    applyCapabilityVisibility();
    applyWorkspaceVisibility();
    portalFilters.updateFilterOptions(state.queues[state.activePage] || []);
  }

  function paymentHistoryScope(document) {
    // Payment number plus order is the operator-facing batch identity.
    // Versions may carry different farmer snapshots, but they are still
    // revisions of the same payment/order and should not become duplicate
    // top-level cards. Keeping the order in the key prevents an unrelated
    // batch that happens to reuse a payment number from being merged.
    const payment = String(document?.payment_number || '').trim();
    const order = String(document?.order_number || '').trim();
    return payment ? `payment:${payment}::order:${order}` : `order:${order}`;
  }

  function collapsePaymentHistoryVersions(documents) {
    const grouped = new Map();
    (documents || []).forEach(document => {
      const key = paymentHistoryScope(document);
      if (!grouped.has(key)) grouped.set(key, []);
      grouped.get(key).push(document);
    });
    return [...grouped.values()].map(versions => {
      versions.sort((left, right) => Number(right.version || 0) - Number(left.version || 0));
      return { ...versions[0], previous_versions: versions.slice(1) };
    });
  }

  function physicalSignoffMarkup(document, kind) {
    const signoff = document?.physical_signoff || {};
    const type = kind === 'payments' ? 'payment' : 'requisition';
    const status = String(signoff.status || 'awaiting_signed_scan');
    const role = signoff.approval_role ? `Configured approver: ${escapeHtml(signoff.approval_role)}.` : 'No approver role is configured.';
    if (status === 'signed_approved') {
      return `<section class="physical-signoff physical-signoff-approved"><div><strong>Signed &amp; stamped scan retained</strong><span>${role} Hash: ${escapeHtml(String(signoff.scan_checksum || '').slice(0, 12))}&hellip;</span></div>${signoff.drive_url ? `<button type="button" class="btn btn-secondary history-open-signed-scan" data-url="${escapeHtml(signoff.drive_url)}">Open signed scan</button>` : ''}</section>`;
    }
    if (status === 'legacy_not_signable') {
      return `<section class="physical-signoff physical-signoff-muted"><div><strong>Legacy workbook</strong><span>Its source bytes were not retained. Regenerate this document before attaching a signed scan.</span></div></section>`;
    }
    if (status === 'upload_failed') {
      return `<section class="physical-signoff physical-signoff-warning"><div><strong>Signed scan retained locally; Drive retry needed</strong><span>${escapeHtml(signoff.drive_error || 'The scan has not reached Drive yet.')}</span></div>${signoff.id ? `<button type="button" class="btn btn-secondary history-retry-signed-scan" data-signoff-id="${escapeHtml(signoff.id)}">Retry upload</button>` : ''}</section>`;
    }
    if (status === 'rejected') {
      return `<section class="physical-signoff physical-signoff-warning"><div><strong>Signed scan rejected</strong><span>${escapeHtml(signoff.rejection_reason || 'Attach a new signed scan after correcting it.')}</span></div></section>`;
    }
    if (!signoff.can_upload) {
      return `<section class="physical-signoff physical-signoff-muted"><div><strong>Awaiting signed &amp; stamped scan</strong><span>${role}</span></div></section>`;
    }
    return `<details class="physical-signoff physical-signoff-upload"><summary><span><strong>Attach signed &amp; stamped scan</strong><small>${role} The original Excel stays unchanged.</small></span></summary><div class="physical-signoff-form"><label class="invoice-upload-dropzone"><span class="upload-icon">&#8593;</span><strong>Tap to choose signed PDF or image</strong><small>PDF, JPG, or PNG. One complete, readable scan.</small><input class="history-signed-scan" type="file" accept="application/pdf,image/jpeg,image/png" hidden></label><label class="physical-signoff-attestation"><input class="history-signoff-attest" type="checkbox"> I confirm this is the complete signed and stamped copy of this exact document version.</label><button type="button" class="btn btn-primary history-upload-signed-scan" data-document-type="${type}" data-document-id="${escapeHtml(document.id)}">Upload signed scan</button></div></details>`;
  }

  function priorPhysicalSignoffsMarkup(document) {
    const prior = document?.physical_signoff?.previous_approved || [];
    if (!prior.length) return '';
    return `<details class="history-previous-versions physical-signoff-prior"><summary>${prior.length} earlier signed version${prior.length === 1 ? '' : 's'} retained</summary><div>${prior.map(item => `<div class="history-previous-version"><span>v${escapeHtml(item.source_version || 0)} - signed scan retained</span>${item.drive_url ? `<button type="button" class="btn btn-secondary history-open-signed-scan" data-url="${escapeHtml(item.drive_url)}">Open signed scan</button>` : ''}</div>`).join('')}</div></details>`;
  }

  function renderDocumentHistory(documents, kind) {
    const target = el('history-list');
    if (!target) return;
    if (!documents.length) {
      target.innerHTML = `<div class="empty-state"><div class="es-title">No ${kind} documents yet</div><div class="es-sub">Generated payment reviews and final documents will appear here.</div></div>`;
      return;
    }
    target.innerHTML = documents.map(doc => {
      const previousVersions = kind === 'payments' && doc.previous_versions?.length
        ? `<details class="history-previous-versions"><summary>${doc.previous_versions.length} previous version${doc.previous_versions.length === 1 ? '' : 's'} retained</summary><div>${doc.previous_versions.map(previous => `<div class="history-previous-version"><span>v${escapeHtml(previous.version || 0)} - ${escapeHtml(previous.status === 'final' ? 'Final' : previous.status === 'pending_review' ? 'Awaiting Head of Rural review' : previous.status === 'failed' ? 'Storage failed' : 'Saved')}</span><button type="button" class="btn btn-secondary history-view-document" data-kind="payments" data-id="${escapeHtml(previous.id)}">View</button>${previous.physical_signoff?.status === 'signed_approved' && previous.physical_signoff?.drive_url ? `<button type="button" class="btn btn-secondary history-open-signed-scan" data-url="${escapeHtml(previous.physical_signoff.drive_url)}">Open signed scan</button>` : ''}</div>`).join('')}</div></details>`
        : '';
      const syncBadge = doc.sync_status === 'retryable_failure'
        ? `<span class="badge badge-red" title="${escapeHtml(doc.sync_error || 'External storage failed')}">Storage retry needed</span>`
        : doc.sync_status === 'pending'
          ? '<span class="badge badge-orange">Storage syncing</span>'
          : doc.sync_status === 'succeeded'
            ? '<span class="badge badge-green">Stored</span>'
            : '';
      return `<article class="farmer-card history-document-card">
        <div class="fc-name">${kind === 'payments' ? `Payment #${escapeHtml(doc.payment_number || '-')}` : `Order ${escapeHtml(doc.order_number || '-')}`}</div>
        <div class="fc-sub">${kind === 'payments' ? `Order ${escapeHtml(doc.order_number || '-')} | ` : ''}${escapeHtml(doc.row_count || 0)} client(s) | Version ${escapeHtml(doc.version || 0)}</div>
        <div class="fc-sub">Workbook generated: ${escapeHtml(fmtDateTime(doc.workbook_generated_at || doc.generated_at))}${doc.generated_by ? ` | ${escapeHtml(doc.generated_by)}` : ''}</div>
        ${syncBadge}
        ${kind === 'payments' ? `<span class="badge ${doc.status === 'final' ? 'badge-green' : doc.status === 'failed' ? 'badge-red' : 'badge-orange'}">${doc.status === 'final' ? 'Final' : doc.status === 'failed' ? 'Storage retry needed' : 'Awaiting Head of Rural review'}</span>` : ''}
        <div class="history-document-actions">
          <button type="button" class="btn btn-secondary history-view-document" data-kind="${kind}" data-id="${escapeHtml(doc.id)}" data-order="${escapeHtml(doc.order_number || '')}">${kind === 'payments' && doc.status !== 'final' ? 'Review payment' : 'View preview'}</button>
          ${doc.drive_url || doc.download_url ? `<button type="button" class="btn btn-primary history-open-excel" data-url="${escapeHtml(doc.drive_url || doc.download_url)}">Open Excel</button>` : ''}
          ${hasCapability('portal.documents.regenerate') && kind === 'payments'
            ? (doc.status === 'final' || doc.status === 'failed' ? `<button type="button" class="btn btn-secondary history-regenerate-payment" data-id="${escapeHtml(doc.id)}">${doc.status === 'failed' ? 'Retry payment doc' : 'Regenerate payment doc'}</button>` : '')
            : (hasCapability('portal.documents.regenerate') && kind === 'orders' ? `<button type="button" class="btn btn-secondary history-regenerate-order" data-order="${escapeHtml(doc.order_number || '')}" data-requisition-date="${escapeHtml(doc.requisition_date || '')}" data-farmer-ids="${escapeHtml((doc.farmer_ids || []).join(','))}">Regenerate requisition/order</button>` : '')}
        </div>
        ${physicalSignoffMarkup(doc, kind)}
        ${priorPhysicalSignoffsMarkup(doc)}
        ${previousVersions}
      </article>`;
    }).join('');
  }
  async function loadHistory(kind = historyKind) {
    historyKind = kind;
    const target = el('history-list');
    if (target) target.innerHTML = '<div class="empty-state"><div class="spinner-inline"></div></div>';
    document.querySelectorAll('.history-kind').forEach(button => {
      button.classList.toggle('btn-primary', button.dataset.kind === kind);
      button.classList.toggle('btn-secondary', button.dataset.kind !== kind);
    });
    const { ok, data } = await apiFetch('/document-history/?kind=' + encodeURIComponent(kind));
    if (!ok || !data.ok) {
      if (target) target.innerHTML = '<div class="empty-state"><div class="es-title">Could not load document history</div></div>';
      return;
    }
    const documents = kind === 'payments'
      ? collapsePaymentHistoryVersions(data.documents || [])
      : (data.documents || []);
    renderDocumentHistory(documents, kind);
  }

  function caseHistoryUrl(farmerId) {
    return farmerId
      ? `/portal/cases/${encodeURIComponent(farmerId)}/`
      : '/portal/s/case_history/';
  }

  function showCaseHistorySearch() {
    const results = el('case-history-results');
    const selected = el('case-history-selected');
    if (results) results.hidden = false;
    if (selected) selected.hidden = true;
  }

  async function loadCaseHistoryFarmer(farmerId, { pushUrl = false } = {}) {
    if (!farmerId) {
      showCaseHistorySearch();
      return;
    }
    const results = el('case-history-results');
    const selected = el('case-history-selected');
    const content = el('case-history-content');
    if (!selected || !content) return;
    if (results) results.hidden = true;
    selected.hidden = false;
    if (pushUrl) window.history.pushState({ screen: 'case_history', farmerId }, '', caseHistoryUrl(farmerId));
    content.innerHTML = '<div class="empty-state"><div class="spinner-inline"></div><div class="es-sub">Loading complete case history...</div></div>';
    const requestOptions = canManagePortalWorkspace()
      ? { headers: { 'X-Portal-Workspace-Open-Key': newWorkspaceOpenKey() } }
      : undefined;
    const { ok, data } = await apiFetch('/farmers/' + encodeURIComponent(farmerId) + '/', requestOptions);
    if (!ok || !data?.ok) {
      content.innerHTML = `<div class="batch-warning">${escapeHtml(data?.error || 'Could not load case history.')}</div>`;
      return;
    }
    portalFarmerSheet.renderCase360?.(data.case360, content);
  }

  async function searchCaseHistory(query) {
    const target = el('case-history-results');
    if (!target) return;
    const normalized = String(query || '').trim();
    if (!normalized) {
      target.innerHTML = '<div class="empty-state"><div class="es-title">Enter a search term</div><div class="es-sub">Use a customer name, telephone number, or national ID.</div></div>';
      return;
    }
    showCaseHistorySearch();
    target.innerHTML = '<div class="empty-state"><div class="spinner-inline"></div></div>';
    const { ok, data } = await apiFetch('/farmers/?search=' + encodeURIComponent(normalized));
    if (!ok || !data?.ok) {
      target.innerHTML = `<div class="batch-warning">${escapeHtml(data?.error || 'Could not search cases.')}</div>`;
      return;
    }
    const farmers = data.farmers || [];
    target.innerHTML = farmers.length ? farmers.map(farmer => `
      <article class="farmer-card case-history-result">
        <div class="fc-top"><div><div class="fc-name">${escapeHtml(farmer.customer_name || 'Unnamed customer')}</div><div class="fc-sub">${escapeHtml([farmer.national_id, farmer.primary_phone].filter(Boolean).join(' | ') || 'No ID or telephone recorded')}</div></div></div>
        <div class="fc-sub">${escapeHtml(locationText(farmer))}</div>
        <button type="button" class="btn btn-primary case-history-open" data-farmer-id="${escapeHtml(farmer.id)}">Open Case History</button>
      </article>`).join('') : '<div class="empty-state"><div class="es-title">No matching cases</div><div class="es-sub">Check the spelling, telephone number, or national ID.</div></div>';
  }

  function loadCaseHistory() {
    const farmerId = document.getElementById('portal-screen')?.dataset.caseFarmerId;
    if (farmerId) loadCaseHistoryFarmer(farmerId);
    else showCaseHistorySearch();
  }

  // Page router
  function loadPage(page) {
    if (page === 'dashboard') loadDashboard();
    else if (page === 'invoices' && portalInvoices.load) portalInvoices.load(1);
    else if (page === 'history') loadHistory();
    else if (page === 'case_history') loadCaseHistory();
    else if (page === 'payments' && portalPayments.load) portalPayments.load();
    else if (page === 'imports' && portalImports.load) portalImports.load();
    else if (page === 'settings') loadPortalSettings(true);
    else if (queueConfig[page]) loadQueue(page, 1);
  }

  function populatePortalSettingScreens(screens, selected) {
    const select = el('portal-preference-default-screen');
    if (!select) return;
    select.replaceChildren();
    const defaultOption = document.createElement('option');
    defaultOption.value = '';
    defaultOption.textContent = 'Role default';
    select.appendChild(defaultOption);
    (screens || []).forEach((screen) => {
      const option = document.createElement('option');
      option.value = screen.key;
      option.textContent = screen.label;
      select.appendChild(option);
    });
    select.value = selected || '';
  }

  function populatePortalSettingSelect(id, items, selected, emptyLabel) {
    const select = el(id);
    if (!select) return;
    select.replaceChildren();
    const empty = document.createElement('option');
    empty.value = '';
    empty.textContent = emptyLabel;
    select.appendChild(empty);
    (items || []).forEach((item) => {
      const option = document.createElement('option');
      option.value = item.value ?? item.key ?? item;
      option.textContent = item.label ?? item.value ?? item;
      select.appendChild(option);
    });
    select.value = selected || '';
  }

  function delegationDateTimeValue(hoursFromNow = 8) {
    const date = new Date(Date.now() + hoursFromNow * 60 * 60 * 1000);
    date.setMinutes(date.getMinutes() - date.getTimezoneOffset());
    return date.toISOString().slice(0, 16);
  }

  function delegationMarkup(item, history = false) {
    const scope = [item.branch || 'All branches', item.product || 'All products'].join(' · ');
    const activity = history
      ? (item.revoked_at ? `Revoked ${fmtDateTime(item.revoked_at)}` : `Expired ${fmtDateTime(item.expires_at)}`)
      : `Ends ${fmtDateTime(item.expires_at)}`;
    const revokeForm = history ? '' : `<form class="portal-delegation-revoke-form" data-delegation-id="${escapeHtml(item.id)}">
      <label class="sr-only" for="delegation-revoke-${escapeHtml(item.id)}">Reason for revoking delegation</label>
      <input id="delegation-revoke-${escapeHtml(item.id)}" name="reason" maxlength="2000" required placeholder="Reason for revoking">
      <button class="btn btn-secondary" type="submit">Revoke</button>
    </form>`;
    return `<article class="portal-delegation-row${history ? ' is-history' : ''}">
      <div><strong>${escapeHtml(item.delegate)} · ${escapeHtml(item.gate_label)}</strong>
        <span>${escapeHtml(scope)} · ${escapeHtml(activity)}</span>
        <span>Granted by ${escapeHtml(item.authorized_by)}: ${escapeHtml(item.reason || 'No reason recorded.')}</span>
        ${item.revocation_reason ? `<span>Revocation: ${escapeHtml(item.revocation_reason)}</span>` : ''}
      </div>${revokeForm}
    </article>`;
  }

  function renderPortalHealth(target, health, canManageMaintenance = false) {
    const labels = {
      database: 'Database',
      requisition_template: 'Requisition template',
      payment_template: 'Payment template',
      order_storage: 'Order storage',
      payment_storage: 'Payment storage',
    };
    const checks = Object.entries(health.checks || {}).map(([key, value]) => `<div class="portal-health-check${value === 'ok' ? '' : ' is-degraded'}"><strong>${escapeHtml(labels[key] || key)}</strong><span>${escapeHtml(value === 'ok' ? 'Ready' : value === 'missing' ? 'Needs configuration' : 'Retry needed')}</span></div>`).join('');
    const retryCount = Number(health.due_order_retries || 0) + Number(health.due_payment_retries || 0);
    const status = String(health.status || 'down');
    const statusCopy = {
      live: 'Live — Portal is ready for normal work.',
      maintenance: `Under maintenance — staff can view records but new changes are paused.${health.maintenance?.reason ? ` ${health.maintenance.reason}` : ''}`,
      degraded: `Some document operations need attention${retryCount ? ` (${retryCount} retry${retryCount === 1 ? '' : 'ies'} due)` : ''}.`,
      down: 'Portal readiness could not be confirmed. Do not submit a new change until it is checked.',
    }[status] || 'System readiness could not be confirmed.';
    const maintenanceControls = canManageMaintenance ? `<form class="portal-maintenance-form" data-portal-maintenance-form>
      <h3>Maintenance mode</h3><p>Under maintenance keeps Portal readable and pauses new writes. Existing requests already in progress can finish.</p>
      <label>Mode<select name="mode"><option value="live"${status !== 'maintenance' ? ' selected' : ''}>Live</option><option value="maintenance"${status === 'maintenance' ? ' selected' : ''}>Under maintenance</option></select></label>
      <label class="maintenance-reason">Reason<textarea name="reason" maxlength="500" placeholder="Required when pausing new Portal changes">${escapeHtml(health.maintenance?.reason || '')}</textarea></label>
      <button type="submit" class="btn btn-secondary">Save maintenance mode</button>
    </form>` : '';
    target.innerHTML = `<div class="portal-readiness-heading status-${escapeHtml(status)}"><span class="portal-status-pulse" aria-hidden="true"></span><div><h2>System readiness</h2><p>${escapeHtml(statusCopy)}</p></div></div><div class="portal-health-grid">${checks}</div>${maintenanceControls}`;
    const form = target.querySelector('[data-portal-maintenance-form]');
    form?.addEventListener('submit', async (event) => {
      event.preventDefault();
      const button = form.querySelector('button[type="submit"]');
      const mode = form.elements.mode?.value || 'live';
      const reason = String(form.elements.reason?.value || '').trim();
      if (mode === 'maintenance' && !reason) {
        showToast('Enter a reason before putting Portal into maintenance mode.', 'error');
        return;
      }
      setButtonLoading(button, true, 'Saving');
      try {
        const result = await portalApi.postJson('/health/maintenance/', { mode, reason }, tg);
        if (!result.ok || !result.data?.ok) throw new Error(result.data?.error || 'Maintenance mode could not be updated.');
        showToast(mode === 'maintenance' ? 'Portal is now read-only for staff.' : 'Portal is live again.', 'success');
        await renderPortalOperations({ health: true, maintenance: true });
      } catch (error) {
        showToast(error.message || 'Maintenance mode could not be updated.', 'error');
      } finally {
        setButtonLoading(button, false);
      }
    });
  }

  function renderPortalDelegations(target, payload) {
    const delegates = payload.delegates || [];
    const gates = payload.gates || [];
    state.portalDelegationOptions = payload;
    target.innerHTML = `<h2>Temporary approval delegation</h2><p>Business Admins can cover one approval gate temporarily. A reason, exact scope, and expiry are mandatory.</p>
      <form id="portal-delegation-form" class="portal-delegation-form">
        <label>Delegate<select id="portal-delegation-delegate" required><option value="">Choose staff member</option>${delegates.map(item => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.label)}</option>`).join('')}</select></label>
        <label>Approval gate<select id="portal-delegation-gate" required><option value="">Choose approval gate</option>${gates.map(item => `<option value="${escapeHtml(item.value)}">${escapeHtml(item.label)}</option>`).join('')}</select></label>
        <label>Branch<select id="portal-delegation-branch" disabled><option value="">Choose delegate first</option></select></label>
        <label>Expires at<input id="portal-delegation-expiry" type="datetime-local" required value="${delegationDateTimeValue()}" max="${delegationDateTimeValue(14 * 24)}"></label>
        <label class="delegation-reason">Reason<textarea id="portal-delegation-reason" maxlength="2000" required placeholder="For example: annual leave cover"></textarea></label>
        <div class="form-actions"><button id="portal-create-delegation" class="btn btn-primary" type="submit">Grant temporary authority</button></div>
      </form>
      <div class="portal-delegation-list"><h3>Active delegations</h3>${payload.active?.length ? payload.active.map(item => delegationMarkup(item)).join('') : '<p class="portal-delegation-empty">No active temporary delegations.</p>'}</div>
      ${payload.history?.length ? `<details class="history-previous-versions"><summary>Recent expired or revoked delegations</summary><div class="portal-delegation-list">${payload.history.map(item => delegationMarkup(item, true)).join('')}</div></details>` : ''}
    `;
  }

  function populateDelegationBranchChoices() {
    const delegateSelect = el('portal-delegation-delegate');
    const branchSelect = el('portal-delegation-branch');
    if (!delegateSelect || !branchSelect) return;
    const candidate = (state.portalDelegationOptions?.delegates || []).find(item => String(item.id) === String(delegateSelect.value));
    branchSelect.replaceChildren();
    if (!candidate) {
      branchSelect.disabled = true;
      const option = document.createElement('option');
      option.value = '';
      option.textContent = 'Choose delegate first';
      branchSelect.appendChild(option);
      return;
    }
    branchSelect.disabled = false;
    if (candidate.all_branches) {
      const allOption = document.createElement('option');
      allOption.value = '';
      allOption.textContent = 'All branches';
      branchSelect.appendChild(allOption);
    }
    (candidate.branches || []).forEach((branch) => {
      const option = document.createElement('option');
      option.value = branch;
      option.textContent = branch;
      branchSelect.appendChild(option);
    });
    if (!candidate.all_branches && candidate.branches?.length === 1) branchSelect.value = candidate.branches[0];
  }

  async function renderPortalOperations(operations) {
    const target = el('portal-settings-operations');
    if (!target) return;
    target.replaceChildren();
    const tasks = [];
    if (operations?.health) {
      const healthTarget = document.createElement('div');
      healthTarget.className = 'portal-operation-card';
      healthTarget.innerHTML = '<h2>System readiness</h2><p>Checking templates and document storage…</p>';
      target.appendChild(healthTarget);
      tasks.push(apiFetch('/health/').then(({ ok, data }) => {
        if (!ok || !data.ok) throw new Error(data.error || 'System readiness could not be loaded.');
        renderPortalHealth(healthTarget, data, Boolean(operations?.maintenance));
      }).catch(error => { healthTarget.innerHTML = `<div class="portal-readiness-heading status-down"><span class="portal-status-pulse" aria-hidden="true"></span><div><h2>System readiness</h2><p>${escapeHtml(error.message || 'Portal readiness could not be loaded.')}</p></div></div>`; }));
    }
    if (operations?.delegation) {
      const delegationTarget = document.createElement('div');
      delegationTarget.className = 'portal-operation-card';
      delegationTarget.innerHTML = '<h2>Temporary approval delegation</h2><p>Loading current temporary authority…</p>';
      target.appendChild(delegationTarget);
      tasks.push(apiFetch('/settings/delegations/').then(({ ok, data }) => {
        if (!ok || !data.ok) throw new Error(data.error || 'Delegations could not be loaded.');
        renderPortalDelegations(delegationTarget, data.data || {});
      }).catch(error => { delegationTarget.innerHTML = `<h2>Temporary approval delegation</h2><p>${escapeHtml(error.message)}</p>`; }));
    }
    await Promise.all(tasks);
  }

  async function loadPortalSettings(loadOperations = false) {
    const { ok, data } = await apiFetch('/settings/');
    if (!ok || !data.ok) throw new Error(data.error || 'Portal settings could not be loaded.');
    const personal = data.data?.personal || {};
    state.personalPreference = personal;
    state.portalSettings = data.data || {};
    if (utils.renderSettingsAccount) utils.renderSettingsAccount(el('portal-settings-account'), data.data?.account || {});
    if (el('portal-settings-release')) el('portal-settings-release').textContent = data.data?.account?.app_release || 'Current release';
    populatePortalSettingScreens(data.data?.screens || [], personal.default_screen);
    populatePortalSettingSelect('portal-preference-default-queue', data.data?.queues || [], personal.default_filters?.queue, 'Use landing screen');
    populatePortalSettingSelect('portal-preference-default-branch', data.data?.branches || [], personal.default_filters?.branch, 'All permitted branches');
    populatePortalSettingSelect('portal-preference-review-status', data.data?.review_statuses || [], personal.default_filters?.status, 'Final decisions');
    if (el('portal-preference-compact-cards')) el('portal-preference-compact-cards').checked = Boolean(personal.compact_cards);
    document.body.classList.toggle('portal-compact-cards', Boolean(personal.compact_cards));
    applyWorkspaceVisibility();
    if (loadOperations) await renderPortalOperations(data.data?.operations || {});
    return personal;
  }

  function newWorkspaceOpenKey() {
    if (window.crypto?.randomUUID) return window.crypto.randomUUID();
    return 'portal-open-' + Date.now() + '-' + Math.random().toString(36).slice(2);
  }

  function workspaceCaseMarkup(item, { pinAction = false } = {}) {
    const meta = [item.branch, String(item.workflow_state || '').replace(/_/g, ' ')].filter(Boolean).join(' · ');
    const action = pinAction
      ? '<button type="button" class="workspace-toggle-pin" data-farmer-id="' + escapeHtml(item.farmer_id) + '">Unpin</button>'
      : '<button type="button" class="workspace-toggle-pin workspace-primary" data-farmer-id="' + escapeHtml(item.farmer_id) + '">Pin</button>';
    return '<article class="portal-workspace-item"><button type="button" class="portal-workspace-item-main workspace-open-case" data-farmer-id="' + escapeHtml(item.farmer_id) + '"><strong>' + escapeHtml(item.customer_name || 'Unnamed customer') + '</strong><span>' + escapeHtml(meta || 'Open case') + '</span></button><div class="portal-workspace-item-actions">' + action + '</div></article>';
  }

  function workspaceSelectOptions(items, selected, blankLabel) {
    const rows = blankLabel ? [{ key: '', label: blankLabel }, ...(items || [])] : (items || []);
    return rows.map(item => {
      const key = String(item?.key ?? item?.value ?? item ?? '');
      const label = String(item?.label ?? item ?? key);
      return '<option value="' + escapeHtml(key) + '"' + (key === String(selected || '') ? ' selected' : '') + '>' + escapeHtml(label) + '</option>';
    }).join('');
  }

  function workspaceEditFormMarkup(view) {
    const settings = state.portalSettings || {};
    const filters = view.filters || {};
    return '<form class="portal-workspace-edit-form" data-view-id="' + escapeHtml(view.id) + '" hidden>'
      + '<label>View name<input name="name" maxlength="60" required value="' + escapeHtml(view.name) + '"></label>'
      + '<label>Screen<select name="screen">' + workspaceSelectOptions(settings.screens || [], view.screen) + '</select></label>'
      + '<label>Queue<select name="queue">' + workspaceSelectOptions(settings.queues || [], view.queue, 'Use screen') + '</select></label>'
      + '<label>Branch<select name="branch">' + workspaceSelectOptions(settings.branches || [], filters.branch, 'All permitted branches') + '</select></label>'
      + '<label>Review list<select name="status">' + workspaceSelectOptions(settings.review_statuses || [], filters.status, 'Not a review list') + '</select></label>'
      + '<label>Order<select name="ordering">' + workspaceSelectOptions([{ key: 'queue_default', label: 'Queue default' }, { key: 'newest', label: 'Newest first' }], view.ordering) + '</select></label>'
      + '<div class="portal-workspace-edit-actions"><button type="submit" class="workspace-primary">Save view</button><button type="button" class="workspace-cancel-edit">Cancel</button></div>'
      + '</form>';
  }

  function workspaceViewMarkup(view, { settings = false } = {}) {
    const destination = view.queue || view.screen || 'Portal';
    const stateLabel = view.available ? destination.replace(/_/g, ' ') : 'Unavailable';
    const notice = view.available ? '' : '<span>' + escapeHtml(view.unavailable_reason || 'This view is no longer available to your Portal access.') + '</span>';
    let actions = '';
    if (settings) {
      actions = '<button type="button" class="workspace-open-view workspace-primary" data-view-id="' + escapeHtml(view.id) + '"' + (view.available ? '' : ' disabled') + '>Open</button>'
        + '<button type="button" class="workspace-set-startup" data-view-id="' + escapeHtml(view.id) + '"' + (view.available || view.is_startup ? '' : ' disabled') + '>' + (view.is_startup ? 'Startup' : 'Set startup') + '</button>'
        + '<button type="button" class="workspace-edit-view" data-view-id="' + escapeHtml(view.id) + '">Edit</button>'
        + '<button type="button" class="workspace-delete-view" data-view-id="' + escapeHtml(view.id) + '">Delete</button>';
    } else if (view.available) {
      actions = '<button type="button" class="workspace-open-view workspace-primary" data-view-id="' + escapeHtml(view.id) + '">Open</button>';
    }
    return '<article class="portal-workspace-item' + (view.available ? '' : ' is-unavailable') + '"><div class="portal-workspace-item-main"><strong>' + escapeHtml(view.name) + (view.is_startup ? ' · Startup' : '') + '</strong><span>' + escapeHtml(stateLabel) + ' · ' + escapeHtml(view.ordering === 'newest' ? 'Newest first' : 'Queue default') + '</span>' + notice + '</div><div class="portal-workspace-item-actions">' + actions + '</div>' + (settings ? workspaceEditFormMarkup(view) : '') + '</article>';
  }

  function renderPortalWorkspace() {
    if (!canManagePortalWorkspace()) {
      const dashboard = el('portal-workspace-dashboard');
      if (dashboard) dashboard.hidden = true;
      return;
    }
    const workspace = state.workspace;
    if (!workspace) return;
    const dashboard = el('portal-workspace-dashboard');
    const summary = workspace.summary || {};
    if (dashboard) {
      dashboard.hidden = false;
      const defaultCount = summary.default_view_count == null ? '—' : String(summary.default_view_count);
      const summaryTarget = el('portal-workspace-summary');
      if (summaryTarget) {
        summaryTarget.innerHTML = [
          [defaultCount, summary.default_view_label || 'Portal default'],
          [String(summary.overdue_count || 0), 'Overdue visible'],
          [String(summary.pinned_count || 0), 'Pinned cases'],
          [String(summary.recent_count || 0), 'Recent cases'],
        ].map(item => '<div class="portal-workspace-summary-item"><strong>' + escapeHtml(item[0]) + '</strong><span>' + escapeHtml(item[1]) + '</span></div>').join('');
      }
      const pins = workspace.pinned || [];
      const recents = workspace.recent || [];
      const pinTarget = el('portal-workspace-pins');
      const recentTarget = el('portal-workspace-recents');
      const viewTarget = el('portal-workspace-dashboard-views');
      if (pinTarget) pinTarget.innerHTML = pins.length ? pins.map(item => workspaceCaseMarkup(item, { pinAction: true })).join('') : '<p class="portal-workspace-empty">Pin an open case to keep it here.</p>';
      if (recentTarget) recentTarget.innerHTML = recents.length ? recents.map(item => workspaceCaseMarkup(item)).join('') : '<p class="portal-workspace-empty">Recently opened cases appear here.</p>';
      if (viewTarget) {
        const availableViews = (workspace.views || []).filter(view => view.available).slice(0, 3);
        viewTarget.innerHTML = availableViews.length ? availableViews.map(view => workspaceViewMarkup(view)).join('') : '';
      }
    }
    const settingsTarget = el('portal-workspace-saved-views');
    if (settingsTarget) {
      const views = workspace.views || [];
      settingsTarget.innerHTML = views.length ? views.map(view => workspaceViewMarkup(view, { settings: true })).join('') : '<p class="portal-workspace-empty">No saved views yet. Open a queue, choose your filters, then save it here.</p>';
    }
    if (el('portal-workspace-view-order')) el('portal-workspace-view-order').value = state.workspaceOrdering || 'queue_default';
  }

  async function loadPortalWorkspace({ includeSummary = false } = {}) {
    if (!canManagePortalWorkspace()) {
      applyWorkspaceVisibility();
      return null;
    }
    const { ok, data } = await apiFetch(includeSummary ? '/workspace/?summary=1' : '/workspace/');
    if (!ok || !data?.ok) throw new Error(data?.error || 'Workspace could not be loaded.');
    state.workspace = data.data || {};
    renderPortalWorkspace();
    return state.workspace;
  }

  function applyWorkspaceView(view) {
    if (!view?.available) {
      showToast(view?.unavailable_reason || 'This saved view is unavailable.', 'error');
      return;
    }
    state.workspaceOrdering = view.ordering === 'newest' ? 'newest' : 'queue_default';
    state.filters.branch = String(view.filters?.branch || '');
    state.filters.reviewStage = String(view.filters?.status || 'decision');
    const destination = String(view.queue || view.screen || '');
    if (!destination || !hasCapability(PAGE_CAPABILITIES[destination])) {
      showToast('This saved view is no longer available to your Portal access.', 'error');
      return;
    }
    syncFinalReviewStageTabs();
    lastShellScreen = destination;
    switchPage(destination);
    rememberPortalUi();
    loadPage(destination);
  }

  function currentWorkspaceViewPayload() {
    const queue = queueConfig[state.activePage] ? state.activePage : '';
    return {
      name: el('portal-workspace-view-name')?.value || '',
      screen: state.activePage || 'dashboard',
      queue,
      filters: {
        branch: state.filters.branch || '',
        status: state.activePage === 'final' ? state.filters.reviewStage || 'decision' : '',
      },
      ordering: el('portal-workspace-view-order')?.value || state.workspaceOrdering || 'queue_default',
    };
  }

  function appendWorkspacePinControl(farmer) {
    if (!canManagePortalWorkspace()) return;
    const footer = el('sheet-footer');
    if (!footer || !farmer?.id) return;
    footer.querySelector('.workspace-toggle-pin')?.remove();
    const pinned = Boolean((state.workspace?.pinned || []).some(item => String(item.farmer_id) === String(farmer.id)));
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'secondary workspace-toggle-pin';
    button.dataset.farmerId = farmer.id;
    button.textContent = pinned ? 'Unpin case' : 'Pin case';
    footer.prepend(button);
  }
  // Bootstrap
  async function init() {
    configureHtmx();
    await loadMeta();
    try { await loadPortalSettings(); } catch (_) { /* Settings are non-critical to opening the workflow. */ }
    if (canManagePortalWorkspace()) {
      try { await loadPortalWorkspace(); } catch (_) { /* Workspace is optional convenience data. */ }
    }
    window.setInterval(loadMeta, 60000);
    const shellScreen = document.getElementById('portal-screen')?.dataset.screen || 'dashboard';
    const isRootLanding = /\/portal\/?$/.test(window.location.pathname);
    const savedFilters = state.personalPreference?.default_filters || {};
    const startupView = isRootLanding ? state.workspace?.startup_view : null;
    const hasRestoredBranch = Object.prototype.hasOwnProperty.call(restoredPortalUi, 'branch');
    const hasRestoredReviewStage = Object.prototype.hasOwnProperty.call(restoredPortalUi, 'reviewStage');
    const workspaceFilters = startupView?.filters || {};
    if (startupView) state.workspaceOrdering = startupView.ordering === 'newest' ? 'newest' : 'queue_default';
    if (isRootLanding && !hasRestoredBranch && (workspaceFilters.branch || savedFilters.branch)) {
      state.filters.branch = workspaceFilters.branch || savedFilters.branch;
    }
    if (isRootLanding && !hasRestoredReviewStage && ['decision', 'payment'].includes(workspaceFilters.status || savedFilters.status)) {
      state.filters.reviewStage = workspaceFilters.status || savedFilters.status;
    }
    syncFinalReviewStageTabs();
    const savedQueue = isRootLanding ? String(startupView?.queue || savedFilters.queue || '') : '';
    const requestedPage = savedQueue && hasCapability(PAGE_CAPABILITIES[savedQueue])
      ? savedQueue
      : (isRootLanding && (startupView?.screen || state.personalPreference?.default_screen)
        ? (startupView?.screen || state.personalPreference.default_screen)
        : (shellScreen === 'dashboard' && restoredPortalUi.activePage ? restoredPortalUi.activePage : shellScreen));
    const initialPage = hasCapability(PAGE_CAPABILITIES[requestedPage]) ? requestedPage : firstPermittedPage();
    if (!initialPage) {
      document.getElementById('portal-screen').innerHTML = '<section class="shell-error" role="alert"><h2>Access not configured</h2><p>Ask an administrator to assign a Portal role and capability.</p></section>';
      return;
    }
    lastShellScreen = initialPage;
    switchPage(initialPage);
    loadPage(initialPage);
    if (window.lucide) {
      window.lucide.createIcons();
    }
  }

  function updateBatchPanel() {
    if (portalRequisitions.updateBatchPanel) {
      portalRequisitions.updateBatchPanel();
    }
  }

  document.addEventListener('click', event => {
    const dormantWorkspaceControl = event.target.closest(
      '[data-portal-workspace], .workspace-manage, .workspace-clear-recents, '
      + '.workspace-open-case, .workspace-toggle-pin, .workspace-open-view, '
      + '.workspace-set-startup, .workspace-edit-view, .workspace-cancel-edit, '
      + '.workspace-delete-view'
    );
    if (dormantWorkspaceControl && !PORTAL_WORKSPACE_UI_ENABLED) {
      event.preventDefault();
      return;
    }
    const manageWorkspaceButton = event.target.closest('.workspace-manage');
    if (manageWorkspaceButton) {
      event.preventDefault();
      if (!canManagePortalWorkspace()) return;
      switchPage('settings');
      loadPortalSettings(true).then(() => loadPortalWorkspace()).catch(error => showToast(error.message || 'Could not open workspace settings.', 'error'));
      return;
    }
    const clearRecentsButton = event.target.closest('.workspace-clear-recents');
    if (clearRecentsButton) {
      event.preventDefault();
      setButtonLoading(clearRecentsButton, true, 'Clearing');
      portalApi.postJson('/workspace/recents/clear/', {}, tg)
        .then(result => {
          if (!result.ok || !result.data?.ok) throw new Error(result.data?.error || 'Could not clear recently opened cases.');
          return loadPortalWorkspace();
        })
        .then(() => showToast('Recently opened cases were cleared from this workspace.', 'success'))
        .catch(error => showToast(error.message || 'Could not clear recently opened cases.', 'error'))
        .finally(() => setButtonLoading(clearRecentsButton, false));
      return;
    }
    const openWorkspaceCaseButton = event.target.closest('.workspace-open-case');
    if (openWorkspaceCaseButton) {
      event.preventDefault();
      openCurrentFarmerSheet({ id: openWorkspaceCaseButton.dataset.farmerId }, null);
      return;
    }
    const pinWorkspaceCaseButton = event.target.closest('.workspace-toggle-pin');
    if (pinWorkspaceCaseButton) {
      event.preventDefault();
      const farmerId = pinWorkspaceCaseButton.dataset.farmerId || '';
      const currentlyPinned = Boolean((state.workspace?.pinned || []).some(item => String(item.farmer_id) === String(farmerId)));
      setButtonLoading(pinWorkspaceCaseButton, true, currentlyPinned ? 'Unpinning' : 'Pinning');
      portalApi.postJson(`/workspace/cases/${encodeURIComponent(farmerId)}/${currentlyPinned ? 'unpin' : 'pin'}/`, {}, tg)
        .then(result => {
          if (!result.ok || !result.data?.ok) throw new Error(result.data?.error || 'Could not update the case pin.');
          return loadPortalWorkspace();
        })
        .then(() => {
          pinWorkspaceCaseButton.textContent = currentlyPinned ? 'Pin case' : 'Unpin case';
          showToast(currentlyPinned ? 'Case unpinned.' : 'Case pinned.', 'success');
        })
        .catch(error => showToast(error.message || 'Could not update the case pin.', 'error'))
        .finally(() => setButtonLoading(pinWorkspaceCaseButton, false));
      return;
    }
    const openWorkspaceViewButton = event.target.closest('.workspace-open-view');
    if (openWorkspaceViewButton) {
      event.preventDefault();
      setButtonLoading(openWorkspaceViewButton, true, 'Opening');
      portalApi.postJson(`/workspace/views/${encodeURIComponent(openWorkspaceViewButton.dataset.viewId || '')}/activate/`, {}, tg)
        .then(result => {
          if (!result.ok || !result.data?.ok) throw new Error(result.data?.error || 'Could not open this saved view.');
          applyWorkspaceView(result.data.data);
          return loadPortalWorkspace();
        })
        .catch(error => showToast(error.message || 'Could not open this saved view.', 'error'))
        .finally(() => setButtonLoading(openWorkspaceViewButton, false));
      return;
    }
    const startupWorkspaceViewButton = event.target.closest('.workspace-set-startup');
    if (startupWorkspaceViewButton) {
      event.preventDefault();
      setButtonLoading(startupWorkspaceViewButton, true, 'Saving');
      portalApi.postJson(`/workspace/views/${encodeURIComponent(startupWorkspaceViewButton.dataset.viewId || '')}/startup/`, {}, tg)
        .then(result => {
          if (!result.ok || !result.data?.ok) throw new Error(result.data?.error || 'Could not set the startup view.');
          return loadPortalWorkspace();
        })
        .then(() => showToast('Portal startup view updated.', 'success'))
        .catch(error => showToast(error.message || 'Could not set the startup view.', 'error'))
        .finally(() => setButtonLoading(startupWorkspaceViewButton, false));
      return;
    }
    const editWorkspaceViewButton = event.target.closest('.workspace-edit-view');
    if (editWorkspaceViewButton) {
      event.preventDefault();
      const card = editWorkspaceViewButton.closest('.portal-workspace-item');
      const form = card?.querySelector('.portal-workspace-edit-form');
      if (!form) return;
      document.querySelectorAll('.portal-workspace-edit-form').forEach(other => {
        if (other !== form) other.hidden = true;
      });
      form.hidden = !form.hidden;
      editWorkspaceViewButton.textContent = form.hidden ? 'Edit' : 'Close edit';
      return;
    }
    const cancelWorkspaceEditButton = event.target.closest('.workspace-cancel-edit');
    if (cancelWorkspaceEditButton) {
      event.preventDefault();
      const form = cancelWorkspaceEditButton.closest('.portal-workspace-edit-form');
      if (form) form.hidden = true;
      const card = cancelWorkspaceEditButton.closest('.portal-workspace-item');
      const editButton = card?.querySelector('.workspace-edit-view');
      if (editButton) editButton.textContent = 'Edit';
      return;
    }
    const deleteWorkspaceViewButton = event.target.closest('.workspace-delete-view');
    if (deleteWorkspaceViewButton) {
      event.preventDefault();
      if (!window.confirm('Delete this personal saved view?')) return;
      setButtonLoading(deleteWorkspaceViewButton, true, 'Deleting');
      apiFetch(`/workspace/views/${encodeURIComponent(deleteWorkspaceViewButton.dataset.viewId || '')}/`, { method: 'DELETE' })
        .then(result => {
          if (!result.ok || !result.data?.ok) throw new Error(result.data?.error || 'Could not delete this saved view.');
          return loadPortalWorkspace();
        }).then(() => showToast('Saved view deleted.', 'success'))
        .catch(error => showToast(error.message || 'Could not delete this saved view.', 'error'))
        .finally(() => setButtonLoading(deleteWorkspaceViewButton, false));
      return;
    }
    const openCaseHistoryButton = event.target.closest('.case-history-open');
    if (openCaseHistoryButton) {
      event.preventDefault();
      window.location.assign(caseHistoryUrl(openCaseHistoryButton.dataset.farmerId));
      return;
    }
    if (event.target.closest('#case-history-back')) {
      event.preventDefault();
      window.history.pushState({ screen: 'case_history' }, '', caseHistoryUrl());
      showCaseHistorySearch();
      return;
    }
    const kindButton = event.target.closest('.history-kind');
    if (kindButton) {
      event.preventDefault();
      loadHistory(kindButton.dataset.kind || 'orders');
      return;
    }
    const excelButton = event.target.closest('.history-open-excel');
    if (excelButton) {
      event.preventDefault();
      // This handler lives in the portal shell, not the requisitions module;
      // using the module's `deps` here throws before the link can open.
      openPortalLink(excelButton.dataset.url || '');
      return;
    }
    const signedScanButton = event.target.closest('.history-open-signed-scan');
    if (signedScanButton) {
      event.preventDefault();
      openPortalLink(signedScanButton.dataset.url || '');
      return;
    }
    const uploadSignedScanButton = event.target.closest('.history-upload-signed-scan');
    if (uploadSignedScanButton) {
      event.preventDefault();
      const card = uploadSignedScanButton.closest('.history-document-card');
      const file = card?.querySelector('.history-signed-scan')?.files?.[0];
      const attested = Boolean(card?.querySelector('.history-signoff-attest')?.checked);
      if (!file || !attested) {
        showToast('Choose the signed scan and confirm that it is complete, signed, stamped, readable, and matches this document version.', 'error');
        return;
      }
      const formData = new FormData();
      formData.append('signed_scan', file);
      formData.append('attested_complete', 'true');
      setButtonLoading(uploadSignedScanButton, true, 'Uploading...');
      portalApi.postForm(
        `/document-signoffs/${encodeURIComponent(uploadSignedScanButton.dataset.documentType || '')}/${encodeURIComponent(uploadSignedScanButton.dataset.documentId || '')}/upload/`,
        formData,
        tg,
      ).then(async result => {
        if (!result.ok && !result.data?.pending_retry) throw new Error(result.data?.error || 'Could not store the signed scan.');
        showToast(result.data?.pending_retry ? 'Signed scan retained; its Drive upload needs a retry.' : 'Signed and stamped scan retained.', result.data?.pending_retry ? 'error' : 'success');
        await loadHistory(historyKind);
      }).catch(error => showToast(error.message || 'Could not store the signed scan.', 'error'))
        .finally(() => setButtonLoading(uploadSignedScanButton, false));
      return;
    }
    const retrySignedScanButton = event.target.closest('.history-retry-signed-scan');
    if (retrySignedScanButton) {
      event.preventDefault();
      setButtonLoading(retrySignedScanButton, true, 'Retrying...');
      portalApi.postForm(
        `/document-signoffs/${encodeURIComponent(retrySignedScanButton.dataset.signoffId || '')}/retry/`,
        new FormData(),
        tg,
      ).then(async result => {
        if (!result.ok && !result.data?.pending_retry) throw new Error(result.data?.error || 'Could not retry the signed scan upload.');
        showToast(result.data?.pending_retry ? 'Drive still unavailable; the signed scan remains retained for retry.' : 'Signed scan uploaded and approved.', result.data?.pending_retry ? 'error' : 'success');
        await loadHistory(historyKind);
      }).catch(error => showToast(error.message || 'Could not retry the signed scan upload.', 'error'))
        .finally(() => setButtonLoading(retrySignedScanButton, false));
      return;
    }
    const regenerateOrderButton = event.target.closest('.history-regenerate-order');
    if (regenerateOrderButton) {
      event.preventDefault();
      portalRequisitions.regenerateOrderHistory?.(
        regenerateOrderButton.dataset.order || '',
        String(regenerateOrderButton.dataset.farmerIds || '').split(',').filter(Boolean),
        regenerateOrderButton.dataset.requisitionDate || '',
        regenerateOrderButton,
      );
      return;
    }
    const regeneratePaymentButton = event.target.closest('.history-regenerate-payment');
    if (regeneratePaymentButton) {
      event.preventDefault();
      portalRequisitions.regeneratePaymentHistory?.(
        regeneratePaymentButton.dataset.id || '',
        regeneratePaymentButton,
      );
      return;
    }
    const viewButton = event.target.closest('.history-view-document');
    if (!viewButton) return;
    event.preventDefault();
    if (viewButton.dataset.kind === 'payments') portalRequisitions.openFinalPaymentHistory?.(viewButton.dataset.id);
    else portalRequisitions.openFinalOrderHistory?.(viewButton.dataset.order);
  });
  let jblSearchTimer;
  el('jbl-search')?.addEventListener('input', e => {
    clearTimeout(jblSearchTimer);
    state.jblSearch = e.target.value.trim();
    rememberPortalUi();
    jblSearchTimer = setTimeout(() => loadQueue('jbl', 1), 350);
  });
  el('jbl-search-clear')?.addEventListener('click', () => {
    state.jblSearch = '';
    rememberPortalUi();
    if (el('jbl-search')) el('jbl-search').value = '';
    loadQueue('jbl', 1);
  });

  document.addEventListener('click', event => {
    const reviewTab = event.target.closest('[data-final-review-stage]');
    if (!reviewTab) return;
    event.preventDefault();
    selectFinalReviewStage(reviewTab.dataset.finalReviewStage);
  });

  // The filter module deliberately owns filtering mechanics. Persisting this
  // harmless view context here keeps all Portal navigation state in one place.
  document.addEventListener('change', event => {
    if (event.target.matches('#filter-county, #filter-branch')) {
      window.setTimeout(rememberPortalUi, 0);
    }
    if (event.target.matches('#portal-preference-compact-cards')) {
      document.body.classList.toggle('portal-compact-cards', Boolean(event.target.checked));
    }
    if (event.target.matches('#portal-delegation-delegate')) {
      populateDelegationBranchChoices();
    }
  });

  document.addEventListener('click', event => {
    if (!event.target.matches('#portal-clear-personal-settings')) return;
    event.preventDefault();
    const button = event.target;
    setButtonLoading(button, true, 'Clearing');
    portalApi.postJson('/settings/', {
      preferences: {
        default_screen: '',
        default_filters: {},
        compact_cards: false,
      },
    }, tg).then((result) => {
      if (!result.ok || !result.data?.ok) throw new Error(result.data?.error || 'Could not clear Portal defaults.');
      state.personalPreference = result.data.data || null;
      document.body.classList.remove('portal-compact-cards');
      return loadPortalSettings(true);
    }).then(() => showToast('Your Portal defaults were cleared.', 'success'))
      .catch((error) => showToast(error.message, 'error'))
      .finally(() => setButtonLoading(button, false));
  });

  document.addEventListener('submit', event => {
    if (!PORTAL_WORKSPACE_UI_ENABLED && (
      event.target.matches('.portal-workspace-edit-form')
      || event.target.matches('#portal-workspace-save-view-form')
    )) {
      event.preventDefault();
      return;
    }
    if (event.target.matches('.portal-workspace-edit-form')) {
      event.preventDefault();
      const form = event.target;
      const button = form.querySelector('button[type="submit"]');
      const payload = {
        name: form.elements.name?.value || '',
        screen: form.elements.screen?.value || '',
        queue: form.elements.queue?.value || '',
        filters: {
          branch: form.elements.branch?.value || '',
          status: form.elements.status?.value || '',
        },
        ordering: form.elements.ordering?.value || 'queue_default',
      };
      setButtonLoading(button, true, 'Saving');
      apiFetch(`/workspace/views/${encodeURIComponent(form.dataset.viewId || '')}/`, {
        method: 'PATCH', body: JSON.stringify(payload),
      }).then(result => {
        if (!result.ok || !result.data?.ok) throw new Error(result.data?.error || 'Could not update this saved view.');
        return loadPortalWorkspace();
      }).then(() => showToast('Saved view updated.', 'success'))
        .catch(error => showToast(error.message || 'Could not update this saved view.', 'error'))
        .finally(() => setButtonLoading(button, false));
      return;
    }
    if (event.target.matches('#portal-workspace-save-view-form')) {
      event.preventDefault();
      const button = el('portal-workspace-save-view');
      const payload = currentWorkspaceViewPayload();
      setButtonLoading(button, true, 'Saving');
      portalApi.postJson('/workspace/views/', payload, tg).then(result => {
        if (!result.ok || !result.data?.ok) throw new Error(result.data?.error || 'Could not save this Portal view.');
        if (el('portal-workspace-view-name')) el('portal-workspace-view-name').value = '';
        state.workspaceOrdering = payload.ordering === 'newest' ? 'newest' : 'queue_default';
        return loadPortalWorkspace();
      }).then(() => showToast('Personal Portal view saved.', 'success'))
        .catch(error => showToast(error.message || 'Could not save this Portal view.', 'error'))
        .finally(() => setButtonLoading(button, false));
      return;
    }
    if (event.target.matches('#portal-personal-settings-form')) {
      event.preventDefault();
      const button = el('portal-save-personal-settings');
      setButtonLoading(button, true, 'Saving');
      portalApi.postJson('/settings/', {
        preferences: {
          default_screen: el('portal-preference-default-screen')?.value || '',
          default_filters: {
            queue: el('portal-preference-default-queue')?.value || '',
            branch: el('portal-preference-default-branch')?.value || '',
            status: el('portal-preference-review-status')?.value || '',
          },
          compact_cards: Boolean(el('portal-preference-compact-cards')?.checked),
        },
      }, tg).then((result) => {
        if (!result.ok || !result.data?.ok) throw new Error(result.data?.error || 'Could not save Portal settings.');
        state.personalPreference = result.data.data || null;
        document.body.classList.toggle('portal-compact-cards', Boolean(state.personalPreference?.compact_cards));
        showToast('Your Portal settings were saved.', 'success');
      }).catch((error) => showToast(error.message, 'error')).finally(() => setButtonLoading(button, false));
      return;
    }
    if (event.target.matches('#portal-delegation-form')) {
      event.preventDefault();
      const button = el('portal-create-delegation');
      setButtonLoading(button, true, 'Granting');
      portalApi.postJson('/settings/delegations/', {
        delegate_id: el('portal-delegation-delegate')?.value || '',
        gate: el('portal-delegation-gate')?.value || '',
        branch: el('portal-delegation-branch')?.value || '',
        expires_at: el('portal-delegation-expiry')?.value || '',
        reason: el('portal-delegation-reason')?.value || '',
      }, tg).then((result) => {
        if (!result.ok || !result.data?.ok) throw new Error(result.data?.error || 'Could not grant temporary authority.');
        return loadPortalSettings(true);
      }).then(() => showToast('Temporary approval authority was granted and audit-logged.', 'success'))
        .catch((error) => showToast(error.message, 'error'))
        .finally(() => setButtonLoading(button, false));
      return;
    }
    if (event.target.matches('.portal-delegation-revoke-form')) {
      event.preventDefault();
      const form = event.target;
      const button = form.querySelector('button[type="submit"]');
      const reason = form.querySelector('[name="reason"]')?.value || '';
      setButtonLoading(button, true, 'Revoking');
      portalApi.postJson(`/settings/delegations/${encodeURIComponent(form.dataset.delegationId || '')}/revoke/`, { reason }, tg).then((result) => {
        if (!result.ok || !result.data?.ok) throw new Error(result.data?.error || 'Could not revoke temporary authority.');
        return loadPortalSettings(true);
      }).then(() => showToast('Temporary approval authority was revoked and audit-logged.', 'success'))
        .catch((error) => showToast(error.message, 'error'))
        .finally(() => setButtonLoading(button, false));
      return;
    }
    if (!event.target.matches('#case-history-search-form')) return;
    event.preventDefault();
    searchCaseHistory(el('case-history-search')?.value);
  });

  window.PortalAppShell = {
    activate(page) {
      if (!page) return;
      const changed = lastShellScreen !== page;
      lastShellScreen = page;
      switchPage(page);
      if (changed) loadPage(page);
      if (window.lucide) window.lucide.createIcons();
    },
    openCaseHistory(farmerId) {
      portalFarmerSheet.closeSheet?.();
      window.location.assign(caseHistoryUrl(farmerId));
    },
  };

  function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
      const cookies = document.cookie.split(';');
      for (let i = 0; i < cookies.length; i++) {
        const cookie = cookies[i].trim();
        if (cookie.substring(0, name.length + 1) === (name + '=')) {
          cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
          break;
        }
      }
    }
    return cookieValue;
  }
  if (portalFarmerSheet.init) {
    portalFarmerSheet.init({
      apiFetch,
      el,
      escapeHtml,
      fmt,
      fmtDate,
      getCookie,
      loadDashboard,
      locationText,
      openAssignedOrder,
      openPortalLink,
      portalApi,
      reloadCurrentQueue,
      setButtonLoading,
      showToast,
      state,
      tg,
    });
  }
  if (portalFilters.init) {
    portalFilters.init({
      applyFilters,
      creditBadge,
      el,
      escapeHtml,
      fmt,
      fmtDate,
      jblBadge,
      loadQueue,
      locationText,
      openFarmerSheet,
      openCurrentFarmerSheet,
      openPaymentReviewDocument,
      queueConfig,
      renderQueueFragment,
      stageBadge,
      state,
      updateBatchPanel,
    });
  }
  if (portalRequisitions.init) {
    portalRequisitions.init({
      apiFetch,
      batchClientRows,
      el,
      escapeHtml,
      fmtDate,
      getCookie,
      loadHistory,
      loadQueue,
      openPortalLink,
      portalApi,
      portalHelpers,
      renderWarnings,
      setButtonLoading,
      showToast,
      state,
      summaryGrid,
      tg,
      updateConnectionBanner,
    });
  }
  if (portalInvoices.init) {
    portalInvoices.init({
      apiFetch,
      el,
      escapeHtml,
      fmtDate,
      getCookie,
      locationText,
      openPortalLink,
      portalApi,
      setButtonLoading,
      showToast,
      state,
      summaryGrid,
      tg,
    });
  }
  if (portalPayments.init) {
    portalPayments.init({
      apiFetch,
      el,
      escapeHtml,
      getCookie,
      openPortalLink,
      portalApi,
      requisitions: portalRequisitions,
      setButtonLoading,
      showToast,
      state,
      tg,
    });
  }

  updateConnectionBanner();
  init();

})();
