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
  const tg = utils.initTelegram ? utils.initTelegram({ closingConfirmation: false }) : window.Telegram?.WebApp;
  if (tg && !utils.initTelegram) {
    tg.ready();
    tg.expand();
  }
  // State
  let state = {
    activePage: 'dashboard',
    counts: {},
    queues: { jbl: [], credit: [], final: [], requisition: [], deferred: [], all: [], batches: [] },
    pagination: {},
    pages: { jbl: 1, credit: 1, final: 1, requisition: 1, deferred: 1, all: 1, batches: 1 },
    search: '',
    metaStatuses: [],
    metaDecisions: [],
    metaImabOptions: [],
    metaFinalDecisions: [],
    selectedFarmer: null,
    activeMode: null, // 'jbl_visit' | 'credit' | 'final_review' | 'requisition'
    filters: { county: '', branch: '' },
    selectedRequisitions: new Set(),
    pendingRequisitionPayload: null
  };

  // Helpers
  function el(id) { return document.getElementById(id); }

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
    const res = await fetch(apiBase() + path, { ...opts, headers });
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
    const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    const month = months[d.getMonth()];
    const year = d.getFullYear();
    return `${day}-${month}-${year}`;
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
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.toggle('active', b.dataset.page === page));

    if (page !== 'requisition') {
      state.selectedRequisitions.clear();
      updateBatchPanel();
    }

    // Show filter bar on farmer list views.
    const filterBar = el('portal-filter-bar');
    if (filterBar) {
      if (page === 'dashboard' || page === 'batches') {
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
    const { ok, data } = await apiFetch('/dashboard/');
    if (!ok) {
      loading.innerHTML = '<strong>Dashboard unavailable</strong><span>Check your Telegram access, then refresh.</span>';
      loading.setAttribute('aria-busy', 'false');
      loading.style.display = 'block';
      return;
    }
    loading.setAttribute('aria-busy', 'false');
    loading.style.display = 'none';
    state.counts = data.counts || {};
    renderDashboard();
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
    jbl: { endpoint: '/jbl-queue/', fragmentEndpoint: '/queues/jbl/fragment/', listId: 'jbl-list', pageKey: 'jbl', mode: 'jbl_visit', emptyTitle: 'All caught up!', emptySub: 'No farmers are waiting for a JBL visit.' },
    credit: { endpoint: '/credit-queue/', fragmentEndpoint: '/queues/credit/fragment/', listId: 'credit-list', pageKey: 'credit', mode: 'credit', emptyTitle: 'No BRO analysis cases', emptySub: 'No farmers are awaiting BRO credit analysis.' },
    final: { endpoint: '/final-review-queue/', fragmentEndpoint: '/queues/final/fragment/', listId: 'final-list', pageKey: 'final', mode: 'final_review', emptyTitle: 'No final review cases', emptySub: 'No clients are awaiting Head of Rural review.' },
    requisition: { endpoint: '/requisition-queue/', fragmentEndpoint: '/queues/requisition/fragment/', listId: 'req-list', pageKey: 'requisition', mode: 'requisition', emptyTitle: 'No approved cases', emptySub: 'No credit-approved farmers are awaiting an order number.' },
    deferred: { endpoint: '/deferred/', fragmentEndpoint: '/queues/deferred/fragment/', listId: 'deferred-list', pageKey: 'deferred', mode: null, emptyTitle: 'No deferred cases', emptySub: 'No farmers are deferred or flagged.' },
    all: { endpoint: '/farmers/', fragmentEndpoint: '/queues/all/fragment/', listId: 'all-list', pageKey: 'all', mode: null, emptyTitle: 'No farmers found', emptySub: 'Try a different search term.' },
    batches: { endpoint: '/requisition-batches/', fragmentEndpoint: '/requisition-batches/fragment/', listId: 'batches-list', pageKey: 'batches', mode: null, emptyTitle: 'No batches found', emptySub: 'No requisition batches have been generated yet.' },
  };

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
    listEl.innerHTML = '<div class="empty-state"><div class="spinner-inline"></div></div>';

    const url = portalQueues.queueUrl ? portalQueues.queueUrl(qKey, page, state) : cfg.endpoint + '?page=' + page;

    const { ok, data } = await apiFetch(url);
    if (!ok) { listEl.innerHTML = `<div class="empty-state"><div class="es-icon">!</div><div class="es-title">Error loading queue</div></div>`; return; }

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
          const response = await fetch(apiBase() + path, { headers: initDataHeader() });
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
      card.querySelector('.farmer-card-checkbox')?.addEventListener('change', event => {
        event.stopPropagation();
        const id = event.target.dataset.id;
        if (event.target.checked) state.selectedRequisitions.add(id);
        else state.selectedRequisitions.delete(id);
        updateBatchPanel();
      });
      card.addEventListener('click', async () => {
        const id = card.dataset.farmerId;
        const { ok, data } = await apiFetch('/farmers/' + encodeURIComponent(id) + '/');
        if (!ok || !data.ok) {
          showToast(data.error || 'Could not load farmer details.', 'error');
          return;
        }
        openFarmerSheet(data.farmer, card.dataset.mode || null);
      });
    });
  }

  function hydrateHtmxBatchCards(root) {
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
      const fileBadge = (b.drive_url || b.has_requisition_file) ? '<span class="badge badge-green">Form saved</span>' : '<span class="badge badge-grey">No saved form</span>';
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
                ${escapeHtml(b.requisition_date || 'No date')} - ${farmerCount} client(s)
                <span class="badge ${invoiceColor}" style="margin-left:4px;">${invoiceProgress}</span>
                ${fileBadge}
              </div>
              ${b.generated_by ? `<div class="fc-sub">Generated by ${escapeHtml(b.generated_by)}</div>` : ''}
            </div>
            <div style="display:flex;gap:8px;flex-wrap:wrap;">
              <button class="btn btn-secondary btn-view-batch" data-order="${escapeHtml(b.order_number)}">View</button>
              <button class="btn btn-primary btn-download-batch" data-url="${escapeHtml(b.drive_url || b.download_url || '')}" ${(b.drive_url || b.download_url) ? '' : 'disabled'}>Open Form</button>
              <button class="btn btn-secondary btn-upload-invoices" data-order="${escapeHtml(b.order_number)}">Upload Invoices</button>
            </div>
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

  async function openBatchDetail(orderNumber) {
    if (portalRequisitions.openBatchDetail) {
      return portalRequisitions.openBatchDetail(orderNumber);
    }
  }


  function renderFarmerList(listEl, farmers, cfg, qKey) {
    if (!farmers.length) {
      listEl.innerHTML = `<div class="empty-state"><div class="es-icon">OK</div><div class="es-title">${cfg.emptyTitle}</div><div class="es-sub">${cfg.emptySub}</div></div>`;
      return;
    }
    listEl.innerHTML = farmers.map((f, i) => `
      <div class="farmer-card${qKey === 'requisition' ? ' requisition-card' : ''}" data-qkey="${qKey}" data-idx="${i}" id="fc-${qKey}-${i}">
        ${qKey === 'requisition' ? `
          <input type="checkbox" class="farmer-card-checkbox" data-id="${f.id}" ${state.selectedRequisitions.has(f.id) ? 'checked' : ''} onclick="event.stopPropagation();">
        ` : ''}
        <div style="flex: 1;">
          <div class="fc-name">${f.customer_name || f.national_id || f.primary_phone || 'Unknown'}</div>
          <div class="fc-sub">${fmt(f.county)}${f.sub_county ? ' | ' + f.sub_county : ''}${f.branch ? ' | ' + f.branch : ''}</div>
          <div class="fc-sub">${f.primary_phone || ''}</div>
          ${qKey === 'jbl' && f.sign_date ? `<div class="fc-sub fc-visit-date">HB visit: ${escapeHtml(fmtDate(f.sign_date))}</div>` : ''}
          <div class="fc-badges">
            ${stageBadge(f)}
            ${jblBadge(f)}
            ${creditBadge(f)}
            ${f.order_number ? `<span class="badge badge-green">Order: ${f.order_number}</span>` : ''}
          </div>
        </div>
      </div>
    `).join('');

    listEl.querySelectorAll('.farmer-card').forEach(card => {
      card.addEventListener('click', () => {
        const qKey = card.dataset.qkey;
        const idx = parseInt(card.dataset.idx, 10);
        const farmer = state.queues[qKey][idx];
        openFarmerSheet(farmer, cfg.mode);
      });
    });

    if (qKey === 'requisition') {
      listEl.querySelectorAll('.farmer-card-checkbox').forEach(cb => {
        cb.addEventListener('change', () => {
          const id = cb.dataset.id;
          if (cb.checked) {
            state.selectedRequisitions.add(id);
          } else {
            state.selectedRequisitions.delete(id);
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
    }
  }

  function reloadCurrentQueue() {
    const p = state.activePage;
    if (queueConfig[p]) loadQueue(p, state.pages[p] || 1);
  }
  // Search (All Cases tab)
  let searchTimer;
  el('all-search')?.addEventListener('input', e => {
    clearTimeout(searchTimer);
    state.search = e.target.value.trim();
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
  }
  // Page router
  function loadPage(page) {
    if (page === 'dashboard') loadDashboard();
    else if (queueConfig[page]) loadQueue(page, 1);
  }
  // Bootstrap
  async function init() {
    configureHtmx();
    await loadMeta();
    switchPage('dashboard');
    loadDashboard();
    if (window.lucide) {
      window.lucide.createIcons();
    }
  }

  function updateBatchPanel() {
    if (portalRequisitions.updateBatchPanel) {
      portalRequisitions.updateBatchPanel();
    }
  }

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
      openFarmerSheet,
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
      getCookie,
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

  updateConnectionBanner();
  init();

})();
