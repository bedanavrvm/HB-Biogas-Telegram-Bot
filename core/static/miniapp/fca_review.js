(function () {
  const tg = window.MiniAppTelegram ? window.MiniAppTelegram.init() : null;
  const payload = JSON.parse(document.getElementById('batch-data').textContent);
  const utils = window.MiniAppUtils || {};
  let rows = payload.rows || [];
  const statusValues = payload.status_values || [];
  const body = document.getElementById('rowsBody');
  const statusEl = document.getElementById('status');
  const pageHeader = document.querySelector('main > header');
  const toolbar = document.querySelector('.toolbar');
  const summary = document.querySelector('.summary');
  let commitRequestId = '';
  const fields = ['Customer Name', 'ID Number', 'Primary Phone', 'Hub', 'Field Officer', 'Location', 'HB Staff', 'Deposit', 'Jawabu Visit Date', 'JBL Officer', 'Status', 'Comment', 'Review Notes', 'Source'];
  const draft = utils.createServerDraft ? utils.createServerDraft({
    workflow: 'fca_review',
    contextKey: payload.batch_id,
    initData: () => tg ? tg.initData || '' : '',
    token: () => payload.token || '',
    onSaved: () => setStatus('Draft saved securely. Attachments are submitted only when you commit.', ''),
    onError: (error) => {
      if (navigator.onLine === false) setStatus('Offline. Changes are still on this screen; reconnect to save the draft.', 'error');
      else if (!error.conflict) setStatus(error.message || 'Draft could not be saved.', 'error');
    },
  }) : null;

  function updateTableFrame() {
    const chrome = (pageHeader ? pageHeader.offsetHeight : 0)
      + (toolbar ? toolbar.offsetHeight : 0)
      + (summary ? summary.offsetHeight : 0)
      + 18;
    document.documentElement.style.setProperty('--fca-chrome-height', `${chrome}px`);
  }

  function isReview(row) {
    return row['Import Status'] === 'review_needed' || String(row['Review Notes'] || '').trim();
  }

  function editable(name) {
    return name !== 'Source' && name !== 'Review Notes' && name !== 'Hub' && name !== 'Field Officer';
  }

  function render() {
    body.innerHTML = '';
    rows.forEach((row, index) => {
      const tr = document.createElement('tr');
      tr.className = !row.approved ? 'row-skipped' : (isReview(row) ? 'row-review' : '');
      const number = document.createElement('td');
      number.className = 'table-number';
      number.textContent = String(index + 1);
      tr.appendChild(number);
      const use = document.createElement('td');
      const checkbox = document.createElement('input');
      checkbox.type = 'checkbox';
      checkbox.checked = !!row.approved;
      checkbox.addEventListener('change', () => {
        row.approved = checkbox.checked;
        saveDraft();
        renderCounts();
        tr.className = !row.approved ? 'row-skipped' : (isReview(row) ? 'row-review' : '');
      });
      use.appendChild(checkbox);
      tr.appendChild(use);

      fields.forEach((name) => {
        const td = document.createElement('td');
        if (name === 'Status') {
          const select = document.createElement('select');
          const blank = document.createElement('option');
          blank.value = '';
          blank.textContent = '';
          select.appendChild(blank);
          statusValues.forEach((value) => {
            const option = document.createElement('option');
            option.value = value;
            option.textContent = value;
            select.appendChild(option);
          });
          select.value = row[name] || '';
          select.addEventListener('change', () => { row[name] = select.value; saveDraft(); });
          td.appendChild(select);
        } else if (name === 'Comment') {
          const input = document.createElement('textarea');
          input.value = row[name] || '';
          input.addEventListener('input', () => { row[name] = input.value; saveDraft(); });
          td.appendChild(input);
        } else {
          const input = document.createElement('input');
          input.value = row[name] || '';
          input.readOnly = !editable(name);
          input.addEventListener('input', () => { row[name] = input.value; saveDraft(); });
          td.appendChild(input);
        }
        tr.appendChild(td);
      });
      body.appendChild(tr);
    });
    renderCounts();
    updateTableFrame();
  }

  function renderCounts() {
    document.getElementById('totalCount').textContent = rows.length;
    document.getElementById('approvedCount').textContent = rows.filter((row) => row.approved).length;
    document.getElementById('reviewCount').textContent = rows.filter((row) => row.approved && isReview(row)).length;
    document.getElementById('skippedCount').textContent = rows.filter((row) => !row.approved).length;
  }

  function setStatus(text, kind) {
    statusEl.textContent = text;
    statusEl.className = 'status ' + (kind || '');
    updateTableFrame();
  }

  function saveDraft() {
    if (draft && rows.length) draft.schedule({ rows });
  }

  async function restoreDraft() {
    if (!draft) return;
    try {
      const saved = await draft.load();
      if (saved && Array.isArray(saved.payload?.rows)) {
        rows = saved.payload.rows;
        setStatus('Secure draft restored. Review and commit when ready.', '');
        render();
      }
    } catch (error) {
      setStatus('Draft recovery is unavailable. The original batch values are still shown.', 'error');
    }
  }

  function clearDraft() {
    return draft ? draft.clear().catch(() => {}) : Promise.resolve();
  }

  window.addEventListener('visibilitychange', () => { if (document.visibilityState === 'hidden') saveDraft(); });
  window.addEventListener('offline', () => setStatus('Offline. Changes remain open here; reconnect to save the secure draft.', 'error'));
  window.addEventListener('online', () => setStatus('Back online. Your next edit will save the secure draft.', ''));
  document.getElementById('approveAll').addEventListener('click', () => {
    rows.forEach((row) => { if (!isReview(row)) row.approved = true; });
    saveDraft();
    render();
  });

  document.getElementById('skipReview').addEventListener('click', () => {
    rows.forEach((row) => { if (isReview(row)) row.approved = false; });
    saveDraft();
    render();
  });

  document.getElementById('commitBtn').addEventListener('click', async () => {
    const btn = document.getElementById('commitBtn');
    if (navigator.onLine === false) {
      saveDraft();
      setStatus('Offline. Changes remain open in this screen. Reconnect and wait for “Draft saved” before closing, then commit.', 'error');
      return;
    }
    saveDraft();
    btn.disabled = true;
    commitRequestId = commitRequestId || utils.createRequestId?.('fca-commit') || ('fca-commit-' + Date.now());
    setStatus('Committing approved FCA rows...', '');
    try {
      const response = await fetch('/api/fca/review/commit/', {
        method: 'POST',
        headers: {
          ...(utils.messageHeaders ? utils.messageHeaders({ 'Content-Type': 'application/json' }) : { 'Content-Type': 'application/json' }),
          ...(utils.idempotencyHeaders ? utils.idempotencyHeaders(commitRequestId) : { 'X-Request-ID': commitRequestId, 'Idempotency-Key': commitRequestId }),
        },
        body: JSON.stringify({
          batch_id: payload.batch_id,
          token: payload.token,
          init_data: tg ? tg.initData : '',
          client_request_id: commitRequestId,
          rows,
        }),
      });
      const rawResult = await response.json().catch(() => ({}));
      const result = utils.normalizeResponsePayload
        ? utils.normalizeResponsePayload(response, rawResult, 'Some rows still need correction.')
        : rawResult;
      if (!response.ok || !result.success) {
        if (response.status > 0 && response.status < 500) commitRequestId = '';
        if (Array.isArray(result.rows)) {
          rows = result.rows;
          render();
        }
        setStatus(result.message || 'Some rows still need correction.', 'error');
        return;
      }
      rows = Array.isArray(result.rows) ? result.rows : [];
      commitRequestId = '';
      render();
      const sync = result.sheet_sync || {};
      setStatus(`Committed ${result.committed || 0} row(s). MD updated: ${sync.updated || 0}, created: ${sync.created || 0}. ${rows.length} row(s) remain.`, 'ok');
      clearDraft();
      utils.haptic?.('success');
      if (!rows.length && tg) setTimeout(() => window.MiniAppDiagnostics.intentionalClose('empty_queue'), 900);
    } catch (err) {
      saveDraft();
      setStatus('Could not commit rows. Review edits remain open; reconnect to save the secure draft and retry.', 'error');
      utils.haptic?.('error');
    } finally {
      btn.disabled = false;
    }
  });

  window.addEventListener('resize', updateTableFrame);
  render();
  restoreDraft();
  updateTableFrame();
})();


