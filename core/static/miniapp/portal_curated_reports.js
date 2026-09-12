/* Fixed, capability-scoped Portal reports. The custom designer remains dormant. */
(() => {
  'use strict';

  const api = () => window.PortalMiniAppApi || {};
  const state = { preset: 'pipeline', page: 1, result: null, loading: false, tg: null };
  const labels = { pipeline: 'Pipeline workload', outcomes: 'Visit & decision outcomes', finance: 'Orders & finance' };
  const escapeHtml = value => String(value ?? '').replace(/[&<>'"]/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[char]));
  const root = () => document.getElementById('portal-reports-root');
  const requestId = () => window.crypto?.randomUUID?.() || `portal-report-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  const filters = () => ({
    from: document.getElementById('portal-report-from')?.value || '',
    to: document.getElementById('portal-report-to')?.value || '',
    branch: document.getElementById('portal-report-branch')?.value || '',
    county: document.getElementById('portal-report-county')?.value || '',
    stage: document.getElementById('portal-report-stage')?.value || '',
  });
  function format(value, type) {
    if (value === null || value === undefined || value === '') return '—';
    if (type === 'number') {
      const number = Number(value);
      return Number.isFinite(number) ? number.toLocaleString('en-KE', {maximumFractionDigits: 2}) : escapeHtml(value);
    }
    if (type === 'date') {
      const parsed = new Date(value);
      return Number.isNaN(parsed.getTime()) ? escapeHtml(value) : parsed.toLocaleDateString('en-GB');
    }
    return escapeHtml(value);
  }
  function toast(message, tone = 'info') { window.PortalAppShell?.showToast?.(message, tone); }
  function tabs() {
    return `<div class="portal-curated-tabs" role="tablist">${Object.entries(labels).map(([key, label]) => `<button type="button" role="tab" data-curated-preset="${key}" aria-selected="${state.preset === key}" class="${state.preset === key ? 'active' : ''}">${escapeHtml(label)}</button>`).join('')}</div>`;
  }
  function filterMarkup(result) {
    const applied = result?.applied_filters || {};
    const options = result?.filter_options || {};
    const period = result?.period || {};
    const select = (id, title, values, selected) => `<label><span>${title}</span><select id="${id}"><option value="">All</option>${(values || []).map(value => `<option${String(value) === String(selected || '') ? ' selected' : ''}>${escapeHtml(value)}</option>`).join('')}</select></label>`;
    return `<form id="portal-curated-filters" class="portal-curated-filters">
      ${state.preset === 'pipeline' ? '' : `<label><span>From</span><input id="portal-report-from" type="date" value="${escapeHtml(applied.from || period.from || '')}"></label><label><span>To</span><input id="portal-report-to" type="date" value="${escapeHtml(applied.to || period.to || '')}"></label>`}
      ${select('portal-report-branch', 'Branch', options.branches, applied.branch)}
      ${select('portal-report-county', 'County', options.counties, applied.county)}
      ${state.preset === 'pipeline' ? `<label><span>Stage</span><select id="portal-report-stage"><option value="">All stages</option>${['jbl_visit','credit','final_review','order','ordered','deferred','rejected'].map(value => `<option value="${value}"${value === applied.stage ? ' selected' : ''}>${escapeHtml(value.replaceAll('_', ' '))}</option>`).join('')}</select></label>` : ''}
      <button class="btn btn-secondary" type="submit"><i data-lucide="filter"></i> Apply</button>
      <button class="btn btn-secondary" type="button" data-curated-export><i data-lucide="download"></i> XLSX</button>
    </form>`;
  }
  function chartMarkup(chart) {
    if (chart.error) return `<article class="portal-curated-chart"><strong>${escapeHtml(chart.title)}</strong><p>${escapeHtml(chart.error)}</p></article>`;
    const max = Math.max(1, ...(chart.values || []).map(Number));
    return `<article class="portal-curated-chart"><strong>${escapeHtml(chart.title)}</strong><div>${(chart.labels || []).map((label, index) => `<span><em>${escapeHtml(label)}</em><i style="--bar:${Math.max(2, Number(chart.values[index] || 0) / max * 100)}%"></i><b>${format(chart.values[index], 'number')}</b></span>`).join('') || '<p>No data for these filters.</p>'}</div>${chart.notice ? `<small>${escapeHtml(chart.notice)}</small>` : ''}</article>`;
  }
  function render() {
    const target = root(); if (!target) return;
    const result = state.result;
    if (!result) { target.innerHTML = `${tabs()}<div class="empty-state"><div class="spinner-inline"></div><div class="es-sub">Loading ${escapeHtml(labels[state.preset])}…</div></div>`; return; }
    const pages = result.pagination || {page:1, pages:1};
    target.innerHTML = `${tabs()}${filterMarkup(result)}
      <div class="portal-curated-summary">${Object.entries(result.summary || {}).map(([label, value]) => `<div><strong>${format(value, typeof value === 'string' && /^\d+(\.\d+)?$/.test(value) ? 'number' : '')}</strong><span>${escapeHtml(label)}</span></div>`).join('')}</div>
      <div class="portal-curated-charts">${(result.charts || []).map(chartMarkup).join('')}</div>
      <section class="portal-curated-results"><div class="stage-summary-heading"><h2>Supporting cases</h2><span>${Number(result.total_rows || 0).toLocaleString()} in scope</span></div><div class="miniapp-table-zoom" data-miniapp-table-zoom="portal-curated"><span>Table size</span><button type="button" data-miniapp-table-zoom-out aria-label="Zoom table out">−</button><button type="button" data-miniapp-table-zoom-reset>100%</button><button type="button" data-miniapp-table-zoom-in aria-label="Zoom table in">+</button></div><div class="portal-report-table-wrap" data-miniapp-table-zoom-target><table class="portal-report-table"><thead><tr>${result.columns.map(column => `<th>${escapeHtml(column.label)}</th>`).join('')}</tr></thead><tbody>${result.rows.map(row => `<tr>${result.columns.map(column => `<td>${format(row[column.key], column.type)}</td>`).join('')}</tr>`).join('') || `<tr><td colspan="${result.columns.length}">No cases match these filters.</td></tr>`}</tbody></table></div>
      <div class="pagination"><button class="btn btn-secondary" data-curated-page="${pages.page - 1}" ${pages.page <= 1 ? 'disabled' : ''}>Previous</button><span>${pages.page} / ${pages.pages}</span><button class="btn btn-secondary" data-curated-page="${pages.page + 1}" ${pages.page >= pages.pages ? 'disabled' : ''}>Next</button></div></section>`;
    window.lucide?.createIcons?.();
    window.MiniAppComponents?.bindTableZoom?.(target.querySelector('[data-miniapp-table-zoom="portal-curated"]'), 'portal-curated-table-zoom');
  }
  async function load(page = 1, suppliedFilters = null) {
    if (state.loading || !root()) return;
    state.loading = true; state.page = page; if (!state.result) render();
    try {
      const response = await api().postJson('/reports/workspace/', {preset: state.preset, filters: suppliedFilters || filters(), page, client_request_id: requestId()}, state.tg);
      if (!response.ok || !response.data?.ok) throw new Error(response.data?.error || 'The report could not be loaded.');
      state.result = response.data.result; render();
    } catch (error) {
      if (root()) root().innerHTML = `${tabs()}<div class="empty-state"><div class="es-title">Report unavailable</div><div class="es-sub">${escapeHtml(error.message)}</div><button class="btn btn-secondary" data-curated-retry>Retry</button></div>`;
    } finally { state.loading = false; }
  }
  async function exportXlsx() {
    const key = requestId();
    const response = await fetch(`${api().apiBase()}/reports/workspace/export/`, {method:'POST', headers:{'Content-Type':'application/json', ...api().initDataHeader(state.tg), 'X-Request-ID':key, 'Idempotency-Key':key}, body:JSON.stringify({preset:state.preset, filters:filters(), client_request_id:key})});
    if (!response.ok) { const payload = await response.json().catch(() => ({})); throw new Error(payload.error || 'The report could not be exported.'); }
    const url = URL.createObjectURL(await response.blob()); const link = document.createElement('a'); link.href = url; link.download = `portal-${state.preset}-report.xlsx`; document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000); toast('XLSX download ready.', 'success');
  }
  document.addEventListener('click', event => {
    if (!root()?.contains(event.target)) return;
    const preset = event.target.closest('[data-curated-preset]'); if (preset) { state.preset = preset.dataset.curatedPreset; state.result = null; return load(1, {}); }
    const page = event.target.closest('[data-curated-page]'); if (page && !page.disabled) return load(Number(page.dataset.curatedPage));
    if (event.target.closest('[data-curated-retry]')) return load(state.page);
    if (event.target.closest('[data-curated-export]')) exportXlsx().catch(error => toast(error.message, 'error'));
  });
  document.addEventListener('submit', event => { if (event.target.id === 'portal-curated-filters') { event.preventDefault(); load(1); } });
  window.PortalMiniAppReports = { load(options = {}) { state.tg = options.tg || state.tg; state.result = null; return load(1, {}); }, unmount() { state.result = null; }, canHandleBack() { return false; }, handleBack() { return false; } };
})();
