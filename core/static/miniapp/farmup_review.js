(function () {
  const tg = window.MiniAppTelegram ? window.MiniAppTelegram.init() : null;
  const utils = window.MiniAppUtils || {};
  const payload = JSON.parse(document.getElementById('batch-data').textContent);
  let rows = payload.rows || [];
  // Batches created before Application Action was introduced have no stored
  // value. Normalize them before review/highlight calculations so the visible
  // default is also the actual row value.
  rows.forEach((row) => {
    if (isBlank(row['Application Action'])) row['Application Action'] = 'update_existing';
  });
  const batchId = payload.batch_id;
  const token = payload.token;
  const initData = tg ? tg.initData : '';
  const fields = ['Customer Name', 'National ID', 'Primary Phone', 'Secondary Phone', 'Application Action', 'Additional Unit Reason', 'County', 'HBG Visit Date', 'Deposit Paid to HB', 'HB Sales Person', 'Cleaning Notes'];
  const body = document.getElementById('rowsBody');
  const statusEl = document.getElementById('status');
  const rowSearch = document.getElementById('rowSearch');
  const reviewOnlyFilter = document.getElementById('reviewOnlyFilter');
  const reviewMetricFilter = document.getElementById('reviewMetricFilter');
  const visibleCount = document.getElementById('visibleCount');
  let searchText = '';
  let reviewOnly = false;
  const draft = utils.createServerDraft ? utils.createServerDraft({
    workflow: 'farmup_review',
    contextKey: batchId,
    initData: () => tg ? tg.initData || '' : '',
    token: () => token || '',
    onSaved: () => setStatus('Draft saved securely. Commit when the review is complete.', ''),
    onError: (error) => {
      if (navigator.onLine === false) setStatus('Offline. Changes remain open here; reconnect to save the draft.', 'error');
      else if (!error.conflict) setStatus(error.message || 'Draft could not be saved.', 'error');
    },
  }) : null;

  function isBlank(value) {
    return !String(value || '').trim();
  }

  function isReview(row) {
    return row['Import Status'] === 'review_needed' || fields.some((fieldName) => (
      !['Cleaning Notes', 'Application Action', 'Additional Unit Reason'].includes(fieldName) && isBlank(row[fieldName])
    )) || (row['Application Action'] === 'create_additional_unit' && isBlank(row['Additional Unit Reason']));
  }

  function rowNotes(row) {
    return String(row['Cleaning Notes'] || '').toLowerCase();
  }

  function fieldHasProblem(row, fieldName) {
    // Application Action has a safe default and Cleaning Notes is purely
    // informational. Neither field should receive validation highlighting.
    if (fieldName === 'Application Action') {
      return !['update_existing', 'create_additional_unit'].includes(row[fieldName] || 'update_existing');
    }
    if (fieldName === 'Additional Unit Reason') {
      return row['Application Action'] === 'create_additional_unit' && isBlank(row[fieldName]);
    }
    if (fieldName === 'Cleaning Notes') return false;
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
    const candidateRows = reviewOnly ? rows.filter(isReview) : rows;
    if (!needle) return candidateRows;
    const terms = needle.split(/\s+/).filter(Boolean);
    return candidateRows.filter((row) => {
      const haystack = rowSearchText(row);
      return terms.every((term) => haystack.includes(term));
    });
  }

  function render() {
    body.innerHTML = '';
    const filteredRows = visibleRows();
    filteredRows.forEach((row, index) => {
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
        let input;
        if (name === 'Application Action') {
          input = document.createElement('select');
          [['update_existing', 'Update existing / first unit'], ['create_additional_unit', 'Create next linked unit']].forEach(([value, label]) => {
            const option = document.createElement('option'); option.value = value; option.textContent = label; input.appendChild(option);
          });
        } else {
          input = name === 'Cleaning Notes' ? document.createElement('textarea') : document.createElement('input');
        }
        if (fieldHasProblem(row, name)) {
          td.classList.add('field-error');
          input.classList.add('field-error-input');
          input.setAttribute('aria-invalid', 'true');
        }
        input.value = row[name] || (name === 'Application Action' ? 'update_existing' : '');
        if (name === 'Additional Unit Reason') {
          input.placeholder = row['Application Action'] === 'create_additional_unit'
            ? 'Why is this another unit?'
            : 'Required only for another unit';
          input.disabled = row['Application Action'] !== 'create_additional_unit';
        }
        input.addEventListener('input', () => { row[name] = input.value; saveDraft(); });
        if (name === 'Application Action') {
          input.addEventListener('change', () => {
            row[name] = input.value;
            if (input.value !== 'create_additional_unit') row['Additional Unit Reason'] = '';
            saveDraft();
            render();
          });
        }
        td.appendChild(input);
        tr.appendChild(td);
      });
      body.appendChild(tr);
    });
    if (!filteredRows.length) {
      const tr = document.createElement('tr');
      const td = document.createElement('td');
      td.colSpan = fields.length + 2;
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
      const reviewText = reviewOnly ? 'review row(s)' : 'row(s)';
      visibleCount.textContent = searchText.trim()
        ? `Showing ${shown} of ${rows.length} ${reviewText}`
        : (reviewOnly ? `Showing ${shown} review row(s)` : 'Showing all rows');
    }
    if (reviewOnlyFilter) {
      reviewOnlyFilter.classList.toggle('active', reviewOnly);
      reviewOnlyFilter.setAttribute('aria-pressed', reviewOnly ? 'true' : 'false');
    }
    if (reviewMetricFilter) {
      reviewMetricFilter.classList.toggle('active', reviewOnly);
      reviewMetricFilter.setAttribute('aria-pressed', reviewOnly ? 'true' : 'false');
    }
  }

  function setStatus(text, kind) {
    statusEl.textContent = text;
    statusEl.className = 'status ' + (kind || '');
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

  rowSearch?.addEventListener('input', () => {
    searchText = rowSearch.value || '';
    render();
  });

  reviewOnlyFilter?.addEventListener('click', () => {
    reviewOnly = !reviewOnly;
    render();
  });

  reviewMetricFilter?.addEventListener('click', () => {
    reviewOnly = !reviewOnly;
    render();
  });

  document.getElementById('clearSearch')?.addEventListener('click', () => {
    searchText = '';
    reviewOnly = false;
    if (rowSearch) rowSearch.value = '';
    render();
    rowSearch?.focus();
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
        // The response is now the canonical outstanding set. Remove the old
        // draft so a later recovery cannot reintroduce committed rows.
        clearDraft();
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
      clearDraft();
      utils.haptic?.('success');
      if (tg) setTimeout(() => tg.close(), 900);
    } catch (err) {
      saveDraft();
      setStatus('Could not commit rows. Review edits remain open; reconnect to save the secure draft and retry.', 'error');
      utils.haptic?.('error');
    } finally {
      btn.disabled = false;
    }
  });

  render();
  restoreDraft();
})();




