/* Controlled Portal reporting UI. It only sends keys from the server catalogue. */
(() => {
  'use strict';

  const state = {
    catalogue: null,
    definitions: [],
    current: null,
    result: null,
    relationships: null,
    charts: [],
    tg: null,
    canManage: false,
    root: null,
  };

  const api = () => window.PortalMiniAppApi || {};
  const escapeHtml = (value) => String(value ?? '').replace(/[&<>'"]/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;',
  }[char]));
  const requestId = () => window.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  const root = () => document.getElementById('portal-reports-root');

  function fields() {
    return (state.catalogue?.categories || []).flatMap((category) => category.fields.map((field) => ({ ...field, category: category.label })));
  }
  function field(key) { return fields().find((item) => item.key === key); }
  function label(key) { return field(key)?.label || key; }
  function selectedFields() { return state.current?.configuration?.fields || []; }
  function selectedReportFields(predicate = () => true) { return selectedFields().map(field).filter(Boolean).filter(predicate); }
  function toast(message, type = '') { window.MiniAppUtils?.showToast?.(document.getElementById('toast'), message, { className: `toast show ${type ? `${type}-toast` : ''}`, resetClassName: 'toast', timeout: 3500 }); }

  function emptyDraft() {
    return {
      title: 'New Portal report', source_key: 'portal_cases', version: 0,
      configuration: { fields: ['customer_name', 'branch', 'workflow_state', 'credit_decision', 'created_at'], filters: [], ordering: { field: 'customer_name', direction: 'asc' } },
      charts: [], is_new: true,
    };
  }

  function optionMarkup(items, selected, empty = 'Choose') {
    return `<option value="">${escapeHtml(empty)}</option>${items.map((item) => `<option value="${escapeHtml(item.key || item)}"${String(item.key || item) === String(selected || '') ? ' selected' : ''}>${escapeHtml(item.label || item)}</option>`).join('')}`;
  }
  function valueToInput(value) { return Array.isArray(value) ? value.join(' | ') : String(value ?? ''); }
  function filterRowsMarkup() {
    const filters = state.current?.configuration?.filters || [];
    const available = selectedReportFields((item) => item.filterable);
    if (!filters.length) return '<p class="portal-report-empty-copy">No filters. This report reads every case inside your current access scope.</p>';
    return filters.map((filter, index) => {
      const activeField = field(filter.field) || available[0];
      const operators = activeField?.operators || [];
      const inputHint = filter.operator === 'between' ? 'Start | end' : filter.operator === 'in' ? 'One | two | three' : 'Value';
      return `<div class="portal-report-filter-row" data-report-filter-row="${index}">
        <select data-report-filter-field>${optionMarkup(available, filter.field, 'Field')}</select>
        <select data-report-filter-operator>${optionMarkup(operators, filter.operator, 'Operator')}</select>
        <input data-report-filter-value value="${escapeHtml(valueToInput(filter.value))}" placeholder="${inputHint}">
        <button type="button" class="btn btn-secondary" data-report-action="remove-filter" data-index="${index}" aria-label="Remove filter">Remove</button>
      </div>`;
    }).join('');
  }
  function chartRowsMarkup() {
    const charts = state.current?.charts || [];
    if (!charts.length) return '<p class="portal-report-empty-copy">No charts yet. Add a chart after selecting its category/date and numeric fields.</p>';
    const dimensions = selectedReportFields((item) => item.groupable);
    const metrics = selectedReportFields((item) => item.type === 'number');
    return charts.map((chart, index) => {
      const dateBucket = chart.chart_type === 'line' ? `<select data-report-chart-bucket>${optionMarkup([{ key: 'day', label: 'By day' }, { key: 'month', label: 'By month' }], chart.date_bucket, 'Date grouping')}</select>` : '';
      return `<div class="portal-report-chart-row" data-report-chart-row="${index}">
        <input data-report-chart-title value="${escapeHtml(chart.title || '')}" maxlength="100" placeholder="Chart title (optional)">
        <select data-report-chart-type>${optionMarkup([{ key: 'bar', label: 'Bar' }, { key: 'doughnut', label: 'Doughnut' }, { key: 'line', label: 'Line' }], chart.chart_type, 'Chart type')}</select>
        <select data-report-chart-dimension>${optionMarkup(dimensions, chart.dimension_field, 'Category/date')}</select>
        <select data-report-chart-aggregation>${optionMarkup([{ key: 'count', label: 'Count cases' }, { key: 'sum', label: 'Sum amount' }, { key: 'average', label: 'Average amount' }], chart.aggregation, 'Aggregation')}</select>
        <select data-report-chart-metric>${optionMarkup(metrics, chart.metric_field, 'Numeric field')}</select>
        ${dateBucket}
        <button type="button" class="btn btn-secondary" data-report-action="remove-chart" data-index="${index}" aria-label="Remove chart">Remove</button>
      </div>`;
    }).join('');
  }
  function relationshipMarkup() {
    if (!state.canManage || !state.relationships) return '';
    const isolated = state.relationships.unlinked_identity_only || [];
    return `<details class="portal-report-data-boundary"><summary>Data-source boundaries</summary>
      <p><strong>${escapeHtml(state.relationships.root || 'Portal customer cases')}</strong> is the current report source. Related collections are available only through named safe counts; they cannot be flattened into case rows.</p>
      <p>Not joined in v1: ${escapeHtml(isolated.map((item) => item.replace(/^core\./, '')).join(', ') || 'none')}.</p>
    </details>`;
  }
  function editorMarkup() {
    if (!state.current) return '<section class="portal-report-editor portal-report-placeholder"><h2>Select a report</h2><p>Create a controlled report or choose one to run it. Only approved Portal fields are available.</p></section>';
    const current = state.current;
    const editable = state.canManage;
    const categories = state.catalogue?.categories || [];
    return `<section class="portal-report-editor">
      <div class="portal-report-editor-heading"><div><span class="settings-eyebrow">${current.is_new ? 'NEW DEFINITION' : `VERSION ${escapeHtml(current.version)}`}</span><h2>${escapeHtml(current.title)}</h2><p>Live data respects the viewer’s current Portal access scope. Exports contain the same scoped data.</p></div>
      ${current.is_new || !editable ? '' : '<button type="button" class="btn btn-secondary" data-report-action="archive">Archive</button>'}</div>
      <label class="portal-report-title">Report title<input id="portal-report-title" maxlength="100" value="${escapeHtml(current.title)}" ${editable ? '' : 'readonly'}></label>
      <div class="portal-report-field-catalog"><h3>Report fields</h3><p>Choose up to ${escapeHtml(state.catalogue?.limits?.fields || 18)} fields. Sensitive case comments, media, GPS and cross-workflow records are intentionally excluded.</p>
        <div class="portal-report-field-grid">${categories.map((category) => `<fieldset><legend>${escapeHtml(category.label)}</legend>${category.fields.map((item) => `<label><input type="checkbox" data-report-field value="${escapeHtml(item.key)}" ${selectedFields().includes(item.key) ? 'checked' : ''} ${editable ? '' : 'disabled'}><span>${escapeHtml(item.label)}${item.derived ? ' <small>Derived</small>' : ''}</span></label>`).join('')}</fieldset>`).join('')}</div>
      </div>
      <section class="portal-report-section"><div class="portal-report-section-heading"><div><h3>Filters</h3><p>Filters narrow live Portal cases; they cannot broaden branch access.</p></div>${editable ? '<button type="button" class="btn btn-secondary" data-report-action="add-filter">Add filter</button>' : ''}</div>${filterRowsMarkup()}</section>
      <section class="portal-report-section portal-report-ordering"><h3>Ordering</h3><div><select id="portal-report-order-field">${optionMarkup(selectedReportFields((item) => item.sortable && !item.derived), current.configuration?.ordering?.field, 'Order field')}</select><select id="portal-report-order-direction">${optionMarkup([{ key: 'asc', label: 'Ascending' }, { key: 'desc', label: 'Descending' }], current.configuration?.ordering?.direction, 'Direction')}</select></div></section>
      <section class="portal-report-section"><div class="portal-report-section-heading"><div><h3>Charts</h3><p>Chart categories must be selected report fields. A count chart has no numeric metric.</p></div>${editable ? '<button type="button" class="btn btn-secondary" data-report-action="add-chart">Add chart</button>' : ''}</div>${chartRowsMarkup()}</section>
      <div class="portal-report-actions">
        ${editable ? `<button type="button" class="btn btn-primary" data-report-action="save">${current.is_new ? 'Save report' : 'Save changes'}</button>` : ''}
        ${current.is_new ? '' : '<button type="button" class="btn btn-secondary" data-report-action="run">Run live report</button><button type="button" class="btn btn-secondary" data-report-action="export">Download XLSX</button>'}
      </div>${relationshipMarkup()}
    </section>`;
  }
  function listMarkup() {
    const reports = state.definitions;
    return `<aside class="portal-report-list"><div class="portal-report-list-heading"><div><span class="settings-eyebrow">SAVED REPORTS</span><h2>Definitions</h2></div>${state.canManage ? '<button type="button" class="btn btn-primary" data-report-action="new">New</button>' : ''}</div>
      ${reports.length ? reports.map((report) => `<button type="button" class="portal-report-list-item${String(state.current?.id || '') === String(report.id) ? ' is-active' : ''}" data-report-action="select" data-id="${escapeHtml(report.id)}"><strong>${escapeHtml(report.title)}</strong><span>${escapeHtml(report.configuration?.fields?.length || 0)} fields · ${escapeHtml(report.charts?.length || 0)} charts · v${escapeHtml(report.version)}</span></button>`).join('') : '<p class="portal-report-empty-copy">No reports saved yet.</p>'}
    </aside>`;
  }
  function resultMarkup() {
    const result = state.result;
    if (!result) return '';
    const table = `<div class="portal-report-table-wrap"><table class="portal-report-table"><thead><tr>${result.columns.map((item) => `<th>${escapeHtml(item.label)}</th>`).join('')}</tr></thead><tbody>${result.rows.length ? result.rows.map((row) => `<tr>${result.columns.map((column) => `<td>${escapeHtml(formatValue(row[column.key], column.type))}</td>`).join('')}</tr>`).join('') : `<tr><td colspan="${result.columns.length}">No cases match this report.</td></tr>`}</tbody></table></div>`;
    const pagination = result.pagination?.pages > 1 ? `<div class="portal-report-pager"><span>Page ${escapeHtml(result.pagination.page)} of ${escapeHtml(result.pagination.pages)} · ${escapeHtml(result.total_rows)} rows</span><div><button type="button" class="btn btn-secondary" data-report-action="page" data-page="${Math.max(1, result.pagination.page - 1)}" ${result.pagination.page <= 1 ? 'disabled' : ''}>Previous</button><button type="button" class="btn btn-secondary" data-report-action="page" data-page="${Math.min(result.pagination.pages, result.pagination.page + 1)}" ${result.pagination.page >= result.pagination.pages ? 'disabled' : ''}>Next</button></div></div>` : `<p class="portal-report-result-copy">${escapeHtml(result.total_rows)} live row${result.total_rows === 1 ? '' : 's'}${result.total_rows > result.shown_rows_limit ? `; table is limited to the first ${escapeHtml(result.shown_rows_limit)}` : ''}.</p>`;
    return `<section class="portal-report-results"><div class="portal-report-results-heading"><div><span class="settings-eyebrow">LIVE RESULT</span><h2>${escapeHtml(result.definition?.title || 'Report')}</h2><p>Generated ${escapeHtml(formatValue(result.run_at, 'date'))}. This preview is not a document and does not save a data snapshot.</p></div></div><div id="portal-report-charts" class="portal-report-charts">${(result.charts || []).map((chart, index) => `<article class="portal-report-chart"><h3>${escapeHtml(chart.title)}</h3><p>${escapeHtml(chart.metric_label)} by ${escapeHtml(chart.dimension_label)}${chart.truncated ? ' · first 100 groups' : ''}</p><canvas id="portal-report-chart-${index}" aria-label="${escapeHtml(chart.title)}"></canvas></article>`).join('')}</div>${table}${pagination}</section>`;
  }
  function render() {
    state.root = root();
    if (!state.root) return;
    state.charts.forEach((chart) => chart.destroy?.());
    state.charts = [];
    state.root.innerHTML = `<div class="portal-reports-layout">${listMarkup()}${editorMarkup()}</div>${resultMarkup()}`;
    renderCharts();
  }
  function renderCharts() {
    const result = state.result;
    if (!result || !window.Chart) return;
    (result.charts || []).forEach((chart, index) => {
      const canvas = document.getElementById(`portal-report-chart-${index}`);
      if (!canvas) return;
      state.charts.push(new window.Chart(canvas, {
        type: chart.type,
        data: { labels: chart.labels, datasets: [{ label: chart.metric_label, data: chart.values, borderColor: '#078b86', backgroundColor: ['#078b86', '#1d91d1', '#f2a93b', '#7367d8', '#3ea56d', '#d55c5c'], borderWidth: 2, fill: chart.type === 'line' ? false : undefined }] },
        options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: chart.type === 'doughnut' } }, scales: chart.type === 'doughnut' ? {} : { y: { beginAtZero: true, ticks: { precision: 0 } } } },
      }));
    });
  }
  function formatValue(value, type) {
    if (value === null || value === undefined || value === '') return '—';
    if (type === 'date') {
      const parsed = new Date(value);
      return Number.isNaN(parsed.getTime()) ? String(value) : parsed.toLocaleDateString('en-GB', { day: '2-digit', month: 'long', year: 'numeric' });
    }
    if (type === 'number') return String(value).replace(/\.00$/, '');
    return String(value);
  }
  function readDraft() {
    const current = state.current;
    if (!current) return null;
    const config = {
      fields: [...document.querySelectorAll('[data-report-field]:checked')].map((node) => node.value),
      filters: [...document.querySelectorAll('[data-report-filter-row]')].map((row) => {
        const reportField = row.querySelector('[data-report-filter-field]')?.value || '';
        const operator = row.querySelector('[data-report-filter-operator]')?.value || '';
        const raw = row.querySelector('[data-report-filter-value]')?.value || '';
        const value = ['between', 'in'].includes(operator) ? raw.split('|').map((item) => item.trim()).filter(Boolean) : raw.trim();
        return { field: reportField, operator, value };
      }),
      ordering: { field: document.getElementById('portal-report-order-field')?.value || '', direction: document.getElementById('portal-report-order-direction')?.value || 'asc' },
    };
    const charts = [...document.querySelectorAll('[data-report-chart-row]')].map((row) => ({
      title: row.querySelector('[data-report-chart-title]')?.value || '', chart_type: row.querySelector('[data-report-chart-type]')?.value || '',
      dimension_field: row.querySelector('[data-report-chart-dimension]')?.value || '', aggregation: row.querySelector('[data-report-chart-aggregation]')?.value || '',
      metric_field: row.querySelector('[data-report-chart-metric]')?.value || '', date_bucket: row.querySelector('[data-report-chart-bucket]')?.value || '',
    }));
    return { title: document.getElementById('portal-report-title')?.value || '', configuration: config, charts, version: current.version };
  }
  function snapshotDraft() {
    const draft = readDraft();
    if (!draft || !state.current) return;
    state.current = { ...state.current, ...draft };
  }
  async function load() {
    state.root = root();
    if (!state.root) return;
    state.root.innerHTML = '<div class="empty-state"><div class="spinner-inline"></div><div class="es-sub">Loading controlled reports...</div></div>';
    const [catalogueResult, reportsResult, relationshipResult] = await Promise.all([
      api().apiFetch('/reports/catalogue/', {}, state.tg), api().apiFetch('/reports/', {}, state.tg),
      state.canManage
        ? api().apiFetch('/reports/relationships/', {}, state.tg)
        : Promise.resolve({ ok: true, data: { ok: true, relationship_summary: null } }),
    ]);
    if (!catalogueResult.ok || !catalogueResult.data?.ok || !reportsResult.ok || !reportsResult.data?.ok) {
      state.root.innerHTML = `<div class="empty-state"><div class="es-title">Reports unavailable</div><div class="es-sub">${escapeHtml(catalogueResult.data?.error || reportsResult.data?.error || 'Check your IT reporting access and try again.')}</div></div>`;
      return;
    }
    state.catalogue = catalogueResult.data.catalogue;
    state.definitions = reportsResult.data.reports || [];
    state.relationships = relationshipResult.data?.relationship_summary || null;
    state.current = state.definitions[0] || null;
    state.result = null;
    render();
  }
  async function select(id) {
    const result = await api().apiFetch(`/reports/${encodeURIComponent(id)}/`, {}, state.tg);
    if (!result.ok || !result.data?.ok) throw new Error(result.data?.error || 'Could not load this report.');
    state.current = result.data.report;
    state.result = null;
    render();
  }
  async function save() {
    const draft = readDraft();
    if (!draft) return;
    const isNew = Boolean(state.current?.is_new);
    const path = isNew ? '/reports/' : `/reports/${encodeURIComponent(state.current.id)}/`;
    const result = await api().postJson(path, draft, state.tg);
    if (!result.ok || !result.data?.ok) throw new Error(result.data?.error || 'Could not save the report.');
    state.current = result.data.report;
    state.current.is_new = false;
    const existing = state.definitions.findIndex((item) => item.id === state.current.id);
    if (existing >= 0) state.definitions.splice(existing, 1, state.current); else state.definitions.push(state.current);
    state.definitions.sort((a, b) => a.title.localeCompare(b.title));
    state.result = null;
    render();
    toast(result.data.message || 'Report saved.', 'success');
  }
  async function run(page = 1) {
    if (!state.current?.id) return;
    const result = await api().postJson(`/reports/${encodeURIComponent(state.current.id)}/run/`, { page }, state.tg);
    if (!result.ok || !result.data?.ok) throw new Error(result.data?.error || 'Could not run the report.');
    state.result = result.data.result;
    state.current = result.data.result.definition;
    render();
  }
  async function archive() {
    if (!state.current?.id || !window.confirm('Archive this report definition? Its audit history remains available.')) return;
    const result = await api().postJson(`/reports/${encodeURIComponent(state.current.id)}/archive/`, { version: state.current.version }, state.tg);
    if (!result.ok || !result.data?.ok) throw new Error(result.data?.error || 'Could not archive the report.');
    state.definitions = state.definitions.filter((item) => item.id !== state.current.id);
    state.current = state.definitions[0] || null;
    state.result = null;
    render();
    toast('Report archived.', 'success');
  }
  async function exportXlsx() {
    if (!state.current?.id) return;
    const key = requestId();
    const response = await fetch(`${api().apiBase()}/reports/${encodeURIComponent(state.current.id)}/export/`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', ...api().initDataHeader(state.tg), 'X-Request-ID': key, 'Idempotency-Key': key },
      body: JSON.stringify({ client_request_id: key }),
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.error || 'Could not download the report.');
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url; link.download = 'portal-report.xlsx';
    document.body.appendChild(link); link.click(); link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    toast('XLSX download ready.', 'success');
  }
  function addFilter() {
    snapshotDraft();
    const candidate = selectedReportFields((item) => item.filterable)[0];
    if (!candidate) throw new Error('Select a filterable report field first.');
    state.current.configuration.filters.push({ field: candidate.key, operator: candidate.operators[0], value: '' });
    render();
  }
  function addChart() {
    snapshotDraft();
    const dimension = selectedReportFields((item) => item.groupable)[0];
    if (!dimension) throw new Error('Select a category or date report field first.');
    state.current.charts.push({ title: '', chart_type: 'bar', dimension_field: dimension.key, aggregation: 'count', metric_field: '', date_bucket: '' });
    render();
  }
  function bindEvents() {
    if (document.documentElement.dataset.portalReportsBound) return;
    document.documentElement.dataset.portalReportsBound = 'true';
    document.addEventListener('click', async (event) => {
      const button = event.target.closest('[data-report-action]');
      if (!button || !root()?.contains(button)) return;
      event.preventDefault();
      try {
        const action = button.dataset.reportAction;
        if (action === 'new') { state.current = emptyDraft(); state.result = null; render(); }
        else if (action === 'select') await select(button.dataset.id);
        else if (action === 'add-filter') addFilter();
        else if (action === 'remove-filter') { snapshotDraft(); state.current.configuration.filters.splice(Number(button.dataset.index), 1); render(); }
        else if (action === 'add-chart') addChart();
        else if (action === 'remove-chart') { snapshotDraft(); state.current.charts.splice(Number(button.dataset.index), 1); render(); }
        else if (action === 'save') await save();
        else if (action === 'run') await run();
        else if (action === 'page') await run(Number(button.dataset.page || 1));
        else if (action === 'archive') await archive();
        else if (action === 'export') await exportXlsx();
      } catch (error) { toast(error.message || 'That report action could not be completed.', 'error'); }
    });
    document.addEventListener('change', (event) => {
      if (!root()?.contains(event.target)) return;
      if (event.target.matches('[data-report-field]')) {
        snapshotDraft();
        if (state.current.configuration.fields.length > (state.catalogue?.limits?.fields || 18)) {
          event.target.checked = false;
          state.current.configuration.fields = state.current.configuration.fields.filter((item) => item !== event.target.value);
          toast(`Choose at most ${state.catalogue?.limits?.fields || 18} fields.`, 'error');
        }
        render();
        return;
      }
      if (event.target.matches('[data-report-chart-type], [data-report-chart-aggregation]')) {
        snapshotDraft();
        const row = event.target.closest('[data-report-chart-row]');
        const chart = state.current?.charts?.[Number(row?.dataset.reportChartRow)];
        if (!chart) return;
        if (chart.aggregation === 'count') chart.metric_field = '';
        if (chart.chart_type === 'line') {
          const dateDimension = selectedReportFields((item) => item.type === 'date')[0];
          if (dateDimension) chart.dimension_field = dateDimension.key;
          chart.date_bucket = chart.date_bucket || 'day';
        } else {
          chart.date_bucket = '';
        }
        render();
      }
    });
  }

  window.PortalMiniAppReports = {
    async load(options = {}) {
      state.tg = options.tg || state.tg;
      state.canManage = Boolean(options.canManage);
      bindEvents();
      return load();
    },
  };
})();
