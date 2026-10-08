(function () {
  'use strict';

  const utils = window.MiniAppUtils || {};

  function bindSearch(options) {
    const settings = options || {};
    const input = settings.input;
    const clearButton = settings.clearButton;
    const delay = Number.isFinite(Number(settings.delay)) ? Number(settings.delay) : 250;
    let timer = null;
    let sequence = 0;
    if (!input || typeof settings.onSearch !== 'function') return null;

    function emit(immediate) {
      window.clearTimeout(timer);
      const value = String(input.value || '').trim();
      if (clearButton) clearButton.hidden = !value;
      const token = ++sequence;
      timer = window.setTimeout(function () {
        settings.onSearch(value, token);
      }, immediate || !value ? 0 : delay);
    }
    input.addEventListener('input', function () { emit(false); });
    clearButton?.addEventListener('click', function () {
      input.value = '';
      input.focus();
      emit(true);
    });
    if (clearButton) clearButton.hidden = !String(input.value || '').trim();
    return Object.freeze({ refresh: function () { emit(true); }, sequence: function () { return sequence; } });
  }

  function renderFilterChips(container, filters, onRemove) {
    if (!container) return;
    container.replaceChildren();
    Object.entries(filters || {}).forEach(function (entry) {
      const key = entry[0];
      const item = entry[1];
      const value = item && typeof item === 'object' ? item.value : item;
      if (value === '' || value == null) return;
      const label = item && typeof item === 'object' ? item.label : key;
      const text = item && typeof item === 'object' ? item.text || value : value;
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'miniapp-filter-chip';
      button.dataset.filterKey = key;
      button.setAttribute('aria-label', `Remove ${label} filter`);
      button.textContent = `${label}: ${text} ×`;
      button.addEventListener('click', function () { onRemove?.(key); });
      container.appendChild(button);
    });
  }

  function bindFilterSheet(options) {
    const settings = options || {};
    const trigger = settings.trigger;
    const overlay = settings.overlay;
    const sheet = settings.sheet;
    const form = settings.form;
    const closeButtons = overlay ? overlay.querySelectorAll('[data-miniapp-sheet-close]') : [];
    if (!trigger || !overlay || !sheet) return null;
    let opener = null;
    const focusable = 'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

    function open() {
      opener = document.activeElement;
      overlay.hidden = false;
      overlay.classList.add('open');
      overlay.setAttribute('aria-hidden', 'false');
      window.requestAnimationFrame(function () { sheet.querySelector(focusable)?.focus(); });
      window.dispatchEvent(new CustomEvent('miniapp:overlay-change'));
    }
    function close() {
      overlay.classList.remove('open');
      overlay.hidden = true;
      overlay.setAttribute('aria-hidden', 'true');
      opener?.focus?.();
      window.dispatchEvent(new CustomEvent('miniapp:overlay-change'));
    }
    trigger.addEventListener('click', open);
    closeButtons.forEach(function (button) { button.addEventListener('click', close); });
    overlay.addEventListener('click', function (event) { if (event.target === overlay) close(); });
    sheet.addEventListener('keydown', function (event) {
      if (event.key === 'Escape') { event.preventDefault(); close(); return; }
      if (event.key !== 'Tab') return;
      const nodes = Array.from(sheet.querySelectorAll(focusable));
      if (!nodes.length) return;
      const first = nodes[0];
      const last = nodes[nodes.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    });
    form?.addEventListener('submit', function (event) {
      event.preventDefault();
      settings.onApply?.(new FormData(form));
      close();
    });
    return Object.freeze({ open: open, close: close, isOpen: function () { return overlay.classList.contains('open'); } });
  }

  function bindPagination(options) {
    const settings = options || {};
    const container = settings.container;
    const pagination = settings.pagination || {};
    if (!container) return;
    container.replaceChildren();
    const page = Math.max(1, Number(pagination.page || 1));
    const pages = Math.max(1, Number(pagination.pages || 1));
    if (pages <= 1 && !settings.alwaysVisible) return;
    container.classList.add('miniapp-pagination');
    const previous = document.createElement('button');
    previous.type = 'button'; previous.textContent = 'Previous'; previous.disabled = page <= 1;
    const status = document.createElement('span');
    status.className = 'miniapp-pagination-status'; status.textContent = `Page ${page} of ${pages}`; status.setAttribute('aria-live', 'polite');
    const next = document.createElement('button');
    next.type = 'button'; next.textContent = 'Next'; next.disabled = page >= pages;
    previous.addEventListener('click', function () { settings.onPage?.(page - 1); });
    next.addEventListener('click', function () { settings.onPage?.(page + 1); });
    container.append(previous, status, next);
  }

  function showFeedback(options) {
    const settings = options || {};
    const target = settings.target;
    if (!target) return;
    target.replaceChildren();
    target.classList.add('miniapp-feedback');
    target.dataset.tone = settings.tone || 'info';
    const copy = document.createElement('div');
    const title = document.createElement('strong'); title.textContent = settings.title || 'Action needed';
    const message = document.createElement('p'); message.textContent = settings.message || '';
    copy.append(title, message);
    if (settings.reference) {
      const reference = document.createElement('small'); reference.textContent = `Reference: ${settings.reference}`; copy.appendChild(reference);
    }
    const actions = document.createElement('div'); actions.className = 'miniapp-feedback-actions';
    if (typeof settings.retry === 'function') {
      const retry = document.createElement('button'); retry.type = 'button'; retry.textContent = 'Try Again'; retry.addEventListener('click', settings.retry); actions.appendChild(retry);
    }
    if (settings.dismissible !== false) {
      const dismiss = document.createElement('button'); dismiss.type = 'button'; dismiss.textContent = 'Dismiss'; dismiss.addEventListener('click', function () { target.hidden = true; }); actions.appendChild(dismiss);
    }
    target.append(copy, actions);
    target.hidden = false;
  }

  function createListContext(key) {
    const context = utils.createUiContext?.(`list:${key}`);
    let ephemeralSearch = '';
    let ephemeralFocusId = '';
    function read() {
      const stored = context?.read?.() || {};
      return {
        page: Math.max(1, Number(stored.page || 1)),
        filters: stored.filters && typeof stored.filters === 'object' ? stored.filters : {},
        scrollY: Math.max(0, Number(stored.scrollY || 0)),
        focusId: ephemeralFocusId,
        search: ephemeralSearch,
      };
    }
    function write(value) {
      const source = value || {};
      if (Object.prototype.hasOwnProperty.call(source, 'search')) ephemeralSearch = String(source.search || '');
      ephemeralFocusId = String(source.focusId || ephemeralFocusId || '');
      context?.write?.({
        page: Math.max(1, Number(source.page || 1)),
        filters: source.filters && typeof source.filters === 'object' ? source.filters : {},
        scrollY: Math.max(0, Number(source.scrollY || 0)),
      });
    }
    function clearSearch() { ephemeralSearch = ''; }
    return Object.freeze({ read: read, write: write, clearSearch: clearSearch });
  }

  function bindSingleFlightAction(options) {
    const settings = options || {};
    if (!settings.button || typeof settings.operation !== 'function') return null;
    let requestKey = settings.requestKey || utils.createRequestId?.('miniapp-action') || String(Date.now());
    async function run(event) {
      event?.preventDefault?.();
      settings.button.disabled = true;
      settings.button.setAttribute('aria-busy', 'true');
      try {
        return await (utils.singleFlight ? utils.singleFlight(requestKey, function () { return settings.operation(requestKey); }) : settings.operation(requestKey));
      } catch (error) {
        if (!error || !['client_network_unavailable', 'client_request_timeout'].includes(error.code)) requestKey = settings.requestKey || utils.createRequestId?.('miniapp-action') || String(Date.now());
        throw error;
      } finally {
        settings.button.disabled = false;
        settings.button.removeAttribute('aria-busy');
      }
    }
    settings.button.addEventListener('click', function (event) { run(event).catch(function () {}); });
    return Object.freeze({ run: run, requestKey: function () { return requestKey; }, reset: function () { requestKey = utils.createRequestId?.('miniapp-action') || String(Date.now()); } });
  }

  const TABLE_ZOOM_LEVELS = Object.freeze([20, 40, 60, 80, 90, 100, 110, 125, 140, 160, 180, 200]);

  function bindTableZoom(root, storageKey) {
    if (!root || root.dataset.tableZoomBound === '1') return null;
    const tableWrap = root.querySelector('[data-miniapp-table-zoom-target]');
    const outButton = root.querySelector('[data-miniapp-table-zoom-out]');
    const resetButton = root.querySelector('[data-miniapp-table-zoom-reset]');
    const inButton = root.querySelector('[data-miniapp-table-zoom-in]');
    if (!tableWrap || !outButton || !resetButton || !inButton) return null;
    root.dataset.tableZoomBound = '1';
    let stored = 100;
    try { stored = Number(window.localStorage.getItem(storageKey || 'miniapp-table-zoom') || 100); } catch (_) {}
    let level = TABLE_ZOOM_LEVELS.includes(stored) ? stored : 100;
    function render(next, persist) {
      level = TABLE_ZOOM_LEVELS.includes(Number(next)) ? Number(next) : 100;
      tableWrap.style.setProperty('--miniapp-table-scale', String(level / 100));
      resetButton.textContent = level + '%';
      resetButton.setAttribute('aria-label', 'Table zoom ' + level + '%. Reset to 100%.');
      outButton.disabled = level === TABLE_ZOOM_LEVELS[0];
      inButton.disabled = level === TABLE_ZOOM_LEVELS[TABLE_ZOOM_LEVELS.length - 1];
      if (persist) {
        try { window.localStorage.setItem(storageKey || 'miniapp-table-zoom', String(level)); } catch (_) {}
      }
    }
    function adjacent(direction) {
      const index = TABLE_ZOOM_LEVELS.indexOf(level);
      render(TABLE_ZOOM_LEVELS[Math.max(0, Math.min(TABLE_ZOOM_LEVELS.length - 1, index + direction))], true);
    }
    outButton.addEventListener('click', function () { adjacent(-1); });
    inButton.addEventListener('click', function () { adjacent(1); });
    resetButton.addEventListener('click', function () { render(100, true); });
    render(level, false);
    return Object.freeze({ getLevel: function () { return level; }, setLevel: function (value) { render(value, true); } });
  }

  function createPagedInbox({ root, badge, loadPage, renderItems, onError }) {
    const list = root.querySelector('[data-inbox-list]');
    const pagination = root.querySelector('[data-inbox-pagination]');
    const previous = root.querySelector('[data-inbox-prev]');
    const next = root.querySelector('[data-inbox-next]');
    const range = root.querySelector('[data-inbox-range]');
    let page = 1, pages = 1, sequence = 0, loading = false;
    function updateButtons() {
      previous.disabled = loading || page <= 1;
      next.disabled = loading || page >= pages;
      list.setAttribute('aria-busy', String(loading));
    }
    function display(payload) {
      const rows = payload.notification_items || [];
      const total = Number(payload.notification_count || 0);
      const info = payload.notification_pagination || { page: 1, pages: 1, start: total ? 1 : 0, end: rows.length };
      page = info.page; pages = info.pages;
      renderItems(list, rows);
      badge.textContent = total > 99 ? '99+' : String(total);
      badge.hidden = !total;
      badge.parentElement.setAttribute('aria-label', `${total} tasks needing attention`);
      range.textContent = `${info.start}\u2013${info.end} of ${total}`;
      pagination.hidden = pages <= 1;
      list.scrollTop = 0;
    }
    function setPayload(payload) {
      sequence++; loading = false;
      display(payload); updateButtons();
    }
    async function load(requestedPage = page) {
      const request = ++sequence;
      loading = true; updateButtons();
      try {
        const payload = await loadPage(requestedPage);
        if (request === sequence) display(payload);
      } catch (error) {
        if (request === sequence && error?.name !== 'AbortError') onError(error);
      } finally {
        if (request === sequence) { loading = false; updateButtons(); }
      }
    }
    previous.addEventListener('click', () => load(page - 1));
    next.addEventListener('click', () => load(page + 1));
    updateButtons();
    return Object.freeze({ setPayload, load });
  }

  window.MiniAppComponents = Object.freeze({
    createPagedInbox: createPagedInbox,
    bindSearch: bindSearch,
    renderFilterChips: renderFilterChips,
    bindFilterSheet: bindFilterSheet,
    bindPagination: bindPagination,
    showFeedback: showFeedback,
    createListContext: createListContext,
    bindSingleFlightAction: bindSingleFlightAction,
    TABLE_ZOOM_LEVELS: TABLE_ZOOM_LEVELS,
    bindTableZoom: bindTableZoom,
  });

  // Shared report controls keep the standalone Mini Apps and Portal in step.
  function chooseExcelExport({ trigger, id = 'miniapp-excel-dialog' } = {}) {
    if (document.querySelector('.miniapp-excel-dialog[open]')) return Promise.resolve(null);
    const opener = trigger || document.activeElement;
    const dialog = document.createElement('dialog');
    dialog.id = id;
    dialog.className = 'miniapp-excel-dialog';
    dialog.setAttribute('aria-labelledby', `${id}-title`);
    dialog.innerHTML = `<header class="miniapp-report-dialog-head"><h2 id="${id}-title">Download Excel</h2><button type="button" data-scope="cancel" aria-label="Close download options">×</button></header><p>Choose the records to include.</p><div class="miniapp-export-choices"><button type="button" class="primary btn btn-primary" data-scope="filtered">Download filtered</button><button type="button" class="secondary btn btn-secondary" data-scope="all">Download all</button></div><p class="miniapp-export-scope-note">All includes every date within this report and your access.</p>`;
    document.body.appendChild(dialog);
    return new Promise(resolve => {
      let settled = false;
      const finish = scope => {
        if (settled) return;
        settled = true; dialog.close(); dialog.remove();
        if (opener?.isConnected) opener.focus();
        resolve(scope);
      };
      dialog.addEventListener('click', event => {
        const button = event.target.closest('[data-scope]');
        if (button) finish(button.dataset.scope === 'cancel' ? null : button.dataset.scope);
        else if (event.target === dialog) {
          const box = dialog.getBoundingClientRect();
          if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) finish(null);
        }
      });
      dialog.addEventListener('cancel', event => { event.preventDefault(); finish(null); });
      dialog.addEventListener('close', () => finish(null));
      dialog.showModal();
      dialog.querySelector('[data-scope="filtered"]').focus();
    });
  }

  function setChartHelp(target, text, warning = '') {
    if (!target) return;
    const panel = target.closest('article') || target.parentElement;
    let heading = panel?.querySelector('.tat-report-chart-head, .report-chart-head, header');
    if (!heading && panel?.querySelector('h3')) {
      const title = panel.querySelector('h3');
      heading = document.createElement('div'); heading.className = 'tat-report-chart-head';
      title.before(heading); heading.appendChild(title);
    }
    if (!heading) return;
    let help = heading.querySelector('.miniapp-chart-help');
    if (!help) {
      help = document.createElement('details'); help.className = 'miniapp-chart-help';
      const toggle = document.createElement('summary');
      toggle.textContent = '?'; toggle.setAttribute('aria-label', 'About this chart');
      const content = document.createElement('div'); content.className = 'miniapp-chart-help-content';
      help.append(toggle, content); heading.appendChild(help);
    }
    help.querySelector('.miniapp-chart-help-content').textContent = String(text || target.textContent || '');
    help.hidden = !help.querySelector('.miniapp-chart-help-content').textContent;
    target.textContent = warning;
    target.hidden = !warning;
  }

  function closeExcelExport() {
    const dialog = document.querySelector('.miniapp-excel-dialog[open]');
    if (!dialog) return false;
    dialog.close(); return true;
  }

  function chartPresentation({ id, temporal = false, composition = false, stacked = false, count = 0 } = {}) {
    if (temporal) return { defaultType: 'line', allowedTypes: ['line', 'bar'] };
    if (stacked) return { defaultType: 'stacked_bar', allowedTypes: ['stacked_bar', 'bar'] };
    if (composition && count > 0 && count <= 8) return { defaultType: 'doughnut', allowedTypes: ['doughnut', 'bar'] };
    return { defaultType: 'bar', allowedTypes: ['bar', ...(id === 'case_progression' ? ['line'] : [])] };
  }

  // One measurement contract for report axes and tooltips. Numeric values
  // stay in their source unit; do not silently label minutes as hours/days.
  function chartMeasurement(unit = 'cases', label = '') {
    const names = { cases:'Cases', complaints:'Complaints', actions:'Actions',
      minutes:'Minutes', hours:'Hours', days:'Days', percent:'Percentage (%)',
      KES:'KES', cases_per_assignee:'Cases per assignee' };
    const axisTitle = label || names[unit] || unit;
    const suffix = {percent:'%', KES:' KES', cases_per_assignee:' cases per assignee'}[unit] || ` ${unit}`;
    return { axisTitle, format(value) {
      if (value == null || !Number.isFinite(Number(value))) return 'Unavailable';
      return `${new Intl.NumberFormat('en-KE', {maximumFractionDigits:2}).format(Number(value))}${suffix}`;
    } };
  }

  function applyChartMeasurement(options, {unit, label, horizontal = false, color} = {}) {
    const measurement = chartMeasurement(unit, label);
    options.plugins ||= {};
    options.plugins.tooltip ||= {};
    options.plugins.tooltip.callbacks ||= {};
    options.plugins.tooltip.callbacks.label = context => `${context.dataset.label || context.label}: ${measurement.format(context.raw)}`;
    if (options.scales && Object.keys(options.scales).length) {
      const axis = options.scales[horizontal ? 'x' : 'y'];
      axis.title = {display:true, text:measurement.axisTitle, color, font:{size:11}};
    } else {
      options.plugins.subtitle = {display:true, text:measurement.axisTitle, position:'bottom', color, font:{size:11}};
    }
    return options;
  }

  const chartMenus = '.miniapp-chart-help[open], .miniapp-chart-options[open], .tat-chart-options[open], .portal-chart-settings[open], .portal-chart-cases[open]';
  function prepareChartMenu(menu) {
    menu.classList.add('miniapp-chart-popover');
    let panel = menu.querySelector(':scope > .miniapp-chart-menu');
    if (!panel) { panel = document.createElement('div'); panel.className = 'miniapp-chart-menu'; menu.appendChild(panel); }
    [...menu.children].filter(child => child.tagName !== 'SUMMARY' && child !== panel).forEach(child => panel.appendChild(child));
  }
  function closeChartMenus(root = document, restoreFocus = true) {
    const menus = [...root.querySelectorAll(chartMenus)];
    menus.forEach(menu => {menu.open = false;});
    if (restoreFocus) menus[0]?.querySelector('summary')?.focus();
    return menus.length > 0;
  }
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && closeChartMenus()) {event.preventDefault(); event.stopPropagation();}
  }, true);
  document.addEventListener('click', event => {
    document.querySelectorAll(chartMenus).forEach(help => {
      if (!help.contains(event.target)) help.open = false;
    });
  });
  const chartOptionsIcon = '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="M4 7h16M4 17h16"/><circle cx="9" cy="7" r="2" fill="var(--bg-surface, var(--tat-surface, var(--surface, #fff)))"/><circle cx="15" cy="17" r="2" fill="var(--bg-surface, var(--tat-surface, var(--surface, #fff)))"/></svg>';
  function chartTypeIcon(type) {
    const paths = {
      line: '<path d="M3 3v18h18M6 15l5-5 4 3 6-7"/>',
      bar: '<path d="M3 3v18h18M7 16v-5M12 16V7M17 16v-8"/>',
      stacked_bar: '<path d="M3 3v18h18M7 16V7M12 16V5M17 16V9M5 11h4M10 9h4M15 12h4"/>',
      pie: '<path d="M21 12A9 9 0 1 1 12 3v9zM15 3.5V9h5.5A9 9 0 0 0 15 3.5Z"/>',
      doughnut: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="4"/><path d="M12 3v5M16 12h5"/>',
    };
    return `<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[type] || paths.bar}</svg>`;
  }
  // Bucket keys already represent local reporting dates. Avoid parsing them as
  // UTC instants (and shifting days in the viewer's timezone).
  function formatChartDate(value) {
    const text = String(value ?? '');
    const match = /^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?$/.exec(text);
    if (!match) return text;
    const [, year, month = '01', day = '01'] = match;
    const date = new Date(Date.UTC(Number(year), Number(month) - 1, Number(day)));
    if (date.getUTCFullYear() !== Number(year) || date.getUTCMonth() + 1 !== Number(month) || date.getUTCDate() !== Number(day)) return text;
    return `${day}-${month}-${year.slice(-2)}`;
  }
  function periodDates(mode, values = {}) {
    const parts = new Intl.DateTimeFormat('en-CA', { timeZone: 'Africa/Nairobi', year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(new Date());
    const p = Object.fromEntries(parts.map(part => [part.type, part.value]));
    const today = `${p.year}-${p.month}-${p.day}`;
    if (mode === 'all') return { from: '', to: '' };
    if (mode === 'custom') return { from: values.from || '', to: values.to || '' };
    const year = Number(values.year || p.year);
    const quarter = Number(values.quarter || Math.ceil(Number(p.month) / 3));
    let startMonth = mode === 'year' ? 1 : mode === 'quarter' ? quarter * 3 - 2 : Number((values.month || `${p.year}-${p.month}`).slice(5));
    const selectedYear = mode === 'month' ? Number((values.month || p.year).slice(0, 4)) : year;
    if (!['month','quarter','year'].includes(mode) || !Number.isInteger(selectedYear) || selectedYear < 1900 || selectedYear > 9998 || !Number.isInteger(startMonth) || startMonth < 1 || startMonth > 12) throw new Error('Choose a valid period.');
    const endMonth = mode === 'year' ? 12 : mode === 'quarter' ? startMonth + 2 : startMonth;
    const from = `${selectedYear}-${String(startMonth).padStart(2, '0')}-01`;
    let to = `${selectedYear}-${String(endMonth).padStart(2, '0')}-${new Date(Date.UTC(selectedYear, endMonth, 0)).getUTCDate()}`;
    if (from <= today && today <= to) to = today;
    return { from, to };
  }
  window.MiniAppReportControls = Object.freeze({ chooseExcelExport, closeExcelExport, setChartHelp, chartPresentation, chartOptionsIcon, chartTypeIcon, formatChartDate, periodDates, chartMeasurement, applyChartMeasurement, prepareChartMenu, closeChartMenus });
})();
