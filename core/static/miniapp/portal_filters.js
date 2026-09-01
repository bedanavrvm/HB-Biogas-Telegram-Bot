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
          <div class="farmer-card${qKey === 'requisition' ? ' requisition-card' : ''}${qKey === 'jbl' || qKey === 'my_visits' ? '' : ' operational-farmer-card'}" data-qkey="${qKey}" data-farmer-id="${deps.escapeHtml(farmer.id || '')}" data-idx="${originalIdx}" id="fc-${qKey}-${originalIdx}">
          ${qKey === 'requisition' ? `
            <input type="checkbox" class="farmer-card-checkbox" data-id="${deps.escapeHtml(farmer.id)}" ${state().selectedRequisitions.has(farmer.id) ? 'checked' : ''} onclick="event.stopPropagation();">
          ` : ''}
          ${qKey === 'jbl' || qKey === 'my_visits' ? deps.renderVisitQueueCard(farmer, qKey) : deps.renderOperationalQueueCard(farmer, qKey)}
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
