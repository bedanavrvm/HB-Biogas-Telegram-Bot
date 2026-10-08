'use strict';
// Synthetic localhost only. Called by Django's isolated live-server test.
const {chromium, expect} = require('playwright/test');
const path = require('node:path');
(async () => {
  const [url, output, mode = 'baseline'] = process.argv.slice(2);
  const target = new URL(url);
  if (!['localhost', '127.0.0.1'].includes(target.hostname) || !process.env.QA_SESSION_ID) throw Error('Local synthetic session required.');
  const browser = await chromium.launch();
  const context = await browser.newContext({viewport:{width:1280,height:900}});
  await context.addCookies([{name:'sessionid',value:process.env.QA_SESSION_ID,domain:target.hostname,path:'/'}]);
  await context.route('**/*', route => {
    const u = new URL(route.request().url());
    return u.origin === target.origin || ['data:','blob:'].includes(u.protocol) ? route.continue() : route.abort();
  });
  await context.tracing.start({screenshots:true,snapshots:true,sources:true});
  const page = await context.newPage();
  const errors=[];page.on('pageerror',error => errors.push(error.message));
  try {
    await page.goto(url);
    if(mode !== 'baseline') {
      await page.locator('#id_name').fill('Synthetic custom loan document');
      await page.getByText('Upload a PDF instead',{exact:true}).click();
      await page.locator('#id_pdf').setInputFiles({name:'synthetic.pdf',mimeType:'application/pdf',buffer:Buffer.from(process.env.QA_PDF_BASE64,'base64')});
      await page.getByRole('button',{name:'Create document',exact:true}).click();
    }
    await expect.poll(() => page.locator('#calibration-page').evaluate(i => i.complete && i.naturalWidth > 0)).toBe(true);
    await page.screenshot({path:path.join(output,`${mode}-custom-pdf.png`),fullPage:true});
    if (mode === 'baseline') {
      await page.getByRole('button',{name:'+ Signer slot',exact:true}).click();
      await expect(page.locator('#calibration-status')).toContainText('Every configured signer slot is already placed');
      console.log('BASELINE: synthetic post-upload checkpoint; 0 configured signers; add-signature cannot define a signer; 1 dead end; publish unavailable.');
    } else {
      await expect(page.locator('#document-signers')).toBeVisible();
      await page.locator('#document-signer-pack').selectOption('borrower,officer,credit_analyst,branch_manager');
      await expect(page.locator('#calibration-save-state')).toHaveText('Saved');
      await expect(page.locator('#document-signer-list .document-signer-row')).toHaveCount(4);
      await page.locator('[data-signer-label="0"]').fill('Applicant');
      await page.locator('[data-signer-label="0"]').blur();
      await expect(page.locator('#calibration-save-state')).toHaveText('Saved');
      await page.locator('#document-lending-fields').click();
      await expect(page.locator('#calibration-save-state')).toHaveText('Saved');
      if(mode === 'value-contract') {
        await page.locator('#document-pdf').evaluate(element => {element.open=true;});
        await page.locator('#document-shared-values').check();
        await expect(page.locator('#calibration-save-state')).toHaveText('Saved');
        await expect(page.locator('#document-shared-values')).toBeDisabled();
        await page.locator('#calibration-add').click();
        await expect(page.locator('#cal-field-meaning')).toBeVisible();
        await page.locator('#cal-field-meaning').evaluate(element => {element.open=true;});
        for(const width of [320,390,430,1280]) {
          await page.setViewportSize({width,height:900});
          expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
          await page.screenshot({path:path.join(output,`shared-values-field-${width}.png`),fullPage:true});
          await page.emulateMedia({colorScheme:'dark'});
          await page.evaluate(() => {document.documentElement.classList.add('dark');});
          await page.screenshot({path:path.join(output,`shared-values-field-${width}-dark.png`),fullPage:true});
          await page.emulateMedia({colorScheme:'light'});
          await page.evaluate(() => {document.documentElement.classList.remove('dark');});
        }
        await page.locator('#cal-field-confirm').scrollIntoViewIfNeeded();
        await expect(page.locator('#cal-field-confirm')).toBeVisible();
        await page.locator('#cal-field-dismiss').click();
        await page.setViewportSize({width:1280,height:900});
        await page.locator('#document-pdf').evaluate(element => {element.open=false;});
      }
      await page.locator('#document-signers').evaluate(element => {element.open=false;});
      let placements=0;
      while(await page.locator('[data-document-task]').filter({hasText:/^Place:/}).count()) {
        await page.locator('[data-document-task]').filter({hasText:/^Place:/}).first().click();
        await page.locator('#calibration-overlays').click({position:{x:160,y:60+placements*48}});
        await expect(page.locator('#calibration-save-state')).toHaveText('Saved');
        if(++placements > 15) throw Error('Placement did not clear its server task.');
      }
      await expect(page.locator('#calibration-publish')).toBeEnabled();
      const previewResponse=page.waitForResponse(response => response.url().endsWith('/calibration-preview/') && response.request().method()==='POST');
      const previousImage=await page.locator('#calibration-page').getAttribute('src');
      await page.locator('#cal-filled').click();
      expect((await previewResponse).status()).toBe(200);
      await expect(page.locator('#calibration-page')).not.toHaveAttribute('src',previousImage);
      await expect.poll(() => page.locator('#calibration-page').evaluate(i => i.complete && i.naturalWidth > 0)).toBe(true);
      await page.screenshot({path:path.join(output,'final-preview-1280.png'),fullPage:true});
      const sourceResponse=page.waitForResponse(response => response.url().includes('/calibration-page/?page=') && response.request().method()==='GET');
      await page.locator('#cal-source').click();
      expect((await sourceResponse).status()).toBe(200);
      for(const width of [320,390,430,1280]) {
        await page.setViewportSize({width,height:900});
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
        if(width < 700) await page.locator('#cal-mobile-fields').click();
        await page.screenshot({path:path.join(output,`final-editor-${width}.png`),fullPage:true});
        if(width < 700) await page.locator('#calibration-sheet-close').click();
      }
      await page.locator('#calibration-publish').click();
      await expect(page.locator('#calibration-save-state')).toHaveText('Published');
      await page.reload();
      await expect(page.locator('#calibration-save-state')).toHaveText('Published');
      await expect(page.locator('.cal-published-label')).toBeVisible();
      await expect(page.locator('#calibration-publish')).toBeHidden();
      await expect(page.locator('#document-signer-list .document-signer-row')).toHaveCount(4);
      await page.screenshot({path:path.join(output,'final-published-1280.png'),fullPage:true});
      await page.setViewportSize({width:390,height:900});
      await page.locator('#cal-mobile-fields').click();
      await expect(page.locator('#calibration-sheet-close')).toBeEnabled();
      await page.locator('#document-signers').evaluate(element => {element.open=true;});
      await page.screenshot({path:path.join(output,'final-published-390.png'),fullPage:true});
      await page.locator('#calibration-sheet-close').click();
      await expect(page.locator('#calibration-sidebar')).not.toHaveClass(/mobile-open/);
      await expect(page.locator('#calibration-sidebar')).toHaveAttribute('aria-hidden','true');
      await page.setViewportSize({width:1280,height:900});
      const productUrl=new URL(process.env.QA_PRODUCT_URL);
      if(productUrl.origin !== target.origin) throw Error('Product workspace must use the same isolated server.');
      await page.goto(productUrl.href);
      await page.getByText('Choose documents',{exact:true}).click();
      const choice=page.locator('[name="templates"]').filter({visible:true});
      await choice.uncheck();await choice.check();
      await expect(page.locator('[data-save-feedback]')).toHaveText('Saved');
      await expect(page.locator('[data-product-publish] button')).toBeEnabled();
      await page.screenshot({path:path.join(output,'final-product-ready-1280.png'),fullPage:true});
      await page.setViewportSize({width:390,height:900});
      await page.screenshot({path:path.join(output,'final-product-ready-390.png'),fullPage:true});
      await page.setViewportSize({width:1280,height:900});
      const productResponse=page.waitForResponse(response => response.request().method()==='POST' && response.url().endsWith('/publish/'));
      await page.locator('[data-product-publish] button').click();
      expect((await productResponse).status()).toBe(200);
      await expect(page.locator('.osw-hero .osw-status')).toHaveText('Published');
      expect(errors).toEqual([]);
      console.log(`FINAL: custom PDF uploaded, signer pack added, signer edited, lending fields added, ${placements} fields/signatures placed, previewed and published; draft product linked and published; 0 dead ends. Mobile 320/390/430 and desktop checked.`);
    }
  } catch(error) {
    await page.screenshot({path:path.join(output,`${mode}-failure.png`),fullPage:true});throw error;
  } finally {
    await context.tracing.stop({path:path.join(output,`${mode}-trace.zip`)});
    await browser.close();
  }
})().catch(e => {console.error(e);process.exitCode=1;});
