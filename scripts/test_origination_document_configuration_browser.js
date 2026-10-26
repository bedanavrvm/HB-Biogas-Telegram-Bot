'use strict';
const {chromium, expect} = require('playwright/test');
const path = require('node:path');
(async () => {
  const [url, output] = process.argv.slice(2);
  const target = new URL(url);
  if (!['localhost', '127.0.0.1'].includes(target.hostname) || !process.env.QA_SESSION_ID) throw Error('Local synthetic session required.');
  const browser = await chromium.launch();
  const context = await browser.newContext({viewport:{width:1280,height:900}});
  await context.addCookies([{name:'sessionid',value:process.env.QA_SESSION_ID,domain:target.hostname,path:'/'}]);
  await context.route('**/*', route => {
    const destination = new URL(route.request().url());
    return destination.origin === target.origin || ['data:','blob:'].includes(destination.protocol) ? route.continue() : route.abort();
  });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('dialog', dialog => dialog.accept());
  try {
    await page.goto(url);
    await expect.poll(() => page.locator('#calibration-page').evaluate(image => image.complete && image.naturalWidth > 0)).toBe(true);
    await page.locator('#document-signers').evaluate(element => {element.open=true;});
    await expect(page.locator('body')).not.toContainText('Review signer: asset owner');
    await page.locator('[data-signer-edit="0"]').click();
    const phone = page.locator('[data-signer-identity="phone"]').first();
    await expect(phone).toHaveValue('synthetic_main_phone');
    await expect(phone.locator('option:checked')).toContainText('from application/Main LAF');
    await page.locator('[data-nav-action="select"][data-kind="signature"][data-key="officer.signature"]').click();
    await page.locator('#calibration-delete').click();
    await expect(page.locator('#calibration-save-state')).toHaveText('Saved');
    await expect(page.locator('[data-nav-action][data-key="officer.signature"]')).toHaveCount(0);
    await expect(page.locator('#document-signer-list .document-signer-row')).toHaveCount(1);
    // A subsequent signer edit uses the new schema revision returned by placement autosave.
    await page.locator('[data-signer-label="0"]').fill('Synthetic applicant');
    await page.locator('[data-signer-label="0"]').blur();
    await expect(page.locator('#calibration-save-state')).toHaveText('Saved');
    await page.reload();
    await expect.poll(() => page.locator('#calibration-page').evaluate(image => image.complete && image.naturalWidth > 0)).toBe(true);
    await page.locator('#document-signers').evaluate(element => {element.open=true;});
    await expect(page.locator('#document-signer-list .document-signer-row')).toHaveCount(1);
    await page.locator('[data-signer-edit="0"]').click();
    await expect(page.locator('[data-signer-identity="phone"]').first()).toHaveValue('synthetic_main_phone');
    for (const width of [390, 1280]) {
      await page.setViewportSize({width,height:900});
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await page.screenshot({path:path.join(output,`document-contract-${width}.png`),fullPage:true});
    }
    expect(errors).toEqual([]);
    console.log('PASS: shared Main LAF identity retained, last officer signature removes obligation, later autosave and reload preserve changes.');
  } finally {
    await browser.close();
  }
})().catch(error => {console.error(error);process.exitCode=1;});
