'use strict';
// Isolated native Admin only; Django supplies synthetic authentication and files.
const {chromium, expect} = require('playwright/test');
const path = require('node:path');
const fs = require('node:fs');
(async () => {
  const target = new URL(process.argv[2]);
  if (!['localhost','127.0.0.1'].includes(target.hostname)) throw Error('Loopback required.');
  const browser = await chromium.launch();
  try {
    const context = await browser.newContext({viewport:{width:1366,height:900}});
    await context.addCookies([{name:'sessionid',value:process.env.QA_SESSION_ID,domain:target.hostname,path:'/'}]);
    await context.route('**/*', route => new URL(route.request().url()).origin === target.origin ? route.continue() : route.abort());
    const page = await context.newPage();
    await page.goto(target.href);
    await expect(page.locator('#calibration-save-state')).toHaveText('Saved');
    await page.locator('button[data-nav-action="select"][data-key="borrower.signature"]').click();
    await expect(page.locator('#calibration-duplicate')).toBeEnabled();
    const url = new URL(await page.locator('#calibration-app').getAttribute('data-signers-url'), target);
    const saved = page.waitForResponse(response => response.url() === url.href && response.request().method() === 'POST');
    await page.locator('#calibration-duplicate').click();
    const response = await saved;
    expect(response.status()).toBe(200);
    const data = await response.json();
    expect(data.signers).toHaveLength(1);
    expect(data.signers[0].role).toBe('borrower');
    expect(data.configuration.signature_overlay_manifest.slots['borrower.signature_copy']).toBeTruthy();
    expect(data.configuration.signature_overlay_manifest.slots['borrower.signature_copy_date']).toBeTruthy();
    await expect(page.locator('#calibration-save-state')).toHaveText('Saved');
    await page.reload();
    await expect(page.locator('button[data-nav-action="select"][data-key="borrower.signature_copy"]')).toBeVisible();
    await page.locator('button[data-nav-action="edit-signature"][data-key="borrower.signature_copy"]').click();
    const identity = page.locator('[data-signer-identity="national_id"]');
    await expect(identity).toBeVisible();
    const identitySaved = page.waitForResponse(response => response.url() === url.href && response.request().method() === 'POST');
    await identity.selectOption('');
    expect((await (await identitySaved).json()).signers[0].identity_fields.national_id).toBeNull();
    await expect(page.locator('#calibration-save-state')).toHaveText('Saved');
    await page.reload();
    const signerLabel = page.locator('[data-signer-label="0"]');
    const labelSaved = page.waitForResponse(response => response.url() === url.href && response.request().method() === 'POST');
    await signerLabel.fill('Borrower "Quoted"');
    await signerLabel.blur();
    expect((await (await labelSaved).json()).signers[0].label).toBe('Borrower "Quoted"');
    await expect(page.locator('#calibration-save-state')).toHaveText('Saved');
    await page.reload();
    await expect(signerLabel).toHaveValue('Borrower "Quoted"');
    await page.locator('[data-signer-edit="0"]').click();
    await expect(identity).toHaveValue('');
    const output = path.resolve('test-results/origination-signature-copy');
    fs.mkdirSync(output,{recursive:true});
    for (const colorScheme of ['light','dark']) {
      await page.emulateMedia({colorScheme});
      await page.evaluate(dark => document.documentElement.classList.toggle('dark', dark), colorScheme === 'dark');
      for (const width of [390,1366]) {
        await page.setViewportSize({width,height:900});
        if (width < 700) await page.locator('#cal-mobile-fields').click();
        await expect(identity).toBeVisible();
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
        await page.screenshot({path:path.join(output,`${colorScheme}-${width}.png`),fullPage:true});
        if (width < 700) await page.keyboard.press('Escape');
      }
    }
    await page.locator('#calibration-publish').click();
    await expect(page.locator('#calibration-save-state')).toHaveText('Published');
    await page.setViewportSize({width:1366,height:900});
    await page.locator('button[data-nav-action="select"][data-key="borrower.signature_copy"]').click();
    await expect(page.locator('#calibration-duplicate')).toBeDisabled();
  } finally { await browser.close(); }
})().catch(error => {console.error(error);process.exitCode=1;});
