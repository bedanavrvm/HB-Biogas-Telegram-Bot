(function () {
  'use strict';

  let deps = null;

  function el(id) { return deps.el(id); }
  function state() { return deps.state; }

  function updateFilterOptions(farmers) {
    const countySelect = el('filter-county');
    const branchSelect = el('filter-branch');
    if (!countySelect || !branchSelect) return;

    const currentCounty = state().filters.county;
    const currentBranch = state().filters.branch;
    const counties = new Set(state().metaCounties || []);
    const branches = new Set(state().metaBranches || []);

    (farmers || []).forEach(farmer => {
      const county = String(farmer.county || '').trim();
      const branch = String(farmer.branch || '').trim();
      if (county && !counties.size) counties.add(county);
      if ((!currentCounty || county === currentCounty) && branch && !branches.size) branches.add(branch);
    });

    countySelect.innerHTML = '<option value="">All Counties</option>' +
      Array.from(counties).sort().map(county => (
        `<option value="${deps.escapeHtml(county)}"${county === currentCounty ? ' selected' : ''}>${deps.escapeHtml(county)}</option>`
      )).join('');

    branchSelect.innerHTML = '<option value="">All Branches</option>' +
      Array.from(branches).sort().map(branch => (
        `<option value="${deps.escapeHtml(branch)}"${branch === currentBranch ? ' selected' : ''}>${deps.escapeHtml(branch)}</option>`
      )).join('');

    const clearBtn = el('btn-clear-filters');
    if (clearBtn) clearBtn.style.display = (currentCounty || currentBranch) ? 'inline-flex' : 'none';
  }

  function applyFilters() {
    const qKey = state().activePage;
    const cfg = deps.queueConfig[qKey];
    if (!cfg) return;

    const originalFarmers = state().queues[qKey] || [];
    const filteredFarmers = originalFarmers.filter(farmer => {
      const county = String(farmer.county || '').trim();
      const branch = String(farmer.branch || '').trim();
      const matchCounty = !state().filters.county || county === state().filters.county;
      const matchBranch = !state().filters.branch || branch === state().filters.branch;
      return matchCounty && matchBranch;
    });

    renderFilteredFarmerList(el(cfg.listId), filteredFarmers, cfg, qKey);
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
            ${qKey === 'jbl' && farmer.sign_date ? `<div class="fc-sub fc-visit-date">HB visit: ${deps.escapeHtml(deps.fmtDate(farmer.sign_date))}</div>` : ''}
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

  async function refreshFilteredQueue(qKey) {
    if (qKey === 'all') {
      deps.loadQueue('all', 1);
      return;
    }
    if (deps.queueConfig[qKey]?.fragmentEndpoint && window.htmx) {
      updateFilterOptions(state().queues[qKey] || []);
      if (!(await deps.renderQueueFragment(qKey, 1))) applyFilters();
      return;
    }
    updateFilterOptions(state().queues[qKey] || []);
    applyFilters();
  }

  function bindEvents() {
    el('final-review-stage')?.addEventListener('change', async event => {
      state().filters.reviewStage = event.target.value || 'decision';
      // Fetch the selected lens again so the non-HTMX fallback and the
      // fragment path both replace the cached decision queue.
      await deps.loadQueue('final', 1);
    });

    el('filter-county')?.addEventListener('change', async event => {
      state().filters.county = event.target.value;
      state().filters.branch = '';
      await refreshFilteredQueue(state().activePage);
    });

    el('filter-branch')?.addEventListener('change', async event => {
      state().filters.branch = event.target.value;
      await refreshFilteredQueue(state().activePage);
    });

    el('btn-clear-filters')?.addEventListener('click', async () => {
      state().filters.county = '';
      state().filters.branch = '';
      await refreshFilteredQueue(state().activePage);
    });
  }

  function init(initialDeps) {
    deps = initialDeps;
    bindEvents();
  }

  window.PortalMiniAppFilters = {
    init,
    updateFilterOptions,
    applyFilters,
    renderFilteredFarmerList,
  };
})();
