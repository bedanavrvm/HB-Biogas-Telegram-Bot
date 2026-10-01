'use strict';
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const {chromium} = require('playwright');
const {install,base,output,batchId,batch} = require('./portal_journey_audit');
(async()=>{
  const browser=await chromium.launch(); const results={};
  try {
    const page=await browser.newPage({viewport:{width:390,height:800}});
    await install(page,{requests:[],errors:[],approval:true});
    await page.goto(`${base}/portal/s/approvals/payments/${batchId}/`,{waitUntil:'networkidle'});
    await page.locator('.payment-current-case summary').first().click();
    await page.locator('.payment-review-comment').first().fill('Synthetic unsaved review');
    page.on('dialog',async dialog=>{results.discardPrompt=dialog.message();await dialog.dismiss();});
    results.paymentReviewCanLeaveWithoutConfirmation=await page.evaluate(()=>MiniAppUtils.canNavigatePage('/portal/s/dashboard/'));
    const rows = page.locator('#payments-current-cases .payment-current-case');
    await rows.nth(1).locator('summary').click();
    await rows.nth(1).locator('.payment-review-comment').fill('Keep this second unsaved comment');
    await page.route('**/api/portal/payments/batches/*/cases/*/review/', route => route.fulfill({status:200, contentType:'application/json', body:JSON.stringify({ok:true,batch:{...batch,status:'in_review',revision:2,cases:batch.cases.map((item,index)=>index ? item : {...item,decision:'approved',comment:'Synthetic unsaved review'})}})}));
    await rows.first().locator('.payment-approve').click();
    await page.waitForTimeout(150);
    // Current pending rows use farmer IDs; find the retained text independent
    // of its collapsed/expanded placement after re-render.
    results.otherReviewCommentRetained = await page.locator('.payment-review-comment').evaluateAll(nodes=>nodes.some(node=>node.value==='Keep this second unsaved comment'));
    await page.screenshot({path:path.join(output,'unsaved-payment-review.png'),fullPage:true});
    await page.close();
    const pump=await browser.newPage({viewport:{width:390,height:800}});
    await install(pump,{requests:[],errors:[]});
    let releasePump;
    await pump.route('**/api/portal/publication/pump/',async route=>{await new Promise(resolve=>{releasePump=resolve;}); await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({ok:true,changed:false,poll_after_seconds:60})});});
    await pump.goto(`${base}/portal/s/dashboard/`,{waitUntil:'domcontentloaded'});
    await pump.waitForTimeout(1800);
    results.backgroundPumpRequestStarted=Boolean(releasePump);
    results.navigationAllowedDuringBackgroundPump=await pump.evaluate(()=>MiniAppUtils.canNavigatePage('/portal/s/jbl/'));
    await pump.waitForTimeout(20500);
    results.stalledPumpLeaseReleased = await pump.evaluate(()=>localStorage.getItem('portal-publication-pump-lease') === null);
    await pump.screenshot({path:path.join(output,'background-pump-blocks-navigation.png'),fullPage:true});
    releasePump?.(); await pump.waitForTimeout(100); await pump.close();
    const hb = await browser.newPage({viewport:{width:390,height:800}});
    const hbObservation = {requests:[],errors:[]};
    await install(hb,hbObservation);
    await hb.route('**/api/portal/hb-actions/10000000-0000-4000-8000-000000000001/**',route=>route.fulfill({
      status:200,contentType:'application/json',body:JSON.stringify({ok:true,options:{},permissions:{write:true,correct:true},action:{
        farmer_id:'10000000-0000-4000-8000-000000000001',customer_name:'Synthetic HB Customer',order_number:'SYN-1',
        workstream:'installation',installation_status:'open',installation_status_label:'Not installed',history:[],
      }}),
    }));
    await hb.goto(`${base}/portal/s/hb-actions/10000000-0000-4000-8000-000000000001/?workstream=installation`,{waitUntil:'networkidle'});
    await hb.locator('#hb-report-installation-delay').click();
    await hb.locator('#hb-installation-note').fill('Synthetic unsaved installation delay');
    hb.on('dialog',async dialog=>{results.hbDiscardPrompt=dialog.message();await dialog.dismiss();});
    results.hbDelayCanLeaveWithoutConfirmation=await hb.evaluate(()=>MiniAppUtils.canNavigatePage('/portal/s/hb-actions/'));
    results.hbPageErrors=hbObservation.errors;
    await hb.screenshot({path:path.join(output,'unsaved-hb-delay.png'),fullPage:true});
    await hb.close();
    assert.equal(results.paymentReviewCanLeaveWithoutConfirmation, false);
    assert.equal(results.hbDelayCanLeaveWithoutConfirmation, false);
    assert.equal(results.backgroundPumpRequestStarted, true);
    assert.equal(results.navigationAllowedDuringBackgroundPump, true);
    assert.equal(results.stalledPumpLeaseReleased, true);
    assert.equal(results.otherReviewCommentRetained, true);
    assert.deepEqual(results.hbPageErrors, []);
  } finally {await browser.close();fs.writeFileSync(path.join(output,'behavior.json'),JSON.stringify(results,null,2));}
  console.log(JSON.stringify(results,null,2));
})().catch(error=>{console.error(error);process.exitCode=1;});
