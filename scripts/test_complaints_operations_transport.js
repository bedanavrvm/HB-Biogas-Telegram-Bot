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
  async function capture(name, keepScroll = false) {
    if (!keepScroll) await page.getByRole('main').evaluate(element => element.scrollTo(0, 0));
    await page.evaluate(() => new Promise(requestAnimationFrame));
    // Capture the settled control colours, not the middle of a theme transition.
    await page.evaluate(async () => { await Promise.all(document.getAnimations().filter(animation => animation instanceof CSSTransition).map(animation => animation.finished.catch(() => {}))); });
    const metrics = await page.evaluate(() => {
      const main = document.querySelector('[role="main"]');
      return { width: innerWidth, page: document.documentElement.scrollWidth,
        main: main?.getBoundingClientRect().width, mainClient: main?.clientWidth,
        mainScroll: main?.scrollWidth, theme: document.documentElement.dataset.colorMode };
    });
    assert.ok(metrics.page <= metrics.width, name + ': horizontal clipping'); layouts.push({ name, ...metrics });
    assert.ok(metrics.mainScroll <= metrics.mainClient + 1, name + ': workspace clipping');
    await page.screenshot({ path: path.join(output, name + '.png'), fullPage: true }); captures++;
  }
  async function select(label, option) {
    const box = page.getByLabel(label, { exact: true }); await box.fill(option);
    const escaped = option.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    await page.getByRole('option', { name: new RegExp('^' + escaped + '(?:$| - )') }).click();
  }
  async function preferenceChecks() {
    await page.setViewportSize({ width: 1366, height: 900 }); await page.emulateMedia({ colorScheme: 'light' });
    await page.getByRole('button', { name: 'Settings', exact: true }).click();
    await select('Default queue', 'Resolved'); await select('Default branch', 'Synthetic Other Branch');
    const saving = page.waitForResponse(response => response.url().endsWith('/preferences/') && response.request().method() === 'POST');
    await page.getByRole('button', { name: 'Save preferences', exact: true }).click();
    assert.deepEqual((await (await saving).json()).default_filters, { status: 'resolved', branch: 'Synthetic Other Branch' });
    await page.getByText('Preferences saved.', { exact: true }).waitFor(); await capture('settings-desktop');
    await page.emulateMedia({ colorScheme: 'dark' }); await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForFunction(() => document.documentElement.dataset.colorMode === 'dark');
    await capture('settings-dark-mobile');
    const restored = page.waitForResponse(response => response.url().endsWith('/cases/') && response.request().method() === 'POST');
    await page.goto(origin.origin + '/staff/app/complaints/');
    const response = await restored;
    assert.equal(response.request().postDataJSON().status, 'resolved', 'Restored request must use the saved status');
    assert.equal((await response.json()).pagination.total, 4, 'Saved branch must include the synthetic cases');
    await heading('4 cases');
    await page.getByText('Synthetic Other Branch', { exact: true }).waitFor();
    await page.goto(origin.origin + '/staff/app/complaints/?status=pending'); await heading('7 cases');
    await page.getByRole('button', { name: 'Settings', exact: true }).click();
    await select('Default queue', 'Not resolved'); await select('Default branch', 'All branches');
    await page.getByRole('button', { name: 'Save preferences', exact: true }).click();
    await page.getByText('Preferences saved.', { exact: true }).waitFor();
    await page.goto(origin.origin + '/staff/app/complaints/'); await heading('7 cases');
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
    if (input.preferences_only) { await preferenceChecks(); process.stdout.write(JSON.stringify({ passed: true, captures })); return; }
    const documentsBefore = requests.filter(row => row.resource === 'document').length;
    await page.getByRole('button', { name: 'Synthetic Customer 01', exact: true }).click();
    await heading('Synthetic Customer 01');
    assert.equal(await page.getByText('Synthetic older note 000', { exact: true }).count(), 0);
    await page.route('**/cases/*/history/', route => route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: 'Older activity could not be loaded. Try again.' }) }), { times: 1 });
    await page.getByRole('button', { name: 'Load older activity', exact: true }).click();
    await page.getByRole('button', { name: 'Retry older activity', exact: true }).waitFor();
    await capture('history-retry');
    await page.route('**/cases/*/history/', route => route.fulfill({ status: 400, contentType: 'application/json', body: JSON.stringify({ error: 'Refresh the complaint activity and try again.', field_errors: { history_cursor: 'invalid' } }) }), { times: 1 });
    await page.getByRole('button', { name: 'Retry older activity', exact: true }).click();
    await page.getByRole('button', { name: 'Refresh activity', exact: true }).click();
    await page.getByRole('button', { name: 'Load older activity', exact: true }).click();
    await page.getByText('Synthetic older note 011', { exact: true }).waitFor();
    await page.getByRole('button', { name: 'Load older activity', exact: true }).click();
    await page.getByText('Synthetic older note 000', { exact: true }).waitFor();
    assert.equal(await page.getByText(/^Synthetic older note \d{3}$/).count(), 61);
    assert.equal(await page.getByRole('button', { name: 'Load older activity', exact: true }).count(), 0);
    await capture('history-all-loaded');
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
    await page.getByText('Reported vs resolved', { exact: true }).waitFor(); await capture('reports-desktop');
    const drill = page.locator('svg[aria-label^="Complaint types."]').locator('[role="button"]').first();
    await drill.press('Enter');
    await page.waitForFunction(() => document.activeElement?.getAttribute('aria-label') === 'Filtered report complaints');
    async function reportCaptures(view) {
      for (const theme of ['light', 'dark']) {
        await page.emulateMedia({ colorScheme: theme });
        await page.waitForFunction(value => document.documentElement.dataset.colorMode === value, theme);
        for (const width of [320, 360, 390, 768, 1280, 1366, 1440, 1920]) {
          await page.setViewportSize({ width, height: width < 768 ? 844 : 900 }); await capture(`reports-${view}-${theme}-${width}`);
        }
      }
      for (const width of [390, 1366]) {
        await page.setViewportSize({ width, height: width < 768 ? 844 : 900 });
        for (const chart of await page.locator('svg[aria-label]').all()) {
          const label = await chart.getAttribute('aria-label');
          if (!label || !/\. (Hours|Complaints)\.$/.test(label)) continue;
          await chart.scrollIntoViewIfNeeded(); await capture(`chart-${view}-${width}-${label.split('.')[0].replaceAll(' ', '-')}`, true);
        }
      }
    }
    await reportCaptures('overview');
    await select('Report', 'Turnaround performance'); await heading('Resolution time');
    await select('View by', 'Day'); await heading('Resolution time');
    await page.locator('svg[aria-label^="Resolution time."]').getByRole('button', { name: /192 hours/ }).waitFor();
    assert.equal(await page.locator('svg[aria-label^="Resolution time."]').count(), 1);
    await page.getByText('4 of 4 timed resolutions had a target set.', { exact: true }).waitFor();
    await page.locator('svg[aria-label^="Resolution time."]').getByRole('button', { name: /Median resolution: 0 hours/ }).waitFor();
    await page.locator('svg[aria-label^="Home Based response time."]').getByRole('button', { name: /12 hours/ }).waitFor();
    const selectedReport = page.waitForResponse(response => response.url().endsWith('/reports/') && response.request().postDataJSON()?.selection?.metric === 'late');
    await page.locator('svg[aria-label^="Resolution targets."]').getByRole('button', { name: /^Late:/ }).press('Enter');
    assert.equal((await (await selectedReport).json()).table.count, 1);
    await page.waitForFunction(() => document.activeElement?.getAttribute('aria-label') === 'Filtered report complaints');
    await reportCaptures('turnaround');
    await page.setViewportSize({ width: 1366, height: 900 });
    await page.getByRole('button', { name: 'Download Excel', exact: true }).click();
    const downloading = page.waitForEvent('download');
    await page.getByRole('button', { name: 'Download filtered results', exact: true }).click();
    const file = await downloading; assert.ok(file.suggestedFilename().endsWith('.xlsx'));
    assert.ok(file.suggestedFilename().length > 6);
    await select('Report', 'Complaints overview'); await heading('Reported vs resolved');
    await page.getByLabel('From', { exact: true }).fill(input.month_start);
    const weeklyReport = page.waitForResponse(response => response.url().endsWith('/reports/') && response.request().postDataJSON()?.granularity === 'week' && !response.request().postDataJSON()?.selection?.metric);
    await select('View by', 'Week'); await weeklyReport;
    await page.locator('svg[aria-label^="Reported vs resolved."]').waitFor();
    const partialResponse = page.waitForResponse(response => response.url().endsWith('/reports/') && response.request().postDataJSON()?.selection?.metric === 'received');
    await page.locator('svg[aria-label^="Reported vs resolved."]').getByRole('button').first().press('Enter');
    const selectedPeriod = (await partialResponse).request().postDataJSON().selection;
    await page.waitForFunction(() => document.activeElement?.getAttribute('aria-label') === 'Filtered report complaints');
    assert.equal(selectedPeriod.date_from, input.month_start);
    const firstWeekEnd = new Date(input.month_start + 'T00:00:00Z');
    firstWeekEnd.setUTCDate(firstWeekEnd.getUTCDate() + 6 - (firstWeekEnd.getUTCDay() + 6) % 7);
    assert.equal(selectedPeriod.date_to, firstWeekEnd.toISOString().slice(0, 10));
    const activity = page.getByRole('region', { name: 'Reported vs resolved chart', exact: true });
    await activity.getByLabel('Chart type', { exact: true }).fill('Line');
    await activity.getByLabel('Chart type', { exact: true }).press('Enter');
    await page.waitForFunction(() => document.querySelectorAll('[aria-label="Reported vs resolved chart"] polyline').length === 2);
    await capture('reports-partial-week-line');
    await select('Period', 'All dates');
    await select('Report', 'Open-case follow-up'); await heading('Open-case age');
    await page.locator('svg[aria-label^="Open-case age."]').waitFor();
    assert.equal(await page.locator('svg[aria-label^="Open-case age."]').count(), 1);
    assert.equal(await page.locator('svg[aria-label^="Complaints reopened."]').getByRole('button').count(), 1);
    const ageResponse = page.waitForResponse(response => response.url().endsWith('/reports/') && response.request().postDataJSON()?.selection?.metric_value === '3_7');
    await select('Select cases in open-case age', '3-7 days');
    assert.equal((await (await ageResponse).json()).table.count, 2);
    await page.waitForFunction(() => document.activeElement?.getAttribute('aria-label') === 'Filtered report complaints');
    await reportCaptures('follow-up');
    await page.setViewportSize({ width: 390, height: 844 });
    await page.evaluate(() => { document.documentElement.style.fontSize = '200%'; });
    await capture('reports-large-text');
    await page.evaluate(() => { document.documentElement.style.fontSize = ''; });
    await page.getByLabel('From', { exact: true }).fill('2099-01-01');
    await page.getByText('No matching complaints.', { exact: true }).first().waitFor(); await capture('reports-empty');
    await page.getByLabel('From', { exact: true }).fill(''); await heading('Open-case age');
    await page.route('**/operations/v1/groups/*/reports/', route => route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: 'Synthetic unavailable report' }) }), { times: 1 });
    await select('View by', 'Month');
    await page.getByRole('heading', { name: 'Report action could not be completed', exact: true }).waitFor();
    assert.equal(await page.getByLabel('View by', { exact: true }).inputValue(), ''); // ADS selected value is not its search text.
    await capture('reports-failure-retained-filters');
    await page.getByRole('button', { name: 'Retry report', exact: true }).click(); await heading('Open-case age');
    await page.getByText('Month', { exact: true }).waitFor();
    assert.equal(requests.filter(row => row.resource === 'document').length, documentsBefore);
    await page.goBack(); await heading('7 cases');
    await page.goForward(); await heading('Open-case age');
    assert.equal(new URL(page.url()).searchParams.get('report'), 'follow-up');
    assert.equal(new URL(page.url()).searchParams.get('group_by'), 'month');
    await page.getByRole('button', { name: 'Refresh', exact: true }).click(); await heading('Open-case age');
    await page.getByText('Month', { exact: true }).waitFor();
    await page.reload(); await heading('Open-case age');
    await page.getByText('Month', { exact: true }).waitFor();
    await preferenceChecks();
    assert.deepEqual(await page.evaluate(() => ({ local: localStorage.length, session: sessionStorage.length })), { local: 0, session: 0 });
    assert.deepEqual(errors, []);
    fs.writeFileSync(path.join(output, 'layout.json'), JSON.stringify(layouts, null, 2));
    process.stdout.write(JSON.stringify({ passed: true, captures }));
  } finally { await browser.close(); }
}
main().catch(error => { console.error(error.stack); process.exitCode = 1; });
