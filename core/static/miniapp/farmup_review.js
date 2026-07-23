(function () {
  const tg = window.MiniAppTelegram ? window.MiniAppTelegram.init() : null;
  const payload = JSON.parse(document.getElementById('batch-data').textContent);
  let rows = payload.rows || [];
  const batchId = payload.batch_id;
  const token = payload.token;
  const initData = tg ? tg.initData : '';
  const draftKey = 'farmupReviewDraft:' + batchId;
  const draftMaxAgeMs = 7 * 24 * 60 * 60 * 1000;
  const fields = ['Customer Name', 'National ID', 'Primary Phone', 'Secondary Phone', 'County', 'HBG Visit Date', 'Deposit Paid to HB', 'HB Sales Person', 'Cleaning Notes'];
  const body = document.getElementById('rowsBody');
  const statusEl = document.getElementById('status');
  const rowSearch = document.getElementById('rowSearch');
  const visibleCount = document.getElementById('visibleCount');
  let searchText = '';

  function isReview(row) {
    return row['Import Status'] === 'review_needed';
  }

  function rowNotes(row) {
    return String(row['Cleaning Notes'] || '').toLowerCase();
  }

  function isBlank(value) {
    return !String(value || '').trim();
  }

  function fieldHasProblem(row, fieldName) {
    if (fieldName !== 'Cleaning Notes' && isBlank(row[fieldName])) return true;
    if (!isReview(row)) return false;
    const notes = rowNotes(row);
    if (fieldName === 'Customer Name') {
      return isBlank(row[fieldName]) || notes.includes('customer name');
    }
    if (fieldName === 'National ID') {
      return isBlank(row[fieldName]) || notes.includes('national id');
    }
    if (fieldName === 'Primary Phone') {
      return notes.includes('primary phone') || (isBlank(row[fieldName]) && notes.includes('phone'));
    }
    if (fieldName === 'Secondary Phone') {
      return notes.includes('secondary phone');
    }
    if (fieldName === 'Cleaning Notes') {
      return true;
    }
    return isBlank(row[fieldName]) && notes.includes(fieldName.toLowerCase());
  }

  function rowSearchText(row) {
    const values = [
      row['Customer Name'],
      row['National ID'],
      row['Primary Phone'],
      row['Secondary Phone'],
      row['County'],
      row['Constituency'],
      row['Village'],
      row['HBG Visit Date'],
      row['Deposit Paid to HB'],
      row['HB Sales Person'],
      row['Import Status'],
      row['Cleaning Notes'],
      row['Source Row'],
      row['Source File'],
    ];
    return values.map((value) => String(value || '').toLowerCase()).join(' ');
  }

  function visibleRows() {
    const needle = searchText.trim().toLowerCase();
    if (!needle) return rows;
    const terms = needle.split(/\s+/).filter(Boolean);
    return rows.filter((row) => {
      const haystack = rowSearchText(row);
      return terms.every((term) => haystack.includes(term));
    });
  }

  function render() {
    body.innerHTML = '';
    const filteredRows = visibleRows();
    filteredRows.forEach((row) => {
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
        const input = name === 'Cleaning Notes' ? document.createElement('textarea') : document.createElement('input');
        if (fieldHasProblem(row, name)) {
          td.classList.add('field-error');
          input.classList.add('field-error-input');
          input.setAttribute('aria-invalid', 'true');
        }
        input.value = row[name] || '';
        input.addEventListener('input', () => { row[name] = input.value; saveDraft(); });
        td.appendChild(input);
        tr.appendChild(td);
      });
      body.appendChild(tr);
    });
    if (!filteredRows.length) {
      const tr = document.createElement('tr');
      const td = document.createElement('td');
      td.colSpan = fields.length + 1;
      td.className = 'no-results';
      td.textContent = 'No rows match the current search.';
      tr.appendChild(td);
      body.appendChild(tr);
    }
    renderCounts();
  }

  function renderCounts() {
    document.getElementById('totalCount').textContent = rows.length;
    document.getElementById('approvedCount').textContent = rows.filter((row) => row.approved).length;
    document.getElementById('reviewCount').textContent = rows.filter((row) => row.approved && isReview(row)).length;
    document.getElementById('skippedCount').textContent = rows.filter((row) => !row.approved).length;
    const shown = visibleRows().length;
    if (visibleCount) {
      visibleCount.textContent = searchText.trim()
        ? `Showing ${shown} of ${rows.length} row(s)`
        : 'Showing all rows';
    }
  }

  function setStatus(text, kind) {
    statusEl.textContent = text;
    statusEl.className = 'status ' + (kind || '');
  }

  function canUseStorage() {
    try {
      const probe = '__farmup_review_probe__';
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
      setStatus('Unsaved review draft restored from this device.', '');
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

  rowSearch?.addEventListener('input', () => {
    searchText = rowSearch.value || '';
    render();
  });

  document.getElementById('clearSearch')?.addEventListener('click', () => {
    searchText = '';
    if (rowSearch) rowSearch.value = '';
    render();
    rowSearch?.focus();
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
    setStatus('Committing approved rows...', '');
    try {
      const response = await fetch('/api/jawabu-farmers/review/commit/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ batch_id: batchId, token, init_data: initData, rows }),
      });
      const result = await response.json();
      if (!response.ok || !result.success) {
        setStatus(result.message || 'Some rows still need correction.', 'error');
        if (result.rows) {
          rows = result.rows;
          render();
        }
        return;
      }
      const remaining = Array.isArray(result.rows) ? result.rows : [];
      if (remaining.length) {
        rows = remaining;
        render();
        const sync = result.sheet_sync || {};
        const syncText = sync.enabled
          ? ` Master sync: ${sync.created || 0} created, ${sync.updated || 0} updated, ${sync.conflicts || 0} conflict(s).`
          : ' Master sync is not enabled for this group.';
        setStatus(`Committed ${result.committed} row(s). ${remaining.length} row(s) remain for review.${syncText}`, 'ok');
        return;
      }
      const sync = result.sheet_sync || {};
      const syncText = sync.enabled
        ? ` Master sync: ${sync.created || 0} created, ${sync.updated || 0} updated, ${sync.conflicts || 0} conflict(s).`
        : ' Master sync is not enabled for this group.';
      setStatus(`Committed ${result.committed} row(s). All rows are complete.${syncText}`, 'ok');
      if (tg) setTimeout(() => tg.close(), 900);
    } catch (err) {
      saveDraft();
      setStatus('Could not commit rows. Review edits were saved on this device. Check your connection and try again.', 'error');
    } finally {
      btn.disabled = false;
    }
  });

  restoreDraftIfFresh();
  render();
})();




