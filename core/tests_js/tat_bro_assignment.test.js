'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const assignment = require('../static/miniapp/tat_bro_assignment.js');

const users = assignment.normalizeUsers([
  {
    id: 17,
    name: 'Alex Doe',
    username: 'alex-django',
    telegram_username: '@alex_field',
  },
  {
    id: 22,
    name: 'Alex Doe',
    username: 'alex-office',
    telegram_username: '',
  },
  {
    id: 31,
    name: 'Mary BRO',
    username: 'mary-bro',
    telegram_username: 'mary_bro',
  },
]);

assert.deepEqual(
  users.map((user) => user.option_value),
  ['17', '22', '31'],
  'canonical Django user IDs are the submitted option values'
);
assert.deepEqual(
  assignment.optionRows(users).map((row) => row.label),
  ['Alex Doe (@alex_field)', 'Alex Doe (alex-office)', 'Mary BRO'],
  'duplicate display names expose a privacy-safe staff identifier'
);
assert.equal(assignment.defaultValue(users, 17), '17', 'a BRO creator defaults to self');
assert.equal(assignment.defaultValue(users, 999), '', 'a non-BRO creator has no implicit default');
assert.deepEqual(
  assignment.selectionPayload(users, '22'),
  { bro_user_id: '22', bro_name: 'Alex Doe' },
  'submissions carry both canonical identity and the display snapshot'
);

const legacyUsers = assignment.normalizeUsers([], ['Cached BRO']);
assert.deepEqual(
  assignment.selectionPayload(legacyUsers, 'legacy:0'),
  { bro_user_id: '', bro_name: 'Cached BRO' },
  'cached bootstrap payloads retain the legacy name-only contract'
);

const select = {
  innerHTML: 'old options',
  value: '',
  options: [],
  ownerDocument: { createElement: () => ({ value: '', textContent: '' }) },
  appendChild(option) { this.options.push(option); },
};
assignment.populateSelect(select, users, 31);
assert.equal(select.options.length, 4, 'the complete roster is rendered after the placeholder');
assert.equal(select.value, '31', 'the creator default is applied after rendering all options');

const template = fs.readFileSync(
  path.join(__dirname, '..', 'templates', 'tat_tracker', 'app.html'),
  'utf8'
);
const tracker = fs.readFileSync(
  path.join(__dirname, '..', 'static', 'miniapp', 'tat_tracker.js'),
  'utf8'
);
assert.match(template, /select name="bro_user_id" required/);
assert.ok(
  template.indexOf('tat_bro_assignment.js') < template.indexOf('tat_tracker.js'),
  'assignment helpers load before the TAT application'
);
assert.match(tracker, /payload\.bro_user_id = selectedBro\.bro_user_id/);
assert.match(tracker, /payload\.bro_name = selectedBro\.bro_name/);
assert.match(
  tracker,
  /broInput\.value = broAssignment\.defaultValue\(state\.broUsers, state\.defaultBroUserId\)/,
  'a successful submission resets the form to the creator default'
);

console.log('TAT BRO assignment client tests passed');
