(function () {
  'use strict';

  let deps = null;
  let activeBatch = null;
  let batches = [];
  let receiptBatches = [];
  let activeReceipt = null;
  let candidateGroups = { ready: [], blocked: [], pending: [] };
  let candidateFilter = 'ready';
  let batchFilter = 'open';
  let sequenceRevision = 0;
  const selected = new Set();
  const selectedModes = new Map();
  let searchTimer = null;
  let detailLoadVersion = 0;

  function el(id) { return deps.el(id); }
  function escape(value) { return deps.escapeHtml(value == null ? '' : value); }
  function capability(key) { return !deps.state || deps.state.capabilities?.has(key); }
  function root() { return document.getElementById('portal-screen'); }
  function screen() { return root()?.dataset.screen || ''; }
  function active() { return ['payments', 'payment_approvals'].includes(screen()); }
  function approvalMode() { return screen() === 'payment_approvals'; }
  function detailBatchId() { return root()?.dataset.paymentBatchId || ''; }
  function inboxUrl() { return approvalMode() ? '/portal/s/approvals/payments/' : '/portal/s/payments/'; }
  function detailUrl(id) { return `${inboxUrl()}${encodeURIComponent(id)}/`; }
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

  function setBatchTabCount(filter, value) {
    const badge = document.querySelector(`[data-payment-batch-count="${filter}"]`);
    if (!badge) return;
    const count = Number(value || 0);
    badge.textContent = String(count);
    badge.closest('button')?.setAttribute('aria-label', `${badge.closest('button')?.querySelector('span:first-child')?.textContent || 'Payment batches'}: ${count}`);
  }

  function renderBatchTabCounts() {
    const count = key => batches.filter(item => item.status === key).length;
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
    return `<a class="payment-batch-card" data-payment-batch="${escape(batch.id)}" href="${escape(detailUrl(batch.id))}">
      <span class="payment-batch-card-head"><strong>${number}</strong><span class="badge ${statusClass(batch.status)}">${escape(batch.status_label)}</span></span>
      <span class="payment-batch-card-mode">${escape(batch.payment_mode_summary)}</span>
      <span class="payment-batch-card-stats"><b>${escape(counts.total || 0)} cases</b><b>${escape(money(batch.total_amount))}</b><small>${escape(counts.approved || 0)} approved · ${escape(counts.returned || 0)} returned · ${escape(counts.pending || 0)} awaiting</small></span>
    </a>`;
  }

  function renderBatches() {
    normalizeBatchFilter();
    renderBatchTabCounts();
    const target = el('payments-batches');
    if (!target) return;
    document.querySelectorAll('[data-payment-batch-filter]').forEach(button => button.classList.toggle('active', button.dataset.paymentBatchFilter === batchFilter));
    const visible = batches.filter(item => {
      if (approvalMode()) return item.status === batchFilter;
      return batchFilter === 'all' || (batchFilter === 'open' ? !['completed', 'cancelled'].includes(item.status) : item.status === batchFilter);
    });
    target.innerHTML = visible.length
      ? visible.map(batchCard).join('')
      : `<div class="empty-state"><div class="es-title">${approvalMode() ? 'No payment approvals waiting' : 'No payment batches'}</div><div class="es-sub">${approvalMode() ? 'Submitted batches appear here for the authorised approval role.' : 'Create a batch when invoice-matched cases are ready.'}</div></div>`;
  }

  async function load(options) {
    if (!active()) return;
    normalizeBatchFilter();
    const routeBatchId = detailBatchId();
    if (routeBatchId) return openBatch(routeBatchId, options);
    const target = el('payments-batches');
    if (target && !options?.quiet) target.innerHTML = '<div class="empty-state"><div class="spinner-inline"></div></div>';
    try {
      const response = await deps.apiFetch('/payments/batches/');
      if (!response.ok || !response.data?.ok) throw new Error(response.data?.error || 'Could not load payment batches.');
      batches = response.data.batches || [];
      if (el('payments-batches')) renderBatches();
      if (!approvalMode()) await loadReceiptBatches({quiet: options?.quiet});
    } catch (error) {
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
      return receipt.status !== 'payment_created' || receipt.payment_batch_id;
    });
    if (!visible.length) {
      target.innerHTML = '<div class="empty-state compact"><div class="es-title">No invoice deliveries waiting</div><div class="es-sub">Receive an HB invoice delivery to start payment preparation.</div></div>';
      return;
    }
    target.innerHTML = visible.map(function (receipt) {
      const matched = receiptCount(receipt, 'matched');
      const held = receiptCount(receipt, 'name_change') + receiptCount(receipt, 'review') + receiptCount(receipt, 'parse_failed');
      const action = receipt.payment_batch_id
        ? `<button type="button" class="btn btn-secondary payment-open-receipt-batch" data-payment-receipt-batch="${escape(receipt.payment_batch_id)}">Open payment</button>`
        : `<button type="button" class="btn btn-secondary payment-open-receipt" data-payment-receipt="${escape(receipt.id)}">Review delivery</button>`;
      return `<article class="payment-receipt-row"><div><strong>${escape(receipt.status_label || 'Invoice delivery')}</strong><small>${escape(matched)} matched${held ? ` · ${escape(held)} held` : ''}</small></div><div class="payment-receipt-row-action">${held ? '<span class="badge badge-orange">Held</span>' : '<span class="badge badge-green">Ready</span>'}${action}</div></article>`;
    }).join('');
  }

  async function loadReceiptBatches(options) {
    const target = el('payments-receipts-list');
    if (target && !options?.quiet) target.innerHTML = '<div class="empty-state compact"><div class="spinner-inline"></div></div>';
    try {
      const response = await deps.apiFetch('/invoice-receipts/');
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
    const payable = items.filter(function (item) { return item.status === 'matched' && item.farmer_id; });
    const held = items.filter(function (item) { return item.status !== 'matched'; });
    if (title) title.textContent = activeReceipt.payment_batch_id ? 'Payment created from this delivery' : 'Prepare payment from invoice delivery';
    if (copy) copy.textContent = activeReceipt.payment_batch_id
      ? 'This delivery already has a governed payment batch.'
      : 'Matched invoices default to Loan - Jawabu. Switch only a Cash exception. Held invoices are not included.';
    target.innerHTML = [
      ...payable.map(function (item) {
        const label = item.applicant_name || item.invoice_holder_name || item.invoice_no || 'Matched invoice';
        return `<div class="payment-receipt-dialog-row"><span><strong>${escape(label)}</strong><small>${escape(item.invoice_no || 'Invoice')} · Loan - Jawabu</small></span><button type="button" class="payment-receipt-cash-toggle" data-payment-receipt-dialog-cash="${escape(item.farmer_id)}" aria-pressed="false" aria-label="Switch ${escape(label)} to Cash" title="Switch this invoice to Cash"><i data-lucide="landmark" aria-hidden="true"></i><span>Loan</span></button></div>`;
      }),
      ...held.map(function (item) {
        return `<div class="payment-receipt-dialog-row held"><span><strong>${escape(item.invoice_no || item.source_filename || 'Invoice')}</strong><small>${escape(item.reason || item.status_label || 'Needs review')}</small></span><span class="badge badge-orange">${escape(item.status_label || 'Held')}</span></div>`;
      }),
    ].join('') || '<div class="empty-state compact"><div class="es-title">No invoices in this delivery</div></div>';
    if (submit) submit.hidden = Boolean(activeReceipt.payment_batch_id) || !payable.length;
    if (dialog.showModal && !dialog.open) dialog.showModal();
    window.lucide?.createIcons?.();
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
    (activeReceipt.items || []).filter(function (item) { return item.status === 'matched' && item.farmer_id; }).forEach(function (item) {
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
      setDetailFeedback('');
      showDetail();
      if (!approvalMode() && !activeBatch.receipt_batch_id && capability('portal.payment.prepare') && ['draft', 'in_review', 'review_complete', 'awaiting_scan'].includes(activeBatch.status)) await loadCandidates(options);
    } catch (error) {
      const message = error.message || 'Could not open payment batch.';
      setDetailFeedback(message, {error: true, retry: true});
      deps.showToast(message, 'error');
    }
  }

  function caseDetails(item, {editableMode = false} = {}) {
    const cashSelected = item.payment_mode === 'CASH';
    const paymentMode = editableMode
      ? `<button type="button" class="payment-candidate-cash-toggle${cashSelected ? ' is-cash' : ''}" data-payment-case-cash="${escape(item.farmer_id)}" aria-pressed="${cashSelected}" aria-label="${cashSelected ? 'Cash selected. Switch back to Loan - Jawabu' : 'Switch this case to Cash'}" title="${cashSelected ? 'Cash selected. Switch back to Loan - Jawabu' : 'Switch this case to Cash'}"><i data-lucide="${cashSelected ? 'banknote' : 'landmark'}" aria-hidden="true"></i><span class="sr-only">${cashSelected ? 'Cash' : 'Loan - Jawabu'}</span></button>`
      : `<span class="payment-case-mode-readonly">${escape(item.payment_mode_label || 'Not recorded')}</span>`;
    const value = (itemValue, fallback = 'Not recorded') => escape(itemValue || fallback);
    return `<div class="payment-case-identifiers"><span>${value(item.case_reference, 'Case reference unavailable')}</span><span>ID ${value(item.national_id)}</span><span>${value(item.primary_phone, 'Phone not recorded')}</span></div>
      <dl class="payment-case-details">
        <div><dt>Branch</dt><dd>${value(item.branch)}</dd></div>
        <div><dt>Loan officer</dt><dd>${value(item.loan_officer, 'Unassigned')}</dd></div>
        <div><dt>Invoice / order</dt><dd>${value(item.invoice_number)} / ${value(item.order_number)}</dd></div>
        <div><dt>Amount</dt><dd>${escape(money(item.amount))}</dd></div>
        <div><dt>Repayment</dt><dd>${value(item.preferred_repayment_date, 'Missing')}</dd></div>
        <div class="payment-case-mode"><dt>Payment</dt><dd>${paymentMode}</dd></div>
      </dl>`;
  }

  function caseRow(item, {compact = false} = {}) {
    const canReview = approvalMode() && item.decision === 'pending' && capability('portal.payment.review') && ['in_review', 'review_complete'].includes(activeBatch.status);
    const canRemove = !approvalMode() && capability('portal.payment.prepare') && !['completed', 'cancelled'].includes(activeBatch.status);
    const warning = item.changed_since_review ? '<span class="payment-case-warning">Payment details changed</span>' : '';
    const badge = `<span class="badge ${item.decision === 'approved' ? 'badge-green' : item.decision === 'returned' ? 'badge-orange' : 'badge-blue'}">${escape(item.decision === 'pending' ? 'Awaiting review' : item.decision)}</span>`;
    const customerName = escape(item.customer_name || 'Unnamed customer');
    const caseUrl = `/portal/cases/${escape(item.farmer_id)}/?from=${approvalMode() ? 'payment_approvals' : 'payments'}`;
    const history = `<div class="payment-case-title"><strong>${customerName}</strong>${badge}</div><button type="button" class="payment-case-open" data-case-url="${caseUrl}" aria-label="View case details for ${customerName}"><span>View case</span><i data-lucide="chevron-right" aria-hidden="true"></i></button>`;
    if (compact) {
      return `<article class="payment-case-row payment-review-approved" data-payment-case="${escape(item.farmer_id)}">
        <div class="payment-case-heading">${history}</div>
        ${caseDetails(item)}
      </article>`;
    }
    return `<article class="payment-current-case payment-review-${escape(item.decision)}${item.changed_since_review ? ' changed' : ''}" data-payment-case="${escape(item.farmer_id)}">
      <div class="payment-case-heading">${history}</div>
      ${caseDetails(item, {editableMode: canRemove})}${warning}
      ${canReview ? `<textarea class="payment-review-comment" rows="2" placeholder="Approval comment">${escape(item.comment || '')}</textarea><div class="payment-case-actions"><button type="button" class="btn btn-secondary payment-return">Return</button><button type="button" class="btn btn-primary payment-approve">Approve</button></div>` : item.comment ? `<p class="payment-review-note">${escape(item.comment)}</p>` : ''}
      ${canRemove ? '<button type="button" class="payment-remove-case">Remove</button>' : ''}
    </article>`;
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
    required.progress.innerHTML = `<span><strong>${escape(counts.total || 0)}</strong><small>Cases</small></span><span><strong>${escape(counts.approved || 0)}</strong><small>Approved</small></span><span><strong>${escape(counts.returned || 0)}</strong><small>Returned</small></span><span><strong>${escape(counts.pending || 0)}</strong><small>Awaiting</small></span>`;
    required.progress.hidden = emptyDraft;
    const cases = activeBatch.cases || [];
    const approvedCases = cases.filter(item => item.decision === 'approved');
    const actionableCases = cases.filter(item => item.decision !== 'approved');
    const currentHeading = el('payments-current-heading');
    if (currentHeading) currentHeading.hidden = actionableCases.length === 0;
    required.cases.innerHTML = cases.length ? [
      actionableCases.length ? actionableCases.map(caseRow).join('') : '',
      approvedCases.length ? `<details class="payment-approved-cases"><summary><span>Approved</span><b>${escape(approvedCases.length)}</b></summary><div class="payment-approved-case-list">${approvedCases.map(item => caseRow(item, {compact: true})).join('')}</div></details>` : '',
    ].join('') : '<div class="empty-state compact"><div class="es-title">No cases added</div></div>';
    if (el('payments-current-section')) el('payments-current-section').hidden = emptyDraft;
    const heldItems = activeBatch.held_items || [];
    const heldTarget = el('payments-held-items');
    const heldSection = el('payments-held-section');
    if (heldTarget) {
      heldTarget.innerHTML = heldItems.map(function (item) {
        const add = item.can_add_to_payment && !approvalMode() && capability('portal.payment.prepare') && !['completed', 'cancelled'].includes(activeBatch.status)
          ? `<div class="payment-receipt-add"><button type="button" class="payment-receipt-cash-toggle" data-payment-receipt-cash="${escape(item.farmer_id)}" aria-pressed="false" aria-label="Switch ${escape(item.applicant_name || item.invoice_no || 'invoice')} to Cash" title="Switch this invoice to Cash"><i data-lucide="landmark" aria-hidden="true"></i><span>Loan</span></button><button type="button" class="btn btn-secondary payment-add-receipt-item" data-payment-receipt-farmer="${escape(item.farmer_id)}">Add to payment</button></div>`
          : '';
        const label = item.can_add_to_payment ? 'Corrected - ready to add' : (item.status_label || 'Held');
        return `<article class="payment-current-case payment-held-item${item.can_add_to_payment ? ' payment-receipt-ready' : ''}"><div class="payment-case-heading"><strong>${escape(item.invoice_no || 'Unparsed invoice')}</strong><span class="badge ${item.can_add_to_payment ? 'badge-green' : 'badge-orange'}">${escape(label)}</span></div><div class="payment-case-values"><span>Invoice: ${escape(item.invoice_holder_name || 'Unknown holder')}</span><span>Applicant: ${escape(item.applicant_name || 'Not matched')}</span></div>${item.reason ? `<p class="payment-review-note">${escape(item.reason)}</p>` : ''}${add}</article>`;
      }).join('');
    }
    if (heldSection) heldSection.hidden = !heldItems.length;
    const activity = activeBatch.activity || [];
    required.activity.innerHTML = activity.length ? activity.map(item => `<div><strong>${escape(activityLabel(item.action))}</strong><small>${escape(item.actor)} &middot; ${escape(formatDateTime(item.created_at))}</small></div>`).join('') : '<small>No batch changes recorded.</small>';
    const activityPanel = required.activity.closest('.payment-activity');
    if (activityPanel) activityPanel.hidden = emptyDraft;
    const addPanel = el('payments-add-panel');
    if (addPanel) addPanel.hidden = approvalMode() || Boolean(activeBatch.receipt_batch_id) || !capability('portal.payment.prepare') || ['completed', 'cancelled'].includes(activeBatch.status);
    renderPrimaryAction();
    window.lucide?.createIcons?.();
  }

  function renderPrimaryAction() {
    const target = el('payments-primary-action');
    if (!target || !activeBatch) return;
    if (activeBatch.status === 'draft' && capability('portal.payment.prepare') && Number(activeBatch.counts?.total || 0) > 0) {
      target.innerHTML = '<button type="button" class="btn btn-primary" id="payments-submit-review">Submit for payment approval</button>';
    } else if (activeBatch.status === 'in_review') {
      target.innerHTML = `<div class="payment-state-note"><strong>${activeBatch.counts.approved || 0} of ${activeBatch.counts.total || 0} reviewed</strong><small>${approvalMode() ? 'Review each case above.' : 'This batch is with the payment approver.'}</small></div>`;
    } else if (activeBatch.status === 'review_complete' && approvalMode() && capability('portal.payment.review')) {
      target.innerHTML = '<button type="button" class="btn btn-primary" id="payments-generate">Confirm and generate workbook</button>';
    } else if (activeBatch.status === 'review_complete') {
      target.innerHTML = '<div class="payment-state-note"><strong>Approval complete</strong><small>The authorised approver will generate the workbook.</small></div>';
    } else if (activeBatch.status === 'awaiting_scan') {
      const open = activeBatch.workbook_download_url ? '<button type="button" class="btn btn-secondary" id="payments-open-workbook"><i data-lucide="download"></i> Download workbook</button>' : '';
      const upload = capability('portal.documents.sign') ? '<label class="payment-scan-picker"><input type="file" id="payments-scan-file" accept="application/pdf,image/jpeg,image/png"><span id="payments-scan-label">Select signed scan</span></label><button type="button" class="btn btn-primary" id="payments-upload-scan">Upload signed copy</button>' : '<p class="payment-state-note">Waiting for an authorised user to upload the signed copy.</p>';
      target.innerHTML = open + upload;
    } else if (activeBatch.status === 'completed') {
      const signed = activeBatch.signed_scan_url
        ? '<button type="button" class="btn btn-secondary" id="payments-open-signed-copy">Open signed copy</button>'
        : '';
      target.innerHTML = `<div class="payment-complete"><strong>Payment completed</strong><small>The signed batch is locked.</small></div>${signed}`;
    } else target.innerHTML = '';
    if (!approvalMode() && capability('portal.payment.prepare') && Number(activeBatch.counts?.total || 0) > 0 && !['completed', 'cancelled'].includes(activeBatch.status)) {
      target.insertAdjacentHTML('beforeend', '<button type="button" class="payment-cancel-link" id="payments-cancel">Cancel</button>');
    }
    target.hidden = target.childElementCount === 0;
    target.classList.toggle('payment-primary-action-quiet', Boolean(target.querySelector('.payment-state-note')));
  }

  function candidateCard(item, kind) {
    const row = item.row || {};
    const id = String(item.farmer_id || '');
    const current = new Set((activeBatch?.cases || []).map(entry => String(entry.farmer_id)));
    if (current.has(id)) return '';
    const blocked = kind !== 'ready';
    const mode = selectedModes.get(id) || 'LOAN-JAWABU';
    const reasons = kind === 'pending' ? `Already in Payment #${item.payment_review_payment_number || '-'}` : (item.missing || []).join(', ');
    const advisory = kind === 'ready' ? (item.warnings || []).join(', ') : '';
    return `<article class="payment-candidate${kind === 'ready' ? ' has-mode-toggle' : ''}${blocked ? ' blocked' : ''}${selected.has(id) ? ' selected' : ''}">
      <span class="payment-candidate-main">${kind === 'ready' ? `<input class="payment-candidate-checkbox" type="checkbox" value="${escape(id)}" aria-label="Select ${escape(item.customer_name || row.name || 'case')}" ${selected.has(id) ? 'checked' : ''}>` : '<i data-lucide="circle-alert"></i>'}<span><strong>${escape(item.customer_name || row.name || 'Unnamed customer')}</strong><small>${escape([item.national_id, item.invoice_number].filter(Boolean).join(' · '))}</small></span></span>
      <span class="payment-candidate-meta"><span>Amount<strong>${escape(money(row.hb_invoice_amount))}</strong></span><span>Repayment<strong>${escape(row.repayment_dates || 'Missing')}</strong></span></span>
      ${kind === 'ready' ? `<button type="button" class="payment-candidate-cash-toggle${mode === 'CASH' ? ' is-cash' : ''}" data-payment-candidate-cash="${escape(id)}" aria-pressed="${mode === 'CASH'}" aria-label="${mode === 'CASH' ? 'Cash selected. Switch back to Loan - Jawabu' : 'Switch this case to Cash'}" title="${mode === 'CASH' ? 'Cash selected. Switch back to Loan - Jawabu' : 'Switch this case to Cash'}"><i data-lucide="${mode === 'CASH' ? 'banknote' : 'landmark'}" aria-hidden="true"></i><span class="sr-only">${mode === 'CASH' ? 'Cash' : 'Loan - Jawabu'}</span></button>` : ''}
      ${blocked ? `<span class="payment-candidate-warning">${escape(reasons || 'Payment details need attention')}</span>` : ''}
      ${advisory ? `<span class="payment-candidate-warning payment-candidate-advisory">${escape(advisory)}</span>` : ''}
    </article>`;
  }

  function renderCandidates() {
    document.querySelectorAll('[data-payment-filter]').forEach(button => {
      const isActive = button.dataset.paymentFilter === candidateFilter;
      button.classList.toggle('active', isActive);
      button.setAttribute('aria-pressed', String(isActive));
    });
    document.querySelectorAll('[data-payment-filter-count]').forEach(count => {
      count.textContent = String((candidateGroups[count.dataset.paymentFilterCount] || []).length);
    });
    const visible = candidateGroups[candidateFilter] || [];
    const html = visible.map(item => candidateCard(item, candidateFilter)).filter(Boolean);
    const resultCount = el('payments-result-count');
    if (resultCount) resultCount.textContent = `${html.length} found`;
    el('payments-list').innerHTML = html.length ? html.join('') : '<div class="empty-state compact"><div class="es-title">No matching cases</div></div>';
    el('payments-selected-count').textContent = `${selected.size} selected`;
    el('payments-clear-selection').hidden = selected.size === 0;
    el('payments-add-selected').disabled = selected.size === 0;
    window.lucide?.createIcons?.();
  }

  async function loadCandidates(options) {
    if (!activeBatch) return;
    const list = el('payments-list');
    if (list && !options?.quiet) list.innerHTML = '<div class="empty-state compact"><div class="spinner-inline"></div></div>';
    try {
      const query = String(el('payments-search')?.value || '').trim();
      const response = await deps.apiFetch('/payments/candidates/?search=' + encodeURIComponent(query));
      if (!response.ok || !response.data?.ok) throw new Error(response.data?.error || 'Could not load payment cases.');
      candidateGroups = {ready: response.data.ready || [], blocked: response.data.blocked || [], pending: response.data.pending_review || []};
      renderCandidates();
    } catch (error) {
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
      activeBatch = response.data.batch;
      renderDetail();
      if (!approvalMode() && !activeBatch.receipt_batch_id) await loadCandidates({quiet: true});
      const list = await deps.apiFetch('/payments/batches/');
      if (list.ok && list.data?.ok) { batches = list.data.batches || []; renderBatchTabCounts(); }
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
      return Promise.resolve(window.confirm(`${copy}\n\nThe number remains used even if this batch is later cancelled.`));
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

  async function addSelected(button) {
    if (!selected.size) return;
    const paymentModes = Object.fromEntries([...selected].map(id => [id, selectedModes.get(id) || 'LOAN-JAWABU']));
    if (await mutate(`/payments/batches/${activeBatch.id}/cases/`, {farmer_ids: [...selected], payment_modes: paymentModes}, button, 'Adding...')) {
      selected.clear(); selectedModes.clear(); renderCandidates(); deps.showToast('Cases added to payment batch.', 'success');
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
      ? '<i data-lucide="banknote" aria-hidden="true"></i><span>Cash</span>'
      : '<i data-lucide="landmark" aria-hidden="true"></i><span>Loan</span>';
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
    const reason = window.prompt('Why are you cancelling this payment batch?', '');
    if (!reason?.trim()) return;
    if (await mutate(`/payments/batches/${activeBatch.id}/cancel/`, {reason: reason.trim()}, button, 'Cancelling...')) {
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
    document.addEventListener('change', event => {
      const checkbox = event.target.closest('.payment-candidate-checkbox');
      if (checkbox) { checkbox.checked ? selected.add(checkbox.value) : selected.delete(checkbox.value); renderCandidates(); return; }
      if (event.target.id === 'payments-scan-file') {
        const file = event.target.files?.[0]; el('payments-scan-label').textContent = file ? file.name : 'Select signed scan';
      }
    });
    document.addEventListener('input', event => {
      if (event.target.id !== 'payments-search') return;
      clearTimeout(searchTimer); searchTimer = setTimeout(() => loadCandidates(), 300);
    });
    document.addEventListener('click', event => {
      const target = event.target;
      const batch = target.closest('[data-payment-batch]');
      if (batch) {
        event.preventDefault();
        const url = batch.getAttribute('href') || detailUrl(batch.dataset.paymentBatch);
        return navigatePayment(url);
      }
      const batchFilterButton = target.closest('[data-payment-batch-filter]');
      if (batchFilterButton) { batchFilter = batchFilterButton.dataset.paymentBatchFilter; return renderBatches(); }
      if (target.closest('#payments-refresh')) return load();
      if (target.closest('#payments-receive-invoices')) return navigatePayment('/portal/s/invoices/upload/');
      if (target.closest('.payment-open-receipt')) return openReceipt(target.closest('.payment-open-receipt').dataset.paymentReceipt);
      if (target.closest('.payment-open-receipt-batch')) return navigatePayment(detailUrl(target.closest('.payment-open-receipt-batch').dataset.paymentReceiptBatch));
      if (target.closest('#payment-receipt-create')) return createPaymentFromReceipt(target.closest('#payment-receipt-create'));
      if (target.closest('#payments-sequence-save')) return saveSequence(target.closest('#payments-sequence-save'));
      if (target.closest('#payments-detail-back')) return closeDetail();
      if (target.closest('#payments-detail-retry')) return openBatch(detailBatchId(), {});
      const filter = target.closest('[data-payment-filter]');
      if (filter) { candidateFilter = filter.dataset.paymentFilter; return renderCandidates(); }
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

  function init(initialDeps) { deps = initialDeps; bind(); }
  window.PortalMiniAppPayments = {init, load, loadSequence};
})();
