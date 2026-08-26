(function () {
  'use strict';

  let deps = null;

  function el(id) { return deps.el(id); }
  function state() { return deps.state; }

  function updateFilterOptions() {}

  function applyFilters() {
    const qKey = state().activePage;
    const cfg = deps.queueConfig[qKey];
    if (!cfg) return;

    renderFilteredFarmerList(el(cfg.listId), state().queues[qKey] || [], cfg, qKey);
  }

  function renderFilteredFarmerList(listEl, farmers, cfg, qKey) {
    if (!listEl) return;
    if (!farmers.length) {
      listEl.innerHTML = `<div class="empty-state queue-empty-state"><div class="es-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="m5 12 4.2 4.2L19 6.5"/></svg></div><div class="es-title">${deps.escapeHtml(cfg.emptyTitle)}</div><div class="es-sub">No matching records found for the selected filters.</div></div>`;
      return;
    }

    listEl.innerHTML = farmers.map(farmer => {
      const originalIdx = state().queues[qKey].indexOf(farmer);
      return `
          <div class="farmer-card${qKey === 'requisition' ? ' requisition-card' : ''}" data-qkey="${qKey}" data-farmer-id="${deps.escapeHtml(farmer.id || '')}" data-idx="${originalIdx}" id="fc-${qKey}-${originalIdx}">
          ${qKey === 'requisition' ? `
            <input type="checkbox" class="farmer-card-checkbox" data-id="${deps.escapeHtml(farmer.id)}" ${state().selectedRequisitions.has(farmer.id) ? 'checked' : ''} onclick="event.stopPropagation();">
          ` : ''}
          <div style="flex: 1;">
            <div class="fc-name">${deps.escapeHtml(farmer.customer_name || farmer.national_id || farmer.primary_phone || 'Unknown')}</div>
            <div class="fc-sub">${deps.escapeHtml(deps.locationText(farmer))}</div>
            <div class="fc-sub">${deps.escapeHtml(farmer.primary_phone || '')}</div>
            ${qKey === 'jbl' && farmer.hbg_visit_date ? `<div class="fc-sub fc-visit-date">HB visit: ${deps.escapeHtml(farmer.hbg_visit_date_label || deps.fmtDate(farmer.hbg_visit_date))}</div>` : ''}
            ${qKey === 'my_visits' && farmer.jbl_visit_date ? `<div class="fc-sub fc-visit-date">JBL visit: ${deps.escapeHtml(farmer.jbl_visit_date_label || deps.fmtDate(farmer.jbl_visit_date))}</div>` : ''}
            <div class="fc-badges">
              ${farmer.reappraisal_required ? `<span class="badge badge-red">Reappraisal required since ${deps.escapeHtml(farmer.deferred_until || '')}</span>` : ''}
              ${farmer.unit_number ? `<span class="badge badge-grey">Unit ${deps.escapeHtml(farmer.unit_number)}</span>` : ''}
              ${deps.stageBadge(farmer)}
              ${deps.jblBadge(farmer)}
              ${deps.creditBadge(farmer)}
              ${state().filters.reviewStage === 'payment' && farmer.payment_review_document_id ? `<span class="badge badge-orange">Payment #${deps.escapeHtml(farmer.payment_review_payment_number || '-')} awaiting HOR review</span><span class="badge badge-grey">Order ${deps.escapeHtml(farmer.payment_review_order_number || '-')}</span><button type="button" class="btn btn-secondary btn-open-payment-review" data-payment-document-id="${deps.escapeHtml(farmer.payment_review_document_id)}">Open payment review</button>` : ''}
              ${farmer.order_number ? `<span class="badge badge-green">Order: ${deps.escapeHtml(farmer.order_number)}</span>` : ''}
            </div>
          </div>
        </div>
      `;
    }).join('');

    listEl.querySelectorAll('.farmer-card').forEach(card => {
      card.addEventListener('click', () => {
        const key = card.dataset.qkey;
        const farmerId = card.dataset.farmerId;
        const farmer = (state().queues[key] || []).find(item => String(item.id) === String(farmerId)) || { id: farmerId };
        const mode = qKey === 'final'
          ? (state().filters.reviewStage === 'requisition' ? 'requisition' : state().filters.reviewStage === 'payment' ? null : cfg.mode)
          : cfg.mode;
        deps.openCurrentFarmerSheet(farmer, mode);
      });
    });
    listEl.querySelectorAll('.btn-open-payment-review').forEach(button => {
      button.addEventListener('click', event => {
        event.preventDefault();
        event.stopPropagation();
        deps.openPaymentReviewDocument(button.dataset.paymentDocumentId);
      });
    });

    if (qKey === 'requisition') {
      listEl.querySelectorAll('.farmer-card-checkbox').forEach(checkbox => {
        checkbox.addEventListener('change', () => {
          const id = checkbox.dataset.id;
          if (checkbox.checked) state().selectedRequisitions.add(id);
          else state().selectedRequisitions.delete(id);
          deps.updateBatchPanel();
        });
      });
    }
  }

  function init(initialDeps) {
    deps = initialDeps;
  }

  window.PortalMiniAppFilters = {
    init,
    updateFilterOptions,
    applyFilters,
    renderFilteredFarmerList,
  };
})();
