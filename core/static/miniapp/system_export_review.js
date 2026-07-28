(function () {
  const tg = window.MiniAppTelegram ? window.MiniAppTelegram.init() : null;
  const payload = JSON.parse(document.getElementById('batch-data').textContent);
  let rows = payload.rows || [];
  const batchId = payload.batch_id;
  const token = payload.token;
  const draftKey = 'systemExportReviewDraft:' + batchId;
  const body = document.getElementById('rowsBody');
  const statusEl = document.getElementById('status');
  const searchEl = document.getElementById('rowSearch');
  const visibleCount = document.getElementById('visibleCount');
  let searchText = '';
  let reviewOnly = false;

  const fields = ['Customer ID', 'Name', 'Mobile No', 'ID NO', 'Branch', 'Loan Officer', 'Product Name', 'LGF Balance'];

  function escapeHtml(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
  }

  function isReview(row) {
    return row['Import Status'] !== 'ready' || !String(row['Matched Farmer ID'] || '').trim();
  }

  function searchTextFor(row) {
    return [
      ...fields,
      'Import Status', 'Match Basis', 'Matched Customer', 'Cleaning Notes', 'Source Row',
    ].map((field) => String(row[field] || '').toLowerCase()).join(' ');
  }

  function visibleRows() {
    const source = reviewOnly ? rows.filter(isReview) : rows;
    const terms = searchText.trim().toLowerCase().split(/\s+/).filter(Boolean);
    if (!terms.length) return source;
    return source.filter((row) => terms.every((term) => searchTextFor(row).includes(term)));
  }

  function setStatus(message, kind) {
    statusEl.textContent = message;
    statusEl.className = 'status ' + (kind || '');
  }

  function render() {
    body.innerHTML = '';
    const filtered = visibleRows();
    filtered.forEach((row) => {
      const tr = document.createElement('tr');
      tr.className = !row.approved ? 'row-skipped' : (isReview(row) ? 'row-review' : '');
      const useCell = document.createElement('td');
      const checkbox = document.createElement('input');
      checkbox.type = 'checkbox';
      checkbox.checked = !!row.approved;
      checkbox.title = isReview(row) ? 'This row still needs review' : 'Include this row';
      checkbox.addEventListener('change', () => { row.approved = checkbox.checked; saveDraft(); renderCounts(); });
      useCell.appendChild(checkbox);
      tr.appendChild(useCell);

      fields.forEach((field) => {
        const td = document.createElement('td');
        const input = document.createElement('input');
        input.value = row[field] || '';
        input.title = field;
        input.addEventListener('input', () => { row[field] = input.value; saveDraft(); });
        td.appendChild(input);
        tr.appendChild(td);
      });

      const matchCell = document.createElement('td');
      const select = document.createElement('select');
      const empty = document.createElement('option');
      empty.value = '';
      empty.textContent = isReview(row) ? 'Select match' : 'Matched';
      select.appendChild(empty);
      (row['Match Candidates'] || []).forEach((candidate) => {
        const option = document.createElement('option');
        option.value = candidate.id;
        option.textContent = `${candidate.customer_name || 'Unnamed'}${candidate.customer_no ? ` / ${candidate.customer_no}` : ''}`;
        option.selected = candidate.id === row['Matched Farmer ID'];
        select.appendChild(option);
      });
      select.value = row['Matched Farmer ID'] || '';
      select.addEventListener('change', () => {
        row['Matched Farmer ID'] = select.value;
        const candidate = (row['Match Candidates'] || []).find((item) => item.id === select.value);
        row['Matched Customer'] = candidate ? candidate.customer_name : '';
        if (candidate) {
          row['Import Status'] = 'ready';
          row['Match Basis'] = 'manual_review';
        }
        saveDraft();
        render();
      });
      matchCell.appendChild(select);
      const help = document.createElement('small');
      help.textContent = row['Match Basis'] ? `Basis: ${row['Match Basis']}` : 'No exact match';
      matchCell.appendChild(help);
      tr.appendChild(matchCell);

      const notesCell = document.createElement('td');
      const notes = document.createElement('textarea');
      notes.value = row['Cleaning Notes'] || '';
      notes.addEventListener('input', () => { row['Cleaning Notes'] = notes.value; saveDraft(); });
      notesCell.appendChild(notes);
      tr.appendChild(notesCell);
      body.appendChild(tr);
    });
    if (!filtered.length) {
      const tr = document.createElement('tr');
      const td = document.createElement('td');
      td.colSpan = fields.length + 3;
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
    document.getElementById('reviewCount').textContent = rows.filter(isReview).length;
    document.getElementById('skippedCount').textContent = rows.filter((row) => !row.approved).length;
    const shown = visibleRows().length;
    visibleCount.textContent = reviewOnly ? `Showing ${shown} review row(s)` : `Showing ${shown} of ${rows.length} row(s)`;
  }

  function saveDraft() {
    try { localStorage.setItem(draftKey, JSON.stringify({ savedAt: Date.now(), rows })); } catch (error) { /* optional device draft */ }
  }

  function restoreDraft() {
    try {
      const draft = JSON.parse(localStorage.getItem(draftKey) || 'null');
      if (draft && Array.isArray(draft.rows) && Date.now() - Number(draft.savedAt || 0) < 7 * 24 * 60 * 60 * 1000) rows = draft.rows;
    } catch (error) { localStorage.removeItem(draftKey); }
  }

  document.getElementById('approveAll').addEventListener('click', () => { rows.forEach((row) => { if (!isReview(row)) row.approved = true; }); saveDraft(); render(); });
  document.getElementById('skipReview').addEventListener('click', () => { rows.forEach((row) => { if (isReview(row)) row.approved = false; }); saveDraft(); render(); });
  document.getElementById('reviewOnlyFilter')?.addEventListener('click', () => { reviewOnly = !reviewOnly; render(); });
  document.getElementById('reviewMetricFilter')?.addEventListener('click', () => { reviewOnly = !reviewOnly; render(); });
  searchEl?.addEventListener('input', () => { searchText = searchEl.value || ''; render(); });
  document.getElementById('clearSearch')?.addEventListener('click', () => { searchText = ''; reviewOnly = false; searchEl.value = ''; render(); });
  document.getElementById('commitBtn').addEventListener('click', async () => {
    const button = document.getElementById('commitBtn');
    button.disabled = true;
    setStatus('Committing selected system-export rows...', '');
    try {
      const response = await fetch('/api/jawabu-farmers/review/commit/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ batch_id: batchId, token, init_data: tg ? tg.initData : '', rows }),
      });
      const result = await response.json();
      if (!response.ok || !result.success) throw new Error(result.message || 'Commit failed.');
      localStorage.removeItem(draftKey);
      rows = result.rows || [];
      setStatus(result.message || 'System export committed.', 'success');
      render();
    } catch (error) {
      setStatus(error.message || 'Commit failed. Check the rows and retry.', 'error');
    } finally { button.disabled = false; }
  });

  restoreDraft();
  render();
  if (tg) { tg.ready(); tg.expand(); }
})();
