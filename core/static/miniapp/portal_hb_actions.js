(function () {
  'use strict';

  let deps = {};
  let detail = null;
  let options = {};
  let correctionMode = false;
  let activeStatus = '';
  let page = 1;
  let searchTimer = null;

  const byId = id => document.getElementById(id);
  const esc = value => deps.escapeHtml ? deps.escapeHtml(value == null ? '' : String(value)) : String(value || '');
  const statusLabels = {
    needs_planning: 'Needs planning', pending_installation: 'Pending', scheduled: 'Scheduled',
    installed: 'Installed', closed: 'Closed',
  };
  const allowedStatusTargets = {
    needs_planning: ['pending_installation', 'scheduled', 'installed', 'closed'],
    pending_installation: ['pending_installation', 'scheduled', 'installed', 'closed'],
    scheduled: ['scheduled', 'pending_installation', 'installed', 'closed'],
    installed: ['installed'],
    closed: ['closed'],
  };

  function field(id) { return byId(id); }
  function setOptions(select, rows, placeholder) {
    if (!select) return;
    select.innerHTML = (placeholder ? `<option value="">${esc(placeholder)}</option>` : '')
      + (rows || []).map(row => `<option value="${esc(row.value)}">${esc(row.label)}</option>`).join('');
  }

  function statusClass(value) { return `hb-status-${String(value || '').replace(/_/g, '-')}`; }

  async function loadList() {
    const target = byId('hb-action-list');
    if (!target) return;
    target.innerHTML = '<div class="empty-state"><div class="spinner-inline"></div></div>';
    const params = new URLSearchParams({page: String(page)});
    const search = byId('hb-actions-search')?.value.trim() || '';
    if (search) params.set('search', search);
    if (activeStatus) params.set('status', activeStatus);
    const response = await deps.portalApi.apiFetch(`/hb-actions/?${params.toString()}`, {}, deps.tg);
    if (!response.ok || !response.data?.ok) {
      target.innerHTML = `<div class="empty-state"><strong>HB Action could not load</strong><div class="es-sub">${esc(response.data?.error || 'Check your connection and try again.')}</div><button type="button" class="btn btn-secondary" data-hb-retry>Retry</button></div>`;
      target.querySelector('[data-hb-retry]')?.addEventListener('click', loadList);
      return;
    }
    renderCounts(response.data.counts || {});
    const items = response.data.items || [];
    target.innerHTML = items.length ? items.map(item => `
      <a class="hb-action-row" href="${esc(item.detail_url)}" data-hb-action-link>
        <span class="hb-action-row-main"><strong>${esc(item.customer_name || 'Unnamed customer')}</strong><small>${esc([item.case_reference, item.branch, item.product].filter(Boolean).join(' · '))}</small></span>
        <span class="hb-action-row-side"><span class="hb-action-status ${statusClass(item.installation_status)}">${esc(item.installation_status_label)}</span><small>Order ${esc(item.order_number)}</small></span>
        <i data-lucide="chevron-right" aria-hidden="true"></i>
      </a>`).join('') : '<div class="empty-state compact"><strong>No HB work here</strong><div class="es-sub">Cases appear after a signed and stamped order is accepted.</div></div>';
    renderPagination(response.data.page, response.data.pages);
    window.lucide?.createIcons?.();
  }

  function renderCounts(counts) {
    const target = byId('hb-action-counts');
    if (!target) return;
    const rows = [['', 'All', Object.values(counts).reduce((sum, value) => sum + Number(value || 0), 0)], ...Object.keys(statusLabels).map(key => [key, statusLabels[key], counts[key] || 0])];
    target.innerHTML = rows.map(([key, label, count]) => `<button type="button" class="hb-count-pill${activeStatus === key ? ' active' : ''}" data-status="${esc(key)}"><span>${esc(label)}</span><b>${esc(count)}</b></button>`).join('');
    target.querySelectorAll('[data-status]').forEach(button => button.addEventListener('click', () => {
      activeStatus = button.dataset.status || ''; page = 1; loadList();
    }));
  }

  function renderPagination(current, pages) {
    const target = byId('hb-action-pagination');
    if (!target) return;
    target.innerHTML = pages > 1 ? `<button type="button" ${current <= 1 ? 'disabled' : ''} data-page="${current - 1}">Previous</button><span>${current} of ${pages}</span><button type="button" ${current >= pages ? 'disabled' : ''} data-page="${current + 1}">Next</button>` : '';
    target.querySelectorAll('[data-page]').forEach(button => button.addEventListener('click', () => { page = Number(button.dataset.page); loadList(); }));
  }

  function populateDetail(action) {
    detail = action;
    byId('hb-action-detail-title').textContent = action.customer_name || 'Installation record';
    byId('hb-action-detail-meta').textContent = [action.case_reference, action.branch, `Order ${action.order_number}`].filter(Boolean).join(' · ');
    byId('hb-action-summary').innerHTML = `
      <div><span>Status</span><strong class="hb-action-status ${statusClass(action.installation_status)}">${esc(action.installation_status_label)}</strong></div>
      <div><span>Installation</span><strong>${esc(action.installation_date_display || 'Not set')}</strong></div>
      <div><span>Commissioning</span><strong>${esc(action.commissioning_status_label || 'Not started')}</strong></div>`;
    const invoice = byId('hb-action-invoice');
    if (action.invoice) {
      invoice.hidden = false; invoice.href = action.invoice.url;
      byId('hb-action-invoice-copy').textContent = [action.invoice.number, action.invoice.date].filter(Boolean).join(' · ');
    } else invoice.hidden = true;

    const allowed = allowedStatusTargets[action.installation_status] || [];
    const statusOptions = (options.installation_statuses || []).filter(row => allowed.includes(row.value));
    setOptions(field('hb-installation-status'), statusOptions, action.installation_status === 'needs_planning' ? 'Choose status' : '');
    setOptions(field('hb-readiness-status'), options.readiness_statuses, 'Choose readiness');
    setOptions(field('hb-installation-report-status'), options.installation_report_statuses, 'Choose report status');
    setOptions(field('hb-commissioning-status'), options.commissioning_statuses, 'Choose status');
    field('hb-installation-status').value = action.installation_status === 'needs_planning' ? '' : action.installation_status;
    field('hb-readiness-status').value = action.readiness_status || '';
    field('hb-installation-date').value = action.installation_date || '';
    field('hb-pending-installation-comment').value = action.pending_installation_comment || '';
    field('hb-serial-number').value = action.serial_number || '';
    field('hb-installation-report-status').value = action.installation_report_status || '';
    field('hb-commissioning-status').value = action.commissioning_status || '';
    field('hb-commissioning-date').value = action.commissioning_date || '';
    field('hb-pending-commissioning-comment').value = action.pending_commissioning_comment || '';
    field('hb-correction-reason').value = '';
    renderFormState();
    renderHistory(action.history || []);
  }

  function renderFormState() {
    const status = field('hb-installation-status')?.value || '';
    const installed = status === 'installed';
    const pending = ['pending_installation', 'scheduled', 'closed'].includes(status);
    byId('hb-readiness-fields').hidden = !pending;
    byId('hb-pending-installation-wrap').hidden = !pending;
    byId('hb-installed-fields').hidden = !installed;
    byId('hb-commissioning-card').hidden = !installed;
    byId('hb-installation-date-label').textContent = installed ? 'Actual installation date' : 'Scheduled installation date';
    const commissionDone = field('hb-commissioning-status')?.value === 'done';
    byId('hb-commissioning-date-label').textContent = commissionDone ? 'Actual commissioning date' : 'Scheduled commissioning date';
    byId('hb-pending-commissioning-wrap').hidden = !installed || commissionDone;
  }

  function renderHistory(rows) {
    byId('hb-action-history-count').textContent = `(${rows.length})`;
    byId('hb-action-history-list').innerHTML = rows.length ? rows.map(row => `<article><strong>${esc(row.label)}</strong><span>${esc([row.actor, deps.fmtDate ? deps.fmtDate(row.created_at) : row.created_at].filter(Boolean).join(' · '))}</span>${row.reason ? `<p>${esc(row.reason)}</p>` : ''}</article>`).join('') : '<p class="meta">No activity recorded.</p>';
  }

  function payloadFromForm() {
    return {
      revision: detail.revision,
      installation_status: field('hb-installation-status').value,
      readiness_status: field('hb-readiness-status').value,
      installation_date: field('hb-installation-date').value,
      pending_installation_comment: field('hb-pending-installation-comment').value.trim(),
      serial_number: field('hb-serial-number').value.trim(),
      installation_report_status: field('hb-installation-report-status').value,
      commissioning_status: field('hb-commissioning-status').value,
      commissioning_date: field('hb-commissioning-date').value,
      pending_commissioning_comment: field('hb-pending-commissioning-comment').value.trim(),
      reason: field('hb-correction-reason').value.trim(),
    };
  }

  function validate(payload) {
    if (!payload.installation_status) return 'Choose the installation status.';
    if (['pending_installation', 'scheduled'].includes(payload.installation_status)) {
      if (!payload.readiness_status) return 'Choose the customer readiness status.';
      if (payload.installation_status === 'scheduled' && !payload.installation_date) return 'Choose the scheduled installation date.';
      if ((payload.readiness_status !== 'ready' || !payload.installation_date) && !payload.pending_installation_comment) return 'Add a short pending installation comment.';
    }
    if (payload.installation_status === 'closed' && !payload.pending_installation_comment) return 'Add a closure reason.';
    if (payload.installation_status === 'installed') {
      if (!payload.installation_date) return 'Choose the actual installation date.';
      if (!payload.installation_report_status) return 'Choose whether the installation report was submitted.';
      if (!payload.commissioning_status) return 'Choose the commissioning status.';
      if (payload.commissioning_status === 'done' && !payload.commissioning_date) return 'Choose the actual commissioning date.';
      if (payload.commissioning_status === 'pending' && !payload.commissioning_date && !payload.pending_commissioning_comment) return 'Add a commissioning date or pending comment.';
    }
    return '';
  }

  async function save(event) {
    event.preventDefault();
    const payload = payloadFromForm();
    const error = validate(payload);
    if (error) { deps.showToast(error, 'error'); return; }
    const button = byId('hb-action-save');
    deps.setButtonLoading?.(button, true, correctionMode ? 'Saving correction…' : 'Saving…');
    const endpoint = `/hb-actions/${encodeURIComponent(detail.farmer_id)}/${correctionMode ? 'correct' : 'transition'}/`;
    const response = await deps.portalApi.postJson(endpoint, payload, deps.tg);
    deps.setButtonLoading?.(button, false);
    if (!response.ok || !response.data?.ok) { deps.showToast(response.data?.error || 'The record could not be saved.', 'error'); return; }
    correctionMode = false;
    byId('hb-correction-reason-wrap').hidden = true;
    byId('hb-action-save').textContent = 'Save progress';
    populateDetail(response.data.action);
    deps.showToast('HB action saved.', 'success');
  }

  async function loadDetail(farmerId) {
    const response = await deps.portalApi.apiFetch(`/hb-actions/${encodeURIComponent(farmerId)}/`, {}, deps.tg);
    if (!response.ok || !response.data?.ok) {
      byId('hb-action-detail-loading').innerHTML = `<strong>Record unavailable</strong><div class="es-sub">${esc(response.data?.error || 'Check your connection and try again.')}</div>`;
      return;
    }
    options = response.data.options || {};
    byId('hb-action-detail-loading').hidden = true;
    byId('hb-action-detail').hidden = false;
    const toggle = byId('hb-action-edit-toggle');
    toggle.hidden = !response.data.permissions?.correct;
    const form = byId('hb-action-form');
    form.hidden = !response.data.permissions?.write;
    populateDetail(response.data.action);
    window.lucide?.createIcons?.();
  }

  function init(injected) {
    deps = injected || {};
    const root = document.getElementById('portal-screen');
    if (root?.dataset.screen !== 'hb_actions') return;
    const farmerId = root.dataset.hbActionFarmerId || '';
    if (farmerId) {
      byId('hb-action-form')?.addEventListener('submit', save);
      byId('hb-installation-status')?.addEventListener('change', renderFormState);
      byId('hb-commissioning-status')?.addEventListener('change', renderFormState);
      byId('hb-action-edit-toggle')?.addEventListener('click', () => {
        correctionMode = !correctionMode;
        byId('hb-correction-reason-wrap').hidden = !correctionMode;
        byId('hb-action-save').textContent = correctionMode ? 'Save correction' : 'Save progress';
        byId('hb-action-edit-toggle').classList.toggle('active', correctionMode);
      });
      return;
    }
    byId('hb-actions-refresh')?.addEventListener('click', loadList);
    byId('hb-actions-search')?.addEventListener('input', () => {
      window.clearTimeout(searchTimer); searchTimer = window.setTimeout(() => { page = 1; loadList(); }, 250);
    });
  }

  function loadCurrent() {
    const root = document.getElementById('portal-screen');
    const farmerId = root?.dataset.hbActionFarmerId || '';
    return farmerId ? loadDetail(farmerId) : loadList();
  }

  window.PortalMiniAppHbActions = {init, load: loadCurrent};
})();
