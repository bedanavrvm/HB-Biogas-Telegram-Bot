/* Local synthetic Admin confirmation only; no production/provider access. */
const {chromium, expect} = require('playwright/test');
const path = require('path');
const fs = require('fs');

(async () => {
  const url = new URL(process.argv[2]);
  if (!['127.0.0.1', 'localhost'].includes(url.hostname)) throw new Error('Local test server required.');
  const output = process.argv[3];
  fs.mkdirSync(output, {recursive: true});
  const browser = await chromium.launch({headless: true});
  try {
    const context = await browser.newContext();
    await context.addCookies([{name: 'sessionid', value: process.env.QA_SESSION_ID, url: url.origin}]);
    const page = await context.newPage();
    await page.route('**/*', route => {
      const target = new URL(route.request().url());
      return ['127.0.0.1', 'localhost', 'data:', 'about:'].includes(target.hostname || target.protocol)
        ? route.continue() : route.abort();
    });
    await page.goto(url.href);
    await page.locator(`input[name="_selected_action"][value="${process.env.QA_DELETE_PRODUCT_ID}"]`).check();
    await page.locator('select[name="action"]').first().selectOption('delete_testing_selection');
    await page.locator('button[name="index"]').first().click();
    await expect(page.getByRole('button', {name: 'Confirm permanent deletion'})).toBeVisible();
    for (const width of [320, 430, 1280]) {
      await page.setViewportSize({width, height: 850});
      for (const theme of ['light', 'dark']) {
        await page.evaluate(value => {
          document.documentElement.classList.toggle('dark', value === 'dark');
          document.documentElement.dataset.theme = value;
        }, theme);
        const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1);
        expect(overflow).toBe(false);
        await page.screenshot({path: path.join(output, `confirmation-${width}-${theme}.png`), fullPage: true});
      }
    }
    await page.getByRole('radio', {name: 'Also delete the linked records listed below'}).check();
    await page.getByRole('button', {name: 'Update impact'}).click();
    await expect(page.getByRole('radio', {name: 'Also delete the linked records listed below'})).toBeChecked();
    await page.getByRole('button', {name: 'Confirm permanent deletion'}).click();
    await expect(page.getByText('Deleted 1 record(s); kept 0 linked record(s). Sheet cleanup: 0 queued update(s). Drive files kept.', {exact: true})).toBeVisible();
    console.log('Admin selection, impact refresh and confirmation passed; six local screenshots captured.');
  } finally {
    await browser.close();
  }
})().catch(error => {console.error(error); process.exit(1);});
