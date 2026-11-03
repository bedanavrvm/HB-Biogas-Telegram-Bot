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
  const pumpStatuses=[];
  try {
    page = await browser.newPage({viewport: {width:1280, height:900}});
    page.setDefaultTimeout(90000);
    page.on('pageerror', error => errors.push(error.message));
    await page.route('**/*',route=>new URL(route.request().url()).origin===new URL(config.origin).origin?route.continue():route.abort());
    page.on('response',response=>{if(new URL(response.url()).pathname==='/api/portal/publication/pump/')pumpStatuses.push(response.status());});
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
    await page.locator('[data-action=previous]').click(); await idle();
    await page.locator('[data-action=select_page]').click(); await idle();
    await page.locator('[data-action=cleanup]').click();
    await page.locator('[data-confirm][open]').waitFor();
    assert.match(await page.locator('[data-confirm]').innerText(), /Eco-conserve/);
    await page.locator('[data-confirm] button[value=confirm]').click();
    await page.waitForFunction(() => !document.querySelector('[data-action=commit]').hidden&&!document.querySelector('[data-action=commit]').disabled);
    await page.locator('[data-action=commit]').click();
    await page.locator('[data-confirm][open]').waitFor();await page.locator('[data-confirm] button[value=confirm]').click();
    await feedback('50 imported');await idle();
    assert.equal(await page.locator('[data-synced-count]').innerText(),'0 / 50');
    assert.equal(await page.locator('[data-imported-count]').innerText(),'50 / 61');
    assert.equal(await page.locator('[data-not-imported]').innerText(),'11');
    await shot('sync-50-imported');
    assert.equal(await page.locator('[data-action=project]').isVisible(),true,'Sheet sync action must explain its prerequisite instead of disappearing after 50 imports');
    assert.equal(await page.locator('[data-action=project]').isDisabled(),true);
    assert.match(await page.locator('[data-sync-message]').innerText(),/Review unimported rows/);
    for(const width of [320,390]){
      await page.setViewportSize({width,height:900});
      await page.locator('[data-sheet-sync]').scrollIntoViewIfNeeded();
      assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
      assert.equal(await page.locator('[data-action=project]').isVisible(),true);
      await shot('sync-50-imported-'+width);
    }
    await page.setViewportSize({width:1280,height:900});
    const pump=await page.evaluate(async()=>{const r=await fetch('/api/portal/publication/pump/',{method:'POST',headers:{'Content-Type':'application/json','X-Request-ID':crypto.randomUUID()},body:'{}'});return {status:r.status,data:await r.json()};});
    assert.equal(pump.status,200);assert.equal(pump.data.paused,true);assert.equal(pump.data.reason,'legacy_cutover_maintenance');
    await shot('sync-partial-import');
    await page.locator('[data-action=review_pending]').click();await idle();
    assert.equal(await page.locator('[data-filter]').inputValue(),'pending');
    assert.match(await page.locator('[data-page]').innerText(),/of 11/);
    await page.locator('[data-action=select_all]').click(); await idle();
    await page.route('**/legacy/uploads/*/advance/',route=>route.abort('connectionfailed'),{times:1});
    await page.locator('[data-action=commit]').click();
    await page.locator('[data-confirm][open]').waitFor();
    await page.locator('[data-confirm] button[value=confirm]').click();
    await page.waitForFunction(()=>document.querySelector('[data-sync-message]').textContent.includes('Import paused'));
    await idle();
    assert.equal(await page.locator('[data-imported-count]').innerText(),'50 / 61');
    assert.equal(await page.locator('[data-action=project]').isVisible(),true);
    assert.equal(await page.locator('[data-action=project]').isDisabled(),true);
    await shot('sync-import-paused');
    const pausedUpload=await page.locator('[data-resume]').inputValue();
    await page.reload();await page.locator(`[data-resume] option[value="${pausedUpload}"]`).waitFor({state:'attached'});await idle();
    await page.locator('[data-resume]').selectOption(pausedUpload);await idle();
    assert.match(await page.locator('[data-sync-message]').innerText(),/Resume processing/);
    await page.locator('[data-action=resume]').click();
    await feedback('61 imported'); await idle();
    assert.equal(await page.locator('[data-synced-count]').innerText(),'0 / 61');
    assert.equal(await page.locator('[data-sync-pending]').innerText(),'61');
    assert.equal(await page.locator('[data-action=project]').isEnabled(),true);
    assert.match(await page.locator('[data-sync-message]').innerText(),/Sheet sync has not started/);
    await shot('sync-awaiting-confirmation');
    const summary=await page.waitForResponse(response=>response.request().method()==='GET'&&response.url().includes('?summary=1'));
    assert.equal(summary.status(),200);const savedSummary=await summary.json();
    assert.equal(savedSummary.upload.sheet_sync.pending,61);assert.equal('rows' in savedSummary,false);
    await page.locator('[data-action=project]').click(); await page.locator('[data-confirm][open]').waitFor();
    assert.match(await page.locator('[data-confirm]').innerText(), /Master Data is untouched/);
    await page.locator('[data-confirm] button[value=cancel]').click();await idle();
    assert.equal(await page.locator('[data-synced-count]').innerText(),'0 / 61');
    await page.locator('[data-action=project]').click();await page.locator('[data-confirm][open]').waitFor();
    await page.locator('[data-confirm] button[value=confirm]').click();
    await page.locator('[data-sheet-sync][data-state=needs_attention]').waitFor();await idle();
    assert.equal(await page.locator('[data-synced-count]').innerText(),'0 / 61');
    assert.match(await page.locator('[data-sync-message]').innerText(),/did not confirm/);
    await shot('sync-unconfirmed-acknowledgement');
    const upload=await page.locator('[data-resume]').inputValue();
    await page.reload();await page.locator(`[data-resume] option[value="${upload}"]`).waitFor({state:'attached'});await idle();
    await page.locator('[data-resume]').selectOption(upload);await idle();
    await page.locator('[data-sheet-sync][data-state=needs_attention]').waitFor();
    await page.locator('[data-action=resume]').click();await feedback('complete');await idle();
    assert.equal(await page.locator('[data-synced-count]').innerText(),'61 / 61');
    assert.equal(await page.locator('[data-sync-pending]').innerText(),'0');
    await page.locator('[data-sheet-sync][data-state=complete]').waitFor();
    for (const width of [320,390,1280]) {
      await page.setViewportSize({width,height:900});
      await page.locator('[data-source-sheet="Eco-conserve"]').scrollIntoViewIfNeeded();
      assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
      await shot('complete-'+width);
    }
    assert.deepEqual(errors, []);
    assert.ok(pumpStatuses.length>0&&pumpStatuses.every(status=>status===200),JSON.stringify(pumpStatuses));
    fs.writeFileSync(path.join(config.artifacts,'observations.json'), JSON.stringify({rows:61, source:'Eco-conserve',
      allCasesImporter:false, reviewSelectionRetained:true, pageTwo:true, complete:true, partialImport:{saved:50,total:61,syncActionVisible:true,syncActionDisabled:true},interruptedImportResumed:true,
      syncBeforeConfirmation:0,syncedAfterReadback:61,lostAcknowledgementRecovered:true,pumpStatuses,widths:[320,390,1280], scriptErrors:errors},null,2));
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
