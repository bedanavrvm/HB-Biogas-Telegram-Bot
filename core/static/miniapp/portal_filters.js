(function () {
  'use strict';

  const components = window.MiniAppComponents || {};
  const contexts = new Map();
  const boundRoots = new WeakSet();
  let deps = null;

  function state() { return deps.state; }

  function contextFor(queueKey) {
    if (!contexts.has(queueKey)) contexts.set(queueKey, components.createListContext?.('portal:' + queueKey) || null);
    return contexts.get(queueKey);
  }

  function filtersFor(queueKey) {
    state().filtersByQueue ||= {};
    state().filtersByQueue[queueKey] ||= { county: '', branch: '', ordering: '' };
    return state().filtersByQueue[queueKey];
  }

  function optionValue(option) {
    if (option && typeof option === 'object') return String(option.value || option.code || option.name || option.label || '');
    return String(option || '');
  }

  function optionLabel(option) {
    if (option && typeof option === 'object') return String(option.label || option.name || option.value || option.code || '');
    return String(option || '');
  }

  function populateSelect(select, options, selected) {
    if (!select) return;
    const first = select.options[0]?.cloneNode(true);
    select.replaceChildren();
    if (first) select.appendChild(first);
    (options || []).forEach(function (option) {
      const value = optionValue(option);
      if (!value) return;
      const node = document.createElement('option');
      node.value = value;
      node.textContent = optionLabel(option);
      select.appendChild(node);
    });
    select.value = selected || '';
  }

  function readableValue(root, key, value) {
    const option = root.querySelector('[name="' + key + '"] option[value="' + CSS.escape(value) + '"]');
    return option?.textContent || value;
  }

  function persist(queueKey, focusId) {
    contextFor(queueKey)?.write?.({
      page: state().pages?.[queueKey] || 1,
      filters: filtersFor(queueKey),
      search: state().searches?.[queueKey] || '',
      scrollY: window.scrollY,
      focusId: String(focusId || ''),
    });
  }

  function updatePresentation(root, queueKey) {
    const filters = filtersFor(queueKey);
    const active = Object.entries(filters).filter(function (entry) { return Boolean(String(entry[1] || '').trim()); });
    const count = root.querySelector('[data-portal-filter-count]');
    if (count) {
      count.textContent = String(active.length);
      count.hidden = active.length === 0;
    }
    components.renderFilterChips?.(
      root.querySelector('[data-portal-filter-chips]'),
      Object.fromEntries(active.map(function (entry) {
        const labels = { county: 'County', branch: 'Branch', ordering: 'Order' };
        return [entry[0], { label: labels[entry[0]], value: entry[1], text: readableValue(root, entry[0], entry[1]) }];
      })),
      function (key) {
        filters[key] = '';
        const control = root.querySelector('[name="' + key + '"]');
        if (control) control.value = '';
        updatePresentation(root, queueKey);
        state().pages[queueKey] = 1;
        persist(queueKey);
        deps.loadQueue(queueKey, 1);
      }
    );
  }

  function restoreQueueState(queueKey) {
    const saved = contextFor(queueKey)?.read?.() || {};
    state().filtersByQueue ||= {};
    state().searches ||= {};
    if (!state().filtersByQueue[queueKey]) {
      state().filtersByQueue[queueKey] = {
        county: String(saved.filters?.county || ''),
        branch: String(saved.filters?.branch || ''),
        ordering: String(saved.filters?.ordering || ''),
      };
    }
    if (!state().pages[queueKey] || state().pages[queueKey] === 1) state().pages[queueKey] = Math.max(1, Number(saved.page || 1));
    if (!Object.prototype.hasOwnProperty.call(state().searches, queueKey)) state().searches[queueKey] = String(saved.search || '');
  }

  function setupQueueTools(queueKey) {
    const root = document.querySelector('[data-portal-queue-tools="' + CSS.escape(queueKey) + '"]');
    if (!root) return;
    restoreQueueState(queueKey);
    const filters = filtersFor(queueKey);
    const form = root.querySelector('[data-portal-filter-form]');
    populateSelect(form?.elements.county, state().metaCounties, filters.county);
    populateSelect(form?.elements.branch, state().metaBranches, filters.branch);
    if (form?.elements.ordering) form.elements.ordering.value = filters.ordering || '';
    updatePresentation(root, queueKey);
    if (boundRoots.has(root)) return;
    boundRoots.add(root);

    const input = root.querySelector('[data-portal-queue-search]');
    if (input) input.value = String(state().searches[queueKey] || '');
    components.bindSearch?.({
      input: input,
      clearButton: root.querySelector('[data-portal-search-clear]'),
      delay: 250,
      onSearch: function (value) {
        state().searches[queueKey] = value;
        state().pages[queueKey] = 1;
        persist(queueKey);
        deps.loadQueue(queueKey, 1);
      },
    });
    const sheetController = components.bindFilterSheet?.({
      trigger: root.querySelector('[data-portal-filter-trigger]'),
      overlay: root.querySelector('[data-portal-filter-overlay]'),
      sheet: root.querySelector('[data-portal-filter-sheet]'),
      form: form,
      onApply: function (formData) {
        filters.county = String(formData.get('county') || '');
        filters.branch = String(formData.get('branch') || '');
        filters.ordering = String(formData.get('ordering') || '');
        state().pages[queueKey] = 1;
        updatePresentation(root, queueKey);
        persist(queueKey);
        deps.loadQueue(queueKey, 1);
      },
    });
    root.querySelector('[data-portal-filter-reset]')?.addEventListener('click', function () {
      filters.county = '';
      filters.branch = '';
      filters.ordering = '';
      form?.reset();
      state().pages[queueKey] = 1;
      updatePresentation(root, queueKey);
      persist(queueKey);
      sheetController?.close?.();
      deps.loadQueue(queueKey, 1);
    });
  }

  function updateFilterOptions() {
    const queueKey = state().activePage;
    if (deps.queueConfig[queueKey]) setupQueueTools(queueKey);
  }

  function rememberSelection(queueKey, farmerId) { persist(queueKey, farmerId); }
  function rememberPage(queueKey) { persist(queueKey); }

  function restorePosition(queueKey) {
    const saved = contextFor(queueKey)?.read?.();
    if (!saved || !saved.scrollY) return;
    window.requestAnimationFrame(function () {
      window.scrollTo({ top: saved.scrollY, behavior: 'auto' });
      if (saved.focusId) document.querySelector('[data-farmer-id="' + CSS.escape(saved.focusId) + '"]')?.focus?.({ preventScroll: true });
    });
  }

  function init(initialDeps) { deps = initialDeps; }

  window.PortalMiniAppFilters = {
    init: init,
    updateFilterOptions: updateFilterOptions,
    setupQueueTools: setupQueueTools,
    rememberSelection: rememberSelection,
    rememberPage: rememberPage,
    restorePosition: restorePosition,
    applyFilters: function () {},
    renderFilteredFarmerList: function () {},
  };
})();
