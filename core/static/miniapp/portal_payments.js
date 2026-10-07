(function () {
  'use strict';

  let deps = null;
  let activeBatch = null;
  let batches = [];
  let receiptBatches = [];
  let showArchivedReceipts = false;
  let activeReceipt = null;
  let candidates = [];
  let candidatePage = 1;
  let candidatePagination = null;
  let candidateLoadVersion = 0;
  let candidatePanelOpen = false;
  let suppressCandidateFocus = false;
  let batchFilter = 'open';
  let sequenceRevision = 0;
  const selected = new Set();
  const selectedModes = new Map();
  let searchTimer = null;
  let detailLoadVersion = 0;
  let previewRequestVersion = 0;
  let previewHistoryActive = false;
  let previewTrigger = null;
  let receiptPreviewVersion = 0;
  let receiptPreviewUrl = '';
  let receiptPreviewTrigger = null;
  const reviewProtections = new Map();
  let batchPage = 1;
  let batchSearch = '';
  let batchPagination = null;
  let batchCounts = null;
  let listLoadVersion = 0;

  function el(id) { return deps.el(id); }
  function escape(value) { return deps.escapeHtml(value == null ? '' : value); }
  function capability(key) { return !deps.state || deps.state.capabilities?.has(key); }
  function root() { return document.getElementById('portal-screen'); }
  function screen() { return root()?.dataset.screen || ''; }
  function active() { return ['payments', 'payment_approvals'].includes(screen()); }
  function approvalMode() { return screen() === 'payment_approvals'; }
  function detailBatchId() { return root()?.dataset.paymentBatchId || ''; }
  function listParams() { return new URLSearchParams({status: batchFilter, page: String(batchPage), search: batchSearch}); }
  function inboxPath() { return approvalMode() ? '/portal/s/approvals/payments/' : '/portal/s/payments/'; }
  function inboxUrl() { return `${inboxPath()}?${listParams()}`; }
  function detailUrl(id) { return `${inboxPath()}${encodeURIComponent(id)}/?${listParams()}`; }
  function money(value) {
    const number = Number(String(value ?? '').replace(/,/g, ''));
    return Number.isFinite(number) ? `KES ${number.toLocaleString('en-KE', {maximumFractionDigits: 2})}` : 'KES 0';
  }
  function request(path, method, body) {
    return deps.apiFetch(path, {method, body: JSON.stringify(body || {})});
  }
  function statusClass(status) {
    return ({completed: 'badge-green', awaiting_scan: 'badge-orange', review_complete: 'badge-blue', in_review: 'badge-blue', cancelled: 'badge-grey'})[status] || 'badge-grey';
  }
  function approvalQueueStatus(batch) {
    return batch.approval_queue_status || (batch.requires_re_review ? 'in_review' : batch.status);
  }

  function setBatchTabCount(filter, value) {
    const badge = document.querySelector(`[data-payment-batch-count="${filter}"]`);
    if (!badge) return;
    const count = Number(value || 0);
    badge.textContent = String(count);
    badge.closest('button')?.setAttribute('aria-label', `${badge.closest('button')?.querySelector('span:first-child')?.textContent || 'Payment batches'}: ${count}`);
  }

  function renderBatchTabCounts() {
    if (batchCounts) {
      Object.entries(batchCounts).forEach(([key, count]) => setBatchTabCount(key, count));
      return;
    }
    const count = key => batches.filter(item => (approvalMode() ? approvalQueueStatus(item) : item.status) === key).length;
    if (approvalMode()) {
      setBatchTabCount('in_review', count('in_review'));
      setBatchTabCount('review_complete', count('review_complete'));
      return;
    }
    setBatchTabCount('open', batches.filter(item => !['completed', 'cancelled'].includes(item.status)).length);
    setBatchTabCount('completed', count('completed'));
    setBatchTabCount('cancelled', count('cancelled'));
    setBatchTabCount('all', batches.length);
  }

  function normalizeBatchFilter() {
    const allowed = approvalMode()
      ? ['in_review', 'review_complete']
      : ['open', 'completed', 'cancelled', 'all'];
    if (!allowed.includes(batchFilter)) batchFilter = approvalMode() ? 'in_review' : 'open';
  }

  function navigatePayment(url) {
    if (window.PortalAppShell?.navigateUrl) return window.PortalAppShell.navigateUrl(url);
    window.location.assign(url);
  }

  function batchCard(batch) {
    const counts = batch.counts || {};
    const number = batch.payment_number ? `Payment #${escape(batch.payment_number)}` : 'Payment batch';
    const pending = Number(counts.pending || 0);
    const returned = Number(counts.returned || 0);
    const total = Number(counts.total || 0);
    const nextAction = batch.requires_re_review ? `${Number(counts.changed || pending)} ${Number(counts.changed || pending) === 1 ? 'case needs' : 'cases need'} re-review`
      : batch.status === 'completed' ? 'Signed payment'
      : batch.status === 'awaiting_scan' ? 'Signed copy needed'
      : returned ? `${returned} returned for correction`
      : batch.status === 'review_complete' ? 'Ready to generate'
      : pending && approvalMode() ? `Review ${pending} ${pending === 1 ? 'case' : 'cases'}`
      : batch.status === 'draft' ? 'Prepare payment' : 'Awaiting approval';
    return `<a class="payment-batch-card" data-payment-batch="${escape(batch.id)}" href="${escape(detailUrl(batch.id))}">
      <span class="payment-batch-card-head"><strong>${number}</strong><b>${escape(money(batch.total_amount))}</b></span>
      <span class="payment-batch-card-foot"><span>${escape(total)} ${total === 1 ? 'case' : 'cases'} · ${escape(batch.payment_mode_summary || 'Payment')}</span><span class="payment-batch-next ${statusClass(batch.status)}">${escape(nextAction)}</span></span>
    </a>`;
  }

  function renderBatches() {
    normalizeBatchFilter();
    renderBatchTabCounts();
    const target = el('payments-batches');
    if (!target) return;
    document.querySelectorAll('[data-payment-batch-filter]').forEach(button => button.classList.toggle('active', button.dataset.paymentBatchFilter === batchFilter));
    const visible = batches.filter(item => {
      if (approvalMode()) return approvalQueueStatus(item) === batchFilter;
      return batchFilter === 'all' || (batchFilter === 'open' ? !['completed', 'cancelled'].includes(item.status) : item.status === batchFilter);
    });
    target.innerHTML = visible.length
      ? visible.map(batchCard).join('')
      : `<div class="empty-state"><div class="es-title">${approvalMode() ? 'No payment approvals waiting' : 'No payment batches'}</div><div class="es-sub">${approvalMode() ? 'Submitted batches appear here for the authorised approval role.' : 'Create a batch when invoice-matched cases are ready.'}</div></div>`;
    if (!visible.length && batchSearch) target.innerHTML = '<div class="empty-state"><div class="es-title">No matching payments</div><div class="es-sub">Try another payment number.</div></div>';
    window.MiniAppComponents?.bindPagination?.({container: el('payments-pagination'), pagination: batchPagination || {}, onPage: value => { batchPage = value; load(); }});
  }

  async function load(options) {
    if (!active()) return;
    normalizeBatchFilter();
    const routeBatchId = detailBatchId();
    if (routeBatchId) return openBatch(routeBatchId, options);
    const version = ++listLoadVersion;
    if (window.location.pathname.startsWith('/portal/')) window.history.replaceState(window.history.state, '', `${inboxPath()}?${listParams()}`);
    const target = el('payments-batches');
    if (target && !options?.quiet) target.innerHTML = '<div class="empty-state"><div class="spinner-inline"></div></div>';
    try {
      const response = await deps.apiFetch(`/payments/batches/?${listParams()}&view=${approvalMode() ? 'approval' : 'preparation'}`);
      if (version !== listLoadVersion || !active() || detailBatchId()) return;
      if (!response.ok || !response.data?.ok) throw new Error(response.data?.error || 'Could not load payment batches.');
      batches = response.data.batches || [];
      batchCounts = response.data.counts || null;
      batchPagination = response.data.pagination || null;
      batchPage = Number(batchPagination?.page || batchPage);
      if (window.location.pathname.startsWith('/portal/')) window.history.replaceState(window.history.state, '', `${inboxPath()}?${listParams()}`);
      if (el('payments-batches')) renderBatches();
      if (!approvalMode()) await loadReceiptBatches({quiet: options?.quiet});
    } catch (error) {
      if (version !== listLoadVersion || !active() || detailBatchId()) return;
      if (target) target.innerHTML = `<div class="batch-warning">${escape(error.message || 'Could not load payment batches.')}</div>`;
    }
  }

  async function loadSequence() {
    const status = el('payments-sequence-status');
    try {
      const response = await deps.apiFetch('/payments/sequence/');
      if (!response.ok || !response.data?.ok) throw new Error(response.data?.error || 'Could not load the payment number.');
      const input = el('payments-sequence-next');
      if (input) input.value = response.data.next_number || 1;
      sequenceRevision = Number(response.data.revision || 0);
      if (status) status.textContent = `Next official payment: ${response.data.next_number || 1}`;
    } catch (error) {
      if (status) status.textContent = error.message || 'Could not load the payment number.';
    }
  }

  async function saveSequence(button) {
    const nextNumber = el('payments-sequence-next')?.value;
    const reason = String(el('payments-sequence-reason')?.value || '').trim();
    if (!reason) return deps.showToast('Enter a reason for changing the next payment number.', 'error');
    deps.setButtonLoading(button, true, 'Saving...');
    try {
      const response = await request('/payments/sequence/', 'PATCH', {
        next_number: nextNumber, reason, revision: sequenceRevision,
      });
      if (!response.ok || !response.data?.ok) throw new Error(response.data?.error || 'Could not save the payment number.');
      el('payments-sequence-reason').value = '';
      sequenceRevision = Number(response.data.revision || sequenceRevision);
      if (el('payments-sequence-status')) el('payments-sequence-status').textContent = `Next official payment: ${response.data.next_number}`;
      deps.showToast('Official payment number updated.', 'success');
    } catch (error) {
      deps.showToast(error.message || 'Could not save the payment number.', 'error');
    } finally { deps.setButtonLoading(button, false); }
  }

  async function createBatch(button) {
    deps.setButtonLoading(button, true, 'Creating...');
    try {
      const response = await request('/payments/batches/', 'POST', {});
      if (!response.ok || !response.data?.ok) throw new Error(response.data?.error || 'Could not create payment batch.');
      activeBatch = response.data.batch;
      selected.clear();
      selectedModes.clear();
      navigatePayment(detailUrl(activeBatch.id));
      deps.showToast('Payment batch created.', 'success');
    } catch (error) {
      deps.showToast(error.message || 'Could not create payment batch.', 'error');
    } finally { deps.setButtonLoading(button, false); }
  }

  function showDetail() {
    if (!el('payments-detail')) return;
    el('payments-detail').hidden = false;
    renderDetail();
  }

  function receiptCount(receipt, status) {
    return Number(receipt?.counts?.[status] || 0);
  }

  function renderReceiptBatches() {
    const target = el('payments-receipts-list');
    if (!target) return;
    const visible = receiptBatches.filter(function (receipt) {
      return showArchivedReceipts ? receipt.archived : !receipt.archived && receipt.status !== 'payment_created' && receipt.total_count > 0;
    });
    if (!visible.length) {
      target.innerHTML = '<div class="empty-state compact"><div class="es-title">No invoice deliveries waiting</div><div class="es-sub">Receive an HB invoice delivery to start payment preparation.</div></div>';
      return;
    }
    target.innerHTML = visible.map(function (receipt) {
      const matched = receiptCount(receipt, 'matched');
      const correction = receiptCount(receipt, 'name_change');
      const held = receiptCount(receipt, 'review') + receiptCount(receipt, 'parse_failed');
      const action = receipt.payment_batch_id
        ? `<button type="button" class="btn btn-secondary payment-open-receipt-batch" data-payment-receipt-batch="${escape(receipt.payment_batch_id)}">Open payment</button>`
        : `<button type="button" class="btn btn-secondary payment-open-receipt" data-payment-receipt="${escape(receipt.id)}">Review delivery</button>`;
      return `<article class="payment-receipt-row"><div><strong>${escape(deps.fmtDate?.(receipt.created_at) || String(receipt.created_at || '').slice(0, 10))}</strong><small>${escape(matched)} ready${correction ? ` · ${escape(correction)} corrections` : ''}${held ? ` · ${escape(held)} need review` : ''}</small></div><div class="payment-receipt-row-action">${action}<button type="button" class="miniapp-icon-button portal-finance-icon" data-receipt-archive="${escape(receipt.id)}" aria-label="${receipt.archived ? 'Restore' : 'Archive'} delivery" title="${receipt.archived ? 'Restore' : 'Archive'} delivery"><i data-lucide="${receipt.archived ? 'archive-restore' : 'archive'}" aria-hidden="true"></i></button></div></article>`;
    }).join('');
    window.lucide?.createIcons?.();
  }

  async function loadReceiptBatches(options) {
    const target = el('payments-receipts-list');
    if (target && !options?.quiet) target.innerHTML = '<div class="empty-state compact"><div class="spinner-inline"></div></div>';
    try {
      const response = await deps.apiFetch(`/invoice-receipts/${showArchivedReceipts ? '?archived=1' : ''}`);
      if (!response.ok || !response.data?.ok) throw new Error(response.data?.error || 'Could not load invoice deliveries.');
      receiptBatches = response.data.batches || [];
      renderReceiptBatches();
    } catch (error) {
      if (target) target.innerHTML = `<div class="batch-warning">${escape(error.message || 'Could not load invoice deliveries.')}</div>`;
    }
  }

  function renderReceiptDialog() {
    const dialog = el('payment-receipt-dialog');
    const title = el('payment-receipt-dialog-title');
    const copy = el('payment-receipt-dialog-copy');
    const target = el('payment-receipt-dialog-items');
    const submit = el('payment-receipt-create');
    if (!dialog || !target || !activeReceipt) return;
    const items = activeReceipt.items || [];
    const payable = items.filter(function (item) { return ['matched', 'name_change'].includes(item.status) && item.farmer_id; });
    const held = items.filter(function (item) { return !['matched', 'name_change'].includes(item.status) || !item.farmer_id; });
    if (title) title.textContent = activeReceipt.payment_batch_id ? 'Payment created' : 'Prepare payment';
    if (copy) copy.textContent = activeReceipt.payment_batch_id
      ? 'This delivery already has a governed payment batch.'
      : 'Jawabu is selected by default. Switch Cash exceptions. Held invoices stay out of this payment.';
    target.innerHTML = [
      ...payable.map(function (item) {
        const label = item.applicant_name || item.invoice_holder_name || item.invoice_no || 'Matched invoice';
        const correction = item.status === 'name_change' ? ` · ${escape(item.reason || 'Corrected invoice needed')}` : '';
        return `<div class="payment-receipt-dialog-row"><span><strong>${escape(label)}</strong><small>${escape(item.invoice_no || 'Invoice')}${correction}</small></span><div class="payment-receipt-row-tools">${receiptPreviewButton(item)}<button type="button" class="payment-receipt-cash-toggle" data-payment-receipt-dialog-cash="${escape(item.farmer_id)}" aria-pressed="false" aria-label="Switch ${escape(label)} to Cash" title="Switch this invoice to Cash"><i data-lucide="landmark" aria-hidden="true"></i></button></div></div>`;
      }),
      ...held.map(function (item) {
        return `<div class="payment-receipt-dialog-row held"><span><strong>${escape(item.invoice_no || item.source_filename || 'Invoice')}</strong><small>${escape(item.reason || item.status_label || 'Needs review')}</small></span><div class="payment-receipt-row-tools">${receiptPreviewButton(item)}<span class="badge badge-orange">${escape(item.status_label || 'Held')}</span></div></div>`;
      }),
    ].join('') || '<div class="empty-state compact"><div class="es-title">No invoices in this delivery</div></div>';
    if (submit) submit.hidden = Boolean(activeReceipt.payment_batch_id) || !payable.length;
    if (dialog.showModal && !dialog.open) dialog.showModal();
    window.lucide?.createIcons?.();
  }

  function receiptPreviewButton(item) {
    return `<button type="button" class="miniapp-icon-button portal-finance-icon payment-receipt-invoice-preview" data-receipt-item="${escape(item.id)}" aria-label="Preview invoice ${escape(item.invoice_no || item.source_filename || '')}" title="Preview invoice" ${item.preview_url ? '' : 'disabled'}><i data-lucide="eye" aria-hidden="true"></i></button>`;
  }

  function closeReceiptPreview({fromHistory = false} = {}) {
    ++receiptPreviewVersion;
    el('payment-receipt-preview')?.close();
    if (!fromHistory && window.history.state?.receiptInvoicePreview) window.history.back();
    if (receiptPreviewUrl) window.SecureMediaViewer?.revoke(receiptPreviewUrl);
    receiptPreviewUrl = '';
    if (receiptPreviewTrigger?.isConnected) receiptPreviewTrigger.focus();
    window.dispatchEvent(new Event('portal:dialog-change'));
  }

  async function previewReceiptInvoice(button) {
    const item = activeReceipt?.items?.find(row => String(row.id) === button.dataset.receiptItem);
    const dialog = el('payment-receipt-preview'), content = el('payment-receipt-preview-content');
    if (!item?.preview_url || !dialog || !content) return;
    const version = ++receiptPreviewVersion;
    receiptPreviewTrigger = button;
    el('payment-receipt-preview-title').textContent = `Invoice ${item.invoice_no || ''}`.trim();
    content.innerHTML = '<div class="empty-state"><div class="spinner-inline"></div></div>';
    if (!dialog.open) { dialog.showModal(); window.history.pushState({...window.history.state, receiptInvoicePreview: true}, '', window.location.href); }
    window.dispatchEvent(new Event('portal:dialog-change'));
    try {
      const blob = await window.SecureMediaViewer.fetchAuthorizedBlob(item.preview_url, {
        headers: deps.portalApi?.initDataHeader?.(deps.tg) || {},
      });
      if (version !== receiptPreviewVersion || !dialog.open) return;
      if (receiptPreviewUrl) window.SecureMediaViewer.revoke(receiptPreviewUrl);
      const gallery = (activeReceipt?.items || []).filter(row => row.preview_url);
      const index = gallery.indexOf(item);
      const move = offset => previewReceiptInvoice({dataset: {receiptItem: String(gallery[index + offset].id)}});
      receiptPreviewUrl = window.SecureMediaViewer.renderBlob(content, blob, {
        name: item.source_filename || 'Invoice',
        onNext: index < gallery.length - 1 ? () => move(1) : undefined,
        onPrevious: index > 0 ? () => move(-1) : undefined,
      });
    } catch (error) {
      if (version === receiptPreviewVersion && dialog.open) content.innerHTML = `<p class="batch-warning">${escape(error.message || 'Could not load invoice.')}</p><button type="button" class="btn btn-secondary payment-receipt-invoice-preview" data-receipt-item="${escape(item.id)}">Retry</button>`;
    }
  }

  async function openReceipt(receiptId) {
    try {
      const response = await deps.apiFetch(`/invoice-receipts/${encodeURIComponent(receiptId)}/`);
      if (!response.ok || !response.data?.ok) throw new Error(response.data?.error || 'Could not open invoice delivery.');
      activeReceipt = response.data.receipt_batch;
      renderReceiptDialog();
    } catch (error) { deps.showToast(error.message || 'Could not open invoice delivery.', 'error'); }
  }

  async function createPaymentFromReceipt(button) {
    if (!activeReceipt?.id) return;
    const modes = {};
    (activeReceipt.items || []).filter(function (item) { return ['matched', 'name_change'].includes(item.status) && item.farmer_id; }).forEach(function (item) {
      modes[item.farmer_id] = 'LOAN-JAWABU';
    });
    el('payment-receipt-dialog-items')?.querySelectorAll('[data-payment-receipt-dialog-cash]').forEach(function (toggle) {
      if (toggle.getAttribute('aria-pressed') === 'true') modes[toggle.dataset.paymentReceiptDialogCash] = 'CASH';
    });
    if (!Object.keys(modes).length) return deps.showToast('There are no matched invoices to add to payment.', 'error');
    deps.setButtonLoading(button, true, 'Creating...');
    try {
      const response = await request(`/invoice-receipts/${activeReceipt.id}/payment/`, 'POST', {
        revision: activeReceipt.revision, payment_modes: modes,
      });
      if (!response.ok || !response.data?.ok) throw new Error(response.data?.error || 'Could not create payment batch.');
      el('payment-receipt-dialog')?.close();
      deps.showToast('Payment batch created from the invoice delivery.', 'success');
      navigatePayment(detailUrl(response.data.batch.id));
    } catch (error) { deps.showToast(error.message || 'Could not create payment batch.', 'error'); }
    finally { deps.setButtonLoading(button, false); }
  }

  function closeDetail() {
    navigatePayment(inboxUrl());
  }

  function setDetailFeedback(message, {error = false, loading = false, retry = false} = {}) {
    const root = el('payments-detail');
    const target = el('payments-detail-feedback');
    if (!root || !target) return;
    root.setAttribute('aria-busy', loading ? 'true' : 'false');
    if (!message) {
      target.hidden = true;
      target.replaceChildren();
      return;
    }
    target.hidden = false;
    target.classList.toggle('error', error);
    target.innerHTML = `${loading ? '<div class="spinner-inline" aria-hidden="true"></div>' : ''}<span>${escape(message)}</span>${retry ? '<button type="button" class="btn btn-secondary" id="payments-detail-retry">Retry</button>' : ''}`;
  }

  async function openBatch(id, options) {
    const loadVersion = ++detailLoadVersion;
    const routeSignature = `${screen()}:${detailBatchId()}`;
    if (!options?.quiet) setDetailFeedback('Loading payment batch…', {loading: true});
    try {
      const response = await deps.apiFetch(`/payments/batches/${encodeURIComponent(id)}/`);
      if (!active() || loadVersion !== detailLoadVersion || routeSignature !== `${screen()}:${detailBatchId()}`) return;
      if (!response.ok || !response.data?.ok) throw new Error(response.data?.error || 'Could not open payment batch.');
      activeBatch = response.data.batch;
      if (candidateBatchId !== String(activeBatch.id)) resetCandidateSearch();
      candidateBatchId = String(activeBatch.id);
      setDetailFeedback('');
      showDetail();
      if (candidatePanelOpen && !approvalMode() && capability('portal.payment.prepare')) await loadCandidates(options);
    } catch (error) {
      const message = error.message || 'Could not open payment batch.';
      setDetailFeedback(message, {error: true, retry: true});
      deps.showToast(message, 'error');
    }
  }

  function caseDetails(item) {
    const value = (itemValue, fallback = 'Not recorded') => escape(itemValue || fallback);
    return `<div class="payment-case-identifiers"><span>${value(item.case_reference, 'Case reference unavailable')}</span><span>ID ${value(item.national_id)}</span><span>${window.PortalMiniAppHelpers.phoneLink(item.primary_phone)}</span></div>
      <dl class="payment-case-details">
        <div><dt>Branch</dt><dd>${value(item.branch)}</dd></div>
        <div><dt>Loan officer</dt><dd>${value(item.loan_officer, 'Unassigned')}</dd></div>
        <div><dt>Invoice / order</dt><dd>${value(item.invoice_number)} / ${value(item.order_number)}</dd></div>
        <div><dt>Repayment</dt><dd>${value(item.preferred_repayment_date, 'Missing')}</dd></div>
      </dl>`;
  }

  function caseRow(item, {compact = false} = {}) {
    const canReview = approvalMode() && item.decision === 'pending' && capability('portal.payment.review') && (
      ['in_review', 'review_complete'].includes(activeBatch.status)
      || (activeBatch.status === 'awaiting_scan' && activeBatch.requires_re_review)
    );
    const canRemove = !approvalMode() && capability('portal.payment.prepare') && !['completed', 'cancelled'].includes(activeBatch.status);
    const warning = item.changed_since_review ? `<span class="payment-case-warning">${escape(item.changed_fields?.length ? `${item.changed_fields.join(', ')} changed` : 'Payment details changed')} — review again</span>` : '';
    const badge = `<span class="badge ${item.decision === 'approved' ? 'badge-green' : item.decision === 'returned' ? 'badge-orange' : 'badge-blue'}">${escape(item.changed_since_review ? 'Needs re-review' : item.decision === 'pending' ? 'Awaiting review' : item.decision)}</span>`;
    const customerName = escape(item.customer_name || 'Unnamed customer');
    const caseUrl = `/portal/cases/${escape(item.farmer_id)}/?from=${approvalMode() ? 'payment_approvals' : 'payments'}`;
    const history = `<button type="button" class="payment-case-open" data-case-url="${caseUrl}" aria-label="View case details for ${customerName}"><span>View case</span><i data-lucide="chevron-right" aria-hidden="true"></i></button>`;
    const cashSelected = item.payment_mode === 'CASH';
    const modeAction = canRemove ? `<button type="button" class="payment-candidate-cash-toggle${cashSelected ? ' is-cash' : ''}" data-payment-case-cash="${escape(item.farmer_id)}" aria-pressed="${cashSelected}" aria-label="${cashSelected ? 'Cash selected. Switch to Loan - Jawabu' : 'Loan selected. Switch to Cash'}" title="${cashSelected ? 'Cash selected. Switch to Loan - Jawabu' : 'Loan selected. Switch to Cash'}"><i data-lucide="${cashSelected ? 'banknote' : 'landmark'}" aria-hidden="true"></i></button>` : '';
    const removeAction = canRemove ? '<button type="button" class="payment-remove-case">Remove</button>' : '';
    return `<details class="payment-current-case payment-review-${escape(item.decision)}${item.changed_since_review ? ' changed' : ''}${compact ? ' payment-case-row' : ''}" data-payment-case="${escape(item.farmer_id)}">
      <summary class="payment-case-heading"><span class="payment-case-title"><strong>${customerName}</strong>${compact && item.decision === 'approved' ? '' : badge}</span><span class="payment-case-summary-facts"><b>${escape(money(item.amount))}</b><small>${escape(item.payment_mode_label || 'Payment not recorded')} <i data-lucide="chevron-down" aria-hidden="true"></i></small></span></summary>
      <div class="payment-case-expanded">${caseDetails(item)}${warning}<div class="payment-case-toolbar">${history}${modeAction}${removeAction}</div>
      ${canReview ? `<label class="payment-review-label">${item.changed_since_review ? 'Update prior comment for re-review' : 'Approval comment'}<textarea class="payment-review-comment" rows="2" placeholder="Record your reason or conditions">${escape(item.comment || '')}</textarea></label><div class="payment-case-actions"><button type="button" class="btn btn-secondary payment-return">Return</button><button type="button" class="btn btn-primary payment-approve">Approve</button></div>` : item.comment ? `<p class="payment-review-note"><strong>Head of Rural comment:</strong> ${escape(item.comment)}</p>` : ''}
      </div>
    </details>`;
  }

  function activityLabel(action) {
    return ({created: 'Batch created', cases_added: 'Cases added', case_removed: 'Case removed', submitted_for_review: 'Sent for review', case_reviewed: 'Case reviewed', reviews_invalidated: 'Review reopened after changes', case_mode_changed: 'Case payment mode changed', workbook_generated: 'Workbook generated', signed_scan_accepted: 'Signed scan accepted', cancelled: 'Batch cancelled'})[action] || String(action || '').replaceAll('_', ' ');
  }

  function formatDateTime(value) {
    if (!value) return '';
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? value : date.toLocaleString('en-GB', {day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit'}).replace(',', '');
  }

  function renderDetail() {
    if (!activeBatch) return;
    const unsaved = new Map();
    for (const [id, protection] of reviewProtections) {
      if (protection.isDirty()) unsaved.set(id, protection.input.value);
      protection.destroy();
    }
    reviewProtections.clear();
    const detailRoot = document.getElementById('payments-detail');
    const required = {
      title: detailRoot?.querySelector('#payments-detail-title'),
      meta: detailRoot?.querySelector('#payments-detail-meta'),
      total: detailRoot?.querySelector('#payments-detail-total'),
      progress: detailRoot?.querySelector('#payments-progress'),
      cases: detailRoot?.querySelector('#payments-current-cases'),
      activity: detailRoot?.querySelector('#payments-activity'),
    };
    if (!detailRoot || [required.title, required.meta, required.progress, required.cases, required.activity].some(node => !node)) {
      setDetailFeedback('Payment details could not be displayed. Retry this page or return to payment batches.', {error: true, retry: true});
      window.dispatchEvent(new CustomEvent('portal:render-error', {detail: {screen: screen(), component: 'payment-detail'}}));
      return;
    }
    const counts = activeBatch.counts || {};
    const emptyDraft = activeBatch.status === 'draft' && Number(counts.total || 0) === 0;
    detailRoot.classList.toggle('payment-detail-empty', emptyDraft);
    required.title.textContent = activeBatch.payment_number ? `Payment #${activeBatch.payment_number}` : 'Payment batch';
    required.meta.textContent = activeBatch.status_label || activeBatch.payment_mode_summary || '';
    if (required.total) required.total.textContent = money(activeBatch.total_amount);
    required.progress.innerHTML = [['pending','awaiting review'],['returned','returned'],['approved','approved']].filter(([key])=>Number(counts[key])>0).map(([key,label])=>`<span><strong>${escape(counts[key])}</strong> ${label}</span>`).join('');
    required.progress.hidden = emptyDraft || (!Number(counts.pending) && !Number(counts.returned));
    const cases = activeBatch.cases || [];
    const approvedCases = cases.filter(item => item.decision === 'approved');
    const actionableCases = cases.filter(item => item.decision !== 'approved');
    const currentHeading = el('payments-current-heading');
    if (currentHeading) {
      currentHeading.hidden = actionableCases.length === 0;
      const title = currentHeading.querySelector('h3');
      if (title) title.textContent = approvalMode() ? 'Cases to review' : 'Cases in this payment';
    }
    required.cases.innerHTML = cases.length ? [
      actionableCases.length ? actionableCases.map(caseRow).join('') : '',
      approvedCases.length ? `<details class="payment-approved-cases"><summary><span>Approved</span><b>${escape(approvedCases.length)}</b></summary><div class="payment-approved-case-list">${approvedCases.map(item => caseRow(item, {compact: true})).join('')}</div></details>` : '',
    ].join('') : '<div class="empty-state compact"><div class="es-title">No cases added</div></div>';
    required.cases.querySelectorAll('[data-payment-case]').forEach(card => {
      const input = card.querySelector('.payment-review-comment');
      if (!input) return;
      const id = card.dataset.paymentCase;
      const protection = window.MiniAppUtils?.bindFormCloseProtection?.(card, `payment-review:${id}`, () => input.value);
      if (!protection) return;
      protection.input = input;
      reviewProtections.set(id, protection);
      if (unsaved.has(id)) { input.value = unsaved.get(id); protection.markDirty(); }
    });
    if (el('payments-current-section')) el('payments-current-section').hidden = emptyDraft;
    const heldItems = activeBatch.held_items || [];
    const heldTarget = el('payments-held-items');
    const heldSection = el('payments-held-section');
    if (heldTarget) {
      heldTarget.innerHTML = heldItems.map(function (item) {
        const add = item.can_add_to_payment && !approvalMode() && capability('portal.payment.prepare') && !['completed', 'cancelled'].includes(activeBatch.status)
          ? `<div class="payment-receipt-add"><button type="button" class="payment-receipt-cash-toggle" data-payment-receipt-cash="${escape(item.farmer_id)}" aria-pressed="false" aria-label="Switch ${escape(item.applicant_name || item.invoice_no || 'invoice')} to Cash" title="Switch this invoice to Cash"><i data-lucide="landmark" aria-hidden="true"></i></button><button type="button" class="btn btn-secondary payment-add-receipt-item" data-payment-receipt-farmer="${escape(item.farmer_id)}">Add to payment</button></div>`
          : '';
        const label = item.can_add_to_payment ? 'Corrected - ready to add' : (item.status_label || 'Held');
        return `<article class="payment-current-case payment-held-item${item.can_add_to_payment ? ' payment-receipt-ready' : ''}"><div class="payment-case-heading"><strong>${escape(item.invoice_no || 'Unparsed invoice')}</strong><span class="badge ${item.can_add_to_payment ? 'badge-green' : 'badge-orange'}">${escape(label)}</span></div><div class="payment-case-values"><span>Invoice: ${escape(item.invoice_holder_name || 'Unknown holder')}</span><span>Applicant: ${escape(item.applicant_name || 'Not matched')}</span></div>${item.reason ? `<p class="payment-review-note">${escape(item.reason)}</p>` : ''}${add}</article>`;
      }).join('');
    }
    if (heldSection) heldSection.hidden = !heldItems.length;
    const activity = activeBatch.activity || [];
    required.activity.innerHTML = activity.length ? activity.map(item => `<div><strong>${escape(activityLabel(item.action))}</strong>${window.MiniAppActivityChanges?.html(item.changes, {title: activityLabel(item.action)}) || ''}<small>${escape(item.actor)} &middot; ${escape(formatDateTime(item.created_at))}</small></div>`).join('') : '<small>No batch changes recorded.</small>';
    const activityPanel = required.activity.closest('.payment-activity');
    if (activityPanel) activityPanel.hidden = emptyDraft;
    const addPanel = el('payments-add-panel');
    if (addPanel) addPanel.hidden = approvalMode() || !capability('portal.payment.prepare') || ['completed', 'cancelled'].includes(activeBatch.status);
    if (addPanel?.hidden) setCandidatePanel(false);
    renderPrimaryAction();
    window.lucide?.createIcons?.();
  }

  function renderPrimaryAction() {
    const target = el('payments-primary-action');
    if (!target || !activeBatch) return;
    let documents = el('payments-document-actions');
    if (!documents) {
      documents = document.createElement('div');
      documents.id = 'payments-document-actions';
      documents.className = 'payment-document-actions';
      el('payments-detail')?.querySelector('.payment-detail-header')?.insertAdjacentElement('afterend', documents);
    }
    documents.innerHTML = '';
    if (Number(activeBatch.counts?.total || 0) > 0 && capability('portal.payment.view') && !(activeBatch.requires_re_review && activeBatch.status === 'awaiting_scan')) {
      documents.insertAdjacentHTML('beforeend', '<button type="button" class="btn btn-secondary payment-preview-action" id="payments-preview-sheet"><i data-lucide="eye" aria-hidden="true"></i> Preview payment</button>');
    }
    if (activeBatch.status === 'awaiting_scan' && !activeBatch.requires_re_review && activeBatch.workbook_download_url) {
      documents.insertAdjacentHTML('beforeend', '<button type="button" class="btn btn-secondary" id="payments-open-workbook"><i data-lucide="download" aria-hidden="true"></i> Download workbook</button>');
    }
    if (activeBatch.status === 'completed' && activeBatch.signed_scan_url) {
      documents.insertAdjacentHTML('beforeend', '<button type="button" class="btn btn-secondary" id="payments-open-signed-copy">Open signed copy</button>');
    }
    if (!approvalMode() && capability('portal.payment.prepare') && Number(activeBatch.counts?.total || 0) > 0 && !['completed', 'cancelled'].includes(activeBatch.status)) {
      documents.insertAdjacentHTML('beforeend', '<button type="button" class="payment-cancel-link" id="payments-cancel">Cancel batch</button>');
    }
    documents.hidden = !documents.childElementCount;
    if (activeBatch.status === 'draft' && capability('portal.payment.prepare') && Number(activeBatch.counts?.total || 0) > 0) {
      target.innerHTML = '<button type="button" class="btn btn-primary" id="payments-submit-review">Submit for payment approval</button>';
    } else if (activeBatch.status === 'in_review') {
      target.innerHTML = approvalMode() ? '' : '<div class="payment-state-note">This batch is with the payment approver.</div>';
    } else if (activeBatch.requires_re_review) {
      target.innerHTML = `<div class="payment-state-note">${approvalMode() ? 'Review the changed cases above. The previous workbook cannot be signed.' : 'Payment details changed. Head of Rural must review the changed cases again.'}</div>`;
    } else if (activeBatch.status === 'review_complete' && approvalMode() && capability('portal.payment.review')) {
      target.innerHTML = '<button type="button" class="btn btn-primary" id="payments-generate">Confirm and generate workbook</button>';
    } else if (activeBatch.status === 'review_complete') {
      target.innerHTML = '<div class="payment-state-note">Approval complete. The approver will generate the workbook.</div>';
    } else if (activeBatch.status === 'awaiting_scan') {
      const upload = capability('portal.documents.sign') ? '<label class="payment-scan-picker"><input type="file" id="payments-scan-file" accept="application/pdf,image/jpeg,image/png"><span id="payments-scan-label">Select signed scan</span></label><button type="button" class="btn btn-primary" id="payments-upload-scan">Upload signed copy</button>' : '<p class="payment-state-note">Waiting for an authorised user to upload the signed copy.</p>';
      target.innerHTML = upload;
    } else if (activeBatch.status === 'completed') {
      target.innerHTML = '';
    } else target.innerHTML = '';
    target.hidden = target.childElementCount === 0;
    target.classList.toggle('payment-primary-action-quiet', Boolean(target.querySelector('.payment-state-note')));
  }

  let candidateBatchId = '';

  function resetCandidateSearch() {
    ++candidateLoadVersion;
    clearTimeout(searchTimer);
    candidatePanelOpen = false;
    candidatePage = 1;
    candidates = [];
    selected.clear();
    selectedModes.clear();
    if (el('payments-search')) el('payments-search').value = '';
    setCandidatePanel(false);
  }

  function setCandidatePanel(open) {
    candidatePanelOpen = open;
    const panel = el('payments-search-results');
    if (panel) panel.hidden = !open;
    el('payments-search')?.setAttribute('aria-expanded', String(open));
    if (!open) { ++candidateLoadVersion; clearTimeout(searchTimer); }
  }

  function closeCandidatePanel() {
    setCandidatePanel(false);
    const input = el('payments-search');
    suppressCandidateFocus = document.activeElement !== input;
    input?.focus();
    suppressCandidateFocus = false;
  }

  function candidateCard(item) {
    const row = item.row || {};
    const id = String(item.farmer_id || '');
    const current = new Set((activeBatch?.cases || []).map(entry => String(entry.farmer_id)));
    const blocked = item.selectable !== true || current.has(id);
    const mode = selectedModes.get(id) || 'LOAN-JAWABU';
    const reasons = current.has(id) ? 'Already in this payment' : item.unavailable_reason;
    const advisory = !blocked ? (item.warnings || []).join(', ') : '';
    const reasonId = `payment-case-reason-${id}`;
    return `<article class="payment-candidate${!blocked ? ' has-mode-toggle' : ''}${blocked ? ' blocked' : ''}${selected.has(id) ? ' selected' : ''}">
      <span class="payment-candidate-main"><label class="payment-candidate-select"><input class="payment-candidate-checkbox" type="checkbox" value="${escape(id)}" aria-label="Select ${escape(item.customer_name || row.name || 'case')}" ${selected.has(id) ? 'checked' : ''} ${blocked ? `disabled aria-describedby="${escape(reasonId)}"` : ''}></label><span><strong>${escape(item.customer_name || row.name || 'Unnamed customer')}</strong><small>${escape([item.national_id ? `ID ${item.national_id}` : '', item.invoice_number ? `Invoice ${item.invoice_number}` : '', row.hb_invoice_amount != null ? money(row.hb_invoice_amount) : ''].filter(Boolean).join(' · '))}</small></span></span>
      ${!blocked ? `<button type="button" class="payment-candidate-cash-toggle${mode === 'CASH' ? ' is-cash' : ''}" data-payment-candidate-cash="${escape(id)}" aria-pressed="${mode === 'CASH'}" aria-label="${mode === 'CASH' ? 'Cash selected. Switch back to Loan - Jawabu' : 'Switch this case to Cash'}" title="${mode === 'CASH' ? 'Cash selected. Switch back to Loan - Jawabu' : 'Switch this case to Cash'}"><i data-lucide="${mode === 'CASH' ? 'banknote' : 'landmark'}" aria-hidden="true"></i><span class="sr-only">${mode === 'CASH' ? 'Cash' : 'Loan - Jawabu'}</span></button>` : ''}
      ${blocked ? `<span id="${escape(reasonId)}" class="payment-candidate-warning">${escape(reasons || 'Payment details need attention')}</span>` : ''}
      ${advisory ? `<span class="payment-candidate-warning payment-candidate-advisory">${escape(advisory)}</span>` : ''}
    </article>`;
  }

  function renderCandidates() {
    if (!el('payments-list')) return;
    const html = candidates.map(candidateCard);
    const resultCount = el('payments-result-count');
    if (resultCount) resultCount.textContent = `${candidatePagination?.total ?? html.length} cases found`;
    el('payments-list').innerHTML = html.length ? html.join('') : '<div class="empty-state compact"><div class="es-title">No matching cases</div></div>';
    el('payments-selected-count').textContent = `${selected.size} selected`;
    el('payments-clear-selection').hidden = selected.size === 0;
    el('payments-add-selected').disabled = selected.size === 0;
    window.MiniAppComponents?.bindPagination?.({container: el('payments-candidate-pagination'), pagination: candidatePagination || {}, onPage: value => { candidatePage = value; loadCandidates(); }});
    window.lucide?.createIcons?.();
  }

  async function loadCandidates(options) {
    if (!activeBatch || !candidatePanelOpen || approvalMode() || !capability('portal.payment.prepare')) return;
    const version = ++candidateLoadVersion;
    const batchId = String(activeBatch.id);
    const list = el('payments-list');
    if (list && !options?.quiet) list.innerHTML = '<div class="empty-state compact"><div class="spinner-inline"></div></div>';
    try {
      const query = String(el('payments-search')?.value || '').trim();
      const params = new URLSearchParams({include_all: '1', batch_id: batchId, search: query, page: String(candidatePage)});
      const response = await deps.apiFetch('/payments/candidates/?' + params);
      if (version !== candidateLoadVersion || !candidatePanelOpen || batchId !== String(activeBatch?.id) || batchId !== detailBatchId()) return;
      if (!response.ok || !response.data?.ok) throw new Error(response.data?.error || 'Could not load payment cases.');
      candidates = response.data.results || [];
      candidatePagination = response.data.pagination || null;
      candidatePage = Number(candidatePagination?.page || candidatePage);
      // Revoke newly blocked selections on this page; keep unrelated selections.
      candidates.filter(item => !item.selectable).forEach(item => { selected.delete(String(item.farmer_id)); selectedModes.delete(String(item.farmer_id)); });
      renderCandidates();
    } catch (error) {
      if (version !== candidateLoadVersion || !candidatePanelOpen || batchId !== String(activeBatch?.id) || batchId !== detailBatchId()) return;
      if (list) list.innerHTML = `<div class="batch-warning">${escape(error.message || 'Could not load payment cases.')}</div>`;
    }
  }

  async function mutate(path, body, button, loadingText) {
    document.querySelector('.payment-generation-error')?.remove();
    deps.setButtonLoading(button, true, loadingText || 'Saving...');
    let response = null;
    try {
      response = await request(path, 'POST', {...body, revision: activeBatch.revision});
      if (!response.ok || !response.data?.ok) throw new Error(response.data?.error || 'The payment batch could not be updated.');
      const reviewedCase = path.match(/\/cases\/([^/]+)\/review\/$/);
      if (reviewedCase) reviewProtections.get(decodeURIComponent(reviewedCase[1]))?.markClean();
      activeBatch = response.data.batch;
      renderDetail();
      if (!approvalMode()) await loadCandidates({quiet: true});
      const list = await deps.apiFetch(`/payments/batches/?${listParams()}&view=${approvalMode() ? 'approval' : 'preparation'}`);
      if (list.ok && list.data?.ok) { batches = list.data.batches || []; batchCounts = list.data.counts || null; renderBatchTabCounts(); }
      return true;
    } catch (error) {
      const message = error.message || 'The payment batch could not be updated.';
      deps.showToast(message, 'error');
      if (path.endsWith('/generate/')) {
        const requestId = response?.data?.support_reference || window.MiniAppUtils?.displaySupportReference?.(response?.data?.request_id || response?.requestId) || '';
        // Number allocation is durable before the external workbook upload.
        // Reload so a retry sends the current revision and retains that same
        // number instead of failing as a stale client.
        await openBatch(activeBatch.id, {quiet: true});
        el('payments-primary-action')?.insertAdjacentHTML(
          'beforeend',
          `<div class="batch-warning payment-generation-error" role="alert"><strong>Workbook not generated</strong><span>${escape(message)}</span>${requestId ? `<small>Reference ${escape(requestId)}</small>` : ''}</div>`,
        );
      }
      if (/changed (while|after review)/i.test(String(error.message || ''))) {
        await openBatch(activeBatch.id, {quiet: true});
      }
      return false;
    } finally { deps.setButtonLoading(button, false); }
  }

  function confirmFirstSubmission() {
    if (activeBatch?.submitted_at) return Promise.resolve(true);
    const counts = activeBatch?.counts || {};
    const copy = `Submit ${counts.total || 0} case${Number(counts.total || 0) === 1 ? '' : 's'} for payment approval? The official payment number is allocated only after every case is approved and the workbook is generated.`;
    const dialog = el('payment-submit-confirm');
    if (!dialog?.showModal) {
      return Promise.resolve(window.confirm(copy));
    }
    el('payment-submit-confirm-copy').textContent = copy;
    el('payment-submit-confirm-cases').textContent = String(counts.total || 0);
    el('payment-submit-confirm-total').textContent = money(activeBatch?.total_amount);
    return new Promise(resolve => {
      const close = () => {
        dialog.removeEventListener('close', close);
        resolve(dialog.returnValue === 'confirm');
      };
      dialog.addEventListener('close', close);
      dialog.showModal();
    });
  }

  async function submitForReview(button) {
    if (!await confirmFirstSubmission()) return;
    if (button.disabled) return;
    await mutate(`/payments/batches/${activeBatch.id}/submit/`, {}, button, 'Submitting...');
  }

  async function previewSheet(button) {
    const overlay = el('payment-preview-overlay');
    const target = el('payment-preview-content');
    if (!overlay || !target || !activeBatch) return;
    const batchId = activeBatch.id;
    const requestVersion = ++previewRequestVersion;
    previewTrigger = button;
    overlay.classList.add('open');
    try {
      window.history.pushState({...window.history.state, paymentPreview: true}, '', window.location.href);
      previewHistoryActive = true;
    } catch (_) { previewHistoryActive = false; }
    target.innerHTML = '<div class="empty-state"><div class="spinner-inline"></div></div>';
    deps.setButtonLoading(button, true, 'Loading...');
    try {
      const response = await deps.apiFetch(`/payments/batches/${encodeURIComponent(batchId)}/preview/`);
      if (requestVersion !== previewRequestVersion || !overlay.classList.contains('open') || activeBatch?.id !== batchId) return;
      if (!response.ok || !response.data?.ok) throw new Error(response.data?.error || 'Payment sheet could not be previewed.');
      const preview = response.data.preview;
      el('payment-preview-title').textContent = preview.draft ? 'Draft payment sheet' : `Payment sheet #${preview.payment_number}`;
      el('payment-preview-sub').textContent = preview.draft ? 'Before Head of Rural review' : 'Saved workbook snapshot';
      target.innerHTML = deps.requisitions.renderPrintablePayment(preview);
    } catch (error) {
      if (requestVersion === previewRequestVersion && overlay.classList.contains('open')) target.innerHTML = `<div class="batch-warning">${escape(error.message || 'Payment sheet could not be previewed.')}</div>`;
    } finally { deps.setButtonLoading(button, false); }
  }

  function closePreview({fromHistory = false} = {}) {
    const overlay = el('payment-preview-overlay');
    if (!previewHistoryActive && !overlay?.classList.contains('open')) return;
    previewRequestVersion += 1;
    overlay?.classList.remove('open');
    overlay?.setAttribute('aria-hidden', 'true');
    if (previewHistoryActive && !fromHistory && window.history.state?.paymentPreview) window.history.back();
    previewHistoryActive = false;
    if (previewTrigger?.isConnected) previewTrigger.focus();
    previewTrigger = null;
  }

  async function addSelected(button) {
    if (!selected.size) return;
    const paymentModes = Object.fromEntries([...selected].map(id => [id, selectedModes.get(id) || 'LOAN-JAWABU']));
    if (await mutate(`/payments/batches/${activeBatch.id}/cases/`, {farmer_ids: [...selected], payment_modes: paymentModes}, button, 'Adding...')) {
      selected.clear(); selectedModes.clear(); renderCandidates(); setCandidatePanel(false); deps.showToast('Cases added to payment batch.', 'success');
    } else {
      await loadCandidates({quiet: true});
    }
  }

  async function toggleCaseMode(button) {
    const farmerId = button.dataset.paymentCaseCash;
    const mode = button.getAttribute('aria-pressed') === 'true' ? 'LOAN-JAWABU' : 'CASH';
    button.disabled = true;
    try {
      const response = await request(
        `/payments/batches/${activeBatch.id}/cases/${farmerId}/mode/`, 'POST',
        {payment_mode: mode, revision: activeBatch.revision}
      );
      if (!response.ok || !response.data?.ok) throw new Error(response.data?.error || 'Could not change this case payment mode.');
      activeBatch = response.data.batch;
      renderDetail();
      deps.showToast(mode === 'CASH' ? 'Case changed to Cash.' : 'Case changed to Loan - Jawabu.', 'success');
    } catch (error) {
      deps.showToast(error.message || 'Could not change this case payment mode.', 'error');
    } finally { button.disabled = false; }
  }

  async function addReceiptItem(button) {
    const farmerId = String(button.dataset.paymentReceiptFarmer || '');
    const cashToggle = button.parentElement?.querySelector('[data-payment-receipt-cash]');
    if (!farmerId) return deps.showToast('This corrected invoice cannot be added yet.', 'error');
    const paymentMode = cashToggle?.getAttribute('aria-pressed') === 'true' ? 'CASH' : 'LOAN-JAWABU';
    if (await mutate(`/payments/batches/${activeBatch.id}/cases/`, {farmer_ids: [farmerId], payment_modes: {[farmerId]: paymentMode}}, button, 'Adding...')) {
      deps.showToast('Corrected invoice added to the payment batch.', 'success');
    }
  }

  function toggleReceiptCash(button) {
    const cash = button.getAttribute('aria-pressed') !== 'true';
    button.setAttribute('aria-pressed', cash ? 'true' : 'false');
    button.classList.toggle('is-cash', cash);
    const title = cash ? 'Cash selected. Switch back to Loan - Jawabu' : 'Switch this invoice to Cash';
    button.title = title;
    button.setAttribute('aria-label', title);
    button.innerHTML = cash
      ? '<i data-lucide="banknote" aria-hidden="true"></i>'
      : '<i data-lucide="landmark" aria-hidden="true"></i>';
    window.lucide?.createIcons?.();
  }

  async function reviewCase(card, decision, button) {
    const comment = String(card.querySelector('.payment-review-comment')?.value || '').trim();
    if (!comment) return deps.showToast('Enter an approval comment for this case.', 'error');
    if (await mutate(`/payments/batches/${activeBatch.id}/cases/${card.dataset.paymentCase}/review/`, {decision, comment}, button, decision === 'approved' ? 'Approving...' : 'Returning...')) {
      deps.showToast(decision === 'approved' ? 'Case approved.' : 'Case returned for correction.', 'success');
    }
  }

  async function removeCase(card, button) {
    const reason = window.prompt('Why are you removing this case from the payment batch?', '');
    if (!reason?.trim()) return;
    await mutate(`/payments/batches/${activeBatch.id}/cases/${card.dataset.paymentCase}/remove/`, {reason: reason.trim()}, button, 'Removing...');
  }

  async function cancelBatch(button) {
    if (!window.confirm('Cancel this unsigned payment? Its cases return to payment preparation and its number can be reused.')) return;
    if (await mutate(`/payments/batches/${activeBatch.id}/cancel/`, {reason: ''}, button, 'Cancelling...')) {
      deps.showToast('Payment batch cancelled. Its cases can be added to another batch.', 'success');
      await load({quiet: true});
    }
  }

  async function uploadScan(button) {
    const file = el('payments-scan-file')?.files?.[0];
    if (!file) return deps.showToast('Select the signed PDF, JPG or PNG first.', 'error');
    const data = new FormData(); data.append('signed_scan', file);
    deps.setButtonLoading(button, true, 'Uploading...');
    try {
      const response = await deps.portalApi.postForm(`/document-signoffs/payment/${activeBatch.current_document_id}/upload/`, data, deps.tg, {'X-CSRFToken': deps.getCookie('csrftoken') || ''});
      if (!response.ok || !response.data?.ok) throw new Error(response.data?.error || 'Could not upload the signed copy.');
      deps.showToast('Signed copy accepted. Payment completed.', 'success');
      await openBatch(activeBatch.id, {quiet: true});
      const list = await deps.apiFetch('/payments/batches/');
      if (list.ok && list.data?.ok) batches = list.data.batches || [];
    } catch (error) { deps.showToast(error.message || 'Could not upload the signed copy.', 'error'); }
    finally { deps.setButtonLoading(button, false); }
  }

  function bind() {
    if (document.documentElement.dataset.portalPaymentsBound) return;
    document.documentElement.dataset.portalPaymentsBound = 'true';
    window.addEventListener('popstate', () => {
      if (el('payment-receipt-preview')?.open && !window.history.state?.receiptInvoicePreview) closeReceiptPreview({fromHistory: true});
      if (previewHistoryActive && !window.history.state?.paymentPreview) closePreview({fromHistory: true});
    });
    document.addEventListener('keydown', event => {
      if (event.key === 'Escape' && previewHistoryActive) closePreview();
      if (event.key === 'Escape' && candidatePanelOpen && event.target.closest('#payments-add-panel')) {
        // Native search inputs otherwise clear the term and emit an input
        // event, immediately reopening the panel we just closed.
        event.preventDefault();
        closeCandidatePanel();
      }
    });
    el('payment-receipt-preview')?.addEventListener('cancel', event => { event.preventDefault(); closeReceiptPreview(); });
    const previewOverlay = el('payment-preview-overlay');
    if (previewOverlay) new MutationObserver(() => {
      if (previewHistoryActive && !previewOverlay.classList.contains('open')) closePreview();
    }).observe(previewOverlay, {attributes: true, attributeFilter: ['class']});
    document.addEventListener('change', event => {
      const checkbox = event.target.closest('.payment-candidate-checkbox');
      if (checkbox && !checkbox.disabled) {
        const id = checkbox.value;
        const restoreFocus = document.activeElement === checkbox;
        checkbox.checked ? selected.add(id) : selected.delete(id);
        renderCandidates();
        if (restoreFocus) [...el('payments-list').querySelectorAll('.payment-candidate-checkbox')].find(input => input.value === id)?.focus();
        return;
      }
      if (event.target.id === 'payments-scan-file') {
        const file = event.target.files?.[0]; el('payments-scan-label').textContent = file ? file.name : 'Select signed scan';
      }
    });
    document.addEventListener('input', event => {
      if (event.target.id === 'payments-batch-search') {
        batchSearch = event.target.value.trim(); batchPage = 1;
        clearTimeout(searchTimer); searchTimer = setTimeout(() => load(), 300); return;
      }
      if (event.target.id !== 'payments-search') return;
      setCandidatePanel(true); candidatePage = 1; ++candidateLoadVersion;
      clearTimeout(searchTimer); searchTimer = setTimeout(() => loadCandidates(), 250);
    });
    document.addEventListener('focusin', event => {
      if (event.target.id === 'payments-search' && !candidatePanelOpen && !suppressCandidateFocus) { setCandidatePanel(true); loadCandidates(); }
    });
    document.addEventListener('click', event => {
      const target = event.target;
      if (target.closest('#payments-search-close')) { closeCandidatePanel(); return; }
      if (target.closest('#payment-receipt-preview-close')) return closeReceiptPreview();
      if (target.closest('.payment-receipt-invoice-preview')) return previewReceiptInvoice(target.closest('.payment-receipt-invoice-preview'));
      const batch = target.closest('[data-payment-batch]');
      if (batch) {
        event.preventDefault();
        const url = batch.getAttribute('href') || detailUrl(batch.dataset.paymentBatch);
        return navigatePayment(url);
      }
      const batchFilterButton = target.closest('[data-payment-batch-filter]');
      if (batchFilterButton) { batchFilter = batchFilterButton.dataset.paymentBatchFilter; batchPage = 1; return load(); }
      if (target.closest('#payments-refresh')) return load();
      if (target.closest('#payments-receipts-toggle')) {
        showArchivedReceipts = !showArchivedReceipts;
        target.closest('button').setAttribute('aria-pressed', String(showArchivedReceipts));
        return loadReceiptBatches();
      }
      const archiveReceipt = target.closest('[data-receipt-archive]');
      if (archiveReceipt) {
        const receipt = receiptBatches.find(item => item.id === archiveReceipt.dataset.receiptArchive);
        if (!receipt || !window.confirm(`${receipt.archived ? 'Restore' : 'Archive'} this delivery? Its invoices will not be changed.`)) return;
        deps.setButtonLoading(archiveReceipt, true);
        deps.portalApi.postJson(`/invoice-receipts/${receipt.id}/archive/`, {archived: !receipt.archived, revision: receipt.revision}, deps.tg)
          .then(result => { if (!result.ok || !result.data?.ok) throw new Error(result.data?.error || 'Delivery could not be changed.'); return loadReceiptBatches(); })
          .catch(error => deps.showToast(error.message, 'error'))
          .finally(() => deps.setButtonLoading(archiveReceipt, false));
        return;
      }
      if (target.closest('#payments-receive-invoices')) return navigatePayment('/portal/s/invoices/upload/');
      if (target.closest('.payment-open-receipt')) return openReceipt(target.closest('.payment-open-receipt').dataset.paymentReceipt);
      if (target.closest('.payment-open-receipt-batch')) return navigatePayment(detailUrl(target.closest('.payment-open-receipt-batch').dataset.paymentReceiptBatch));
      if (target.closest('#payment-receipt-create')) return createPaymentFromReceipt(target.closest('#payment-receipt-create'));
      if (target.closest('#payments-sequence-save')) return saveSequence(target.closest('#payments-sequence-save'));
      if (target.closest('#payments-detail-back')) return closeDetail();
      if (target.closest('#payments-detail-retry')) return openBatch(detailBatchId(), {});
      if (target.closest('#payments-clear-selection')) { selected.clear(); selectedModes.clear(); return renderCandidates(); }
      if (target.closest('#payments-add-selected')) return addSelected(target.closest('#payments-add-selected'));
      const candidateCashToggle = target.closest('[data-payment-candidate-cash]');
      if (candidateCashToggle) {
        const id = candidateCashToggle.dataset.paymentCandidateCash;
        selectedModes.set(id, candidateCashToggle.getAttribute('aria-pressed') === 'true' ? 'LOAN-JAWABU' : 'CASH');
        renderCandidates();
        return;
      }
      const caseCashToggle = target.closest('[data-payment-case-cash]');
      if (caseCashToggle) return toggleCaseMode(caseCashToggle);
      if (target.closest('.payment-receipt-cash-toggle')) return toggleReceiptCash(target.closest('.payment-receipt-cash-toggle'));
      if (target.closest('.payment-add-receipt-item')) return addReceiptItem(target.closest('.payment-add-receipt-item'));
      if (target.closest('#payments-submit-review')) return submitForReview(target.closest('#payments-submit-review'));
      if (target.closest('#payments-preview-sheet')) return previewSheet(target.closest('#payments-preview-sheet'));
      if (target.closest('#payments-generate')) return mutate(`/payments/batches/${activeBatch.id}/generate/`, {}, target.closest('#payments-generate'), 'Generating...');
      if (target.closest('#payments-open-workbook')) return deps.downloadPortalFile({url: activeBatch.workbook_download_url, filename: activeBatch.workbook_filename || `Payment-${activeBatch.payment_number || 'workbook'}.xlsx`});
      if (target.closest('#payments-open-signed-copy')) return deps.openPortalLink(activeBatch.signed_scan_url);
      if (target.closest('#payments-upload-scan')) return uploadScan(target.closest('#payments-upload-scan'));
      if (target.closest('#payments-cancel')) return cancelBatch(target.closest('#payments-cancel'));
      const card = target.closest('[data-payment-case]');
      if (card && target.closest('.payment-approve')) return reviewCase(card, 'approved', target.closest('.payment-approve'));
      if (card && target.closest('.payment-return')) return reviewCase(card, 'returned', target.closest('.payment-return'));
      if (card && target.closest('.payment-remove-case')) return removeCase(card, target.closest('.payment-remove-case'));
      const history = target.closest('.payment-case-open');
      if (history) {
        const url = history.dataset.caseUrl;
        if (window.PortalCaseNavigation?.open?.(url)) return;
        window.location.assign(url);
      }
    });
  }

  function init(initialDeps) {
    deps = initialDeps;
    const params = new URLSearchParams(window.location.search);
    batchFilter = params.get('status') || (approvalMode() ? 'in_review' : 'open');
    batchPage = Math.max(1, parseInt(params.get('page'), 10) || 1);
    batchSearch = params.get('search') || '';
    if (el('payments-batch-search')) el('payments-batch-search').value = batchSearch;
    bind();
  }
  window.PortalMiniAppPayments = {init, load, loadSequence};
})();
