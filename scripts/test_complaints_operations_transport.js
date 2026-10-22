'use strict';
// Started only by the opted-in isolated Django test server. No live fixtures.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');

async function main() {
  let text = ''; for await (const chunk of process.stdin) text += chunk;
  const input = JSON.parse(text), origin = new URL(input.origin);
  assert.ok(['127.0.0.1', 'localhost'].includes(origin.hostname));
  const output = path.resolve('test-results/complaints-browser-operations', input.build);
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1366, height: 900 }, colorScheme: 'light', acceptDownloads: true });
  const page = await context.newPage(); page.setDefaultTimeout(20000);
  page.on('dialog', dialog => dialog.accept());
  const errors = [], requests = [], layouts = []; let captures = 0;
  await context.route('**/*', route => {
    const url = new URL(route.request().url());
    if (url.origin === origin.origin) return route.continue();
    errors.push('External browser request'); return route.abort();
  });
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => requests.push({ url: request.url(), resource: request.resourceType() }));
  const heading = name => page.getByRole('heading', { name, exact: true }).waitFor();
  async function capture(name) {
    await page.evaluate(() => new Promise(requestAnimationFrame));
    const metrics = await page.evaluate(() => ({ width: innerWidth, page: document.documentElement.scrollWidth,
      main: document.querySelector('main')?.getBoundingClientRect().width, theme: document.documentElement.dataset.colorMode }));
    assert.ok(metrics.page <= metrics.width, name + ': horizontal clipping'); layouts.push({ name, ...metrics });
    await page.screenshot({ path: path.join(output, name + '.png'), fullPage: true }); captures++;
  }
  async function select(label, option) {
    const box = page.getByLabel(label, { exact: true }); await box.fill(option); await box.press('Enter');
  }
  try {
    await page.goto(origin.origin + '/staff/app/complaints/');
    await heading('Sign in'); await page.getByLabel(/^Staff username/).fill(input.username);
    await page.getByLabel(/^Password/).fill(input.password);
    await page.getByRole('button', { name: 'Sign in', exact: true }).click();
    await heading('Check your authenticator');
    await page.getByRole('button', { name: 'Use a recovery code', exact: true }).click();
    await page.getByLabel(/^Recovery code/).fill(input.code);
    await page.getByRole('button', { name: 'Verify', exact: true }).click();
    await heading('7 cases');
    const documentsBefore = requests.filter(row => row.resource === 'document').length;
    await page.getByRole('button', { name: 'Synthetic Customer 00', exact: true }).click();
    await heading('Synthetic Customer 00');
    assert.match(page.url(), /staff\/app\/complaints\/cases\/[a-f\d-]+\//);
    assert.equal(await page.locator('a[href^="tel:"]').count(), 1);
    await select('Update complaint', 'Add resolution comment');
    await page.getByLabel(/^Resolution comment/).fill('Synthetic browser follow-up.');
    await page.getByRole('button', { name: 'Add resolution comment', exact: true }).click();
    await page.getByText('Synthetic browser follow-up.', { exact: true }).waitFor();
    await capture('desktop-comment-saved');
    for (const theme of ['light', 'dark']) {
      await page.emulateMedia({ colorScheme: theme });
      await page.waitForFunction(value => document.documentElement.dataset.colorMode === value, theme);
      for (const width of [320, 360, 390, 768, 1280, 1366, 1440, 1920]) {
        await page.setViewportSize({ width, height: width < 768 ? 844 : 900 }); await capture(`queue-${theme}-${width}`);
      }
    }
    await page.setViewportSize({ width: 1366, height: 900 }); await page.emulateMedia({ colorScheme: 'light' });
    await page.getByLabel('Search name, ID, phone or branch').fill('999999999999');
    await page.getByRole('button', { name: 'Search', exact: true }).click(); await heading('7 cases');
    assert.ok(!page.url().includes('999999999999'));
    assert.ok(!requests.some(row => new URL(row.url).search.includes('999999999999')));
    await page.getByRole('button', { name: 'New complaint', exact: true }).click(); await heading('New complaint');
    await page.getByLabel(/^Customer name/).fill('Synthetic retained draft');
    await page.getByRole('button', { name: 'Submit complaint', exact: true }).click();
    assert.equal(await page.getByLabel(/^Customer name/).inputValue(), 'Synthetic retained draft');
    await capture('create-field-errors');
    await page.getByRole('button', { name: 'Save draft', exact: true }).click();
    await page.getByText('Draft saved.', { exact: true }).waitFor();
    await page.getByRole('button', { name: 'Cases', exact: true }).click();
    await page.getByRole('button', { name: 'New complaint', exact: true }).click();
    await page.getByRole('button', { name: 'Restore', exact: true }).click();
    assert.equal(await page.getByLabel(/^Customer name/).inputValue(), 'Synthetic retained draft');
    await page.getByRole('button', { name: 'Cases', exact: true }).click();
    await page.getByRole('button', { name: 'Reports', exact: true }).click();
    await page.getByText('Reported over time', { exact: true }).waitFor(); await capture('reports-desktop');
    const drill = page.locator('svg[aria-label^="Complaint types."]').locator('[role="button"]').first();
    await drill.press('Enter');
    await page.waitForFunction(() => document.activeElement?.getAttribute('aria-label') === 'Filtered report complaints');
    for (const theme of ['light', 'dark']) {
      await page.emulateMedia({ colorScheme: theme });
      await page.waitForFunction(value => document.documentElement.dataset.colorMode === value, theme);
      for (const width of [320, 360, 390, 768, 1280, 1366, 1440, 1920]) {
        await page.setViewportSize({ width, height: width < 768 ? 844 : 900 }); await capture(`reports-${theme}-${width}`);
      }
    }
    await page.setViewportSize({ width: 1366, height: 900 });
    await page.getByRole('button', { name: 'Download Excel', exact: true }).click();
    const downloading = page.waitForEvent('download');
    await page.getByRole('button', { name: 'Download filtered results', exact: true }).click();
    const file = await downloading; assert.ok(file.suggestedFilename().endsWith('.xlsx'));
    assert.ok(file.suggestedFilename().length > 6);
    assert.equal(requests.filter(row => row.resource === 'document').length, documentsBefore);
    await page.goBack(); await heading('7 cases');
    await page.goForward(); await page.getByText('Reported over time', { exact: true }).waitFor();
    await page.reload(); await page.getByText('Reported over time', { exact: true }).waitFor();
    assert.deepEqual(await page.evaluate(() => ({ local: localStorage.length, session: sessionStorage.length })), { local: 0, session: 0 });
    assert.deepEqual(errors, []);
    fs.writeFileSync(path.join(output, 'layout.json'), JSON.stringify(layouts, null, 2));
    process.stdout.write(JSON.stringify({ passed: true, captures }));
  } finally { await browser.close(); }
}
main().catch(error => { console.error(error.stack); process.exitCode = 1; });
