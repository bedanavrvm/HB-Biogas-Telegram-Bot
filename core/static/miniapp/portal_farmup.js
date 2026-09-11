(() => {
  'use strict';

  const api = window.PortalMiniAppApi || {};
  const utils = window.MiniAppUtils || {};
  const tg = window.Telegram?.WebApp;
  const fields = [
    'Customer Name', 'National ID', 'Primary Phone', 'Secondary Phone',
    'Application Action', 'Additional Unit Reason', 'County',
    'HBG Visit Date', 'Deposit Paid to HB', 'HB Sales Person', 'Cleaning Notes',
  ];
  let batches = [];
  let active = null;
  let search = '';
  let needsReviewOnly = false;
  let commitRequestKey = '';

  function node(id) { return document.getElementById(id); }
  function activeScreen() { return document.getElementById('portal-screen')?.dataset.screen === 'farmup'; }
  function can(key) { return window.PortalAppShell?.hasCapability?.(key) !== false; }
  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, char => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[char]));
  }
  function requestId(prefix) {
    return utils.createRequestId?.(prefix) || `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }
  function setLoading(button, loading, label = 'Working') {
    if (utils.setButtonLoading) return utils.setButtonLoading(button, loading, label);
    if (!button) return;
    if (loading) { button.dataset.label = button.textContent; button.disabled = true; button.textContent = label; }
    else { button.disabled = false; button.textContent = button.dataset.label || button.textContent; }
  }
  function feedback(message, tone = 'info') {
    const target = node('portal-farmup-feedback');
    if (!target) return;
    target.className = `portal-import-feedback ${tone}`;
    target.textContent = message;
  }
  function isBlank(value) { return !String(value ?? '').trim(); }
  function isReview(row) {
    return row['Import Status'] === 'review_needed'
      || ['Customer Name', 'National ID', 'Primary Phone', 'Secondary Phone', 'County', 'HBG Visit Date', 'Deposit Paid to HB', 'HB Sales Person']
        .some(field => isBlank(row[field]))
      || (row['Application Action'] === 'create_additional_unit' && isBlank(row['Additional Unit Reason']));
  }
  function fieldProblem(row, field) {
    if (field === 'Cleaning Notes') return false;
    if (field === 'Application Action') return !['update_existing', 'create_additional_unit'].includes(row[field] || 'update_existing');
    if (field === 'Additional Unit Reason') return row['Application Action'] === 'create_additional_unit' && isBlank(row[field]);
    const notes = String(row['Cleaning Notes'] || '').toLowerCase();
    if (field === 'National ID') return isBlank(row[field]) || notes.includes('national id');
    if (field === 'Customer Name') return isBlank(row[field]) || notes.includes('customer name');
    if (field === 'Primary Phone') return isBlank(row[field]) || notes.includes('primary phone');
    if (field === 'Secondary Phone') return isBlank(row[field]) || notes.includes('secondary phone');
    return isBlank(row[field]) && (isReview(row) || notes.includes(field.toLowerCase()));
  }
  function searchable(row) { return Object.values(row).map(value => String(value ?? '').toLowerCase()).join(' '); }
  function visibleRows() {
    const terms = search.trim().toLowerCase().split(/\s+/).filter(Boolean);
    return (active?.rows || []).filter(row => {
      if (needsReviewOnly && !isReview(row)) return false;
      const haystack = searchable(row);
      return terms.every(term => haystack.includes(term));
    });
  }
  function counts() {
    const rows = active?.rows || [];
    return {
      total: rows.length,
      approved: rows.filter(row => row.approved).length,
      skipped: rows.filter(row => !row.approved).length,
      unresolved: rows.filter(row => row.approved && isReview(row)).length,
    };
  }
  function archiveBadge(batch) {
    if (batch.archive_state === 'archived') return '<span class="badge badge-green">Drive archived</span>';
    if (batch.archive_state === 'needs_attention') return '<span class="badge badge-orange">Drive needs attention</span>';
    return '<span class="badge badge-blue">Archive pending</span>';
  }
  function renderBatches() {
    const target = node('portal-farmup-list');
    if (!target) return;
    if (!batches.length) {
      target.innerHTML = '<div class="empty-state"><div class="es-title">No FarmUp batches</div><div class="es-sub">Upload a Farmers CSV to begin a reviewed intake.</div></div>';
      return;
    }
    target.innerHTML = batches.map(batch => `<article class="portal-import-card">
      <div class="portal-import-card-title"><div><span class="settings-eyebrow">FARMUP</span><h3>${escapeHtml(batch.source_filename || 'Farmers CSV')}</h3><p>${escapeHtml(batch.created_at || '')}</p></div><div>${batch.is_portal_archived ? '<span class="badge">Working list archived</span>' : ''}${archiveBadge(batch)}</div></div>
      <div class="portal-import-stats"><span><strong>${Number(batch.total_rows || 0)}</strong> source rows</span><span class="${batch.review_needed ? 'warning' : ''}"><strong>${Number(batch.review_needed || 0)}</strong> review needed</span><span><strong>${Number(batch.committed_count || 0)}</strong> committed</span></div>
      <div class="portal-import-actions"><button class="btn btn-primary farmup-open" data-batch-id="${escapeHtml(batch.id)}">${batch.status === 'committed' ? 'View result' : 'Review rows'}</button>${batch.archive_state === 'needs_attention' && can('portal.farmup.stage') ? `<button class="btn btn-secondary farmup-drive-retry" data-batch-id="${escapeHtml(batch.id)}">Retry Drive archive</button>` : ''}${can('portal.farmup.stage') && !batch.is_portal_archived ? `<button class="btn btn-secondary farmup-archive" data-batch-id="${escapeHtml(batch.id)}">Archive from FarmUp</button>` : ''}</div>
    </article>`).join('');
  }
  async function load({ silent = false } = {}) {
    if (!activeScreen()) return;
    const target = node('portal-farmup-list');
    if (!silent && target) target.innerHTML = '<div class="empty-state"><div class="spinner-inline"></div><div class="es-sub">Loading FarmUp batches...</div></div>';
    const result = await api.apiFetch('/farmup/', {}, tg);
    if (!activeScreen()) return;
    if (!result.ok || !result.data?.ok) throw new Error(result.data?.error || 'FarmUp batches could not be loaded.');
    batches = result.data.batches || [];
    renderBatches();
    const form = node('portal-farmup-upload');
    if (form) form.hidden = !can('portal.farmup.stage');
  }
  function editorCell(row, field) {
    const problem = fieldProblem(row, field);
    const value = escapeHtml(row[field] || (field === 'Application Action' ? 'update_existing' : ''));
    let control;
    if (field === 'Application Action') {
      control = `<select data-farmup-field="${field}"><option value="update_existing"${value === 'update_existing' ? ' selected' : ''}>Update existing / first unit</option><option value="create_additional_unit"${value === 'create_additional_unit' ? ' selected' : ''}>Create next linked unit</option></select>`;
    } else if (field === 'Cleaning Notes') {
      control = `<textarea data-farmup-field="${field}">${value}</textarea>`;
    } else {
      const disabled = field === 'Additional Unit Reason' && row['Application Action'] !== 'create_additional_unit';
      control = `<input data-farmup-field="${field}" value="${value}"${disabled ? ' disabled' : ''}>`;
    }
    return `<td data-label="${escapeHtml(field)}" class="${problem ? 'field-error' : ''}">${control}</td>`;
  }
  function renderEditor() {
    const target = node('portal-farmup-review');
    if (!target || !active) return;
    target.hidden = false;
    const shown = visibleRows();
    const metric = counts();
    const rows = shown.map(row => `<tr data-row-id="${escapeHtml(row.row_id)}" class="${!row.approved ? 'row-skipped' : (isReview(row) ? 'row-review' : '')}"><td data-label="Use"><input class="farmup-approved" type="checkbox" ${row.approved ? 'checked' : ''}></td>${fields.map(field => editorCell(row, field)).join('')}</tr>`).join('');
    target.innerHTML = `<div class="portal-import-review-heading"><div><span class="settings-eyebrow">EDITABLE PREVIEW</span><h2>${escapeHtml(active.source_filename || 'FarmUp')}</h2><p>Correct highlighted fields, then choose which rows to commit.</p></div><button class="btn btn-secondary" id="farmup-close">Close</button></div>
      <div class="farmup-counters"><span><strong>${metric.total}</strong>Total</span><span><strong>${metric.approved}</strong>Approved</span><span class="warning"><strong>${metric.unresolved}</strong>Unresolved</span><span><strong>${metric.skipped}</strong>Skipped</span></div>
      <div class="farmup-toolbar"><input id="farmup-search" type="search" value="${escapeHtml(search)}" placeholder="Search rows..."><button class="btn btn-secondary ${needsReviewOnly ? 'active' : ''}" id="farmup-review-filter" aria-pressed="${needsReviewOnly}">Needs review</button><button class="btn btn-secondary" id="farmup-approve-valid">Approve valid</button><button class="btn btn-secondary" id="farmup-skip-flagged">Skip flagged</button></div>
      <div class="farmup-row-table-wrap"><table class="farmup-row-table"><thead><tr><th>Use</th>${fields.map(field => `<th>${escapeHtml(field)}</th>`).join('')}</tr></thead><tbody>${rows || `<tr><td colspan="${fields.length + 1}">No rows match this filter.</td></tr>`}</tbody></table></div>
      ${can('portal.farmup.commit') && active.status !== 'committed' ? '<div class="farmup-commit-bar"><span>Commit writes approved rows to Django and the configured synchronized register.</span><button class="btn btn-primary" id="farmup-commit">Review commit</button></div>' : ''}`;
  }
  async function openBatch(batchId) {
    const target = node('portal-farmup-review');
    if (target) { target.hidden = false; target.innerHTML = '<div class="empty-state"><div class="spinner-inline"></div></div>'; }
    const result = await api.apiFetch(`/farmup/${encodeURIComponent(batchId)}/`, {}, tg);
    if (!result.ok || !result.data?.ok) throw new Error(result.data?.error || 'FarmUp preview could not be loaded.');
    active = result.data.batch;
    (active.rows || []).forEach(row => { if (!row['Application Action']) row['Application Action'] = 'update_existing'; });
    search = ''; needsReviewOnly = false; commitRequestKey = ''; renderEditor();
    target?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
  async function stage(form) {
    const input = form.querySelector('input[type=file]');
    const button = form.querySelector('button[type=submit]');
    if (!input?.files?.[0]) return feedback('Choose a Farmers CSV first.', 'error');
    const body = new FormData(); body.set('file', input.files[0]);
    setLoading(button, true, 'Parsing');
    try {
      const result = await api.postForm('/farmup/stage/', body, tg);
      if (!result.ok || !result.data?.ok) throw new Error(result.data?.error || 'FarmUp upload failed.');
      feedback(result.data.message, 'success'); input.value = '';
      await load({ silent: true }); await openBatch(result.data.batch.id);
      if (result.data.archive_operation_id) await attemptDrive(result.data.archive_operation_id, true);
    } catch (error) { feedback(error.message, 'error'); }
    finally { setLoading(button, false); }
  }
  function confirmation(metric) {
    const dialog = document.createElement('dialog');
    dialog.className = 'farmup-confirm-dialog';
    dialog.innerHTML = `<form method="dialog"><h2>Commit FarmUp rows?</h2><div class="farmup-counters"><span><strong>${metric.approved}</strong>Approved</span><span><strong>${metric.skipped}</strong>Skipped</span><span class="warning"><strong>${metric.unresolved}</strong>Unresolved</span></div><p>Approved rows will update Django workflow state and may synchronize to the configured Master Data Sheet.</p><div class="portal-import-actions"><button value="cancel" class="btn btn-secondary">Go back</button><button value="confirm" class="btn btn-primary">Commit approved rows</button></div></form>`;
    document.body.appendChild(dialog); dialog.showModal();
    return new Promise(resolve => dialog.addEventListener('close', () => { const ok = dialog.returnValue === 'confirm'; dialog.remove(); resolve(ok); }, { once: true }));
  }
  async function commit() {
    if (!active) return;
    const metric = counts();
    if (!await confirmation(metric)) return;
    const button = node('farmup-commit'); setLoading(button, true, 'Committing');
    // Preserve the key across ambiguous network failures. A later click then
    // asks the server to replay the same result instead of writing twice.
    const key = commitRequestKey || requestId('portal-farmup-commit');
    commitRequestKey = key;
    const payload = { rows: active.rows, revision_token: active.revision_token, client_request_id: key };
    try {
      const result = await api.postJson(`/farmup/${encodeURIComponent(active.id)}/commit/`, payload, tg);
      if (!result.ok || !result.data?.ok) throw new Error(result.data?.error || 'FarmUp commit failed.');
      const summary = result.data.result || {};
      commitRequestKey = '';
      feedback(`${summary.committed || 0} committed, ${summary.skipped || 0} skipped, ${summary.review_needed || 0} unresolved.`, summary.success ? 'success' : 'error');
      await load({ silent: true }); await openBatch(active.id);
    } catch (error) { feedback(error.message, 'error'); }
    finally { setLoading(button, false); }
  }
  async function attemptDrive(operationId, silent = false) {
    const result = await api.postJson('/farmup/archive-attempt/', { operation_id: operationId }, tg);
    if (!result.ok || !result.data?.ok) { if (!silent) feedback(result.data?.error || 'Drive archive needs attention.', 'error'); return; }
    if (!silent) feedback('FarmUp source archived to Drive.', 'success');
    await load({ silent: true });
  }

  document.addEventListener('submit', event => {
    if (!event.target.matches('#portal-farmup-upload')) return;
    event.preventDefault(); stage(event.target);
  });
  document.addEventListener('input', event => {
    if (event.target.id === 'farmup-search') {
      search = event.target.value;
      const caret = event.target.selectionStart;
      renderEditor();
      const replacement = node('farmup-search');
      replacement?.focus();
      replacement?.setSelectionRange?.(caret, caret);
      return;
    }
    const control = event.target.closest('[data-farmup-field]');
    if (!control || !active) return;
    const row = active.rows.find(item => String(item.row_id) === control.closest('tr')?.dataset.rowId);
    if (row) row[control.dataset.farmupField] = control.value;
  });
  document.addEventListener('change', event => {
    if (!active) return;
    const row = active.rows.find(item => String(item.row_id) === event.target.closest('tr')?.dataset.rowId);
    if (!row) return;
    if (event.target.matches('.farmup-approved')) row.approved = event.target.checked;
    if (event.target.dataset.farmupField) row[event.target.dataset.farmupField] = event.target.value;
    renderEditor();
  });
  document.addEventListener('click', event => {
    const open = event.target.closest('.farmup-open'); if (open) return openBatch(open.dataset.batchId).catch(error => feedback(error.message, 'error'));
    if (event.target.closest('#portal-farmup-refresh')) return load().catch(error => feedback(error.message, 'error'));
    if (event.target.closest('#farmup-close')) { node('portal-farmup-review').hidden = true; active = null; return; }
    if (event.target.closest('#farmup-review-filter')) { needsReviewOnly = !needsReviewOnly; renderEditor(); return; }
    if (event.target.closest('#farmup-approve-valid')) { active.rows.forEach(row => { if (!isReview(row)) row.approved = true; }); renderEditor(); return; }
    if (event.target.closest('#farmup-skip-flagged')) { active.rows.forEach(row => { if (isReview(row)) row.approved = false; }); renderEditor(); return; }
    if (event.target.closest('#farmup-commit')) return commit();
    const retry = event.target.closest('.farmup-drive-retry'); if (retry) { const batch = batches.find(item => item.id === retry.dataset.batchId); return attemptDrive(batch?.archive_operation_id); }
    const archive = event.target.closest('.farmup-archive'); if (archive && window.confirm('Archive this batch from the FarmUp working list? Retained evidence will remain available.')) {
      api.postJson(`/farmup/${encodeURIComponent(archive.dataset.batchId)}/archive/`, {}, tg).then(result => { if (!result.ok) throw new Error(result.data?.error); return load({ silent: true }); }).catch(error => feedback(error.message, 'error'));
    }
  });

  window.PortalMiniAppFarmUp = { load };
})();
