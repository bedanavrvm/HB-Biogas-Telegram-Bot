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
    state().filtersByQueue[queueKey] ||= { county: [], branch: [], status: [], hbg_visit_date_from: '', hbg_visit_date_to: '', jbl_visit_date_from: '', jbl_visit_date_to: '', ordering: '' };
    const filters = state().filtersByQueue[queueKey];
    filters.county = listValue(filters.county);
    filters.branch = listValue(filters.branch);
    filters.status = listValue(filters.status);
    ['hbg_visit_date_from', 'hbg_visit_date_to', 'jbl_visit_date_from', 'jbl_visit_date_to'].forEach(key => { filters[key] = String(filters[key] || ''); });
    return filters;
  }

  function listValue(value) {
    if (Array.isArray(value)) return value.filter(Boolean).map(String);
    return value ? [String(value)] : [];
  }

  function optionValue(option) {
    if (option && typeof option === 'object') return String(option.value || option.code || option.name || option.label || '');
    return String(option || '');
  }

  function optionLabel(option) {
    if (option && typeof option === 'object') return String(option.label || option.name || option.value || option.code || '');
    return String(option || '');
  }

  const statusLabels = {
    jbl_visit: 'Awaiting visit', credit: 'Awaiting credit analysis',
    final_review: 'Awaiting final review', order: 'Ready for order',
    ordered: 'Ordered', deferred: 'Deferred', rejected: 'Rejected', withdrawn: 'Withdrawn',
  };

  function displayDate(value) {
    const match = String(value || '').match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (match) return `${match[3]}-${match[2]}-${match[1]}`;
    return /^\d{2}-\d{2}-\d{4}$/.test(String(value || '')) ? String(value) : '';
  }

  function isoDate(value) {
    const text = String(value || '').trim();
    if (!text) return '';
    const match = text.match(/^(\d{2})-(\d{2})-(\d{4})$/);
    if (!match) return null;
    const iso = `${match[3]}-${match[2]}-${match[1]}`;
    const date = new Date(`${iso}T00:00:00Z`);
    return Number.isNaN(date.getTime()) || date.toISOString().slice(0, 10) !== iso ? null : iso;
  }

  function cardOptions(root) {
    return Array.from(document.querySelectorAll(`[data-qkey="${CSS.escape(root.dataset.portalQueueTools || '')}"]`)).map(card => ({
      county: card.dataset.county || '', branch: card.dataset.branch || '',
      workflow_state: card.dataset.workflowState || '',
      hbg_visit_date: card.dataset.hbgVisit === '1', jbl_visit_date: card.dataset.jblVisit === '1',
    }));
  }

  function availableOptions(queueKey, root, rows) {
    const source = Array.isArray(rows) && rows.length ? rows : cardOptions(root);
    if (!source.length) return null;
    const choices = key => Array.from(new Set(source.map(row => String(row[key] || '').trim()).filter(Boolean))).sort((a, b) => a.localeCompare(b));
    return {
      county: choices('county'), branch: choices('branch'),
      status: queueKey === 'all' ? choices('workflow_state').filter(value => statusLabels[value]) : [],
      has_hbg_visit_date: source.some(row => Boolean(row.hbg_visit_date || row.hbg_visit)),
      has_jbl_visit_date: source.some(row => Boolean(row.jbl_visit_date || row.jbl_visit)),
    };
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
    if (key.endsWith('_date_from') || key.endsWith('_date_to')) return displayDate(value);
    if (Array.isArray(value)) return value.map(item => readableValue(root, key, item)).join(', ');
    const checkbox = root.querySelector('input[name="' + key + '"][value="' + CSS.escape(value) + '"]');
    if (checkbox) return checkbox.closest('label')?.textContent.trim() || value;
    const option = root.querySelector('[name="' + key + '"] option[value="' + CSS.escape(value) + '"]');
    return option?.textContent || value;
  }

  function persist(queueKey, focusId) {
    contextFor(queueKey)?.write?.({
      page: state().pages?.[queueKey] || 1,
      filters: filtersFor(queueKey),
      search: state().searches?.[queueKey] || '',
      scrollY: document.getElementById('content')?.scrollTop || 0,
      focusId: String(focusId || ''),
    });
  }

  function updatePresentation(root, queueKey) {
    const filters = filtersFor(queueKey);
    const active = Object.entries(filters).filter(function (entry) {
      return Array.isArray(entry[1]) ? entry[1].length > 0 : Boolean(String(entry[1] || '').trim());
    });
    const count = root.querySelector('[data-portal-filter-count]');
    if (count) {
      count.textContent = String(active.length);
      count.hidden = active.length === 0;
    }
    components.renderFilterChips?.(
      root.querySelector('[data-portal-filter-chips]'),
      Object.fromEntries(active.map(function (entry) {
        const labels = { county: 'County', branch: 'Branch', status: 'Status', hbg_visit_date_from: 'HB visit from', hbg_visit_date_to: 'HB visit to', jbl_visit_date_from: 'JBL visit from', jbl_visit_date_to: 'JBL visit to', ordering: 'Order' };
        return [entry[0], { label: labels[entry[0]], value: entry[1], text: readableValue(root, entry[0], entry[1]) }];
      })),
      function (key) {
        filters[key] = ['county', 'branch', 'status'].includes(key) ? [] : '';
        root.querySelectorAll('[name="' + key + '"]').forEach(control => {
          if (control.type === 'checkbox') control.checked = false;
          else control.value = '';
        });
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
        county: listValue(saved.filters?.county),
        branch: listValue(saved.filters?.branch),
        status: queueKey === 'all' ? listValue(saved.filters?.status) : [],
        hbg_visit_date_from: String(saved.filters?.hbg_visit_date_from || ''),
        hbg_visit_date_to: String(saved.filters?.hbg_visit_date_to || ''),
        jbl_visit_date_from: String(saved.filters?.jbl_visit_date_from || ''),
        jbl_visit_date_to: String(saved.filters?.jbl_visit_date_to || ''),
        ordering: String(saved.filters?.ordering || ''),
      };
    }
    if (!state().pages[queueKey] || state().pages[queueKey] === 1) state().pages[queueKey] = Math.max(1, Number(saved.page || 1));
    if (!Object.prototype.hasOwnProperty.call(state().searches, queueKey)) state().searches[queueKey] = String(saved.search || '');
  }

  function setupQueueTools(queueKey, rows) {
    const root = document.querySelector('[data-portal-queue-tools="' + CSS.escape(queueKey) + '"]');
    if (!root) return;
    restoreQueueState(queueKey);
    const filters = filtersFor(queueKey);
    const form = root.querySelector('[data-portal-filter-form]');
    const available = availableOptions(queueKey, root, rows);
    ['county', 'branch', 'status'].forEach(key => {
      const container = form?.querySelector('[data-portal-filter-options="' + key + '"]');
      if (!container) return populateSelect(form?.elements[key], key === 'county' ? state().metaCounties : state().metaBranches, filters[key]);
      const base = key === 'county' ? state().metaCounties : key === 'branch' ? state().metaBranches : Object.keys(statusLabels).map(value => ({value, label: statusLabels[value]}));
      const selected = listValue(filters[key]);
      const current = new Set([...(available?.[key] || []), ...selected]);
      // Once staff have selected a value, retain the complete permitted list for
      // that group. Otherwise selecting one county/status would hide every
      // other choice and make a multi-select filter impossible to adjust.
      const options = available && !selected.length ? base.filter(option => current.has(optionValue(option))) : base;
      const signature = JSON.stringify(options.map(option => [optionValue(option), optionLabel(option)]));
      if (container.dataset.optionsSignature === signature) return;
      container.dataset.optionsSignature = signature;
      container.replaceChildren();
      options.forEach(option => {
        const label = document.createElement('label'), input = document.createElement('input');
        input.type = 'checkbox'; input.name = key; input.value = optionValue(option);
        label.append(input, document.createTextNode(optionLabel(option))); container.append(label);
      });
    });
    [['hbg_visit_date', 'has_hbg_visit_date'], ['jbl_visit_date', 'has_jbl_visit_date']].forEach(([key, availabilityKey]) => {
      const group = form?.querySelector('[data-portal-filter-group="' + key + '"]');
      if (!group) return;
      const active = Boolean(filters[`${key}_from`] || filters[`${key}_to`]);
      group.hidden = Boolean(available && !available[availabilityKey] && !active);
    });
    form?.querySelectorAll('input[type="checkbox"]').forEach(input => {
      const selected = Array.isArray(filters[input.name]) ? filters[input.name] : [filters[input.name]];
      input.checked = selected.includes(input.value);
    });
    if (form?.elements.ordering) form.elements.ordering.value = filters.ordering || '';
    ['hbg_visit_date_from', 'hbg_visit_date_to', 'jbl_visit_date_from', 'jbl_visit_date_to'].forEach(key => { if (form?.elements[key]) form.elements[key].value = displayDate(filters[key]); });
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
      onApply: function () {},
    });
    let changeTimer;
    form?.addEventListener('change', function () {
      const data = new FormData(form);
      ['county', 'branch', 'status'].forEach(key => {
        filters[key] = data.getAll(key);
      });
      filters.ordering = String(data.get('ordering') || '');
      let invalidDate = false;
      ['hbg_visit_date_from', 'hbg_visit_date_to', 'jbl_visit_date_from', 'jbl_visit_date_to'].forEach(key => {
        const control = form.elements[key];
        const normalized = isoDate(data.get(key));
        if (normalized === null) {
          invalidDate = true;
          control?.setCustomValidity('Use DD-MM-YYYY.');
          control?.reportValidity?.();
          return;
        }
        control?.setCustomValidity('');
        filters[key] = normalized;
        if (control && normalized) control.value = displayDate(normalized);
      });
      if (invalidDate) return;
      state().pages[queueKey] = 1;
      updatePresentation(root, queueKey);
      persist(queueKey);
      clearTimeout(changeTimer);
      changeTimer = setTimeout(() => deps.loadQueue(queueKey, 1), 180);
    });
    root.querySelector('[data-portal-filter-reset]')?.addEventListener('click', function () {
      filters.county = [];
      filters.branch = [];
      filters.status = [];
      filters.ordering = '';
      ['hbg_visit_date_from', 'hbg_visit_date_to', 'jbl_visit_date_from', 'jbl_visit_date_to'].forEach(key => { filters[key] = ''; });
      clearTimeout(changeTimer);
      form?.reset();
      state().pages[queueKey] = 1;
      updatePresentation(root, queueKey);
      persist(queueKey);
      sheetController?.close?.();
      deps.loadQueue(queueKey, 1);
    });
  }

  function updateFilterOptions(rows) {
    const queueKey = state().activePage;
    if (deps.queueConfig[queueKey]) setupQueueTools(queueKey, rows);
  }

  function rememberSelection(queueKey, farmerId) { persist(queueKey, farmerId); }
  function rememberPage(queueKey) { persist(queueKey); }

  function restorePosition(queueKey) {
    const saved = contextFor(queueKey)?.read?.();
    if (!saved) return;
    window.requestAnimationFrame(function () {
      document.getElementById('content')?.scrollTo({ top: saved.scrollY || 0, behavior: 'auto' });
      if (saved.focusId) document.querySelector('[data-farmer-id="' + CSS.escape(saved.focusId) + '"]')?.focus?.({ preventScroll: true });
    });
  }

  function init(initialDeps) { deps = initialDeps; }

  function updateResultCount(queueKey, total) {
    if (!Number.isFinite(Number(total))) return;
    const root = document.querySelector('[data-portal-queue-tools="' + CSS.escape(queueKey) + '"]');
    root?.querySelectorAll('[data-portal-matching-count]').forEach(node => {
      node.textContent = `${total} matching case${Number(total) === 1 ? '' : 's'}`;
    });
  }

  window.PortalMiniAppFilters = {
    init: init,
    updateResultCount: updateResultCount,
    updateFilterOptions: updateFilterOptions,
    setupQueueTools: setupQueueTools,
    rememberSelection: rememberSelection,
    rememberPage: rememberPage,
    restorePosition: restorePosition,
    applyFilters: function () {},
    renderFilteredFarmerList: function () {},
  };
})();
