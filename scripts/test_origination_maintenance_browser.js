'use strict';
// Called only by the isolated Django live-server test. Never accepts remote hosts.
const {chromium, expect} = require('playwright/test');
const path = require('node:path');

(async () => {
  const [url, output] = process.argv.slice(2);
  const target = new URL(url);
  if (!['localhost', '127.0.0.1'].includes(target.hostname) || !process.env.QA_SESSION_ID) {
    throw new Error('A synthetic local test server and test session are required.');
  }
  const browser = await chromium.launch({headless:true});
  const context = await browser.newContext({viewport:{width:1280,height:900}});
  await context.addCookies([{name:'sessionid',value:process.env.QA_SESSION_ID,domain:target.hostname,path:'/'}]);
  await context.route('**/*', route => {
    const request = new URL(route.request().url());
    return request.protocol === 'data:' || request.protocol === 'blob:' || request.origin === target.origin
      ? route.continue() : route.abort();
  });
  const page = await context.newPage();
  page.on('response', response => { if (response.status() >= 400) console.error(`${response.status()} ${response.url()}`); });
  const capture = async name => {
    for (const width of [320,390,430,1280]) {
      await page.setViewportSize({width,height:900});
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await page.screenshot({path:path.join(output,`${name}-${width}.png`),fullPage:true});
    }
    await page.evaluate(() => document.documentElement.classList.add('dark'));
    await page.setViewportSize({width:390,height:900});
    await page.screenshot({path:path.join(output,`${name}-dark-390.png`),fullPage:true});
    await page.evaluate(() => document.documentElement.classList.remove('dark'));
    await page.setViewportSize({width:1280,height:900});
  };
  try {
    await page.goto(url);
    await expect(page.getByRole('heading',{name:'Documents',exact:true})).toBeVisible();
    await capture('documents');
    await page.locator('.osw-maintenance-document').first().getByRole('button',{name:'Edit',exact:true}).click();
    await expect(page.locator('.cal-field-edit-button').first()).toBeVisible();
    await expect.poll(() => page.locator('#calibration-page').evaluate(image => image.complete && image.naturalWidth > 0)).toBe(true);
    await page.locator('.cal-field-edit-button').first().click();
    await expect(page.getByRole('heading',{name:'Edit document field'})).toBeVisible();
    await page.locator('#cal-field-label').fill('Requested amount');
    await page.getByRole('button',{name:'Save field',exact:true}).click();
    await expect(page.locator('#calibration-field-dialog')).not.toBeVisible();
    await page.screenshot({path:path.join(output,'field-editor-1280.png'),fullPage:true});
    await page.getByRole('button',{name:'Save & return',exact:true}).click();
    await expect(page.getByRole('heading',{name:'Documents',exact:true})).toBeVisible();
    await page.getByRole('link',{name:'Review changes',exact:true}).click();
    await expect(page.getByRole('heading',{name:'Proposed changes'})).toBeVisible();
    await capture('shared-review');
    await page.getByRole('button',{name:'Apply document changes',exact:true}).click();
    await expect(page.locator('#osw-confirm')).toBeVisible();
    await page.locator('#osw-confirm').getByRole('button',{name:'Confirm',exact:true}).click();
    await expect(page.getByRole('heading',{name:'Product setup workspace'})).toBeVisible();
    await page.goto(url);
    await expect(page.locator('.osw-maintenance-document').first()).toContainText('v2');
    await page.locator('.osw-maintenance-document').first().getByText('Replace or remove',{exact:true}).click();
    await page.getByRole('button',{name:'Remove from product',exact:true}).click();
    await page.locator('#osw-confirm').getByRole('button',{name:'Confirm',exact:true}).click();
    await expect(page.getByText('New applications will be unavailable until', {exact:false})).toBeVisible();
    await capture('withdrawal-review');
    await page.getByLabel('I understand that new applications will be unavailable.').check();
    await page.getByRole('button',{name:'Apply document changes',exact:true}).click();
    await page.locator('#osw-confirm').getByRole('button',{name:'Confirm',exact:true}).click();
    await expect(page.getByRole('heading',{name:'Product setup workspace'})).toBeVisible();
    await expect(page.getByText('Needs fixing',{exact:true}).first()).toBeVisible();
    console.log('Synthetic live admin edit, review, upgrade and withdrawal passed.');
  } catch (error) {
    await page.screenshot({path:path.join(output,'failure.png'),fullPage:true});
    throw error;
  } finally { await browser.close(); }
})().catch(error => { console.error(error.message); process.exitCode = 1; });
