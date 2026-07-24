(function () {
  'use strict';

  let deps = null;
  let invoiceUploadInProgress = false;

  function el(id) { return deps.el(id); }
  function state() { return deps.state; }
  function csrfHeader() { return { 'X-CSRFToken': deps.getCookie('csrftoken') || '' }; }

  function workbookBorder(style) {
    if (!style) return 'none';
    return `${style === 'medium' ? 2 : style === 'thick' ? 3 : 1}px solid #7d8793`;
  }

  function renderWorkbookPreview(workbook) {
    const sheets = workbook?.sheets || [];
    if (!sheets.length) return '<div class="empty-state">Workbook preview is unavailable.</div>';
    const active = workbook.active_sheet || 0;
    const renderedSheets = sheets.map((sheet, index) => {
      const columns = (sheet.columns || []).map(col => `<col style="width:${col.hidden ? 0 : Math.max(24, col.width * 7)}px">`).join('');
      const rows = (sheet.rows || []).filter(row => !row.hidden).map(row => {
        const cells = (row.cells || []).map(cell => {
          const s = cell.style || {};
          const css = [`background:${s.background || '#fff'}`, `color:${s.color || '#111827'}`,
            `font-weight:${s.bold ? '700' : '400'}`, `font-style:${s.italic ? 'italic' : 'normal'}`,
            `font-size:${Math.max(8, s.font_size || 11)}px`,
            `text-align:${s.horizontal === 'center' ? 'center' : s.horizontal === 'right' ? 'right' : 'left'}`,
            `vertical-align:${s.vertical === 'top' ? 'top' : s.vertical === 'bottom' ? 'bottom' : 'middle'}`,
            `white-space:${s.wrap ? 'normal' : 'nowrap'}`, `border-top:${workbookBorder(s.border_top)}`,
            `border-right:${workbookBorder(s.border_right)}`, `border-bottom:${workbookBorder(s.border_bottom)}`,
            `border-left:${workbookBorder(s.border_left)}`].join(';');
          return `<td colspan="${cell.col_span || 1}" rowspan="${cell.row_span || 1}" style="${css}">${deps.escapeHtml(cell.value || '')}</td>`;
        }).join('');
        return `<tr style="height:${Math.max(10, row.height || 18)}px">${cells}</tr>`;
      }).join('');
      return `<section class="workbook-sheet" data-sheet-index="${index}" ${index === active ? '' : 'hidden'}><table><colgroup>${columns}</colgroup><tbody>${rows}</tbody></table>${sheet.truncated ? '<div class="batch-warning">Preview shortened for display. The saved Excel retains all cells.</div>' : ''}</section>`;
    }).join('');
    const tabs = sheets.length > 1 ? `<div class="workbook-tabs">${sheets.map((sheet, index) => `<button type="button" class="workbook-tab ${index === active ? 'active' : ''}" data-sheet-index="${index}">${deps.escapeHtml(sheet.name)}</button>`).join('')}</div>` : '';
    return `<div class="workbook-preview"><div class="workbook-preview-scroll">${renderedSheets}</div>${tabs}</div>`;
  }

  function activateWorkbookTabs(container) {
    container?.querySelectorAll('.workbook-tab').forEach(tab => tab.addEventListener('click', () => {
      const index = tab.dataset.sheetIndex;
      container.querySelectorAll('.workbook-tab').forEach(item => item.classList.toggle('active', item === tab));
      container.querySelectorAll('.workbook-sheet').forEach(sheet => { sheet.hidden = sheet.dataset.sheetIndex !== index; });
    }));
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
      const label = doc.status === 'final' ? 'Final payment document' : 'Payment preview';
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
        const rows = preview.rows || [];
        target.innerHTML = `<div class="form-section"><h3>Payment Preview — Order ${deps.escapeHtml(orderNumber)}</h3>
          <div class="batch-client-list">${rows.map(row => `<div class="batch-client-row"><div class="name">${deps.escapeHtml(row.name || row.name_imab || '-')}</div><div class="meta">Customer ${deps.escapeHtml(row.cust_no || '-')} | Invoice ${deps.escapeHtml(row.hb_invoice_amount ?? '-')} | Discount ${deps.escapeHtml(row.discount ?? '-')} | HB deposit ${deps.escapeHtml(row.deposit_paid_hbg ?? '-')} | JBL deposit ${deps.escapeHtml(row.deposit_paid_jbl ?? '-')}</div></div>`).join('')}</div></div>`;
        target.innerHTML = `<div class="form-section"><h3>Excel Preview - Order ${deps.escapeHtml(orderNumber)}</h3>${renderWorkbookPreview(preview.workbook_preview)}</div>`;
        activateWorkbookTabs(target);
        deps.showToast('Payment Excel preview shown in the Mini App.', 'success');
        return;
      }
      const path = '/payment-documents/' + encodeURIComponent(orderNumber) + '/' + (final ? 'finalize/' : 'preview/');
      const response = await deps.portalApi.postJson(path, {}, deps.tg, csrfHeader());
      const data = response.data || {};
      if (!response.ok || !data.ok) {
        renderPaymentResult(target, data);
        deps.showToast(data.error || 'Payment document is not ready.', 'error');
        return;
      }
      renderPaymentResult(target, data);
      deps.showToast('Final payment document stored in Drive.', 'success');
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

  async function previewRequisitionWorkbook(payload, button) {
    if (!payload) return;
    deps.setButtonLoading(button, true, 'Previewing...');
    try {
      const response = await deps.portalApi.postJson('/requisition-queue/preview-workbook/', payload, deps.tg, csrfHeader());
      const result = response.data || {};
      if (!response.ok || !result.ok || !result.drive_url) {
        deps.showToast(result.error || 'Could not generate workbook preview.', 'error');
        return;
      }
      deps.openPortalLink(result.drive_url);
      deps.showToast('Workbook preview stored in Drive.', 'success');
      deps.loadQueue('batches', state().pages.batches || 1);
    } catch (err) {
      deps.showToast(err.message || 'Could not generate workbook preview.', 'error');
    } finally {
      deps.setButtonLoading(button, false);
    }
  }

  async function previewRequisitionInApp(payload, button) {
    deps.setButtonLoading(button, true, 'Loading Preview...');
    try {
      const response = await deps.portalApi.postJson('/requisition-queue/preview/', payload, deps.tg, csrfHeader());
      if (!response.ok || !response.data?.ok) throw new Error(response.data?.error || 'Could not load preview.');
      state().pendingRequisitionPayload = payload;
      openRequisitionPreview(response.data);
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
    const paymentResult = el('batch-detail-payment-result');
    const clients = el('batch-detail-clients');
    title.textContent = `Order ${orderNumber}`;
    sub.textContent = 'Loading batch details...';
    summary.innerHTML = '';
    actions.innerHTML = '';
    invoiceResult.innerHTML = '';
    if (paymentResult) paymentResult.innerHTML = '';
    clients.innerHTML = '<div class="empty-state"><div class="spinner-inline"></div></div>';
    overlay.classList.add('open');

    const { ok, data } = await deps.apiFetch('/requisition-batches/' + encodeURIComponent(orderNumber) + '/');
    if (!ok || !data.ok) {
      clients.innerHTML = `<div class="empty-state"><div class="es-title">Could not load batch</div><div class="es-sub">${deps.escapeHtml(data.error || 'Try again.')}</div></div>`;
      return;
    }
    const batch = data.batch;
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
      <button class="btn btn-secondary" id="batch-payment-readiness">Check Payment</button>
      <button class="btn btn-secondary" id="batch-payment-preview">Preview Payment in App</button>
      <button class="btn btn-primary" id="batch-payment-final">Generate Final Payment</button>
    `;
    el('batch-detail-download')?.addEventListener('click', () => deps.openPortalLink(batch.drive_url || batch.download_url));
    el('batch-detail-generate')?.addEventListener('click', e => generateRequisitionForBatch(batch, e.currentTarget));
    el('batch-detail-preview')?.addEventListener('click', e => {
      const farmerIds = (batch.farmers || []).map(farmer => farmer.id).filter(Boolean);
      previewRequisitionInApp({
        farmer_ids: farmerIds,
        order_number: batch.order_number,
        requisition_date: batch.requisition_date || new Date().toISOString().split('T')[0],
        return_url: true,
      }, e.currentTarget);
    });
    el('batch-detail-upload')?.addEventListener('click', () => openInvoiceOverlay(batch.order_number));
    el('batch-payment-readiness')?.addEventListener('click', () => checkPaymentReadiness(batch.order_number));
    el('batch-payment-preview')?.addEventListener('click', e => generatePaymentDocument(batch.order_number, false, e.currentTarget));
    el('batch-payment-final')?.addEventListener('click', e => generatePaymentDocument(batch.order_number, true, e.currentTarget));

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
      openRequisitionPreview(data);
    } catch (err) {
      console.error(err);
      deps.showToast('Could not prepare preview.', 'error');
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
    summary.innerHTML = deps.summaryGrid([
      { label: 'Ready', value: String(data.ready_count || 0) },
      { label: 'Blocked', value: String(data.blocked_count || 0) },
      { label: 'Warnings', value: String(data.warning_count || 0) },
    ]);
    deps.renderWarnings(warnings, data.warnings || []);
    const allFarmers = [...(data.ready || []), ...(data.blocked || []).map(item => item.farmer)];
    list.innerHTML = data.workbook_preview
      ? `<h3 class="workbook-preview-title">Excel Preview</h3>${renderWorkbookPreview(data.workbook_preview)}`
      : deps.batchClientRows(allFarmers, blockedById);
    activateWorkbookTabs(list);
    confirm.disabled = (data.blocked_count || 0) > 0 || !(data.ready_count || 0);
    confirm.textContent = confirm.disabled ? 'Resolve Blocked Items' : 'Generate Requisition';
    const preview = el('requisition-preview-workbook');
    if (preview) preview.hidden = true;
    overlay.classList.add('open');
  }

  async function generateWorkbookPreviewFromSelection() {
    const payload = state().pendingRequisitionPayload;
    if (!payload) return;
    await previewRequisitionWorkbook(payload, el('requisition-preview-workbook'));
  }

  async function generateRequisitionFromPreview() {
    const payload = state().pendingRequisitionPayload;
    if (!payload) return;
    const confirm = el('requisition-preview-confirm');
    deps.setButtonLoading(confirm, true, 'Generating...');
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
      deps.loadQueue('requisition', 1);
      deps.loadQueue('batches', 1);
    } catch (err) {
      console.error(err);
      deps.showToast('An error occurred during generation.', 'error');
    } finally {
      deps.setButtonLoading(confirm, false);
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
    el('btn-generate-requisition')?.addEventListener('click', requestRequisitionPreview);
    el('requisition-preview-confirm')?.addEventListener('click', generateRequisitionFromPreview);
    el('requisition-preview-workbook')?.addEventListener('click', generateWorkbookPreviewFromSelection);
    el('requisition-preview-close')?.addEventListener('click', () => el('requisition-preview-overlay').classList.remove('open'));
    el('requisition-preview-cancel')?.addEventListener('click', () => el('requisition-preview-overlay').classList.remove('open'));
    el('requisition-preview-overlay')?.addEventListener('click', e => {
      if (e.target === el('requisition-preview-overlay')) el('requisition-preview-overlay').classList.remove('open');
    });
    el('batch-detail-close')?.addEventListener('click', () => el('batch-detail-overlay').classList.remove('open'));
    el('batch-detail-overlay')?.addEventListener('click', e => {
      if (e.target === el('batch-detail-overlay')) el('batch-detail-overlay').classList.remove('open');
    });
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
    updateBatchPanel,
  };
})();
