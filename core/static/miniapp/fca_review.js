(function () {
  const tg = window.MiniAppTelegram ? window.MiniAppTelegram.init() : null;
  const payload = JSON.parse(document.getElementById('batch-data').textContent);
  let rows = payload.rows || [];
  const statusValues = payload.status_values || [];
  const body = document.getElementById('rowsBody');
  const statusEl = document.getElementById('status');
  const fields = ['Customer Name', 'ID Number', 'Primary Phone', 'Secondary Phone', 'Location', 'HB Staff', 'Deposit', 'Jawabu Visit Date', 'Status', 'Comment', 'Review Notes', 'Source'];

  function isReview(row) {
    return row['Import Status'] === 'review_needed' || String(row['Review Notes'] || '').trim();
  }

  function editable(name) {
    return name !== 'Source' && name !== 'Review Notes';
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
          select.addEventListener('change', () => { row[name] = select.value; });
          td.appendChild(select);
        } else if (name === 'Comment') {
          const input = document.createElement('textarea');
          input.value = row[name] || '';
          input.addEventListener('input', () => { row[name] = input.value; });
          td.appendChild(input);
        } else {
          const input = document.createElement('input');
          input.value = row[name] || '';
          input.readOnly = !editable(name);
          input.addEventListener('input', () => { row[name] = input.value; });
          td.appendChild(input);
        }
        tr.appendChild(td);
      });
      body.appendChild(tr);
    });
    renderCounts();
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
  }

  document.getElementById('approveAll').addEventListener('click', () => {
    rows.forEach((row) => { if (!isReview(row)) row.approved = true; });
    render();
  });

  document.getElementById('skipReview').addEventListener('click', () => {
    rows.forEach((row) => { if (isReview(row)) row.approved = false; });
    render();
  });

  document.getElementById('commitBtn').addEventListener('click', async () => {
    const btn = document.getElementById('commitBtn');
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
      setStatus('Could not commit rows. Check your connection and try again.', 'error');
    } finally {
      btn.disabled = false;
    }
  });

  render();
})();
