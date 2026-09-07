'use strict';

const assert = require('node:assert/strict');
const path = require('node:path');

const zoom = require(path.join(__dirname, '..', 'static', 'miniapp', 'ag_grid_zoom.js'));

function button() {
  const listeners = {};
  return {
    attributes: {}, disabled: false, textContent: '', title: '',
    addEventListener(name, callback) { listeners[name] = callback; },
    setAttribute(name, value) { this.attributes[name] = value; },
    click() { listeners.click(); },
  };
}

assert.deepEqual(zoom.LEVELS, [20, 40, 60, 80, 90, 100, 110, 125, 140]);
assert.equal(zoom.normalizeLevel('not-a-number'), 100);
assert.equal(zoom.normalizeLevel(119), 125);
assert.equal(zoom.adjacentLevel(100, 1), 110);
assert.equal(zoom.adjacentLevel(20, -1), 20);
assert.deepEqual(zoom.metricsFor(125, {
  fontSize: 10, gridSize: 4, rowHeight: 34, headerHeight: 36, cellPadding: 6,
}), {
  level: 125, fontSize: 12.5, gridSize: 5, rowHeight: 43, headerHeight: 45, cellPadding: 7.5,
  smallFontSize: 11.3,
});
assert.deepEqual(zoom.scaleColumnDefs([
  { field: 'name', width: 200, minWidth: 100 },
  { headerName: 'Group', children: [{ field: 'status', width: 120 }] },
], 20), [
  { field: 'name', width: 40, minWidth: 20 },
  { headerName: 'Group', children: [{ field: 'status', width: 24, minWidth: 8 }] },
]);

const stored = new Map([['tat-report-grid-zoom', '110']]);
const storage = {
  getItem(key) { return stored.get(key) || null; },
  setItem(key, value) { stored.set(key, value); },
};
const styles = new Map();
const grid = { style: { setProperty(name, value) { styles.set(name, value); } } };
const outButton = button();
const resetButton = button();
const inButton = button();
const container = { hidden: true };
const apiCalls = [];
let columnDefs = [{ field: 'name', width: 120, minWidth: 80 }];
const api = {
  getGridOption(name) { return name === 'columnDefs' ? columnDefs : null; },
  setGridOption(name, value) { if (name === 'columnDefs') columnDefs = value; apiCalls.push([name, value]); },
  resetRowHeights() { apiCalls.push(['resetRowHeights']); },
  refreshHeader() { apiCalls.push(['refreshHeader']); },
};

const control = zoom.bind({
  container, gridElement: grid, outButton, resetButton, inButton,
  storage, storageKey: 'tat-report-grid-zoom', apiProvider: () => api,
  defaults: { fontSize: 10, gridSize: 4, rowHeight: 34, headerHeight: 36, cellPadding: 6 },
});

assert.equal(container.hidden, false);
assert.equal(control.getLevel(), 110);
assert.equal(resetButton.textContent, '110%');
assert.equal(styles.get('--ag-font-size'), '11px');
assert.equal(styles.get('--ag-row-height'), '37px');
assert.deepEqual(columnDefs, [{ field: 'name', width: 132, minWidth: 88 }]);
assert.ok(apiCalls.some(call => call[0] === 'rowHeight' && call[1] === 37));
assert.ok(apiCalls.some(call => call[0] === 'headerHeight' && call[1] === 40));

inButton.click();
assert.equal(control.getLevel(), 125);
assert.equal(stored.get('tat-report-grid-zoom'), '125');
assert.equal(resetButton.textContent, '125%');

control.setLevel(140);
assert.equal(inButton.disabled, true);
assert.equal(outButton.disabled, false);
resetButton.click();
assert.equal(control.getLevel(), 100);
assert.equal(stored.get('tat-report-grid-zoom'), '100');

control.setLevel(20);
assert.equal(outButton.disabled, true);
assert.equal(styles.get('--ag-row-height'), '7px');
assert.deepEqual(columnDefs, [{ field: 'name', width: 24, minWidth: 16 }]);
assert.match(resetButton.attributes['aria-label'], /20%/);

console.log('AG Grid zoom tests passed');
