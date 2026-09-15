(function () {
  'use strict';

  let deps = null;
  let activeBatch = null;
  let batches = [];
  let candidateGroups = { ready: [], blocked: [], pending: [] };
  let candidateFilter = 'ready';
  let batchFilter = 'open';
  let sequenceRevision = 0;
  const selected = new Set();
  const selectedModes = new Map();
  let searchTimer = null;

  function el(id) { return deps.el(id); }
  function escape(value) { return deps.escapeHtml(value == null ? '' : value); }
  function capability(key) { return !deps.state || deps.state.capabilities?.has(key); }
  function active() { return document.getElementById('portal-screen')?.dataset.screen === 'payments'; }
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

  function renderSummary() {
    const target = el('payments-summary');
    if (!target) return;
    const count = key => batches.filter(item => item.status === key).length;
    target.innerHTML = [
      ['Draft', count('draft')],
      ['In review', count('in_review') + count('review_complete')],
      ['Awaiting scan', count('awaiting_scan')],
      ['Completed', count('completed')],
    ].map(([label, value]) => `<span><strong>${value}</strong><small>${label}</small></span>`).join('');
  }

  function batchCard(batch) {
    const counts = batch.counts || {};
    const number = batch.payment_number ? `Payment #${escape(batch.payment_number)}` : 'Draft payment';
    return `<button type="button" class="payment-batch-card" data-payment-batch="${escape(batch.id)}">
      <span class="payment-batch-card-head"><strong>${number}</strong><span class="badge ${statusClass(batch.status)}">${escape(batch.status_label)}</span></span>
      <span class="payment-batch-card-mode">${escape(batch.payment_mode_summary)}</span>
      <span class="payment-batch-card-stats"><b>${escape(counts.total || 0)} cases</b><b>${escape(money(batch.total_amount))}</b><small>${escape(counts.approved || 0)} approved · ${escape(counts.returned || 0)} returned · ${escape(counts.pending || 0)} awaiting</small></span>
    </button>`;
  }

  function renderBatches() {
    renderSummary();
    const target = el('payments-batches');
    if (!target) return;
    document.querySelectorAll('[data-payment-batch-filter]').forEach(button => button.classList.toggle('active', button.dataset.paymentBatchFilter === batchFilter));
    const visible = batches.filter(item => batchFilter === 'all' || (batchFilter === 'open' ? !['completed', 'cancelled'].includes(item.status) : item.status === batchFilter));
    target.innerHTML = visible.length
      ? visible.map(batchCard).join('')
      : '<div class="empty-state"><div class="es-title">No payment batches</div><div class="es-sub">Create a batch when invoice-matched cases are ready.</div></div>';
  }

  async function load(options) {
    if (!active()) return;
    const target = el('payments-batches');
    if (target && !options?.quiet) target.innerHTML = '<div class="empty-state"><div class="spinner-inline"></div></div>';
    try {
      const response = await deps.apiFetch('/payments/batches/');
      if (!response.ok || !response.data?.ok) throw new Error(response.data?.error || 'Could not load payment batches.');
      batches = response.data.batches || [];
      renderBatches();
      if (capability('portal.payment.sequence.manage')) loadSequence();
      if (activeBatch) await openBatch(activeBatch.id, {quiet: true});
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
      await load({quiet: true});
      showDetail();
      deps.showToast('Payment batch created.', 'success');
    } catch (error) {
      deps.showToast(error.message || 'Could not create payment batch.', 'error');
    } finally { deps.setButtonLoading(button, false); }
  }

  function showDetail() {
    el('payments-detail').hidden = false;
    el('payments-batches').hidden = true;
    el('payments-summary').hidden = true;
    document.querySelector('.payment-batch-filters')?.setAttribute('hidden', '');
    document.querySelector('.payment-new-row')?.setAttribute('hidden', '');
    renderDetail();
  }

  function closeDetail() {
    activeBatch = null;
    selected.clear();
    selectedModes.clear();
    el('payments-detail').hidden = true;
    el('payments-batches').hidden = false;
    el('payments-summary').hidden = false;
    document.querySelector('.payment-batch-filters')?.removeAttribute('hidden');
    document.querySelector('.payment-new-row')?.removeAttribute('hidden');
    renderBatches();
  }

  async function openBatch(id, options) {
    try {
      const response = await deps.apiFetch(`/payments/batches/${encodeURIComponent(id)}/`);
      if (!response.ok || !response.data?.ok) throw new Error(response.data?.error || 'Could not open payment batch.');
      activeBatch = response.data.batch;
      showDetail();
      if (capability('portal.payment.prepare') && ['draft', 'in_review', 'review_complete', 'awaiting_scan'].includes(activeBatch.status)) await loadCandidates(options);
    } catch (error) { deps.showToast(error.message || 'Could not open payment batch.', 'error'); }
  }

  function caseRow(item) {
    const canReview = capability('portal.payment.review') && ['in_review', 'review_complete'].includes(activeBatch.status);
    const canRemove = capability('portal.payment.prepare') && !['completed', 'cancelled'].includes(activeBatch.status);
    const warning = item.changed_since_review ? '<span class="payment-case-warning">Payment details changed</span>' : '';
    return `<article class="payment-current-case payment-review-${escape(item.decision)}${item.changed_since_review ? ' changed' : ''}" data-payment-case="${escape(item.farmer_id)}">
      <div class="payment-case-heading"><button type="button" class="payment-case-history" data-case-url="/portal/cases/${escape(item.farmer_id)}/"><strong>${escape(item.customer_name || 'Unnamed customer')}</strong><small>${escape(item.invoice_number || 'No invoice')} · ${escape(item.order_number || 'No order')}</small></button><span class="badge ${item.decision === 'approved' ? 'badge-green' : item.decision === 'returned' ? 'badge-orange' : 'badge-blue'}">${escape(item.decision === 'pending' ? 'Awaiting review' : item.decision)}</span></div>
      <div class="payment-case-values"><span>${escape(money(item.amount))}</span><span>Repayment: ${escape(item.preferred_repayment_date || 'Missing')}</span></div>
      ${canRemove ? `<label class="payment-case-mode"><span>Payment mode</span><select data-payment-case-mode="${escape(item.farmer_id)}"><option value="LOAN-JAWABU" ${item.payment_mode === 'LOAN-JAWABU' ? 'selected' : ''}>Loan - Jawabu</option><option value="CASH" ${item.payment_mode === 'CASH' ? 'selected' : ''}>Cash</option></select></label>` : `<span class="payment-case-mode-readonly">${escape(item.payment_mode_label)}</span>`}${warning}
      ${canReview ? `<textarea class="payment-review-comment" rows="2" placeholder="Head of Rural comment">${escape(item.comment || '')}</textarea><div class="payment-case-actions"><button type="button" class="btn btn-secondary payment-return">Return</button><button type="button" class="btn btn-primary payment-approve">Approve</button></div>` : item.comment ? `<p class="payment-review-note">${escape(item.comment)}</p>` : ''}
      ${canRemove ? '<button type="button" class="payment-remove-case">Remove</button>' : ''}
    </article>`;
  }

  function activityLabel(action) {
    return ({created: 'Batch created', cases_added: 'Cases added', case_removed: 'Case removed', submitted_for_review: 'Sent for review', case_reviewed: 'Case reviewed', reviews_invalidated: 'Review reopened after changes', case_mode_changed: 'Case payment mode changed', workbook_generated: 'Workbook generated', signed_scan_accepted: 'Signed scan accepted', cancelled: 'Batch cancelled'})[action] || String(action || '').replaceAll('_', ' ');
  }

  function formatDateTime(value) {
    if (!value) return '';
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? value : date.toLocaleString('en-KE', {day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit'});
  }

  function renderDetail() {
    if (!activeBatch) return;
    const counts = activeBatch.counts || {};
    el('payments-detail-title').textContent = activeBatch.payment_number ? `Payment #${activeBatch.payment_number}` : 'Draft payment';
    el('payments-detail-meta').textContent = `${activeBatch.payment_mode_summary} · ${activeBatch.status_label}`;
    el('payments-progress').innerHTML = `<span><strong>${escape(counts.total || 0)}</strong><small>Cases</small></span><span><strong>${escape(counts.approved || 0)}</strong><small>Approved</small></span><span><strong>${escape(counts.returned || 0)}</strong><small>Returned</small></span><span><strong>${escape(counts.pending || 0)}</strong><small>Awaiting</small></span><span class="payment-progress-total"><strong>${escape(money(activeBatch.total_amount))}</strong><small>Total</small></span>`;
    const cases = activeBatch.cases || [];
    el('payments-current-cases').innerHTML = cases.length ? cases.map(caseRow).join('') : '<div class="empty-state compact"><div class="es-title">No cases added</div></div>';
    const activity = activeBatch.activity || [];
    el('payments-activity').innerHTML = activity.length ? activity.map(item => `<div><strong>${escape(activityLabel(item.action))}</strong><small>${escape(item.actor)} &middot; ${escape(formatDateTime(item.created_at))}</small></div>`).join('') : '<small>No batch changes recorded.</small>';
    const addPanel = el('payments-add-panel');
    if (addPanel) addPanel.hidden = !capability('portal.payment.prepare') || ['completed', 'cancelled'].includes(activeBatch.status);
    renderPrimaryAction();
    window.lucide?.createIcons?.();
  }

  function renderPrimaryAction() {
    const target = el('payments-primary-action');
    if (!target || !activeBatch) return;
    if (activeBatch.status === 'draft' && capability('portal.payment.prepare')) {
      target.innerHTML = '<button type="button" class="btn btn-primary" id="payments-submit-review">Submit for Head of Rural review</button>';
    } else if (activeBatch.status === 'in_review') {
      target.innerHTML = `<div class="payment-state-note"><strong>${activeBatch.counts.approved || 0} of ${activeBatch.counts.total || 0} reviewed</strong><small>Head of Rural reviews each case here.</small></div>`;
    } else if (activeBatch.status === 'review_complete' && capability('portal.payment.review')) {
      target.innerHTML = '<button type="button" class="btn btn-primary" id="payments-generate">Confirm and generate workbook</button>';
    } else if (activeBatch.status === 'awaiting_scan') {
      const open = activeBatch.current_document_url ? '<button type="button" class="btn btn-secondary" id="payments-open-workbook">Open workbook</button>' : '';
      const upload = capability('portal.documents.sign') ? '<label class="payment-scan-picker"><input type="file" id="payments-scan-file" accept="application/pdf,image/jpeg,image/png"><span id="payments-scan-label">Select signed scan</span></label><button type="button" class="btn btn-primary" id="payments-upload-scan">Upload signed copy</button>' : '<p class="payment-state-note">Waiting for an authorised user to upload the signed copy.</p>';
      target.innerHTML = open + upload;
    } else if (activeBatch.status === 'completed') {
      const signed = activeBatch.signed_scan_url
        ? '<button type="button" class="btn btn-secondary" id="payments-open-signed-copy">Open signed copy</button>'
        : '';
      target.innerHTML = `<div class="payment-complete"><strong>Payment completed</strong><small>The signed batch is locked.</small></div>${signed}`;
    } else target.innerHTML = '';
    if (capability('portal.payment.prepare') && !['completed', 'cancelled'].includes(activeBatch.status)) {
      target.insertAdjacentHTML('beforeend', '<button type="button" class="payment-cancel-link" id="payments-cancel">Cancel</button>');
    }
  }

  function candidateCard(item, kind) {
    const row = item.row || {};
    const id = String(item.farmer_id || '');
    const current = new Set((activeBatch?.cases || []).map(entry => String(entry.farmer_id)));
    if (current.has(id)) return '';
    const blocked = kind !== 'ready';
    const mode = selectedModes.get(id) || '';
    const reasons = kind === 'pending' ? `Already in Payment #${item.payment_review_payment_number || '-'}` : (item.missing || []).join(', ');
    return `<article class="payment-candidate ${blocked ? 'blocked' : ''}${selected.has(id) ? ' selected' : ''}">
      <span class="payment-candidate-main">${kind === 'ready' ? `<input class="payment-candidate-checkbox" type="checkbox" value="${escape(id)}" aria-label="Select ${escape(item.customer_name || row.name || 'case')}" ${selected.has(id) ? 'checked' : ''} ${mode ? '' : 'disabled'}>` : '<i data-lucide="circle-alert"></i>'}<span><strong>${escape(item.customer_name || row.name || 'Unnamed customer')}</strong><small>${escape([item.national_id, item.invoice_number].filter(Boolean).join(' · '))}</small></span></span>
      <span class="payment-candidate-meta"><span>Amount<strong>${escape(money(row.hb_invoice_amount))}</strong></span><span>Repayment<strong>${escape(row.repayment_dates || 'Missing')}</strong></span></span>
      ${kind === 'ready' ? `<select class="payment-candidate-mode" data-payment-candidate-mode="${escape(id)}" aria-label="Payment mode for ${escape(item.customer_name || row.name || 'case')}"><option value="">Choose payment mode</option><option value="LOAN-JAWABU" ${mode === 'LOAN-JAWABU' ? 'selected' : ''}>Loan - Jawabu</option><option value="CASH" ${mode === 'CASH' ? 'selected' : ''}>Cash</option></select>` : ''}
      ${blocked ? `<span class="payment-candidate-warning">${escape(reasons || 'Payment details need attention')}</span>` : ''}
    </article>`;
  }

  function renderCandidates() {
    document.querySelectorAll('[data-payment-filter]').forEach(button => button.classList.toggle('active', button.dataset.paymentFilter === candidateFilter));
    const visible = candidateGroups[candidateFilter] || [];
    const html = visible.map(item => candidateCard(item, candidateFilter)).filter(Boolean);
    el('payments-result-count').textContent = `${html.length} found`;
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
    deps.setButtonLoading(button, true, loadingText || 'Saving...');
    try {
      const response = await request(path, 'POST', {...body, revision: activeBatch.revision});
      if (!response.ok || !response.data?.ok) throw new Error(response.data?.error || 'The payment batch could not be updated.');
      activeBatch = response.data.batch;
      renderDetail();
      await loadCandidates({quiet: true});
      const list = await deps.apiFetch('/payments/batches/');
      if (list.ok && list.data?.ok) { batches = list.data.batches || []; renderSummary(); }
      return true;
    } catch (error) {
      deps.showToast(error.message || 'The payment batch could not be updated.', 'error');
      if (/changed (while|after review)/i.test(String(error.message || ''))) {
        await openBatch(activeBatch.id, {quiet: true});
      }
      return false;
    } finally { deps.setButtonLoading(button, false); }
  }

  async function changeCaseMode(select) {
    const farmerId = select.dataset.paymentCaseMode;
    const prior = activeBatch.cases.find(item => item.farmer_id === farmerId)?.payment_mode;
    select.disabled = true;
    try {
      const response = await request(
        `/payments/batches/${activeBatch.id}/cases/${farmerId}/mode/`, 'POST',
        {payment_mode: select.value, revision: activeBatch.revision}
      );
      if (!response.ok || !response.data?.ok) throw new Error(response.data?.error || 'Could not change this case payment mode.');
      activeBatch = response.data.batch;
      renderDetail();
      deps.showToast('Case payment mode updated.', 'success');
    } catch (error) {
      select.value = prior || '';
      deps.showToast(error.message || 'Could not change this case payment mode.', 'error');
    } finally { select.disabled = false; }
  }

  async function addSelected(button) {
    if (!selected.size) return;
    const paymentModes = Object.fromEntries([...selected].map(id => [id, selectedModes.get(id)]));
    if (await mutate(`/payments/batches/${activeBatch.id}/cases/`, {farmer_ids: [...selected], payment_modes: paymentModes}, button, 'Adding...')) {
      selected.clear(); selectedModes.clear(); renderCandidates(); deps.showToast('Cases added to payment batch.', 'success');
    }
  }

  async function reviewCase(card, decision, button) {
    const comment = String(card.querySelector('.payment-review-comment')?.value || '').trim();
    if (!comment) return deps.showToast('Enter a Head of Rural comment for this case.', 'error');
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
      const candidateMode = event.target.closest('[data-payment-candidate-mode]');
      if (candidateMode) {
        const id = candidateMode.dataset.paymentCandidateMode;
        candidateMode.value ? selectedModes.set(id, candidateMode.value) : selectedModes.delete(id);
        if (!candidateMode.value) selected.delete(id);
        renderCandidates();
        return;
      }
      const caseMode = event.target.closest('[data-payment-case-mode]');
      if (caseMode) { changeCaseMode(caseMode); return; }
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
      if (batch) return openBatch(batch.dataset.paymentBatch);
      const batchFilterButton = target.closest('[data-payment-batch-filter]');
      if (batchFilterButton) { batchFilter = batchFilterButton.dataset.paymentBatchFilter; return renderBatches(); }
      if (target.closest('#payments-refresh')) return load();
      if (target.closest('#payments-new')) return createBatch(target.closest('#payments-new'));
      if (target.closest('#payments-sequence-save')) return saveSequence(target.closest('#payments-sequence-save'));
      if (target.closest('#payments-detail-back')) return closeDetail();
      const filter = target.closest('[data-payment-filter]');
      if (filter) { candidateFilter = filter.dataset.paymentFilter; return renderCandidates(); }
      if (target.closest('#payments-clear-selection')) { selected.clear(); return renderCandidates(); }
      if (target.closest('#payments-add-selected')) return addSelected(target.closest('#payments-add-selected'));
      if (target.closest('#payments-submit-review')) return mutate(`/payments/batches/${activeBatch.id}/submit/`, {}, target.closest('#payments-submit-review'), 'Submitting...');
      if (target.closest('#payments-generate')) return mutate(`/payments/batches/${activeBatch.id}/generate/`, {}, target.closest('#payments-generate'), 'Generating...');
      if (target.closest('#payments-open-workbook')) return deps.openPortalLink(activeBatch.current_document_url);
      if (target.closest('#payments-open-signed-copy')) return deps.openPortalLink(activeBatch.signed_scan_url);
      if (target.closest('#payments-upload-scan')) return uploadScan(target.closest('#payments-upload-scan'));
      if (target.closest('#payments-cancel')) return cancelBatch(target.closest('#payments-cancel'));
      const card = target.closest('[data-payment-case]');
      if (card && target.closest('.payment-approve')) return reviewCase(card, 'approved', target.closest('.payment-approve'));
      if (card && target.closest('.payment-return')) return reviewCase(card, 'returned', target.closest('.payment-return'));
      if (card && target.closest('.payment-remove-case')) return removeCase(card, target.closest('.payment-remove-case'));
      const history = target.closest('.payment-case-history');
      if (history) {
        const url = history.dataset.caseUrl;
        if (window.PortalCaseNavigation?.open?.(url)) return;
        window.location.assign(url);
      }
    });
  }

  function init(initialDeps) { deps = initialDeps; bind(); }
  window.PortalMiniAppPayments = {init, load};
})();
