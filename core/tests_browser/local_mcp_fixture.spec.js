'use strict';

const path = require('node:path');
const { test, expect } = require('playwright/test');

const fixturePath = path.join(__dirname, 'fixtures', 'local_mcp_fixtures.js');
const { initData } = require(fixturePath);

test('shared local MCP fixture supplies synthetic Portal data and blocks writes and external requests', async ({ page }) => {
  await page.route('http://127.0.0.1:8000/**', route => {
    if (new URL(route.request().url()).pathname !== '/') return route.continue();
    return route.fulfill({ contentType: 'text/html', body: '<!doctype html><html><body><main>Local fixture contract</main></body></html>' });
  });
  await page.addInitScript({ path: fixturePath });
  await page.goto('http://127.0.0.1:8000/');

  const identity = await page.evaluate(() => ({
    initData: window.Telegram.WebApp.initData,
    platform: window.Telegram.WebApp.platform,
    installed: window.__JBL_MCP_FIXTURES__,
  }));
  expect(identity).toEqual({ initData, platform: 'tdesktop', installed: true });

  const home = await page.evaluate(async () => (await fetch('/api/portal/dashboard/')).json());
  expect(home.home.actions[0]).toMatchObject({ id: 'synthetic-case', label: 'Example test case' });

  const write = await page.evaluate(async () => {
    const response = await fetch('/api/portal/jbl-visit/', { method: 'POST', body: '{}' });
    return { status: response.status, body: await response.json() };
  });
  expect(write).toMatchObject({ status: 403, body: { code: 'LOCAL_SYNTHETIC_FIXTURE_READ_ONLY' } });

  const external = await page.evaluate(async () => {
    try { await fetch('https://www.googleapis.com/'); return 'unexpectedly allowed'; }
    catch (error) { return error.message; }
  });
  expect(external).toContain('blocked an external network request');

  const xhrWrite = await page.evaluate(() => {
    try {
      const request = new XMLHttpRequest();
      request.open('POST', '/api/portal/jbl-visit/');
      request.send('{}');
      return 'unexpectedly allowed';
    } catch (error) {
      return error.message;
    }
  });
  expect(xhrWrite).toContain('Writes are disabled');
});
