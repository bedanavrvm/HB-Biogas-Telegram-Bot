(function () {
  'use strict';

  let deps = null;
  let invoiceUploadInProgress = false;

  function el(id) { return deps.el(id); }
  function state() { return deps.state; }
  function csrfHeader() { return { 'X-CSRFToken': deps.getCookie('csrftoken') || '' }; }

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
    const inv = batch.invoice_summary || {};
    sub.textContent = `${batch.requisition_date || 'No date'} - ${batch.farmer_count || 0} client(s)`;
    summary.innerHTML = deps.summaryGrid([
      { label: 'Clients', value: String(batch.farmer_count || 0) },
      { label: 'Invoiced', value: String(inv.invoiced_count || 0) },
      { label: 'Pending invoices', value: String(inv.pending_invoice_count ?? 0) },
    ]);
    actions.innerHTML = `
      ${batch.download_url ? `<button class="btn btn-primary" id="batch-detail-download">Open Requisition Form</button>` : '<span class="badge badge-grey">No saved requisition file</span>'}
      <button class="btn btn-secondary" id="batch-detail-upload">Upload Invoices</button>
    `;
    el('batch-detail-download')?.addEventListener('click', () => deps.openPortalLink(batch.download_url));
    el('batch-detail-upload')?.addEventListener('click', () => openInvoiceOverlay(batch.order_number));

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
    list.innerHTML = deps.batchClientRows(allFarmers, blockedById);
    confirm.disabled = (data.blocked_count || 0) > 0 || !(data.ready_count || 0);
    confirm.textContent = confirm.disabled ? 'Resolve Blocked Items' : 'Generate Requisition';
    overlay.classList.add('open');
  }

  async function generateRequisitionFromPreview() {
    const payload = state().pendingRequisitionPayload;
    if (!payload) return;
    const confirm = el('requisition-preview-confirm');
    deps.setButtonLoading(confirm, true, 'Generating...');
    try {
      const response = await deps.portalApi.postJson('/requisition-queue/generate/', payload, deps.tg, csrfHeader());
      const result = response.data || {};
      if (!response.ok || !result.ok || !result.download_url) {
        deps.showToast(result.error || 'Requisition generation failed.', 'error');
        return;
      }
      deps.openPortalLink(result.download_url);
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
        invoiceResultsSummary.textContent = deps.portalHelpers.invoiceResultsSummary(res);
        invoiceResultsList.innerHTML = deps.portalHelpers.invoiceResultRows(res);
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
