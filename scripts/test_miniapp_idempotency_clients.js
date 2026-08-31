#!/usr/bin/env node
'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '..');
let sequence = 0;
const requests = [];

function response() {
  return {
    ok: true,
    status: 200,
    headers: { get: () => '' },
    json: async () => ({ ok: true }),
    text: async () => '',
  };
}

const browser = {
  crypto: { randomUUID: () => `00000000-0000-4000-8000-${String(++sequence).padStart(12, '0')}` },
};
const context = vm.createContext({
  AbortController,
  Date,
  FormData,
  Math,
  Promise,
  URLSearchParams,
  clearTimeout,
  console,
  fetch: async (url, options) => {
    requests.push({ url, options });
    return response();
  },
  navigator: { onLine: true },
  setTimeout,
  window: browser,
});
browser.window = browser;
browser.fetch = context.fetch;
browser.setTimeout = setTimeout;
browser.clearTimeout = clearTimeout;

function load(relativePath) {
  const filename = path.join(root, relativePath);
  vm.runInContext(fs.readFileSync(filename, 'utf8'), context, { filename });
}

load('core/static/miniapp/utils.js');
load('core/static/miniapp/spin_api.js');
load('core/static/miniapp/order_approval_api.js');

async function testSingleFlight() {
  let resolveOperation;
  let calls = 0;
  const operation = () => {
    calls += 1;
    return new Promise(resolve => { resolveOperation = resolve; });
  };
  const first = browser.MiniAppUtils.singleFlight('same-action-12345678', operation);
  const second = browser.MiniAppUtils.singleFlight('same-action-12345678', operation);
  await Promise.resolve();
  assert.equal(calls, 1, 'double click must share one in-flight request');
  assert.equal(first, second, 'double click must receive the same promise');
  resolveOperation('done');
  await Promise.all([first, second]);
}

async function testJsonPath() {
  requests.length = 0;
  const payload = { action: 'review' };
  await browser.SpinMiniAppApi.postJson('/api/spin/review/update/', payload);
  assert.equal(requests.length, 1);
  const request = requests[0].options;
  assert.ok(payload.client_request_id, 'JSON action must retain its request key');
  assert.equal(request.headers['Idempotency-Key'], payload.client_request_id);
  assert.equal(request.headers['X-Request-ID'], payload.client_request_id);
  assert.equal(JSON.parse(request.body).client_request_id, payload.client_request_id);

  await browser.SpinMiniAppApi.postJson('/api/spin/review/update/', payload);
  assert.equal(requests[1].options.headers['Idempotency-Key'], payload.client_request_id,
    'an explicit retry must reuse the original action key');
}

async function testMultipartPath() {
  requests.length = 0;
  const form = new FormData();
  form.set('group_id', '-100-test');
  await browser.OrderApprovalMiniAppApi.postForm('/api/order-approval/webapp/submit/', form);
  const key = form.get('client_request_id');
  assert.ok(key, 'multipart action must retain its request key in FormData');
  assert.equal(requests[0].options.headers['Idempotency-Key'], key);
  assert.equal(requests[0].options.headers['X-Request-ID'], key);
  assert.equal(requests[0].options.body.get('client_request_id'), key);
}

function testXhrPath() {
  const headers = {};
  const xhr = { setRequestHeader: (name, value) => { headers[name] = value; } };
  const key = browser.MiniAppUtils.setXhrIdempotencyHeaders(xhr, 'xhr-upload-12345678');
  assert.equal(key, 'xhr-upload-12345678');
  assert.equal(headers['Idempotency-Key'], key);
  assert.equal(headers['X-Request-ID'], key);
}

(async () => {
  await testSingleFlight();
  await testJsonPath();
  await testMultipartPath();
  testXhrPath();
  process.stdout.write('Mini App idempotency client tests passed.\n');
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
