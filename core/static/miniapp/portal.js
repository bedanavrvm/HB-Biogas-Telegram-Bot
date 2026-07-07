// portal.js — JBL Pipeline Portal Mini App

(() => {
  'use strict';

  // ── Init Telegram Web App ────────────────────────────────────────────────
  const tg = window.Telegram?.WebApp;
  if (tg) {
    tg.ready();
    tg.expand();
  }

  // ── State ────────────────────────────────────────────────────────────────
  let state = {
    activePage: 'dashboard',
    counts: {},
    queues: { jbl: [], credit: [], requisition: [], deferred: [], all: [], batches: [] },
    pagination: {},
    pages: { jbl: 1, credit: 1, requisition: 1, deferred: 1, all: 1, batches: 1 },
    search: '',
    metaStatuses: [],
    metaDecisions: [],
    selectedFarmer: null,
    activeMode: null, // 'jbl_visit' | 'credit' | 'requisition'
    filters: { county: '', branch: '' },
    selectedRequisitions: new Set()
  };

  let mapInstance = null;
  let mapMarker = null;

  // ── Helpers ──────────────────────────────────────────────────────────────
  function el(id) { return document.getElementById(id); }

  function apiBase() { return '/api/portal'; }

  function initDataHeader() {
    const raw = tg?.initData || '';
    return raw ? { 'X-Telegram-Init-Data': raw } : {};
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
    t.textContent = msg;
    t.className = 'toast show' + (type ? ' ' + type + '-toast' : '');
    clearTimeout(_toastTimer);
    _toastTimer = setTimeout(() => { t.classList.remove('show'); }, 3000);
  }

  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, ch => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;'
    }[ch]));
  }

  function fmt(v) { return v || '—'; }
  function fmtDate(v) {
    if (!v) return '—';
    const d = new Date(v);
    if (isNaN(d.getTime())) return '—';
    const day = String(d.getDate()).padStart(2, '0');
    const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    const month = months[d.getMonth()];
    const year = d.getFullYear();
    return `${day}-${month}-${year}`;
  }

  function stageBadge(farmer) {
    const stage = farmer.pipeline_stage || 1;
    const labels = ['—', 'Awaiting JBL', 'JBL Visited', 'Credit Set', 'Ordered', '', '', 'Invoiced'];
    const styles = ['', 'badge-grey', 'badge-blue', 'badge-orange', 'badge-green', '', '', 'badge-green'];
    return `<span class="badge ${styles[stage] || ''}">${labels[stage] || 'Stage ' + stage}</span>`;
  }

  function creditBadge(farmer) {
    if (!farmer.credit_decision) return '';
    const map = { Approved: 'badge-green', Rejected: 'badge-red', Deferred: 'badge-orange', Pending: 'badge-grey', 'Exemption Approved': 'badge-green' };
    return `<span class="badge ${map[farmer.credit_decision] || 'badge-grey'}">${farmer.credit_decision}</span>`;
  }

  function jblBadge(farmer) {
    if (!farmer.jbl_visit_status) return '';
    const cls = farmer.jbl_visit_status.startsWith('Approved') ? 'badge-green'
      : farmer.jbl_visit_status === 'Awaiting Analysis' ? 'badge-blue'
      : farmer.jbl_visit_status.includes('Reject') || farmer.jbl_visit_status.includes('Cancel') ? 'badge-red'
      : 'badge-orange';
    return `<span class="badge ${cls}">${farmer.jbl_visit_status}</span>`;
  }

  // ── Tab navigation ────────────────────────────────────────────────────────
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

    // Show filter bar only on list queue views (jbl, credit, requisition, deferred)
    const filterBar = el('portal-filter-bar');
    if (filterBar) {
      if (page === 'dashboard' || page === 'all' || page === 'batches') {
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

  // ── Dashboard ─────────────────────────────────────────────────────────────
  async function loadDashboard() {
    el('dash-loading').style.display = 'block';
    el('dash-counts').style.display = 'none';
    const { ok, data } = await apiFetch('/dashboard/');
    el('dash-loading').style.display = 'none';
    if (!ok) { showToast('Could not load dashboard', 'error'); return; }
    state.counts = data.counts || {};
    renderDashboard();
  }

  function renderDashboard() {
    const c = state.counts;
    el('cnt-jbl').textContent = c.jbl_queue ?? '—';
    el('cnt-credit').textContent = c.credit_queue ?? '—';
    el('cnt-requisition').textContent = c.requisition_queue ?? '—';
    el('cnt-deferred').textContent = c.deferred ?? '—';
    el('cnt-total').textContent = c.total ?? '—';
    // Update tab badges
    setBadge('tab-badge-jbl', c.jbl_queue);
    setBadge('tab-badge-credit', c.credit_queue);
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
  document.querySelectorAll('.count-card[data-page]').forEach(card => {
    card.addEventListener('click', () => {
      const page = card.dataset.page;
      switchPage(page);
      loadPage(page);
    });
  });

  // ── Generic queue loader ──────────────────────────────────────────────────
  const queueConfig = {
    jbl: { endpoint: '/jbl-queue/', listId: 'jbl-list', pageKey: 'jbl', mode: 'jbl_visit', emptyTitle: 'All caught up!', emptySub: 'No farmers are waiting for a JBL visit.' },
    credit: { endpoint: '/credit-queue/', listId: 'credit-list', pageKey: 'credit', mode: 'credit', emptyTitle: 'No credit cases', emptySub: 'No farmers are awaiting credit analysis.' },
    requisition: { endpoint: '/requisition-queue/', listId: 'req-list', pageKey: 'requisition', mode: 'requisition', emptyTitle: 'No approved cases', emptySub: 'No credit-approved farmers are awaiting an order number.' },
    deferred: { endpoint: '/deferred/', listId: 'deferred-list', pageKey: 'deferred', mode: null, emptyTitle: 'No deferred cases', emptySub: 'No farmers are deferred or flagged.' },
    all: { endpoint: '/farmers/', listId: 'all-list', pageKey: 'all', mode: null, emptyTitle: 'No farmers found', emptySub: 'Try a different search term.' },
    batches: { endpoint: '/requisition-batches/', listId: 'batches-list', pageKey: 'batches', mode: null, emptyTitle: 'No batches found', emptySub: 'No requisition batches have been generated yet.' },
  };

  async function loadQueue(qKey, page = 1) {
    const cfg = queueConfig[qKey];
    if (!cfg) return;
    const listEl = el(cfg.listId);
    listEl.innerHTML = '<div class="empty-state"><div class="spinner-inline"></div></div>';

    let url = cfg.endpoint + '?page=' + page;
    if (qKey === 'all') {
      const searchVal = state.search || '';
      if (searchVal) url += '&search=' + encodeURIComponent(searchVal);
    }

    const { ok, data } = await apiFetch(url);
    if (!ok) { listEl.innerHTML = `<div class="empty-state"><div class="es-icon">⚠️</div><div class="es-title">Error loading queue</div></div>`; return; }

    if (qKey === 'batches') {
      const batches = data.batches || [];
      state.queues[qKey] = batches;
      state.pagination[qKey] = data.pagination || {};
      state.pages[qKey] = page;
      renderBatchesList(listEl, batches, cfg);
      renderPagination(qKey, data.pagination);
      return;
    }

    const farmers = data.farmers || [];
    state.queues[qKey] = farmers;
    state.pagination[qKey] = data.pagination || {};
    state.pages[qKey] = page;

    // Apply filtering
    if (qKey !== 'dashboard' && qKey !== 'all') {
      updateFilterOptions(farmers);
      applyFilters();
    } else {
      renderFarmerList(listEl, farmers, cfg, qKey);
    }
    renderPagination(qKey, data.pagination);
  }

  function renderBatchesList(listEl, batches, cfg) {
    if (!batches.length) {
      listEl.innerHTML = `<div class="empty-state"><div class="es-icon">📦</div><div class="es-title">${cfg.emptyTitle}</div><div class="es-sub">${cfg.emptySub}</div></div>`;
      return;
    }

    listEl.innerHTML = batches.map((b, idx) => {
      const farmerIds = b.farmers.map(f => f.id);
      const invoicedCount = b.invoiced_count ?? b.farmers.filter(f => f.invoiced).length;
      const allInvoiced = invoicedCount === b.farmer_count;
      const invoiceProgress = b.farmer_count
        ? `${invoicedCount}/${b.farmer_count} invoiced`
        : '0 invoiced';
      const invoiceColor = allInvoiced ? 'badge-green' : invoicedCount > 0 ? 'badge-orange' : 'badge-gray';
      return `
        <div class="farmer-card" style="display: flex; flex-direction: column; gap: 8px; cursor: default;">
          <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px;">
            <div>
              <div class="fc-name" style="font-size: 16px; font-weight: 700; color: var(--text-primary);">
                Batch: ${b.order_number}
              </div>
              <div class="fc-sub" style="font-size: 13px; color: var(--text-muted);">
                Requisition Date: ${b.requisition_date || 'N/A'} · ${b.farmer_count} client(s)
                &nbsp;<span class="badge ${invoiceColor}" style="font-size: 11px;">${invoiceProgress}</span>
              </div>
            </div>
            <div style="display: flex; gap: 8px;">
              <button class="btn btn-primary btn-download-batch" data-order="${b.order_number}" data-date="${b.requisition_date || ''}" data-ids="${farmerIds.join(',')}" style="height: 32px; padding: 0 12px; font-size: 12px; display: flex; align-items: center; gap: 6px;">
                <i data-lucide="download" style="width: 14px; height: 14px;"></i> Download Form
              </button>
              <button class="btn btn-secondary btn-upload-invoices" data-order="${b.order_number}" style="height: 32px; padding: 0 12px; font-size: 12px; display: flex; align-items: center; gap: 6px; border: 1px solid var(--border-color); color: var(--text-primary); background: transparent;">
                <i data-lucide="upload" style="width: 14px; height: 14px;"></i> Upload Invoices
              </button>
            </div>
          </div>
          <div style="border-top: 1px solid var(--border-color); padding-top: 8px; margin-top: 4px;">
            <div style="font-size: 11px; text-transform: uppercase; font-weight: 600; color: var(--text-muted); margin-bottom: 4px;">Included Clients:</div>
            <div style="font-size: 13px; color: var(--text-primary); line-height: 1.4;">
              ${b.farmers.map(f => `
                <span class="badge ${f.invoiced ? 'badge-green' : 'badge-gray'}" style="margin: 2px 4px 2px 0; display: inline-flex; align-items: center; gap: 4px;" title="${f.invoiced ? ('Invoice: ' + (f.invoice_number || '—') + (f.invoice_amount ? ' · KES ' + f.invoice_amount : '') + (f.balance_due ? ' · Bal: ' + f.balance_due : '')) : 'No invoice uploaded'}">
                  ${f.invoiced ? '✅' : '⏳'} ${f.customer_name} (${f.county || 'N/A'})
                </span>
              `).join('')}
            </div>
          </div>
        </div>
      `;
    }).join('');


    // Wire download buttons
    listEl.querySelectorAll('.btn-download-batch').forEach(btn => {
      btn.addEventListener('click', async (e) => {
        e.preventDefault();
        e.stopPropagation();

        const orderNumber = btn.dataset.order;
        const requisitionDate = btn.dataset.date;
        const farmerIds = btn.dataset.ids.split(',');

        btn.disabled = true;
        const origText = btn.innerHTML;
        btn.innerHTML = '<div class="spinner-inline" style="width: 14px; height: 14px; margin: 0;"></div> Downloading...';

        try {
          const rawHeader = initDataHeader();
          const headers = { 'Content-Type': 'application/json', ...rawHeader };
          const payload = {
            order_number: orderNumber,
            requisition_date: requisitionDate,
            farmer_ids: farmerIds
          };

          const response = await fetch('/api/portal/requisition-queue/generate/', {
            method: 'POST',
            headers: headers,
            body: JSON.stringify(payload)
          });

          if (!response.ok) {
            const errData = await response.json().catch(() => ({}));
            throw new Error(errData.error || 'Failed to download batch.');
          }

          const blob = await response.blob();
          const downloadUrl = window.URL.createObjectURL(blob);
          const a = document.createElement('a');
          a.href = downloadUrl;
          a.download = `JBL_Requisition_Form_${orderNumber}.xlsx`;
          document.body.appendChild(a);
          a.click();
          a.remove();
          window.URL.revokeObjectURL(downloadUrl);
          showToast('Form downloaded successfully!', 'success');
        } catch (err) {
          showToast(err.message, 'error');
        } finally {
          btn.disabled = false;
          btn.innerHTML = origText;
          if (window.lucide) window.lucide.createIcons();
        }
      });
    });

    // Wire upload buttons
    listEl.querySelectorAll('.btn-upload-invoices').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();

        const orderNumber = btn.dataset.order;
        const overlay = el('invoice-overlay');
        const overlaySub = el('invoice-overlay-sub');
        const batchNumInput = el('invoice-batch-number');
        const fileInput = el('invoice-file-input');
        const fileInfo = el('invoice-file-info');
        const submitBtn = el('invoice-submit-btn');
        const resultsDiv = el('invoice-results');

        batchNumInput.value = orderNumber;
        overlaySub.textContent = `Batch: ${orderNumber}`;

        // Reset state
        fileInput.value = '';
        fileInfo.style.display = 'none';
        fileInfo.textContent = '';
        submitBtn.disabled = true;
        resultsDiv.style.display = 'none';

        overlay.classList.add('open');
      });
    });

    if (window.lucide) {
      window.lucide.createIcons();
    }
  }

  function renderFarmerList(listEl, farmers, cfg, qKey) {
    if (!farmers.length) {
      listEl.innerHTML = `<div class="empty-state"><div class="es-icon">✅</div><div class="es-title">${cfg.emptyTitle}</div><div class="es-sub">${cfg.emptySub}</div></div>`;
      return;
    }
    listEl.innerHTML = farmers.map((f, i) => `
      <div class="farmer-card${qKey === 'requisition' ? ' requisition-card' : ''}" data-qkey="${qKey}" data-idx="${i}" id="fc-${qKey}-${i}">
        ${qKey === 'requisition' ? `
          <input type="checkbox" class="farmer-card-checkbox" data-id="${f.id}" ${state.selectedRequisitions.has(f.id) ? 'checked' : ''} onclick="event.stopPropagation();">
        ` : ''}
        <div style="flex: 1;">
          <div class="fc-name">${f.customer_name || f.national_id || f.primary_phone || 'Unknown'}</div>
          <div class="fc-sub">${fmt(f.county)}${f.sub_county ? ' · ' + f.sub_county : ''}${f.branch ? ' · ' + f.branch : ''}</div>
          <div class="fc-sub">${f.primary_phone || ''}</div>
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
      listEl.innerHTML = `<div class="empty-state"><div class="es-icon">🔍</div><div class="es-title">${cfg.emptyTitle}</div><div class="es-sub">No matching records found for chosen filters.</div></div>`;
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
            <div class="fc-sub">${fmt(f.county)}${f.sub_county ? ' · ' + f.sub_county : ''}${f.branch ? ' · ' + f.branch : ''}</div>
            <div class="fc-sub">${f.primary_phone || ''}</div>
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
      <button id="pg-prev-${qKey}" ${prev ? '' : 'disabled'}>← Prev</button>
      <span class="pg-info">Page ${pg.page} of ${pg.pages} (${pg.total} total)</span>
      <button id="pg-next-${qKey}" ${next ? '' : 'disabled'}>Next →</button>
    `;
    if (prev) pgEl.querySelector('#pg-prev-' + qKey).addEventListener('click', () => loadQueue(qKey, pg.page - 1));
    if (next) pgEl.querySelector('#pg-next-' + qKey).addEventListener('click', () => loadQueue(qKey, pg.page + 1));
  }

  // ── Detail sheet ──────────────────────────────────────────────────────────
  function openFarmerSheet(farmer, mode) {
    state.selectedFarmer = farmer;
    state.activeMode = mode;

    // Header
    el('sheet-name').textContent = farmer.customer_name || 'Unknown Farmer';
    el('sheet-sub').textContent = [farmer.county, farmer.sub_county, farmer.branch].filter(Boolean).join(' · ') || farmer.primary_phone || '';

    // Info rows
    const infoFields = [
      ['National ID', fmt(farmer.national_id)],
      ['Phone', fmt(farmer.primary_phone)],
      ['HBG Visit', fmtDate(farmer.sign_date)],
      ['JBL Visit', fmtDate(farmer.jbl_visit_date)],
      ['JBL Officer', fmt(farmer.jbl_officer)],
      ['JBL Status', farmer.jbl_visit_status ? `<span class="badge badge-blue">${farmer.jbl_visit_status}</span>` : '—'],
      ['Credit Decision', farmer.credit_decision ? `<span class="badge ${farmer.credit_decision === 'Approved' ? 'badge-green' : 'badge-orange'}">${farmer.credit_decision}</span>` : '—'],
      ['Order No.', farmer.order_number ? `<strong>${farmer.order_number}</strong>` : '—'],
      ['Requisition Date', fmtDate(farmer.requisition_date)],
      ['HB Sales Person', fmt(farmer.hb_sales_person)],
      ['Village', fmt(farmer.village)],
      // Stage 7 — Invoice
      ...(farmer.invoice_number || farmer.invoice_amount || farmer.balance_due ? [
        ['— Invoice —', ''],
        ['Invoice No.', farmer.invoice_number ? `<code style="font-size:12px;">${farmer.invoice_number}</code>` : '—'],
        ['Invoice Date', fmtDate(farmer.invoice_date)],
        ['Invoice Amount', farmer.invoice_amount ? `<strong>KES ${farmer.invoice_amount}</strong>` : '—'],
        ['Discount', farmer.discount ? `KES ${farmer.discount}` : '—'],
        ['Payment', farmer.payment ? `KES ${farmer.payment}` : '—'],
        ['Balance Due', farmer.balance_due
          ? `<span class="badge ${parseFloat(farmer.balance_due) === 0 ? 'badge-green' : 'badge-orange'}">KES ${farmer.balance_due}</span>`
          : '—'],
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
    } else if (mode === 'requisition') {
      const notApproved = farmer.credit_decision !== 'Approved';
      if (notApproved) {
        el('sheet-gate-warning').style.display = 'flex';
        el('sheet-gate-warning').innerHTML = `⚠️ Credit Decision is <strong>${farmer.credit_decision || 'not set'}</strong>. Must be <strong>Approved</strong> to assign an order.`;
        formEl.innerHTML = buildRequisitionForm(farmer);
        footerEl.innerHTML = `<button class="primary" id="btn-submit-req" disabled>Assign Order (Gate: Not Approved)</button>`;
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
          <select id="jbl-status"><option value="">— Select —</option>${statusOptions}</select>
        </div>
        <div class="form-row">
          <label>Officer Name</label>
          <input type="text" id="jbl-officer" placeholder="Your name" value="${farmer.jbl_officer || ''}">
        </div>
        <div class="form-row">
          <label>Comment (optional)</label>
          <textarea id="jbl-comment" rows="2" placeholder="Additional notes...">${farmer.jbl_visit_comment || ''}</textarea>
        </div>
        <div class="form-row" style="border-bottom: none; background: transparent; padding: 12px 0 0;">
          <button type="button" id="btn-gps" style="width: 100%; height: 38px; display: flex; align-items: center; justify-content: center; gap: 8px;">
            📍 Capture GPS Location
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
      btn.innerHTML = '⏳ Capturing Location...';
      navigator.geolocation.getCurrentPosition(
        position => {
          const lat = position.coords.latitude;
          const lng = position.coords.longitude;
          el('jbl-lat').value = lat;
          el('jbl-lng').value = lng;
          el('gps-coords').innerHTML = `Location captured ✓<br><span style="font-family: monospace; font-size: 12px; color: var(--color-success)">Lat: ${lat.toFixed(6)}, Lng: ${lng.toFixed(6)}</span>`;
          btn.innerHTML = '📍 Location Captured';
          btn.disabled = false;
          showToast('GPS location captured ✓', 'success');
        },
        error => {
          btn.disabled = false;
          btn.innerHTML = '📍 Try Capture Again';
          let msg = 'Failed to get location';
          if (error.code === error.PERMISSION_DENIED) msg = 'Location permission denied';
          else if (error.code === error.POSITION_UNAVAILABLE) msg = 'Location unavailable';
          else if (error.code === error.TIMEOUT) msg = 'Location request timed out';
          el('gps-coords').textContent = '⚠️ ' + msg;
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
    return `
      <div class="form-section">
        <div class="form-row">
          <label>Credit Decision</label>
          <select id="credit-decision"><option value="">— Select —</option>${decisionOptions}</select>
        </div>
      </div>
      ${farmer.jbl_visit_comment ? `<div class="info-row"><span class="ir-label">JBL Comment</span><span class="ir-value">${farmer.jbl_visit_comment}</span></div>` : ''}
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

  // ── Submit handlers ───────────────────────────────────────────────────────
  async function submitJblVisit() {
    const farmer = state.selectedFarmer;
    if (!farmer) return;
    const visitDate = el('jbl-date')?.value || '';
    const visitStatus = el('jbl-status')?.value || '';
    const officer = el('jbl-officer')?.value || '';
    const comment = el('jbl-comment')?.value || '';
    const latitude = el('jbl-lat')?.value || '';
    const longitude = el('jbl-lng')?.value || '';
    if (!visitStatus) { showToast('Please select a visit status', 'error'); return; }

    const btn = el('btn-submit-jbl');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-inline"></span> Saving…';

    const { ok, data } = await apiFetch('/jbl-queue/' + farmer.id + '/', {
      method: 'POST',
      body: JSON.stringify({
        visit_date: visitDate,
        visit_status: visitStatus,
        officer: officer,
        comment: comment,
        latitude: latitude,
        longitude: longitude
      }),
    });

    btn.disabled = false;
    btn.textContent = 'Log JBL Visit';
    if (!ok) { showToast(data.error || 'Save failed', 'error'); return; }
    showToast('JBL visit logged ✓', 'success');
    closeSheet();
    reloadCurrentQueue();
    loadDashboard();
  }

  async function submitCreditDecision() {
    const farmer = state.selectedFarmer;
    if (!farmer) return;
    const decision = el('credit-decision')?.value || '';
    if (!decision) { showToast('Please select a decision', 'error'); return; }

    const btn = el('btn-submit-credit');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-inline"></span> Saving…';

    const { ok, data } = await apiFetch('/credit-queue/' + farmer.id + '/', {
      method: 'POST',
      body: JSON.stringify({ decision }),
    });

    btn.disabled = false;
    btn.textContent = 'Set Credit Decision';
    if (!ok) { showToast(data.error || 'Save failed', 'error'); return; }
    showToast('Credit decision saved ✓', 'success');
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
    btn.innerHTML = '<span class="spinner-inline"></span> Saving…';

    const { ok, status, data } = await apiFetch('/requisition-queue/' + farmer.id + '/', {
      method: 'POST',
      body: JSON.stringify({ order_number: orderNumber, requisition_date: reqDate }),
    });

    btn.disabled = false;
    btn.textContent = 'Assign Order Number';
    if (!ok) {
      if (status === 403) { showToast('⛔ ' + (data.error || 'Credit not approved'), 'error'); }
      else { showToast(data.error || 'Save failed', 'error'); }
      return;
    }
    showToast('Order assigned ✓', 'success');
    closeSheet();
    reloadCurrentQueue();
    loadDashboard();
  }

  function reloadCurrentQueue() {
    const p = state.activePage;
    if (queueConfig[p]) loadQueue(p, state.pages[p] || 1);
  }

  // ── Filters Event Listeners ────────────────────────────────────────────────
  el('filter-county')?.addEventListener('change', e => {
    state.filters.county = e.target.value;
    state.filters.branch = ''; // reset branch if county changed
    const qKey = state.activePage;
    updateFilterOptions(state.queues[qKey] || []);
    applyFilters();
  });

  el('filter-branch')?.addEventListener('change', e => {
    state.filters.branch = e.target.value;
    applyFilters();
  });

  el('btn-clear-filters')?.addEventListener('click', () => {
    state.filters.county = '';
    state.filters.branch = '';
    const qKey = state.activePage;
    updateFilterOptions(state.queues[qKey] || []);
    applyFilters();
  });

  // ── Search (All Cases tab) ────────────────────────────────────────────────
  let searchTimer;
  el('all-search')?.addEventListener('input', e => {
    clearTimeout(searchTimer);
    state.search = e.target.value.trim();
    searchTimer = setTimeout(() => loadQueue('all', 1), 400);
  });

  // ── Meta (dropdown values) ────────────────────────────────────────────────
  async function loadMeta() {
    const { ok, data } = await apiFetch('/meta/');
    if (!ok) return;
    state.metaStatuses = data.jbl_visit_statuses || [];
    state.metaDecisions = data.credit_decisions || [];
  }

  // ── Page router ───────────────────────────────────────────────────────────
  function loadPage(page) {
    if (page === 'dashboard') loadDashboard();
    else if (queueConfig[page]) loadQueue(page, 1);
  }

  // ── Bootstrap ─────────────────────────────────────────────────────────────
  async function init() {
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

  // Bind Generate Form Button
  el('btn-generate-requisition')?.addEventListener('click', async () => {
    const orderNoInput = el('batch-order-num');
    const reqDateInput = el('batch-req-date');
    if (!orderNoInput || !reqDateInput) return;

    const order_number = orderNoInput.value.trim();
    const requisition_date = reqDateInput.value.trim();

    if (!order_number) {
      alert('Please enter an Order Number / Batch Ref.');
      return;
    }
    if (!requisition_date) {
      alert('Please select a Requisition Date.');
      return;
    }

    const farmer_ids = Array.from(state.selectedRequisitions);
    if (!farmer_ids.length) {
      alert('No farmers selected.');
      return;
    }

    try {
      showToast('Generating requisition form...');
      const response = await fetch(apiBase() + '/requisition-queue/generate/', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...initDataHeader(),
          'X-CSRFToken': getCookie('csrftoken') || ''
        },
        body: JSON.stringify({
          farmer_ids,
          order_number,
          requisition_date
        })
      });

      if (!response.ok) {
        let errText = 'Failed to generate requisition form.';
        try {
          const errJson = await response.json();
          if (errJson.error) errText = errJson.error;
        } catch(e) {}
        showToast(errText, 'error');
        return;
      }

      let filename = `JBL_Requisition_Form_${order_number}.xlsx`;
      const cd = response.headers.get('Content-Disposition');
      if (cd && cd.includes('filename=')) {
        const m = cd.match(/filename="([^"]+)"/);
        if (m && m[1]) filename = m[1];
      }

      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);

      showToast('Form downloaded successfully!', 'success');

      // Clear selection & inputs, then reload
      state.selectedRequisitions.clear();
      orderNoInput.value = '';
      reqDateInput.value = '';
      updateBatchPanel();
      
      // Reload current queue
      loadQueue('requisition', 1);
    } catch (err) {
      console.error(err);
      showToast('An error occurred during submission.', 'error');
    }
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

  // ── Invoice Upload Handlers ────────────────────────────────────────────────
  const invoiceOverlay = el('invoice-overlay');
  const invoiceOverlayClose = el('invoice-overlay-close');
  const invoiceUploadForm = el('invoice-upload-form');
  const invoiceFileInput = el('invoice-file-input');
  const invoiceFileInfo = el('invoice-file-info');
  const invoiceSubmitBtn = el('invoice-submit-btn');
  const invoiceResults = el('invoice-results');
  const invoiceResultsSummary = el('invoice-results-summary');
  const invoiceResultsList = el('invoice-results-list');

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
      if (!String(file.name || '').toLowerCase().endsWith('.pdf')) {
        showToast('Only PDF files are supported.', 'error');
        invoiceFileInput.value = '';
        invoiceFileInfo.style.display = 'none';
        invoiceSubmitBtn.disabled = true;
        return;
      }
      invoiceFileInfo.textContent = `Selected: ${file.name} (${(file.size / 1024).toFixed(1)} KB)`;
      invoiceFileInfo.style.display = 'block';
      invoiceSubmitBtn.disabled = false;
    } else {
      invoiceFileInfo.style.display = 'none';
      invoiceSubmitBtn.disabled = true;
    }
  });

  invoiceUploadForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const file = invoiceFileInput.files[0];
    if (!file) return;

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
        const customerName = escapeHtml(r.customer_name || '—');
        const invoiceNo = escapeHtml(r.invoice_no || '—');
        const status = escapeHtml(r.status || 'Unmatched');
        const reason = r.reason ? `<div style="font-size:11px; color:#7f1d1d; margin-top:2px;">${escapeHtml(r.reason)}</div>` : '';
        const parsed = !matched ? `
          <div style="font-size:11px; color:#475569; margin-top:4px; line-height:1.45;">
            Parsed ID: <strong>${escapeHtml(r.parsed_national_id || '�')}</strong> �
            Phone: <strong>${escapeHtml(r.parsed_phone || '�')}</strong> �
            Selected order: <strong>${escapeHtml(r.selected_order_number || res.order_number || '�')}</strong><br>
            Batch candidates: ${escapeHtml(r.batch_candidate_count ?? '�')} �
            ID matches: ${escapeHtml(r.batch_id_match_count ?? '�')} �
            Phone matches: ${escapeHtml(r.batch_phone_match_count ?? '�')} �
            Name matches: ${escapeHtml(r.batch_name_match_count ?? '�')}
          </div>` : '';
        const outside = (r.outside_batch_matches || []).length ? `
          <div style="font-size:11px; color:#7c2d12; margin-top:4px; line-height:1.45;">
            Possible match outside selected order:<br>
            ${(r.outside_batch_matches || []).map(m => `${escapeHtml(m.customer_name || '�')} � ID ${escapeHtml(m.national_id || '�')} � ${escapeHtml(m.primary_phone || '�')} � Order ${escapeHtml(m.order_number || '�')} � Status ${escapeHtml(m.status || '�')}`).join('<br>')}
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
      invoiceSubmitBtn.disabled = false;
      invoiceSubmitBtn.textContent = origBtnText;
    }
  });

  init();

})();
