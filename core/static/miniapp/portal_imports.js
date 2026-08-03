(() => {
  'use strict';

  const api = window.PortalMiniAppApi || {};
  const utils = window.MiniAppUtils || {};
  const tg = window.Telegram?.WebApp;
  let importState = { batches: [], loaded: false };

  function node(id) { return document.getElementById(id); }

  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, char => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[char]));
  }

  function formatDateTime(value) {
    if (!value) return '—';
    if (utils.formatDateTime) return utils.formatDateTime(value);
    return String(value).replace('T', ' ').slice(0, 16);
  }

  function feedback(message, tone = 'info') {
    const list = node('portal-import-list');
    if (!list) return;
    let target = node('portal-import-feedback');
    if (!target) {
      target = document.createElement('div');
      target.id = 'portal-import-feedback';
      target.className = 'portal-import-feedback';
      list.before(target);
    }
    target.className = `portal-import-feedback ${tone}`;
    target.textContent = message;
  }

  function setLoading(button, loading, label = 'Working') {
    if (utils.setButtonLoading) {
      utils.setButtonLoading(button, loading, label);
      return;
    }
    if (!button) return;
    if (loading) {
      button.dataset.label = button.textContent;
      button.disabled = true;
      button.textContent = label;
    } else {
      button.disabled = false;
      button.textContent = button.dataset.label || button.textContent;
      delete button.dataset.label;
    }
  }

  function archiveText(batch) {
    if (batch.archive_state === 'archived') return '<span class="badge badge-green">Drive archived</span>';
    if (batch.archive_state === 'needs_attention') return '<span class="badge badge-orange">Drive needs attention</span>';
    return '<span class="badge badge-blue">Drive archive pending</span>';
  }

  function kindText(kind) {
    return String(kind) === 'sysup' ? 'SysUp' : 'FarmUp';
  }

  function renderBatches() {
    const list = node('portal-import-list');
    if (!list) return;
    if (!importState.batches.length) {
      list.innerHTML = '<div class="empty-state"><div class="es-title">No staged imports</div><div class="es-sub">Stage a FarmUp or SysUp source file above to review it here.</div></div>';
      return;
    }
    list.innerHTML = importState.batches.map(batch => {
      const issues = Number(batch.review_needed || 0);
      const archived = archiveText(batch);
      const retry = batch.archive_state === 'needs_attention'
        ? `<button type="button" class="btn btn-secondary portal-import-archive" data-batch-id="${escapeHtml(batch.id)}">Retry Drive archive</button>` : '';
      return `<article class="portal-import-card">
        <div class="portal-import-card-title"><div><span class="settings-eyebrow">${kindText(batch.kind)}</span><h3>${escapeHtml(batch.source_filename || 'Untitled import')}</h3><p>Jawabu HomeBiogas · ${escapeHtml(formatDateTime(batch.created_at))}</p></div>${archived}</div>
        <div class="portal-import-stats"><span><strong>${escapeHtml(batch.total_rows)}</strong> rows</span><span class="${issues ? 'warning' : ''}"><strong>${escapeHtml(issues)}</strong> review needed</span><span><strong>${escapeHtml(batch.committed_count)}</strong> committed outside Portal</span></div>
        ${batch.error ? `<p class="portal-import-error">${escapeHtml(batch.error)}</p>` : ''}
        ${batch.archive_error ? `<p class="portal-import-error">${escapeHtml(batch.archive_error)}</p>` : ''}
        <div class="portal-import-actions"><button type="button" class="btn btn-primary portal-import-review-button" data-batch-id="${escapeHtml(batch.id)}">Review data</button>${retry}</div>
      </article>`;
    }).join('');
  }

  async function load({ silent = false } = {}) {
    const list = node('portal-import-list');
    if (!list) return;
    if (!silent) list.innerHTML = '<div class="empty-state"><div class="spinner-inline"></div><div class="es-sub">Loading staged imports...</div></div>';
    try {
      const result = await api.apiFetch('/imports/', {}, tg);
      if (!result.ok || !result.data?.ok) throw new Error(result.data?.error || 'Could not load staged imports.');
      importState = { batches: result.data.batches || [], loaded: true };
      renderBatches();
    } catch (error) {
      list.innerHTML = `<div class="empty-state"><div class="es-title">Imports unavailable</div><div class="es-sub">${escapeHtml(error.message || 'Refresh and try again.')}</div></div>`;
    }
  }

  async function stage(form) {
    const kind = String(form.dataset.importKind || '').trim();
    const fileInput = form.querySelector('input[type="file"]');
    const submit = form.querySelector('button[type="submit"]');
    if (!fileInput?.files?.[0]) {
      feedback('Choose a source file before staging it.', 'error');
      return;
    }
    const formData = new FormData();
    formData.set('file', fileInput.files[0]);
    setLoading(submit, true, 'Staging');
    feedback('Validating and staging the source file…', 'info');
    try {
      const result = await api.postForm(`/imports/${encodeURIComponent(kind)}/stage/`, formData, tg);
      if (!result.ok || !result.data?.ok) throw new Error(result.data?.error || 'The import was not staged.');
      fileInput.value = '';
      feedback(result.data.replayed ? 'This retry reopened the existing staged import.' : 'Import staged for review. Archiving its source to Drive…', 'success');
      await load({ silent: true });
      if (result.data.archive_operation_id) await archive(result.data.archive_operation_id, { silent: true });
    } catch (error) {
      feedback(error.message || 'The import could not be staged.', 'error');
    } finally {
      setLoading(submit, false);
    }
  }

  function rowColumns(rows) {
    const names = new Set();
    rows.slice(0, 50).forEach(row => Object.keys(row || {}).forEach(key => names.add(key)));
    const ignored = new Set(['raw_data']);
    return [...names].filter(name => !ignored.has(name)).slice(0, 16);
  }

  function displayCell(value) {
    if (value === null || value === undefined || value === '') return '—';
    if (typeof value === 'object') return JSON.stringify(value);
    return String(value);
  }

  async function review(batchId, page = 1) {
    const target = node('portal-import-review');
    if (!target) return;
    target.hidden = false;
    target.innerHTML = '<div class="empty-state"><div class="spinner-inline"></div><div class="es-sub">Loading review rows...</div></div>';
    try {
      const result = await api.apiFetch(`/imports/${encodeURIComponent(batchId)}/?page=${encodeURIComponent(page)}`, {}, tg);
      if (!result.ok || !result.data?.ok) throw new Error(result.data?.error || 'Could not load import review data.');
      const batch = result.data.batch || {};
      const rows = Array.isArray(batch.rows) ? batch.rows : [];
      const columns = rowColumns(rows);
      const pagination = batch.review_pagination || {};
      const currentPage = Number(pagination.page || 1);
      const pageCount = Number(pagination.pages || 1);
      const totalRows = Number(pagination.total_rows || batch.total_rows || rows.length);
      const table = !rows.length
        ? '<div class="empty-state"><div class="es-title">No parsed rows</div><div class="es-sub">This staged file did not produce review rows.</div></div>'
        : `<div class="portal-import-table-wrap"><table class="portal-import-table"><thead><tr>${columns.map(column => `<th>${escapeHtml(column)}</th>`).join('')}</tr></thead><tbody>${rows.map(row => `<tr>${columns.map(column => `<td>${escapeHtml(displayCell(row?.[column]))}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
      target.innerHTML = `<div class="portal-import-review-heading"><div><span class="settings-eyebrow">REVIEW ONLY</span><h2>${escapeHtml(batch.source_filename || 'Staged import')}</h2><p>${escapeHtml(batch.total_rows || 0)} parsed rows · ${escapeHtml(batch.review_needed || 0)} need review. No Portal commit action is available.</p></div><button type="button" class="btn btn-secondary" id="portal-import-review-close">Close review</button></div>${table}`;
      if (pageCount > 1) {
        target.insertAdjacentHTML('beforeend', `<div class="portal-import-pager"><span>Showing page ${escapeHtml(currentPage)} of ${escapeHtml(pageCount)} (${escapeHtml(totalRows)} rows)</span><div><button type="button" class="btn btn-secondary portal-import-review-page" data-batch-id="${escapeHtml(batch.id)}" data-page="${escapeHtml(currentPage - 1)}" ${currentPage <= 1 ? 'disabled' : ''}>Previous</button><button type="button" class="btn btn-secondary portal-import-review-page" data-batch-id="${escapeHtml(batch.id)}" data-page="${escapeHtml(currentPage + 1)}" ${currentPage >= pageCount ? 'disabled' : ''}>Next</button></div></div>`);
      }
      target.scrollIntoView({ behavior: 'smooth', block: 'start' });
    } catch (error) {
      target.innerHTML = `<div class="empty-state"><div class="es-title">Review unavailable</div><div class="es-sub">${escapeHtml(error.message || 'Refresh and try again.')}</div></div>`;
    }
  }

  async function archive(operationId, { silent = false } = {}) {
    try {
      const result = await api.postJson('/imports/archive-attempt/', { operation_id: operationId }, tg);
      if (!result.ok || !result.data?.ok) throw new Error(result.data?.error || 'Drive archive needs attention.');
      if (!silent) feedback('The source file is archived in the controlled Imports Drive folder.', 'success');
      await load({ silent: true });
    } catch (error) {
      if (!silent) feedback(error.message || 'Drive archive needs attention. Retry from the import card.', 'error');
      await load({ silent: true });
    }
  }

  function operationForBatch(batchId) {
    // The batch list deliberately never exposes opaque external-operation IDs.
    // A failed archive gets a server-reserved retry operation when the list is
    // refreshed, so the review action remains local and access-controlled.
    return importState.batches.find(batch => String(batch.id) === String(batchId))?.archive_operation_id || '';
  }

  document.addEventListener('submit', event => {
    const form = event.target.closest('.portal-import-upload');
    if (!form) return;
    event.preventDefault();
    stage(form);
  });

  document.addEventListener('click', event => {
    const refresh = event.target.closest('#portal-import-refresh');
    if (refresh) {
      load();
      return;
    }
    const reviewButton = event.target.closest('.portal-import-review-button');
    if (reviewButton) {
      review(reviewButton.dataset.batchId);
      return;
    }
    const reviewPageButton = event.target.closest('.portal-import-review-page');
    if (reviewPageButton && !reviewPageButton.disabled) {
      review(reviewPageButton.dataset.batchId, Number(reviewPageButton.dataset.page || 1));
      return;
    }
    if (event.target.closest('#portal-import-review-close')) {
      const target = node('portal-import-review');
      if (target) {
        target.hidden = true;
        target.replaceChildren();
      }
      return;
    }
    const archiveButton = event.target.closest('.portal-import-archive');
    if (archiveButton) {
      const operationId = operationForBatch(archiveButton.dataset.batchId);
      if (!operationId) {
        feedback('The Drive retry is unavailable. Refresh Imports and try again.', 'error');
        return;
      }
      setLoading(archiveButton, true, 'Retrying');
      archive(operationId).finally(() => setLoading(archiveButton, false));
    }
  });

  window.PortalMiniAppImports = { load };
})();
