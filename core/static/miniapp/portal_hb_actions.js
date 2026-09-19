(function () {
  'use strict';

  let deps = {};
  let detail = null;
  let options = {};
  let permissions = {};
  let correctionMode = false;
  let activeQueue = 'installation';
  let activeState = 'open';
  let page = 1;
  let searchTimer = null;
  let invoiceObjectUrl = '';
  const filters = {branch: '', readiness: '', installation_report: '', invoice: '', date_from: '', date_to: '', overdue: false};

  const byId = id => document.getElementById(id);
  const esc = value => deps.escapeHtml ? deps.escapeHtml(value == null ? '' : String(value)) : String(value || '');
  const installationLabels = {open: 'Open', installed: 'Installed', closed: 'Closed'};
  const commissioningLabels = {not_commissioned: 'Not commissioned', commissioned: 'Commissioned'};
  const allowedStatusTargets = {
    open: ['open', 'installed', 'closed'],
    installed: ['installed'], closed: ['closed'],
  };

  function field(id) { return byId(id); }
  function setOptions(select, rows, placeholder) {
    if (!select) return;
    const current = select.value;
    select.innerHTML = (placeholder ? `<option value="">${esc(placeholder)}</option>` : '')
      + (rows || []).map(row => `<option value="${esc(row.value)}">${esc(row.label)}</option>`).join('');
    if ([...select.options].some(option => option.value === current)) select.value = current;
  }
  function statusClass(value) { return `hb-status-${String(value || '').replace(/_/g, '-')}`; }
  function currentWorkstream() {
    const root = byId('portal-screen');
    if (!root?.dataset.hbActionFarmerId) return activeQueue;
    const value = new URLSearchParams(window.location.search).get('workstream') || '';
    return ['installation', 'commissioning'].includes(value) ? value : '';
  }
  function setQueueUrl() {
    const url = new URL(window.location.href);
    url.searchParams.set('queue', activeQueue);
    window.history.replaceState({}, '', url.pathname + url.search);
  }

  function filterCount() {
    return Object.entries(filters).filter(([key, value]) => key !== 'overdue' ? Boolean(value) : value).length;
  }
  function renderFilterSummary() {
    const count = filterCount();
    const badge = byId('hb-action-filter-count');
    if (badge) { badge.hidden = !count; badge.textContent = String(count); }
    const chips = byId('hb-action-filter-chips');
    if (!chips) return;
    const labels = [];
    if (filters.branch) labels.push(filters.branch);
    if (filters.readiness) labels.push(field('hb-filter-readiness')?.selectedOptions[0]?.textContent || filters.readiness);
    if (filters.installation_report) labels.push(field('hb-filter-report')?.selectedOptions[0]?.textContent || filters.installation_report);
    if (filters.invoice) labels.push(filters.invoice === 'present' ? 'Invoice linked' : 'No invoice');
    if (filters.date_from || filters.date_to) labels.push(`${filters.date_from || 'Any date'} – ${filters.date_to || 'Any date'}`);
    if (filters.overdue) labels.push(activeQueue === 'commissioning' ? 'Delayed only' : 'Overdue only');
    chips.innerHTML = labels.map(label => `<span class="miniapp-filter-chip">${esc(label)}</span>`).join('');
  }
  function populateFilterOptions(payload) {
    setOptions(field('hb-filter-branch'), (payload.branches || []).map(value => ({value, label: value})), 'All authorized branches');
    setOptions(field('hb-filter-readiness'), payload.readiness || [], 'All readiness states');
    setOptions(field('hb-filter-report'), payload.installation_reports || [], 'All report states');
  }
  function updateFilterMode() {
    const commissioning = activeQueue === 'commissioning';
    byId('hb-action-filter-title').textContent = commissioning ? 'Filter commissioning' : 'Filter installation';
    byId('hb-filter-readiness-wrap').hidden = commissioning;
    byId('hb-filter-report-wrap').hidden = commissioning;
    byId('hb-filter-date-from-label').textContent = commissioning ? 'Ready date from' : 'Planned date from';
    byId('hb-filter-date-to-label').textContent = commissioning ? 'Ready date to' : 'Planned date to';
    byId('hb-filter-overdue-label').textContent = commissioning ? 'Delayed only' : 'Planned date passed';
  }
  function openFilters() {
    updateFilterMode();
    const overlay = byId('hb-action-filter-overlay');
    overlay.hidden = false; overlay.classList.add('open'); overlay.setAttribute('aria-hidden', 'false');
  }
  function closeFilters() {
    const overlay = byId('hb-action-filter-overlay');
    overlay?.classList.remove('open'); overlay?.setAttribute('aria-hidden', 'true');
    if (overlay) overlay.hidden = true;
  }
  function readFilters() {
    filters.branch = field('hb-filter-branch').value;
    filters.readiness = activeQueue === 'installation' ? field('hb-filter-readiness').value : '';
    filters.installation_report = activeQueue === 'installation' ? field('hb-filter-report').value : '';
    filters.invoice = field('hb-filter-invoice').value;
    filters.date_from = field('hb-filter-date-from').value;
    filters.date_to = field('hb-filter-date-to').value;
    filters.overdue = field('hb-filter-overdue').checked;
  }
  function clearFilters() {
    Object.assign(filters, {branch: '', readiness: '', installation_report: '', invoice: '', date_from: '', date_to: '', overdue: false});
    ['hb-filter-branch', 'hb-filter-readiness', 'hb-filter-report', 'hb-filter-invoice', 'hb-filter-date-from', 'hb-filter-date-to'].forEach(id => { if (field(id)) field(id).value = ''; });
    if (field('hb-filter-overdue')) field('hb-filter-overdue').checked = false;
    page = 1; renderFilterSummary(); loadList();
  }

  function countdownText(item) {
    if (item.commissioning_state === 'done') return item.commissioning_date_display ? `Commissioned ${item.commissioning_date_display}` : 'Commissioned';
    if (item.commissioning_state === 'waiting') {
      if (Number(item.days_until_ready) === 1) return 'Ready tomorrow';
      return `Ready in ${Number(item.days_until_ready || 0)} days`;
    }
    if (item.commissioning_state === 'due_today') return 'Due today';
    if (item.commissioning_state === 'delayed') return `Delayed by ${Number(item.commissioning_overdue_days || 0)} day${Number(item.commissioning_overdue_days || 0) === 1 ? '' : 's'}`;
    return 'Waiting for installation';
  }

  function installationSecondary(item) {
    if (item.installation_status === 'installed') return item.installation_date_display ? `Installed ${item.installation_date_display}` : 'Installed';
    if (item.installation_status === 'closed') return 'Closed';
    if (item.planned_installation_date_display) return `Planned ${item.planned_installation_date_display}`;
    if (item.readiness_status_label) return item.readiness_status_label;
    return 'Needs an installation update';
  }

  async function loadList() {
    const target = byId('hb-action-list');
    if (!target) return;
    target.innerHTML = '<div class="empty-state"><div class="spinner-inline"></div></div>';
    const params = new URLSearchParams({page: String(page), queue: activeQueue, state: activeState});
    const search = byId('hb-actions-search')?.value.trim() || '';
    if (search) params.set('search', search);
    Object.entries(filters).forEach(([key, value]) => { if (value) params.set(key, value === true ? '1' : String(value)); });
    const response = await deps.portalApi.apiFetch(`/hb-actions/?${params.toString()}`, {}, deps.tg);
    if (!response.ok || !response.data?.ok) {
      target.innerHTML = `<div class="empty-state"><strong>HB Action could not load</strong><div class="es-sub">${esc(response.data?.error || 'Check your connection and try again.')}</div><button type="button" class="btn btn-secondary" data-hb-retry>Retry</button></div>`;
      target.querySelector('[data-hb-retry]')?.addEventListener('click', loadList);
      return;
    }
    populateFilterOptions(response.data.filters || {});
    renderCounts(response.data.counts || {});
    renderFilterSummary();
    const items = response.data.items || [];
    target.innerHTML = items.length ? items.map(item => {
      const state = activeQueue === 'commissioning' ? item.commissioning_status : item.installation_status;
      const label = activeQueue === 'commissioning' ? item.commissioning_status_label : item.installation_status_label;
      const secondary = activeQueue === 'commissioning' ? countdownText(item) : installationSecondary(item);
      return `<a class="hb-action-row" href="${esc(item.detail_url)}" data-hb-action-link>
        <span class="hb-action-row-main"><strong>${esc(item.customer_name || 'Unnamed customer')}</strong><small>${esc([item.case_reference, item.branch].filter(Boolean).join(' · '))}</small></span>
        <span class="hb-action-row-side"><span class="hb-action-status ${statusClass(state)}">${esc(label)}</span><small>${esc(secondary)}</small></span>
        <i data-lucide="chevron-right" aria-hidden="true"></i>
      </a>`;
    }).join('') : `<div class="empty-state compact"><strong>No ${esc(activeQueue)} work here</strong><div class="es-sub">${activeQueue === 'installation' ? 'Cases appear after a signed and stamped order is accepted.' : 'Cases appear here after installation is completed.'}</div></div>`;
    renderPagination(response.data.page, response.data.pages);
    window.lucide?.createIcons?.();
  }

  function renderCounts(counts) {
    const target = byId('hb-action-counts');
    if (!target) return;
    const labels = activeQueue === 'commissioning' ? commissioningLabels : installationLabels;
    target.setAttribute('aria-label', `${activeQueue} status filters`);
    target.innerHTML = Object.keys(labels).map(key => `<button type="button" class="hb-count-pill${activeState === key ? ' active' : ''}" data-state="${esc(key)}"><span>${esc(labels[key])}</span><b>${esc(counts[key] || 0)}</b></button>`).join('');
    target.querySelectorAll('[data-state]').forEach(button => button.addEventListener('click', () => { activeState = button.dataset.state || 'open'; page = 1; loadList(); }));
  }
  function renderPagination(current, pages) {
    const target = byId('hb-action-pagination');
    if (!target) return;
    target.innerHTML = pages > 1 ? `<button type="button" ${current <= 1 ? 'disabled' : ''} data-page="${current - 1}">Previous</button><span>${current} of ${pages}</span><button type="button" ${current >= pages ? 'disabled' : ''} data-page="${current + 1}">Next</button>` : '';
    target.querySelectorAll('[data-page]').forEach(button => button.addEventListener('click', () => { page = Number(button.dataset.page); loadList(); }));
  }
  function setQueue(queue) {
    activeQueue = queue; activeState = queue === 'commissioning' ? 'not_commissioned' : 'open'; page = 1;
    document.querySelectorAll('[data-hb-queue]').forEach(button => {
      const active = button.dataset.hbQueue === queue;
      button.classList.toggle('active', active); button.setAttribute('aria-selected', String(active));
    });
    updateFilterMode(); setQueueUrl(); loadList();
  }

  function renderReadiness(action) {
    const target = byId('hb-commissioning-readiness');
    if (!target) return;
    target.className = `hb-commissioning-readiness ${statusClass(action.commissioning_state)}`;
    target.innerHTML = `<span>${esc(action.commissioning_state_label || 'Commissioning')}</span><strong>${esc(countdownText(action))}</strong><small>Standard readiness date: ${esc(action.commissioning_ready_on_display || 'Not available')}</small>`;
  }
  function populateDetail(action) {
    detail = action;
    const workstream = action.workstream || currentWorkstream() || (action.installation_status === 'installed' ? 'commissioning' : 'installation');
    byId('hb-action-detail-title').textContent = workstream === 'commissioning' ? 'Commissioning record' : 'Installation record';
    byId('hb-action-detail-meta').textContent = [action.customer_name, action.case_reference, action.branch, `Order ${action.order_number}`].filter(Boolean).join(' · ');
    byId('hb-action-back').href = `/portal/s/hb-actions/?queue=${encodeURIComponent(workstream)}`;
    byId('hb-action-summary').innerHTML = workstream === 'commissioning' ? `
      <div><span>Installed</span><strong>${esc(action.installation_date_display || 'Not set')}</strong></div>
      <div><span>Ready date</span><strong>${esc(action.commissioning_ready_on_display || 'Not set')}</strong></div>
      <div><span>Commissioning</span><strong class="hb-action-status ${statusClass(action.commissioning_status)}">${esc(action.commissioning_status_label || 'Not commissioned')}</strong></div>` : `
      <div><span>Status</span><strong class="hb-action-status ${statusClass(action.installation_status)}">${esc(action.installation_status_label)}</strong></div>
      <div><span>Planned</span><strong>${esc(action.planned_installation_date_display || 'Not set')}</strong></div>
      <div><span>Order</span><strong>${esc(action.order_number || '-')}</strong></div>`;
    const invoice = byId('hb-action-invoice');
    if (action.invoice) {
      invoice.hidden = false; invoice.href = action.invoice.url; invoice.dataset.mode = action.invoice.mode;
      byId('hb-action-invoice-label').textContent = action.invoice.label || 'Invoice';
      byId('hb-action-invoice-copy').textContent = [action.invoice.number, action.invoice.date].filter(Boolean).join(' · ');
    } else { invoice.hidden = true; invoice.removeAttribute('data-mode'); }

    const allowed = allowedStatusTargets[action.installation_status] || [];
    const statusOptions = (options.installation_statuses || []).filter(row => allowed.includes(row.value));
    setOptions(field('hb-installation-status'), statusOptions, '');
    setOptions(field('hb-readiness-status'), options.readiness_statuses, 'Choose readiness');
    setOptions(field('hb-installation-report-status'), options.installation_report_statuses, 'Choose report status');
    field('hb-installation-status').value = action.installation_status || 'open';
    field('hb-readiness-status').value = action.readiness_status || '';
    field('hb-planned-installation-date').value = action.planned_installation_date || '';
    field('hb-installation-date').value = action.installation_date || '';
    field('hb-installation-note').value = action.installation_note || '';
    field('hb-serial-number').value = action.serial_number || '';
    field('hb-installation-report-status').value = action.installation_report_status || '';
    field('hb-commissioning-date').value = action.commissioning_status === 'commissioned' ? (action.commissioning_date || '') : '';
    field('hb-correction-reason').value = '';
    byId('hb-installation-card').hidden = workstream !== 'installation';
    byId('hb-commissioning-card').hidden = workstream !== 'commissioning';
    byId('hb-action-save').textContent = workstream === 'commissioning' ? 'Mark commissioned' : 'Save installation';
    renderReadiness(action); renderFormState(); renderHistory(action.history || []); applyReadOnlyState();
  }
  function renderFormState() {
    const status = field('hb-installation-status')?.value || '';
    const installed = status === 'installed';
    byId('hb-open-installation-fields').hidden = installed || status === 'closed';
    byId('hb-installation-note-wrap').hidden = installed;
    byId('hb-installed-fields').hidden = !installed;
  }
  function applyReadOnlyState() {
    const form = byId('hb-action-form');
    const completedMilestone = (
      (detail?.workstream === 'installation' && ['installed', 'closed'].includes(detail?.installation_status))
      || (detail?.workstream === 'commissioning' && detail?.commissioning_status === 'commissioned')
    );
    const editable = Boolean(permissions.write) && (!completedMilestone || correctionMode);
    form.querySelectorAll('input,select,textarea').forEach(control => { if (control.id !== 'hb-correction-reason') control.disabled = !editable; });
    byId('hb-action-save').hidden = !editable;
    byId('hb-action-edit-toggle').hidden = !permissions.correct || !completedMilestone;
  }
  function renderHistory(rows) {
    byId('hb-action-history-count').textContent = `(${rows.length})`;
    byId('hb-action-history-list').innerHTML = rows.length ? rows.map(row => `<article><strong>${esc(row.label)}</strong><span>${esc([row.actor, deps.fmtDate ? deps.fmtDate(row.created_at) : row.created_at].filter(Boolean).join(' · '))}</span>${row.reason ? `<p>${esc(row.reason)}</p>` : ''}</article>`).join('') : '<p class="meta">No activity recorded.</p>';
  }

  function payloadFromForm() {
    const workstream = detail.workstream || currentWorkstream();
    if (workstream === 'commissioning') return {revision: detail.revision, workstream, commissioning_status: 'commissioned', commissioning_date: field('hb-commissioning-date').value, reason: field('hb-correction-reason').value.trim()};
    return {
      revision: detail.revision, workstream: 'installation', installation_status: field('hb-installation-status').value,
      readiness_status: field('hb-readiness-status').value, planned_installation_date: field('hb-planned-installation-date').value,
      installation_date: field('hb-installation-date').value, installation_note: field('hb-installation-note').value.trim(), serial_number: field('hb-serial-number').value.trim(),
      installation_report_status: field('hb-installation-report-status').value, reason: field('hb-correction-reason').value.trim(),
    };
  }
  function validate(payload) {
    const today = deps.state?.businessDate || new Date().toISOString().slice(0, 10);
    if (payload.workstream === 'commissioning') {
      if (!payload.commissioning_date) return 'Choose the actual commissioning date.';
      if (payload.commissioning_date > today) return 'The actual commissioning date cannot be in the future.';
      return '';
    }
    if (!payload.installation_status) return 'Choose the installation status.';
    if (payload.installation_status === 'open' && payload.readiness_status === 'not_ready' && !payload.installation_note) return 'Add a short installation note for a known readiness blocker.';
    if (payload.installation_status === 'closed' && !payload.installation_note) return 'Add a closure reason.';
    if (payload.installation_status === 'installed') {
      if (!payload.installation_date) return 'Choose the actual installation date.';
      if (payload.installation_date > today) return 'The actual installation date cannot be in the future.';
      if (!payload.installation_report_status) return 'Choose whether the installation report was submitted.';
    }
    return '';
  }
  function dateDifferenceDays(later, earlier) { return Math.round((Date.parse(`${later}T00:00:00Z`) - Date.parse(`${earlier}T00:00:00Z`)) / 86400000); }
  function addDays(value, days) { const date = new Date(`${value}T00:00:00Z`); date.setUTCDate(date.getUTCDate() + days); return date.toISOString().slice(0, 10); }
  function confirmEarly(message) {
    return new Promise(resolve => { if (deps.tg?.showConfirm) deps.tg.showConfirm(message, resolve); else resolve(window.confirm(message)); });
  }
  async function save(event) {
    event.preventDefault();
    const payload = payloadFromForm(); const error = validate(payload);
    if (error) { deps.showToast(error, 'error'); return; }
    if (payload.workstream === 'commissioning' && detail.commissioning_ready_on && payload.commissioning_date < detail.commissioning_ready_on) {
      const days = dateDifferenceDays(detail.commissioning_ready_on, payload.commissioning_date);
      const confirmed = await confirmEarly(`This commissioning date is ${days} day${days === 1 ? '' : 's'} before the standard 21-day readiness date. Continue?`);
      if (!confirmed) return;
      payload.early_commissioning_acknowledged = true;
    }
    if (payload.workstream === 'installation' && correctionMode && detail.commissioning_status === 'commissioned' && detail.commissioning_date && payload.installation_date) {
      const correctedReadyOn = addDays(payload.installation_date, 21);
      if (detail.commissioning_date < correctedReadyOn) {
        const days = dateDifferenceDays(correctedReadyOn, detail.commissioning_date);
        const confirmed = await confirmEarly(`The corrected installation date makes commissioning ${days} day${days === 1 ? '' : 's'} earlier than the standard readiness date. Continue?`);
        if (!confirmed) return;
        payload.early_commissioning_acknowledged = true;
      }
    }
    const button = byId('hb-action-save');
    deps.setButtonLoading?.(button, true, correctionMode ? 'Saving correction…' : 'Saving…');
    const endpoint = `/hb-actions/${encodeURIComponent(detail.farmer_id)}/${correctionMode ? 'correct' : 'transition'}/`;
    const response = await deps.portalApi.postJson(endpoint, payload, deps.tg);
    deps.setButtonLoading?.(button, false);
    if (!response.ok || !response.data?.ok) { deps.showToast(response.data?.error || 'The record could not be saved.', 'error'); return; }
    correctionMode = false; byId('hb-correction-reason-wrap').hidden = true;
    if (payload.workstream === 'installation' && response.data.action.installation_status === 'installed') {
      deps.showToast('Installation saved. The case is now in the commissioning queue.', 'success');
      window.location.assign(`/portal/s/hb-actions/${encodeURIComponent(detail.farmer_id)}/?workstream=commissioning`); return;
    }
    populateDetail(response.data.action);
    deps.showToast(payload.workstream === 'commissioning' ? 'Commissioning recorded.' : 'Installation saved.', 'success');
  }

  function closeInvoicePreview() {
    if (invoiceObjectUrl) { window.SecureMediaViewer?.revoke(invoiceObjectUrl); invoiceObjectUrl = ''; }
    byId('media-viewer-overlay')?.classList.remove('open');
    const content = byId('media-viewer-content'); if (content) content.replaceChildren();
  }
  async function openInvoicePreview(event) {
    const anchor = event.currentTarget;
    if (anchor.dataset.mode !== 'preview') return;
    event.preventDefault();
    const overlay = byId('media-viewer-overlay'); const content = byId('media-viewer-content');
    if (!overlay || !content || !window.SecureMediaViewer) return deps.showToast('The secure invoice viewer is unavailable. Refresh and retry.', 'error');
    closeInvoicePreview();
    byId('media-viewer-title').textContent = 'Invoice sent';
    byId('media-viewer-sub').textContent = [detail?.invoice?.number, detail?.invoice?.date].filter(Boolean).join(' · ');
    content.innerHTML = '<div class="media-viewer-loading" role="status"><span class="spinner-inline" aria-hidden="true"></span> Loading invoice…</div>';
    overlay.classList.add('open');
    try {
      const blob = await window.SecureMediaViewer.fetchAuthorizedBlob(anchor.href, {headers: {'X-Request-ID': window.crypto?.randomUUID?.() || `hb-invoice-${Date.now()}`}});
      invoiceObjectUrl = window.SecureMediaViewer.renderBlob(content, blob, {mimeType: 'text/html', name: 'Invoice preview'});
    } catch (error) { content.innerHTML = `<p class="media-viewer-error">${esc(error.message || 'The invoice could not be opened in the Mini App.')}</p>`; }
  }

  async function loadDetail(farmerId) {
    const requested = currentWorkstream(); const suffix = requested ? `?workstream=${encodeURIComponent(requested)}` : '';
    const response = await deps.portalApi.apiFetch(`/hb-actions/${encodeURIComponent(farmerId)}/${suffix}`, {}, deps.tg);
    if (!response.ok || !response.data?.ok) {
      byId('hb-action-detail-loading').innerHTML = `<strong>Record unavailable</strong><div class="es-sub">${esc(response.data?.error || 'Check your connection and try again.')}</div>`; return;
    }
    options = response.data.options || {}; permissions = response.data.permissions || {};
    byId('hb-action-detail-loading').hidden = true; byId('hb-action-detail').hidden = false;
    populateDetail(response.data.action); window.lucide?.createIcons?.();
  }
  function init(injected) {
    deps = injected || {};
    const root = byId('portal-screen'); if (root?.dataset.screen !== 'hb_actions') return;
    const farmerId = root.dataset.hbActionFarmerId || '';
    if (farmerId) {
      byId('hb-action-form')?.addEventListener('submit', save);
      byId('hb-installation-status')?.addEventListener('change', renderFormState);
      byId('hb-action-invoice')?.addEventListener('click', openInvoicePreview);
      byId('media-viewer-close')?.addEventListener('click', closeInvoicePreview);
      byId('hb-action-edit-toggle')?.addEventListener('click', () => {
        correctionMode = !correctionMode; byId('hb-correction-reason-wrap').hidden = !correctionMode;
        byId('hb-action-save').textContent = correctionMode ? 'Save correction' : (detail?.workstream === 'commissioning' ? 'Mark commissioned' : 'Save installation');
        byId('hb-action-edit-toggle').classList.toggle('active', correctionMode); applyReadOnlyState();
      });
      window.addEventListener('beforeunload', closeInvoicePreview); return;
    }
    const requestedQueue = new URLSearchParams(window.location.search).get('queue');
    activeQueue = ['installation', 'commissioning'].includes(requestedQueue) ? requestedQueue : 'installation';
    activeState = activeQueue === 'commissioning' ? 'not_commissioned' : 'open';
    document.querySelectorAll('[data-hb-queue]').forEach(button => button.addEventListener('click', () => setQueue(button.dataset.hbQueue)));
    document.querySelectorAll('[data-hb-queue]').forEach(button => { const active = button.dataset.hbQueue === activeQueue; button.classList.toggle('active', active); button.setAttribute('aria-selected', String(active)); });
    byId('hb-actions-refresh')?.addEventListener('click', loadList);
    byId('hb-actions-search')?.addEventListener('input', () => { window.clearTimeout(searchTimer); searchTimer = window.setTimeout(() => { page = 1; loadList(); }, 250); });
    byId('hb-action-filter-trigger')?.addEventListener('click', openFilters);
    byId('hb-action-filter-close')?.addEventListener('click', closeFilters);
    byId('hb-action-filter-overlay')?.addEventListener('click', event => { if (event.target === event.currentTarget) closeFilters(); });
    byId('hb-action-filter-form')?.addEventListener('submit', event => { event.preventDefault(); readFilters(); page = 1; closeFilters(); renderFilterSummary(); loadList(); });
    byId('hb-action-filter-reset')?.addEventListener('click', clearFilters);
    updateFilterMode();
  }
  function loadCurrent() { const farmerId = byId('portal-screen')?.dataset.hbActionFarmerId || ''; return farmerId ? loadDetail(farmerId) : loadList(); }

  window.PortalMiniAppHbActions = {init, load: loadCurrent};
})();
