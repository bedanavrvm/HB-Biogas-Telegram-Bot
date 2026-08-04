/* Controlled Portal reporting UI. It only sends keys from the server catalogue. */
(() => {
  'use strict';

  const EDITOR_STEPS = ['fields', 'filters', 'review'];
  const DRAFT_STORAGE_PREFIX = 'portal-report-draft:v1:';
  const state = {
    catalogue: null,
    catalogueSearch: '',
    definitions: [],
    current: null,
    result: null,
    relationships: null,
    charts: [],
    editorPreviewChart: null,
    editorPreview: { index: -1, key: '', status: 'idle', data: null, error: '' },
    editorPreviewTimer: null,
    editorPreviewController: null,
    editorPreviewSequence: 0,
    activeChartIndex: 0,
    chartObserver: null,
    chartResizeTimer: null,
    viewportEventsBound: false,
    viewportHandler: null,
    themeHandler: null,
    loadVersion: 0,
    runError: '',
    tg: null,
    canManage: false,
    root: null,
    route: { view: 'catalogue', reportId: '', step: '' },
    fieldSearch: '',
  };

  const api = () => window.PortalMiniAppApi || {};
  const escapeHtml = (value) => String(value ?? '').replace(/[&<>'"]/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;',
  }[char]));
  const requestId = () => window.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  const root = () => document.getElementById('portal-reports-root');
  const toast = (message, type = '') => window.MiniAppUtils?.showToast?.(
    document.getElementById('toast'), message,
    { className: `toast show ${type ? `${type}-toast` : ''}`, resetClassName: 'toast', timeout: 3500 },
  );

  function requestShellNavigationSync() {
    window.dispatchEvent(new Event('portal:reports-route-change'));
  }

  function syncEditorShell() {
    document.body.classList.toggle('portal-report-editor-active', state.route.view === 'edit');
  }

  function telegramViewportHeight() {
    return Number(state.tg?.viewportStableHeight)
      || Number(state.tg?.viewportHeight)
      || Number(window.visualViewport?.height)
      || Number(window.innerHeight)
      || 640;
  }

  function chartHeight() {
    return Math.max(190, Math.min(300, Math.round(telegramViewportHeight() * 0.31)));
  }

  function readRoute() {
    const screen = document.getElementById('portal-screen');
    const view = screen?.dataset.reportView || 'catalogue';
    const reportStep = screen?.dataset.reportStep || '';
    return {
      view: ['catalogue', 'detail', 'edit', 'run'].includes(view) ? view : 'catalogue',
      reportId: screen?.dataset.reportId || '',
      step: EDITOR_STEPS.includes(reportStep) ? reportStep : (view === 'edit' ? 'fields' : ''),
    };
  }

  function loadingMarkup(message = 'Loading controlled reports...') {
    return `<div class="empty-state"><div class="spinner-inline"></div><div class="es-sub">${escapeHtml(message)}</div></div>`;
  }

  function retryMarkup(title, message, action = 'retry-load') {
    return `<section class="portal-report-placeholder portal-report-retry-state"><h2>${escapeHtml(title)}</h2><p>${escapeHtml(message)}</p><div class="portal-report-actions"><button type="button" class="btn btn-primary" data-report-action="${escapeHtml(action)}">Try again</button><button type="button" class="btn btn-secondary" data-report-action="catalogue">Back to reports</button></div></section>`;
  }

  function showLoadFailure(message) {
    const target = root();
    if (!target) return;
    target.innerHTML = retryMarkup('Reports unavailable', message || 'Check your connection and try again.');
  }

  function isCurrentLoad(version, target) {
    return state.loadVersion === version && root() === target;
  }

  function canReuseEditorDraft(nextRoute) {
    // Fields, Filters, and Review are route-backed for deep links and Back,
    // but switching between them must not refetch the catalogue or discard
    // the browser-only draft. The next route has already been authorized by
    // the server; this only reuses data that is still in the same live Portal
    // screen and will still be validated on save.
    return Boolean(
      state.catalogue
      && state.current
      && state.route.view === 'edit'
      && nextRoute.view === 'edit'
      && state.route.reportId === nextRoute.reportId
    );
  }

  function routeUrl(view = 'catalogue', reportId = '', step = 'fields') {
    const base = '/portal/s/reports/';
    if (view === 'catalogue') return base;
    if (view === 'edit' && !reportId) return `${base}new/${EDITOR_STEPS.includes(step) ? step : 'fields'}/`;
    const safeId = encodeURIComponent(reportId || '');
    if (!safeId) return base;
    if (view === 'edit') return `${base}${safeId}/edit/${EDITOR_STEPS.includes(step) ? step : 'fields'}/`;
    if (view === 'run') return `${base}${safeId}/run/`;
    return `${base}${safeId}/`;
  }

  function navigate(view = 'catalogue', reportId = '', step = 'fields') {
    if (state.route.view === 'edit') snapshotDraft();
    const url = routeUrl(view, reportId, step);
    if (window.PortalAppShell?.navigateUrl) {
      window.PortalAppShell.navigateUrl(url);
      return;
    }
    window.location.assign(url);
  }

  function fields() {
    return (state.catalogue?.categories || []).flatMap((category) => (
      category.fields.map((item) => ({ ...item, category: category.label }))
    ));
  }
  function field(key) { return fields().find((item) => item.key === key); }
  function label(key) { return field(key)?.label || key; }
  function selectedFields() { return state.current?.configuration?.fields || []; }
  function selectedReportFields(predicate = () => true) { return selectedFields().map(field).filter(Boolean).filter(predicate); }
  function editorStep() { return state.route.step || 'fields'; }
  function editorStepIndex(step = editorStep()) { return EDITOR_STEPS.indexOf(step); }
  function stepTitle(step) { return ({ fields: 'Basics & fields', filters: 'Filters & ordering', review: 'Charts & review' }[step] || step); }

  function emptyDraft() {
    return {
      title: 'New Portal report', source_key: 'portal_cases', version: 0,
      configuration: {
        fields: ['customer_name', 'branch', 'workflow_state', 'credit_decision', 'created_at'],
        filters: [],
        ordering: { field: 'customer_name', direction: 'asc' },
      },
      charts: [], is_new: true,
    };
  }

  function draftKey(report = state.current) {
    return `${DRAFT_STORAGE_PREFIX}${report?.id || state.route.reportId || 'new'}`;
  }
  function readLocalDraft(report = state.current) {
    try {
      const raw = window.sessionStorage?.getItem(draftKey(report));
      return raw ? JSON.parse(raw) : null;
    } catch (_) {
      return null;
    }
  }
  function persistDraft() {
    if (!state.current || state.route.view !== 'edit') return;
    const payload = {
      id: state.current.id || '',
      is_new: Boolean(state.current.is_new),
      title: state.current.title || '',
      source_key: state.current.source_key || 'portal_cases',
      version: Number(state.current.version || 0),
      configuration: state.current.configuration || {},
      charts: state.current.charts || [],
    };
    try { window.sessionStorage?.setItem(draftKey(state.current), JSON.stringify(payload)); } catch (_) { /* Storage is optional. */ }
  }
  function clearLocalDraft(report = state.current) {
    try { window.sessionStorage?.removeItem(draftKey(report)); } catch (_) { /* Storage is optional. */ }
  }
  function restoreLocalDraft(serverReport, { isNew = false } = {}) {
    const stored = readLocalDraft(serverReport || { id: '' });
    if (!stored) return serverReport;
    if (isNew && stored.is_new) return { ...emptyDraft(), ...stored, is_new: true };
    if (serverReport && stored.id === serverReport.id && Number(stored.version) === Number(serverReport.version)) {
      return { ...serverReport, ...stored, id: serverReport.id, is_new: false };
    }
    clearLocalDraft(serverReport || { id: '' });
    return serverReport;
  }

  function optionMarkup(items, selected, empty = 'Choose') {
    return `<option value="">${escapeHtml(empty)}</option>${items.map((item) => {
      const value = item.key || item;
      return `<option value="${escapeHtml(value)}"${String(value) === String(selected || '') ? ' selected' : ''}>${escapeHtml(item.label || item)}</option>`;
    }).join('')}`;
  }
  function valueToInput(value) { return Array.isArray(value) ? value.join(' | ') : String(value ?? ''); }
  function formatDateTime(value) {
    if (!value) return 'Not recorded';
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? String(value) : parsed.toLocaleString('en-GB', {
      day: '2-digit', month: 'long', year: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false,
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
  function fieldChips(keys, { removable = false } = {}) {
    return keys.length
      ? `<div class="portal-report-chips">${keys.map((key) => removable
        ? `<button type="button" data-report-action="remove-field" data-field="${escapeHtml(key)}" aria-label="Remove ${escapeHtml(label(key))}">${escapeHtml(label(key))}<span aria-hidden="true">×</span></button>`
        : `<span>${escapeHtml(label(key))}</span>`).join('')}</div>`
      : '<p class="portal-report-empty-copy">No fields selected.</p>';
  }

  function compactFieldSummary(keys) {
    const labels = keys.map(label);
    if (!labels.length) return 'None';
    const visible = labels.slice(0, 3).join(', ');
    return `${visible}${labels.length > 3 ? ` +${labels.length - 3} more` : ''}`;
  }

  function compactFilterSummary(filters) {
    if (!filters.length) return 'None';
    return filters.map((filter) => `${label(filter.field)} ${filter.operator} ${valueToInput(filter.value) || '—'}`).join(' · ');
  }
  function filterSummary(filters) {
    if (!filters.length) return '<p class="portal-report-empty-copy">No filters. The report reads cases inside the viewer’s approved Portal scope.</p>';
    return `<ul class="portal-report-summary-list">${filters.map((filter) => `<li><strong>${escapeHtml(label(filter.field))}</strong><span>${escapeHtml(filter.operator)} ${escapeHtml(valueToInput(filter.value) || '—')}</span></li>`).join('')}</ul>`;
  }

  function filterRowsMarkup() {
    const filters = state.current?.configuration?.filters || [];
    const available = selectedReportFields((item) => item.filterable);
    if (!filters.length) return '<p class="portal-report-empty-copy">No filters yet. Add one only when it helps staff answer a defined operational question.</p>';
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

  function charting() {
    return state.catalogue?.charting || { types: [], aggregations: [], preview_buckets: 12 };
  }
  function chartTypeRule(key) { return charting().types.find((item) => item.key === key); }
  function chartAggregationRule(key) { return charting().aggregations.find((item) => item.key === key); }
  function chartDimensions() { return selectedReportFields((item) => item.chart_dimension); }
  function chartTypesForDimension(dimension) {
    return dimension ? charting().types.filter((item) => (item.dimension_types || []).includes(dimension.type)) : [];
  }
  function chartMetricsForAggregation(aggregation) {
    return selectedReportFields((item) => item.chart_metric && (item.aggregations || []).includes(aggregation));
  }
  function chartAggregations() {
    return charting().aggregations.filter((item) => !item.metric_required || chartMetricsForAggregation(item.key).length);
  }
  function chartTitle(chart) {
    if (String(chart?.title || '').trim()) return String(chart.title).trim();
    const aggregation = chartAggregationRule(chart?.aggregation)?.label || 'Case count';
    return `${aggregation} by ${label(chart?.dimension_field || '')}`;
  }
  function normalizeChart(chart) {
    const dimensions = chartDimensions();
    if (!dimensions.length) return chart;
    let dimension = dimensions.find((item) => item.key === chart.dimension_field);
    if (!dimension) {
      dimension = dimensions[0];
      chart.dimension_field = dimension.key;
    }
    const types = chartTypesForDimension(dimension);
    if (!types.some((item) => item.key === chart.chart_type)) chart.chart_type = types[0]?.key || '';
    if (!chartAggregations().some((item) => item.key === chart.aggregation)) chart.aggregation = 'count';
    const aggregation = chartAggregationRule(chart.aggregation);
    if (aggregation?.metric_required) {
      const metrics = chartMetricsForAggregation(chart.aggregation);
      if (!metrics.some((item) => item.key === chart.metric_field)) chart.metric_field = metrics[0]?.key || '';
    } else chart.metric_field = '';
    if (chartTypeRule(chart.chart_type)?.requires_date_bucket) {
      if (!['day', 'month'].includes(chart.date_bucket)) chart.date_bucket = '';
    } else chart.date_bucket = '';
    return chart;
  }
  function chartPreviewReadiness(chart) {
    const dimension = field(chart?.dimension_field || '');
    const type = chartTypeRule(chart?.chart_type || '');
    const aggregation = chartAggregationRule(chart?.aggregation || '');
    if (!dimension?.chart_dimension || !selectedFields().includes(dimension.key)) return 'Choose an approved operational field to compare.';
    if (!type || !chartTypesForDimension(dimension).some((item) => item.key === type.key)) return 'Choose a chart display that fits the selected field.';
    if (!aggregation) return 'Choose how this chart should measure cases.';
    if (aggregation.metric_required) {
      const metric = field(chart.metric_field || '');
      if (!metric?.chart_metric || !chartMetricsForAggregation(chart.aggregation).some((item) => item.key === metric.key)) return 'Choose a compatible financial or derived metric.';
    }
    if (type.requires_date_bucket && !['day', 'month'].includes(chart.date_bucket)) return 'Choose whether this date trend is grouped by day or by month.';
    return '';
  }
  function chartPreviewKey(chart) {
    return JSON.stringify({ configuration: state.current?.configuration || {}, chart: {
      chart_type: chart?.chart_type || '', dimension_field: chart?.dimension_field || '',
      aggregation: chart?.aggregation || '', metric_field: chart?.metric_field || '',
      date_bucket: chart?.date_bucket || '', title: chart?.title || '',
    } });
  }
  function resetEditorPreview() {
    window.clearTimeout(state.editorPreviewTimer);
    state.editorPreviewTimer = null;
    state.editorPreviewController?.abort?.();
    state.editorPreviewController = null;
    state.editorPreviewSequence += 1;
    state.editorPreview = { index: -1, key: '', status: 'idle', data: null, error: '' };
    state.editorPreviewChart?.destroy?.();
    state.editorPreviewChart = null;
  }
  function editorPreviewMarkup(chart, index) {
    const readiness = chartPreviewReadiness(chart);
    if (readiness) return `<div class="portal-report-chart-preview is-awaiting"><strong>Live preview</strong><span>${escapeHtml(readiness)}</span></div>`;
    const preview = state.editorPreview;
    if (preview.index !== index || preview.key !== chartPreviewKey(chart) || preview.status === 'idle') return '<div class="portal-report-chart-preview is-loading"><span class="spinner-inline"></span><span>Preparing a live aggregate…</span></div>';
    if (preview.status === 'loading') return '<div class="portal-report-chart-preview is-loading"><span class="spinner-inline"></span><span>Refreshing the live aggregate…</span></div>';
    if (preview.status === 'error') return `<div class="portal-report-chart-preview is-error"><strong>Preview unavailable</strong><span>${escapeHtml(preview.error || 'Check the selected fields and try again.')}</span><button type="button" class="btn btn-secondary" data-report-action="retry-chart-preview">Try again</button></div>`;
    const data = preview.data || {};
    return `<div class="portal-report-chart-preview is-ready" data-report-editor-preview><div class="portal-report-chart-preview-heading"><div><strong>Live preview</strong><span>${escapeHtml(data.metric_label || '')} by ${escapeHtml(data.dimension_label || '')} · up to ${escapeHtml(charting().preview_buckets || 12)} groups</span></div></div>${data.notice ? `<p class="portal-report-chart-preview-notice">${escapeHtml(data.notice)}</p>` : ''}<canvas id="portal-report-editor-chart-preview" aria-label="${escapeHtml(data.title || chartTitle(chart))}"></canvas></div>`;
  }

  function chartRowsMarkup() {
    const charts = state.current?.charts || [];
    if (!charts.length) return '<p class="portal-report-empty-copy">No charts yet. Reports remain useful without charts; add only a chart that supports an operational decision.</p>';
    const dimensions = chartDimensions();
    if (state.activeChartIndex >= charts.length) state.activeChartIndex = Math.max(0, charts.length - 1);
    return charts.map((chart, index) => {
      normalizeChart(chart);
      const dimension = field(chart.dimension_field);
      const typeOptions = chartTypesForDimension(dimension);
      const aggregation = chartAggregationRule(chart.aggregation);
      const metrics = chartMetricsForAggregation(chart.aggregation);
      const dateBucket = chartTypeRule(chart.chart_type)?.requires_date_bucket
        ? `<label class="portal-report-chart-choice">Group date by<select data-report-chart-bucket>${optionMarkup([{ key: 'day', label: 'Day' }, { key: 'month', label: 'Month' }], chart.date_bucket, 'Choose')}</select></label>`
        : '';
      return `<details class="portal-report-chart-card" data-report-chart-row="${index}"${index === state.activeChartIndex ? ' open' : ''}>
        <summary><span><strong>${escapeHtml(chartTitle(chart))}</strong><small>${escapeHtml(label(chart.dimension_field))} · ${escapeHtml(aggregation?.label || chart.aggregation)}</small></span><em>Chart ${index + 1}</em></summary>
        <div class="portal-report-chart-card-body">
          <input type="hidden" data-report-chart-type value="${escapeHtml(chart.chart_type)}">
          <label class="portal-report-chart-title">Chart title <small>Optional</small><input data-report-chart-title value="${escapeHtml(chart.title || '')}" maxlength="100" placeholder="Use the suggested title"></label>
          <div class="portal-report-chart-choices">
            <label class="portal-report-chart-choice">Compare by<select data-report-chart-dimension>${optionMarkup(dimensions, chart.dimension_field, 'Choose an operational field')}</select></label>
            <label class="portal-report-chart-choice">Measure<select data-report-chart-aggregation>${optionMarkup(chartAggregations(), chart.aggregation, 'Choose')}</select></label>
            ${aggregation?.metric_required ? `<label class="portal-report-chart-choice">Metric<select data-report-chart-metric>${optionMarkup(metrics, chart.metric_field, 'Choose a numeric field')}</select></label>` : ''}
            ${dateBucket}
          </div>
          <div class="portal-report-chart-type-choice"><span>Show as</span><div>${typeOptions.map((item) => `<button type="button" data-report-chart-type-choice="${escapeHtml(item.key)}" data-index="${index}" class="${item.key === chart.chart_type ? 'is-active' : ''}">${escapeHtml(item.label)}</button>`).join('')}</div></div>
          ${index === state.activeChartIndex ? editorPreviewMarkup(chart, index) : ''}
          <div class="portal-report-chart-card-actions"><button type="button" class="portal-report-remove-chart" data-report-action="remove-chart" data-index="${index}"><i data-lucide="trash-2" aria-hidden="true"></i>Remove chart</button></div>
        </div>
      </details>`;
    }).join('');
  }

  function relationshipMarkup() {
    if (!state.canManage || !state.relationships) return '';
    const isolated = state.relationships.unlinked_identity_only || [];
    return `<details class="portal-report-data-boundary"><summary>Data-source boundary</summary>
      <p><strong>${escapeHtml(state.relationships.root || 'Portal customer cases')}</strong> is the report source. Related collections are available only through named safe counts; they cannot be flattened into case rows.</p>
      <p>Not joined: ${escapeHtml(isolated.map((item) => item.replace(/^core\./, '')).join(', ') || 'none')}.</p>
    </details>`;
  }

  function stepperMarkup() {
    const active = editorStep();
    const activeIndex = editorStepIndex(active);
    return `<nav class="portal-report-stepper" aria-label="Report setup steps"><div><strong>Step ${activeIndex + 1} of ${EDITOR_STEPS.length}</strong><span>${escapeHtml(stepTitle(active))}</span></div><div class="portal-report-step-dots">${EDITOR_STEPS.map((step, index) => `<button type="button" class="${step === active ? 'is-active' : ''}" data-report-action="step" data-report-step="${step}" aria-label="Go to step ${index + 1}: ${escapeHtml(stepTitle(step))}"${!state.canManage ? ' disabled' : ''}><span aria-hidden="true"></span></button>`).join('')}</div></nav>`;
  }
  function draftNoticeMarkup() {
    return '<p class="portal-report-draft-note">Draft changes stay only in this browser until you save or discard them. They are not yet a report definition or audit event.</p>';
  }
  function editorFieldsMarkup(current, editable) {
    const categories = state.catalogue?.categories || [];
    const categoryMarkup = categories.map((category) => {
      const selectedCount = category.fields.filter((item) => selectedFields().includes(item.key)).length;
      return `<details class="portal-report-field-category" data-report-field-category data-selected-count="${selectedCount}"${selectedCount ? ' open' : ''}><summary><span>${escapeHtml(category.label)}</span><strong>${selectedCount}/${category.fields.length}</strong></summary><div>${category.fields.map((item) => `<label data-report-field-label data-search="${escapeHtml(`${item.label} ${category.label}`.toLowerCase())}"><input type="checkbox" data-report-field value="${escapeHtml(item.key)}" ${selectedFields().includes(item.key) ? 'checked' : ''} ${editable ? '' : 'disabled'}><span>${escapeHtml(item.label)}${item.derived ? ' <small>Derived</small>' : ''}</span></label>`).join('')}</div></details>`;
    }).join('');
    return `<section class="portal-report-editor-step" data-report-editor-step="fields">
      <label class="portal-report-title">Report title<input id="portal-report-title" maxlength="100" value="${escapeHtml(current.title)}" ${editable ? '' : 'readonly'}></label>
      <div class="portal-report-section-heading"><div><h3>Report fields</h3><p>Choose the information that staff need to see. Sensitive comments, media, GPS, and cross-workflow data are excluded.</p></div><strong class="portal-report-selection-count">${escapeHtml(selectedFields().length)} / ${escapeHtml(state.catalogue?.limits?.fields || 18)}</strong></div>
      <label class="portal-report-field-search">Find a field<input type="search" data-report-field-search value="${escapeHtml(state.fieldSearch)}" placeholder="Search approved fields"></label>
      <div class="portal-report-selected-fields"><span>Selected</span>${fieldChips(selectedFields(), { removable: editable })}</div>
      <div class="portal-report-field-grid">${categoryMarkup}</div><p class="portal-report-empty-copy" data-report-field-search-empty hidden>No approved field matches that search.</p>
    </section>`;
  }
  function editorFiltersMarkup(current, editable) {
    const filters = current.configuration?.filters || [];
    const filtersContent = filters.length
      ? filterRowsMarkup()
      : `<div class="portal-report-empty-inline"><span>No filters applied.</span>${editable ? '<button type="button" class="btn btn-secondary" data-report-action="add-filter">Add filter</button>' : ''}</div>`;
    return `<section class="portal-report-editor-step" data-report-editor-step="filters">
      <section class="portal-report-section portal-report-section-first"><div class="portal-report-section-heading"><div><h3>Filters</h3><p>Filters only narrow cases already inside your approved Portal scope.</p></div>${filters.length && editable ? '<button type="button" class="btn btn-secondary" data-report-action="add-filter">Add filter</button>' : ''}</div>${filtersContent}</section>
      <section class="portal-report-section portal-report-ordering"><div class="portal-report-section-heading"><div><h3>Ordering</h3><p>Set the order staff will see in the live report.</p></div></div><div><select id="portal-report-order-field" ${editable ? '' : 'disabled'}>${optionMarkup(selectedReportFields((item) => item.sortable && !item.derived), current.configuration?.ordering?.field, 'Order field')}</select><select id="portal-report-order-direction" ${editable ? '' : 'disabled'}>${optionMarkup([{ key: 'asc', label: 'Ascending' }, { key: 'desc', label: 'Descending' }], current.configuration?.ordering?.direction, 'Direction')}</select></div></section>
    </section>`;
  }
  function editorReviewMarkup(current, editable) {
    return `<section class="portal-report-editor-step" data-report-editor-step="review">
      <section class="portal-report-review-summary" aria-label="Report definition summary"><div><span>Fields</span><strong>${escapeHtml(compactFieldSummary(selectedFields()))}</strong></div><div><span>Filters</span><strong>${escapeHtml(compactFilterSummary(current.configuration?.filters || []))}</strong></div><div><span>Ordering</span><strong>${escapeHtml(label(current.configuration?.ordering?.field || ''))} · ${escapeHtml(current.configuration?.ordering?.direction || 'asc')}</strong></div></section>
      <section class="portal-report-section portal-report-section-first"><div class="portal-report-section-heading"><div><h3>Charts</h3><p>Optional. Categories and metrics must be selected report fields.</p></div>${editable ? '<button type="button" class="btn btn-secondary" data-report-action="add-chart">Add chart</button>' : ''}</div>${chartRowsMarkup()}</section>
    </section>`;
  }
  function editorActionsMarkup(current, editable) {
    const currentIndex = editorStepIndex();
    const previous = EDITOR_STEPS[currentIndex - 1];
    const next = EDITOR_STEPS[currentIndex + 1];
    return `<div class="portal-report-actions portal-report-editor-actions portal-report-wizard-actions">
      <button type="button" class="btn btn-secondary" data-report-action="back">${previous ? `Back: ${escapeHtml(stepTitle(previous))}` : 'Back to reports'}</button>
      ${editable && currentIndex < EDITOR_STEPS.length - 1 ? `<button type="button" class="btn btn-primary" data-report-action="next">Continue: ${escapeHtml(stepTitle(next))}</button>` : ''}
      ${editable && currentIndex === EDITOR_STEPS.length - 1 ? `<button type="button" class="btn btn-primary" data-report-action="save">${current.is_new ? 'Save report' : 'Save changes'}</button>` : ''}
      ${editable ? '<details class="portal-report-more-menu"><summary aria-label="More report actions" title="More report actions">⋯</summary><div><button type="button" data-report-action="discard">Discard local draft</button></div></details>' : ''}
    </div>`;
  }
  function editorMarkup() {
    if (!state.current) return '<section class="portal-report-editor portal-report-placeholder"><h2>Report unavailable</h2><p>Return to Reports and choose a saved definition.</p><button type="button" class="btn btn-secondary" data-report-action="catalogue">Back to reports</button></section>';
    const current = state.current;
    const editable = state.canManage;
    const step = editorStep();
    const content = step === 'filters' ? editorFiltersMarkup(current, editable) : step === 'review' ? editorReviewMarkup(current, editable) : editorFieldsMarkup(current, editable);
    return `<section class="portal-report-editor">
      <div class="portal-report-editor-heading"><div><span class="settings-eyebrow">${current.is_new ? 'NEW DEFINITION' : `VERSION ${escapeHtml(current.version)}`}</span><h2>${escapeHtml(current.title)}</h2><p>Live data, results, and XLSX exports always respect the viewer’s current Portal scope.</p></div></div>
      ${relationshipMarkup()}${stepperMarkup()}${content}${editable ? draftNoticeMarkup() : ''}${editorActionsMarkup(current, editable)}
    </section>`;
  }

  function catalogueMarkup() {
    const reports = state.definitions;
    return `<section class="portal-report-catalogue"><div class="portal-report-catalogue-heading"><div><span class="settings-eyebrow">SAVED REPORTS</span><h2>Find and run</h2><p>Open a definition to review its fields, rules, and charts. Run uses current approved Portal data.</p></div>${state.canManage ? '<button type="button" class="btn btn-primary" data-report-action="new">New report</button>' : ''}</div>
      <label class="portal-report-search">Find a report<input type="search" data-report-catalogue-search value="${escapeHtml(state.catalogueSearch)}" placeholder="Search report title"></label>
      <div class="portal-report-catalogue-list">${reports.length ? reports.map((report) => `<article class="portal-report-card" data-report-card data-search="${escapeHtml(report.title.toLowerCase())}"><div><span class="settings-eyebrow">VERSION ${escapeHtml(report.version)}</span><h3>${escapeHtml(report.title)}</h3><p>Updated ${escapeHtml(formatDateTime(report.updated_at || report.created_at))}</p></div><div class="portal-report-card-stats"><span>${escapeHtml(report.configuration?.fields?.length || 0)} fields</span><span>${escapeHtml(report.configuration?.filters?.length || 0)} filters</span><span>${escapeHtml(report.charts?.length || 0)} charts</span></div><div class="portal-report-actions"><button type="button" class="btn btn-secondary" data-report-action="open" data-id="${escapeHtml(report.id)}">Open</button><button type="button" class="btn btn-primary" data-report-action="run-card" data-id="${escapeHtml(report.id)}">Run</button>${state.canManage ? `<button type="button" class="btn btn-secondary" data-report-action="archive-card" data-id="${escapeHtml(report.id)}">Archive</button>` : ''}</div></article>`).join('') : '<div class="portal-report-empty-state"><strong>No reports saved yet.</strong><span>Create a controlled report only when it answers a recurring operational question.</span></div>'}</div>
      <div class="portal-report-empty-state" data-report-search-empty hidden><strong>No report matches that title.</strong><span>Clear the search or create a new controlled report.</span></div>
    </section>`;
  }

  function detailMarkup() {
    const current = state.current;
    if (!current) return '<section class="portal-report-detail portal-report-placeholder"><h2>Report unavailable</h2><p>This report is no longer available. Return to the catalogue and choose another definition.</p><button type="button" class="btn btn-secondary" data-report-action="catalogue">Back to reports</button></section>';
    const fieldsCount = current.configuration?.fields?.length || 0;
    const filtersCount = current.configuration?.filters?.length || 0;
    const chartCount = current.charts?.length || 0;
    return `<section class="portal-report-detail"><div class="portal-report-detail-heading"><div><span class="settings-eyebrow">VERSION ${escapeHtml(current.version)}</span><h2>${escapeHtml(current.title)}</h2><p>Last updated ${escapeHtml(formatDateTime(current.updated_at || current.created_at))}. The data remains scoped to the current viewer.</p></div><button type="button" class="btn btn-secondary" data-report-action="catalogue">Back to reports</button></div>
      <div class="portal-report-summary-grid"><div class="portal-report-summary-item"><span>Fields</span><strong>${escapeHtml(fieldsCount)}</strong></div><div class="portal-report-summary-item"><span>Filters</span><strong>${escapeHtml(filtersCount)}</strong></div><div class="portal-report-summary-item"><span>Charts</span><strong>${escapeHtml(chartCount)}</strong></div></div>
      <section class="portal-report-detail-section"><h3>Included fields</h3>${fieldChips(selectedFields())}</section>
      <section class="portal-report-detail-section"><h3>Filters</h3>${filterSummary(current.configuration?.filters || [])}</section>
      <section class="portal-report-detail-section"><h3>Ordering</h3><p>${escapeHtml(label(current.configuration?.ordering?.field || ''))} · ${escapeHtml(current.configuration?.ordering?.direction || 'asc')}</p></section>
      <section class="portal-report-detail-section"><h3>Charts</h3>${chartCount ? `<ul class="portal-report-summary-list">${current.charts.map((chart) => `<li><strong>${escapeHtml(chart.title || 'Untitled chart')}</strong><span>${escapeHtml(chart.chart_type)} · ${escapeHtml(label(chart.dimension_field))} · ${escapeHtml(chart.aggregation)}</span></li>`).join('')}</ul>` : '<p>No charts configured.</p>'}</section>
      <div class="portal-report-actions"><button type="button" class="btn btn-primary" data-report-action="run">Run live report</button><button type="button" class="btn btn-secondary" data-report-action="export">Download XLSX</button>${state.canManage ? '<button type="button" class="btn btn-secondary" data-report-action="edit">Edit definition</button><button type="button" class="btn btn-secondary" data-report-action="archive">Archive</button>' : ''}</div>
    </section>`;
  }

  function resultMarkup() {
    const result = state.result;
    if (!result) return retryMarkup(
      'Report could not run',
      state.runError || 'Refresh or return to the definition and try again.',
      'rerun',
    );
    const pageSize = Number(result.pagination?.page_size || result.rows.length || 1);
    const firstPosition = (Number(result.pagination?.page || 1) - 1) * pageSize;
    const table = `<div class="portal-report-table-wrap"><table class="portal-report-table"><thead><tr><th class="table-number">No.</th>${result.columns.map((item) => `<th>${escapeHtml(item.label)}</th>`).join('')}</tr></thead><tbody>${result.rows.length ? result.rows.map((row, index) => `<tr><td class="table-number">${firstPosition + index + 1}</td>${result.columns.map((column) => `<td>${escapeHtml(formatValue(row[column.key], column.type))}</td>`).join('')}</tr>`).join('') : `<tr><td colspan="${result.columns.length + 1}">No cases match this report.</td></tr>`}</tbody></table></div>`;
    const pagination = result.pagination?.pages > 1 ? `<div class="portal-report-pager"><span>Page ${escapeHtml(result.pagination.page)} of ${escapeHtml(result.pagination.pages)} · ${escapeHtml(result.total_rows)} rows</span><div><button type="button" class="btn btn-secondary" data-report-action="page" data-page="${Math.max(1, result.pagination.page - 1)}" ${result.pagination.page <= 1 ? 'disabled' : ''}>Previous</button><button type="button" class="btn btn-secondary" data-report-action="page" data-page="${Math.min(result.pagination.pages, result.pagination.page + 1)}" ${result.pagination.page >= result.pagination.pages ? 'disabled' : ''}>Next</button></div></div>` : `<p class="portal-report-result-copy">${escapeHtml(result.total_rows)} live row${result.total_rows === 1 ? '' : 's'}${result.total_rows > result.shown_rows_limit ? `; table is limited to the first ${escapeHtml(result.shown_rows_limit)}` : ''}.</p>`;
    return `<section class="portal-report-results"><div class="portal-report-results-heading"><div><span class="settings-eyebrow">LIVE RESULT</span><h2>${escapeHtml(result.definition?.title || 'Report')}</h2><p>Generated ${escapeHtml(formatDateTime(result.run_at))}. This preview does not save a data snapshot.</p></div><div class="portal-report-actions"><button type="button" class="btn btn-primary" data-report-action="rerun">Run again</button><button type="button" class="btn btn-secondary" data-report-action="export">Download XLSX</button></div></div><div class="portal-report-summary-grid"><div class="portal-report-summary-item"><span>Rows</span><strong>${escapeHtml(result.total_rows || 0)}</strong></div><div class="portal-report-summary-item"><span>Shown</span><strong>${escapeHtml(result.rows?.length || 0)}</strong></div><div class="portal-report-summary-item"><span>Charts</span><strong>${escapeHtml(result.charts?.length || 0)}</strong></div></div><div id="portal-report-charts" class="portal-report-charts">${(result.charts || []).map((chart, index) => `<article class="portal-report-chart"><h3>${escapeHtml(chart.title)}</h3><p>${escapeHtml(chart.metric_label)} by ${escapeHtml(chart.dimension_label)}${chart.truncated ? ' · first 100 groups' : ''}</p><canvas id="portal-report-chart-${index}" aria-label="${escapeHtml(chart.title)}"></canvas></article>`).join('')}</div>${table}${pagination}</section>`;
  }

  function render() {
    state.root = root();
    if (!state.root) return;
    state.chartObserver?.disconnect?.();
    state.chartObserver = null;
    state.charts.forEach((chart) => chart.destroy?.());
    state.charts = [];
    state.editorPreviewChart?.destroy?.();
    state.editorPreviewChart = null;
    if (state.route.view === 'edit') state.root.innerHTML = editorMarkup();
    else if (state.route.view === 'detail') state.root.innerHTML = detailMarkup();
    else if (state.route.view === 'run') state.root.innerHTML = `${resultMarkup()}<div class="portal-report-actions"><button type="button" class="btn btn-secondary" data-report-action="detail">Back to definition</button></div>`;
    else state.root.innerHTML = catalogueMarkup();
    syncEditorShell();
    if (state.route.view === 'edit' && editorStep() === 'fields') applyFieldSearch(state.fieldSearch);
    window.lucide?.createIcons?.();
    renderMobileResultCards();
    renderCharts();
    if (state.route.view === 'edit' && editorStep() === 'review') {
      renderEditorChartPreview();
      scheduleEditorChartPreview();
    }
    scheduleChartResize();
    requestShellNavigationSync();
  }

  function renderMobileResultCards() {
    const result = state.result;
    const target = root();
    const table = target?.querySelector('.portal-report-table-wrap');
    if (!result || !table) return;
    const pageSize = Number(result.pagination?.page_size || result.rows.length || 1);
    const firstPosition = (Number(result.pagination?.page || 1) - 1) * pageSize;
    const primary = (result.columns || []).slice(0, 4);
    const remaining = (result.columns || []).slice(4);
    const cards = result.rows?.length ? result.rows.map((row, index) => {
      const values = (columns) => columns.map((column) => `<div class="portal-report-row-field"><span>${escapeHtml(column.label)}</span><strong>${escapeHtml(formatValue(row[column.key], column.type))}</strong></div>`).join('');
      const details = remaining.length ? `<details class="portal-report-row-more"><summary>More fields (${remaining.length})</summary><div class="portal-report-row-fields">${values(remaining)}</div></details>` : '';
      return `<article class="portal-report-row-card"><header><span>Case row</span><strong>No. ${firstPosition + index + 1}</strong></header><div class="portal-report-row-fields">${values(primary)}</div>${details}</article>`;
    }).join('') : '<div class="portal-report-empty-state"><strong>No cases match this report.</strong><span>Change a filter or run the report again when new work arrives.</span></div>';
    table.insertAdjacentHTML('beforebegin', `<div class="portal-report-mobile-results" aria-label="Report results">${cards}</div>`);
  }

  function renderCharts() {
    const result = state.result;
    if (!result) return;
    const cards = [...(root()?.querySelectorAll('.portal-report-chart') || [])];
    const mount = (container, index) => {
      const chart = result.charts?.[index];
      if (!chart || container.dataset.chartMounted === 'true') return;
      container.dataset.chartMounted = 'true';
      mountChart(container, chart, index);
    };
    if (!cards.length) return;
    if (!window.IntersectionObserver) {
      cards.forEach(mount);
      return;
    }
    state.chartObserver = new window.IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        state.chartObserver?.unobserve(entry.target);
        mount(entry.target, cards.indexOf(entry.target));
      });
    }, { rootMargin: '160px 0px' });
    cards.forEach((card) => state.chartObserver.observe(card));
  }

  function mountChart(container, chart, index) {
    if (chart.error) {
      container.innerHTML = `<h3>${escapeHtml(chart.title)}</h3><p>${escapeHtml(chart.error)}</p>`;
      return;
    }
    const canvas = document.getElementById(`portal-report-chart-${index}`);
    if (!canvas) return;
    canvas.style.height = `${chartHeight()}px`;
    if (!window.Chart) {
      container.innerHTML = chartFallbackMarkup(chart, 'Chart display is unavailable in this Mini App session.');
      return;
    }
    try {
      state.charts.push(createChartInstance(canvas, chart));
    } catch (error) {
      console.warn('Portal report chart could not render.', error);
      container.innerHTML = chartFallbackMarkup(chart, 'This chart could not be drawn. The live report rows remain available below.');
    }
  }

  function createChartInstance(canvas, chart) {
    const colors = chartColors();
    const horizontal = chart.type === 'bar' && (chart.labels || []).length > 4;
    return new window.Chart(canvas, {
      type: chart.type,
      data: {
        labels: chart.labels,
        datasets: [{
          label: chart.metric_label,
          data: chart.values,
          borderColor: colors.primary,
          backgroundColor: chart.type === 'doughnut' ? colors.palette : colors.primary,
          borderWidth: 2,
          fill: chart.type === 'line' ? false : undefined,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        indexAxis: horizontal ? 'y' : 'x',
        interaction: { mode: 'nearest', intersect: false },
        plugins: {
          legend: { display: chart.type === 'doughnut', labels: { color: colors.text } },
          tooltip: { enabled: true },
        },
        scales: chart.type === 'doughnut' ? {} : {
          x: { ticks: { color: colors.hint, autoSkip: true, maxRotation: 0 }, grid: { color: colors.grid } },
          y: { beginAtZero: true, ticks: { color: colors.hint, precision: 0 }, grid: { color: colors.grid } },
        },
      },
    });
  }

  function chartColors() {
    const params = state.tg?.themeParams || window.Telegram?.WebApp?.themeParams || {};
    const style = window.getComputedStyle?.(document.documentElement);
    const primary = params.button_color || params.link_color || style?.getPropertyValue('--color-primary').trim() || '#078b86';
    const text = params.text_color || style?.getPropertyValue('--text-primary').trim() || '#17212b';
    const hint = params.hint_color || style?.getPropertyValue('--text-muted').trim() || '#708499';
    const grid = params.section_separator_color || params.secondary_bg_color || style?.getPropertyValue('--border-color').trim() || 'rgba(112,132,153,.25)';
    return { primary, text, hint, grid, palette: themePalette(primary) };
  }

  function themePalette(color) {
    const match = String(color || '').trim().match(/^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i);
    if (!match) return [color, color, color, color, color, color];
    const [red, green, blue] = match.slice(1).map((value) => Number.parseInt(value, 16));
    const max = Math.max(red, green, blue) / 255;
    const min = Math.min(red, green, blue) / 255;
    const delta = max - min;
    const hue = !delta ? 180 : 60 * (((max === red / 255 ? (green - blue) / 255 / delta : max === green / 255 ? 2 + ((blue - red) / 255 / delta) : 4 + ((red - green) / 255 / delta))) % 6);
    const lightness = (max + min) / 2;
    const saturation = !delta ? 0 : delta / (1 - Math.abs(2 * lightness - 1));
    return [-34, 0, 32, 64, 142, 205].map((offset) => hslColor(hue + offset, saturation, lightness));
  }

  function hslColor(hue, saturation, lightness) {
    const normalizedHue = ((hue % 360) + 360) % 360;
    const chroma = (1 - Math.abs(2 * lightness - 1)) * saturation;
    const segment = normalizedHue / 60;
    const secondary = chroma * (1 - Math.abs((segment % 2) - 1));
    const [red, green, blue] = segment < 1 ? [chroma, secondary, 0] : segment < 2 ? [secondary, chroma, 0] : segment < 3 ? [0, chroma, secondary] : segment < 4 ? [0, secondary, chroma] : segment < 5 ? [secondary, 0, chroma] : [chroma, 0, secondary];
    const adjustment = lightness - chroma / 2;
    return `rgb(${Math.round((red + adjustment) * 255)} ${Math.round((green + adjustment) * 255)} ${Math.round((blue + adjustment) * 255)})`;
  }

  function resizeChartsForViewport() {
    const target = root();
    if (target) {
      const height = `${chartHeight()}px`;
      target.style.setProperty('--portal-report-chart-height', height);
      target.querySelectorAll('.portal-report-chart canvas').forEach((canvas) => { canvas.style.height = height; });
      target.querySelectorAll('.portal-report-chart-preview canvas').forEach((canvas) => { canvas.style.height = height; });
    }
    state.charts.forEach((chart) => {
      try { chart.resize?.(); } catch (_) { /* Charts are optional visual enhancements. */ }
    });
    try { state.editorPreviewChart?.resize?.(); } catch (_) { /* Preview charts are optional. */ }
  }

  function scheduleChartResize() {
    window.clearTimeout(state.chartResizeTimer);
    state.chartResizeTimer = window.setTimeout(resizeChartsForViewport, 80);
  }

  function refreshChartsForTheme() {
    state.chartObserver?.disconnect?.();
    state.chartObserver = null;
    state.charts.forEach((chart) => chart.destroy?.());
    state.charts = [];
    state.editorPreviewChart?.destroy?.();
    state.editorPreviewChart = null;
    root()?.querySelectorAll('.portal-report-chart').forEach((card) => { delete card.dataset.chartMounted; });
    renderCharts();
    renderEditorChartPreview();
    scheduleChartResize();
  }

  function bindViewportEvents() {
    if (state.viewportEventsBound) return;
    state.viewportEventsBound = true;
    state.viewportHandler = scheduleChartResize;
    state.themeHandler = refreshChartsForTheme;
    window.addEventListener('resize', state.viewportHandler);
    window.visualViewport?.addEventListener('resize', state.viewportHandler);
    state.tg?.onEvent?.('viewportChanged', state.viewportHandler);
    state.tg?.onEvent?.('themeChanged', state.themeHandler);
  }

  function unbindViewportEvents() {
    if (!state.viewportEventsBound) return;
    window.removeEventListener('resize', state.viewportHandler);
    window.visualViewport?.removeEventListener('resize', state.viewportHandler);
    state.tg?.offEvent?.('viewportChanged', state.viewportHandler);
    state.tg?.offEvent?.('themeChanged', state.themeHandler);
    window.clearTimeout(state.chartResizeTimer);
    state.chartResizeTimer = null;
    state.viewportHandler = null;
    state.themeHandler = null;
    state.viewportEventsBound = false;
  }

  function chartFallbackMarkup(chart, message) {
    const points = (chart.labels || []).slice(0, 8).map((labelValue, index) => (
      `<li><span>${escapeHtml(labelValue)}</span><strong>${escapeHtml(chart.values?.[index] ?? 0)}</strong></li>`
    )).join('');
    return `<h3>${escapeHtml(chart.title)}</h3><p>${escapeHtml(message)}</p>${points ? `<ul class="portal-report-chart-fallback">${points}</ul>` : '<p>No chart values were returned.</p>'}`;
  }

  function activeEditorChart() {
    const chart = state.current?.charts?.[state.activeChartIndex];
    return chart ? { chart: normalizeChart(chart), index: state.activeChartIndex } : null;
  }

  function renderEditorChartPreview() {
    const target = root()?.querySelector('[data-report-editor-preview]');
    state.editorPreviewChart?.destroy?.();
    state.editorPreviewChart = null;
    if (!target || state.editorPreview.status !== 'ready' || !state.editorPreview.data) return;
    const canvas = target.querySelector('#portal-report-editor-chart-preview');
    if (!canvas) return;
    canvas.style.height = `${chartHeight()}px`;
    if (!window.Chart) {
      target.innerHTML = chartFallbackMarkup(state.editorPreview.data, 'Chart display is unavailable in this Mini App session.');
      return;
    }
    try {
      state.editorPreviewChart = createChartInstance(canvas, state.editorPreview.data);
    } catch (error) {
      console.warn('Portal report editor preview could not render.', error);
      target.innerHTML = chartFallbackMarkup(state.editorPreview.data, 'This preview could not be drawn. Check the live report after saving.');
    }
  }

  function refreshEditorPreviewMarkup() {
    const active = activeEditorChart();
    const target = root()?.querySelector('[data-report-chart-row][open] .portal-report-chart-preview, [data-report-chart-row][open] [data-report-editor-preview]');
    if (!active || !target) return;
    target.outerHTML = editorPreviewMarkup(active.chart, active.index);
    renderEditorChartPreview();
  }

  function scheduleEditorChartPreview({ force = false } = {}) {
    if (state.route.view !== 'edit' || editorStep() !== 'review' || !state.canManage) return;
    const active = activeEditorChart();
    if (!active) return;
    const readiness = chartPreviewReadiness(active.chart);
    const key = chartPreviewKey(active.chart);
    if (readiness) {
      if (state.editorPreview.key !== key || state.editorPreview.status !== 'idle') {
        resetEditorPreview();
        state.editorPreview = { index: active.index, key, status: 'idle', data: null, error: '' };
        refreshEditorPreviewMarkup();
      }
      return;
    }
    if (!force && state.editorPreview.index === active.index && state.editorPreview.key === key && ['loading', 'ready', 'error'].includes(state.editorPreview.status)) return;
    resetEditorPreview();
    const sequence = ++state.editorPreviewSequence;
    state.editorPreview = { index: active.index, key, status: 'loading', data: null, error: '' };
    refreshEditorPreviewMarkup();
    state.editorPreviewTimer = window.setTimeout(async () => {
      const controller = window.AbortController ? new AbortController() : null;
      state.editorPreviewController = controller;
      try {
        const result = await api().postJson('/reports/preview/', {
          configuration: state.current.configuration,
          chart: active.chart,
        }, state.tg, {}, controller ? { signal: controller.signal } : {});
        if (sequence !== state.editorPreviewSequence || controller?.signal.aborted) return;
        if (!result.ok || !result.data?.ok) throw new Error(result.data?.error || 'Could not prepare this chart preview.');
        state.editorPreview = { index: active.index, key, status: 'ready', data: result.data.preview, error: '' };
      } catch (error) {
        if (sequence !== state.editorPreviewSequence || controller?.signal.aborted) return;
        state.editorPreview = { index: active.index, key, status: 'error', data: null, error: error.message || 'Could not prepare this chart preview.' };
      } finally {
        if (sequence === state.editorPreviewSequence) {
          state.editorPreviewController = null;
          state.editorPreviewTimer = null;
          refreshEditorPreviewMarkup();
        }
      }
    }, 450);
  }

  function readDraft() {
    const current = state.current;
    if (!current) return null;
    const reportRoot = root();
    const config = { ...(current.configuration || {}) };
    const activeStep = reportRoot?.querySelector('[data-report-editor-step]')?.dataset.reportEditorStep;
    const title = reportRoot?.querySelector('#portal-report-title');
    if (title) current.title = title.value.trim();
    if (activeStep === 'fields') config.fields = [...reportRoot.querySelectorAll('[data-report-field]:checked')].map((node) => node.value);
    if (activeStep === 'filters') {
      config.filters = [...reportRoot.querySelectorAll('[data-report-filter-row]')].map((row) => {
        const reportField = row.querySelector('[data-report-filter-field]')?.value || '';
        const operator = row.querySelector('[data-report-filter-operator]')?.value || '';
        const raw = row.querySelector('[data-report-filter-value]')?.value || '';
        const value = ['between', 'in'].includes(operator) ? raw.split('|').map((item) => item.trim()).filter(Boolean) : raw.trim();
        return { field: reportField, operator, value };
      });
      config.ordering = {
        field: reportRoot.querySelector('#portal-report-order-field')?.value || '',
        direction: reportRoot.querySelector('#portal-report-order-direction')?.value || 'asc',
      };
    }
    const charts = activeStep === 'review' ? [...reportRoot.querySelectorAll('[data-report-chart-row]')].map((row) => ({
      title: row.querySelector('[data-report-chart-title]')?.value || '',
      chart_type: row.querySelector('[data-report-chart-type]')?.value || '',
      dimension_field: row.querySelector('[data-report-chart-dimension]')?.value || '',
      aggregation: row.querySelector('[data-report-chart-aggregation]')?.value || '',
      metric_field: row.querySelector('[data-report-chart-metric]')?.value || '',
      date_bucket: row.querySelector('[data-report-chart-bucket]')?.value || '',
    })) : current.charts;
    return { title: current.title, configuration: config, charts, version: current.version };
  }

  function snapshotDraft() {
    const draft = readDraft();
    if (!draft || !state.current) return;
    state.current = { ...state.current, ...draft };
    persistDraft();
  }

  function validateStep(step) {
    snapshotDraft();
    if (step === 'fields') {
      if (!state.current?.title?.trim()) throw new Error('Give this report a title before continuing.');
      if (!selectedFields().length) throw new Error('Choose at least one approved report field before continuing.');
    }
    if (step === 'filters') {
      const incomplete = (state.current?.configuration?.filters || []).some((item) => !item.field || !item.operator || !valueToInput(item.value).trim());
      if (incomplete) throw new Error('Complete or remove every filter before continuing.');
      if (!state.current?.configuration?.ordering?.field) throw new Error('Choose how report rows should be ordered.');
    }
  }

  function filterCatalogue(query) {
    state.catalogueSearch = query;
    const normalized = query.trim().toLowerCase();
    let visible = 0;
    root()?.querySelectorAll('[data-report-card]').forEach((card) => {
      const match = !normalized || card.dataset.search.includes(normalized);
      card.hidden = !match;
      if (match) visible += 1;
    });
    const empty = root()?.querySelector('[data-report-search-empty]');
    if (empty) empty.hidden = visible !== 0;
  }

  function applyFieldSearch(query) {
    const normalized = String(query || '').trim().toLowerCase();
    state.fieldSearch = normalized;
    let visibleCategories = 0;
    root()?.querySelectorAll('[data-report-field-category]').forEach((category) => {
      const labels = [...category.querySelectorAll('[data-report-field-label]')];
      const matching = labels.filter((item) => {
        const match = !normalized || item.dataset.search.includes(normalized);
        item.hidden = !match;
        return match;
      });
      const visible = matching.length > 0;
      category.hidden = !visible;
      if (visible) visibleCategories += 1;
      category.open = normalized ? visible : Number(category.dataset.selectedCount || 0) > 0;
    });
    const empty = root()?.querySelector('[data-report-field-search-empty]');
    if (empty) empty.hidden = visibleCategories !== 0;
  }

  async function load() {
    const target = root();
    if (!target) return;
    const nextRoute = readRoute();
    if (canReuseEditorDraft(nextRoute)) {
      // Invalidate an older async operation, then immediately render the
      // already validated local draft into the fresh htmx screen root. This
      // prevents a route-backed wizard step from waiting on three read APIs.
      state.loadVersion += 1;
      state.root = target;
      state.route = nextRoute;
      state.result = null;
      state.runError = '';
      render();
      return;
    }
    const loadVersion = ++state.loadVersion;
    state.root = target;
    state.route = nextRoute;
    // Search is a short-lived field-picker aid. Preserve it while moving
    // between this report's route-backed wizard steps, but never carry it
    // into a separately opened report or a fresh report definition.
    state.fieldSearch = '';
    syncEditorShell();
    state.result = null;
    state.runError = '';
    target.innerHTML = loadingMarkup();
    try {
      const client = api();
      if (typeof client.apiFetch !== 'function') throw new Error('The Portal reporting client did not initialise. Refresh and try again.');
      const [catalogueResult, reportsResult, relationshipResult] = await Promise.all([
        client.apiFetch('/reports/catalogue/', {}, state.tg),
        client.apiFetch('/reports/', {}, state.tg),
        state.canManage ? client.apiFetch('/reports/relationships/', {}, state.tg) : Promise.resolve({ ok: true, data: { ok: true, relationship_summary: null } }),
      ]);
      if (!isCurrentLoad(loadVersion, target)) return;
      if (!catalogueResult.ok || !catalogueResult.data?.ok || !reportsResult.ok || !reportsResult.data?.ok) {
        showLoadFailure(catalogueResult.data?.error || reportsResult.data?.error || 'Check IT reporting access and try again.');
        return;
      }
      state.catalogue = catalogueResult.data.catalogue;
      state.definitions = reportsResult.data.reports || [];
      state.relationships = relationshipResult.data?.relationship_summary || null;
      if (state.route.view === 'edit' && !state.route.reportId) {
        state.current = restoreLocalDraft(emptyDraft(), { isNew: true });
      } else if (state.route.reportId) {
        try {
          await select(state.route.reportId, { shouldRender: false, restoreDraft: state.route.view === 'edit' });
        } catch (error) {
          state.current = null;
          state.route = { view: 'catalogue', reportId: '', step: '' };
          toast(error.message || 'This report is unavailable.', 'error');
        }
      } else {
        state.current = null;
      }
      if (!isCurrentLoad(loadVersion, target)) return;
      if (state.route.view === 'run' && state.current?.id) {
        try { await run(1, { shouldRender: false }); } catch (error) { state.result = null; state.runError = error.message || 'Could not run this report.'; }
      }
      if (!isCurrentLoad(loadVersion, target)) return;
      render();
    } catch (error) {
      if (!isCurrentLoad(loadVersion, target)) return;
      showLoadFailure(error.message || 'The reports screen could not be loaded.');
    }
  }

  async function select(id, { shouldRender = true, restoreDraft = false } = {}) {
    const result = await api().apiFetch(`/reports/${encodeURIComponent(id)}/`, {}, state.tg);
    if (!result.ok || !result.data?.ok) throw new Error(result.data?.error || 'Could not load this report.');
    state.current = restoreDraft ? restoreLocalDraft(result.data.report) : result.data.report;
    state.result = null;
    if (shouldRender) render();
  }

  async function save() {
    validateStep('review');
    const draft = readDraft();
    if (!draft) return;
    const oldDraftKey = draftKey(state.current);
    const isNew = Boolean(state.current?.is_new);
    const path = isNew ? '/reports/' : `/reports/${encodeURIComponent(state.current.id)}/`;
    const result = await api().postJson(path, draft, state.tg);
    if (!result.ok || !result.data?.ok) throw new Error(result.data?.error || 'Could not save the report.');
    try { window.sessionStorage?.removeItem(oldDraftKey); } catch (_) { /* Storage is optional. */ }
    state.current = { ...result.data.report, is_new: false };
    clearLocalDraft(state.current);
    const existing = state.definitions.findIndex((item) => item.id === state.current.id);
    if (existing >= 0) state.definitions.splice(existing, 1, state.current); else state.definitions.push(state.current);
    state.definitions.sort((a, b) => a.title.localeCompare(b.title));
    state.result = null;
    toast(result.data.message || 'Report saved.', 'success');
    navigate('detail', state.current.id);
  }

  async function run(page = 1, { shouldRender = true } = {}) {
    if (!state.current?.id) return;
    const target = root();
    state.runError = '';
    if (shouldRender && target) target.innerHTML = loadingMarkup('Preparing the live report...');
    try {
      const result = await api().postJson(`/reports/${encodeURIComponent(state.current.id)}/run/`, { page }, state.tg);
      if (!result.ok || !result.data?.ok) throw new Error(result.data?.error || 'Could not run the report.');
      state.result = result.data.result;
      state.current = result.data.result.definition;
      if (shouldRender && root() === target) render();
    } catch (error) {
      state.result = null;
      state.runError = error.message || 'Could not run the report.';
      if (shouldRender && root() === target) target.innerHTML = `${resultMarkup()}<div class="portal-report-actions"><button type="button" class="btn btn-secondary" data-report-action="detail">Back to definition</button></div>`;
      throw error;
    }
  }
  async function archiveDefinition(definition, { returnToCatalogue = false } = {}) {
    if (!definition?.id || !window.confirm('Archive this saved report? Its definition and audit history remain retained, but it will leave the active Reports list.')) return;
    const result = await api().postJson(`/reports/${encodeURIComponent(definition.id)}/archive/`, { version: definition.version }, state.tg);
    if (!result.ok || !result.data?.ok) throw new Error(result.data?.error || 'Could not archive the report.');
    clearLocalDraft(definition);
    state.definitions = state.definitions.filter((item) => item.id !== definition.id);
    if (state.current?.id === definition.id) {
      state.current = null;
      state.result = null;
    }
    toast('Report archived from the active list.', 'success');
    if (returnToCatalogue) navigate('catalogue');
    else render();
  }
  async function archive() {
    return archiveDefinition(state.current, { returnToCatalogue: true });
  }
  async function exportXlsx() {
    if (!state.current?.id) return;
    const key = requestId();
    const response = await fetch(`${api().apiBase()}/reports/${encodeURIComponent(state.current.id)}/export/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...api().initDataHeader(state.tg), 'X-Request-ID': key, 'Idempotency-Key': key },
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
    state.current.configuration = {
      ...(state.current.configuration || {}),
      filters: [...(state.current.configuration?.filters || []), { field: candidate.key, operator: candidate.operators[0], value: '' }],
    };
    persistDraft();
    render();
  }
  function addChart() {
    snapshotDraft();
    const dimension = chartDimensions()[0];
    if (!dimension) throw new Error('Select an approved operational category or date field first.');
    const chart = { title: '', chart_type: chartTypesForDimension(dimension)[0]?.key || '', dimension_field: dimension.key, aggregation: 'count', metric_field: '', date_bucket: '' };
    normalizeChart(chart);
    state.current.charts.push(chart);
    state.activeChartIndex = state.current.charts.length - 1;
    resetEditorPreview();
    persistDraft();
    render();
  }
  function updateChart(index, update) {
    snapshotDraft();
    const chart = state.current?.charts?.[index];
    if (!chart) return;
    update(chart);
    normalizeChart(chart);
    state.activeChartIndex = index;
    resetEditorPreview();
    persistDraft();
    render();
  }
  function discardDraft() {
    if (!state.current || !window.confirm('Discard this browser-only draft? Saved report definitions will not be changed.')) return;
    const wasNew = Boolean(state.current.is_new);
    const reportId = state.current.id;
    clearLocalDraft(state.current);
    navigate(wasNew ? 'catalogue' : 'detail', wasNew ? '' : reportId);
  }

  function bindEvents() {
    if (document.documentElement.dataset.portalReportsBound) return;
    document.documentElement.dataset.portalReportsBound = 'true';
    document.addEventListener('click', async (event) => {
      const chartType = event.target.closest('[data-report-chart-type-choice]');
      if (chartType && root()?.contains(chartType)) {
        event.preventDefault();
        updateChart(Number(chartType.dataset.index), (chart) => { chart.chart_type = chartType.dataset.reportChartTypeChoice || ''; });
        return;
      }
      const button = event.target.closest('[data-report-action]');
      if (!button || !root()?.contains(button)) return;
      event.preventDefault();
      try {
        const action = button.dataset.reportAction;
        if (action === 'new') navigate('edit', '', 'fields');
        else if (action === 'open') navigate('detail', button.dataset.id);
        else if (action === 'run-card') navigate('run', button.dataset.id);
        else if (action === 'catalogue') navigate('catalogue');
        else if (action === 'retry-load') await load();
        else if (action === 'detail') navigate('detail', state.current?.id || state.route.reportId);
        else if (action === 'back') {
          const previous = EDITOR_STEPS[editorStepIndex() - 1];
          navigate(previous ? 'edit' : (state.current?.is_new ? 'catalogue' : 'detail'), previous ? (state.current?.id || '') : (state.current?.id || ''), previous || 'fields');
        } else if (action === 'next') {
          validateStep(editorStep());
          navigate('edit', state.current?.id || '', EDITOR_STEPS[editorStepIndex() + 1]);
        } else if (action === 'step') {
          const targetStep = button.dataset.reportStep;
          if (editorStepIndex(targetStep) > editorStepIndex()) validateStep(editorStep());
          navigate('edit', state.current?.id || '', targetStep);
        } else if (action === 'edit') navigate('edit', state.current?.id || state.route.reportId, 'fields');
        else if (action === 'discard') discardDraft();
        else if (action === 'remove-field') {
          snapshotDraft();
          state.current.configuration.fields = state.current.configuration.fields.filter((fieldKey) => fieldKey !== button.dataset.field);
          persistDraft();
          render();
        }
        else if (action === 'add-filter') addFilter();
        else if (action === 'remove-filter') { snapshotDraft(); state.current.configuration.filters.splice(Number(button.dataset.index), 1); persistDraft(); render(); }
        else if (action === 'add-chart') addChart();
        else if (action === 'remove-chart') {
          snapshotDraft();
          state.current.charts.splice(Number(button.dataset.index), 1);
          state.activeChartIndex = Math.max(0, Math.min(state.activeChartIndex, state.current.charts.length - 1));
          resetEditorPreview();
          persistDraft();
          render();
        }
        else if (action === 'retry-chart-preview') { resetEditorPreview(); scheduleEditorChartPreview({ force: true }); }
        else if (action === 'save') await save();
        else if (action === 'run') navigate('run', state.current?.id || state.route.reportId);
        else if (action === 'rerun') await run(1);
        else if (action === 'page') await run(Number(button.dataset.page || 1));
        else if (action === 'archive') await archive();
        else if (action === 'archive-card') {
          const definition = state.definitions.find((item) => item.id === button.dataset.id);
          await archiveDefinition(definition);
        }
        else if (action === 'export') await exportXlsx();
      } catch (error) { toast(error.message || 'That report action could not be completed.', 'error'); }
    });
    document.addEventListener('input', (event) => {
      if (!root()?.contains(event.target)) return;
      if (event.target.matches('[data-report-catalogue-search]')) { filterCatalogue(event.target.value); return; }
      if (event.target.matches('[data-report-field-search]')) {
        applyFieldSearch(event.target.value);
        return;
      }
      if (state.route.view === 'edit') snapshotDraft();
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
        persistDraft();
        resetEditorPreview();
        render();
        return;
      }
      if (event.target.matches('[data-report-filter-field], [data-report-filter-operator]')) {
        const fieldChanged = event.target.matches('[data-report-filter-field]');
        snapshotDraft();
        const row = event.target.closest('[data-report-filter-row]');
        const filter = state.current?.configuration?.filters?.[Number(row?.dataset.reportFilterRow)];
        const reportField = field(filter?.field);
        if (!filter || !reportField?.filterable) return;
        if (!reportField.operators.includes(filter.operator)) filter.operator = reportField.operators[0] || '';
        if (fieldChanged) filter.value = '';
        persistDraft();
        render();
        return;
      }
      if (event.target.matches('#portal-report-order-field, #portal-report-order-direction')) {
        snapshotDraft();
        persistDraft();
        return;
      }
      if (event.target.matches('[data-report-chart-type], [data-report-chart-aggregation], [data-report-chart-dimension], [data-report-chart-metric], [data-report-chart-bucket]')) {
        snapshotDraft();
        const row = event.target.closest('[data-report-chart-row]');
        const chart = state.current?.charts?.[Number(row?.dataset.reportChartRow)];
        if (!chart) return;
        state.activeChartIndex = Number(row?.dataset.reportChartRow);
        normalizeChart(chart);
        resetEditorPreview();
        persistDraft();
        render();
        return;
      }
      if (state.route.view === 'edit') snapshotDraft();
    });
    document.addEventListener('toggle', (event) => {
      const card = event.target;
      if (!card?.matches?.('[data-report-chart-row]') || !root()?.contains(card) || !card.open) return;
      const index = Number(card.dataset.reportChartRow);
      if (index === state.activeChartIndex) return;
      state.activeChartIndex = index;
      resetEditorPreview();
      render();
    }, true);
  }

  function unmount() {
    state.loadVersion += 1;
    state.chartObserver?.disconnect?.();
    state.chartObserver = null;
    state.charts.forEach((chart) => chart.destroy?.());
    state.charts = [];
    resetEditorPreview();
    unbindViewportEvents();
    document.body.classList.remove('portal-report-editor-active');
    state.root = null;
  }

  function canHandleBack() {
    return Boolean(root() && readRoute().view === 'edit');
  }

  function handleBack() {
    if (!canHandleBack()) return false;
    state.route = readRoute();
    const index = editorStepIndex();
    if (index > 0) {
      navigate('edit', state.current?.id || state.route.reportId, EDITOR_STEPS[index - 1]);
    } else if (state.current?.is_new || !state.route.reportId) {
      navigate('catalogue');
    } else {
      navigate('detail', state.route.reportId);
    }
    return true;
  }

  window.PortalMiniAppReports = {
    async load(options = {}) {
      state.tg = options.tg || state.tg;
      state.canManage = Boolean(options.canManage);
      bindEvents();
      bindViewportEvents();
      return load();
    },
    canHandleBack,
    handleBack,
    unmount,
  };
})();
