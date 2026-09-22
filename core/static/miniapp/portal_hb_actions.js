(function () {
  'use strict';

  let deps = {};
  let detail = null;
  let options = {};
  let permissions = {};
  let correctionMode = false;
  let installationCompletionMode = false;
  let installationDelayMode = false;
  let activeQueue = 'installation';
  let activeState = 'open';
  let page = 1;
  let searchTimer = null;
  let invoiceObjectUrl = '';

  const byId = id => document.getElementById(id);
  const esc = value => deps.escapeHtml ? deps.escapeHtml(value == null ? '' : String(value)) : String(value || '');
  const installationLabels = {open: 'Not installed', installed: 'Installed'};
  const commissioningLabels = {not_commissioned: 'Not commissioned', delayed: 'Delayed', commissioned: 'Commissioned'};

  function field(id) { return byId(id); }
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
    return 'Awaiting installation';
  }

  async function loadList() {
    const target = byId('hb-action-list');
    if (!target) return;
    target.innerHTML = '<div class="empty-state"><div class="spinner-inline"></div></div>';
    const params = new URLSearchParams({page: String(page), queue: activeQueue, state: activeState});
    const search = byId('hb-actions-search')?.value.trim() || '';
    if (search) params.set('search', search);
    const response = await deps.portalApi.apiFetch(`/hb-actions/?${params.toString()}`, {}, deps.tg);
    if (!response.ok || !response.data?.ok) {
      target.innerHTML = `<div class="empty-state"><strong>HB Action could not load</strong><div class="es-sub">${esc(response.data?.error || 'Check your connection and try again.')}</div><button type="button" class="btn btn-secondary" data-hb-retry>Retry</button></div>`;
      target.querySelector('[data-hb-retry]')?.addEventListener('click', loadList);
      return;
    }
    renderCounts(response.data.counts || {});
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
    setQueueUrl(); loadList();
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

    if (workstream === 'installation') {
      installationCompletionMode = action.installation_status === 'installed';
      installationDelayMode = false;
      field('hb-installation-date').value = action.installation_date || '';
      field('hb-installation-note').value = action.installation_note || '';
      field('hb-serial-number').value = action.serial_number || '';
      field('hb-installation-report-submitted').checked = action.installation_report_status === 'yes';
      renderInstallationForm();
    } else {
      field('hb-commissioning-date').value = action.commissioning_status === 'commissioned' ? (action.commissioning_date || '') : '';
      field('hb-pending-commissioning-comment').value = action.pending_commissioning_comment || '';
      field('hb-additional-remarks').value = action.additional_remarks || '';
      renderReadiness(action);
    }
    const legacyClosed = action.installation_status === 'closed';
    byId('hb-action-form').hidden = legacyClosed;
    if (workstream === 'commissioning') byId('hb-action-save').textContent = 'Mark commissioned';
    renderHistory(action.history || []); applyReadOnlyState();
  }
  function renderInstallationForm() {
    if (detail?.workstream !== 'installation') return;
    const completionFieldsVisible = detail.installation_status === 'installed' || installationCompletionMode;
    const delayFieldsVisible = detail.installation_status === 'open' && installationDelayMode;
    const openState = byId('hb-installation-open-state');
    const installedFields = byId('hb-installed-fields');
    const delayFields = byId('hb-installation-delay-fields');
    if (openState) openState.hidden = completionFieldsVisible || delayFieldsVisible;
    if (installedFields) installedFields.hidden = !completionFieldsVisible;
    if (delayFields) delayFields.hidden = !delayFieldsVisible;
    byId('hb-action-save').textContent = delayFieldsVisible
      ? 'Save delay update'
      : (correctionMode && detail.installation_status === 'installed' ? 'Save installation correction' : 'Save installation');
  }
  function applyReadOnlyState() {
    const form = byId('hb-action-form');
    if (!form) return;
    const completedMilestone = (
      (detail?.workstream === 'installation' && ['installed', 'closed'].includes(detail?.installation_status))
      || (detail?.workstream === 'commissioning' && detail?.commissioning_status === 'commissioned')
    );
    const editable = Boolean(permissions.write) && (!completedMilestone || correctionMode);
    form.querySelectorAll('input,select,textarea').forEach(control => {
      if (!control.closest('#hb-commissioning-notes')) control.disabled = !editable;
    });
    const needsInstallationAction = detail?.workstream === 'installation'
      && detail?.installation_status === 'open' && !installationCompletionMode && !installationDelayMode;
    const saveWrap = byId('hb-action-save-wrap');
    if (saveWrap) saveWrap.hidden = !editable || needsInstallationAction;
    const notes = byId('hb-commissioning-notes');
    const pendingNote = byId('hb-pending-commissioning-note-wrap');
    const notesButton = byId('hb-save-commissioning-notes');
    if (notes) notes.hidden = detail?.workstream !== 'commissioning';
    if (pendingNote) pendingNote.hidden = detail?.commissioning_status === 'commissioned';
    if (notesButton) notesButton.disabled = !permissions.write;
    [field('hb-pending-commissioning-comment'), field('hb-additional-remarks')].forEach(control => {
      if (control) control.disabled = !permissions.write;
    });
    const markInstalled = byId('hb-mark-installed');
    if (markInstalled) {
      markInstalled.hidden = detail?.workstream !== 'installation' || detail?.installation_status !== 'open' || installationCompletionMode || installationDelayMode;
      markInstalled.disabled = !permissions.write;
    }
    const reportDelay = byId('hb-report-installation-delay');
    if (reportDelay) {
      reportDelay.hidden = detail?.workstream !== 'installation' || detail?.installation_status !== 'open' || installationDelayMode || installationCompletionMode;
      reportDelay.disabled = !permissions.write;
    }
    const editToggle = byId('hb-action-edit-toggle');
    if (editToggle) editToggle.hidden = !permissions.correct || !completedMilestone || detail?.installation_status === 'closed';
  }

  function applyVisualDetailHierarchy(action) {
    const workstream = action.workstream || currentWorkstream() || (action.installation_status === 'installed' ? 'commissioning' : 'installation');
    byId('hb-action-detail-title').textContent = action.customer_name || (workstream === 'commissioning' ? 'Commissioning record' : 'Installation record');
    byId('hb-action-detail-meta').textContent = [
      action.case_reference,
      action.branch,
      action.order_number ? `Order ${action.order_number}` : '',
    ].filter(Boolean).join(' / ');
    byId('hb-action-summary').innerHTML = workstream === 'commissioning' ? `
      <div class="hb-action-summary-primary"><span>Commissioning</span><strong class="hb-action-status ${statusClass(action.commissioning_status)}">${esc(action.commissioning_status_label || 'Not commissioned')}</strong></div>
      <div><span>Installed on</span><strong>${esc(action.installation_date_display || 'Not set')}</strong></div>
      <div><span>Ready on</span><strong>${esc(action.commissioning_ready_on_display || 'Not set')}</strong></div>` : `
      <div class="hb-action-summary-primary"><span>Installation status</span><strong class="hb-action-status ${statusClass(action.installation_status)}">${esc(action.installation_status_label)}</strong></div>
      <div><span>Order number</span><strong>${esc(action.order_number || 'Not set')}</strong></div>
      <div><span>Installed on</span><strong>${esc(action.installation_date_display || 'Not set')}</strong></div>`;
  }
  function renderHistory(rows) {
    byId('hb-action-history-count').textContent = `(${rows.length})`;
    byId('hb-action-history-list').innerHTML = rows.length ? rows.map(row => `<article><strong>${esc(row.label)}</strong><span>${esc([row.actor, deps.fmtDate ? deps.fmtDate(row.created_at) : row.created_at].filter(Boolean).join(' · '))}</span>${row.reason ? `<p>${esc(row.reason)}</p>` : ''}</article>`).join('') : '<p class="meta">No activity recorded.</p>';
  }

  function payloadFromForm() {
    const workstream = detail.workstream || currentWorkstream();
    if (workstream === 'commissioning') return {revision: detail.revision, workstream, commissioning_status: 'commissioned', commissioning_date: field('hb-commissioning-date')?.value || ''};
    if (installationDelayMode) return {
      revision: detail.revision, workstream: 'installation', installation_status: 'open',
      installation_note: field('hb-installation-note')?.value.trim() || '',
    };
    return {
      revision: detail.revision, workstream: 'installation', installation_status: 'installed',
      installation_date: field('hb-installation-date')?.value || '', serial_number: field('hb-serial-number')?.value.trim() || '',
      installation_report_submitted: Boolean(field('hb-installation-report-submitted')?.checked),
    };
  }
  function validate(payload) {
    const today = deps.state?.businessDate || new Date().toISOString().slice(0, 10);
    if (payload.workstream === 'commissioning') {
      if (!payload.commissioning_date) return 'Choose the actual commissioning date.';
      if (payload.commissioning_date > today) return 'The actual commissioning date cannot be in the future.';
      return '';
    }
    if (payload.installation_status === 'open') return payload.installation_note ? '' : 'Add a short pending installation comment.';
    if (!payload.installation_date) return 'Choose the actual installation date.';
    if (payload.installation_date > today) return 'The actual installation date cannot be in the future.';
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
    correctionMode = false;
    if (payload.workstream === 'installation' && response.data.action.installation_status === 'installed') {
      deps.showToast('Installation saved. The case is now in the commissioning queue.', 'success');
      window.location.assign(`/portal/s/hb-actions/${encodeURIComponent(detail.farmer_id)}/?workstream=commissioning`); return;
    }
    populateDetail(response.data.action);
    applyVisualDetailHierarchy(response.data.action);
    deps.showToast(payload.workstream === 'commissioning' ? 'Commissioning recorded.' : (payload.installation_status === 'open' ? 'Delay update saved.' : 'Installation saved.'), 'success');
  }

  async function saveCommissioningNotes() {
    if (!detail || detail.workstream !== 'commissioning') return;
    const payload = {
      revision: detail.revision,
      pending_commissioning_comment: field('hb-pending-commissioning-comment')?.value.trim() || '',
      additional_remarks: field('hb-additional-remarks')?.value.trim() || '',
    };
    const button = byId('hb-save-commissioning-notes');
    deps.setButtonLoading?.(button, true, 'Saving notes…');
    const response = await deps.portalApi.postJson(`/hb-actions/${encodeURIComponent(detail.farmer_id)}/commissioning-notes/`, payload, deps.tg);
    deps.setButtonLoading?.(button, false);
    if (!response.ok || !response.data?.ok) { deps.showToast(response.data?.error || 'Notes could not be saved.', 'error'); return; }
    populateDetail(response.data.action);
    applyVisualDetailHierarchy(response.data.action);
    deps.showToast('Commissioning notes saved.', 'success');
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
    populateDetail(response.data.action); applyVisualDetailHierarchy(response.data.action); window.lucide?.createIcons?.();
  }
  function init(injected) {
    deps = injected || {};
    const root = byId('portal-screen'); if (root?.dataset.screen !== 'hb_actions') return;
    const farmerId = root.dataset.hbActionFarmerId || '';
    if (farmerId) {
      byId('hb-action-form')?.addEventListener('submit', save);
      byId('hb-save-commissioning-notes')?.addEventListener('click', saveCommissioningNotes);
      byId('hb-mark-installed')?.addEventListener('click', () => {
        installationCompletionMode = true;
        installationDelayMode = false;
        renderInstallationForm();
        applyReadOnlyState();
        field('hb-installation-date')?.focus();
      });
      byId('hb-report-installation-delay')?.addEventListener('click', () => {
        installationDelayMode = true;
        installationCompletionMode = false;
        renderInstallationForm();
        applyReadOnlyState();
        field('hb-installation-note')?.focus();
      });
      byId('hb-action-invoice')?.addEventListener('click', openInvoicePreview);
      byId('media-viewer-close')?.addEventListener('click', closeInvoicePreview);
      byId('hb-action-edit-toggle')?.addEventListener('click', () => {
        correctionMode = !correctionMode;
        if (detail?.workstream === 'installation') renderInstallationForm();
        else byId('hb-action-save').textContent = correctionMode ? 'Save commissioning correction' : 'Mark commissioned';
        const toggle = byId('hb-action-edit-toggle');
        toggle.classList.toggle('active', correctionMode);
        toggle.setAttribute('aria-pressed', String(correctionMode));
        toggle.setAttribute('aria-label', correctionMode ? 'Return to view mode' : 'Edit completed record');
        toggle.title = correctionMode ? 'Return to view mode' : 'Correct this record';
        applyReadOnlyState();
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
  }
  function loadCurrent() { const farmerId = byId('portal-screen')?.dataset.hbActionFarmerId || ''; return farmerId ? loadDetail(farmerId) : loadList(); }

  window.PortalMiniAppHbActions = {init, load: loadCurrent};
})();
