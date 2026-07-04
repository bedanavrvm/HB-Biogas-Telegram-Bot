(function () {
  const tg = window.MiniAppTelegram ? window.MiniAppTelegram.init() : null;
  const payload = JSON.parse(document.getElementById('batch-data').textContent);
  let rows = payload.rows || [];
  const batchId = payload.batch_id;
  const token = payload.token;
  const initData = tg ? tg.initData : '';
  const fields = ['Customer Name', 'National ID', 'Primary Phone', 'Secondary Phone', 'County', 'HBG Visit Date', 'Deposit Paid to HB', 'HB Sales Person', 'Lead Source', 'Installation Status', 'Cleaning Notes'];
  const body = document.getElementById('rowsBody');
  const statusEl = document.getElementById('status');

  function isReview(row) {
    return row['Import Status'] === 'review_needed' || String(row['Cleaning Notes'] || '').trim();
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
        const input = name === 'Cleaning Notes' ? document.createElement('textarea') : document.createElement('input');
        input.value = row[name] || '';
        input.addEventListener('input', () => { row[name] = input.value; });
        td.appendChild(input);
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
      setStatus('Could not commit rows. Check your connection and try again.', 'error');
    } finally {
      btn.disabled = false;
    }
  });

  render();
})();
