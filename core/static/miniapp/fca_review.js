(function () {
  const tg = window.MiniAppTelegram ? window.MiniAppTelegram.init() : null;
  const payload = JSON.parse(document.getElementById('batch-data').textContent);
  let rows = payload.rows || [];
  const statusValues = payload.status_values || [];
  const draftKey = 'fcaReviewDraft:' + payload.batch_id;
  const draftMaxAgeMs = 7 * 24 * 60 * 60 * 1000;
  const body = document.getElementById('rowsBody');
  const statusEl = document.getElementById('status');
  const pageHeader = document.querySelector('main > header');
  const toolbar = document.querySelector('.toolbar');
  const summary = document.querySelector('.summary');
  const fields = ['Customer Name', 'ID Number', 'Primary Phone', 'Hub', 'Field Officer', 'Location', 'HB Staff', 'Deposit', 'Jawabu Visit Date', 'JBL Officer', 'Status', 'Comment', 'Review Notes', 'Source'];

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
    rows.forEach((row) => {
      const tr = document.createElement('tr');
      tr.className = !row.approved ? 'row-skipped' : (isReview(row) ? 'row-review' : '');
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

  function canUseStorage() {
    try {
      const probe = '__fca_review_probe__';
      window.localStorage.setItem(probe, '1');
      window.localStorage.removeItem(probe);
      return true;
    } catch (err) {
      return false;
    }
  }

  const storageAvailable = canUseStorage();

  function saveDraft() {
    if (!storageAvailable) return;
    if (!rows.length) {
      window.localStorage.removeItem(draftKey);
      return;
    }
    window.localStorage.setItem(draftKey, JSON.stringify({ savedAt: new Date().toISOString(), rows }));
  }

  function restoreDraftIfFresh() {
    if (!storageAvailable) return;
    try {
      const raw = window.localStorage.getItem(draftKey);
      const draft = raw ? JSON.parse(raw) : null;
      const saved = draft && draft.savedAt ? Date.parse(draft.savedAt) : NaN;
      if (!draft || !Array.isArray(draft.rows) || Number.isNaN(saved) || Date.now() - saved > draftMaxAgeMs) {
        window.localStorage.removeItem(draftKey);
        return;
      }
      rows = draft.rows;
      setStatus('Unsaved FCA review draft restored from this device.', '');
    } catch (err) {
      window.localStorage.removeItem(draftKey);
    }
  }

  function clearDraft() {
    if (storageAvailable) window.localStorage.removeItem(draftKey);
  }

  window.addEventListener('pagehide', saveDraft);
  window.addEventListener('offline', () => setStatus('Offline. Review edits are saved on this device; commit when online.', 'error'));
  window.addEventListener('online', () => setStatus('Back online. Review edits are still saved locally until commit succeeds.', ''));
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
      setStatus('Offline. Review edits are saved on this device. Commit when online.', 'error');
      return;
    }
    saveDraft();
    btn.disabled = true;
    setStatus('Committing approved FCA rows...', '');
    try {
      const response = await fetch('/api/fca/review/commit/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          batch_id: payload.batch_id,
          token: payload.token,
          init_data: tg ? tg.initData : '',
          rows,
        }),
      });
      const result = await response.json();
      if (!response.ok || !result.success) {
        if (Array.isArray(result.rows)) {
          rows = result.rows;
          render();
        }
        setStatus(result.message || 'Some rows still need correction.', 'error');
        return;
      }
      rows = Array.isArray(result.rows) ? result.rows : [];
      render();
      const sync = result.sheet_sync || {};
      setStatus(`Committed ${result.committed || 0} row(s). MD updated: ${sync.updated || 0}, created: ${sync.created || 0}. ${rows.length} row(s) remain.`, 'ok');
      if (!rows.length && tg) setTimeout(() => tg.close(), 900);
    } catch (err) {
      saveDraft();
      setStatus('Could not commit rows. Review edits were saved on this device. Check your connection and try again.', 'error');
    } finally {
      btn.disabled = false;
    }
  });

  window.addEventListener('resize', updateTableFrame);
  restoreDraftIfFresh();
  render();
  updateTableFrame();
})();



