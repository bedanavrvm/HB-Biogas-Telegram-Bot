'use strict';
// Synthetic Django live-server test only. Never accepts staging/production hosts.
const {chromium, expect} = require('playwright/test');
const path = require('node:path');

(async () => {
  const [url, output] = process.argv.slice(2);
  const target = new URL(url);
  if (!['localhost', '127.0.0.1'].includes(target.hostname)
      || !process.env.QA_SESSION_ID || !process.env.QA_DOCUMENT_ID) {
    throw new Error('An isolated local server, synthetic document and test session are required.');
  }
  const browser = await chromium.launch({headless: true});
  const context = await browser.newContext({viewport: {width: 1280, height: 900}});
  await context.addCookies([{
    name: 'sessionid', value: process.env.QA_SESSION_ID, domain: target.hostname, path: '/',
  }]);
  await context.route('**/*', route => {
    const request = new URL(route.request().url());
    return ['data:', 'blob:'].includes(request.protocol) || request.origin === target.origin
      ? route.continue() : route.abort();
  });
  const page = await context.newPage();
  const failures = [];
  page.on('pageerror', error => failures.push(error.message));
  page.on('response', response => {
    if (new URL(response.url()).origin === target.origin && response.status() >= 400) {
      failures.push(`${response.status()} ${response.url()}`);
    }
  });
  const capture = async name => {
    for (const width of [320, 430, 1280]) {
      await page.setViewportSize({width, height: 900});
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await page.screenshot({path: path.join(output, `${name}-${width}.png`), fullPage: true});
    }
    await page.setViewportSize({width: 430, height: 900});
    await page.evaluate(() => document.documentElement.classList.add('dark'));
    await page.screenshot({path: path.join(output, `${name}-430-dark.png`), fullPage: true});
    await page.evaluate(() => document.documentElement.classList.remove('dark'));
    await page.setViewportSize({width: 1280, height: 900});
  };
  try {
    const catalogueUrl = new URL('/admin/origination/originationdocumenttemplate/', target).href;
    await page.goto(catalogueUrl);
    await expect(page.getByText('No products assigned', {exact: true})).toBeVisible();
    await expect(page.getByText('Unavailable for new applications', {exact: true})).toHaveCount(0);
    await page.screenshot({path: path.join(output, 'catalogue-before-1280.png'), fullPage: true});
    await page.goto(url);
    await page.getByText('Choose documents', {exact: true}).click();
    const choice = page.locator(`form[data-osw-autosave] input[name="templates"][value="${process.env.QA_DOCUMENT_ID}"]`);
    await expect(choice).toBeVisible();
    await expect(choice).not.toBeChecked();
    await capture('available-laf');
    await choice.check();
    await expect(page.locator('[data-save-feedback]')).toHaveText('Saved');
    await expect(page.locator('[data-selected-documents]')).toContainText('Guided Main LAF');
    await expect(page.getByText('No documents selected.', {exact: true})).toHaveCount(0);
    await expect(page.locator('[data-product-publish] button')).toBeEnabled();
    await capture('attached-laf');
    await page.reload();
    await expect(page.locator(`[name="templates"][value="${process.env.QA_DOCUMENT_ID}"]`).first()).toBeChecked();
    await page.locator('[data-product-publish] button').click();
    await expect(page.locator('.osw-hero .osw-status')).toHaveText('Published');
    await capture('published-product');
    await page.goto(catalogueUrl);
    await expect(page.getByText('Optional Rows Loan', {exact: true})).toBeVisible();
    await expect(page.getByText('No products assigned', {exact: true})).toHaveCount(0);
    await page.screenshot({path: path.join(output, 'catalogue-after-1280.png'), fullPage: true});
    expect(failures).toEqual([]);
    console.log('Published LAF selected, autosaved, retained on refresh and product published without republishing/copying PDF. Screenshots: 320/430/1280px, light/dark.');
  } catch (error) {
    await page.screenshot({path: path.join(output, 'failure.png'), fullPage: true});
    throw error;
  } finally {
    await browser.close();
  }
})().catch(error => {console.error(error); process.exitCode = 1;});
