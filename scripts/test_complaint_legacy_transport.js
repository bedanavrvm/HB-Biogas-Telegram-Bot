'use strict';
// Synthetic proof arrives on stdin; every browser request stays on loopback.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require('playwright');
async function main(){
  let text='';for await(const chunk of process.stdin)text+=chunk;const input=JSON.parse(text),origin=new URL(input.origin);
  assert.ok(['127.0.0.1','localhost'].includes(origin.hostname));
  const output=path.resolve('test-results/complaints-legacy-browser');fs.mkdirSync(output,{recursive:true});
  const browser=await chromium.launch({headless:true}),errors=[];let captures=0;
  const context=await browser.newContext({viewport:{width:1280,height:850}}),page=await context.newPage();page.setDefaultTimeout(18000);
  const limit=async(ctx)=>ctx.route('**/*',route=>new URL(route.request().url()).origin===origin.origin?route.continue():route.abort());
  await limit(context);
  page.on('pageerror',e=>errors.push(e.message));
  await context.addInitScript(proof=>{window.Telegram={WebApp:{initData:proof,colorScheme:'light',themeParams:{},ready(){},expand(){},onEvent(){},MainButton:{hide(){},show(){},setText(){},onClick(){},offClick(){}},BackButton:{hide(){},show(){},onClick(){},offClick(){}}}};},input.initData);
  await context.setExtraHTTPHeaders({'X-Telegram-Init-Data':input.initData});
  const snap=async(name,scope=page)=>{await page.screenshot({path:path.join(output,name+'.png'),fullPage:true});captures++;const width=await scope.locator('body').evaluate(()=>({actual:document.documentElement.scrollWidth,view:innerWidth}));assert.ok(width.actual<=width.view,JSON.stringify(width));};
  const idle=scope=>scope.locator('[data-action=pause]').waitFor({state:'hidden'});
  async function upload(scope,filename){await scope.locator('[data-source]').evaluate(n=>n.open=true);await scope.locator('input[type=file]').setInputFiles(filename);await scope.getByRole('button',{name:'Upload and preview mapping'}).click();await scope.locator('[data-action=stage]').waitFor();await idle(scope);}
  async function stage(scope){await scope.locator('[data-action=stage]').click();await scope.locator('[data-review]').waitFor();await idle(scope);}
  try{
    await page.goto(origin.origin+'/complaints/?group_id='+input.group);
    await page.locator('#complaintLegacyImportBtn').waitFor({state:'attached'});
    // Use the real Settings entry, retaining the signed launch in the parent only.
    const settings=page.locator('#settingsBtn');if(await settings.count())await settings.click();
    else await page.getByRole('button',{name:/settings/i}).first().click();
    await page.locator('#complaintLegacyImportBtn').click();
    const frame=page.frameLocator('#complaint-legacy-frame');
    await frame.locator('[data-workspace]').filter({hasText:'Synthetic Complaints'}).waitFor();
    assert.ok(!new URL(await page.locator('#complaint-legacy-frame').getAttribute('src'),origin).search.includes('initData'));
    await upload(frame,input.workbook);await snap('01-column-mapping',frame);await stage(frame);
    await frame.getByRole('checkbox',{name:'Approve source row 2',exact:true}).check();await idle(frame);
    await page.locator('#complaint-legacy-frame').evaluate(f=>f.contentWindow.location.reload());
    await frame.locator('[data-saved] option').nth(1).waitFor({state:'attached'});
    const saved=await frame.locator('[data-saved] option').nth(1).getAttribute('value');await frame.locator('[data-saved]').selectOption(saved);await idle(frame);
    assert.equal(await frame.getByRole('checkbox',{name:'Approve source row 2',exact:true}).isChecked(),true);
    await snap('02-table-review',frame);
    await frame.getByRole('button',{name:'Compare source row 2',exact:true}).click();await snap('03-original-versus-proposed',frame);await frame.getByRole('button',{name:'Done',exact:true}).click();
    await frame.locator('[data-filter]').selectOption('blocked');await idle(frame);
    assert.equal(await frame.getByRole('checkbox',{name:'Approve source row 63',exact:true}).isDisabled(),true);await snap('04-blocked-status-and-date',frame);
    await frame.locator('[data-filter]').selectOption('all');await idle(frame);
    await frame.locator('[data-action=next]').click();await idle(frame);assert.match(await frame.locator('[data-page]').innerText(),/51.*62/);
    await frame.getByRole('button',{name:'Cards',exact:true}).click();await idle(frame);
    assert.equal(await frame.locator('[data-cards] article').filter({hasText:'SYNTHETIC BLOCKED'}).getByRole('checkbox').isDisabled(),true);
    for(const width of [390,320]){await page.setViewportSize({width,height:844});await snap('05-cards-mobile-'+width,frame);}
    await frame.locator('.import-feedback').evaluate(n=>window.scrollTo(0,document.documentElement.scrollHeight));
    const sticky=await frame.locator('.import-feedback').boundingBox();assert.ok(sticky.y>=-1&&sticky.y<100,'Progress stays inside the viewport');
    await page.emulateMedia({colorScheme:'dark'});await snap('06-cards-dark-mobile',frame);await page.emulateMedia({colorScheme:'light'});
    await page.setViewportSize({width:1280,height:850});await frame.locator('[data-action=approve_all]').click();await idle(frame);
    await frame.locator('[data-action=commit]').click();await frame.locator('[data-confirm]').waitFor();await snap('07-save-confirmation',frame);
    await frame.getByRole('button',{name:'Cancel',exact:true}).click();await idle(frame);
    await frame.locator('[data-action=commit]').click();await frame.getByRole('button',{name:'Confirm reviewed action'}).click();await idle(frame);
    assert.match(await frame.locator('[data-feedback]').innerText(),/61 imported/);await snap('08-saved-before-publication',frame);
    await frame.locator('[data-action=publish]').click();await frame.getByRole('button',{name:'Confirm reviewed action'}).click();await idle(frame);
    assert.match(await frame.locator('[data-feedback]').innerText(),/61 queued/);await snap('09-publication-queued',frame);
    assert.equal(await page.evaluate(proof=>[...Object.values(localStorage),...Object.values(sessionStorage)].some(value=>value.includes(proof)),input.initData),false);
    const native=await browser.newContext({viewport:{width:1280,height:850}});await limit(native);const n=await native.newPage();n.setDefaultTimeout(18000);n.on('pageerror',e=>errors.push(e.message));n.on('response',r=>{if(r.status()>=500)errors.push('Server error: '+new URL(r.url()).pathname);});
    const base=`${origin.origin}/api/staff/complaints/operations/v1/groups/${input.key}/legacy-import/`;
    assert.equal((await native.request.get(base)).status(),401);
    async function post(url,data){const session=await(await native.request.get(origin.origin+'/api/staff/auth/v1/session/')).json();return native.request.post(origin.origin+url,{headers:{'X-CSRFToken':session.csrf_token,Origin:origin.origin},data});}
    assert.equal((await post('/api/staff/auth/v1/login/',{username:input.username,password:input.password})).status(),401);
    assert.equal((await native.request.get(base)).status(),401);
    const mfa=await post('/api/staff/auth/v1/mfa/',{code:input.code});assert.equal(mfa.status(),200,await mfa.text());
    assert.equal((await native.request.post(base,{data:{command:'index'}})).status(),403);
    assert.equal((await native.request.get(base.replace('/'+input.key+'/','/'+input.other+'/'))).status(),403);
    await n.goto(origin.origin+'/staff/app/complaints/?workspace='+input.key);
    await n.getByRole('button',{name:'Workspace tools',exact:true}).click();await n.getByRole('menuitem',{name:'Legacy import',exact:true}).click();
    await n.getByRole('heading',{name:'Legacy import',exact:true}).waitFor();await idle(n);
    assert.equal(await n.evaluate(()=>typeof window.Telegram),'undefined');
    const download=n.waitForEvent('download');await n.getByRole('button',{name:'Download template',exact:true}).click();assert.match((await download).suggestedFilename(),/Legacy Import Template.xlsx/);await idle(n);
    await upload(n,input.nativeWorkbook);await stage(n);await n.locator('[data-action=approve_all]').click();await idle(n);
    await n.locator('[data-action=commit]').click();await n.getByRole('button',{name:'Confirm reviewed action'}).click();await idle(n);
    assert.match(await n.locator('[data-feedback]').innerText(),/1 imported/);
    await n.screenshot({path:path.join(output,'10-native-mfa-import.png'),fullPage:true});captures++;
    await n.getByRole('link',{name:/Complaints/}).click();await n.getByRole('button',{name:'Workspace tools',exact:true}).waitFor();assert.equal(new URL(n.url()).searchParams.get('workspace'),String(input.key));
    const queue=await(await post(`/api/staff/complaints/operations/v1/groups/${input.key}/cases/`,{q:'SYNTHETIC 1',status:'all'})).json();
    const closed=queue.items.find(row=>row.status==='CLOSED');assert.ok(closed);
    const recovered=n.waitForResponse(r=>new URL(r.url()).pathname.endsWith('/recovery/'));
    await n.goto(origin.origin+`/staff/app/complaints/cases/${closed.key}/?workspace=${input.key}`);await recovered;
    await n.getByText('Legacy workbook; historical details may be incomplete',{exact:false}).first().waitFor();
    await n.getByText('Closure date unknown',{exact:false}).first().waitFor();
    await n.getByRole('tab',{name:/History/}).click();await n.getByText('Historical complaint imported',{exact:true}).waitFor();
    await n.screenshot({path:path.join(output,'11-imported-case-history.png'),fullPage:true});captures++;
    assert.equal(errors.length,0,errors.join('\n'));
    fs.writeFileSync(path.join(output,'results.json'),JSON.stringify({passed:true,captures,channels:['signed Telegram','native cookie/password/MFA/CSRF'],cases:62,queued:61},null,2));
    process.stdout.write(JSON.stringify({passed:true,captures}));
  }catch(error){await page.screenshot({path:path.join(output,'failure.png'),fullPage:true});throw error;}
  finally{await browser.close();}
}
main().catch(error=>{console.error(error.stack);process.exitCode=1;});
