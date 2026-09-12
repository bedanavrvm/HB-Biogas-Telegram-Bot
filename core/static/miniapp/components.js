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
      ephemeralSearch = String(source.search || ephemeralSearch || '');
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

  window.MiniAppComponents = Object.freeze({
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
})();
