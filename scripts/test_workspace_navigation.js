'use strict';
// Pure allowlist/continuity checks. No browser server, network or customer data.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('../browser/node_modules/typescript');
const source = fs.readFileSync(path.join(__dirname, '../browser/src/workspace-navigation.ts'), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
const writes = [];
const window = { location: { href: 'http://127.0.0.1/staff/app/complaints/reports/?workspace=12&status=all&page=2&report=follow-up&group_by=week&from=2024-02-29&to=2024-03-09&date_basis=resolved&report_page=4' }, history: {
  pushState: (...args) => writes.push(args), replaceState: (...args) => writes.push(args),
} };
const sandbox = { window, URL, URLSearchParams, exports: {} };
vm.runInNewContext(compiled, sandbox);
const { readRoute, writeRoute, initialQueuePreferences, reportLocation, formDate } = sandbox.exports;
const route = readRoute();
assert.equal(route.view, 'reports'); assert.equal(route.report.view, 'follow-up');
assert.equal(route.report.grouping, 'week'); assert.equal(route.report.from, '2024-02-29');
assert.equal(route.report.page, 4);
window.location.href = 'http://127.0.0.1/staff/app/complaints/settings/';
assert.equal(readRoute().view, 'settings');
assert.equal(reportLocation(new URL('http://localhost/?range=month')).from.slice(-2), '01');
assert.equal(reportLocation(new URL('http://localhost/?range=year')).from.slice(-5), '01-01');
assert.equal(reportLocation(new URL('http://localhost/?range=all')).from, '');
assert.equal(formDate('22 Oct 2026'),'2026-10-22');
assert.equal(formDate('22 Sept 2026'),'2026-09-22');
assert.equal(formDate('22 Sep 2026'),'2026-09-22');
assert.equal(formDate('2024-02-29'),'2024-02-29');
for (const value of ['2026-02-31','31 Feb 2026','29 Feb 2026','2026-13-01','0000-01-01','12/01/2026']) assert.equal(formDate(value),'');
writeRoute({ ...route, report: { ...route.report, branch: 'Synthetic private branch', category: 'Synthetic private category' } });
assert.equal(writes[0][0], null); // No customer/history-state payload.
assert.equal(writes[0][2].includes('Synthetic'), false);
assert.equal(new URL(writes[0][2], 'http://localhost').searchParams.get('group_by'), 'week');
assert.equal(initialQueuePreferences(route, { default_filters: { status: 'resolved' } }, 'http://localhost/').status, 'resolved');
assert.equal(initialQueuePreferences(route, { default_filters: { status: 'resolved' } }, 'http://localhost/?status=all').status, 'all');
assert.equal(initialQueuePreferences(route, { default_filters: { status: 'invalid' } }, 'http://localhost/').status, 'pending');
for (const bad of ['2026-02-29', '2026-13-01', '2026-10-32', 'not-a-date', '21-10-2026']) {
  assert.equal(reportLocation(new URL('http://localhost/?from=' + bad)).from, '');
}
const invalid = reportLocation(new URL('http://localhost/?report=evil&group_by=secret&report_page=Infinity&from=2026-10-01x&report_status=evil&date_basis=evil&q=synthetic'));
assert.equal(invalid.view, 'overview'); assert.equal(invalid.grouping, 'month'); assert.equal(invalid.page, 1);
assert.equal(invalid.status, ''); assert.equal(invalid.basis, 'reported'); assert.equal(invalid.from, '');
assert.equal(reportLocation(new URL('http://localhost/?report_page=999999')).page, 100000);
assert.equal(reportLocation(new URL('http://localhost/?report_page=-7')).page, 1);
process.stdout.write('Workspace navigation allowlists, preferences and private-facet checks passed.\n');
