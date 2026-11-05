'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),{chromium}=require('playwright');
async function main(){
  let raw='';for await(const chunk of process.stdin)raw+=chunk;const input=JSON.parse(raw),origin=new URL(input.origin);
  assert.ok(['127.0.0.1','localhost'].includes(origin.hostname));
  const folder=path.resolve('test-results/complaint-customer-lookup'),browser=await chromium.launch({headless:true}),errors=[],shots=[];
  async function context(native=false){const c=await browser.newContext({viewport:{width:1280,height:900}});await c.route('**/*',r=>new URL(r.request().url()).origin===origin.origin?r.continue():r.abort());
    if(!native){await c.addInitScript(proof=>{window.Telegram={WebApp:{initData:proof,colorScheme:'light',themeParams:{},ready(){},expand(){},onEvent(){},MainButton:{hide(){},show(){},setText(){},onClick(fn){window.__tgMainClick=fn;},offClick(){}},BackButton:{hide(){},show(){},onClick(){},offClick(){}}}};},input.initData);await c.setExtraHTTPHeaders({'X-Telegram-Init-Data':input.initData});}return c;}
  const snap=async(page,name)=>{const file=name+'.png';await page.screenshot({path:path.join(folder,file),fullPage:true});shots.push(file);};
  const tg=await context(),page=await tg.newPage();let activePage=page;const lookups=[];page.setDefaultTimeout(18000);page.on('pageerror',e=>errors.push(e.message));
  try{
    await page.goto(origin.origin+'/complaints/?group_id='+input.group);await page.locator('#newCaseBtn').click();
    const form=page.locator('#createCaseForm');await form.locator('[name=complaint_description]').fill('TELEGRAM PREFILL REVIEW: preserve this description.');
    await form.locator('[name=secondary_phone]').fill('0799999999');await form.locator('[name=customer_id]').fill('90123456');
    const choices=page.locator('#portalCustomerSuggestions [data-customer-choice]');await choices.first().waitFor();assert.equal(await choices.count(),2);await snap(page,'01-telegram-matches');
    await page.setViewportSize({width:390,height:844});await snap(page,'02-telegram-mobile-matches');await page.setViewportSize({width:1280,height:900});
    await page.locator(`[data-customer-choice="${input.sourceKey}"]`).click();await page.getByText('Biodata copied from '+input.reference+'. You can edit these fields.',{exact:true}).waitFor();
    assert.equal(await form.locator('[name=customer_phone]').inputValue(),'254712345601');assert.equal(await form.locator('[name=secondary_phone]').inputValue(),'254712345602');
    assert.equal(await form.locator('[name=county]').inputValue(),input.place.county);assert.equal(await form.locator('[name=sub_county]').inputValue(),input.place.sub_county);
    assert.match(await form.locator('[name=complaint_description]').inputValue(),/preserve this description/);await snap(page,'03-telegram-filled');
    await page.locator('#createSaveState').filter({hasText:'Draft saved'}).waitFor();await page.reload();await page.locator('#newCaseBtn').click();await page.getByRole('button',{name:'Restore',exact:true}).click();
    await page.getByText('Biodata copied from '+input.reference+'. Review the restored details before submitting.',{exact:true}).waitFor();
    assert.equal(await form.locator('[name=portal_source_key]').inputValue(),input.sourceKey);assert.equal(await form.locator('[name=customer_phone]').inputValue(),'254712345601');
    await form.locator('[name=complaint_category]').selectOption({label:'Synthetic system issue'});await page.evaluate(()=>window.__tgMainClick());await page.locator('#detailView').waitFor({state:'visible'});await snap(page,'04-telegram-saved');
    const native=await context(true),n=await native.newPage();activePage=n;n.setDefaultTimeout(18000);n.on('pageerror',e=>errors.push(e.message));n.on('request',r=>{if(r.url().endsWith('/customers/suggest/'))lookups.push(r.postDataJSON());});
    async function post(url,data){const auth=await(await native.request.get(origin.origin+'/api/staff/auth/v1/session/')).json();return native.request.post(origin.origin+url,{headers:{Origin:origin.origin,'X-CSRFToken':auth.csrf_token},data});}
    const base=`/api/staff/complaints/operations/v1/groups/${input.key}/`;
    assert.equal((await native.request.post(origin.origin+base+'customers/suggest/',{data:{client_name:'SYNTHETIC'}})).status(),403);
    assert.equal((await post(base+'customers/suggest/',{client_name:'SYNTHETIC'})).status(),401);
    assert.equal((await post('/api/staff/auth/v1/login/',{username:input.username,password:input.password})).status(),401);
    assert.equal((await post('/api/staff/auth/v1/mfa/',{code:input.code})).status(),200);
    assert.equal((await native.request.post(origin.origin+base+'customers/suggest/',{data:{client_name:'SYNTHETIC'}})).status(),403);
    const ranked=await(await post(base+'customers/suggest/',{customer_id:'90888888',customer_phone:'0712345601',client_name:'SYNTHETIC ALICE'})).json();
    assert.equal(ranked.matches[0].key,input.legacyKey);assert.equal(ranked.matches[1].matched_on,'Primary phone');assert.ok(ranked.matches[1].conflicts.includes('Different entered ID'));
    await n.goto(origin.origin+'/staff/app/complaints/?workspace='+input.key);await n.getByRole('button',{name:'New complaint',exact:true}).click();
    await n.getByLabel(/^Complaint description/).fill('BROWSER PREFILL REVIEW: preserve this description.');await n.getByLabel(/^National ID/).fill('zzznomatch');
    await n.getByLabel(/^Customer name/).fill('zzznomatch');await n.getByText('No matching Portal customer. Continue entering details manually.',{exact:true}).waitFor();await snap(n,'05-native-no-match');
    await n.getByLabel(/^Customer name/).fill('SYNTHETIC ALICE');await n.getByLabel(/^National ID/).fill('90888888');
    await n.locator(`[data-customer-choice="${input.legacyKey}"]`).click();await n.getByText('Portal county: OLD COUNTY. Choose a supported county.',{exact:true}).first().waitFor();
    assert.equal(await n.getByLabel(/^Primary phone number/).inputValue(),'71234');await snap(n,'05a-native-historical-review');await n.getByRole('button',{name:'Clear Portal selection',exact:true}).click();
    assert.equal(await n.getByLabel(/^Primary phone number/).inputValue(),'71234');await n.getByLabel(/^Primary phone number/).fill('');await n.getByLabel(/^Customer name/).fill('SYNTHETIC ALICE');await n.getByLabel(/^National ID/).fill('90123456');
    await n.locator('[data-customer-choice]').first().waitFor();await n.getByLabel(/^National ID/).press('Escape');assert.equal(await n.locator('[data-customer-choice]').count(),0);
    await n.getByLabel(/^National ID/).fill('9012345');await n.locator('[data-customer-choice]').first().waitFor();await n.locator('[data-customer-choice]').first().focus();await n.keyboard.press('ArrowDown');assert.equal(await n.evaluate(()=>document.activeElement.dataset.customerChoice),await n.locator('[data-customer-choice]').nth(1).getAttribute('data-customer-choice'));await snap(n,'06-native-id-matches');
    await n.keyboard.press('Escape');assert.equal(await n.locator('[data-customer-choice]').count(),0);await n.getByRole('heading',{name:'Create complaint',exact:true}).waitFor();await n.getByLabel(/^National ID/).fill('90123456');await n.locator(`[data-customer-choice="${input.sourceKey}"]`).waitFor();
    await n.getByLabel('Choose evidence files',{exact:true}).setInputFiles({name:'preserved.pdf',mimeType:'application/pdf',buffer:Buffer.from('%PDF-1.4\nsynthetic attachment')});
    await n.locator(`[data-customer-choice="${input.sourceKey}"]`).click();await n.getByText('Biodata copied from '+input.reference+'. You can edit these fields.',{exact:true}).waitFor();
    assert.equal(await n.getByLabel(/^Primary phone number/).inputValue(),'254712345601');assert.equal(await n.getByLabel(/^Alternative phone number/).inputValue(),'254712345602');
    assert.match(await n.getByLabel(/^Complaint description/).inputValue(),/preserve this description/);
    await n.getByText('Loading location choices…',{exact:true}).waitFor({state:'hidden'});await n.getByText('Nakuru County',{exact:true}).waitFor();await n.getByText('Nakuru East',{exact:true}).waitFor();await snap(n,'07-native-filled');
    assert.equal(await n.getByRole('button',{name:'Remove preserved.pdf',exact:true}).count(),1);await n.getByRole('button',{name:'Remove preserved.pdf',exact:true}).click();
    await n.setViewportSize({width:390,height:844});await snap(n,'08-native-mobile-filled');await n.emulateMedia({colorScheme:'dark'});await snap(n,'09-native-dark-filled');await n.emulateMedia({colorScheme:'light'});await n.setViewportSize({width:1280,height:900});
    const unavailable=async route=>route.abort('failed');await n.route('**/customers/suggest/',unavailable);await n.getByLabel(/^National ID/).fill('901234');
    await n.getByText('Customer lookup unavailable. Continue manually or retry.',{exact:true}).waitFor();await snap(n,'10-native-lookup-offline');await n.unroute('**/customers/suggest/',unavailable);await n.getByRole('button',{name:'Retry customer lookup'}).click();await n.locator('[data-customer-choice]').first().waitFor();
    await n.locator(`[data-customer-choice="${input.sourceKey}"]`).click();
    await n.getByText('Biodata copied from '+input.reference+'. You can edit these fields.',{exact:true}).waitFor();
    await n.locator('#create-category').click();await n.getByRole('option',{name:'Synthetic system issue',exact:true}).click();
    const saved=n.waitForResponse(r=>r.url().endsWith('/cases/create/')&&r.request().method()==='POST');await n.getByRole('button',{name:'Submit complaint',exact:true}).click();const response=await saved;assert.equal(response.status(),201,await response.text());
    await n.getByRole('dialog').waitFor({state:'hidden'});await snap(n,'11-native-saved');
    assert.equal(errors.length,0,errors.join('\n'));fs.writeFileSync(path.join(folder,'results.json'),JSON.stringify({passed:true,shots,cases:2},null,2));console.log(JSON.stringify({passed:true,captures:shots.length}));
  }catch(error){await activePage.screenshot({path:path.join(folder,'failure.png'),fullPage:true});error.stack+='\nSynthetic lookup requests: '+JSON.stringify(lookups)+'\nPage errors: '+JSON.stringify(errors);throw error;}finally{await browser.close();}
}
main().catch(error=>{console.error(error.stack);process.exitCode=1;});
