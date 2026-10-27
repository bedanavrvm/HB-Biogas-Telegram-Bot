'use strict';
const {chromium,expect}=require('playwright/test');
const path=require('node:path');
(async()=>{
  const [base,output,mode]=process.argv.slice(2), origin=new URL(base).origin;
  if(!['localhost','127.0.0.1'].includes(new URL(base).hostname)) throw Error('Loopback required');
  const browser=await chromium.launch();
  const context=await browser.newContext({viewport:{width:390,height:844}});
  await context.addCookies([{name:'sessionid',value:process.env.QA_SESSION_ID,domain:new URL(base).hostname,path:'/'}]);
  await context.route('**/*',route=>new URL(route.request().url()).origin===origin?route.continue():route.abort());
  await context.addInitScript(()=>{
    window.Telegram={WebApp:{initData:'',ready(){},expand(){},onEvent(){},BackButton:{show(){},hide(){},onClick(){},offClick(){}}}};
    window.__streams=[];
    navigator.mediaDevices.getUserMedia=async()=>{
      const canvas=document.createElement('canvas');canvas.width=900;canvas.height=600;
      const ctx=canvas.getContext('2d');ctx.fillStyle='white';ctx.fillRect(0,0,900,600);
      for(let i=0;i<600;i++){ctx.fillStyle=`hsl(${i%360} 50% 50%)`;ctx.fillRect((i*19)%900,(i*37)%600,22,8);}
      const stream=canvas.captureStream(5);window.__streams.push(stream);return stream;
    };
  });
  const page=await context.newPage(),errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  try{
    if(mode==='setup' || mode==='setup-fields') {
      await page.goto(base);
      await expect(page.locator('[data-outstanding]')).toHaveText('1 thing left');
      await expect(page.locator('[data-outstanding-items]')).toContainText('Documents');
      await expect(page.locator('[data-outstanding-items] li')).toHaveCount(1);
      const details=async()=>{
        for(const text of ['Home Visit (v3)','Loan Amount (loan_amount)','different information','Loan Application (v1)'])
          await expect(page.locator('[data-outstanding-items]')).toContainText(text);
        await expect(page.locator('[data-outstanding-items]')).not.toContainText('Review the highlighted document fields');
      };
      if(mode==='setup-fields') await details();
      await page.locator('#id_name').fill('Optional Rows Loan revised');
      await page.locator('#id_name').blur();
      await expect(page.locator('[data-save-feedback]')).toHaveText('Saved');
      await expect(page.locator('[data-outstanding]')).toHaveText('1 thing left');
      await expect(page.locator('[data-outstanding-items]')).toContainText('Documents');
      if(mode==='setup-fields') await details();
      await page.locator('[data-outstanding-items] a').click();
      await expect(page).toHaveURL(/\/documents\/$/);
      await page.screenshot({path:path.join(output,`${mode}-remaining-task-390.png`),fullPage:true});
      return;
    }
    await page.goto(origin+'/origination/');
    await page.locator('[data-application-open]').first().click();
    await expect(page.locator('.editor-document-actions > #origination-remove + #origination-restart-laf')).toHaveCount(1);
    await expect(page.locator('#origination-remove')).toHaveText('');
    await page.locator('#origination-section-picker').click();
    await page.locator('[data-section-index]').filter({hasText:'Product requirements'}).click();
    const borrower=page.locator('[data-product-wrap="requirement:borrower_id_copy"]');
    await expect(borrower).toHaveCount(1);
    await expect(borrower.getByRole('button',{name:'Camera',exact:true})).toBeVisible();
    await expect(borrower).toContainText('Upload');
    const saved=page.waitForResponse(r=>r.url().includes('/requirements/borrower_id_copy/evidence/')&&r.request().method()==='POST');
    await borrower.locator('[data-id-upload]').setInputFiles([path.join(output,'synthetic-id.jpg'),path.join(output,'synthetic-id.pdf')]);
    expect((await saved).status()).toBe(201);
    await expect(borrower.locator('.evidence-row.status-uploaded')).toHaveCount(1);
    await borrower.getByRole('button',{name:'Camera',exact:true}).click();
    for(let i=0;i<2;i++){await expect(page.locator('#evidence-camera-capture')).toBeEnabled();await page.locator('#evidence-camera-capture').click();await expect(page.locator('#identity-captured-photos img')).toHaveCount(i+1);}
    await page.locator('[data-id-retake="0"]').click();await page.locator('#evidence-camera-capture').click();
    await expect(page.locator('#identity-captured-photos img')).toHaveCount(2);
    const saveBox=await page.locator('#identity-camera-save').boundingBox();expect(saveBox.y+saveBox.height).toBeLessThan(844);
    await page.screenshot({path:path.join(output,'camera-390.png'),fullPage:true});
    const captured=page.waitForResponse(r=>r.url().includes('/requirements/borrower_id_copy/evidence/')&&r.request().method()==='POST');
    await page.locator('#identity-camera-save').click();expect((await captured).status()).toBe(201);
    await expect(page.locator('.camera-capture-dialog')).toHaveCount(0);
    expect(await page.evaluate(()=>__streams.every(s=>s.getTracks().every(t=>t.readyState==='ended')))).toBe(true);
    for(const width of [390,1280]){await page.setViewportSize({width,height:900});await page.screenshot({path:path.join(output,`requirements-${width}.png`),fullPage:true});}
    await page.locator('#origination-remove').click();await expect(page.locator('#origination-invalidation-reason')).toHaveCount(0);
    const deleted=page.waitForResponse(r=>r.url().endsWith('/delete-draft/'));
    await page.locator('#origination-removal-confirm').click();expect((await deleted).status()).toBe(200);
    await expect(page.locator('[data-application-open]')).toHaveCount(0);
    expect(errors).toEqual([]);console.log('PASS: real-shell mixed upload, continuous camera, replacement, preview, and unsigned deletion.');
  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
