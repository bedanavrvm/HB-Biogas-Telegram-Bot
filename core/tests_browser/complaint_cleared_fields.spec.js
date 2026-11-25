'use strict';
const {test,expect}=require('playwright/test');
const fs=require('node:fs'),assert=require('node:assert/strict');
const config=process.env.COMPLAINT_CLEAR_REVIEW_CONFIG;
const cfg=config?JSON.parse(fs.readFileSync(config,'utf8')):null;
test.skip(!cfg,'Requires an isolated signed synthetic Django/PostgreSQL review host.');
test('native corrections retain cleared-value history and re-sync both Mini Apps',async({page:p,context:ctx},info)=>{
 assert(['127.0.0.1','localhost'].includes(new URL(cfg.origin).hostname));
 const errors=[];
 await p.setViewportSize({width:390,height:900});
 await ctx.addInitScript(proof=>{window.Telegram={WebApp:{initData:proof,colorScheme:'light',themeParams:{},ready(){},expand(){},onEvent(){},offEvent(){},BackButton:{show(){},hide(){},onClick(){},offClick(){}},MainButton:{hide(){},onClick(){},offClick(){}}}}},cfg.proof);
 await ctx.route('**/*',r=>r.request().url().startsWith(cfg.origin)||/^(data|blob):/.test(r.request().url())?r.continue():r.abort());
 p.on('pageerror',e=>errors.push(e.message));
 await p.goto(cfg.origin+'/complaints/?group_id='+cfg.group);
 await p.locator('#caseList .case-row').first().click();
 await p.locator('#complaint-correction summary').click();
 const county=p.locator('#complaint-correction select[name=county]'),sub=p.locator('#complaint-correction select[name=sub_county]');
 await p.waitForFunction(()=>document.querySelector('#complaint-correction select[name=county]')?.options.length>1);
 const originalCounty=await county.inputValue();
 const failLocations=route=>route.abort();await p.route('**/api/complaints/location-options/**',failLocations);
 await p.locator('#complaint-correction [name=village]').fill('Retain this unsaved draft');
 await county.selectOption('');
 await p.getByText('Location choices unavailable. Your edits are retained.',{exact:false}).waitFor();
 assert.equal(await p.locator('#complaint-correction [name=village]').inputValue(),'Retain this unsaved draft');
 assert.equal(await sub.inputValue(),'');
 await p.unroute('**/api/complaints/location-options/**',failLocations);
 await county.selectOption(originalCounty);
 await p.waitForFunction(()=>!document.querySelector('#complaint-correction button[type=submit]').disabled);
 if(await sub.inputValue()!=='Nakuru East'||await p.locator('#complaint-correction [name=village]').inputValue()!=='Synthetic old landmark'){
   await sub.selectOption('Nakuru East');await p.locator('#complaint-correction [name=village]').fill('Synthetic old landmark');
   const reset=p.waitForResponse(r=>r.url().endsWith('/correct/'));await p.locator('#complaint-correction button[type=submit]').click();assert.equal((await reset).status(),200);
   await p.locator('#complaint-correction summary').click();await p.waitForFunction(()=>document.querySelector('#complaint-correction select[name=sub_county]')?.options.length>1);
 }
 const date=p.locator('[data-correction-date=timestamp]');assert.match(await date.inputValue(),/^\d{2}\/\d{2}\/\d{4} \d{2}:\d{2}$/);
 const calendar=p.getByRole('button',{name:'Choose reported date / time (eat)',exact:true});
 const displayBox=await date.boundingBox(),calendarBox=await calendar.boundingBox();
 assert(Math.abs(displayBox.y-calendarBox.y)<4);assert(calendarBox.x>displayBox.x);
 assert.equal(await calendar.locator('svg rect').count(),1);
 const displayed=await date.inputValue(),original=await p.locator('#complaint-correction [name=timestamp]').inputValue();
 for(const [value,iso] of [['23/11/2026 12:30','2026-11-23T12:30'],['01/12/2026 12:30','2026-12-01T12:30']]){await date.fill(value);assert((await p.locator('#complaint-correction [name=timestamp]').inputValue()).startsWith(iso));}
 await date.fill(displayed);await p.locator('#complaint-correction [name=timestamp]').evaluate((node,value)=>node.value=value,original);
 assert.equal(await sub.inputValue(),'Nakuru East');
 await sub.selectOption('');await p.locator('#complaint-correction [name=village]').fill('');
 const saved=p.waitForResponse(r=>r.url().endsWith('/correct/'));
 await p.locator('#complaint-correction button[type=submit]').click();
 const response=await saved;assert.equal(response.status(),200,await response.text());
 const detail=await response.json();
 const changes=detail.case.updates.flatMap(row=>row.changes||[]);
 assert(changes.some(c=>c.old_value==='Synthetic old landmark'&&c.new_value===''));
 assert((await p.locator('#activityPanel').innerText()).includes('Synthetic old landmark'));
 assert((await p.locator('#activityPanel').innerText()).includes('Nakuru East'));
 for(const width of [390,1280]){await p.setViewportSize({width,height:900});await p.locator('#activityPanel').scrollIntoViewIfNeeded();await p.screenshot({path:info.outputPath('history-'+width+'.png')});}
 await p.locator('#complaint-correction summary').click();await p.locator('#complaint-correction').scrollIntoViewIfNeeded();
 for(const width of [390,1280]){await p.setViewportSize({width,height:900});await p.screenshot({path:info.outputPath('editor-'+width+'.png')});}
 const retry=p.waitForResponse(r=>r.url().endsWith('/sync-retry/'));await p.getByRole('button',{name:'Re-sync to Sheet',exact:true}).click();assert.equal((await retry).status(),200);
 await p.goto(cfg.origin+'/portal/cases/'+cfg.portal_case+'/?from=all');
 const refresh=p.waitForResponse(r=>r.url().endsWith('/publication/attempt/'));
 await p.getByRole('button',{name:'Re-sync to Sheet',exact:true}).click();assert.equal((await refresh).status(),202);
 await p.screenshot({path:info.outputPath('portal-refresh.png')});

 await p.goto(cfg.origin+'/complaints/?group_id='+cfg.group);
 await p.locator('#newCaseBtn').click();
 await p.locator('#createCaseForm [name=customer_id]').fill('99998887');
 await p.locator('[data-customer-choice]').first().click();
 await expect(p.locator('#portalCustomerSuggestions')).toBeHidden();
 await expect(p.getByRole('button',{name:'Clear Master Data selection',exact:true})).toBeVisible();
 assert((await p.locator('#createCaseForm [name=portal_source_label]').inputValue()).startsWith('JBL-'));
 await p.screenshot({path:info.outputPath('biodata-source.png')});

 assert.deepEqual(errors,[]);
});
