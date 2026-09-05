'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const validation = require('../static/miniapp/tat_case_validation.js');

const boundedProduct = {
  key: 'logbook',
  label: 'Logbook',
  min_amount: '50000.00',
  max_amount: '700000.00',
};
const unboundedProduct = {
  key: 'business',
  label: 'Business',
  min_amount: '5000',
  max_amount: '',
};

assert.equal(validation.amountValidationMessage('', boundedProduct), '');
assert.equal(
  validation.amountValidationMessage('49,999', boundedProduct),
  'Logbook amount must be at least KES 50,000.'
);
assert.equal(validation.amountValidationMessage('50000', boundedProduct), '');
assert.equal(validation.amountValidationMessage('700000', boundedProduct), '');
assert.equal(
  validation.amountValidationMessage('700001', boundedProduct),
  'Logbook amount must be at most KES 700,000.'
);
assert.equal(validation.amountValidationMessage('not-an-amount', boundedProduct), 'Enter a valid amount.');
assert.equal(validation.amountRangeText(boundedProduct), 'Allowed range: KES 50,000–700,000.');
assert.equal(validation.amountRangeText(unboundedProduct), 'Allowed amount: KES 5,000 or more.');

const input = {
  min: '',
  max: '',
  value: '1000',
  message: '',
  reported: false,
  removeAttribute(name) { if (name === 'max') this.max = ''; },
  setCustomValidity(message) { this.message = message; },
  reportValidity() { this.reported = true; },
};
const help = { textContent: '' };
validation.configureAmountInput(input, help, boundedProduct);
assert.equal(input.min, '50000.00');
assert.equal(input.max, '700000.00');
assert.equal(help.textContent, 'Allowed range: KES 50,000–700,000.');

validation.configureAmountInput(input, help, unboundedProduct);
assert.equal(input.min, '5000');
assert.equal(input.max, '');
assert.equal(help.textContent, 'Allowed amount: KES 5,000 or more.');
assert.equal(validation.validateAmountInput(input, unboundedProduct, { report: true }), false);
assert.equal(input.message, 'Business amount must be at least KES 5,000.');
assert.equal(input.reported, true);

input.value = '5000';
input.reported = false;
assert.equal(validation.validateAmountInput(input, unboundedProduct, { report: true }), true);
assert.equal(input.message, '');
assert.equal(input.reported, false);

const template = fs.readFileSync(
  path.join(__dirname, '..', 'templates', 'tat_tracker', 'app.html'),
  'utf8'
);
const tracker = fs.readFileSync(
  path.join(__dirname, '..', 'static', 'miniapp', 'tat_tracker.js'),
  'utf8'
);
assert.match(template, /aria-describedby="newCaseAmountHelp"/);
assert.match(template, /id="newCaseAmountHelp"/);
assert.ok(
  template.indexOf('tat_case_validation.js') < template.indexOf('tat_tracker.js'),
  'case validation helpers load before the TAT application'
);
const submitStart = tracker.indexOf("$('newCaseForm').addEventListener('submit'");
const validationCall = tracker.indexOf('validateNewCaseAmount(true)', submitStart);
const createRequest = tracker.indexOf("api('/api/tat-tracker/create/'", submitStart);
assert.ok(validationCall > submitStart && validationCall < createRequest, 'amount limits are checked before the request');

console.log('TAT case client validation tests passed');
