/* Manual Playwright capture of the existing, isolated Portal. No test runner. */
const {chromium}=require('playwright');
const fs=require('node:fs');
const path=require('node:path');
const root=path.resolve(__dirname,'../../../..');
const destination=path.join(__dirname,'assets','before');
const origin='http://127.0.0.1:8777';
fs.mkdirSync(destination,{recursive:true});
(async()=>{
 const browser=await chromium.launch();const sessions=new Map();const observations={};
 async function open(role,route,width=390){
  let session=sessions.get(role);
  if(!session){
   const context=await browser.newContext({viewport:{width,height:844}});
   const fixture=await(await context.request.get(origin+'/_review/fixture?role='+role)).json();
   await context.setExtraHTTPHeaders({'X-Telegram-Init-Data':fixture.init_data});
   await context.addInitScript(initData=>{window.Telegram={WebApp:{initData,colorScheme:'light',themeParams:{},ready(){},expand(){},onEvent(){},offEvent(){},enableClosingConfirmation(){},disableClosingConfirmation(){},disableVerticalSwipes(){},BackButton:{show(){},hide(){},onClick(){},offClick(){}},MainButton:{show(){},hide(){},setParams(){},onClick(){},offClick(){}},HapticFeedback:{notificationOccurred(){},impactOccurred(){},selectionChanged(){}}}};},fixture.init_data);
   await context.route('**/*',route=>{
    const url=new URL(route.request().url());
    if(url.hostname==='127.0.0.1')return route.continue();
    if(url.hostname==='telegram.org')return route.fulfill({contentType:'application/javascript',body:'/* Local bridge. */'});
    if(['data:','blob:'].includes(url.protocol))return route.continue();
    return route.abort();
   });
   session={context,page:await context.newPage(),fixture};sessions.set(role,session);
   session.page.setDefaultTimeout(15000);
  }
  await session.page.setViewportSize({width,height:844});await session.page.goto(origin+route);await session.page.waitForTimeout(1300);
  return session;
 }
 async function capture(id,session,extra={}){
  const p=session.page;await p.waitForTimeout(350);
  await p.screenshot({path:path.join(destination,id+'.png'),animations:'disabled'});
  observations[id]={role:session.fixture.role,route:p.url().replace(origin,''),viewport:p.viewportSize(),captured_at:new Date().toISOString(),text:(await p.locator('body').innerText()).slice(0,14000),...extra};
  fs.writeFileSync(path.join(__dirname,'baseline-context.json'),JSON.stringify(observations,null,2)+'\n');
  console.log('Captured '+id);
 }
 try{
  let s=await open('JBL_OFFICER','/portal/s/jbl/');let p=s.page;
  await p.locator('[data-portal-queue-search="jbl"]').fill('972100');await p.locator('.farmer-card:visible').first().waitFor();await p.waitForTimeout(650);
  const cards=await p.locator('.farmer-card:visible').evaluateAll(nodes=>nodes.map(n=>({id:n.dataset.farmerId,text:n.innerText})));
  await capture('shell',s,{cards});await capture('queue',s,{cards});
  await p.locator('.farmer-card:visible').first().click();await p.locator('#sheet-overlay.open').waitFor();await p.waitForTimeout(600);
  const formFields=await p.locator('#sheet-form input,#sheet-form select,#sheet-form textarea').evaluateAll(nodes=>nodes.map(n=>({id:n.id,value:n.value,type:n.type,options:n.options?Array.from(n.options).map(o=>({value:o.value,label:o.label})):undefined})));
  await capture('visit',s,{formFields,caseId:cards[0].id});
  s=await open('CREDIT_ANALYST','/portal/s/credit/');p=s.page;
  if(await p.locator('#sheet-back').isVisible())await p.locator('#sheet-back').click();
  await p.locator('.farmer-card:visible').first().waitFor();await p.locator('.farmer-card:visible').first().click();await p.locator('#credit-decision').selectOption('Rejected');await p.waitForTimeout(300);
  const credit=await p.locator('#sheet-form input,#sheet-form select,#sheet-form textarea').evaluateAll(nodes=>nodes.map(n=>({id:n.id,value:n.value,options:n.options?Array.from(n.options).map(o=>({value:o.value,label:o.label})):undefined})));
  const reasons=credit.find(f=>f.id==='credit-reason-code')?.options||[];const other=reasons.find(o=>/other/i.test(o.label));
  if(other)await p.locator('#credit-reason-code').selectOption(other.value);
  await capture('credit',s,{formFields:credit});
  s=await open('OPERATIONS_ADMIN','/portal/s/deferred/');p=s.page;
  const caseId=s.fixture.cohorts.expired_credit[0];
  const farmer=await p.evaluate(async id=>(await(await fetch('/api/portal/farmers/'+id+'/')).json()).farmer,caseId);
  await p.locator('[data-portal-queue-search="deferred"]').fill(farmer.national_id);await p.locator('.farmer-card[data-farmer-id="'+caseId+'"]').waitFor();await p.locator('.farmer-card[data-farmer-id="'+caseId+'"]').click();await p.locator('#sheet-overlay.open').waitFor();await p.waitForTimeout(600);
  await capture('revisit',s,{farmer:{id:farmer.id,name:farmer.customer_name,national_id:farmer.national_id,phone:farmer.primary_phone,deferred_until:farmer.deferred_until}});
  s=await open('IT','/portal/s/history/',1280);await s.page.waitForTimeout(1500);await capture('history-desktop',s);
  s=await open('IT','/portal/s/performance/');await s.page.waitForTimeout(1700);await capture('performance',s);
  s=await open('OPERATIONS_ADMIN','/portal/s/invoices/e95f9d22-045e-43af-a86a-8967b15f4ebc/');p=s.page;
  await p.locator('.invoice-name-change-replacement').waitFor();await p.locator('.invoice-name-change-replacement').click();await p.locator('.replacement-candidate-list').waitFor();await p.waitForTimeout(1500);
  await capture('replacement',s,{candidates:await p.locator('.replacement-candidate-list').innerText()});
 }finally{await browser.close();}
})();
