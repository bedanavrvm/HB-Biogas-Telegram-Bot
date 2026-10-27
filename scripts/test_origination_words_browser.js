'use strict';
const {chromium,expect}=require('playwright/test');
const fs=require('node:fs'), path=require('node:path');
(async()=>{
  const target=new URL(process.argv[2]);if(!['localhost','127.0.0.1'].includes(target.hostname))throw Error('Loopback required');
  const browser=await chromium.launch();
  try{
    const context=await browser.newContext({viewport:{width:1280,height:900}});
    await context.addCookies([{name:'sessionid',value:process.env.QA_SESSION_ID,domain:target.hostname,path:'/'}]);
    await context.route('**/*',route=>new URL(route.request().url()).origin===target.origin?route.continue():route.abort());
    const page=await context.newPage();await page.goto(target.href);
    await expect(page.locator('#calibration-save-state')).toHaveText('Saved');
    await page.locator('[data-nav-action="select"][data-key="synthetic_amount"]').click();
    await page.locator('#calibration-advanced').evaluate(node=>node.open=true);
    await page.locator('#cal-number-words').check();
    await expect(page.locator('#calibration-save-state')).toHaveText('Saved');
    const priorImage=await page.locator('#calibration-page').getAttribute('src');
    const previewUrl=await page.locator('#calibration-app').getAttribute('data-preview-url');
    const filled=page.waitForResponse(response=>response.url()===new URL(previewUrl,target).href&&response.request().method()==='POST');
    await page.getByRole('button',{name:'Filled sample',exact:true}).click();
    expect((await filled).status()).toBe(200);
    await expect.poll(()=>page.locator('#calibration-page').getAttribute('src')).not.toBe(priorImage);
    await expect.poll(()=>page.locator('#calibration-page').evaluate(image=>image.complete&&image.naturalWidth>0)).toBe(true);
    await page.getByRole('button',{name:'Fit page',exact:true}).click();
    await page.locator('#cal-number-words').scrollIntoViewIfNeeded();
    const output=path.resolve('test-results/origination-improvements-live');fs.mkdirSync(output,{recursive:true});
    await page.screenshot({path:path.join(output,'numeric-words-1280.png'),fullPage:true});
    await page.reload();await expect(page.locator('#calibration-save-state')).toHaveText('Saved');
    await page.locator('[data-nav-action="select"][data-key="synthetic_amount"]').click();
    await expect(page.locator('#cal-number-words')).toBeChecked();
  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
