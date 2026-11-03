/* Real loopback Django transport. Synthetic initData enters through stdin only. */
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const {chromium} = require('playwright');

(async () => {
  let input = ''; for await (const chunk of process.stdin) input += chunk;
  const config = JSON.parse(input);
  assert.ok(['127.0.0.1', 'localhost', '[::1]'].includes(new URL(config.origin).hostname));
  fs.mkdirSync(config.artifacts, {recursive: true});
  const browser = await chromium.launch();
  let page;
  const errors = [];
  try {
    page = await browser.newPage({viewport: {width:1280, height:900}});
    page.setDefaultTimeout(90000);
    page.on('pageerror', error => errors.push(error.message));
    await page.setExtraHTTPHeaders({'X-Telegram-Init-Data': config.initData});
    await page.addInitScript(initData => {
      window.Telegram = {WebApp: {initData, ready(){}, expand(){}, onEvent(){}, offEvent(){},
        BackButton:{onClick(){},offClick(){},show(){},hide(){}}, MainButton:{hide(){},offClick(){},onClick(){}}}};
    }, config.initData);
    const idle = () => page.waitForFunction(() => !document.querySelector('[data-source-sheet="Eco-conserve"]').disabled);
    const feedback = text => page.waitForFunction(value => document.querySelector('[data-feedback]').textContent.includes(value), text);
    const shot = name => page.screenshot({path:path.join(config.artifacts, name+'.png'), animations:'disabled'});
    await page.goto(config.origin+'/portal/s/all/');
    await page.getByRole('heading', {name:'All Cases', exact:true}).waitFor();
    assert.equal(await page.locator('#legacy-data-workspace,#legacy-import-workspace').count(), 0);
    await page.getByRole('link', {name:'Legacy import', exact:true}).click();
    await page.locator(`[name=group_id] option[value="${config.group}"]`).waitFor({state:'attached'});
    await idle();
    await page.getByRole('button', {name:'Eco-conserve', exact:true}).click(); await idle();
    await page.locator('[name=group_id]').selectOption(config.group);
    await page.locator('[name=namespace]').fill('synthetic-browser-61');
    await page.locator('[data-upload-form] [name=file]').setInputFiles(config.workbook);
    await page.getByRole('button', {name:'Upload and preview mapping', exact:true}).click();
    await page.locator('[data-action=stage]:visible').waitFor(); await idle();
    await page.locator('[data-action=stage]').click(); await feedback('61 staged'); await idle();
    await page.locator('[data-review-grid] .ag-row').first().waitFor(); await shot('staged-table');
    await page.getByRole('button', {name:'Cards', exact:true}).click();
    await page.locator('[data-rows]:visible article').first().waitFor();
    await page.locator('[data-rows] input[type=checkbox]').first().check();
    await page.getByRole('button', {name:'Table', exact:true}).click();
    await page.getByRole('button', {name:'Master Data', exact:true}).click(); await idle();
    assert.equal(await page.locator('[data-resume] option').count(), 1);
    await page.getByRole('button', {name:'Eco-conserve', exact:true}).click(); await idle();
    await page.locator('[data-resume]').selectOption({label:'synthetic-browser-61 · ready'});
    await feedback('1 approved'); await idle();
    await page.reload(); await page.locator('[data-resume] option').nth(1).waitFor({state:'attached'}); await idle();
    await page.locator('[data-resume]').selectOption({label:'synthetic-browser-61 · ready'});
    await feedback('1 approved'); await idle();
    await page.locator('[data-action=next]').click(); await idle();
    assert.match(await page.locator('[data-page]').textContent(), /51/);
    await page.locator('[data-action=cleanup]').click();
    await page.locator('[data-confirm][open]').waitFor();
    assert.match(await page.locator('[data-confirm]').innerText(), /Eco-conserve/);
    await page.locator('[data-confirm] button[value=confirm]').click();
    await page.waitForFunction(() => !document.querySelector('[data-action=commit]').hidden&&!document.querySelector('[data-action=commit]').disabled);
    await page.locator('[data-action=select_all]').click(); await idle();
    await page.locator('[data-action=commit]').click();
    await page.locator('[data-confirm][open]').waitFor();
    await page.locator('[data-confirm] button[value=confirm]').click();
    await feedback('61 imported'); await idle();
    await page.locator('[data-action=project]').click(); await page.locator('[data-confirm][open]').waitFor();
    assert.match(await page.locator('[data-confirm]').innerText(), /Master Data is untouched/);
    await page.locator('[data-confirm] button[value=confirm]').click(); await feedback('complete'); await idle();
    for (const width of [320,390,1280]) {
      await page.setViewportSize({width,height:900});
      await page.locator('[data-source-sheet="Eco-conserve"]').scrollIntoViewIfNeeded();
      assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
      await shot('complete-'+width);
    }
    assert.deepEqual(errors, []);
    fs.writeFileSync(path.join(config.artifacts,'observations.json'), JSON.stringify({rows:61, source:'Eco-conserve',
      allCasesImporter:false, reviewSelectionRetained:true, pageTwo:true, complete:true, widths:[320,390,1280], scriptErrors:errors},null,2));
    console.log('Real Django/Playwright legacy import completed: 61 rows; source switching, selection, pagination, resume and responsive captures.');
  } catch (error) {
    if(page) {
      await page.screenshot({path:path.join(config.artifacts,'failure.png'),animations:'disabled'});
      console.error('Browser script errors:',errors);
      if(await page.locator('[data-feedback]').count()) console.error('Importer feedback:',await page.locator('[data-feedback]').innerText());
      console.error('Visible page:',(await page.locator('body').innerText()).slice(0,1500));
    }
    throw error;
  } finally {await browser.close();}
})().catch(error => {console.error(error); process.exitCode=1;});
