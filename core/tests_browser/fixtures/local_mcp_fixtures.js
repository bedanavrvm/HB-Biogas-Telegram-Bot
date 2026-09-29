/*
 * Synthetic-only browser boundary shared by MCP sessions and its contract test.
 * This is intentionally a tiny Portal shell fixture, not an auth bypass: every
 * API write is rejected, external network requests are blocked, and all data is
 * fictional. The Playwright MCP config separately allows localhost origins only.
 */
(function installLocalMcpFixtures(root) {
  'use strict';

  const fixtureData = { initData: 'synthetic-signed-init-data' };
  if (typeof module !== 'undefined' && module.exports) module.exports = fixtureData;
  if (!root || !root.window) return;
  const window = root.window;

  const allowedHosts = new Set(['127.0.0.1', 'localhost']);
  // MCP may evaluate context init scripts in its initial about:blank tab.
  if (window.location.protocol === 'about:') return;
  if (!allowedHosts.has(window.location.hostname) || window.location.port !== '8000') {
    throw new Error('Local MCP fixtures only run on http://127.0.0.1:8000 or http://localhost:8000.');
  }
  if (window.__JBL_MCP_FIXTURES__) return;
  Object.defineProperty(window, '__JBL_MCP_FIXTURES__', { value: true });

  const initData = fixtureData.initData;
  const eventHandlers = new Map();
  const telegram = {
    initData,
    platform: 'tdesktop',
    colorScheme: 'light',
    themeParams: {},
    ready() {},
    expand() {},
    disableVerticalSwipes() {},
    onEvent(name, callback) { eventHandlers.set(name, callback); },
    offEvent(name) { eventHandlers.delete(name); },
    BackButton: { show() {}, hide() {}, onClick(callback) { eventHandlers.set('back', callback); }, offClick() {} },
    MainButton: { show() {}, hide() {}, setText() {}, onClick(callback) { eventHandlers.set('main', callback); }, offClick() {} },
    HapticFeedback: { impactOccurred() {}, notificationOccurred() {}, selectionChanged() {} },
  };
  window.Telegram = { WebApp: telegram };

  const now = new Date().toISOString();
  const capabilities = [
    'portal.dashboard.view', 'portal.jbl_visit.view', 'portal.jbl_visit.log',
    'portal.credit.view', 'portal.final_review.view', 'portal.requisition.view',
    'portal.invoices.view', 'portal.payments.view', 'portal.hb_actions.view',
    'portal.farmup.view', 'portal.sysup.view', 'portal.document_history.view',
  ];
  const responses = new Map([
    ['/api/portal/meta/', {
      ok: true,
      actor: { name: 'Synthetic Portal Tester', roles: ['IT'] },
      capabilities,
      access_policy_version: 'local-mcp-fixture-v1',
      branches: ['Synthetic Branch'],
      counties: ['Synthetic County'],
      location_catalog: { branches: [], counties: [], sub_counties: [] },
      jbl_visit_statuses: [], credit_decisions: [], imab_created_options: [],
      final_decisions: [], approval_reasons: [], approval_delegation_gates: [],
      jbl_visit_draft_fields: [], voice_input: { enabled: false, fields: [] },
      business_date: now.slice(0, 10),
    }],
    ['/api/portal/dashboard/', {
      ok: true,
      calculated_at: now,
      as_of: now,
      scope: { label: 'Local synthetic preview' },
      counts: {},
      home: {
        actions: [{
          id: 'synthetic-case', label: 'Example test case',
          detail: 'Synthetic data only · no customer record',
          context: 'Local preview', workflow: 'Test fixture',
          url: '/portal/s/jbl/?focus=synthetic-case', severity: 'routine',
        }],
        system_health: [], queues: [], shortcuts: [],
      },
    }],
    ['/api/portal/publication/pump/', { ok: true, changed: false, poll_after_seconds: 60 }],
  ]);

  const originalFetch = window.fetch.bind(window);
  window.fetch = async function syntheticOnlyFetch(input, init) {
    const requestUrl = typeof input === 'string' || input instanceof URL
      ? new URL(String(input), window.location.href)
      : new URL(input.url, window.location.href);
    if (requestUrl.origin !== window.location.origin) {
      throw new Error('The local MCP fixture blocked an external network request.');
    }
    if (!requestUrl.pathname.startsWith('/api/')) return originalFetch(input, init);

    const method = String(init?.method || (input instanceof Request ? input.method : 'GET')).toUpperCase();
    if (method !== 'GET' && requestUrl.pathname !== '/api/portal/publication/pump/') {
      return new Response(JSON.stringify({
        ok: false, error: 'Writes are disabled in the local MCP fixture.',
        code: 'LOCAL_SYNTHETIC_FIXTURE_READ_ONLY',
      }), { status: 403, headers: { 'Content-Type': 'application/json' } });
    }

    const payload = responses.get(requestUrl.pathname) || {
      ok: true, data: [], results: [], rows: [], items: [], records: [],
      count: 0, page: 1, page_size: 25, next: null, previous: null,
    };
    return new Response(JSON.stringify(payload), {
      status: 200,
      headers: { 'Content-Type': 'application/json', 'X-Request-ID': 'synthetic-mcp-response' },
    });
  };

  const xhrOpen = XMLHttpRequest.prototype.open;
  const xhrSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function localFixtureOpen(method, url, ...args) {
    this.__localFixtureRequest = {
      method: String(method || 'GET').toUpperCase(),
      url: new URL(String(url), window.location.href),
    };
    if (this.__localFixtureRequest.url.origin !== window.location.origin) {
      throw new Error('The local MCP fixture blocked an external network request.');
    }
    return xhrOpen.call(this, method, url, ...args);
  };
  XMLHttpRequest.prototype.send = function localFixtureSend(...args) {
    const request = this.__localFixtureRequest;
    if (request && request.url.pathname.startsWith('/api/')) {
      throw new Error(request.method === 'GET'
        ? 'The local MCP fixture requires API reads to use its synthetic fetch responses.'
        : 'Writes are disabled in the local MCP fixture.');
    }
    if (request && request.method !== 'GET') {
      throw new Error('Writes are disabled in the local MCP fixture.');
    }
    return xhrSend.apply(this, args);
  };

  const originalOpen = window.open.bind(window);
  window.open = function localOnlyOpen(url, ...args) {
    const target = new URL(String(url || ''), window.location.href);
    if (target.origin !== window.location.origin) return null;
    return originalOpen(target.href, ...args);
  };
  window.navigator.sendBeacon = () => false;
  document.addEventListener('submit', event => {
    event.preventDefault();
    event.stopImmediatePropagation();
  }, true);
  document.addEventListener('click', event => {
    const anchor = event.target?.closest?.('a[href]');
    if (!anchor) return;
    const target = new URL(anchor.href, window.location.href);
    if (target.origin !== window.location.origin) {
      event.preventDefault();
      event.stopImmediatePropagation();
    }
  }, true);
})(typeof globalThis === 'undefined' ? this : globalThis);
