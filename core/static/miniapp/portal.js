// portal.js - JBL Pipeline Portal Mini App

(() => {
  'use strict';
  // Init Telegram Web App
  const utils = window.MiniAppUtils || {};
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

  let mapInstance = null;
  let mapMarker = null;
  // Helpers
  function el(id) { return document.getElementById(id); }

  function apiBase() { return '/api/portal'; }

  function initDataHeader() {
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

  function fmt(v) { return v || '-'; }
  function fmtDate(v) {
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
    const stage = farmer.pipeline_stage || 1;
    const labels = ['-', 'Awaiting JBL', 'JBL Visited', 'Credit Set', 'Ordered', '', '', 'Invoiced'];
    const styles = ['', 'badge-grey', 'badge-blue', 'badge-orange', 'badge-green', '', '', 'badge-green'];
    return `<span class="badge ${styles[stage] || ''}">${labels[stage] || 'Stage ' + stage}</span>`;
  }

  function creditBadge(farmer) {
    if (!farmer.credit_decision) return '';
    const map = { Approved: 'badge-green', Rejected: 'badge-red', Deferred: 'badge-orange', Pending: 'badge-grey', 'Exemption Approved': 'badge-green' };
    return `<span class="badge ${map[farmer.credit_decision] || 'badge-grey'}">${farmer.credit_decision}</span>`;
  }

  function finalDecisionBadge(farmer) {
    if (!farmer.final_decision) return '';
    const map = { Approved: 'badge-green', Rejected: 'badge-red', Deferred: 'badge-orange', 'Under Review': 'badge-blue' };
    return `<span class="badge ${map[farmer.final_decision] || 'badge-grey'}">Final: ${farmer.final_decision}</span>`;
  }

  function jblBadge(farmer) {
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
  const queueConfig = {
    jbl: { endpoint: '/jbl-queue/', fragmentEndpoint: '/queues/jbl/fragment/', listId: 'jbl-list', pageKey: 'jbl', mode: 'jbl_visit', emptyTitle: 'All caught up!', emptySub: 'No farmers are waiting for a JBL visit.' },
    credit: { endpoint: '/credit-queue/', fragmentEndpoint: '/queues/credit/fragment/', listId: 'credit-list', pageKey: 'credit', mode: 'credit', emptyTitle: 'No BRO analysis cases', emptySub: 'No farmers are awaiting BRO credit analysis.' },
    final: { endpoint: '/final-review-queue/', fragmentEndpoint: '/queues/final/fragment/', listId: 'final-list', pageKey: 'final', mode: 'final_review', emptyTitle: 'No final review cases', emptySub: 'No clients are awaiting Head of Rural review.' },
    requisition: { endpoint: '/requisition-queue/', fragmentEndpoint: '/queues/requisition/fragment/', listId: 'req-list', pageKey: 'requisition', mode: 'requisition', emptyTitle: 'No approved cases', emptySub: 'No credit-approved farmers are awaiting an order number.' },
    deferred: { endpoint: '/deferred/', fragmentEndpoint: '/queues/deferred/fragment/', listId: 'deferred-list', pageKey: 'deferred', mode: null, emptyTitle: 'No deferred cases', emptySub: 'No farmers are deferred or flagged.' },
    all: { endpoint: '/farmers/', fragmentEndpoint: '/queues/all/fragment/', listId: 'all-list', pageKey: 'all', mode: null, emptyTitle: 'No farmers found', emptySub: 'Try a different search term.' },
    batches: { endpoint: '/requisition-batches/', fragmentEndpoint: '/requisition-batches/fragment/', listId: 'batches-list', pageKey: 'batches', mode: null, emptyTitle: 'No batches found', emptySub: 'No requisition batches have been generated yet.' },
  };

  function queueKeyForList(listId) {
    if (!listId) return null;
    const entry = Object.entries(queueConfig).find(([, cfg]) => cfg.listId === listId && cfg.fragmentEndpoint);
    return entry ? entry[0] : null;
  }

  async function loadQueue(qKey, page = 1) {
    const cfg = queueConfig[qKey];
    if (!cfg) return;
    const listEl = el(cfg.listId);
    listEl.innerHTML = '<div class="empty-state"><div class="spinner-inline"></div></div>';

    let url = cfg.endpoint + '?page=' + page;
    if (qKey === 'all') {
      const searchVal = state.search || '';
      if (searchVal) url += '&search=' + encodeURIComponent(searchVal);
      if (state.filters.county) url += '&county=' + encodeURIComponent(state.filters.county);
      if (state.filters.branch) url += '&branch=' + encodeURIComponent(state.filters.branch);
    } else if (cfg.fragmentEndpoint) {
      if (state.filters.county) url += '&county=' + encodeURIComponent(state.filters.county);
      if (state.filters.branch) url += '&branch=' + encodeURIComponent(state.filters.branch);
    }

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
    const cfg = queueConfig[qKey];
    const list = cfg ? el(cfg.listId) : null;
    if (!cfg?.fragmentEndpoint || !window.htmx || !list) return false;
    const params = new URLSearchParams({ page: String(page) });
    if (qKey === 'all' && state.search) params.set('search', state.search);
    if (state.filters.county) params.set('county', state.filters.county);
    if (state.filters.branch) params.set('branch', state.filters.branch);
    try {
      const html = utils.fetchHtml
        ? await utils.fetchHtml(apiBase() + cfg.fragmentEndpoint + '?' + params.toString(), { headers: initDataHeader() })
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
      const fileBadge = b.has_requisition_file ? '<span class="badge badge-green">Form saved</span>' : '<span class="badge badge-grey">No saved form</span>';
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
              <button class="btn btn-primary btn-download-batch" data-url="${escapeHtml(b.download_url || '')}" ${b.download_url ? '' : 'disabled'}>Open Form</button>
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
    return items.map(item => `
      <div class="batch-summary-item">
        <strong>${escapeHtml(item.value)}</strong>
        <span>${escapeHtml(item.label)}</span>
      </div>
    `).join('');
  }

  function batchClientRows(farmers, blockedById = {}) {
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
    if (!container) return;
    if (!warnings || !warnings.length) {
      container.innerHTML = '';
      return;
    }
    container.innerHTML = `<div class="batch-warning-list">${warnings.map(w => `<div class="batch-warning">${escapeHtml(w.message || w)}</div>`).join('')}</div>`;
  }

  function openInvoiceOverlay(orderNumber) {
    const overlay = el('invoice-overlay');
    const overlaySub = el('invoice-overlay-sub');
    const batchNumInput = el('invoice-batch-number');
    const fileInput = el('invoice-file-input');
    const fileInfo = el('invoice-file-info');
    const submitBtn = el('invoice-submit-btn');
    const resultsDiv = el('invoice-results');
    if (!overlay || !batchNumInput) return;

    batchNumInput.value = orderNumber;
    overlaySub.textContent = `Batch: ${orderNumber}`;
    fileInput.value = '';
    fileInfo.style.display = 'none';
    fileInfo.textContent = '';
    submitBtn.disabled = true;
    resultsDiv.style.display = 'none';
    overlay.classList.add('open');
  }

  async function openBatchDetail(orderNumber) {
    if (!orderNumber) return;
    const overlay = el('batch-detail-overlay');
    const title = el('batch-detail-title');
    const sub = el('batch-detail-sub');
    const summary = el('batch-detail-summary');
    const actions = el('batch-detail-actions');
    const invoiceResult = el('batch-detail-invoice-result');
    const clients = el('batch-detail-clients');
    title.textContent = `Order ${orderNumber}`;
    sub.textContent = 'Loading batch details...';
    summary.innerHTML = '';
    actions.innerHTML = '';
    invoiceResult.innerHTML = '';
    clients.innerHTML = '<div class="empty-state"><div class="spinner-inline"></div></div>';
    overlay.classList.add('open');

    const { ok, data } = await apiFetch('/requisition-batches/' + encodeURIComponent(orderNumber) + '/');
    if (!ok || !data.ok) {
      clients.innerHTML = `<div class="empty-state"><div class="es-title">Could not load batch</div><div class="es-sub">${escapeHtml(data.error || 'Try again.')}</div></div>`;
      return;
    }
    const batch = data.batch;
    const inv = batch.invoice_summary || {};
    sub.textContent = `${batch.requisition_date || 'No date'} - ${batch.farmer_count || 0} client(s)`;
    summary.innerHTML = summaryGrid([
      { label: 'Clients', value: String(batch.farmer_count || 0) },
      { label: 'Invoiced', value: String(inv.invoiced_count || 0) },
      { label: 'Pending invoices', value: String(inv.pending_invoice_count ?? 0) },
    ]);
    actions.innerHTML = `
      ${batch.download_url ? `<button class="btn btn-primary" id="batch-detail-download">Open Requisition Form</button>` : '<span class="badge badge-grey">No saved requisition file</span>'}
      <button class="btn btn-secondary" id="batch-detail-upload">Upload Invoices</button>
    `;
    el('batch-detail-download')?.addEventListener('click', () => openPortalLink(batch.download_url));
    el('batch-detail-upload')?.addEventListener('click', () => openInvoiceOverlay(batch.order_number));

    const last = batch.last_invoice_result || {};
    invoiceResult.innerHTML = last.total_parsed ? `
      <div class="batch-warning-list">
        <div class="batch-warning">Last invoice upload: matched ${escapeHtml(last.matched_count || 0)} of ${escapeHtml(last.total_parsed || 0)} parsed invoice(s).</div>
      </div>
    ` : '';
    clients.innerHTML = batchClientRows(batch.farmers || []);
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
    const countySelect = el('filter-county');
    const branchSelect = el('filter-branch');
    if (!countySelect || !branchSelect) return;

    const currentCounty = state.filters.county;
    const currentBranch = state.filters.branch;

    const counties = new Set();
    const branches = new Set();

    farmers.forEach(f => {
      if (f.county) counties.add(f.county.trim());
      if (!currentCounty || (f.county && f.county.trim() === currentCounty)) {
        if (f.branch) branches.add(f.branch.trim());
      }
    });

    countySelect.innerHTML = '<option value="">All Counties</option>' + 
      Array.from(counties).sort().map(c => `<option value="${c}" ${c === currentCounty ? 'selected' : ''}>${c}</option>`).join('');

    branchSelect.innerHTML = '<option value="">All Branches</option>' + 
      Array.from(branches).sort().map(b => `<option value="${b}" ${b === currentBranch ? 'selected' : ''}>${b}</option>`).join('');

    const clearBtn = el('btn-clear-filters');
    if (clearBtn) {
      clearBtn.style.display = (currentCounty || currentBranch) ? 'inline-flex' : 'none';
    }
  }

  function applyFilters() {
    const qKey = state.activePage;
    const cfg = queueConfig[qKey];
    if (!cfg) return;

    const originalFarmers = state.queues[qKey] || [];
    
    const filteredFarmers = originalFarmers.filter(f => {
      const matchCounty = !state.filters.county || (f.county && f.county.trim() === state.filters.county);
      const matchBranch = !state.filters.branch || (f.branch && f.branch.trim() === state.filters.branch);
      return matchCounty && matchBranch;
    });

    const listEl = el(cfg.listId);
    renderFilteredFarmerList(listEl, filteredFarmers, cfg, qKey);
  }

  function renderFilteredFarmerList(listEl, farmers, cfg, qKey) {
    if (!farmers.length) {
      listEl.innerHTML = `<div class="empty-state"><div class="es-icon">OK</div><div class="es-title">${cfg.emptyTitle}</div><div class="es-sub">No matching records found for chosen filters.</div></div>`;
      return;
    }
    listEl.innerHTML = farmers.map(f => {
      const originalIdx = state.queues[qKey].indexOf(f);
      return `
        <div class="farmer-card${qKey === 'requisition' ? ' requisition-card' : ''}" data-qkey="${qKey}" data-idx="${originalIdx}" id="fc-${qKey}-${originalIdx}">
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
      `;
    }).join('');

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
    state.selectedFarmer = farmer;
    state.activeMode = mode;

    // Header
    el('sheet-name').textContent = farmer.customer_name || 'Unknown Farmer';
    el('sheet-sub').textContent = [farmer.county, farmer.sub_county, farmer.branch].filter(Boolean).join(' | ') || farmer.primary_phone || '';

    // Info rows
    const infoFields = [
      ['National ID', fmt(farmer.national_id)],
      ['Phone', fmt(farmer.primary_phone)],
      ['HBG Visit', fmtDate(farmer.sign_date)],
      ['JBL Visit', fmtDate(farmer.jbl_visit_date)],
      ['JBL Officer', fmt(farmer.jbl_officer)],
      ['JBL Status', farmer.jbl_visit_status ? `<span class="badge badge-blue">${farmer.jbl_visit_status}</span>` : '-'],
      ['Credit Decision', farmer.credit_decision ? `<span class="badge ${farmer.credit_decision === 'Approved' ? 'badge-green' : 'badge-orange'}">${farmer.credit_decision}</span>` : '-'],
      ['IMAB Created', fmt(farmer.imab_created)],
      ['Customer No.', fmt(farmer.customer_no)],
      ['Visit Media', farmer.jbl_media_count ? `${farmer.jbl_media_count} file link${farmer.jbl_media_count === 1 ? '' : 's'}` : '-'],
      ['Order No.', farmer.order_number ? `<strong>${farmer.order_number}</strong>` : '-'],
      ['Requisition Date', fmtDate(farmer.requisition_date)],
      ['HB Sales Person', fmt(farmer.hb_sales_person)],
      ['Village', fmt(farmer.village)],
      // Stage 7 - Invoice
      ...(farmer.invoice_number || farmer.invoice_amount || farmer.balance_due ? [
        ['Invoice', ''],
        ['Invoice No.', farmer.invoice_number ? `<code style="font-size:12px;">${farmer.invoice_number}</code>` : '-'],
        ['Invoice Date', fmtDate(farmer.invoice_date)],
        ['Invoice Amount', farmer.invoice_amount ? `<strong>KES ${farmer.invoice_amount}</strong>` : '-'],
        ['Discount', farmer.discount ? `KES ${farmer.discount}` : '-'],
        ['Payment', farmer.payment ? `KES ${farmer.payment}` : '-'],
        ['Balance Due', farmer.balance_due
          ? `<span class="badge ${parseFloat(farmer.balance_due) === 0 ? 'badge-green' : 'badge-orange'}">KES ${farmer.balance_due}</span>`
          : '-'],
      ] : []),
    ];
    el('sheet-info').innerHTML = infoFields.map(([label, value]) =>
      `<li class="info-row"><span class="ir-label">${label}</span><span class="ir-value">${value}</span></li>`
    ).join('');

    // Action form
    const formEl = el('sheet-form');
    const footerEl = el('sheet-footer');
    formEl.innerHTML = '';
    footerEl.innerHTML = '';
    el('sheet-gate-warning').style.display = 'none';

    if (mode === 'jbl_visit') {
      formEl.innerHTML = buildJblForm(farmer);
      footerEl.innerHTML = `<button class="primary" id="btn-submit-jbl">Log JBL Visit</button>`;
      el('btn-submit-jbl').addEventListener('click', submitJblVisit);
      wireGpsButton();
    } else if (mode === 'credit') {
      formEl.innerHTML = buildCreditForm(farmer);
      footerEl.innerHTML = `<button class="primary" id="btn-submit-credit">Set Credit Decision</button>`;
      el('btn-submit-credit').addEventListener('click', submitCreditDecision);
      wireCreditImabFields();
    } else if (mode === 'final_review') {
      formEl.innerHTML = buildFinalReviewForm(farmer);
      footerEl.innerHTML = `<button class="primary" id="btn-submit-final">Save Final Review</button>`;
      el('btn-submit-final').addEventListener('click', submitFinalDecision);
    } else if (mode === 'requisition') {
      const notApproved = farmer.final_decision !== 'Approved';
      if (notApproved) {
        el('sheet-gate-warning').style.display = 'flex';
        el('sheet-gate-warning').innerHTML = `Final Decision is <strong>${farmer.final_decision || 'not set'}</strong>. Must be <strong>Approved</strong> to assign an order.`;
        formEl.innerHTML = buildRequisitionForm(farmer);
        footerEl.innerHTML = `<button class="primary" id="btn-submit-req" disabled>Assign Order (Gate: Final Review)</button>`;
      } else {
        formEl.innerHTML = buildRequisitionForm(farmer);
        footerEl.innerHTML = `<button class="primary" id="btn-submit-req">Assign Order Number</button>`;
        el('btn-submit-req').addEventListener('click', submitOrder);
      }
    }

    // Map Rendering
    const lat = parseFloat(farmer.latitude);
    const lng = parseFloat(farmer.longitude);
    if (!isNaN(lat) && !isNaN(lng)) {
      initMap(lat, lng);
    } else {
      destroyMap();
    }

    el('sheet-overlay').classList.add('open');
    if (window.lucide) window.lucide.createIcons();
  }

  function initMap(lat, lng) {
    const mapContainer = el('sheet-map-container');
    if (!mapContainer) return;
    mapContainer.style.display = 'block';

    // Determine theme
    const isDark = (window.Telegram?.WebApp?.colorScheme === 'dark') || 
                   (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches);

    // Tile URL based on theme (Voyager vs Dark Matter)
    const tileUrl = isDark 
      ? 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png'
      : 'https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png';
    const attribution = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>';

    if (!mapInstance) {
      mapInstance = L.map('sheet-map', {
        zoomControl: false,
        attributionControl: false
      }).setView([lat, lng], 13);

      L.tileLayer(tileUrl, { attribution: attribution, maxZoom: 20 }).addTo(mapInstance);
      mapMarker = L.marker([lat, lng]).addTo(mapInstance);
    } else {
      // Re-locate and reset center
      mapInstance.setView([lat, lng], 13);
      
      // Update tile layer URL
      mapInstance.eachLayer(layer => {
        if (layer instanceof L.TileLayer) {
          layer.setUrl(tileUrl);
        }
      });

      if (mapMarker) {
        mapMarker.setLatLng([lat, lng]);
      } else {
        mapMarker = L.marker([lat, lng]).addTo(mapInstance);
      }
    }

    setTimeout(() => {
      if (mapInstance) mapInstance.invalidateSize();
    }, 100);
  }

  function destroyMap() {
    const mapContainer = el('sheet-map-container');
    if (mapContainer) mapContainer.style.display = 'none';
  }

  function buildJblForm(farmer) {
    const today = new Date().toISOString().split('T')[0];
    const statusOptions = state.metaStatuses.map(s =>
      `<option value="${s}"${farmer.jbl_visit_status === s ? ' selected' : ''}>${s}</option>`
    ).join('');
    return `
      <div class="form-section">
        <div class="form-row">
          <label>Visit Date</label>
          <input type="date" id="jbl-date" value="${farmer.jbl_visit_date || today}">
        </div>
        <div class="form-row">
          <label>Status / Outcome</label>
          <select id="jbl-status"><option value="">- Select -</option>${statusOptions}</select>
        </div>
        <div class="form-row">
          <label>Officer Name</label>
          <input type="text" id="jbl-officer" placeholder="Your name" value="${escapeHtml(farmer.jbl_officer || '')}">
        </div>
        <div class="form-row">
          <label>County</label>
          <input type="text" id="jbl-county" placeholder="County" value="${escapeHtml(farmer.county || '')}">
        </div>
        <div class="form-row">
          <label>Constituency</label>
          <input type="text" id="jbl-sub-county" placeholder="Constituency / sub-county" value="${escapeHtml(farmer.sub_county || '')}">
        </div>
        <div class="form-row">
          <label>Village</label>
          <input type="text" id="jbl-village" placeholder="Village / area" value="${escapeHtml(farmer.village || '')}">
        </div>
        <div class="form-row">
          <label>Comment (optional)</label>
          <textarea id="jbl-comment" rows="2" placeholder="Additional notes...">${escapeHtml(farmer.jbl_visit_comment || '')}</textarea>
        </div>
        <div class="form-row media-upload-row">
          <label>Visit Media</label>
          <div class="media-upload-control">
            <input type="file" id="jbl-media" name="files" multiple accept="image/*,.pdf,.doc,.docx,.xls,.xlsx">
            <small>Optional. Upload visit photos, signed docs, or supporting files.</small>
            ${farmer.jbl_media_count ? `<small>${farmer.jbl_media_count} existing Drive link${farmer.jbl_media_count === 1 ? '' : 's'} on this record.</small>` : ''}
          </div>
        </div>
        <div class="form-row" style="border-bottom: none; background: transparent; padding: 12px 0 0;">
          <button type="button" id="btn-gps" style="width: 100%; height: 38px; display: flex; align-items: center; justify-content: center; gap: 8px;">
            - Capture GPS Location
          </button>
          <div id="gps-coords" style="font-size: 11px; font-weight: 600; color: var(--text-muted); text-align: center; margin-top: 6px;">
            Not captured
          </div>
          <input type="hidden" id="jbl-lat" value="">
          <input type="hidden" id="jbl-lng" value="">
        </div>
      </div>
    `;
  }

  function wireGpsButton() {
    const btn = el('btn-gps');
    if (!btn) return;
    btn.addEventListener('click', () => {
      if (!navigator.geolocation) {
        showToast('GPS is not supported by your browser', 'error');
        return;
      }
      btn.disabled = true;
      btn.innerHTML = 'Capturing Location...';
      navigator.geolocation.getCurrentPosition(
        position => {
          const lat = position.coords.latitude;
          const lng = position.coords.longitude;
          el('jbl-lat').value = lat;
          el('jbl-lng').value = lng;
          el('gps-coords').innerHTML = `Location captured<br><span style="font-family: monospace; font-size: 12px; color: var(--color-success)">Lat: ${lat.toFixed(6)}, Lng: ${lng.toFixed(6)}</span>`;
          btn.innerHTML = 'Location Captured';
          btn.disabled = false;
          showToast('GPS location captured', 'success');
        },
        error => {
          btn.disabled = false;
          btn.innerHTML = 'Try Capture Again';
          let msg = 'Failed to get location';
          if (error.code === error.PERMISSION_DENIED) msg = 'Location permission denied';
          else if (error.code === error.POSITION_UNAVAILABLE) msg = 'Location unavailable';
          else if (error.code === error.TIMEOUT) msg = 'Location request timed out';
          el('gps-coords').textContent = msg;
          showToast(msg, 'error');
        },
        { enableHighAccuracy: true, timeout: 8000, maximumAge: 0 }
      );
    });
  }

  function buildCreditForm(farmer) {
    const decisionOptions = state.metaDecisions.map(d =>
      `<option value="${d}"${farmer.credit_decision === d ? ' selected' : ''}>${d}</option>`
    ).join('');
    const imabOptions = (state.metaImabOptions.length ? state.metaImabOptions : ['Yes', 'No', 'Pending']).map(v =>
      `<option value="${v}"${farmer.imab_created === v ? ' selected' : ''}>${v}</option>`
    ).join('');
    const customerNoDisabled = farmer.imab_created !== 'Yes';
    return `
      <div class="form-section">
        <div class="form-row">
          <label>Credit Decision</label>
          <select id="credit-decision"><option value="">- Select -</option>${decisionOptions}</select>
        </div>
        <div class="form-row">
          <label>IS CUSTOMER CREATED ON IMAB?</label>
          <select id="credit-imab"><option value="">- Select -</option>${imabOptions}</select>
        </div>
        <div class="form-row">
          <label>CUSTOMER NO</label>
          <input type="text" id="credit-customer-no" inputmode="numeric" pattern="[0-9]*" placeholder="IMAB customer number" value="${escapeHtml(customerNoDisabled ? '' : (farmer.customer_no || ''))}"${customerNoDisabled ? ' disabled' : ''}>
          <small id="credit-imab-help" class="field-help">${customerNoDisabled ? 'Select Yes after IMAB creation before entering a customer number.' : 'Required before this case can move to Head of Rural review.'}</small>
        </div>
      </div>
      ${farmer.jbl_visit_comment ? `<div class="info-row"><span class="ir-label">JBL Comment</span><span class="ir-value">${escapeHtml(farmer.jbl_visit_comment)}</span></div>` : ''}
    `;
  }

  function wireCreditImabFields() {
    const imab = el('credit-imab');
    const customerNo = el('credit-customer-no');
    const help = el('credit-imab-help');
    if (!imab || !customerNo) return;
    const sync = () => {
      const enabled = imab.value === 'Yes';
      customerNo.disabled = !enabled;
      if (!enabled) customerNo.value = '';
      if (help) {
        help.textContent = enabled
          ? 'Required before this case can move to Head of Rural review.'
          : 'Select Yes after IMAB creation before entering a customer number.';
      }
    };
    imab.addEventListener('change', sync);
    sync();
  }

  function buildFinalReviewForm(farmer) {
    const decisionOptions = state.metaFinalDecisions.map(d =>
      `<option value="${d}"${farmer.final_decision === d ? ' selected' : ''}>${d}</option>`
    ).join('');
    const phone = String(farmer.primary_phone || '').replace(/[^0-9+]/g, '');
    return `
      <div class="form-section">
        <div class="form-row">
          <label>Client Phone</label>
          <div style="display:flex;gap:8px;align-items:center;width:100%;">
            <input type="tel" value="${escapeHtml(farmer.primary_phone || '')}" readonly style="flex:1;">
            ${phone ? `<a class="phone-call-button" href="tel:+${phone.replace(/^\+/, '')}" aria-label="Call client"><i data-lucide="phone"></i></a>` : ''}
          </div>
        </div>
        <div class="form-row">
          <label>Final Decision</label>
          <select id="final-decision"><option value="">- Select -</option>${decisionOptions}</select>
        </div>
        <div class="form-row">
          <label>After-call Comments</label>
          <textarea id="final-comment" rows="4" placeholder="Summarize the call and reason for the decision...">${escapeHtml(farmer.final_decision_comment || '')}</textarea>
        </div>
      </div>
      ${farmer.jbl_visit_comment ? `<div class="info-row"><span class="ir-label">BRO Comment</span><span class="ir-value">${escapeHtml(farmer.jbl_visit_comment)}</span></div>` : ''}
    `;
  }

  function buildRequisitionForm(farmer) {
    const today = new Date().toISOString().split('T')[0];
    return `
      <div class="form-section">
        <div class="form-row">
          <label>Order Number</label>
          <input type="text" id="req-order" placeholder="e.g. JBL-2026-001" value="${farmer.order_number || ''}">
        </div>
        <div class="form-row">
          <label>Requisition Date</label>
          <input type="date" id="req-date" value="${farmer.requisition_date || today}">
        </div>
      </div>
    `;
  }

  function closeSheet() {
    el('sheet-overlay').classList.remove('open');
    state.selectedFarmer = null;
    state.activeMode = null;
    destroyMap();
  }
  el('sheet-overlay').addEventListener('click', e => { if (e.target === el('sheet-overlay')) closeSheet(); });
  el('sheet-close').addEventListener('click', closeSheet);
  // Submit handlers
  async function submitJblVisit() {
    const farmer = state.selectedFarmer;
    if (!farmer) return;
    const visitDate = el('jbl-date')?.value || '';
    const visitStatus = el('jbl-status')?.value || '';
    const officer = el('jbl-officer')?.value || '';
    const county = el('jbl-county')?.value || '';
    const subCounty = el('jbl-sub-county')?.value || '';
    const village = el('jbl-village')?.value || '';
    const comment = el('jbl-comment')?.value || '';
    const latitude = el('jbl-lat')?.value || '';
    const longitude = el('jbl-lng')?.value || '';
    if (!visitStatus) { showToast('Please select a visit status', 'error'); return; }

    const btn = el('btn-submit-jbl');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-inline"></span> Saving...';

    const { ok, data } = await apiFetch('/jbl-queue/' + farmer.id + '/', {
      method: 'POST',
      body: JSON.stringify({
        visit_date: visitDate,
        visit_status: visitStatus,
        officer: officer,
        county: county,
        sub_county: subCounty,
        village: village,
        comment: comment,
        latitude: latitude,
        longitude: longitude
      }),
    });

    btn.disabled = false;
    btn.textContent = 'Log JBL Visit';
    if (!ok) { showToast(data.error || 'Save failed', 'error'); return; }
    const uploadOk = await uploadJblMediaIfSelected(farmer.id);
    if (!uploadOk) return;
    showToast('JBL visit logged', 'success');
    closeSheet();
    reloadCurrentQueue();
    loadDashboard();
  }

  async function uploadJblMediaIfSelected(farmerId) {
    const input = el('jbl-media');
    const files = input?.files ? Array.from(input.files) : [];
    if (!files.length) return true;
    if (!navigator.onLine) {
      showToast('Offline. Reconnect before uploading visit media.', 'error');
      return false;
    }
    const formData = new FormData();
    files.forEach(file => formData.append('files', file));
    showToast('Uploading visit media...');
    try {
      const response = await fetch(apiBase() + '/jbl-queue/' + farmerId + '/media/', {
        method: 'POST',
        headers: {
          ...initDataHeader(),
          'X-CSRFToken': getCookie('csrftoken') || ''
        },
        body: formData
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || data.ok === false) {
        showToast(data.error || 'Media upload failed. Visit was saved; retry media upload from the record.', 'error');
        return false;
      }
      const warnings = Array.isArray(data.warnings) && data.warnings.length ? ' ' + data.warnings.join(' ') : '';
      showToast(`Stored ${data.stored_count || 0} media file${(data.stored_count || 0) === 1 ? '' : 's'}.${warnings}`, data.warnings?.length ? 'warning' : 'success');
      return true;
    } catch (err) {
      console.error(err);
      showToast('Media upload failed. Visit was saved; retry media upload from the record.', 'error');
      return false;
    }
  }


  async function submitCreditDecision() {
    const farmer = state.selectedFarmer;
    if (!farmer) return;
    const decision = el('credit-decision')?.value || '';
    const imabCreated = el('credit-imab')?.value || '';
    const customerNo = (el('credit-customer-no')?.value || '').replace(/[^0-9]/g, '');
    if (!decision) { showToast('Please select a decision', 'error'); return; }
    if (imabCreated !== 'Yes') { showToast('Create the customer in IMAB before sending this case to Head of Rural review.', 'error'); return; }
    if (!customerNo) { showToast('Enter the IMAB Customer No before sending this case to Head of Rural review.', 'error'); return; }

    const btn = el('btn-submit-credit');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-inline"></span> Saving...';

    const { ok, data } = await apiFetch('/credit-queue/' + farmer.id + '/', {
      method: 'POST',
      body: JSON.stringify({ decision, imab_created: imabCreated, customer_no: customerNo }),
    });

    btn.disabled = false;
    btn.textContent = 'Set Credit Decision';
    if (!ok) { showToast(data.error || 'Save failed', 'error'); return; }
    showToast('Credit decision saved', 'success');
    closeSheet();
    reloadCurrentQueue();
    loadDashboard();
  }

  async function submitFinalDecision() {
    const farmer = state.selectedFarmer;
    if (!farmer) return;
    const finalDecision = el('final-decision')?.value || '';
    const decisionComment = el('final-comment')?.value || '';
    if (!finalDecision) { showToast('Please select a final decision', 'error'); return; }

    const btn = el('btn-submit-final');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-inline"></span> Saving...';

    const { ok, data } = await apiFetch('/final-review-queue/' + farmer.id + '/', {
      method: 'POST',
      body: JSON.stringify({ final_decision: finalDecision, decision_comment: decisionComment }),
    });

    btn.disabled = false;
    btn.textContent = 'Save Final Review';
    if (!ok) { showToast(data.error || 'Save failed', 'error'); return; }
    showToast('Final review saved', 'success');
    closeSheet();
    reloadCurrentQueue();
    loadDashboard();
  }

  async function submitOrder() {
    const farmer = state.selectedFarmer;
    if (!farmer) return;
    const orderNumber = (el('req-order')?.value || '').trim();
    const reqDate = el('req-date')?.value || '';
    if (!orderNumber) { showToast('Order number is required', 'error'); return; }

    const btn = el('btn-submit-req');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-inline"></span> Saving...';

    const { ok, status, data } = await apiFetch('/requisition-queue/' + farmer.id + '/', {
      method: 'POST',
      body: JSON.stringify({ order_number: orderNumber, requisition_date: reqDate }),
    });

    btn.disabled = false;
    btn.textContent = 'Assign Order Number';
    if (!ok) {
      if (status === 403) { showToast('Error: ' + (data.error || 'Final review not approved'), 'error'); }
      else { showToast(data.error || 'Save failed', 'error'); }
      return;
    }
    showToast('Order assigned', 'success');
    closeSheet();
    reloadCurrentQueue();
    loadDashboard();
  }

  function reloadCurrentQueue() {
    const p = state.activePage;
    if (queueConfig[p]) loadQueue(p, state.pages[p] || 1);
  }
  // Filters Event Listeners
  el('filter-county')?.addEventListener('change', async e => {
    state.filters.county = e.target.value;
    state.filters.branch = ''; // reset branch if county changed
    const qKey = state.activePage;
    if (qKey === 'all') {
      loadQueue('all', 1);
    } else if (queueConfig[qKey]?.fragmentEndpoint && window.htmx) {
      updateFilterOptions(state.queues[qKey] || []);
      if (!(await renderQueueFragment(qKey, 1))) applyFilters();
    } else {
      updateFilterOptions(state.queues[qKey] || []);
      applyFilters();
    }
  });

  el('filter-branch')?.addEventListener('change', async e => {
    state.filters.branch = e.target.value;
    if (state.activePage === 'all') loadQueue('all', 1);
    else if (queueConfig[state.activePage]?.fragmentEndpoint && window.htmx) {
      if (!(await renderQueueFragment(state.activePage, 1))) applyFilters();
    }
    else applyFilters();
  });

  el('btn-clear-filters')?.addEventListener('click', async () => {
    state.filters.county = '';
    state.filters.branch = '';
    const qKey = state.activePage;
    if (qKey === 'all') {
      loadQueue('all', 1);
    } else if (queueConfig[qKey]?.fragmentEndpoint && window.htmx) {
      updateFilterOptions(state.queues[qKey] || []);
      if (!(await renderQueueFragment(qKey, 1))) applyFilters();
    } else {
      updateFilterOptions(state.queues[qKey] || []);
      applyFilters();
    }
  });
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
    const panel = el('requisition-batch-panel');
    if (!panel) return;
    const count = state.selectedRequisitions.size;
    if (count > 0) {
      panel.style.display = 'block';
      const badge = el('batch-selected-count');
      if (badge) badge.textContent = `${count} selected`;
    } else {
      panel.style.display = 'none';
    }
  }

  function currentRequisitionPayload() {
    const orderNoInput = el('batch-order-num');
    const reqDateInput = el('batch-req-date');
    if (!orderNoInput || !reqDateInput) return null;
    const order_number = orderNoInput.value.trim();
    const requisition_date = reqDateInput.value.trim();
    const farmer_ids = Array.from(state.selectedRequisitions);
    if (!order_number) {
      alert('Please enter an Order Number / Batch Ref.');
      return null;
    }
    if (!requisition_date) {
      alert('Please select a Requisition Date.');
      return null;
    }
    if (!farmer_ids.length) {
      alert('No farmers selected.');
      return null;
    }
    return { farmer_ids, order_number, requisition_date, return_url: true };
  }

  async function requestRequisitionPreview() {
    const payload = currentRequisitionPayload();
    if (!payload) return;
    try {
      showToast('Preparing batch preview...');
      const response = await fetch(apiBase() + '/requisition-queue/preview/', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...initDataHeader(),
          'X-CSRFToken': getCookie('csrftoken') || ''
        },
        body: JSON.stringify(payload)
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data.ok) {
        showToast(data.error || 'Could not prepare preview.', 'error');
        return;
      }
      state.pendingRequisitionPayload = payload;
      openRequisitionPreview(data);
    } catch (err) {
      console.error(err);
      showToast('Could not prepare preview.', 'error');
    }
  }

  function openRequisitionPreview(data) {
    const overlay = el('requisition-preview-overlay');
    const sub = el('requisition-preview-sub');
    const summary = el('requisition-preview-summary');
    const warnings = el('requisition-preview-warnings');
    const list = el('requisition-preview-list');
    const confirm = el('requisition-preview-confirm');
    const blockedById = {};
    (data.blocked || []).forEach(item => {
      if (item.farmer?.id) blockedById[item.farmer.id] = item.missing || [];
    });
    sub.textContent = `Order ${data.order_number} - ${data.requisition_date}`;
    summary.innerHTML = summaryGrid([
      { label: 'Ready', value: String(data.ready_count || 0) },
      { label: 'Blocked', value: String(data.blocked_count || 0) },
      { label: 'Warnings', value: String(data.warning_count || 0) },
    ]);
    renderWarnings(warnings, data.warnings || []);
    const allFarmers = [...(data.ready || []), ...(data.blocked || []).map(item => item.farmer)];
    list.innerHTML = batchClientRows(allFarmers, blockedById);
    confirm.disabled = (data.blocked_count || 0) > 0 || !(data.ready_count || 0);
    confirm.textContent = confirm.disabled ? 'Resolve Blocked Items' : 'Generate Requisition';
    overlay.classList.add('open');
  }

  async function generateRequisitionFromPreview() {
    const payload = state.pendingRequisitionPayload;
    if (!payload) return;
    const confirm = el('requisition-preview-confirm');
    confirm.disabled = true;
    confirm.innerHTML = '<span class="spinner-inline"></span> Generating...';
    try {
      const response = await fetch(apiBase() + '/requisition-queue/generate/', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...initDataHeader(),
          'X-CSRFToken': getCookie('csrftoken') || ''
        },
        body: JSON.stringify(payload)
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok || !result.ok || !result.download_url) {
        showToast(result.error || 'Requisition generation failed.', 'error');
        return;
      }
      openPortalLink(result.download_url);
      showToast('Requisition generated and saved to Batches.', 'success');
      state.selectedRequisitions.clear();
      state.pendingRequisitionPayload = null;
      el('batch-order-num').value = '';
      el('batch-req-date').value = '';
      updateBatchPanel();
      el('requisition-preview-overlay').classList.remove('open');
      loadQueue('requisition', 1);
      loadQueue('batches', 1);
    } catch (err) {
      console.error(err);
      showToast('An error occurred during generation.', 'error');
    } finally {
      confirm.disabled = false;
      confirm.textContent = 'Generate Requisition';
    }
  }

  el('btn-generate-requisition')?.addEventListener('click', requestRequisitionPreview);
  el('requisition-preview-confirm')?.addEventListener('click', generateRequisitionFromPreview);
  el('requisition-preview-close')?.addEventListener('click', () => el('requisition-preview-overlay').classList.remove('open'));
  el('requisition-preview-cancel')?.addEventListener('click', () => el('requisition-preview-overlay').classList.remove('open'));
  el('requisition-preview-overlay')?.addEventListener('click', e => {
    if (e.target === el('requisition-preview-overlay')) el('requisition-preview-overlay').classList.remove('open');
  });
  el('batch-detail-close')?.addEventListener('click', () => el('batch-detail-overlay').classList.remove('open'));
  el('batch-detail-overlay')?.addEventListener('click', e => {
    if (e.target === el('batch-detail-overlay')) el('batch-detail-overlay').classList.remove('open');
  });


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
  // Invoice Upload Handlers
  const invoiceOverlay = el('invoice-overlay');
  const invoiceOverlayClose = el('invoice-overlay-close');
  const invoiceUploadForm = el('invoice-upload-form');
  const invoiceFileInput = el('invoice-file-input');
  const invoiceFileInfo = el('invoice-file-info');
  const invoiceSubmitBtn = el('invoice-submit-btn');
  const invoiceResults = el('invoice-results');
  const invoiceResultsSummary = el('invoice-results-summary');
  const invoiceResultsList = el('invoice-results-list');
  const invoiceUploadMaxMb = Number(window.PORTAL_CONFIG?.invoiceUploadMaxFileSizeMb || 8);
  const invoiceUploadMaxBytes = Math.max(1, invoiceUploadMaxMb) * 1024 * 1024;
  let invoiceUploadInProgress = false;

  function invoiceFileSizeLabel(bytes) {
    if (!bytes && bytes !== 0) return 'unknown size';
    if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(2)} MB`;
    return `${(bytes / 1024).toFixed(1)} KB`;
  }

  function validateInvoiceFile(file) {
    if (!file) return 'Select a PDF file first.';
    if (!String(file.name || '').toLowerCase().endsWith('.pdf')) return 'Only PDF files are supported.';
    if (file.size > invoiceUploadMaxBytes) {
      return `This PDF is ${invoiceFileSizeLabel(file.size)}. Maximum supported size is ${invoiceUploadMaxMb} MB.`;
    }
    return '';
  }

  function closeInvoiceOverlay() {
    invoiceOverlay.classList.remove('open');
  }

  invoiceOverlayClose.addEventListener('click', closeInvoiceOverlay);
  invoiceOverlay.addEventListener('click', e => {
    if (e.target === invoiceOverlay) closeInvoiceOverlay();
  });

  invoiceFileInput.addEventListener('change', () => {
    const file = invoiceFileInput.files[0];
    if (file) {
      const validationError = validateInvoiceFile(file);
      if (validationError) {
        showToast(validationError, 'error');
        invoiceFileInput.value = '';
        invoiceFileInfo.style.display = 'none';
        invoiceSubmitBtn.disabled = true;
        return;
      }
      invoiceFileInfo.textContent = `Selected: ${file.name} (${invoiceFileSizeLabel(file.size)}). Limit: ${invoiceUploadMaxMb} MB.`;
      invoiceFileInfo.style.display = 'block';
      invoiceSubmitBtn.disabled = false;
    } else {
      invoiceFileInfo.style.display = 'none';
      invoiceSubmitBtn.disabled = true;
    }
  });

  invoiceUploadForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (invoiceUploadInProgress) return;
    const file = invoiceFileInput.files[0];
    const validationError = validateInvoiceFile(file);
    if (validationError) {
      showToast(validationError, 'error');
      return;
    }
    if (navigator.onLine === false) {
      updateConnectionBanner();
      showToast('Offline. Reconnect before uploading invoice PDFs.', 'error');
      return;
    }

    invoiceUploadInProgress = true;
    invoiceSubmitBtn.disabled = true;
    const origBtnText = invoiceSubmitBtn.textContent;
    invoiceSubmitBtn.textContent = 'Extracting & Syncing...';

    try {
      const formData = new FormData(invoiceUploadForm);
      const response = await fetch(apiBase() + '/requisition-batches/upload-invoices/', {
        method: 'POST',
        headers: {
          ...initDataHeader(),
          'X-CSRFToken': getCookie('csrftoken') || ''
        },
        body: formData
      });

      if (!response.ok) {
        const errJson = await response.json().catch(() => ({}));
        throw new Error(errJson.error || 'Failed to process invoices.');
      }

      const res = await response.json();
      if (!res.ok && !(res.results || []).length) {
        throw new Error(res.error || 'Invoice extraction failed.');
      }

      if (res.ok) {
        showToast(`Invoices processed successfully! Matched ${res.matched_count} of ${res.total_parsed}.`, 'success');
      } else {
        showToast(res.error || 'No invoice matched. Review the details below.', 'error');
      }

      // Render results
      const matchedCount = res.matched_count || 0;
      const totalParsed = res.total_parsed || 0;
      const candidateCount = res.candidate_count ?? 'unknown';
      invoiceResultsSummary.textContent = res.ok
        ? `Matched ${matchedCount} of ${totalParsed} parsed invoice(s). Candidates in selected batch: ${candidateCount}.`
        : `${res.error || 'Invoice upload needs review.'} Parsed: ${totalParsed}. Matched: ${matchedCount}. Candidates in selected batch: ${candidateCount}.`;
      invoiceResultsList.innerHTML = (res.results || []).map(r => {
        const matched = r.status === 'Matched';
        const customerName = escapeHtml(r.customer_name || '-');
        const invoiceNo = escapeHtml(r.invoice_no || '-');
        const status = escapeHtml(r.status || 'Unmatched');
        const reason = r.reason ? `<div style="font-size:11px; color:#7f1d1d; margin-top:2px;">${escapeHtml(r.reason)}</div>` : '';
        const parsed = !matched ? `
          <div style="font-size:11px; color:#475569; margin-top:4px; line-height:1.45;">
            Parsed ID: <strong>${escapeHtml(r.parsed_national_id || '-')}</strong> |
            Phone: <strong>${escapeHtml(r.parsed_phone || '-')}</strong> |
            Selected order: <strong>${escapeHtml(r.selected_order_number || res.order_number || '-')}</strong><br>
            Batch candidates: ${escapeHtml(r.batch_candidate_count ?? '-')} |
            ID matches: ${escapeHtml(r.batch_id_match_count ?? '-')} |
            Phone matches: ${escapeHtml(r.batch_phone_match_count ?? '-')} |
            Name matches: ${escapeHtml(r.batch_name_match_count ?? '-')}
          </div>` : '';
        const outside = (r.outside_batch_matches || []).length ? `
          <div style="font-size:11px; color:#7c2d12; margin-top:4px; line-height:1.45;">
            Possible match outside selected order:<br>
            ${(r.outside_batch_matches || []).map(m => `${escapeHtml(m.customer_name || '-')} | ID ${escapeHtml(m.national_id || '-')} - ${escapeHtml(m.primary_phone || '-')} | Order ${escapeHtml(m.order_number || '-')} | Status ${escapeHtml(m.status || '-')}`).join('<br>')}
          </div>` : '';
        return `
        <div style="font-size:13px; padding:6px 8px; background:${matched ? '#f0fdf4' : '#fef2f2'}; border-radius:6px; border:1px solid ${matched ? '#bbf7d0' : '#fecaca'};">
          <div style="display:flex; justify-content:space-between; align-items:center; gap:8px;">
            <span style="font-weight:600; color:#1e293b;">${customerName}</span>
            <div style="display:flex; align-items:center; gap:6px;">
              <span style="font-size:11px; font-family:monospace; color:#64748b;">${invoiceNo}</span>
              <span class="badge ${matched ? 'badge-green' : 'badge-red'}" style="font-size:10px; padding:2px 6px;">${status}</span>
            </div>
          </div>
          ${reason}
          ${parsed}
          ${outside}
        </div>`;
      }).join('');
      invoiceResults.style.display = 'block';

      // Reload batches list
      loadQueue('batches', state.pages['batches'] || 1);
    } catch (err) {
      showToast(err.message, 'error');
    } finally {
      invoiceUploadInProgress = false;
      invoiceSubmitBtn.disabled = false;
      invoiceSubmitBtn.textContent = origBtnText;
    }
  });

  updateConnectionBanner();
  init();

})();
