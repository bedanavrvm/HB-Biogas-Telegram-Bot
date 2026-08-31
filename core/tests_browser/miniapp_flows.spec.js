'use strict';

const path = require('node:path');
const { test, expect } = require('playwright/test');

const root = path.resolve(__dirname, '..', '..');
const asset = (name) => path.join(root, 'core', 'static', 'miniapp', name);

async function loadUtilities(page) {
  await page.addScriptTag({ path: asset('utils.js') });
}

test('Mini App bootstrap initializes Telegram once', async ({ page }) => {
  await page.setContent('<main id="app">Ready</main>');
  await page.evaluate(() => {
    window.__telegramCalls = { ready: 0, expand: 0, swipes: 0 };
    window.Telegram = { WebApp: {
      initData: 'synthetic-signed-init-data',
      ready() { window.__telegramCalls.ready += 1; },
      expand() { window.__telegramCalls.expand += 1; },
      disableVerticalSwipes() { window.__telegramCalls.swipes += 1; },
      disableClosingConfirmation() {},
    } };
  });
  await loadUtilities(page);
  await page.addScriptTag({ path: asset('telegram.js') });
  const result = await page.evaluate(() => {
    window.MiniAppTelegram.init();
    window.MiniAppTelegram.init();
    return window.__telegramCalls;
  });
  expect(result).toEqual({ ready: 1, expand: 1, swipes: 1 });
});

test('authentication failure renders reviewed Portal guidance', async ({ page }) => {
  await page.route('http://miniapp.test/**', route => route.fulfill({
    contentType: 'text/html',
    body: `<!doctype html><style>
      #sidebar { position: fixed; z-index: 2; width: 240px; height: 100%; transform: translateX(-100%); }
      #sidebar.open { transform: translateX(0); }
      #sidebar-backdrop { display: none; position: fixed; inset: 0; z-index: 1; }
      #sidebar-backdrop.open { display: block; }
    </style><body>
      <nav id="sidebar"><a class="shell-nav-link" data-screen="dashboard" href="/portal/s/dashboard/">Dashboard</a></nav>
      <button id="shell-menu-button" aria-expanded="false">Menu</button><div id="sidebar-backdrop"></div>
      <main id="content"><section id="portal-screen" data-top-level="true"></section></main>
    </body>`,
  }));
  await page.addInitScript(() => {
    window.Telegram = { WebApp: {
      ready() {}, expand() {}, disableVerticalSwipes() {}, disableClosingConfirmation() {},
      themeParams: {}, onEvent() {},
      BackButton: { onClick() {}, offClick() {}, show() {}, hide() {} },
      MainButton: { onClick() {}, offClick() {}, show() {}, hide() {}, setText() {} },
    } };
    window.PortalAppShell = { activate() {} };
  });
  await page.goto('http://miniapp.test/portal/s/dashboard/');
  await loadUtilities(page);
  await page.addScriptTag({ path: asset('miniapp-nav.js') });
  await page.evaluate(() => {
    const target = document.getElementById('portal-screen');
    document.body.dispatchEvent(new CustomEvent('htmx:responseError', {
      bubbles: true,
      detail: { target, xhr: { status: 403 } },
    }));
  });
  await expect(page.getByRole('alert')).toContainText(
    'Your Telegram account is not authorized for this Portal screen.',
  );
});

test('double-submit protection shares one browser request', async ({ page }) => {
  await page.setContent('<button id="submit">Submit</button>');
  await loadUtilities(page);
  const result = await page.evaluate(async () => {
    let calls = 0;
    let release;
    const operation = () => {
      calls += 1;
      return new Promise(resolve => { release = resolve; });
    };
    const first = window.MiniAppUtils.singleFlight('same-action-12345678', operation);
    const second = window.MiniAppUtils.singleFlight('same-action-12345678', operation);
    await Promise.resolve();
    const samePromise = first === second;
    release({ ok: true });
    await Promise.all([first, second]);
    return { calls, samePromise };
  });
  expect(result).toEqual({ calls: 1, samePromise: true });
});

test('mobile navigation closes its drawer and Telegram Back stays inside Portal', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.route('http://miniapp.test/**', route => route.fulfill({
    contentType: 'text/html',
    body: `<!doctype html><style>
      #sidebar { position: fixed; z-index: 2; width: 240px; height: 100%; transform: translateX(-100%); }
      #sidebar.open { transform: translateX(0); }
      #sidebar-backdrop { display: none; position: fixed; inset: 0; z-index: 1; }
      #sidebar-backdrop.open { display: block; }
    </style><body>
      <button id="shell-menu-button" aria-expanded="false">Menu</button>
      <aside id="sidebar"><a class="shell-nav-link" data-screen="all" href="http://miniapp.test/portal/s/all/">All cases</a></aside>
      <div id="sidebar-backdrop"></div><main id="content"><section id="portal-screen"></section></main>
    </body>`,
  }));
  await page.addInitScript(() => {
    window.__htmxCalls = [];
    window.Telegram = { WebApp: {
      ready() {}, expand() {}, disableVerticalSwipes() {}, disableClosingConfirmation() {},
      themeParams: {}, onEvent() {},
      BackButton: {
        onClick(callback) { window.__backHandler = callback; }, offClick() {}, show() {}, hide() {},
      },
      MainButton: { onClick() {}, offClick() {}, show() {}, hide() {}, setText() {} },
    } };
    window.PortalAppShell = { activate() {} };
    window.htmx = { ajax(method, url, options) { window.__htmxCalls.push({ method, url, options }); } };
  });
  await page.goto('http://miniapp.test/portal/cases/synthetic-case/');
  await loadUtilities(page);
  await page.addScriptTag({ path: asset('miniapp-nav.js') });
  await page.locator('#shell-menu-button').click();
  await expect(page.locator('#sidebar')).toHaveClass(/open/);
  await page.mouse.click(370, 420);
  await expect(page.locator('#sidebar')).not.toHaveClass(/open/);
  await page.waitForFunction(() => typeof window.__backHandler === 'function');
  const calls = await page.evaluate(() => {
    window.__backHandler();
    return window.__htmxCalls;
  });
  expect(calls).toHaveLength(1);
  expect(calls[0].url).toBe('http://miniapp.test/portal/s/all/');
  expect(calls[0].options.pushURL).toBe(true);
});

