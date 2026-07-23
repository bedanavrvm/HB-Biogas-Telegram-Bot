(function () {
  'use strict';

  let deps = {};
  let state = {
    page: 1,
    status: '',
    search: '',
    loading: false,
    selectedInvoice: null,
  };
  let searchTimer = null;
  let candidateTimer = null;

  function el(id) {
    return deps.el ? deps.el(id) : document.getElementById(id);
  }

  function escapeHtml(value) {
    return deps.escapeHtml ? deps.escapeHtml(value) : String(value ?? '').replace(/[&<>"']/g, function (ch) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch];
    });
  }

  function fmtDate(value) {
    return deps.fmtDate ? deps.fmtDate(value) : (value || '-');
  }

  function csrfHeader() {
    const token = deps.getCookie ? deps.getCookie('csrftoken') : '';
    return token ? { 'X-CSRFToken': token } : {};
  }

  function money(value) {
    if (value === null || value === undefined || value === '') return '-';
    return 'KES ' + escapeHtml(value);
  }

  function badgeClass(status) {
    return {
      matched: 'badge-green',
      unmatched: 'badge-orange',
      ambiguous: 'badge-blue',
      ignored: 'badge-grey',
      parse_failed: 'badge-red',
      needs_review: 'badge-orange',
    }[status] || 'badge-grey';
  }

  function renderSummary(summary) {
    const target = el('invoice-pool-summary');
    if (!target) return;
    const items = [
      { label: 'Batches', value: summary.batch_count || 0 },
      { label: 'Parsed invoices', value: summary.invoice_count || 0 },
      { label: 'Unmatched', value: summary.unmatched_count || 0 },
      { label: 'Matched', value: summary.matched_count || 0 },
      { label: 'Ambiguous', value: summary.ambiguous_count || 0 },
    ];
    target.innerHTML = deps.summaryGrid
      ? deps.summaryGrid(items)
      : items.map(function (item) {
        return '<div class="batch-summary-item"><strong>' + escapeHtml(item.value) + '</strong><span>' + escapeHtml(item.label) + '</span></div>';
      }).join('');
  }

  function renderBatches(batches) {
    const target = el('invoice-pool-batches');
    if (!target) return;
    if (!batches.length) {
      target.innerHTML = '<div class="empty-state"><div class="es-title">No invoice uploads yet</div><div class="es-sub">Upload an HB invoice PDF to start the pool.</div></div>';
      return;
    }
    target.innerHTML = batches.map(function (batch) {
      const drive = batch.drive_url
        ? '<button class="btn btn-secondary invoice-drive-link" data-url="' + escapeHtml(batch.drive_url) + '">Open PDF</button>'
        : '<span class="badge badge-grey">No Drive link</span>';
      return [
        '<div class="farmer-card batch-card" style="cursor:default;">',
        '<div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start;flex-wrap:wrap;">',
        '<div>',
        '<div class="fc-name">' + escapeHtml(batch.original_filename || 'Invoice upload') + '</div>',
        '<div class="fc-sub">' + escapeHtml(fmtDate(batch.created_at)) + (batch.uploaded_by ? ' | ' + escapeHtml(batch.uploaded_by) : '') + '</div>',
        '<div class="fc-badges">',
        '<span class="badge ' + badgeClass(batch.status) + '">' + escapeHtml(batch.status || '-') + '</span>',
        '<span class="badge badge-grey">' + escapeHtml(batch.total_parsed || 0) + ' parsed</span>',
        '<span class="badge badge-green">' + escapeHtml(batch.matched_count || 0) + ' matched</span>',
        '<span class="badge badge-orange">' + escapeHtml(batch.unmatched_count || 0) + ' unmatched</span>',
        '</div>',
        batch.error ? '<div class="batch-warning" style="margin-top:8px;">' + escapeHtml(batch.error) + '</div>' : '',
        '</div>',
        '<div style="display:flex;gap:8px;flex-wrap:wrap;">',
        '<button class="btn btn-secondary invoice-batch-filter" data-batch="' + escapeHtml(batch.id) + '">View invoices</button>',
        drive,
        '</div>',
        '</div>',
        '</div>',
      ].join('');
    }).join('');
    target.querySelectorAll('.invoice-drive-link').forEach(function (btn) {
      btn.addEventListener('click', function () {
        if (deps.openPortalLink) deps.openPortalLink(btn.dataset.url);
        else window.open(btn.dataset.url, '_blank', 'noopener');
      });
    });
    target.querySelectorAll('.invoice-batch-filter').forEach(function (btn) {
      btn.addEventListener('click', function () {
        load(1, { batch_id: btn.dataset.batch || '' });
      });
    });
  }

  function renderInvoices(invoices) {
    const target = el('invoice-pool-list');
    if (!target) return;
    if (!invoices.length) {
      target.innerHTML = '<div class="empty-state"><div class="es-title">No invoices found</div><div class="es-sub">Try a different status or search term.</div></div>';
      return;
    }
    target.innerHTML = invoices.map(function (invoice) {
      const matched = invoice.matched_farmer_name || invoice.matched_order_number
        ? '<div class="fc-sub">Matched: ' + escapeHtml(invoice.matched_farmer_name || '-') + (invoice.matched_order_number ? ' | Order ' + escapeHtml(invoice.matched_order_number) : '') + '</div>'
        : '<div class="fc-sub">No customer/order match yet</div>';
      const actions = [
        '<button class="btn btn-secondary invoice-match-action" data-invoice="' + escapeHtml(invoice.id) + '">Match</button>',
        invoice.status === 'matched' ? '<button class="btn btn-secondary invoice-unmatch-action" data-invoice="' + escapeHtml(invoice.id) + '">Unmatch</button>' : '',
        invoice.status !== 'ignored' ? '<button class="btn btn-secondary invoice-ignore-action" data-invoice="' + escapeHtml(invoice.id) + '">Ignore</button>' : '',
      ].join('');
      return [
        '<div class="farmer-card batch-card" style="cursor:default;">',
        '<div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start;flex-wrap:wrap;">',
        '<div>',
        '<div class="fc-name">Invoice ' + escapeHtml(invoice.invoice_no || '-') + '</div>',
        '<div class="fc-sub">' + escapeHtml(invoice.customer_name || 'Unknown customer') + ' | ID ' + escapeHtml(invoice.customer_id || '-') + ' | ' + escapeHtml(invoice.customer_phone || '-') + '</div>',
        matched,
        '<div class="fc-sub">' + escapeHtml(invoice.batch_filename || '-') + ' | Page ' + escapeHtml(invoice.page || '-') + ' | ' + escapeHtml(fmtDate(invoice.invoice_date)) + '</div>',
        '<div class="fc-badges">',
        '<span class="badge ' + badgeClass(invoice.status) + '">' + escapeHtml(invoice.status || '-') + '</span>',
        '<span class="badge badge-grey">Amount: ' + money(invoice.invoice_amount) + '</span>',
        '<span class="badge badge-grey">Payment: ' + money(invoice.payment) + '</span>',
        '<span class="badge badge-grey">Balance: ' + money(invoice.balance_due) + '</span>',
        '</div>',
        invoice.balance_due_check ? '<div class="fc-sub">Balance check: ' + escapeHtml(invoice.balance_due_check) + '</div>' : '',
        invoice.review_notes ? '<div class="batch-warning" style="margin-top:8px;">' + escapeHtml(invoice.review_notes) + '</div>' : '',
        '</div>',
        '<div style="display:flex;gap:8px;flex-wrap:wrap;">' + actions + '</div>',
        '</div>',
        '</div>',
      ].join('');
    }).join('');
    target.querySelectorAll('.invoice-match-action').forEach(function (btn) {
      btn.addEventListener('click', function () {
        const invoice = invoices.find(function (item) { return item.id === btn.dataset.invoice; });
        openMatchOverlay(invoice || { id: btn.dataset.invoice });
      });
    });
    target.querySelectorAll('.invoice-unmatch-action').forEach(function (btn) {
      btn.addEventListener('click', function () { unmatchInvoice(btn.dataset.invoice); });
    });
    target.querySelectorAll('.invoice-ignore-action').forEach(function (btn) {
      btn.addEventListener('click', function () { ignoreInvoice(btn.dataset.invoice); });
    });
  }

  function renderPagination(pagination) {
    const target = el('pg-invoices');
    if (!target || !pagination || pagination.pages <= 1) {
      if (target) target.innerHTML = '';
      return;
    }
    const prev = pagination.page > 1;
    const next = pagination.page < pagination.pages;
    target.innerHTML = [
      '<button id="pg-prev-invoices" ' + (prev ? '' : 'disabled') + '>Prev</button>',
      '<span class="pg-info">Page ' + escapeHtml(pagination.page) + ' of ' + escapeHtml(pagination.pages) + ' (' + escapeHtml(pagination.total) + ' total)</span>',
      '<button id="pg-next-invoices" ' + (next ? '' : 'disabled') + '>Next</button>',
    ].join('');
    if (prev) el('pg-prev-invoices').addEventListener('click', function () { load(pagination.page - 1); });
    if (next) el('pg-next-invoices').addEventListener('click', function () { load(pagination.page + 1); });
  }

  async function load(page, extra) {
    if (state.loading) return;
    state.loading = true;
    state.page = page || 1;
    const list = el('invoice-pool-list');
    if (list) list.innerHTML = '<div class="empty-state"><div class="spinner-inline"></div></div>';
    const params = new URLSearchParams({ page: String(state.page) });
    if (state.status) params.set('status', state.status);
    if (state.search) params.set('search', state.search);
    if (extra && extra.batch_id) params.set('batch_id', extra.batch_id);
    const result = await deps.apiFetch('/invoice-pool/?' + params.toString());
    state.loading = false;
    if (!result.ok || !result.data?.ok) {
      if (list) list.innerHTML = '<div class="empty-state"><div class="es-title">Could not load invoices</div><div class="es-sub">Refresh and try again.</div></div>';
      return;
    }
    renderSummary(result.data.summary || {});
    renderBatches(result.data.batches || []);
    renderInvoices(result.data.invoices || []);
    renderPagination(result.data.pagination || {});
    if (window.lucide) window.lucide.createIcons();
  }

  function openMatchOverlay(invoice) {
    state.selectedInvoice = invoice;
    const overlay = el('invoice-match-overlay');
    const summary = el('invoice-match-summary');
    const search = el('invoice-match-search');
    const note = el('invoice-match-note');
    const candidates = el('invoice-match-candidates');
    if (!overlay) return;
    if (summary) {
      summary.innerHTML = [
        '<div class="batch-client-row">',
        '<div class="name">Invoice ' + escapeHtml(invoice.invoice_no || '-') + '</div>',
        '<div class="meta">' + escapeHtml(invoice.customer_name || 'Unknown customer') + ' | ID ' + escapeHtml(invoice.customer_id || '-') + ' | ' + escapeHtml(invoice.customer_phone || '-') + '</div>',
        '<div class="meta">Amount ' + money(invoice.invoice_amount) + ' | Balance ' + money(invoice.balance_due) + '</div>',
        '</div>',
      ].join('');
    }
    if (search) search.value = [invoice.customer_id, invoice.customer_phone, invoice.customer_name].filter(Boolean)[0] || '';
    if (note) note.value = '';
    if (candidates) candidates.innerHTML = '<div class="empty-state"><div class="spinner-inline"></div></div>';
    overlay.classList.add('open');
    searchCandidates();
    setTimeout(function () { search?.focus(); }, 50);
  }

  function closeMatchOverlay() {
    el('invoice-match-overlay')?.classList.remove('open');
    state.selectedInvoice = null;
  }

  async function searchCandidates() {
    const search = (el('invoice-match-search')?.value || '').trim();
    const target = el('invoice-match-candidates');
    if (!target) return;
    if (search.length < 2) {
      target.innerHTML = '<div class="empty-state"><div class="es-title">Search farmer records</div><div class="es-sub">Use name, ID, phone, order, or customer no.</div></div>';
      return;
    }
    target.innerHTML = '<div class="empty-state"><div class="spinner-inline"></div></div>';
    const result = await deps.apiFetch('/invoice-pool/farmers/?search=' + encodeURIComponent(search));
    const farmers = result.data?.farmers || [];
    if (!result.ok || !result.data?.ok || !farmers.length) {
      target.innerHTML = '<div class="empty-state"><div class="es-title">No matching farmers</div><div class="es-sub">Try another ID, phone, name, or order.</div></div>';
      return;
    }
    target.innerHTML = farmers.map(function (farmer) {
      const conflict = farmer.has_invoice
        ? '<div class="batch-warning" style="margin-top:8px;">' + escapeHtml(farmer.invoice_conflict_label || 'This farmer already has an invoice.') + '</div>'
        : '';
      return [
        '<div class="farmer-card batch-card" style="cursor:default;">',
        '<div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start;flex-wrap:wrap;">',
        '<div>',
        '<div class="fc-name">' + escapeHtml(farmer.customer_name || 'Unnamed farmer') + '</div>',
        '<div class="fc-sub">ID ' + escapeHtml(farmer.national_id || '-') + ' | ' + escapeHtml(farmer.primary_phone || '-') + '</div>',
        '<div class="fc-sub">' + escapeHtml(farmer.county || '-') + (farmer.order_number ? ' | Order ' + escapeHtml(farmer.order_number) : '') + (farmer.customer_no ? ' | Customer No ' + escapeHtml(farmer.customer_no) : '') + '</div>',
        conflict,
        '</div>',
        '<button class="btn btn-primary invoice-select-candidate" data-farmer="' + escapeHtml(farmer.id) + '"' + (farmer.has_invoice ? ' data-conflict="1"' : '') + '>Select</button>',
        '</div>',
        '</div>',
      ].join('');
    }).join('');
    target.querySelectorAll('.invoice-select-candidate').forEach(function (btn) {
      btn.addEventListener('click', function () {
        matchInvoiceToFarmer(btn.dataset.farmer, btn.dataset.conflict === '1');
      });
    });
  }

  async function matchInvoiceToFarmer(farmerId, hasConflict) {
    if (!state.selectedInvoice?.id) return;
    if (hasConflict && !window.confirm('This farmer already has an invoice. Continue only if you are replacing/correcting it.')) return;
    const note = el('invoice-match-note')?.value || '';
    const response = await deps.apiFetch('/invoice-pool/' + encodeURIComponent(state.selectedInvoice.id) + '/match/', {
      method: 'POST',
      body: JSON.stringify({ farmer_id: farmerId, note: note }),
    });
    if (!response.ok || !response.data?.ok) {
      deps.showToast(response.data?.error || 'Could not match invoice.', 'error');
      return;
    }
    deps.showToast('Invoice matched.', 'success');
    closeMatchOverlay();
    load(state.page);
  }

  async function unmatchInvoice(invoiceId) {
    if (!window.confirm('Unmatch this invoice and clear it from the linked farmer record where applicable?')) return;
    const note = window.prompt('Optional unmatch note:', '') || '';
    const response = await deps.apiFetch('/invoice-pool/' + encodeURIComponent(invoiceId) + '/unmatch/', {
      method: 'POST',
      body: JSON.stringify({ note: note }),
    });
    if (!response.ok || !response.data?.ok) {
      deps.showToast(response.data?.error || 'Could not unmatch invoice.', 'error');
      return;
    }
    deps.showToast('Invoice unmatched.', 'success');
    load(state.page);
  }

  async function ignoreInvoice(invoiceId) {
    const note = window.prompt('Why should this invoice be ignored?');
    if (!note) return;
    const response = await deps.apiFetch('/invoice-pool/' + encodeURIComponent(invoiceId) + '/ignore/', {
      method: 'POST',
      body: JSON.stringify({ note: note }),
    });
    if (!response.ok || !response.data?.ok) {
      deps.showToast(response.data?.error || 'Could not ignore invoice.', 'error');
      return;
    }
    deps.showToast('Invoice ignored.', 'success');
    load(state.page);
  }

  function bindFilters() {
    el('invoice-pool-status')?.addEventListener('change', function (event) {
      state.status = event.target.value || '';
      load(1);
    });
    el('invoice-pool-search')?.addEventListener('input', function (event) {
      clearTimeout(searchTimer);
      state.search = event.target.value.trim();
      searchTimer = setTimeout(function () { load(1); }, 350);
    });
    el('invoice-pool-clear')?.addEventListener('click', function () {
      state.status = '';
      state.search = '';
      if (el('invoice-pool-status')) el('invoice-pool-status').value = '';
      if (el('invoice-pool-search')) el('invoice-pool-search').value = '';
      load(1);
    });
  }

  function bindMatchOverlay() {
    el('invoice-match-close')?.addEventListener('click', closeMatchOverlay);
    el('invoice-match-overlay')?.addEventListener('click', function (event) {
      if (event.target === el('invoice-match-overlay')) closeMatchOverlay();
    });
    el('invoice-match-search')?.addEventListener('input', function () {
      clearTimeout(candidateTimer);
      candidateTimer = setTimeout(searchCandidates, 300);
    });
  }

  function bindUpload() {
    const form = el('invoice-pool-upload-form');
    if (!form) return;
    form.addEventListener('submit', async function (event) {
      event.preventDefault();
      const fileInput = el('invoice-pool-file');
      const resultBox = el('invoice-pool-upload-result');
      const submit = el('invoice-pool-upload-submit');
      const file = fileInput?.files ? fileInput.files[0] : null;
      if (!file) return deps.showToast('Select an invoice PDF first.', 'error');
      if (!String(file.name || '').toLowerCase().endsWith('.pdf')) return deps.showToast('Only PDF invoices are supported.', 'error');
      const formData = new FormData();
      formData.append('file', file);
      if (deps.setButtonLoading) deps.setButtonLoading(submit, true, 'Uploading...');
      const response = await deps.portalApi.postForm('/invoice-pool/upload/', formData, deps.tg, csrfHeader());
      if (deps.setButtonLoading) deps.setButtonLoading(submit, false);
      const data = response.data || {};
      if (!response.ok || data.ok === false) {
        if (resultBox) resultBox.innerHTML = '<div class="batch-warning" style="margin-top:10px;">' + escapeHtml(data.error || 'Invoice upload failed.') + '</div>';
        deps.showToast(data.error || 'Invoice upload failed.', 'error');
        return;
      }
      if (fileInput) fileInput.value = '';
      if (resultBox) {
        resultBox.innerHTML = '<span class="badge badge-green">Parsed ' + escapeHtml(data.total_parsed || 0) + ' invoice(s)</span> <span class="badge badge-orange">' + escapeHtml(data.unmatched_count || 0) + ' unmatched</span>';
      }
      deps.showToast('Invoice uploaded to pool.', 'success');
      load(1);
    });
  }

  function init(inputDeps) {
    deps = inputDeps || {};
    bindFilters();
    bindUpload();
    bindMatchOverlay();
  }

  window.PortalMiniAppInvoices = {
    init,
    load,
  };
})();
