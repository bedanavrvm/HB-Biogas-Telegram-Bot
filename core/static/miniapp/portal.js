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
    queues: { jbl: [], credit: [], requisition: [], deferred: [], all: [] },
    pagination: {},
    pages: { jbl: 1, credit: 1, requisition: 1, deferred: 1, all: 1 },
    search: '',
    metaStatuses: [],
    metaDecisions: [],
    selectedFarmer: null,
    activeMode: null, // 'jbl_visit' | 'credit' | 'requisition'
  };

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
    const labels = ['—', 'Awaiting JBL', 'JBL Visited', 'Credit Set', 'Ordered'];
    const styles = ['', 'badge-grey', 'badge-blue', 'badge-orange', 'badge-green'];
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
    document.querySelectorAll('.page').forEach(p => p.classList.toggle('active', p.id === 'page-' + page));
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

    const farmers = data.farmers || [];
    state.queues[qKey] = farmers;
    state.pagination[qKey] = data.pagination || {};
    state.pages[qKey] = page;

    renderFarmerList(listEl, farmers, cfg, qKey);
    renderPagination(qKey, data.pagination);
  }

  function renderFarmerList(listEl, farmers, cfg, qKey) {
    if (!farmers.length) {
      listEl.innerHTML = `<div class="empty-state"><div class="es-icon">✅</div><div class="es-title">${cfg.emptyTitle}</div><div class="es-sub">${cfg.emptySub}</div></div>`;
      return;
    }
    listEl.innerHTML = farmers.map((f, i) => `
      <div class="farmer-card" data-qkey="${qKey}" data-idx="${i}" id="fc-${qKey}-${i}">
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
    `).join('');

    listEl.querySelectorAll('.farmer-card').forEach(card => {
      card.addEventListener('click', () => {
        const qKey = card.dataset.qkey;
        const idx = parseInt(card.dataset.idx, 10);
        const farmer = state.queues[qKey][idx];
        openFarmerSheet(farmer, cfg.mode);
      });
    });
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

    el('sheet-overlay').classList.add('open');
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

  init();

})();