test('multipart upload failure can retry with the same request key', async ({ page }) => {
  await page.setContent('<main>Upload</main>');
  await page.evaluate(() => {
    window.__requests = [];
    window.__attempt = 0;
    window.fetch = async (url, options) => {
      window.__requests.push({
        url,
        requestId: options.headers['X-Request-ID'],
        idempotencyKey: options.headers['Idempotency-Key'],
      });
      window.__attempt += 1;
      if (window.__attempt === 1) throw new TypeError('synthetic network failure');
      return new Response(JSON.stringify({ ok: true }), {
        status: 200, headers: { 'Content-Type': 'application/json' },
      });
    };
  });
  await loadUtilities(page);
  await page.addScriptTag({ path: asset('order_approval_api.js') });
  const result = await page.evaluate(async () => {
    const form = new FormData();
    form.set('group_id', '-100-synthetic');
    try { await window.OrderApprovalMiniAppApi.postForm('/api/order-approval/webapp/submit/', form); } catch (_) {}
    const response = await window.OrderApprovalMiniAppApi.postForm('/api/order-approval/webapp/submit/', form);
    return { response, key: form.get('client_request_id'), requests: window.__requests };
  });
  expect(result.response.ok).toBe(true);
  expect(result.requests).toHaveLength(2);
  expect(result.requests[0].requestId).toBe(result.key);
  expect(result.requests[1].requestId).toBe(result.key);
  expect(result.requests[1].idempotencyKey).toBe(result.key);
});

function signingHtml() {
  return `<!doctype html><body>
    <main class="sign-shell" data-session-url="/api/origination/sign/api/session/">
      <div id="sign-status"></div><section id="sign-content" hidden>
        <strong id="sign-reference"></strong><strong id="sign-role"></strong><strong id="sign-phone"></strong>
        <div id="signing-mode-banner"></div><span id="signing-mode-label"></span><span id="signing-mode-detail"></span>
        <div id="shared-phone-warning" hidden></div><div id="document-list"></div>
        <span id="packet-consent-text"></span><div id="preview-loading"></div><img id="packet-page" hidden>
        <span id="page-label"></span><button id="page-prev"></button><button id="page-next"></button>
        <canvas id="signature-pad" width="800" height="260"></canvas><button id="signature-clear"></button>
        <button id="mode-drawn" class="active"></button><button id="mode-typed"></button>
        <div id="draw-panel"></div><label id="type-panel" hidden><input id="typed-name"></label>
        <label><input id="packet-consent" type="checkbox"></label>
        <label id="assisted-confirmation" hidden><input id="assisted-consent" type="checkbox"></label>
        <button id="save-signature">Save signature</button><button id="send-otp" disabled>Send code</button>
        <div id="otp-panel" hidden><input id="otp-code"><span id="otp-detail"></span>
          <button id="verify-otp">Verify</button></div>
      </section>
    </main>
  </body>`;
}

test('Origination signing completes its happy path with test-mode services', async ({ page }) => {
  let session = {
    test_mode: true,
    reference: 'SYNTHETIC-LAF-001', signer_role: 'borrower', phone_masked: '+254 *** 001',
    shared_phone_override: false, access_mode: 'remote', documents: [{ key: 'laf', name: 'Loan form', page_count: 1 }],
    reviewed_pages: [], consented: false, status: 'pending', otp: {}, packet_version: 'test-v1',
  };
  await page.route('http://miniapp.test/**', async route => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith('/packet/')) {
      return route.fulfill({
        status: 200, body: 'synthetic-image', contentType: 'image/png',
        headers: { 'X-Preview-Page-Count': '1', 'X-Signing-Packet-Version': 'test-v1' },
      });
    }
    if (url.pathname.endsWith('/consent/')) session = { ...session, consented: true, reviewed_pages: [1] };
    if (url.pathname.endsWith('/otp/')) session = { ...session, otp: { expires_at: '2026-08-31T22:00:00Z' } };
    if (url.pathname.endsWith('/verify/')) {
      session = { ...session, status: 'verified', completion_text: 'Synthetic signing complete.' };
    }
    return route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ ok: true, session }),
    });
  });
  await page.route('http://miniapp.test/sign', route => route.fulfill({
    status: 200, contentType: 'text/html', body: signingHtml(),
  }));
  await page.goto('http://miniapp.test/sign#synthetic-test-token');
  await loadUtilities(page);
  await page.addScriptTag({ path: asset('origination_signing.js') });
  await expect(page.locator('#sign-content')).toBeVisible();
  await expect(page.locator('#page-label')).toHaveText('1 / 1');
  await page.locator('#mode-typed').click();
  await page.locator('#typed-name').fill('Synthetic Borrower');
  await page.locator('#packet-consent').check();
  await page.locator('#save-signature').click();
  await expect(page.locator('#sign-status')).toContainText('signature is ready');
  await page.locator('#send-otp').click();
  await expect(page.locator('#otp-panel')).toBeVisible();
  await page.locator('#otp-code').fill('123456');
  await page.locator('#verify-otp').click();
  await expect(page.locator('#sign-status')).toHaveText('Synthetic signing complete.');
});
