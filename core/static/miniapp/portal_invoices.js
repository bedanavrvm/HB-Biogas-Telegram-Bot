(function () {
  'use strict';

  let deps = {};
  let state = {
    page: 1,
    status: '',
    review: '',
    search: '',
    loading: false,
    workspace: '',
    selectedInvoice: null,
    selectedIds: new Set(),
    candidateScope: 'operational',
  };
  let searchTimer = null;
  let candidateTimer = null;
  let letterPreviewObjectUrl = '';

  function el(id) {
    return deps.el ? deps.el(id) : document.getElementById(id);
  }

  function invoicesScreenIsActive() {
    return document.getElementById('portal-screen')?.dataset.screen === 'invoices';
  }

  function readRoute() {
    const screen = document.getElementById('portal-screen');
    const view = screen?.dataset.invoiceView || 'inbox';
    return {
      view: ['inbox', 'matched', 'ignored', 'all', 'upload', 'detail'].includes(view) ? view : 'inbox',
      invoiceId: screen?.dataset.invoiceId || '',
    };
  }

  function routeUrl(view = 'inbox', invoiceId = '') {
    const base = '/portal/s/invoices/';
    if (view === 'matched') return base + 'matched/';
    if (view === 'ignored') return base + 'ignored/';
    if (view === 'all') return base + 'all/';
    if (view === 'upload') return base + 'upload/';
    if (view === 'detail' && invoiceId) return base + encodeURIComponent(invoiceId) + '/';
    return base;
  }

  function navigate(view = 'inbox', invoiceId = '') {
    const url = routeUrl(view, invoiceId);
    if (window.PortalAppShell?.navigateUrl) {
      window.PortalAppShell.navigateUrl(url);
      return;
    }
    window.location.assign(url);
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

  function canWriteInvoices() {
    return !deps.state || deps.state.capabilities?.has('portal.invoice.write');
  }

  function requestId() {
    return window.crypto?.randomUUID?.() || 'invoice-identity-' + Date.now() + '-' + Math.random().toString(16).slice(2);
  }

  function closeLetterPreview() {
    if (letterPreviewObjectUrl) {
      window.SecureMediaViewer?.revoke(letterPreviewObjectUrl);
      letterPreviewObjectUrl = '';
    }
  }

  async function openLetterPreview(letter) {
    if (!letter?.preview_url) {
      return deps.showToast('This letter version has no in-app preview. Prepare a new version.', 'error');
    }
    const overlay = el('media-viewer-overlay');
    const title = el('media-viewer-title');
    const sub = el('media-viewer-sub');
    const content = el('media-viewer-content');
    if (!overlay || !content || !window.SecureMediaViewer) {
      return deps.showToast('The secure letter viewer is unavailable. Refresh and retry.', 'error');
    }
    closeLetterPreview();
    if (title) title.textContent = 'Corrected-invoice letter';
    if (sub) sub.textContent = 'Version ' + String(letter.version || '-') + ' · ' + String(letter.preview_filename || 'PDF preview');
    content.innerHTML = '<div class="media-viewer-loading" role="status"><span class="spinner-inline" aria-hidden="true"></span> Loading letter…</div>';
    overlay.classList.add('open');
    try {
      const blob = await window.SecureMediaViewer.fetchAuthorizedBlob(letter.preview_url, {
        headers: { 'X-Request-ID': requestId() },
      });
      letterPreviewObjectUrl = window.SecureMediaViewer.renderBlob(content, blob, {
        mimeType: 'text/html',
        name: letter.preview_filename || 'Corrected-invoice letter',
      });
    } catch (error) {
      content.innerHTML = '<p class="media-viewer-error">' + escapeHtml(error.message || 'Could not open the letter preview.') + '</p>';
    }
  }

  function canManageInvoiceIdentity() {
    return !deps.state || deps.state.capabilities?.has('portal.invoice_identity.manage');
  }

  function money(value) {
    if (value === null || value === undefined || value === '') return '-';
    const raw = String(value).replace(/,/g, '').trim();
    const number = Number(raw);
    const display = Number.isFinite(number)
      ? (Number.isInteger(number) ? String(number) : String(number).replace(/\.0+$/, ''))
      : String(value);
    return 'KES ' + escapeHtml(display);
  }

  function hbgDeposit(invoice) {
    return invoice && invoice.hbg_deposit !== undefined && invoice.hbg_deposit !== null && invoice.hbg_deposit !== ''
      ? invoice.hbg_deposit
      : invoice?.payment;
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
    const route = readRoute();
    const needsReview = summary.needs_action_count !== undefined
      ? Number(summary.needs_action_count || 0)
      : Number(summary.draft_count || 0) + Number(summary.unmatched_count || 0) + Number(summary.ambiguous_count || 0);
    const items = route.view === 'upload'
      ? [
          { label: 'Upload batches', value: summary.batch_count || 0 },
          { label: 'Parsed invoices', value: summary.invoice_count || 0 },
          { label: 'Needs review', value: needsReview },
          { label: 'Not parsed', value: summary.parse_failed_batch_count || 0 },
        ]
      : [
          { label: 'Needs review', value: needsReview },
          { label: 'Matched', value: summary.matched_count || 0 },
          { label: 'Ignored', value: summary.ignored_count || 0 },
        ];
    target.innerHTML = items.map(function (item) {
      const key = item.label.toLowerCase().replace(/\s+/g, '-');
      const alert = (key === 'needs-review' || key === 'not-parsed') && Number(item.value) > 0;
      const positive = key === 'matched' && Number(item.value) > 0;
      return '<div class="batch-summary-item invoice-summary-' + key + (alert ? ' has-alert' : '') + (positive ? ' has-positive' : '') + '"><strong>' + escapeHtml(item.value) + '</strong><span>' + escapeHtml(item.label) + '</span></div>';
    }).join('');
  }

  function updateBulkToolbar() {
    const toolbar = el('invoice-bulk-toolbar');
    const count = el('invoice-selected-count');
    if (!canWriteInvoices()) state.selectedIds.clear();
    const selectedCount = state.selectedIds.size;
    if (toolbar) toolbar.style.display = selectedCount ? 'block' : 'none';
    if (count) count.textContent = selectedCount + ' selected';
  }

  function renderInvoices(invoices) {
    const target = el('invoice-pool-list');
    if (!target) return;
    if (!invoices.length) {
      const route = readRoute();
      const copy = route.view === 'matched'
        ? ['No matched invoices', 'Matched invoices will appear here after reconciliation.']
        : route.view === 'ignored'
          ? ['No ignored invoices', 'No invoices have been intentionally excluded from matching.']
          : ['No invoices need review', 'New unmatched or ambiguous invoices will appear here.'];
      target.innerHTML = '<div class="empty-state"><div class="es-title">' + copy[0] + '</div><div class="es-sub">' + copy[1] + '</div></div>';
      return;
    }
    target.innerHTML = invoices.map(function (invoice) {
      const matched = invoice.matched_farmer_name || invoice.matched_order_number
        ? '<span>Matched: ' + escapeHtml(invoice.matched_farmer_name || '-') + (invoice.matched_order_number ? ' | Order ' + escapeHtml(invoice.matched_order_number) : '') + '</span>'
        : '';
      const readiness = invoice.payment_readiness || {};
      const readinessBadge = invoice.status === 'matched' && invoice.matched_order_number
        ? readiness.error
          ? '<span class="badge badge-red">Payment readiness unavailable</span>'
          : readiness.blocked_count > 0
            ? '<span class="badge badge-orange">Payment blocked: ' + escapeHtml(readiness.blocked_count) + '</span>'
            : '<span class="badge badge-green">Payment ready: ' + escapeHtml(readiness.ready_count || 0) + '</span>'
        : '';
      const duplicateBadge = invoice.duplicate_count > 0
        ? '<span class="badge badge-orange">Possible duplicates: ' + escapeHtml(invoice.duplicate_count) + '</span>'
        : '';
      const needsMatch = canWriteInvoices() && ['draft', 'unmatched', 'ambiguous'].includes(invoice.status);
      const primaryAction = needsMatch
        ? '<button class="btn btn-primary invoice-match-action" data-invoice="' + escapeHtml(invoice.id) + '">Review match</button>'
        : '<button class="btn btn-primary invoice-detail-action" data-invoice="' + escapeHtml(invoice.id) + '">Review invoice</button>';
      const secondaryActions = [
        needsMatch ? '<button type="button" class="invoice-detail-action" data-invoice="' + escapeHtml(invoice.id) + '">View details</button>' : '',
        canWriteInvoices() && invoice.status === 'matched' ? '<button type="button" class="invoice-unmatch-action" data-invoice="' + escapeHtml(invoice.id) + '">Unmatch</button>' : '',
        canWriteInvoices() && invoice.status !== 'ignored' ? '<button type="button" class="invoice-ignore-action" data-invoice="' + escapeHtml(invoice.id) + '">Ignore</button>' : '',
        canWriteInvoices() && invoice.status === 'ignored' ? '<button type="button" class="invoice-restore-action" data-invoice="' + escapeHtml(invoice.id) + '">Restore</button>' : '',
      ].filter(Boolean).join('');
      const actions = primaryAction + (secondaryActions ? '<details class="invoice-card-menu"><summary aria-label="More invoice actions">More</summary><div>' + secondaryActions + '</div></details>' : '');
      const checked = state.selectedIds.has(invoice.id) ? ' checked' : '';
      return [
        '<article class="farmer-card invoice-pool-card invoice-status-' + escapeHtml(invoice.status || 'unknown') + (checked ? ' is-selected' : '') + '">',
        '<div class="invoice-card-main">',
        canWriteInvoices() && invoice.status !== 'matched' ? '<input type="checkbox" class="invoice-select-row" data-invoice="' + escapeHtml(invoice.id) + '" aria-label="Select invoice ' + escapeHtml(invoice.invoice_no || '') + '"' + checked + '>' : '<span></span>',
        '<div class="invoice-card-content">',
        '<div class="invoice-card-heading"><div class="fc-name">Invoice ' + escapeHtml(invoice.invoice_no || '-') + '</div><span class="badge ' + badgeClass(invoice.status) + '">' + escapeHtml(invoice.status || '-') + '</span></div>',
        '<div class="invoice-card-customer">' + escapeHtml(invoice.customer_name || 'Unknown invoice holder') + '</div>',
        '<div class="invoice-card-meta"><span>ID ' + escapeHtml(invoice.customer_id || '-') + '</span><span>' + escapeHtml(invoice.customer_phone || '-') + '</span>' + matched + '</div>',
        duplicateBadge ? '<div class="invoice-duplicate-alert">' + duplicateBadge + ' Review before matching.</div>' : '',
        '<div class="fc-badges invoice-card-money">',
        '<span class="badge badge-grey">Amount: ' + money(invoice.invoice_amount) + '</span>',
        '<span class="badge badge-grey">Balance: ' + money(invoice.balance_due) + '</span>',
        readinessBadge,
        '</div>',
        invoice.balance_due_check && String(invoice.balance_due_check).toLowerCase() !== 'ok' ? '<div class="invoice-card-warning">Balance check: ' + escapeHtml(invoice.balance_due_check) + '</div>' : '',
        invoice.review_notes ? '<div class="invoice-card-warning">' + escapeHtml(invoice.review_notes) + '</div>' : '',
        '</div>',
        '</div>',
        '<div class="invoice-card-actions">' + actions + '</div>',
        '</article>',
      ].join('');
    }).join('');
    const visibleIds = new Set(invoices.map(function (invoice) { return invoice.id; }));
    Array.from(state.selectedIds).forEach(function (invoiceId) {
      if (!visibleIds.has(invoiceId)) state.selectedIds.delete(invoiceId);
    });
    target.querySelectorAll('.invoice-select-row').forEach(function (input) {
      input.addEventListener('change', function () {
        if (input.checked) state.selectedIds.add(input.dataset.invoice);
        else state.selectedIds.delete(input.dataset.invoice);
        input.closest('.invoice-pool-card')?.classList.toggle('is-selected', input.checked);
        updateBulkToolbar();
      });
    });
    target.querySelectorAll('.invoice-detail-action').forEach(function (btn) {
      btn.addEventListener('click', function () { openInvoiceDetail(btn.dataset.invoice); });
    });
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
    target.querySelectorAll('.invoice-restore-action').forEach(function (btn) {
      btn.addEventListener('click', function () { restoreInvoice(btn.dataset.invoice); });
    });
    updateBulkToolbar();
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

  function renderUploadHistory(batches) {
    const target = el('invoice-upload-history');
    if (!target) return;
    if (!batches.length) {
      target.innerHTML = '<div class="empty-state"><div class="es-title">No invoice uploads yet</div><div class="es-sub">Upload a PDF when HB invoices are received.</div></div>';
      return;
    }
    target.innerHTML = batches.map(function (batch) {
      const sync = batch.sync_status === 'retryable_failure'
        ? '<span class="badge badge-orange">Drive sync needs retry</span>'
        : batch.sync_status === 'pending'
          ? '<span class="badge badge-blue">Drive sync pending</span>'
          : batch.drive_url
            ? '<span class="badge badge-green">Stored in Drive</span>'
            : '';
      return [
        '<article class="farmer-card invoice-upload-history-card">',
        '<div class="invoice-card-heading"><div class="fc-name">' + escapeHtml(batch.original_filename || 'Invoice PDF') + '</div><span class="badge ' + badgeClass(batch.status) + '">' + escapeHtml(batch.status || '-') + '</span></div>',
        '<div class="invoice-card-meta"><span>' + escapeHtml(fmtDate(batch.created_at)) + '</span><span>' + escapeHtml(batch.total_parsed || 0) + ' parsed</span><span>' + escapeHtml(batch.unmatched_count || 0) + ' unmatched</span></div>',
        '<div class="fc-badges invoice-card-money">' + sync + (batch.error ? '<span class="badge badge-red">' + escapeHtml(batch.error) + '</span>' : '') + '</div>',
        '</article>',
      ].join('');
    }).join('');
  }

  async function loadDetail(invoiceId) {
    const target = el('invoice-detail-page');
    if (!target) return;
    if (!invoiceId) {
      target.innerHTML = '<div class="empty-state"><div class="es-title">Invoice unavailable</div><div class="es-sub">Return to the invoice inbox and choose a record.</div></div>';
      return;
    }
    target.innerHTML = '<div class="empty-state"><div class="spinner-inline"></div><div class="es-sub">Loading invoice detail...</div></div>';
    const result = await deps.apiFetch('/invoice-pool/' + encodeURIComponent(invoiceId) + '/');
    if (!invoicesScreenIsActive() || readRoute().invoiceId !== invoiceId) return;
    if (!result.ok || !result.data?.ok) {
      target.innerHTML = '<div class="empty-state"><div class="es-title">Invoice unavailable</div><div class="es-sub">' + escapeHtml(result.data?.error || 'Refresh the invoice inbox and try again.') + '</div><button type="button" class="btn btn-secondary invoice-detail-back">Back to invoices</button></div>';
      target.querySelector('.invoice-detail-back')?.addEventListener('click', function () { navigate('inbox'); });
      return;
    }
    renderInvoiceDetail(result.data, target, { routeMode: true });
  }

  async function load(page, extra) {
    if (!invoicesScreenIsActive()) return;
    if (state.loading) return;
    state.loading = true;
    try {
      const route = readRoute();
      if (route.view === 'detail') {
        await loadDetail(route.invoiceId);
        return;
      }
      if (state.workspace !== route.view) {
        state.workspace = route.view;
        state.selectedIds.clear();
        state.review = '';
        state.search = '';
      }
      state.page = page || 1;
      const list = el('invoice-pool-list');
      if (list) list.innerHTML = '<div class="empty-state"><div class="spinner-inline"></div></div>';
      const params = new URLSearchParams({ page: String(state.page) });
      if (['inbox', 'matched', 'ignored'].includes(route.view)) params.set('workspace', route.view);
      if (state.status) params.set('status', state.status);
      if (state.review) params.set('review', state.review);
      if (state.search) params.set('search', state.search);
      if (extra && extra.batch_id) params.set('batch_id', extra.batch_id);
      const result = await deps.apiFetch('/invoice-pool/?' + params.toString());
      if (!invoicesScreenIsActive()) return;
      if (!result.ok || !result.data?.ok) {
        if (list) list.innerHTML = '<div class="empty-state"><div class="es-title">Could not load invoices</div><div class="es-sub">Refresh and try again.</div></div>';
        return;
      }
      renderSummary(result.data.summary || {});
      if (route.view === 'upload') {
        renderUploadHistory(result.data.batches || []);
      } else {
        renderInvoices(result.data.invoices || []);
        renderPagination(result.data.pagination || {});
      }
      if (window.lucide) window.lucide.createIcons();
    } catch (_) {
      if (!invoicesScreenIsActive()) return;
      const list = el('invoice-pool-list');
      if (list) list.innerHTML = '<div class="empty-state"><div class="es-title">Could not load invoices</div><div class="es-sub">Refresh and try again.</div></div>';
    } finally {
      state.loading = false;
    }
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
    state.candidateScope = 'operational';
    if (candidates) candidates.innerHTML = '<div class="empty-state"><div class="spinner-inline"></div></div>';
    overlay.classList.add('open');
    searchCandidates();
    setTimeout(function () { search?.focus(); }, 50);
  }

  function closeMatchOverlay() {
    el('invoice-match-overlay')?.classList.remove('open');
    state.selectedInvoice = null;
  }

  function kv(label, value, { wide = false } = {}) {
    return '<div class="invoice-detail-field' + (wide ? ' invoice-detail-field-wide' : '') + '"><div class="meta">' + escapeHtml(label) + '</div><div class="name">' + escapeHtml(value || '-') + '</div></div>';
  }

  function renderInvoiceDetail(data, target = el('invoice-detail-content'), { routeMode = false } = {}) {
    if (!target) return;
    const invoice = data.invoice || {};
    const batch = data.batch || {};
    const events = data.events || [];
    const duplicates = data.duplicates || [];
    const sourceLink = data.source_pdf_url
      ? '<button class="btn btn-secondary invoice-drive-link" data-url="' + escapeHtml(data.source_pdf_url) + '">Open source PDF</button>'
      : '<span class="badge badge-grey">No source PDF link</span>';
    const identity = invoice.identity || {};
    const identityActions = [];
    const hasDifferentIds = identity.discrepancy_codes?.includes('national_id_mismatch');
    const hasMissingId = identity.discrepancy_codes?.includes('national_id_missing');
    if (canManageInvoiceIdentity() && hasDifferentIds && !identity.name_change) {
      identityActions.push('<button type="button" class="btn btn-primary invoice-name-change-start">Request corrected invoice</button>');
    }
    if (canManageInvoiceIdentity() && identity.name_change?.batch_status === 'draft') {
      if (!identity.name_change.latest_letter?.is_current || !identity.name_change.latest_letter?.preview_url) {
        identityActions.push('<button type="button" class="btn btn-primary invoice-name-change-generate">Prepare letter preview</button>');
      }
      if (identity.name_change.latest_letter?.preview_url) {
        identityActions.push('<button type="button" class="btn btn-primary invoice-name-change-preview">Preview v' + escapeHtml(identity.name_change.latest_letter.version) + '</button>');
      }
      if (identity.name_change.latest_letter?.download_url) {
        identityActions.push('<button type="button" class="btn btn-secondary invoice-name-change-download">Download v' + escapeHtml(identity.name_change.latest_letter.version) + '</button>');
      }
      if (identity.name_change.latest_letter?.is_current) {
        identityActions.push('<button type="button" class="btn btn-primary invoice-name-change-sent">Record letter sent</button>');
      }
    }
    if (canManageInvoiceIdentity() && identity.name_change?.status === 'awaiting_replacement') {
      identityActions.push('<button type="button" class="btn btn-primary invoice-name-change-replacement">Confirm replacement invoice</button>');
      identityActions.push('<button type="button" class="btn btn-secondary invoice-name-change-correct-sent">Correct sent request</button>');
    }
    const varianceLabels = (identity.discrepancy_codes || []).filter(function (code) {
      return !['national_id_mismatch', 'national_id_missing'].includes(code);
    }).map(function (code) {
      return code === 'name_variance' ? 'Name spelling differs' : code === 'phone_mismatch' ? 'Phone number differs' : code;
    });
    const identityNotice = hasMissingId
      ? '<div class="invoice-card-warning">A national ID is missing. Correct the parsed invoice or applicant data before continuing.</div>'
      : hasDifferentIds
        ? '<div class="invoice-card-warning">The invoice holder and applicant have different national IDs. Payment stays blocked until a corrected invoice is confirmed.</div>'
        : varianceLabels.length
          ? '<div class="invoice-info-note">National ID matches. ' + escapeHtml(varianceLabels.join('. ')) + '.</div>'
          : '<span class="badge badge-green">National ID matches</span>';
    const currentLetter = identity.name_change?.latest_letter;
    const letterPreviewHtml = currentLetter ? [
      '<div class="invoice-letter-preview">',
      '<div><strong>Generated letter</strong><span>Version ' + escapeHtml(currentLetter.version) + ' · ' + escapeHtml(fmtDate(currentLetter.generated_at)) + '</span></div>',
      '<p>' + (currentLetter.preview_url ? 'The complete letter is ready to preview in the app.' : 'This older letter has no PDF preview. Prepare a new version to view it in the app.') + '</p>',
      '<small>DOCX SHA-256: ' + escapeHtml(String(currentLetter.checksum || '').slice(0, 12)) + (currentLetter.preview_checksum ? ' · PDF SHA-256: ' + escapeHtml(String(currentLetter.preview_checksum).slice(0, 12)) : '') + '</small>',
      '</div>',
    ].join('') : '';
    const identityPanel = identity.invoice_identity ? [
      '<div class="form-section">',
      '<div class="invoice-section-heading"><div><h3>People linked to this invoice</h3><p>Matching an invoice never changes the applicant identity.</p></div><span class="badge ' + (['Matched', 'Corrected'].includes(identity.status_label) ? 'badge-green' : identity.status_label === 'Cancelled' ? 'badge-grey' : 'badge-orange') + '">' + escapeHtml(identity.status_label || 'Matched') + '</span></div>',
      '<div class="invoice-detail-grid">',
      kv('FarmUp lead / contact', identity.lead_identity?.name),
      kv('Lead national ID', identity.lead_identity?.national_id),
      kv('SysUp applicant / borrower', identity.applicant_identity?.name),
      kv('Applicant national ID', identity.applicant_identity?.national_id),
      kv('Invoice holder', identity.invoice_identity.name),
      kv('Invoice holder national ID', identity.invoice_identity.national_id),
      '</div>',
      identityNotice,
      letterPreviewHtml,
      identity.name_change ? '<div class="invoice-correction-summary"><strong>' + escapeHtml(identity.status_label) + '</strong><span>' + escapeHtml(identity.name_change.relationship_type === 'spouse' ? 'Spouse' : 'Other relative / household member') + (identity.name_change.explanation ? ' · ' + escapeHtml(identity.name_change.explanation) : '') + '</span>' + (identity.name_change.letter_readiness?.blockers?.length ? '<small>' + escapeHtml(identity.name_change.letter_readiness.blockers.join(' ')) + '</small>' : '') + '</div>' : '',
      '<div class="invoice-detail-actions">' + identityActions.join('') + '</div>',
      '</div>',
    ].join('') : '';
    const actionButtons = [
      routeMode ? '<button type="button" class="btn btn-secondary invoice-detail-back">Back to invoices</button>' : '',
      canWriteInvoices() && ['draft', 'unmatched', 'ambiguous'].includes(invoice.status) ? '<button type="button" class="btn btn-primary invoice-detail-match-action">Match invoice</button>' : '',
      canWriteInvoices() && invoice.status === 'matched' ? '<button type="button" class="btn btn-secondary invoice-detail-unmatch-action">Change applicant match</button>' : '',
      canWriteInvoices() && invoice.status !== 'ignored' ? '<button type="button" class="btn btn-secondary invoice-detail-ignore-action">Ignore invoice</button>' : '',
      canWriteInvoices() && invoice.status === 'ignored' ? '<button type="button" class="btn btn-secondary invoice-detail-restore-action">Restore invoice</button>' : '',
    ].join('');
    const duplicateHtml = duplicates.length
      ? duplicates.map(function (dup) {
        const reasons = (dup.duplicate_reasons || []).join(', ') || 'Possible duplicate';
        return '<div class="batch-client-row"><div class="name">Invoice ' + escapeHtml(dup.invoice_no || '-') + '</div><div class="meta">' + escapeHtml(reasons) + ' | ' + escapeHtml(dup.customer_name || '-') + ' | ' + escapeHtml(dup.status || '-') + '</div></div>';
      }).join('')
      : '<div class="empty-state"><div class="es-title">No likely duplicates</div><div class="es-sub">Checked invoice no, ID, and phone.</div></div>';
    const eventHtml = events.length
      ? events.map(function (event) {
        return '<div class="batch-client-row"><div class="name">' + escapeHtml(event.action || '-') + ' ' + (event.actor ? '<span class="meta">by ' + escapeHtml(event.actor) + '</span>' : '') + '</div><div class="meta">' + escapeHtml(fmtDate(event.created_at)) + (event.note ? ' | ' + escapeHtml(event.note) : '') + '</div></div>';
      }).join('')
      : '<div class="empty-state"><div class="es-title">No audit events yet</div></div>';
    target.innerHTML = [
      '<div class="batch-client-list">',
      '<div style="display:flex;justify-content:space-between;gap:8px;align-items:flex-start;flex-wrap:wrap;">',
      '<div><div class="fc-name">Invoice ' + escapeHtml(invoice.invoice_no || '-') + '</div>',
      '<div class="fc-sub">' + escapeHtml(invoice.customer_name || 'Unknown customer') + ' | ID ' + escapeHtml(invoice.customer_id || '-') + ' | ' + escapeHtml(invoice.customer_phone || '-') + '</div></div>',
      '<span class="badge ' + badgeClass(invoice.status) + '">' + escapeHtml(invoice.status || '-') + '</span>',
      '</div>',
      '<div class="fc-badges" style="margin-top:10px;">',
      '<span class="badge badge-grey">Amount: ' + money(invoice.invoice_amount) + '</span>',
      '<span class="badge badge-grey">HBG deposit: ' + money(hbgDeposit(invoice)) + '</span>',
      '<span class="badge badge-grey">Balance: ' + money(invoice.balance_due) + '</span>',
      '</div>',
      '<div class="invoice-detail-actions">' + sourceLink + actionButtons + '</div>',
      '</div>',
      '<div class="form-section">',
      '<h3 style="font-size:14px;margin:0 0 8px;">Parsed fields</h3>',
      '<div class="invoice-detail-grid">',
      kv('Invoice date', invoice.invoice_date),
      kv('Page', invoice.page),
      kv('Matched order', invoice.matched_order_number),
      kv('Balance check', invoice.balance_due_check),
      kv('Batch', batch.original_filename || invoice.batch_filename, { wide: true }),
      kv('Matched farmer', invoice.matched_farmer_name, { wide: true }),
      '</div>',
      '</div>',
      identityPanel,
      '<details class="form-section"' + (duplicates.length ? ' open' : '') + '>',
      '<summary>Duplicate check' + (duplicates.length ? ' (' + escapeHtml(duplicates.length) + ')' : '') + '</summary>',
      duplicateHtml,
      '</details>',
      '<details class="form-section">',
      '<summary>Audit trail (' + escapeHtml(events.length) + ')</summary>',
      eventHtml,
      '</details>',
    ].join('');
    target.querySelectorAll('.invoice-drive-link').forEach(function (btn) {
      btn.addEventListener('click', function () {
        if (deps.openPortalLink) deps.openPortalLink(btn.dataset.url);
        else window.open(btn.dataset.url, '_blank', 'noopener');
      });
    });
    target.querySelector('.invoice-detail-back')?.addEventListener('click', function () {
      navigate('inbox');
    });
    target.querySelector('.invoice-detail-match-action')?.addEventListener('click', function () { openMatchOverlay(invoice); });
    target.querySelector('.invoice-detail-unmatch-action')?.addEventListener('click', function () { unmatchInvoice(invoice.id); });
    target.querySelector('.invoice-detail-ignore-action')?.addEventListener('click', function () { ignoreInvoice(invoice.id); });
    target.querySelector('.invoice-detail-restore-action')?.addEventListener('click', function () { restoreInvoice(invoice.id); });
    target.querySelector('.invoice-name-change-start')?.addEventListener('click', function () { startInvoiceNameChange(invoice); });
    target.querySelector('.invoice-name-change-generate')?.addEventListener('click', function () { generateInvoiceNameChangeLetter(identity.name_change, invoice.id, this); });
    target.querySelector('.invoice-name-change-preview')?.addEventListener('click', function () { openLetterPreview(identity.name_change?.latest_letter); });
    target.querySelector('.invoice-name-change-download')?.addEventListener('click', function () {
      const url = identity.name_change?.latest_letter?.download_url;
      if (url && deps.openPortalLink) deps.openPortalLink(url); else if (url) window.open(url, '_blank', 'noopener');
    });
    target.querySelector('.invoice-name-change-sent')?.addEventListener('click', function () { markInvoiceNameChangeSent(identity.name_change); });
    target.querySelector('.invoice-name-change-replacement')?.addEventListener('click', function () { confirmInvoiceReplacement(identity.name_change); });
    target.querySelector('.invoice-name-change-correct-sent')?.addEventListener('click', function () { correctSentInvoiceNameChange(identity.name_change, invoice.id); });
  }

  async function decideInvoiceIdentity(invoiceId, outcome) {
    const title = outcome === 'same_person_confirmed' ? 'Confirm same person' : outcome === 'flagged_for_review' ? 'Flag for specialist review' : 'Confirm different person';
    const values = await openInvoiceWorkflowSheet(title, [
      '<div class="form-row"><label>Verification note</label><textarea name="note" rows="4" required placeholder="Record the evidence and reason for this decision."></textarea></div>',
    ].join(''), outcome === 'flagged_for_review' ? 'Flag for review' : 'Save decision');
    if (!values) return;
    const response = await deps.apiFetch('/invoice-pool/' + encodeURIComponent(invoiceId) + '/identity-review/', {
      method: 'POST', headers: { 'Content-Type': 'application/json', ...csrfHeader() },
      body: JSON.stringify({ outcome: outcome, note: values.note.trim(), client_request_id: requestId() }),
    });
    if (!response.ok || !response.data?.ok) return deps.showToast(response.data?.error || 'Identity verification failed.', 'error');
    loadDetail(invoiceId);
  }

  function openInvoiceWorkflowSheet(title, fieldsHtml, submitLabel) {
    return new Promise(function (resolve) {
      const previousFocus = document.activeElement;
      const overlay = document.createElement('div');
      overlay.className = 'sheet-overlay open invoice-workflow-overlay';
      overlay.setAttribute('role', 'dialog');
      overlay.setAttribute('aria-modal', 'true');
      overlay.setAttribute('aria-labelledby', 'invoice-workflow-title');
      overlay.innerHTML = [
        '<form class="sheet-panel invoice-workflow-form">',
        '<div class="sheet-handle"></div>',
        '<div class="sheet-header"><div><h2 id="invoice-workflow-title">' + escapeHtml(title) + '</h2></div>',
        '<button type="button" class="sheet-close-button" aria-label="Close">x</button></div>',
        '<div class="sheet-body"><div class="form-section">' + fieldsHtml + '</div><div class="invoice-workflow-error" role="alert" aria-live="polite"></div></div>',
        '<div class="sheet-footer"><button type="button" class="btn btn-secondary invoice-workflow-cancel">Cancel</button>',
        '<button type="submit" class="btn btn-primary">' + escapeHtml(submitLabel) + '</button></div>',
        '</form>',
      ].join('');
      document.body.appendChild(overlay);
      const form = overlay.querySelector('form');
      let settled = false;
      function close(value) {
        if (settled) return;
        settled = true;
        document.removeEventListener('keydown', onKeydown);
        overlay.remove();
        previousFocus?.focus?.();
        resolve(value);
      }
      function onKeydown(event) {
        if (event.key === 'Escape') close(null);
        if (event.key === 'Tab') {
          const focusable = Array.from(overlay.querySelectorAll('button,select,input,textarea')).filter(function (node) { return !node.disabled; });
          if (!focusable.length) return;
          const first = focusable[0]; const last = focusable[focusable.length - 1];
          if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
          else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
        }
      }
      overlay.querySelector('.sheet-close-button').addEventListener('click', function () { close(null); });
      overlay.querySelector('.invoice-workflow-cancel').addEventListener('click', function () { close(null); });
      overlay.addEventListener('click', function (event) { if (event.target === overlay) close(null); });
      form.addEventListener('submit', function (event) {
        event.preventDefault();
        if (!form.reportValidity()) return;
        close(Object.fromEntries(new FormData(form).entries()));
      });
      document.addEventListener('keydown', onKeydown);
      setTimeout(function () { overlay.querySelector('select,input,textarea,button')?.focus(); }, 30);
    });
  }

  async function startInvoiceNameChange(invoice) {
    const identity = invoice.identity || {};
    const values = await openInvoiceWorkflowSheet('Request corrected invoice', [
      '<div class="invoice-workflow-context"><strong>Invoice holder</strong><span>' + escapeHtml(invoice.customer_name || '-') + '</span><small>ID ' + escapeHtml(invoice.customer_id || '-') + '</small></div>',
      '<div class="invoice-workflow-context"><strong>Applicant / borrower</strong><span>' + escapeHtml(identity.applicant_identity?.name || invoice.matched_farmer_name || '-') + '</span><small>ID ' + escapeHtml(identity.applicant_identity?.national_id || '-') + '</small></div>',
      '<div class="form-row"><label>Relationship</label><select name="relationship_type" required><option value="spouse">Spouse</option><option value="household_member">Other relative / household member</option></select></div>',
      '<div class="form-row"><label>Explanation <span class="meta">(required for Other)</span></label><textarea name="explanation" rows="2" placeholder="Add useful context"></textarea></div>',
      '<label class="invoice-confirm-row"><input type="checkbox" name="confirmed" value="yes" required><span>I confirm the invoice belongs to this household person and a corrected invoice is required.</span></label>',
      '<p class="field-help">This creates the request and prepares its letter. Payment remains blocked until the corrected replacement invoice is confirmed.</p>',
    ].join(''), 'Request corrected invoice');
    if (!values) return;
    if (values.relationship_type === 'household_member' && !values.explanation?.trim()) {
      return deps.showToast('Explain the relationship when choosing Other relative / household member.', 'error');
    }
    const retryKey = requestId();
    const response = await deps.apiFetch('/invoice-pool/' + encodeURIComponent(invoice.id) + '/name-change/', {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': retryKey, ...csrfHeader() },
      body: JSON.stringify({
        relationship_type: values.relationship_type,
        explanation: values.explanation?.trim() || '',
        confirmed: values.confirmed === 'yes',
        invoice_revision: invoice.revision,
        application_revision: invoice.application_revision,
        client_request_id: retryKey,
      }),
    });
    if (!response.ok || !response.data?.ok) return deps.showToast(response.data?.error || 'Could not start the invoice-name change.', 'error');
    deps.showToast(response.data.letter_warning || 'Corrected-invoice request created.', response.data.letter_warning ? 'warning' : 'success');
    loadDetail(invoice.id);
  }

  async function generateInvoiceNameChangeLetter(change, invoiceId, button) {
    if (!change?.batch_id || button?.disabled) return;
    if (button) { button.disabled = true; button.textContent = 'Generating...'; }
    const retryKey = requestId();
    try {
      const response = await deps.apiFetch('/invoice-name-changes/' + encodeURIComponent(change.batch_id) + '/generate/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Idempotency-Key': retryKey, ...csrfHeader() },
        body: JSON.stringify({ client_request_id: retryKey }),
      });
      if (!response.ok || !response.data?.ok) return deps.showToast(response.data?.error || 'Could not generate the letter.', 'error');
      const letter = response.data.batch?.latest_letter;
      if (letter?.preview_url) await openLetterPreview(letter);
      else deps.showToast('The letter was created, but its preview is unavailable. Download the DOCX from the record.', 'warning');
      if (invoiceId) loadDetail(invoiceId);
    } finally {
      if (button?.isConnected) { button.disabled = false; button.textContent = 'Prepare letter preview'; }
    }
  }

  async function markInvoiceNameChangeSent(change) {
    const letter = change?.latest_letter;
    if (!letter?.id || !letter?.is_current) {
      return deps.showToast('Prepare the current letter before recording it as sent.', 'error');
    }
    const values = await openInvoiceWorkflowSheet('Record letter sent', [
      '<div class="form-row"><label>Generated letter</label><input value="Version ' + escapeHtml(letter.version) + ' - ' + escapeHtml(letter.filename) + '" readonly></div>',
      '<div class="form-row"><label>HB send reference</label><input name="sent_reference" required autocomplete="off"><span class="field-help">Email, message, or dispatch reference.</span></div>',
    ].join(''), 'Record sent');
    if (!values) return;
    const response = await deps.apiFetch('/invoice-name-changes/' + encodeURIComponent(change.batch_id) + '/sent/', {
      method: 'POST', headers: { 'Content-Type': 'application/json', ...csrfHeader() },
      body: JSON.stringify({ artifact_id: letter.id, sent_reference: values.sent_reference.trim() }),
    });
    if (!response.ok || !response.data?.ok) return deps.showToast(response.data?.error || 'Could not record the sent letter.', 'error');
    deps.showToast('Letter marked as sent.', 'success');
    if (change?.original_invoice_id) loadDetail(change.original_invoice_id);
  }

  async function correctSentInvoiceNameChange(change, invoiceId) {
    const values = await openInvoiceWorkflowSheet('Correct sent request', [
      '<div class="form-row"><label>Why is this correction needed?</label><textarea name="reason" rows="2" required></textarea></div>',
      '<div class="form-row"><label>Relationship</label><select name="relationship_type" required><option value="spouse"' + (change.relationship_type === 'spouse' ? ' selected' : '') + '>Spouse</option><option value="household_member"' + (change.relationship_type === 'household_member' ? ' selected' : '') + '>Other relative / household member</option></select></div>',
      '<div class="form-row"><label>Explanation</label><textarea name="explanation" rows="2">' + escapeHtml(change.explanation || '') + '</textarea></div>',
      '<p class="field-help">The already-sent letter stays in the audit history. A new version will be prepared and must be sent again.</p>',
    ].join(''), 'Prepare corrected letter');
    if (!values) return;
    const retryKey = requestId();
    const response = await deps.apiFetch('/invoice-name-change-items/' + encodeURIComponent(change.id) + '/correct-sent/', {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': retryKey, ...csrfHeader() },
      body: JSON.stringify({
        reason: values.reason.trim(), relationship_type: values.relationship_type,
        explanation: values.explanation.trim(), revision: change.revision,
        client_request_id: retryKey,
      }),
    });
    if (!response.ok || !response.data?.ok) return deps.showToast(response.data?.error || 'Could not correct the sent request.', 'error');
    deps.showToast(response.data.letter_warning || 'New letter version prepared.', response.data.letter_warning ? 'warning' : 'success');
    loadDetail(invoiceId);
  }

  async function confirmInvoiceReplacement(change) {
    if (change?.id) openReplacementSelector(change.id);
  }

  async function openInvoiceDetail(invoiceId) {
    if (!invoiceId) return;
    navigate('detail', invoiceId);
  }

  function closeInvoiceDetail() {
    el('invoice-detail-overlay')?.classList.remove('open');
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
    const params = new URLSearchParams({ search: search });
    if (state.selectedInvoice?.id) params.set('invoice_id', state.selectedInvoice.id);
    params.set('scope', state.candidateScope);
    const result = await deps.apiFetch('/invoice-pool/farmers/?' + params.toString());
    const farmers = result.data?.farmers || [];
    if (!result.ok || !result.data?.ok || !farmers.length) {
      target.innerHTML = '<div class="empty-state"><div class="es-title">No matching applicants</div><div class="es-sub">Try another ID, phone, name, or order.</div>' + (state.candidateScope === 'operational' ? '<button type="button" class="btn btn-secondary invoice-search-history">Search historical applicants</button>' : '<span class="badge badge-orange">Historical records searched</span>') + '</div>';
      target.querySelector('.invoice-search-history')?.addEventListener('click', function () { state.candidateScope = 'historical'; searchCandidates(); });
      return;
    }
    const scopeBanner = result.data.historical_search ? '<div class="invoice-history-banner"><strong>Historical records</strong><span>These applicants are outside the current operational pool. Confirm identity carefully.</span></div>' : '';
    target.innerHTML = scopeBanner + farmers.map(function (farmer) {
      const conflict = farmer.has_invoice
        ? '<div class="batch-warning" style="margin-top:8px;">' + escapeHtml(farmer.invoice_conflict_label || 'This farmer already has an invoice.') + '</div>'
        : '';
      const reasons = Array.isArray(farmer.match_reasons) && farmer.match_reasons.length
        ? '<div class="fc-badges" style="margin-top:6px;">' + farmer.match_reasons.map(function (reason) {
          return '<span class="badge badge-blue">' + escapeHtml(reason) + '</span>';
        }).join('') + '</div>'
        : '';
      const tier = farmer.match_tier || 'search_result';
      const tierLabel = tier === 'strong' ? 'Strong suggestion' : tier === 'likely' ? 'Likely suggestion' : tier === 'possible' ? 'Possible match' : 'Search result';
      const invoice = state.selectedInvoice || {};
      return [
        '<div class="farmer-card batch-card invoice-match-candidate" style="cursor:default;">',
        '<div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start;flex-wrap:wrap;">',
        '<div>',
        '<div class="invoice-card-heading"><div class="fc-name">' + escapeHtml(farmer.customer_name || 'Unnamed applicant') + '</div><span class="badge ' + (tier === 'strong' ? 'badge-green' : tier === 'likely' ? 'badge-blue' : 'badge-grey') + '">' + escapeHtml(tierLabel) + '</span></div>',
        '<div class="invoice-match-comparison">',
        '<div><strong>Name</strong><span>Invoice: ' + escapeHtml(invoice.customer_name || '-') + '</span><span>Applicant: ' + escapeHtml(farmer.customer_name || '-') + '</span></div>',
        '<div><strong>National ID</strong><span>Invoice: ' + escapeHtml(invoice.customer_id || '-') + '</span><span>Applicant: ' + escapeHtml(farmer.national_id || '-') + '</span></div>',
        '<div><strong>Phone</strong><span>Invoice: ' + escapeHtml(invoice.customer_phone || '-') + '</span><span>Applicant: ' + escapeHtml(farmer.primary_phone || '-') + '</span></div>',
        '</div>',
        '<div class="fc-sub">' + escapeHtml(deps.locationText(farmer)) + (farmer.order_number ? ' | Order ' + escapeHtml(farmer.order_number) : '') + (farmer.customer_no ? ' | Customer No ' + escapeHtml(farmer.customer_no) : '') + '</div>',
        reasons,
        conflict,
        '</div>',
        '<button class="btn btn-primary invoice-select-candidate" data-farmer="' + escapeHtml(farmer.id) + '"' + (farmer.has_invoice ? ' data-conflict="1"' : '') + '>Confirm match</button>',
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
    let note = el('invoice-match-note')?.value || '';
    if (hasConflict) {
      const values = await openInvoiceWorkflowSheet('Confirm invoice conflict', '<p class="invoice-card-warning">This applicant already has an invoice. Continue only when this is a deliberate correction.</p><div class="form-row"><label>Reason</label><textarea name="note" rows="3" required></textarea></div>', 'Continue matching');
      if (!values) return;
      note = values.note;
    }
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
    const values = await openInvoiceWorkflowSheet('Unmatch invoice', '<p>This removes the current link and clears it from the applicant record where applicable.</p><div class="form-row"><label>Audit note</label><textarea name="note" rows="3"></textarea></div>', 'Unmatch invoice');
    if (!values) return;
    const note = values.note || '';
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
    const values = await openInvoiceWorkflowSheet('Ignore invoice', '<div class="form-row"><label>Reason</label><textarea name="note" rows="3" required></textarea></div>', 'Ignore invoice');
    if (!values) return;
    const note = values.note;
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

  async function restoreInvoice(invoiceId) {
    const values = await openInvoiceWorkflowSheet('Restore invoice', '<div class="form-row"><label>Audit note</label><textarea name="note" rows="3"></textarea></div>', 'Restore invoice');
    if (!values) return;
    const note = values.note || '';
    const response = await deps.apiFetch('/invoice-pool/' + encodeURIComponent(invoiceId) + '/restore/', {
      method: 'POST',
      body: JSON.stringify({ note: note }),
    });
    if (!response.ok || !response.data?.ok) {
      deps.showToast(response.data?.error || 'Could not restore invoice.', 'error');
      return;
    }
    deps.showToast('Invoice restored.', 'success');
    load(state.page);
  }

  async function bulkInvoiceAction(action) {
    const ids = Array.from(state.selectedIds);
    if (!ids.length) return deps.showToast('Select at least one invoice first.', 'error');
    const label = action === 'restore' ? 'restore' : 'ignore';
    const values = await openInvoiceWorkflowSheet((label === 'restore' ? 'Restore' : 'Ignore') + ' selected invoices', '<p>' + escapeHtml(ids.length) + ' invoice(s) will be updated. Matching is never performed in bulk.</p><div class="form-row"><label>Audit note</label><textarea name="note" rows="3"' + (label === 'ignore' ? ' required' : '') + '></textarea></div>', label === 'restore' ? 'Restore selected' : 'Ignore selected');
    if (!values) return;
    const note = values.note || '';
    const response = await deps.apiFetch('/invoice-pool/bulk-action/', {
      method: 'POST',
      body: JSON.stringify({ action: action, invoice_ids: ids, note: note }),
    });
    if (!response.ok || !response.data?.ok) {
      deps.showToast(response.data?.error || 'Bulk action failed.', 'error');
      return;
    }
    state.selectedIds.clear();
    const changed = response.data.changed_count || 0;
    const skipped = response.data.skipped_count || 0;
    deps.showToast('Updated ' + changed + ' invoice(s)' + (skipped ? '; skipped ' + skipped : '') + '.', skipped ? 'warning' : 'success');
    load(state.page);
  }

  function updateNameChangeSelection() {
    const bar = el('invoice-name-change-selection');
    const count = el('invoice-name-change-selected-count');
    const size = state.selectedNameChanges.size;
    if (bar) bar.style.display = size ? 'flex' : 'none';
    if (count) count.textContent = size + ' selected';
  }

  function renderNameChangePagination(pagination) {
    const target = el('pg-invoice-name-changes');
    if (!target || !pagination || pagination.pages <= 1) {
      if (target) target.innerHTML = '';
      return;
    }
    target.innerHTML = '<button type="button" data-page="' + (pagination.page - 1) + '"' + (pagination.page <= 1 ? ' disabled' : '') + '>Prev</button><span class="pg-info">Page ' + escapeHtml(pagination.page) + ' of ' + escapeHtml(pagination.pages) + '</span><button type="button" data-page="' + (pagination.page + 1) + '"' + (pagination.page >= pagination.pages ? ' disabled' : '') + '>Next</button>';
    target.querySelectorAll('button:not([disabled])').forEach(function (button) {
      button.addEventListener('click', function () { loadNameChanges(Number(button.dataset.page)); });
    });
  }

  function renderNameChanges(data) {
    const target = el('invoice-name-change-list');
    if (!target) return;
    const items = data.items || [];
    const batchById = new Map((data.batches || []).map(function (batch) { return [batch.id, batch]; }));
    document.querySelectorAll('#invoice-name-change-tabs [data-count]').forEach(function (badge) {
      badge.textContent = data.counts?.[badge.dataset.count] || 0;
    });
    document.querySelectorAll('#invoice-name-change-tabs [data-segment]').forEach(function (button) {
      button.classList.toggle('active', button.dataset.segment === state.nameChangeSegment);
    });
    if (!items.length) {
      target.innerHTML = '<div class="empty-state"><div class="es-title">No requests in this view</div><div class="es-sub">Requests move here as identity verification, letters, and replacements progress.</div></div>';
      renderNameChangePagination(data.pagination || {});
      return;
    }
    target.innerHTML = items.map(function (item) {
      const ready = item.status === 'draft' && !item.batch_id;
      const batch = item.batch_id ? batchById.get(item.batch_id) : null;
      const checked = state.selectedNameChanges.has(item.id) ? ' checked' : '';
      const age = item.age_days ? '<span class="badge badge-orange">' + escapeHtml(item.age_days) + ' day' + (item.age_days === 1 ? '' : 's') + ' here</span>' : '<span class="badge badge-grey">Updated today</span>';
      let primary = '';
      let secondary = '';
      if (batch?.status === 'draft') {
        primary = batch.latest_letter?.is_current && batch.latest_letter?.drive_url
          ? '<button type="button" class="btn btn-primary name-change-record-sent" data-batch="' + escapeHtml(batch.id) + '">Record sent</button>'
          : '<button type="button" class="btn btn-primary name-change-generate" data-batch="' + escapeHtml(batch.id) + '">Generate letter</button>';
        secondary = batch.latest_letter?.download_url ? '<button type="button" class="name-change-download" data-url="' + escapeHtml(batch.latest_letter.download_url) + '">Open current letter</button>' : '';
      } else if (item.status === 'awaiting_replacement') {
        primary = '<button type="button" class="btn btn-primary name-change-replacement" data-item="' + escapeHtml(item.id) + '">Select replacement</button>';
        secondary = '<button type="button" class="name-change-close" data-item="' + escapeHtml(item.id) + '" data-action="withdraw">Withdraw request</button>';
      } else if (item.status === 'cancelled' || item.status === 'withdrawn') {
        primary = '<button type="button" class="btn btn-primary name-change-follow-up" data-item="' + escapeHtml(item.id) + '">Start follow-up</button>';
      } else if (ready) {
        secondary = '<button type="button" class="name-change-close" data-item="' + escapeHtml(item.id) + '" data-action="cancel">Cancel request</button>';
      }
      return [
        '<article class="farmer-card invoice-name-change-card" data-item="' + escapeHtml(item.id) + '">',
        '<div class="invoice-name-change-card-main">',
        ready ? '<input type="checkbox" class="name-change-select" data-item="' + escapeHtml(item.id) + '" aria-label="Select ' + escapeHtml(item.applicant_name) + '"' + checked + '>' : '<span></span>',
        '<div><div class="invoice-card-heading"><div class="fc-name">' + escapeHtml(item.applicant_name || 'Applicant') + '</div><span class="badge ' + (item.status === 'completed' ? 'badge-green' : item.status === 'withdrawn' || item.status === 'cancelled' ? 'badge-grey' : 'badge-blue') + '">' + escapeHtml(item.status.replaceAll('_', ' ')) + '</span></div>',
        '<div class="fc-sub">Invoice holder: ' + escapeHtml(item.invoice_holder_name || '-') + ' · Invoice ' + escapeHtml(item.original_invoice_no || '-') + '</div>',
        '<div class="fc-badges">' + age + (item.batch_reference ? '<span class="badge badge-blue">' + escapeHtml(item.batch_reference) + '</span>' : '<span class="badge badge-grey">Not yet in a letter</span>') + '</div>',
        item.closed_reason ? '<div class="invoice-card-warning">' + escapeHtml(item.closed_reason) + '</div>' : '',
        '</div></div>',
        '<div class="invoice-card-actions">' + primary + '<details class="invoice-card-menu"><summary>More</summary><div><button type="button" class="name-change-open-invoice" data-invoice="' + escapeHtml(item.original_invoice_id) + '">View source invoice</button>' + secondary + '</div></details></div>',
        '</article>',
      ].join('');
    }).join('');
    target.querySelectorAll('.name-change-select').forEach(function (input) {
      input.addEventListener('change', function () {
        if (input.checked) state.selectedNameChanges.add(input.dataset.item);
        else state.selectedNameChanges.delete(input.dataset.item);
        updateNameChangeSelection();
      });
    });
    target.querySelectorAll('.name-change-open-invoice').forEach(function (button) { button.addEventListener('click', function () { window.sessionStorage?.setItem('portalInvoiceDetailReturn', 'name_changes'); window.sessionStorage?.setItem('portalInvoiceNameChangeFocus', button.closest('[data-item]')?.dataset.item || ''); openInvoiceDetail(button.dataset.invoice); }); });
    target.querySelectorAll('.name-change-generate').forEach(function (button) {
      button.addEventListener('click', function () {
        const batch = batchById.get(button.dataset.batch); if (batch) generateInvoiceNameChangeLetter({ batch_id: batch.id }, '', button).then(function () { loadNameChanges(state.nameChangePage); });
      });
    });
    target.querySelectorAll('.name-change-record-sent').forEach(function (button) { button.addEventListener('click', function () { const batch = batchById.get(button.dataset.batch); if (batch) markInvoiceNameChangeSent({ batch_id: batch.id, latest_letter: batch.latest_letter }).then(function () { loadNameChanges(state.nameChangePage); }); }); });
    target.querySelectorAll('.name-change-download').forEach(function (button) { button.addEventListener('click', function () { deps.openPortalLink ? deps.openPortalLink(button.dataset.url) : window.open(button.dataset.url, '_blank', 'noopener'); }); });
    target.querySelectorAll('.name-change-close').forEach(function (button) { button.addEventListener('click', function () { closeNameChangeRequest(button.dataset.item, button.dataset.action); }); });
    target.querySelectorAll('.name-change-follow-up').forEach(function (button) { button.addEventListener('click', function () { startNameChangeFollowUp(button.dataset.item); }); });
    target.querySelectorAll('.name-change-replacement').forEach(function (button) { button.addEventListener('click', function () { openReplacementSelector(button.dataset.item); }); });
    renderNameChangePagination(data.pagination || {});
    const focusId = window.sessionStorage?.getItem('portalInvoiceNameChangeFocus');
    if (focusId) {
      const focused = target.querySelector('[data-item="' + CSS.escape(focusId) + '"]');
      if (focused) { focused.scrollIntoView({ block: 'center' }); focused.classList.add('is-focused'); }
      window.sessionStorage?.removeItem('portalInvoiceNameChangeFocus');
    }
    updateNameChangeSelection();
  }

  async function loadNameChanges(page) {
    state.nameChangePage = page || 1;
    const params = new URLSearchParams({ segment: state.nameChangeSegment, page: String(state.nameChangePage) });
    if (state.nameChangeSearch) params.set('search', state.nameChangeSearch);
    const target = el('invoice-name-change-list');
    if (target) target.innerHTML = '<div class="empty-state"><div class="spinner-inline"></div></div>';
    const response = await deps.apiFetch('/invoice-name-changes/?' + params.toString());
    if (!response.ok || !response.data?.ok) {
      if (target) target.innerHTML = '<div class="empty-state"><div class="es-title">Could not load name changes</div><div class="es-sub">Refresh and try again.</div></div>';
      return;
    }
    renderNameChanges(response.data);
  }

  async function createNameChangeBatch() {
    const itemIds = Array.from(state.selectedNameChanges);
    if (!itemIds.length) return;
    const key = requestId();
    const response = await deps.apiFetch('/invoice-name-changes/', {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': key, ...csrfHeader() },
      body: JSON.stringify({ item_ids: itemIds, client_request_id: key }),
    });
    if (!response.ok || !response.data?.ok) {
      const conflicts = response.data?.conflicts || [];
      const detail = conflicts.length ? conflicts.map(function (item) { return item.applicant_name + ': ' + item.reason.replaceAll('_', ' '); }).join('\n') : response.data?.error;
      deps.showToast(detail || 'Could not create the letter batch.', 'error');
      state.selectedNameChanges = new Set(response.data?.available_item_ids || itemIds);
      return loadNameChanges(state.nameChangePage);
    }
    state.selectedNameChanges.clear();
    state.nameChangeSegment = 'draft_letters';
    deps.showToast('Letter batch created.', 'success');
    loadNameChanges(1);
  }

  async function closeNameChangeRequest(itemId, action) {
    const withdraw = action === 'withdraw';
    const values = await openInvoiceWorkflowSheet(withdraw ? 'Withdraw sent request' : 'Cancel request', [
      '<div class="form-row"><label>Reason</label><textarea name="reason" rows="4" required></textarea></div>',
      withdraw ? '<div class="form-row"><label>HB communication reference</label><input name="hb_communication_reference" required><span class="field-help">Record the email, message, or call reference confirming withdrawal.</span></div>' : '',
    ].join(''), withdraw ? 'Withdraw request' : 'Cancel request');
    if (!values) return;
    const response = await deps.apiFetch('/invoice-name-change-items/' + encodeURIComponent(itemId) + '/close/', {
      method: 'POST', headers: { 'Content-Type': 'application/json', ...csrfHeader() },
      body: JSON.stringify({ action: action, reason: values.reason, hb_communication_reference: values.hb_communication_reference || '' }),
    });
    if (!response.ok || !response.data?.ok) return deps.showToast(response.data?.error || 'Could not close the request.', 'error');
    deps.showToast(withdraw ? 'Request withdrawn.' : 'Request cancelled.', 'success');
    loadNameChanges(state.nameChangePage);
  }

  async function startNameChangeFollowUp(itemId) {
    const values = await openInvoiceWorkflowSheet('Start follow-up request', '<p>The previous record and sent artifacts stay unchanged. Identity must be verified again before this follow-up can enter a new letter.</p>', 'Start follow-up');
    if (!values) return;
    const key = requestId();
    const response = await deps.apiFetch('/invoice-name-change-items/' + encodeURIComponent(itemId) + '/follow-up/', {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': key, ...csrfHeader() }, body: JSON.stringify({ client_request_id: key }),
    });
    if (!response.ok || !response.data?.ok) return deps.showToast(response.data?.error || 'Could not start the follow-up.', 'error');
    window.sessionStorage?.setItem('portalInvoiceNameChangeFocus', response.data.name_change.id);
    window.sessionStorage?.setItem('portalInvoiceDetailReturn', 'name_changes');
    openInvoiceDetail(response.data.name_change.original_invoice_id);
  }

  async function openReplacementSelector(itemId) {
    const overlay = document.createElement('div');
    overlay.className = 'sheet-overlay open invoice-workflow-overlay';
    overlay.setAttribute('role', 'dialog'); overlay.setAttribute('aria-modal', 'true'); overlay.setAttribute('aria-labelledby', 'replacement-sheet-title');
    overlay.innerHTML = '<div class="sheet-panel invoice-workflow-form"><div class="sheet-handle"></div><div class="sheet-header"><div><h2 id="replacement-sheet-title">Select corrected invoice</h2><p class="sheet-sub">ID matches rank first; conflicting matches remain visible but cannot be selected.</p></div><button type="button" class="sheet-close-button" aria-label="Close">x</button></div><div class="sheet-body"><label class="invoice-search-control"><span class="sr-only">Search replacement invoices</span><input type="search" placeholder="Name, ID, phone, or invoice"></label><div class="replacement-candidate-list farmer-list"></div></div></div>';
    document.body.appendChild(overlay);
    const list = overlay.querySelector('.replacement-candidate-list');
    const input = overlay.querySelector('input');
    function close() { overlay.remove(); }
    async function search() {
      list.innerHTML = '<div class="empty-state"><div class="spinner-inline"></div></div>';
      const params = new URLSearchParams(); if (input.value.trim()) params.set('search', input.value.trim());
      const response = await deps.apiFetch('/invoice-name-change-items/' + encodeURIComponent(itemId) + '/replacement-candidates/?' + params.toString());
      const rows = response.data?.candidates || [];
      if (!response.ok || !response.data?.ok || !rows.length) { list.innerHTML = '<div class="empty-state"><div class="es-title">No replacement invoices found</div><div class="es-sub">Upload the corrected PDF, then search again.</div></div>'; return; }
      list.innerHTML = rows.map(function (row) { const inv = row.invoice; return '<article class="farmer-card replacement-candidate"><div><div class="invoice-card-heading"><div class="fc-name">Invoice ' + escapeHtml(inv.invoice_no || '-') + '</div>' + (row.id_match ? '<span class="badge badge-green">Applicant ID match</span>' : '<span class="badge badge-grey">Check identity</span>') + '</div><div class="fc-sub">' + escapeHtml(inv.customer_name || '-') + ' · ID ' + escapeHtml(inv.customer_id || '-') + ' · ' + escapeHtml(inv.status) + '</div>' + (row.status_note ? '<div class="invoice-card-warning">' + escapeHtml(row.status_note) + '</div>' : '') + '</div><button type="button" class="btn btn-primary choose-replacement" data-invoice="' + escapeHtml(inv.id) + '"' + (row.selectable ? '' : ' disabled') + '>Select</button></article>'; }).join('');
      list.querySelectorAll('.choose-replacement:not([disabled])').forEach(function (button) { button.addEventListener('click', async function () {
        const values = await openInvoiceWorkflowSheet('Confirm corrected invoice', '<div class="form-row"><label>Verification note</label><textarea name="verification_note" rows="3" placeholder="Required only when name or phone differs."></textarea></div>', 'Confirm replacement');
        if (!values) return;
        const result = await deps.apiFetch('/invoice-name-change-items/' + encodeURIComponent(itemId) + '/replacement/', { method: 'POST', headers: { 'Content-Type': 'application/json', ...csrfHeader() }, body: JSON.stringify({ replacement_invoice_id: button.dataset.invoice, verification_note: values.verification_note || '' }) });
        if (!result.ok || !result.data?.ok) return deps.showToast(result.data?.error || 'Could not confirm the replacement.', 'error');
        close(); deps.showToast('Corrected invoice confirmed.', 'success'); loadNameChanges(state.nameChangePage);
      }); });
    }
    overlay.querySelector('.sheet-close-button').addEventListener('click', close); overlay.addEventListener('click', function (event) { if (event.target === overlay) close(); });
    input.addEventListener('input', function () { clearTimeout(candidateTimer); candidateTimer = setTimeout(search, 300); });
    search(); setTimeout(function () { input.focus(); }, 30);
  }

  function bindFilters() {
    if (document.documentElement.dataset.invoiceFiltersBound === 'true') return;
    document.documentElement.dataset.invoiceFiltersBound = 'true';
    document.addEventListener('change', function (event) {
      if (event.target.id === 'invoice-pool-review') state.review = event.target.value || '';
      else return;
      load(1);
    });
    document.addEventListener('input', function (event) {
      if (event.target.id === 'invoice-name-change-search') {
        clearTimeout(searchTimer);
        state.nameChangeSearch = event.target.value.trim();
        searchTimer = setTimeout(function () { loadNameChanges(1); }, 300);
        return;
      }
      if (event.target.id !== 'invoice-pool-search') return;
      clearTimeout(searchTimer);
      state.search = event.target.value.trim();
      searchTimer = setTimeout(function () { load(1); }, 350);
    });
    document.addEventListener('click', function (event) {
      const segment = event.target.closest('#invoice-name-change-tabs [data-segment]');
      if (segment) {
        state.nameChangeSegment = segment.dataset.segment;
        state.selectedNameChanges.clear();
        updateNameChangeSelection();
        loadNameChanges(1);
        return;
      }
      if (event.target.closest('#invoice-name-change-create-batch')) {
        createNameChangeBatch();
        return;
      }
      if (event.target.closest('#invoice-name-change-clear')) {
        state.selectedNameChanges.clear();
        document.querySelectorAll('.name-change-select').forEach(function (input) { input.checked = false; });
        updateNameChangeSelection();
        return;
      }
      if (!event.target.closest('#invoice-pool-clear')) return;
      state.review = '';
      state.search = '';
      if (el('invoice-pool-review')) el('invoice-pool-review').value = '';
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
    el('invoice-detail-close')?.addEventListener('click', closeInvoiceDetail);
    el('invoice-detail-overlay')?.addEventListener('click', function (event) {
      if (event.target === el('invoice-detail-overlay')) closeInvoiceDetail();
    });
  }

  function bindBulkActions() {
    if (document.documentElement.dataset.invoiceBulkActionsBound === 'true') return;
    document.documentElement.dataset.invoiceBulkActionsBound = 'true';
    document.addEventListener('click', function (event) {
      const button = event.target.closest('#invoice-bulk-ignore, #invoice-bulk-restore, #invoice-selection-clear');
      if (!button) return;
      if (button.id === 'invoice-bulk-ignore') {
        bulkInvoiceAction('ignore');
        return;
      }
      if (button.id === 'invoice-bulk-restore') {
        bulkInvoiceAction('restore');
        return;
      }
      state.selectedIds.clear();
      document.querySelectorAll('.invoice-select-row').forEach(function (input) { input.checked = false; });
      updateBulkToolbar();
    });
  }

  function bindUpload() {
    if (document.documentElement.dataset.invoicePoolUploadBound === 'true') return;
    document.documentElement.dataset.invoicePoolUploadBound = 'true';
    document.addEventListener('change', function (event) {
      if (event.target.id !== 'invoice-pool-file') return;
      const files = event.target.files ? Array.from(event.target.files) : [];
      const dropzone = document.getElementById('invoice-pool-dropzone');
      const title = document.getElementById('invoice-pool-file-title');
      const detail = document.getElementById('invoice-pool-file-detail');
      dropzone?.classList.toggle('has-selection', files.length > 0);
      if (title) title.textContent = files.length ? (files.length === 1 ? files[0].name : files.length + ' invoice PDFs selected') : 'Upload invoice PDFs';
      if (detail) detail.textContent = files.length > 1 ? files.slice(0, 3).map(function (file) { return file.name; }).join(' · ') : (files.length ? 'Ready to upload and parse' : 'Tap to select one or more PDF files');
    });
    document.addEventListener('submit', async function (event) {
      const form = event.target.closest('#invoice-pool-upload-form');
      if (!form) return;
      event.preventDefault();
      const fileInput = form.querySelector('#invoice-pool-file');
      const resultBox = form.parentElement?.querySelector('#invoice-pool-upload-result');
      const submit = form.querySelector('#invoice-pool-upload-submit');
      const files = fileInput?.files ? Array.from(fileInput.files) : [];
      if (!files.length) return deps.showToast('Select at least one invoice PDF first.', 'error');
      const invalid = files.find(function (file) {
        return !String(file.name || '').toLowerCase().endsWith('.pdf');
      });
      if (invalid) return deps.showToast('Only PDF invoices are supported: ' + invalid.name, 'error');
      const formData = new FormData();
      const orderNumber = form.querySelector('#invoice-pool-order')?.value?.trim() || '';
      if (orderNumber) formData.append('order_number', orderNumber);
      files.forEach(function (file) {
        formData.append('file', file);
      });
      if (deps.setButtonLoading) deps.setButtonLoading(submit, true, files.length > 1 ? 'Uploading PDFs...' : 'Uploading...');
      try {
        const response = await deps.portalApi.postForm('/invoice-pool/upload/', formData, deps.tg, csrfHeader());
        const data = response.data || {};
        if (!response.ok || data.ok === false) {
          const failures = Array.isArray(data.failures) ? data.failures : [];
          const failureHtml = failures.length
            ? '<ul class="mini-list">' + failures.map(function (item) {
                return '<li><strong>' + escapeHtml(item.filename || 'PDF') + ':</strong> ' + escapeHtml(item.error || 'Upload failed') + '</li>';
              }).join('') + '</ul>'
            : '';
          if (resultBox) resultBox.innerHTML = '<div class="batch-warning" style="margin-top:10px;">' + escapeHtml(data.error || 'Invoice upload failed.') + failureHtml + '</div>';
          deps.showToast(data.error || 'Invoice upload failed.', 'error');
          return;
        }
        if (fileInput) fileInput.value = '';
        const dropzone = document.getElementById('invoice-pool-dropzone');
        dropzone?.classList.remove('has-selection');
        dropzone?.classList.add('upload-complete');
        const title = document.getElementById('invoice-pool-file-title');
        const detail = document.getElementById('invoice-pool-file-detail');
        if (title) title.textContent = files.length > 1 ? files.length + ' invoice PDFs uploaded' : (files[0]?.name || 'Invoice PDF') + ' uploaded';
        if (detail) detail.textContent = 'Tap to select another invoice PDF';
        if (resultBox) {
          const uploaded = data.total_uploaded || 1;
          const failed = data.total_failed || 0;
          const failedBadge = failed ? ' <span class="badge badge-red">' + escapeHtml(failed) + ' failed</span>' : '';
          resultBox.innerHTML = '<span class="badge badge-green">Uploaded ' + escapeHtml(uploaded) + ' PDF(s)</span> <span class="badge badge-blue">Parsed ' + escapeHtml(data.total_parsed || 0) + ' invoice(s)</span> <span class="badge badge-orange">' + escapeHtml(data.unmatched_count || 0) + ' unmatched</span>' + failedBadge;
        }
        deps.showToast(files.length > 1 ? 'Invoices uploaded to pool.' : 'Invoice uploaded to pool.', 'success');
        load(1);
      } catch (error) {
        if (resultBox) resultBox.innerHTML = '<div class="batch-warning" style="margin-top:10px;">The invoice upload did not finish. Check your connection and retry.</div>';
        deps.showToast('The invoice upload did not finish. Check your connection and retry.', 'error');
      } finally {
        if (deps.setButtonLoading) deps.setButtonLoading(submit, false);
      }
    });
  }

  function init(inputDeps) {
    deps = inputDeps || {};
    bindFilters();
    bindUpload();
    bindMatchOverlay();
    bindBulkActions();
    el('media-viewer-close')?.addEventListener('click', closeLetterPreview);
    el('media-viewer-overlay')?.addEventListener('click', function (event) {
      if (event.target === this) closeLetterPreview();
    });
    window.addEventListener('beforeunload', closeLetterPreview);
  }

  window.PortalMiniAppInvoices = {
    init,
    load,
  };
})();
