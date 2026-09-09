'use strict';

const assert = require('node:assert/strict');
const path = require('node:path');

const formatters = require(path.join(__dirname, '..', 'static', 'miniapp', 'tat_formatters.js'));

assert.equal(formatters.formatNairobiDateTime('2026-09-07T06:15:00Z'), '07-09-2026 09:15');
assert.equal(formatters.formatNairobiDateTime('2026-09-07T12:15:00+03:00'), '07-09-2026 12:15');
assert.equal(formatters.formatNairobiDateTime('07-09-26 12:15'), '07-09-2026 12:15');
assert.equal(formatters.formatNairobiDateTime('2026-09-06T22:30:00Z'), '07-09-2026 01:30');
assert.equal(formatters.formatNairobiDateTime(''), '');

assert.equal(formatters.formatNairobiDate('2026-09-07'), '07-09-2026');
assert.equal(formatters.formatNairobiDate('2026-09-06T22:30:00Z'), '07-09-2026');
assert.equal(formatters.nairobiDateInputValue('2026-09-06T22:30:00Z'), '2026-09-07');
assert.equal(formatters.nairobiDateTimeInputValue('2026-09-06T22:30:00Z'), '2026-09-07T01:30');
assert.equal(formatters.nairobiDateTimeInputToIso('2026-09-07T01:30'), '2026-09-07T01:30:00+03:00');
assert.equal(formatters.nairobiDateTimeInputToIso('not-a-date'), '');
assert.equal(formatters.formatLocalizedNumber(12345.6, { maximumFractionDigits: 1 }), '12,345.6');
assert.equal(formatters.formatLocalizedPercent(87.25, 1), '87.3%');

assert.equal(formatters.formatAdaptiveDurationMinutes(null), '\u2014');
assert.equal(formatters.formatAdaptiveDurationMinutes(0), '0s');
assert.equal(formatters.formatAdaptiveDurationMinutes(0.75), '45s');
assert.equal(formatters.formatAdaptiveDurationMinutes(12), '12m');
assert.equal(formatters.formatAdaptiveDurationMinutes(135), '2h 15m');
assert.equal(formatters.formatAdaptiveDurationMinutes(1635), '1d 3h 15m');
assert.equal(formatters.formatAdaptiveDurationMinutes(-75), '\u22121h 15m');
assert.equal(formatters.formatAdaptiveDurationMinutes('not-a-number'), '\u2014');

console.log('TAT formatter tests passed');
