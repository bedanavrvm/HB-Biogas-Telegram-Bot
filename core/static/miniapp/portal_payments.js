(function () {
  'use strict';

  let deps = null;
  const selected = new Set();
  let readyIds = [];
  let activeWorkbook = null;
  let reviewDocument = null;

  function el(id) { return deps.el(id); }
  function escape(value) { return deps.escapeHtml(value == null ? '' : value); }

  function updateSelection() {
    const count = el('payments-selected-count');
    if (count) count.textContent = `${selected.size} selected`;
    document.querySelectorAll('.payment-candidate-checkbox').forEach(input => {
      input.checked = selected.has(input.value);
    });
  }

  function amount(value) {
    if (value === null || value === undefined || value === '') return '-';
    const number = Number(String(value).replace(/,/g, ''));
    return Number.isFinite(number) ? String(number).replace(/\.0+$/, '') : String(value);
  }

  function candidateCard(item, blocked) {
    const row = item.row || {};
    const disabled = blocked ? 'disabled' : '';
    const missing = (item.missing || []).map(value => String(value).replace(/_/g, ' ')).join(', ');
    return `<article class="payment-candidate ${blocked ? 'blocked' : ''}">
      <label class="payment-candidate-main">
        <input class="payment-candidate-checkbox" type="checkbox" value="${escape(item.farmer_id)}" ${disabled}>
        <span><strong>${escape(item.customer_name || row.name || 'Unnamed customer')}</strong><small>${escape([item.national_id, item.primary_phone].filter(Boolean).join(' | '))}</small></span>
      </label>
      <div class="payment-candidate-meta"><span>Invoice <strong>${escape(item.invoice_number || '-')}</strong></span><span>Order <strong>${escape(row.order_no || '-')}</strong></span><span>Balance due <strong>${escape(amount(row.hb_invoice_amount))}</strong></span><span>Branch <strong>${escape(row.branch || '-')}</strong></span><span>Repayment <strong>${escape([row.repayment_dates, row.tenor ? `${row.tenor} months` : ''].filter(Boolean).join(' / ') || '-')}</strong></span></div>
      ${blocked ? `<div class="payment-candidate-warning">Missing: ${escape(missing || 'required payment data')}</div>` : ''}
    </article>`;
  }

  async function load() {
    const list = el('payments-list');
    if (!list) return;
    list.innerHTML = '<div class="empty-state"><div class="spinner-inline"></div></div>';
    const query = String(el('payments-search')?.value || '').trim();
    const response = await deps.apiFetch('/payments/candidates/?search=' + encodeURIComponent(query));
    if (!response.ok || !response.data?.ok) {
      list.innerHTML = `<div class="batch-warning">${escape(response.data?.error || 'Could not load invoiced cases.')}</div>`;
      return;
    }
    const ready = response.data.ready || [];
    const blocked = response.data.blocked || [];
    readyIds = ready.map(item => item.farmer_id);
    const visible = new Set([...readyIds, ...blocked.map(item => item.farmer_id)]);
    [...selected].forEach(id => { if (!visible.has(id)) selected.delete(id); });
    el('payments-ready-summary').textContent = `${ready.length} ready | ${blocked.length} need attention`;
    list.innerHTML = ready.length || blocked.length
      ? ready.map(item => candidateCard(item, false)).join('') + blocked.map(item => candidateCard(item, true)).join('')
      : '<div class="empty-state"><div class="es-title">No invoice-matched cases</div><div class="es-sub">Confirm invoice matching before building a payment batch.</div></div>';
    updateSelection();
  }

  function payload(final) {
    const paymentNumber = String(el('payments-number')?.value || '').trim().replace(/^#/, '');
    if (!/^\d{1,20}$/.test(paymentNumber)) {
      deps.showToast('Enter a valid payment number using digits only.', 'error');
      return null;
    }
    if (!selected.size) {
      deps.showToast('Select at least one ready invoiced case.', 'error');
      return null;
    }
    return { payment_number: paymentNumber, farmer_ids: [...selected], final };
  }

  async function preview(button) {
    const body = payload(false);
    if (!body) return;
    deps.setButtonLoading(button, true, 'Preparing...');
    try {
      const response = await deps.portalApi.postJson('/payments/selection/', body, deps.tg, {'X-CSRFToken': deps.getCookie('csrftoken') || ''});
      if (!response.ok || !response.data?.ok) throw new Error(response.data?.error || 'Could not prepare payment preview.');
      activeWorkbook = response.data.workbook_preview;
      el('payments-workbook-content').innerHTML = deps.requisitions.renderWorkbookPreview(activeWorkbook);
      el('payments-workbook-preview').hidden = false;
      el('payments-workbook-preview').scrollIntoView({behavior: 'smooth', block: 'start'});
    } catch (error) {
      deps.showToast(error.message || 'Could not prepare payment preview.', 'error');
    } finally {
      deps.setButtonLoading(button, false);
    }
  }

  async function finalize(button) {
    const body = payload(true);
    if (!body || !window.confirm(`Submit Payment #${body.payment_number} for ${body.farmer_ids.length} selected case(s) for Head of Rural review?`)) return;
    deps.setButtonLoading(button, true, 'Submitting...');
    try {
      const response = await deps.portalApi.postJson('/payments/selection/', body, deps.tg, {'X-CSRFToken': deps.getCookie('csrftoken') || ''});
      if (!response.ok || !response.data?.ok) throw new Error(response.data?.error || 'Could not submit payment for review.');
      reviewDocument = response.data.document || null;
      renderReviewPanel(reviewDocument);
      deps.showToast('Payment draft submitted for Head of Rural review.', 'success');
      selected.clear();
      updateSelection();
    } catch (error) {
      deps.showToast(error.message || 'Could not submit payment for review.', 'error');
    } finally {
      deps.setButtonLoading(button, false);
    }
  }

  function renderReviewPanel(document) {
    const panel = el('payments-review-panel');
    const content = el('payments-review-content');
    if (!panel || !content || !document) return;
    const isFinal = document.status === 'final';
    panel.hidden = false;
    content.innerHTML = isFinal
      ? `<div class="batch-warning" style="background:#f0fdf4;border-color:#bbf7d0;color:#166534;">
          Payment #${escape(document.payment_number)} approved and stored as the final payment workbook.
          ${document.drive_url ? '<button type="button" class="btn btn-secondary" id="payments-open-review" style="margin-top:8px;">Open final Excel</button>' : ''}
        </div>`
      : `<div class="batch-warning" style="background:#fff7ed;border-color:#fed7aa;color:#9a3412;">
          Payment #${escape(document.payment_number)} is awaiting Head of Rural approval. Repayment date and tenor are already populated in the review workbook.
          ${document.drive_url ? '<button type="button" class="btn btn-secondary" id="payments-open-review" style="margin-top:8px;">Open review Excel</button>' : ''}
        </div>
        <label style="display:grid;gap:6px;margin-top:10px;">Call Up Comments (COL)
          <textarea id="payments-call-up-comments" rows="3" placeholder="Head of Rural approval comments"></textarea>
        </label>
        <button type="button" class="btn btn-primary" id="payments-approve" data-document-id="${escape(document.id)}" style="margin-top:8px;">Approve and create final payment</button>`;
    panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  async function approve(button) {
    const documentId = button?.dataset.documentId || reviewDocument?.id;
    const comment = String(el('payments-call-up-comments')?.value || '').trim();
    if (!documentId || !comment) {
      deps.showToast('Head of Rural Call Up Comments are required.', 'error');
      return;
    }
    deps.setButtonLoading(button, true, 'Approving...');
    try {
      const response = await deps.portalApi.postJson(
        '/payment-document/' + encodeURIComponent(documentId) + '/approve/',
        { call_up_comments: comment },
        deps.tg,
        { 'X-CSRFToken': deps.getCookie('csrftoken') || '' },
      );
      if (!response.ok || !response.data?.ok) throw new Error(response.data?.error || 'Could not approve payment.');
      reviewDocument = response.data.document;
      renderReviewPanel(reviewDocument);
      deps.showToast('Payment approved and final workbook stored.', 'success');
      if (reviewDocument.drive_url) deps.openPortalLink(reviewDocument.drive_url);
    } catch (error) {
      deps.showToast(error.message || 'Could not approve payment.', 'error');
    } finally {
      deps.setButtonLoading(button, false);
    }
  }

  function bind() {
    if (document.documentElement.dataset.portalPaymentsBound) return;
    document.documentElement.dataset.portalPaymentsBound = 'true';
    document.addEventListener('change', event => {
      const input = event.target.closest('.payment-candidate-checkbox');
      if (!input) return;
      if (input.checked) selected.add(input.value); else selected.delete(input.value);
      updateSelection();
    });
    document.addEventListener('click', event => {
      const target = event.target;
      if (target.closest('#payments-search-button')) load();
      else if (target.closest('#payments-select-ready')) {
        if (readyIds.length && readyIds.every(id => selected.has(id))) readyIds.forEach(id => selected.delete(id));
        else readyIds.forEach(id => selected.add(id));
        updateSelection();
      } else if (target.closest('#payments-preview')) preview(target.closest('#payments-preview'));
      else if (target.closest('#payments-finalize')) finalize(target.closest('#payments-finalize'));
      else if (target.closest('#payments-approve')) approve(target.closest('#payments-approve'));
      else if (target.closest('#payments-open-review') && reviewDocument?.drive_url) deps.openPortalLink(reviewDocument.drive_url);
    });
    document.addEventListener('keydown', event => {
      if (event.key === 'Enter' && event.target.matches('#payments-search')) { event.preventDefault(); load(); }
    });
  }

  function init(initialDeps) { deps = initialDeps; bind(); }
  window.PortalMiniAppPayments = { init, load };
})();
