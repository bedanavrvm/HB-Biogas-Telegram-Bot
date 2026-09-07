(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.MiniAppAgGridZoom = api;
}(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';

  const LEVELS = Object.freeze([20, 40, 60, 80, 90, 100, 110, 125, 140]);

  function normalizeLevel(value) {
    if (value === null || value === undefined || String(value).trim() === '') return 100;
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return 100;
    return LEVELS.reduce((closest, level) => (
      Math.abs(level - numeric) < Math.abs(closest - numeric) ? level : closest
    ), 100);
  }

  function metricsFor(level, defaults) {
    const normalized = normalizeLevel(level);
    const scale = normalized / 100;
    const source = Object.assign({
      fontSize: 11,
      gridSize: 4,
      rowHeight: 34,
      headerHeight: 36,
      cellPadding: 8,
      smallFontSize: null,
    }, defaults || {});
    return {
      level: normalized,
      fontSize: Math.round(source.fontSize * scale * 10) / 10,
      gridSize: Math.max(0.8, Math.round(source.gridSize * scale * 10) / 10),
      rowHeight: Math.max(7, Math.round(source.rowHeight * scale)),
      headerHeight: Math.max(8, Math.round(source.headerHeight * scale)),
      cellPadding: Math.max(1, Math.round(source.cellPadding * scale * 10) / 10),
      smallFontSize: Math.round((source.smallFontSize || source.fontSize * 0.9) * scale * 10) / 10,
    };
  }

  function cloneColumnDefs(definitions) {
    return (definitions || []).map(definition => {
      const copy = Object.assign({}, definition);
      if (definition.children) copy.children = cloneColumnDefs(definition.children);
      return copy;
    });
  }

  function scaleColumnDefs(definitions, level) {
    const scale = normalizeLevel(level) / 100;
    return cloneColumnDefs(definitions).map(definition => {
      const scaled = Object.assign({}, definition);
      ['width', 'minWidth', 'maxWidth'].forEach(key => {
        if (Number.isFinite(Number(definition[key]))) {
          scaled[key] = Math.max(6, Math.round(Number(definition[key]) * scale));
        }
      });
      if (Number.isFinite(Number(definition.width)) && !Number.isFinite(Number(definition.minWidth))) {
        scaled.minWidth = Math.max(6, Math.round(Math.min(Number(definition.width), 40) * scale));
      }
      if (definition.children) scaled.children = scaleColumnDefs(definition.children, level);
      return scaled;
    });
  }

  function readLevel(storage, key) {
    if (!storage || !key) return 100;
    try { return normalizeLevel(storage.getItem(key)); } catch (error) { return 100; }
  }

  function writeLevel(storage, key, value) {
    if (!storage || !key) return;
    try { storage.setItem(key, String(value)); } catch (error) { /* Preference storage is optional. */ }
  }

  function adjacentLevel(current, direction) {
    const index = LEVELS.indexOf(normalizeLevel(current));
    return LEVELS[Math.max(0, Math.min(LEVELS.length - 1, index + direction))];
  }

  function availableStorage() {
    try { return typeof localStorage === 'undefined' ? null : localStorage; } catch (error) { return null; }
  }

  function bind(options) {
    const settings = options || {};
    const grid = settings.gridElement;
    const outButton = settings.outButton;
    const inButton = settings.inButton;
    const resetButton = settings.resetButton;
    if (!grid || !outButton || !inButton || !resetButton) return null;

    const storage = settings.storage === undefined ? availableStorage() : settings.storage;
    let level = readLevel(storage, settings.storageKey);
    let baseColumnDefs = null;

    function applyGridApi(metrics, options) {
      const api = typeof settings.apiProvider === 'function' ? settings.apiProvider() : null;
      if (!api) return;
      if (settings.scaleColumns !== false) {
        if (!baseColumnDefs || (options && options.recaptureColumns)) {
          const current = api.getGridOption?.('columnDefs') || api.getColumnDefs?.() || [];
          baseColumnDefs = cloneColumnDefs(current);
        }
        if (baseColumnDefs.length) {
          api.setGridOption?.('columnDefs', scaleColumnDefs(baseColumnDefs, metrics.level));
        }
      }
      api.setGridOption?.('rowHeight', metrics.rowHeight);
      api.setGridOption?.('headerHeight', metrics.headerHeight);
      api.resetRowHeights?.();
      api.refreshHeader?.();
    }

    function render(nextLevel, persist, options) {
      level = normalizeLevel(nextLevel);
      const metrics = metricsFor(level, settings.defaults);
      grid.style.setProperty('--ag-font-size', `${metrics.fontSize}px`);
      grid.style.setProperty('--ag-grid-size', `${metrics.gridSize}px`);
      grid.style.setProperty('--ag-row-height', `${metrics.rowHeight}px`);
      grid.style.setProperty('--ag-header-height', `${metrics.headerHeight}px`);
      grid.style.setProperty('--ag-cell-horizontal-padding', `${metrics.cellPadding}px`);
      grid.style.setProperty('--miniapp-ag-small-font-size', `${metrics.smallFontSize}px`);
      resetButton.textContent = `${level}%`;
      resetButton.setAttribute('aria-label', `Table zoom ${level}%. Reset to 100%.`);
      resetButton.title = `Table zoom ${level}%. Reset to 100%.`;
      outButton.disabled = level === LEVELS[0];
      inButton.disabled = level === LEVELS[LEVELS.length - 1];
      applyGridApi(metrics, options);
      if (persist) writeLevel(storage, settings.storageKey, level);
      if (typeof settings.onChange === 'function') settings.onChange(level, metrics);
      return metrics;
    }

    outButton.addEventListener('click', () => render(adjacentLevel(level, -1), true));
    inButton.addEventListener('click', () => render(adjacentLevel(level, 1), true));
    resetButton.addEventListener('click', () => render(100, true));
    if (settings.container) settings.container.hidden = false;
    render(level, false);

    return Object.freeze({
      getLevel: () => level,
      setLevel: value => render(value, true),
      refresh: options => render(level, false, options),
    });
  }

  return { LEVELS, normalizeLevel, metricsFor, scaleColumnDefs, adjacentLevel, bind };
}));
