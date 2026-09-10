'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function loadUtils(fetchImplementation) {
  const context = {
    window: {},
    fetch: fetchImplementation,
    console,
    URLSearchParams,
    FormData,
    AbortController,
    setTimeout,
    clearTimeout,
  };
  vm.runInNewContext(
    fs.readFileSync(path.join(__dirname, '..', 'static', 'miniapp', 'utils.js'), 'utf8'),
    context,
  );
  return context.window.MiniAppUtils;
}

(async () => {
  const networkUtils = loadUtils(async () => { throw new TypeError('Failed to fetch internal host'); });
  await assert.rejects(
    () => networkUtils.fetchJson('/api/test/', { headers: { 'X-Request-ID': 'network-12345678' } }),
    error => {
      assert.equal(error.code, 'client_network_unavailable');
      assert.equal(error.requestId, 'network-12345678');
      assert.equal(error.presentation.surface_hint, 'banner');
      assert.doesNotMatch(error.message, /internal host|failed to fetch/i);
      return true;
    },
  );

  const malformedUtils = loadUtils(async () => ({
    ok: true,
    status: 200,
    headers: { get() { return ''; } },
    async json() { throw new SyntaxError('private response'); },
  }));
  await assert.rejects(
    () => malformedUtils.fetchJson('/api/test/', { headers: { 'X-Request-ID': 'malformed-12345678' } }),
    error => error.code === 'client_invalid_response' && error.requestId === 'malformed-12345678',
  );

  const abort = new Error('cancelled'); abort.name = 'AbortError';
  const abortUtils = loadUtils(async () => { throw abort; });
  await assert.rejects(() => abortUtils.fetchJson('/api/test/'), error => error === abort);

  const retryUtils = loadUtils(async () => {});
  const normalized = retryUtils.normalizeResponsePayload({
    ok: false,
    status: 429,
    headers: { get(name) { return name === 'Retry-After' ? '12' : ''; } },
  }, { ok: false, code: 'retry_later', message: 'Wait.' });
  assert.equal(normalized.details.retry_after, '12');

  const tatSource = fs.readFileSync(path.join(__dirname, '..', 'static', 'miniapp', 'tat_tracker.js'), 'utf8');
  assert.match(tatSource, /if \(tone === 'ok'\) showNotice\(message, tone\)/);
  assert.doesNotMatch(tatSource, /tone === 'ok' \|\| tone === 'error'\) showNotice/);

  const complaintSource = fs.readFileSync(path.join(__dirname, '..', 'static', 'miniapp', 'complaint_cases.js'), 'utf8');
  assert.match(complaintSource, /function presentError\(error, retry\)/);
  assert.match(complaintSource, /pendingWriteId\(writeKey/);

  console.log('Mini App error handling tests passed');
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
