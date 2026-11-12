'use strict';
const fs=require('node:fs');
const {test,expect}=require('playwright/test');
const configPath=process.env.COMPLAINT_UI_REVIEW_CONFIG;
const cfg=configPath?JSON.parse(fs.readFileSync(configPath,'utf8')):null;
test.skip(!cfg,'Requires the isolated signed synthetic Complaints UI review host.');
async function setup(page,context,width){
 expect(['127.0.0.1','localhost']).toContain(new URL(cfg.origin).hostname);
 await page.setViewportSize({width,height:900});
 await context.route(/^https?:\/\//,r=>new URL(r.request().url()).origin===cfg.origin?r.continue():r.abort());
 await context.addInitScript(proof=>{window.Telegram={WebApp:{initData:proof,colorScheme:'light',themeParams:{},ready(){},expand(){},onEvent(){},offEvent(){},BackButton:{show(){},hide(){},onClick(){},offClick(){}},MainButton:{hide(){},onClick(){},offClick(){}}}};},cfg.initData);
}
for(const width of [320,390,1280])test(`Telegram complaint correction uses paired fields and Nairobi pickers at ${width}`,async({page,context},info)=>{
 await setup(page,context,width);await page.goto(cfg.origin+'/complaints/?group_id='+cfg.telegramGroup);
 await page.locator('[data-status="resolved"]').click();await page.locator('#caseList .case-row').first().click();
 await page.locator('#complaint-correction summary').click();
 await expect(page.locator('#complaint-correction summary')).toHaveText('');
 await expect(page.locator('#complaint-correction summary svg')).toBeVisible();
 const form=page.locator('.complaint-correction-form');
 expect(Math.abs((await form.boundingBox()).width-(await page.locator('.case-title').boundingBox()).width)).toBeLessThan(2);
 await expect(form.locator('[name="timestamp"]')).toHaveAttribute('type','datetime-local');
 await expect(form.locator('[name="date_resolved"]')).toHaveAttribute('type','datetime-local');
 const boxes=await Promise.all(['customer_id','customer_phone','complaint_description'].map(name=>form.locator(`[name="${name}"]`).boundingBox()));
 expect(Math.abs(boxes[0].y-boxes[1].y)).toBeLessThan(2);expect(boxes[2].width).toBeGreaterThan(boxes[0].width*1.8);
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await page.screenshot({path:info.outputPath('complaint-correction-'+width+'.png'),fullPage:true,animations:'disabled'});
 if(width===390){
  const resolved=form.locator('[name="date_resolved"]');
  const original=await resolved.evaluate(input=>input.dataset.originalValue);
  await form.locator('[name="timestamp"]').fill('2026-11-01T12:30');await form.locator('[name="village"]').fill('Synthetic reviewed landmark '+Date.now());
  const saved=page.waitForResponse(r=>r.url().endsWith('/correct/'));
  await form.getByRole('button',{name:'Save correction'}).click();const response=await saved;expect(response.status()).toBe(200);
  const body=response.request().postDataJSON();expect(body.timestamp).toBe('2026-11-01T12:30+03:00');expect(body.date_resolved.startsWith(original)).toBe(true);
  await page.locator('#detailBackBtn').click();await page.locator('#openComplaintQueueFilters').click();
  await page.locator('#complaintQueueFilters [name="order"]').selectOption('newest');
  const refresh=page.waitForResponse(r=>r.url().endsWith('/api/complaints/cases/')&&r.request().postDataJSON()?.order==='newest');
  await page.getByRole('button',{name:'Apply',exact:true}).click();const ordered=await refresh;expect(ordered.request().postDataJSON().order).toBe('newest');expect(ordered.status()).toBe(200);
  const newest=(await ordered.json()).cases.map(row=>row.case_id);
  await page.locator('#openComplaintQueueFilters').click();await expect(page.locator('#complaintQueueFilters [name="order"]')).toHaveValue('newest');
  await page.locator('#complaintQueueFilters [name="order"]').selectOption('oldest');const reversed=page.waitForResponse(r=>r.url().endsWith('/api/complaints/cases/')&&r.request().postDataJSON()?.order==='oldest');
  await page.getByRole('button',{name:'Apply',exact:true}).click();expect((await(await reversed).json()).cases.map(row=>row.case_id)).toEqual([...newest].reverse());
 }
});
for(const width of [320,390,1280])test(`Browser complaint correction and filters align at ${width}`,async({page,context},info)=>{
 await setup(page,context,width);await page.goto(cfg.origin+'/staff/app/complaints/?workspace='+cfg.group);
 if(width===1280)await page.getByRole('button',{name:'Switch to dark mode',exact:true}).click();
 await page.getByRole('button',{name:'Filters',exact:true}).click();
 const filter=page.getByRole('dialog',{name:'Filter complaints',exact:true});await filter.getByLabel('Sort by').click();await filter.getByRole('option',{name:'Oldest first',exact:true}).click();await filter.getByRole('button',{name:'Done',exact:true}).click();
 await expect(page.getByLabel('Queue order')).toHaveValue('oldest');
 await page.getByText('Synthetic Complaint 0',{exact:true}).first().click();
 await page.getByRole('button',{name:'Edit complaint fields',exact:true}).click();
 const dialog=page.getByRole('dialog',{name:'Edit Complaint',exact:true});await expect(dialog).toBeVisible();
 expect((await page.getByRole('button',{name:'Edit complaint fields',exact:true}).boundingBox()).width).toBeLessThanOrEqual(40);
 await expect(dialog.getByLabel('Reported Date / Time (EAT)',{exact:true})).toHaveAttribute('type','datetime-local');
 const boxes=await Promise.all(['National ID','Primary Phone','Description'].map(label=>dialog.getByLabel(label,{exact:true}).boundingBox()));
 expect(Math.abs(boxes[0].y-boxes[1].y)).toBeLessThan(2);expect(boxes[2].width).toBeGreaterThan(boxes[0].width*1.8);
 await page.screenshot({path:info.outputPath('browser-correction-'+width+'.png'),fullPage:true,animations:'disabled'});
 await dialog.getByLabel('Resolved Date / Time (EAT)',{exact:true}).scrollIntoViewIfNeeded();
 await page.screenshot({path:info.outputPath('browser-date-pickers-'+width+'.png'),fullPage:true,animations:'disabled'});
 if(width===390){
  await dialog.getByLabel('Reported Date / Time (EAT)',{exact:true}).fill('2026-11-01T13:45');await dialog.getByLabel('Village / Landmark',{exact:true}).fill('Synthetic browser reviewed landmark');
  const saved=page.waitForResponse(r=>r.url().endsWith('/correct/'));await dialog.getByRole('button',{name:'Save changes',exact:true}).click();const response=await saved;expect(response.status()).toBe(200);expect(response.request().postData()).toContain('2026-11-01T13:45+03:00');
 }
});

test('Browser attachment opens its existing thumbnail while the full image is delayed',async({page,context},info)=>{
 await setup(page,context,390);await page.goto(cfg.origin+'/staff/app/complaints/?workspace='+cfg.group);
 await page.getByText('Synthetic Complaint 2',{exact:true}).first().click();
 const tile=page.locator('[data-stitch="evidence-tile"]').first();await tile.scrollIntoViewIfNeeded();
 const thumbnail=tile.getByRole('img');await expect(thumbnail).toBeVisible();const source=await thumbnail.getAttribute('src');
 let release;const pending=new Promise(resolve=>{release=resolve;});
 await page.route('**/evidence/**/preview/',async route=>{if(!route.request().postDataJSON()?.thumbnail)await pending;await route.continue();});
 try{
  await tile.getByRole('button',{name:'Preview Synthetic photo.jpg',exact:true}).click();
  const dialog=page.getByRole('dialog',{name:'Synthetic photo.jpg',exact:true});
  await expect(dialog.getByRole('img')).toHaveAttribute('src',source,{timeout:1000});
  await expect(dialog.getByRole('img')).toBeVisible();
  await expect(dialog.getByText('Loading full-size preview...',{exact:true})).toBeVisible();
  await page.screenshot({path:info.outputPath('thumbnail-before-full-image.png'),animations:'disabled'});
  release();await expect(dialog.getByText('Loading full-size preview...',{exact:true})).toBeHidden();
 }finally{release();}
});
