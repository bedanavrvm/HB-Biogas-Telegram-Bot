(function () {
  'use strict';

  let deps = null;
  let invoiceUploadInProgress = false;
  let activeBatch = null;
  let activePaymentPrintPayload = null;
  let activePaymentReviewId = null;

  function el(id) { return deps.el(id); }
  function state() { return deps.state; }
  function csrfHeader() { return { 'X-CSRFToken': deps.getCookie('csrftoken') || '' }; }

  function renderPrintableRequisition(data) {
    const farmers = data.farmers || [...(data.ready || []), ...(data.blocked || []).map(item => item.farmer)];
    const rows = farmers.map((farmer, index) => {
      const source = String(farmer.lead_source || '').toLowerCase();
      const isJbl = source.includes('jbl') || source.includes('jawabu');
      const deposit = farmer.deposit_paid_hbg || farmer.actual_receipts || '';
      const preview = farmer.requisition_preview || {
        location: [farmer.sub_county, farmer.village].filter(Boolean).join(' - '),
        hbg_deposit: isJbl ? '' : deposit,
        jbl_deposit: isJbl ? (farmer.system_deposit_paid_jbl || deposit) : '',
      };
      return `<tr>
        <td>${index + 1}</td>
        <td>${deps.escapeHtml(farmer.customer_name || '-')}</td>
        <td>${deps.escapeHtml(farmer.primary_phone || '-')}</td>
        <td>${deps.escapeHtml(farmer.national_id || '-')}</td>
        <td>${deps.escapeHtml(farmer.credit_decision || '-')}</td>
        <td>${deps.escapeHtml(farmer.final_decision_comment || '')}</td>
        <td>${deps.escapeHtml(farmer.county || '-')}</td>
        <td>${deps.escapeHtml(preview.location || '-')}</td>
        <td>${paymentAmount(preview.hbg_deposit)}</td>
        <td>${paymentAmount(preview.jbl_deposit)}</td>
        <td>${deps.escapeHtml(farmer.hb_sales_person || '-')}</td>
      </tr>`;
    }).join('');
    return `<article class="requisition-print-preview">
      <header><h3>JBL Requisition Form</h3><div><strong>Order No:</strong> ${deps.escapeHtml(data.order_number || '-')}</div><div><strong>Date:</strong> ${deps.escapeHtml(deps.fmtDate(data.requisition_date))}</div></header>
      <div class="requisition-print-scroll"><table>
        <thead><tr><th>No.</th><th>Customer name</th><th>Contact</th><th>ID No.</th><th>Credit analysis</th><th>Callup comment</th><th>County</th><th>Location & nearest landmark</th><th>HBG deposit</th><th>JBL deposit</th><th>HB salesperson</th></tr></thead>
        <tbody>${rows || '<tr><td colspan="11">No clients selected.</td></tr>'}</tbody>
      </table></div>
      <footer><span><strong>Requisitioned by:</strong> __________________</span><span><strong>Signature:</strong> __________________</span><span><strong>Date:</strong> __________________</span><span><strong>Jawabu stamp:</strong> __________________</span></footer>
    </article>`;
  }

  function paymentValue(value) {
    return value === null || value === undefined || value === '' ? '' : deps.escapeHtml(value);
  }

  function paymentAmount(value) {
    if (value === null || value === undefined || value === '') return '';
    const number = Number(String(value).replace(/,/g, ''));
    if (!Number.isFinite(number)) return deps.escapeHtml(value);
    return deps.escapeHtml(Number.isInteger(number) ? String(number) : String(number).replace(/\.0+$/, ''));
  }

  function requestedPaymentNumber() {
    const input = el('batch-payment-number');
    let value = String(input?.value || '').trim().replace(/^#/, '');
    if (!value) value = String(window.prompt('Enter the payment number (for example, 89):', '') || '').trim().replace(/^#/, '');
    if (!/^\d{1,20}$/.test(value)) {
      deps.showToast('Enter a valid payment number using digits only.', 'error');
      return '';
    }
    if (input) input.value = value;
    return value;
  }

  function renderPrintablePayment(preview) {
    const rows = (preview.rows || []).map((row, index) => `<tr>
      <td>${index + 1}</td><td>${deps.escapeHtml(deps.fmtDate(row.requisition_date))}</td>
      <td>${paymentValue(row.order_no)}</td><td>${paymentValue(row.cust_no)}</td>
      <td>${paymentValue(row.name_imab)}</td><td>${paymentValue(row.name)}</td>
      <td>${paymentValue(row.mobile_no)}</td><td>${paymentValue(row.secondary_mobile)}</td>
      <td>${paymentValue(row.branch)}</td><td>${paymentValue(row.loan_officer)}</td>
      <td class="amount">${paymentAmount(row.hb_invoice_amount)}</td>
      <td class="amount">${paymentAmount(row.expected_invoice_amount)}</td>
      <td class="amount">${paymentAmount(row.discount)}</td>
      <td class="amount">${paymentAmount(row.deposit_paid_hbg)}</td>
      <td class="amount">${paymentAmount(row.deposit_paid_jbl)}</td>
      <td class="amount">${paymentAmount(row.loan_amount)}</td>
      <td>${deps.escapeHtml(deps.fmtDate(row.repayment_dates))}</td><td>${paymentValue(row.tenor)}</td>
      <td>${paymentValue(row.product)}</td><td>${paymentValue(row.call_up_comments)}</td>
    </tr>`).join('');
    const totals = preview.totals || {};
    return `<article class="payment-print-preview">
      <header><h3>JBL Payment Schedule #${deps.escapeHtml(preview.payment_number || '-')}</h3><div><strong>Order No:</strong> ${deps.escapeHtml(preview.order_number || '-')}</div><div><strong>Clients:</strong> ${deps.escapeHtml(preview.ready_count || 0)}</div></header>
      <div class="payment-total-strip"><span>Balance due <strong>${paymentAmount(totals.hb_invoice_amount) || '0'}</strong></span><span>Discount <strong>${paymentAmount(totals.discount) || '0'}</strong></span><span>HBG deposit <strong>${paymentAmount(totals.deposit_paid_hbg) || '0'}</strong></span><span>JBL deposit <strong>${paymentAmount(totals.deposit_paid_jbl) || '0'}</strong></span></div>
      <div class="payment-print-scroll"><table>
        <thead><tr><th>No.</th><th>Requisition date</th><th>Order no.</th><th>Cust no.</th><th>Name in IMAB</th><th>Name</th><th>Primary mobile</th><th>Secondary mobile</th><th>Branch</th><th>Loan officer</th><th>HB invoice amount</th><th>Expected invoice amount</th><th>Discount</th><th>Deposit paid to HBG</th><th>Deposit paid to JBL</th><th>Loan amount</th><th>Repayment dates</th><th>Tenor</th><th>Product</th><th>Call up comments</th></tr></thead>
        <tbody>${rows || '<tr><td colspan="20">No payment rows available.</td></tr>'}</tbody>
      </table></div>
      <footer><span><strong>Prepared by:</strong> __________________</span><span><strong>Checked by:</strong> __________________</span><span><strong>Authorized by:</strong> __________________</span><span><strong>Date:</strong> __________________</span></footer>
    </article>`;
  }

  function paymentReviewValue(row, key, { amount = false, date = false } = {}) {
    const value = row?.[key];
    if (value === null || value === undefined || value === '') return '-';
    if (amount) return paymentAmount(value) || '-';
    if (date) return deps.escapeHtml(deps.fmtDate(value) || value);
    return paymentValue(value) || '-';
  }

  function bindPaymentReviewAccordion(container) {
    const cards = [...(container?.querySelectorAll('[data-payment-case-card]') || [])];
    cards.forEach(card => {
      card.addEventListener('toggle', () => {
        if (!card.open) return;
        // Keep review focused on one client at a time while retaining native
        // details keyboard and accessibility behaviour.
        cards.forEach(other => {
          if (other !== card) other.open = false;
        });
      });
      const input = card.querySelector('.payment-case-comment');
      const preview = card.querySelector('[data-payment-comment-preview]');
      if (!input || !preview) return;
      const previewContainer = preview.closest('.payment-review-comment-preview') || preview;
      const syncCommentPreview = () => {
        const value = String(input.value || '').trim();
        const text = value || 'Not reviewed — no payment comment';
        preview.textContent = text;
        preview.title = text;
        previewContainer.classList.toggle('has-comment', Boolean(value));
      };
      input.addEventListener('input', syncCommentPreview);
      syncCommentPreview();
    });
  }

  function renderPaymentReviewCards(preview, document) {
    const rows = preview.rows || [];
    const comments = document?.case_call_up_comments || {};
    const pendingReview = document?.status === 'pending_review';
    if (!rows.length) return '<div class="batch-warning">No payment cases are available for review.</div>';
    const fields = [
      ['Requisition date', 'requisition_date', { date: true }],
      ['Order no.', 'order_no'],
      ['Customer no.', 'cust_no'],
      ['Name in IMAB', 'name_imab'],
      ['Customer name', 'name'],
      ['Primary mobile', 'mobile_no'],
      ['Secondary mobile', 'secondary_mobile'],
      ['Branch', 'branch'],
      ['Loan officer', 'loan_officer'],
      ['HB invoice amount (balance due)', 'hb_invoice_amount', { amount: true }],
      ['Expected invoice amount', 'expected_invoice_amount', { amount: true }],
      ['Discount', 'discount', { amount: true }],
      ['Deposit paid to HBG', 'deposit_paid_hbg', { amount: true }],
      ['Deposit paid to JBL', 'deposit_paid_jbl', { amount: true }],
      ['Loan amount', 'loan_amount', { amount: true }],
      ['Repayment date', 'repayment_dates', { date: true }],
      ['Tenor', 'tenor'],
      ['Product', 'product'],
    ];
    return `<section class="payment-review-case-list"><p class="meta">Review each client using the complete payment row. Open a case for the timeline and supporting documents, then record that client's Head of Rural Call Up Comment.</p>${rows.map((row, index) => {
      const farmerId = String(row.farmer_id || document?.farmer_ids?.[index] || '');
      // Pending reviews must never reuse a legacy row-level comment: older
      // snapshots stored the order/requisition comment in that column. The
      // payment COL is authoritative only from the per-case review map.
      const comment = pendingReview
        ? comments[farmerId] || ''
        : row.call_up_comments || comments[farmerId] || '';
      const orderComment = row.order_call_up_comments
        ? `<div class="payment-review-reference"><strong>Order/requisition comment (reference only)</strong><span>${deps.escapeHtml(row.order_call_up_comments)}</span></div>`
        : '';
      return `<details class="payment-review-case-card" data-payment-case-card>
        <summary class="payment-review-case-summary"><div><span class="payment-review-case-number">Case ${index + 1}</span><h3>${deps.escapeHtml(row.name || row.name_imab || 'Unnamed customer')}</h3><p>${deps.escapeHtml([row.cust_no && `Customer ${row.cust_no}`, row.order_no && `Order ${row.order_no}`].filter(Boolean).join(' | ') || 'Identifiers not recorded')}</p><p class="payment-review-comment-preview${comment ? ' has-comment' : ''}"><span class="payment-review-comment-label">Payment comment (COL)</span><span data-payment-comment-preview>${deps.escapeHtml(comment || 'Not reviewed — no payment comment')}</span></p></div><span class="badge badge-orange">HOR review</span></summary>
        <div class="payment-review-case-body"><div class="payment-review-grid">${fields.map(([label, key, options]) => `<div class="payment-review-field"><span>${deps.escapeHtml(label)}</span><strong>${paymentReviewValue(row, key, options)}</strong></div>`).join('')}</div>
        ${orderComment}
        <div class="payment-review-case-actions"><button type="button" class="btn btn-secondary payment-open-case" data-farmer-id="${deps.escapeHtml(farmerId)}">Open case</button></div>
        <label class="payment-review-comment"><span>Payment Call Up Comment (COL)</span><textarea class="payment-case-comment" data-farmer-id="${deps.escapeHtml(farmerId)}" rows="3" placeholder="HOR decision for this client" required>${deps.escapeHtml(comment)}</textarea></label>
        </div></details>`;
    }).join('')}<div class="payment-review-submit"><button type="button" class="btn btn-primary" id="payment-review-approve" data-document-id="${deps.escapeHtml(document.id)}">Approve and create final payment</button></div></section>`;
  }

  async function openPaymentPreview(orderNumber, button) {
    const overlay = el('payment-preview-overlay');
    const target = el('payment-preview-content');
    const sub = el('payment-preview-sub');
    if (!overlay || !target || !orderNumber) return;
    const paymentNumber = requestedPaymentNumber();
    if (!paymentNumber) return;
    overlay.classList.add('open');
    if (el('payment-preview-title')) el('payment-preview-title').textContent = 'Payment Preview';
    if (sub) sub.textContent = `Payment #${paymentNumber} - Order ${orderNumber}`;
    target.innerHTML = '<div class="empty-state"><div class="spinner-inline"></div></div>';
    if (button) deps.setButtonLoading(button, true, 'Loading Preview...');
    try {
      const response = await deps.apiFetch('/payment-documents/' + encodeURIComponent(orderNumber) + '/preview-data/?payment_number=' + encodeURIComponent(paymentNumber));
      const preview = response.data?.preview || {};
      if (!response.ok || !response.data?.ok) {
        renderPaymentResult(target, { readiness: { blocked: preview.blocked || [], ready_count: preview.ready_count || 0 } });
        deps.showToast(response.data?.error || 'Payment preview is blocked.', 'error');
        return;
      }
      target.innerHTML = renderPrintablePayment(preview);
      deps.showToast('Payment preview shown in the Mini App.', 'success');
    } catch (err) {
      target.innerHTML = `<div class="batch-warning">${deps.escapeHtml(err.message || 'Could not load payment preview.')}</div>`;
      deps.showToast('Could not load payment preview.', 'error');
    } finally {
      if (button) deps.setButtonLoading(button, false);
    }
  }

  async function openFinalOrderHistory(orderNumber) {
    const response = await deps.apiFetch('/requisition-batches/' + encodeURIComponent(orderNumber) + '/');
    if (!response.ok || !response.data?.ok) return deps.showToast(response.data?.error || 'Could not load final order.', 'error');
    const batch = response.data.batch || {};
    openRequisitionPreview({
      ...batch,
      ready_count: batch.farmer_count || (batch.farmers || []).length,
      blocked_count: 0,
      warning_count: 0,
    }, { readOnly: true });
  }

  async function openFinalPaymentHistory(documentId) {
    const response = await deps.apiFetch('/payment-document-history/' + encodeURIComponent(documentId) + '/');
    if (!response.ok || !response.data?.ok) return deps.showToast(response.data?.error || 'Could not load payment document.', 'error');
    const document = response.data.document || {};
    const preview = response.data.preview || {};
    preview.rows = (preview.rows || []).map((row, index) => ({
      ...row,
      farmer_id: row.farmer_id || document.farmer_ids?.[index] || '',
    }));
    const overlay = el('payment-preview-overlay');
    if (el('payment-preview-title')) el('payment-preview-title').textContent = document.status === 'pending_review' ? 'Payment Review' : 'Payment Preview';
    if (el('payment-preview-sub')) el('payment-preview-sub').textContent = `Payment #${preview.payment_number || '-'} - Order ${preview.order_number || '-'}`;
    if (el('payment-preview-content')) {
      // Pending payment documents are a case-by-case HOR decision surface.
      // Final documents retain the printable table for historical reference.
      const content = el('payment-preview-content');
      const pendingReview = document.status === 'pending_review';
      content.innerHTML = pendingReview ? renderPaymentReviewCards(preview, document) : renderPrintablePayment(preview);
      if (pendingReview) bindPaymentReviewAccordion(content);
    }
    activePaymentReviewId = document.status === 'pending_review' ? document.id : null;
    activePaymentPrintPayload = { orderNumber: preview.order_number, paymentNumber: preview.payment_number };
    overlay?.classList.add('open');
  }

  async function approvePaymentReview(button) {
    const documentId = button?.dataset.documentId || activePaymentReviewId;
    const caseComments = {};
    document.querySelectorAll('.payment-case-comment').forEach(input => {
      const farmerId = String(input.dataset.farmerId || '').trim();
      if (farmerId) caseComments[farmerId] = String(input.value || '').trim();
    });
    const missing = Object.values(caseComments).some(value => !value);
    if (!documentId || !Object.keys(caseComments).length || missing) {
      deps.showToast('Enter a Head of Rural Call Up Comment for every selected case.', 'error');
      return;
    }
    deps.setButtonLoading(button, true, 'Approving...');
    try {
      const response = await deps.portalApi.postJson(
        '/payment-document/' + encodeURIComponent(documentId) + '/approve/',
        { case_call_up_comments: caseComments },
        deps.tg,
        csrfHeader(),
      );
      if (!response.ok || !response.data?.ok) throw new Error(response.data?.error || 'Could not approve payment.');
      deps.showToast('Payment approved and final workbook stored.', 'success');
      await openFinalPaymentHistory(response.data.document.id);
    } catch (error) {
      deps.showToast(error.message || 'Could not approve payment.', 'error');
    } finally {
      deps.setButtonLoading(button, false);
    }
  }

  function updateBatchPanel() {
    const panel = el('requisition-batch-panel');
    if (!panel) return;
    const count = state().selectedRequisitions.size;
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
    const farmer_ids = Array.from(state().selectedRequisitions);
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

  function paymentReadinessRows(items) {
    if (!items || !items.length) return '';
    return items.map(item => `
      <div class="batch-client-row">
        <div class="name">${deps.escapeHtml(item.customer_name || 'Unnamed client')}</div>
        <div class="meta">ID ${deps.escapeHtml(item.national_id || '-')} | ${deps.escapeHtml(item.primary_phone || '-')}</div>
        <div class="batch-warning" style="margin-top:8px;">Missing: ${(item.missing || []).map(deps.escapeHtml).join(', ')}</div>
      </div>
    `).join('');
  }

  function renderPaymentResult(target, payload) {
    if (!target) return;
    if (!payload) {
      target.innerHTML = '';
      return;
    }
    if (payload.document) {
      const doc = payload.document;
      const label = doc.status === 'final'
        ? 'Final payment document'
        : doc.status === 'pending_review'
          ? 'Payment draft awaiting Head of Rural review'
          : 'Payment preview';
      target.innerHTML = `
        <div class="batch-warning" style="background:#f0fdf4;border-color:#bbf7d0;color:#166534;margin-top:10px;">
          ${label} generated: ${deps.escapeHtml(doc.filename || '')}
          ${doc.drive_url ? `<button type="button" class="btn btn-secondary" id="batch-payment-open" style="margin-top:8px;width:100%;justify-content:center;">Open in Drive</button>` : ''}
        </div>
      `;
      el('batch-payment-open')?.addEventListener('click', () => deps.openPortalLink(doc.drive_url));
      return;
    }
    const readiness = payload.readiness || payload.data || {};
    const blocked = readiness.blocked || [];
    if (blocked.length) {
      target.innerHTML = `
        <div class="batch-warning-list" style="margin-top:10px;">
          <div class="batch-warning">Payment document is blocked for ${blocked.length} client(s). Resolve the missing fields below.</div>
          ${paymentReadinessRows(blocked)}
        </div>
      `;
      return;
    }
    target.innerHTML = `
      <div class="batch-warning" style="background:#f8fafc;border-color:#cbd5e1;color:#334155;margin-top:10px;">
        Payment document ready for ${readiness.ready_count || 0} client(s).
      </div>
    `;
  }

  async function checkPaymentReadiness(orderNumber) {
    const target = el('batch-detail-payment-result');
    if (!target) return;
    target.innerHTML = '<div class="empty-state"><div class="spinner-inline"></div></div>';
    try {
      const { ok, data } = await deps.apiFetch('/payment-documents/' + encodeURIComponent(orderNumber) + '/readiness/');
      if (!ok || !data.ok) throw new Error(data.error || 'Could not check payment readiness.');
      renderPaymentResult(target, data);
    } catch (err) {
      target.innerHTML = `<div class="batch-warning">${deps.escapeHtml(err.message || 'Could not check payment readiness.')}</div>`;
    }
  }

  async function generatePaymentDocument(orderNumber, final, button) {
    const target = el('batch-detail-payment-result');
    const paymentNumber = requestedPaymentNumber();
    if (!paymentNumber) return;
    const label = final ? 'Generating Final...' : 'Loading Preview...';
    deps.setButtonLoading(button, true, label);
    try {
      if (!final) {
        const response = await deps.apiFetch('/payment-documents/' + encodeURIComponent(orderNumber) + '/preview-data/');
        const preview = response.data?.preview || {};
        if (!response.ok || !response.data?.ok) {
          renderPaymentResult(target, { readiness: { blocked: preview.blocked || [], ready_count: preview.ready_count || 0 } });
          throw new Error('Payment preview is blocked. Resolve the listed fields.');
        }
        target.innerHTML = renderPrintablePayment(preview);
        deps.showToast('Payment values preview shown in the Mini App.', 'success');
        return;
      }
      const path = '/payment-documents/' + encodeURIComponent(orderNumber) + '/' + (final ? 'finalize/' : 'preview/');
      const response = await deps.portalApi.postJson(path, { payment_number: paymentNumber }, deps.tg, csrfHeader());
      const data = response.data || {};
      if (!response.ok || !data.ok) {
        renderPaymentResult(target, data);
        deps.showToast(data.error || 'Payment document is not ready.', 'error');
        return;
      }
      renderPaymentResult(target, data);
      deps.showToast(data.document?.status === 'pending_review'
        ? 'Payment draft submitted for Head of Rural review.'
        : 'Payment document stored in Drive.', 'success');
    } catch (err) {
      deps.showToast(err.message || 'Payment document generation failed.', 'error');
    } finally {
      deps.setButtonLoading(button, false);
    }
  }

  async function generateRequisitionForBatch(batch, button) {
    const farmers = batch.farmers || [];
    const farmerIds = farmers.map(farmer => farmer.id).filter(Boolean);
    if (!farmerIds.length) {
      deps.showToast('No clients are linked to this order.', 'error');
      return;
    }
    const reqDate = batch.requisition_date || new Date().toISOString().split('T')[0];
    const payload = {
      farmer_ids: farmerIds,
      order_number: batch.order_number,
      requisition_date: reqDate,
      return_url: true,
    };
    deps.setButtonLoading(button, true, 'Generating...');
    try {
      const response = await deps.portalApi.postJson('/requisition-queue/generate/', payload, deps.tg, csrfHeader());
      const result = response.data || {};
      if (!response.ok || !result.ok) {
        deps.showToast(result.error || 'Could not generate the requisition form.', 'error');
        return;
      }
      deps.showToast('Requisition form generated and stored.', 'success');
      if (result.drive_url || result.download_url) {
        deps.openPortalLink(result.drive_url || result.download_url);
      }
      deps.loadQueue('batches', state().pages.batches || 1);
      openBatchDetail(batch.order_number);
    } catch (err) {
      deps.showToast(err.message || 'Could not generate the requisition form.', 'error');
    } finally {
      deps.setButtonLoading(button, false);
    }
  }

  async function previewRequisitionInApp(payload, button) {
    deps.setButtonLoading(button, true, 'Loading Preview...');
    try {
      const response = await deps.portalApi.postJson('/requisition-queue/preview/', payload, deps.tg, csrfHeader());
      if (!response.ok || !response.data?.ok) throw new Error(response.data?.error || 'Could not load preview.');
      openRequisitionPreview(response.data, { readOnly: true });
    } catch (err) { deps.showToast(err.message, 'error'); }
    finally { deps.setButtonLoading(button, false); }
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

    const { ok, data } = await deps.apiFetch('/requisition-batches/' + encodeURIComponent(orderNumber) + '/');
    if (!ok || !data.ok) {
      clients.innerHTML = `<div class="empty-state"><div class="es-title">Could not load batch</div><div class="es-sub">${deps.escapeHtml(data.error || 'Try again.')}</div></div>`;
      return;
    }
    const batch = data.batch;
    activeBatch = batch;
    const inv = batch.invoice_summary || {};
    sub.textContent = `${batch.requisition_date || 'No date'} - ${batch.farmer_count || 0} client(s)`;
    summary.innerHTML = deps.summaryGrid([
      { label: 'Clients', value: String(batch.farmer_count || 0) },
      { label: 'Invoiced', value: String(inv.invoiced_count || 0) },
      { label: 'Pending invoices', value: String(inv.pending_invoice_count ?? 0) },
    ]);
    const hasRequisitionOutput = batch.drive_url || batch.download_url;
    actions.innerHTML = `
      ${hasRequisitionOutput ? `<button class="btn btn-primary" id="batch-detail-download">Open Saved Excel</button>` : '<button class="btn btn-primary" id="batch-detail-generate">Generate and Save Excel</button><span class="badge badge-grey">No generated requisition form yet</span>'}
      <button class="btn btn-secondary" id="batch-detail-preview">Preview in App</button>
      <button class="btn btn-secondary" id="batch-detail-upload">Upload Invoices</button>
    `;
    if (inv.last_invoice_upload_status) {
      const cls = inv.last_invoice_upload_status === 'success' ? 'badge-green' : inv.last_invoice_upload_status === 'partial' ? 'badge-orange' : 'badge-red';
      invoiceResult.innerHTML = `<span class="badge ${cls}">Last invoice upload: ${deps.escapeHtml(inv.last_invoice_upload_status)}</span>${inv.last_invoice_upload_error ? `<div class="batch-warning" style="margin-top:8px;">${deps.escapeHtml(inv.last_invoice_upload_error)}</div>` : ''}`;
    } else {
      invoiceResult.innerHTML = '<span class="badge badge-grey">No invoice upload recorded</span>';
    }
    clients.innerHTML = deps.batchClientRows(batch.farmers || []);
  }

  async function requestRequisitionPreview() {
    const payload = currentRequisitionPayload();
    if (!payload) return;
    try {
      deps.showToast('Preparing batch preview...');
      const result = await deps.portalApi.postJson('/requisition-queue/preview/', payload, deps.tg, csrfHeader());
      const data = result.data || {};
      if (!result.ok || !data.ok) {
        deps.showToast(data.error || 'Could not prepare preview.', 'error');
        return;
      }
      state().pendingRequisitionPayload = payload;
      openRequisitionPreview(data, { readOnly: false });
    } catch (err) {
      console.error(err);
      deps.showToast('Could not prepare preview.', 'error');
    }
  }

  function openRequisitionPreview(data, { readOnly = false } = {}) {
    const overlay = el('requisition-preview-overlay');
    const sub = el('requisition-preview-sub');
    const summary = el('requisition-preview-summary');
    const warnings = el('requisition-preview-warnings');
    const list = el('requisition-preview-list');
    const confirm = el('requisition-preview-confirm');
    const cancel = el('requisition-preview-cancel');
    const progress = el('requisition-preview-progress');
    const blockedById = {};
    (data.blocked || []).forEach(item => {
      if (item.farmer?.id) blockedById[item.farmer.id] = item.missing || [];
    });
    sub.textContent = `Order ${data.order_number} - ${deps.fmtDate(data.requisition_date)}`;
    summary.innerHTML = deps.summaryGrid([
      { label: 'Ready', value: String(data.ready_count || 0) },
      { label: 'Blocked', value: String(data.blocked_count || 0) },
      { label: 'Warnings', value: String(data.warning_count || 0) },
    ]);
    deps.renderWarnings(warnings, data.warnings || []);
    list.innerHTML = renderPrintableRequisition(data);
    // A previous generation may have left the progress row visible. History
    // previews are read-only and must never imply that a workbook is being
    // generated or make another generation request.
    if (progress) progress.hidden = true;
    // Keep generation as one visible action: Telegram's native MainButton.
    // The inline element is a hidden proxy so the shell can invoke the same
    // click handler and the browser/keyboard fallback remains available.
    const usesTelegramMainButton = Boolean(deps.tg?.MainButton);
    confirm.hidden = readOnly || usesTelegramMainButton;
    confirm.toggleAttribute('aria-hidden', readOnly || usesTelegramMainButton);
    if (readOnly) confirm.removeAttribute('data-main-action');
    else confirm.dataset.mainAction = 'Generate and Save Excel';
    confirm.disabled = readOnly || (data.blocked_count || 0) > 0 || !(data.ready_count || 0);
    confirm.textContent = confirm.disabled && !readOnly ? 'Resolve Blocked Items' : 'Generate and Save Excel';
    if (cancel) cancel.textContent = readOnly ? 'Close Preview' : 'Back';
    overlay.classList.add('open');
  }

  async function generateRequisitionFromPreview() {
    const payload = state().pendingRequisitionPayload;
    if (!payload) return;
    const confirm = el('requisition-preview-confirm');
    if (state().generatingRequisition) return;
    state().generatingRequisition = true;
    const progress = el('requisition-preview-progress');
    const mainButton = deps.tg?.MainButton;
    const usingTelegramMainButton = Boolean(mainButton);
    if (progress) {
      progress.hidden = false;
      progress.querySelector('span:last-child').textContent = 'Generating and saving Excel…';
    }
    // Telegram's MainButton is the visible action in the Mini App. Keep its
    // label and progress state explicit; disabling the hidden proxy would
    // otherwise make the native button disappear before the request starts.
    if (usingTelegramMainButton) {
      mainButton.setText?.('Generating…');
      mainButton.showProgress?.(false);
    } else {
      deps.setButtonLoading(confirm, true, 'Generating...');
    }
    try {
      const response = await deps.portalApi.postJson('/requisition-queue/generate/', payload, deps.tg, csrfHeader());
      const result = response.data || {};
      if (!response.ok || !result.ok || !(result.drive_url || result.download_url)) {
        deps.showToast(result.error || 'Requisition generation failed.', 'error');
        return;
      }
      deps.openPortalLink(result.drive_url || result.download_url);
      deps.showToast('Requisition generated and saved to Batches.', 'success');
      state().selectedRequisitions.clear();
      state().pendingRequisitionPayload = null;
      el('batch-order-num').value = '';
      el('batch-req-date').value = '';
      updateBatchPanel();
      el('requisition-preview-overlay').classList.remove('open');
      confirm.removeAttribute('data-main-action');
      confirm.hidden = true;
      confirm.setAttribute('aria-hidden', 'true');
      deps.loadQueue('requisition', 1);
      deps.loadQueue('batches', 1);
    } catch (err) {
      console.error(err);
      deps.showToast('An error occurred during generation.', 'error');
    } finally {
      state().generatingRequisition = false;
      if (progress) progress.hidden = true;
      if (usingTelegramMainButton) {
        mainButton.hideProgress?.();
        mainButton.setText?.('Generate and Save Excel');
      } else {
        deps.setButtonLoading(confirm, false);
      }
    }
  }

  function validateInvoiceFile(file, maxBytes, maxMb) {
    if (deps.portalHelpers.validateInvoiceFile) return deps.portalHelpers.validateInvoiceFile(file, maxBytes, maxMb);
    if (!file) return 'Select a PDF file first.';
    if (!String(file.name || '').toLowerCase().endsWith('.pdf')) return 'Only PDF files are supported.';
    if (file.size > maxBytes) {
      return `This PDF is ${deps.portalHelpers.invoiceFileSizeLabel(file.size)}. Maximum supported size is ${maxMb} MB.`;
    }
    return '';
  }

  function bindInvoiceUpload() {
    const invoiceOverlay = el('invoice-overlay');
    const invoiceOverlayClose = el('invoice-overlay-close');
    const invoiceUploadForm = el('invoice-upload-form');
    const invoiceFileInput = el('invoice-file-input');
    const invoiceFileInfo = el('invoice-file-info');
    const invoiceSubmitBtn = el('invoice-submit-btn');
    const invoiceResults = el('invoice-results');
    const invoiceResultsSummary = el('invoice-results-summary');
    const invoiceResultsList = el('invoice-results-list');
    if (!invoiceOverlay || !invoiceUploadForm) return;

    const invoiceUploadMaxMb = Number(window.PORTAL_CONFIG?.invoiceUploadMaxFileSizeMb || 8);
    const invoiceUploadMaxBytes = Math.max(1, invoiceUploadMaxMb) * 1024 * 1024;

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
        const validationError = validateInvoiceFile(file, invoiceUploadMaxBytes, invoiceUploadMaxMb);
        if (validationError) {
          deps.showToast(validationError, 'error');
          invoiceFileInput.value = '';
          invoiceFileInfo.style.display = 'none';
          invoiceSubmitBtn.disabled = true;
          return;
        }
        invoiceFileInfo.textContent = `Selected: ${file.name} (${deps.portalHelpers.invoiceFileSizeLabel(file.size)}). Limit: ${invoiceUploadMaxMb} MB.`;
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
      const validationError = validateInvoiceFile(file, invoiceUploadMaxBytes, invoiceUploadMaxMb);
      if (validationError) {
        deps.showToast(validationError, 'error');
        return;
      }
      if (navigator.onLine === false) {
        deps.updateConnectionBanner();
        deps.showToast('Offline. Reconnect before uploading invoice PDFs.', 'error');
        return;
      }

      invoiceUploadInProgress = true;
      invoiceSubmitBtn.disabled = true;
      const origBtnText = invoiceSubmitBtn.textContent;
      invoiceSubmitBtn.textContent = 'Extracting & Syncing...';

      try {
        const formData = new FormData(invoiceUploadForm);
        const response = await deps.portalApi.postForm('/requisition-batches/upload-invoices/', formData, deps.tg, csrfHeader());
        if (!response.ok) throw new Error((response.data || {}).error || 'Failed to process invoices.');

        const res = response.data || {};
        if (!res.ok && !(res.results || []).length) throw new Error(res.error || 'Invoice extraction failed.');

        deps.showToast(
          res.ok ? `Invoices processed successfully! Matched ${res.matched_count} of ${res.total_parsed}.` : (res.error || 'No invoice matched. Review the details below.'),
          res.ok ? 'success' : 'error'
        );
        if (res.requires_confirmation) {
          invoiceResultsSummary.textContent = `Review ${res.total_parsed || 0} extracted invoice(s). No farmer or Sheet has been updated yet.`;
          invoiceResultsList.innerHTML = (res.results || []).map(row => `
            <div class="batch-client-row invoice-draft-row" data-invoice="${deps.escapeHtml(row.id)}">
              <label>Invoice no<input data-field="invoice_no" value="${deps.escapeHtml(row.invoice_no || '')}"></label>
              <label>Date<input type="date" data-field="invoice_date" value="${deps.escapeHtml(row.invoice_date || '')}"></label>
              <label>Customer<input data-field="customer_name" value="${deps.escapeHtml(row.customer_name || '')}"></label>
              <label>ID<input data-field="customer_id" value="${deps.escapeHtml(row.customer_id || '')}"></label>
              <label>Phone<input data-field="customer_phone" value="${deps.escapeHtml(row.customer_phone || '')}"></label>
              <label>Invoice amount<input inputmode="decimal" data-field="invoice_amount" value="${deps.escapeHtml(row.invoice_amount || '')}"></label>
              <label>Discount<input inputmode="decimal" data-field="discount" value="${deps.escapeHtml(row.discount || '')}"></label>
              <label>Payment<input inputmode="decimal" data-field="payment" value="${deps.escapeHtml(row.payment || '')}"></label>
              <label>Balance due<input inputmode="decimal" data-field="balance_due" value="${deps.escapeHtml(row.balance_due || '')}"></label>
              <div class="meta">Proposed match: ${deps.escapeHtml(row.proposed_farmer_name || 'Unresolved')} ${row.proposed_order_number ? `| Order ${deps.escapeHtml(row.proposed_order_number)}` : ''}</div>
            </div>`).join('') + '<button class="btn btn-primary" type="button" id="invoice-confirm-batch">Confirm Entire Batch</button>';
          el('invoice-confirm-batch')?.addEventListener('click', async event => {
            deps.setButtonLoading(event.currentTarget, true, 'Confirming...');
            try {
              for (const draft of invoiceResultsList.querySelectorAll('.invoice-draft-row')) {
                const body = {};
                draft.querySelectorAll('[data-field]').forEach(input => { body[input.dataset.field] = input.value; });
                const saved = await deps.apiFetch('/invoice-pool/' + encodeURIComponent(draft.dataset.invoice) + '/draft/', { method: 'POST', body: JSON.stringify(body) });
                if (!saved.ok || !saved.data?.ok) throw new Error(saved.data?.error || 'Could not save an invoice draft.');
              }
              const confirmed = await deps.apiFetch('/invoice-batches/' + encodeURIComponent(res.invoice_batch_id) + '/confirm/', { method: 'POST', body: JSON.stringify({}) });
              if (!confirmed.ok && confirmed.status !== 202) throw new Error(confirmed.data?.error || 'Batch confirmation failed.');
              deps.showToast(confirmed.data?.batch?.sync_status === 'success' ? 'Invoice batch confirmed and synchronized.' : 'Batch committed; Sheet synchronization needs retry.', confirmed.data?.batch?.sync_status === 'success' ? 'success' : 'warning');
              deps.loadQueue('batches', state().pages.batches || 1);
            } catch (err) { deps.showToast(err.message, 'error'); }
            finally { deps.setButtonLoading(event.currentTarget, false); }
          });
        } else {
          invoiceResultsSummary.textContent = deps.portalHelpers.invoiceResultsSummary(res);
          invoiceResultsList.innerHTML = deps.portalHelpers.invoiceResultRows(res);
        }
        invoiceResults.style.display = 'block';
        deps.loadQueue('batches', state().pages.batches || 1);
      } catch (err) {
        deps.showToast(err.message, 'error');
      } finally {
        invoiceUploadInProgress = false;
        invoiceSubmitBtn.disabled = false;
        invoiceSubmitBtn.textContent = origBtnText;
      }
    });
  }

  function bindEvents() {
    if (!document.documentElement.dataset.portalRequisitionEventsBound) {
      document.documentElement.dataset.portalRequisitionEventsBound = 'true';
      document.addEventListener('click', event => {
        const action = event.target.closest(
          '#btn-generate-requisition, #requisition-preview-confirm, '
          + '#requisition-preview-close, #requisition-preview-cancel, #batch-detail-close, '
          + '#batch-detail-download, #batch-detail-generate, #batch-detail-preview, '
          + '#batch-detail-upload'
        );
        if (action) {
          event.preventDefault();
          if (action.id === 'btn-generate-requisition') requestRequisitionPreview();
          else if (action.id === 'requisition-preview-confirm') generateRequisitionFromPreview();
          else if (action.id === 'requisition-preview-close' || action.id === 'requisition-preview-cancel') {
            const confirm = el('requisition-preview-confirm');
            confirm?.removeAttribute('data-main-action');
            if (confirm) {
              confirm.hidden = true;
              confirm.setAttribute('aria-hidden', 'true');
            }
            el('requisition-preview-overlay')?.classList.remove('open');
          }
          else if (action.id === 'batch-detail-close') el('batch-detail-overlay')?.classList.remove('open');
          else if (!activeBatch) deps.showToast('Batch details are unavailable. Close and reopen this batch.', 'error');
          else if (action.id === 'batch-detail-download') deps.openPortalLink(activeBatch.drive_url || activeBatch.download_url);
          else if (action.id === 'batch-detail-generate') generateRequisitionForBatch(activeBatch, action);
          else if (action.id === 'batch-detail-preview') {
            const farmerIds = (activeBatch.farmers || []).map(farmer => farmer.id).filter(Boolean);
            previewRequisitionInApp({
              farmer_ids: farmerIds,
              order_number: activeBatch.order_number,
              requisition_date: activeBatch.requisition_date || new Date().toISOString().split('T')[0],
              return_url: false,
              preview_format: 'document',
            }, action);
          }
          else if (action.id === 'batch-detail-upload') openInvoiceOverlay(activeBatch.order_number);
          else el('requisition-preview-overlay')?.classList.remove('open');
          return;
        }
        const requisitionOverlay = event.target.closest('#requisition-preview-overlay');
        if (requisitionOverlay && event.target === requisitionOverlay) {
          const confirm = el('requisition-preview-confirm');
          confirm?.removeAttribute('data-main-action');
          if (confirm) {
            confirm.hidden = true;
            confirm.setAttribute('aria-hidden', 'true');
          }
          requisitionOverlay.classList.remove('open');
        }
        const batchOverlay = event.target.closest('#batch-detail-overlay');
        if (batchOverlay && event.target === batchOverlay) batchOverlay.classList.remove('open');
        if (event.target.closest('#payment-preview-close, #payment-preview-done')) el('payment-preview-overlay')?.classList.remove('open');
        const approvePaymentButton = event.target.closest('#payment-review-approve');
        if (approvePaymentButton) {
          event.preventDefault();
          approvePaymentReview(approvePaymentButton);
          return;
        }
        const openPaymentCaseButton = event.target.closest('.payment-open-case');
        if (openPaymentCaseButton) {
          event.preventDefault();
          const farmerId = String(openPaymentCaseButton.dataset.farmerId || '').trim();
          if (!farmerId) {
            deps.showToast('This payment row is not linked to a case.', 'error');
            return;
          }
          if (window.PortalAppShell?.openCaseHistory) {
            window.PortalAppShell.openCaseHistory(farmerId);
          } else {
            window.location.assign('/portal/cases/' + encodeURIComponent(farmerId) + '/');
          }
          return;
        }
        const paymentOverlay = event.target.closest('#payment-preview-overlay');
        if (paymentOverlay && event.target === paymentOverlay) paymentOverlay.classList.remove('open');
      });
    }
    bindInvoiceUpload();
  }

  function init(initialDeps) {
    deps = initialDeps;
    bindEvents();
  }

  window.PortalMiniAppRequisitions = {
    init,
    openBatchDetail,
    openInvoiceOverlay,
    openPaymentPreview,
    openFinalOrderHistory,
    openFinalPaymentHistory,
    renderPrintablePayment,
    updateBatchPanel,
  };
})();
