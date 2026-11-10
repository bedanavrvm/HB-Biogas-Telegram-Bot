/* Synthetic cases in the actual signed Portal; no external requests. */
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { chromium } = require('playwright');

(async () => {
  let input = '';
  for await (const chunk of process.stdin) input += chunk;
  const config = JSON.parse(input);
  assert.equal(new URL(config.origin).hostname, 'localhost');
  fs.mkdirSync(config.artifacts, { recursive: true });
  const browser = await chromium.launch();
  const observations = [];
  try {
    for (const { theme, transport } of [
      { theme: 'light', transport: 'fragment' }, { theme: 'dark', transport: 'fragment' },
      { theme: 'light', transport: 'json-fallback' }, { theme: 'dark', transport: 'json-fallback' },
    ]) {
      const context = await browser.newContext({ viewport: { width: 390, height: 844 }, colorScheme: theme });
      const page = await context.newPage();
      const errors = [];
      page.setDefaultTimeout(20000);
      page.on('pageerror', error => errors.push(error.message));
      await page.route('**/*', route => {
        const url = new URL(route.request().url());
        if (url.origin !== config.origin) return route.abort();
        if (transport === 'json-fallback' && url.pathname.includes('/queues/all/fragment/')) {
          return route.fulfill({ status: 503, body: 'Synthetic fragment outage' });
        }
        return route.continue();
      });
      await page.setExtraHTTPHeaders({ 'X-Telegram-Init-Data': config.initData });
      await page.addInitScript(({ initData, theme }) => {
        const themeParams = theme === 'dark' ? {
          bg_color: '#17171e', secondary_bg_color: '#20202c', text_color: '#ffffff', hint_color: '#a8a8b3',
        } : {
          bg_color: '#f4f7f6', secondary_bg_color: '#ffffff', text_color: '#14201d', hint_color: '#66736f',
        };
        // Telegram's native SDK normally supplies these host-owned CSS values.
        document.addEventListener('DOMContentLoaded', () => {
          for (const [key, value] of Object.entries(themeParams)) {
            document.documentElement.style.setProperty('--tg-theme-' + key.replaceAll('_', '-'), value);
          }
        });
        window.Telegram = { WebApp: {
          initData, colorScheme: theme, themeParams, ready() {}, expand() {}, onEvent() {}, offEvent() {},
          BackButton: { onClick() {}, offClick() {}, show() {}, hide() {} },
          MainButton: { hide() {}, offClick() {}, onClick() {} },
        } };
      }, { initData: config.initData, theme });
      await page.goto(config.origin + '/portal/s/all/');
      assert.equal(await page.evaluate(() => document.documentElement.dataset.miniappColorScheme), theme);
      assert.equal(await page.locator('#content').evaluate(node => getComputedStyle(node).backgroundColor),
        theme === 'dark' ? 'rgb(23, 23, 30)' : 'rgb(244, 247, 246)');
      for (const example of config.cases) {
        const card = page.locator(`#all-list [data-farmer-id="${example.id}"]`);
        await card.waitFor();
        if (example.name === 'HISTORICAL REJECTION') {
          assert.match(await card.innerText(), /Rejected/);
          assert.equal(await card.locator('.badge-grey').filter({ hasText: /^Legacy$/ }).count(), 1);
          assert.equal(await card.locator('.badge-green').filter({ hasText: /^Rejected$/ }).count(), 0);
        }
      }
      const badge = await page.evaluate(() => window.PortalMiniAppHelpers.creditBadge({
        credit_decision: 'Rejected', credit_decision_label: 'Legacy',
      }));
      assert.equal(badge, '<span class="badge badge-grey">Legacy</span>');
      await page.screenshot({ path: path.join(config.artifacts, theme + '-' + transport + '-queue.png'), animations: 'disabled' });
      const example = config.cases[0];
      await page.locator(`#all-list [data-farmer-id="${example.id}"]`).click();
      const history = page.locator('#case-history-content');
      const credit = history.locator('[data-case-section="credit"]');
      await credit.waitFor();
      await credit.locator('summary').click();
      await credit.getByText('Legacy', { exact: true }).waitFor();
      await credit.scrollIntoViewIfNeeded();
      assert.match(await history.innerText(), /Rejected/);
      await page.screenshot({ path: path.join(config.artifacts, theme + '-' + transport + '-credit-detail.png'), animations: 'disabled' });
      for (const item of config.cases) {
        const response = await page.request.get(config.origin + '/api/portal/farmers/' + item.id + '/', {
          headers: { 'X-Telegram-Init-Data': config.initData },
        });
        assert.equal(response.status(), 200);
        const data = await response.json();
        assert.equal(data.farmer.credit_decision_label, item.label);
        assert.equal(data.farmer.credit_decision, item.decision);
      }
      assert.deepEqual(errors, []);
      observations.push({ theme, transport, viewport: '390x844', legacyCredit: 'Legacy', pipeline: 'Rejected', errors });
      await context.close();
    }
    fs.writeFileSync(path.join(config.artifacts, 'observations.json'), JSON.stringify(observations, null, 2) + '\n');
    console.log('Actual Portal legacy credit labels verified in light and dark mobile shells.');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
