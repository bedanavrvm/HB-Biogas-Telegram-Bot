'use strict';
const fs = require('node:fs');
const path = require('node:path');
const {test, expect} = require('playwright/test');
const {mountPortalShell} = require('./fixtures/portal_shell');
const root = path.resolve(__dirname, '../..');
const asset = name => path.join(root, 'core/static/miniapp', name);
const templates = {
  portal:['core/templates/portal/portal.html','portal-recovery'],
  tat:['core/templates/tat_tracker/app.html','tatRecovery'],
  complaints:['core/templates/complaint_cases/app.html','complaintRecovery'],
  origination:['origination/templates/loan_origination/app.html','origination-recovery'],
};
async function mount(page, app, width=390, dark=false, portalVariant=false) {
  await page.setViewportSize({width,height:740});
  const [file,id] = templates[app];
  const template = fs.readFileSync(path.join(root,file),'utf8');
  const host = template.match(new RegExp(`<section id="${id}"[^>]*><\\/section>`))[0];
  if(app==='portal') await mountPortalShell(page, `<div id="portal-screen"><section id="page-settings" class="page active">${host}</section></div>`);
  else {
    await page.route(/^https?:\/\//, route=>route.abort());
    const mainClass = app==='origination'?'origination-shell':app==='tat'?'tat-app':'complaint-app';
    const bodyClass = template.match(/<body[^>]*class="([^"]+)"/)?.[1] || 'workflow-standard';
    await page.setContent(`<body class="${bodyClass}"><main class="${mainClass}">${host}</main></body>`);
    for (const match of template.matchAll(/<link[^>]+static '([^']+\.css)'/g)) {
      const file = [path.join(root,'core/static',match[1]),path.join(root,'origination/static',match[1])].find(fs.existsSync);
      await page.addStyleTag({content:fs.readFileSync(file,'utf8').replace(/@import\s+url\([^)]*\)\s*;/g,'')});
    }
  }
  await page.addScriptTag({path:asset('miniapp_recovery.js')});
  await page.evaluate(({id,dark,portalVariant})=>{
    if(dark) {
      document.documentElement.dataset.miniappColorScheme='dark';
      for(const [key,value] of Object.entries({'bg-color':'#111827','secondary-bg-color':'#1f2937','text-color':'#f9fafb','hint-color':'#cbd5e1','button-color':'#83baff'})) document.documentElement.style.setProperty(`--tg-theme-${key}`,value);
      document.body.style.background='#111827';
    }
    window.repairs=[]; window.notices=[];
    window.fixture = page => ({items:Array.from({length:page===1?10:2},(_,i)=>({key:String((page-1)*10+i),title:'Case Sheet update',detail:'Training applicant · Case changes are saved.',status:'Needs review',reference:'SYNTHETIC-SUPPORT-REF',steps:['Ask your app administrator to check Sheet access.','Do not submit the saved case again.'],action:{label:'Retry sync',endpoint:'/api/training/retry/',payload:{dispatch_id:String(i)},confirmation:'Retry this Sheet update? No case will be submitted again.'}})),pagination:{page,pages:2,total:12}});
    window.testRecovery=window.MiniAppRecovery.mount(document.getElementById(id),{
      variant:portalVariant?'portal':undefined,
      prefix:'/api/training/',load:async page=>window.fixture(page),
      request:async (endpoint,payload)=>{window.repairs.push({endpoint,payload});if(window.retryThrows)throw new Error('Connection lost. Check status.');return {ok:true,data:window.retryStillFailed?{ok:true,case:{sync_status:'failed'}}:{ok:true,status:'pending'}};},
      notify:(message,tone)=>window.notices.push({message,tone}),
    });
  },{id,dark,portalVariant});
  await expect(page.locator('.recovery-row')).toHaveCount(10);
}

for(const dark of [false,true])test(`Portal status overview explains all pages and never masks an outage ${dark?'dark':'light'}`,async({page},info)=>{
  await mount(page,'portal',390,dark,true);
  await page.evaluate(()=>{const fixture=window.fixture;window.fixture=page=>({...fixture(page),summary:{waiting:9,processing:1,needs_attention:2}});return testRecovery.refresh();});
  await expect(page.locator('.portal-recovery-summary')).toContainText('9Waiting1Processing2Needs attention');
  await expect(page.locator('.recovery-details').first()).not.toHaveAttribute('open');
  await page.locator('.recovery-details summary').first().click();
  await expect(page.locator('.recovery-details').first()).toContainText('Do not submit the saved case again.');
  await page.screenshot({path:info.outputPath(`portal-status-${dark?'dark':'light'}.png`),fullPage:true});
  await page.getByRole('button',{name:'Next status page'}).click();
  await expect(page.locator('.recovery-row')).toHaveCount(2);
  await expect(page.locator('.portal-recovery-summary')).toContainText('9Waiting1Processing2Needs attention');
  await page.evaluate(()=>{window.fixture=()=>{throw new Error('Synthetic status outage');};return testRecovery.refresh();});
  await expect(page.locator('[role="alert"]')).toHaveText('Synthetic status outage');
  await expect(page.locator('.portal-recovery-summary')).toHaveCount(0);
  await expect(page.getByRole('button',{name:'Try again',exact:true})).toBeVisible();
});

for(const app of Object.keys(templates)) for(const width of [320,430,1280]) for(const dark of [false,true]) {
  test(`${app} recovery ${width}px ${dark?'dark':'light'}`,async({page})=>{
    await mount(page,app,width,dark);
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    expect(await page.locator('.recovery-list').evaluate(n=>n.scrollHeight>n.clientHeight)).toBe(true);
    expect((await page.locator('.miniapp-recovery header button').boundingBox()).width).toBe(44);
    const heading=await page.locator('.miniapp-recovery>header').boundingBox();
    const refresh=await page.locator('.miniapp-recovery header button').boundingBox();
    expect(Math.abs(heading.x+heading.width-refresh.x-refresh.width)).toBeLessThan(1);
    await page.getByRole('button',{name:'Next status page'}).click();
    await expect(page.locator('.recovery-row')).toHaveCount(2);
    await page.screenshot({path:`test-results/recovery-${app}-${width}-${dark?'dark':'light'}.png`,fullPage:true});
    await page.locator('[data-guide]').first().click();
    await expect(page.getByRole('dialog')).toContainText('SYNTHETIC-SUPPORT-REF');
    await expect(page.getByRole('button',{name:'Copy support reference'})).toBeVisible();
    await page.getByRole('button',{name:'Close',exact:true}).last().click();
    await page.locator('[data-repair]').first().click();
    await expect(page.getByRole('dialog')).toContainText('No case will be submitted again.');
    await page.getByRole('button',{name:'Cancel',exact:true}).click();
    expect(await page.evaluate(()=>window.repairs.length)).toBe(0);
  });
}

test('Retry is single-flight and a failed sync is never labelled successful',async({page})=>{
  await mount(page,'portal');
  await page.evaluate(()=>window.retryStillFailed=true);
  await page.locator('[data-repair]').first().click();
  await page.getByRole('dialog').getByRole('button',{name:'Retry sync',exact:true}).click();
  await expect.poll(()=>page.evaluate(()=>window.repairs.length)).toBe(1);
  await expect.poll(()=>page.evaluate(()=>window.notices.at(-1)?.tone)).toBe('error');
  expect(await page.evaluate(()=>window.notices.at(-1).message)).toContain('still needs attention');
  await page.evaluate(()=>{window.retryStillFailed=false;window.retryThrows=true;});
  await page.locator('[data-repair]').first().click();
  await page.getByRole('dialog').getByRole('button',{name:'Retry sync',exact:true}).click();
  await expect.poll(()=>page.evaluate(()=>window.repairs.length)).toBe(2);
  await expect(page.locator('[data-repair]').first()).toBeEnabled();
  expect(await page.evaluate(()=>window.notices.at(-1).message)).toContain('Connection lost');
});

test('System readiness has concrete repair guidance and a working status check', async({page})=>{
  await mount(page,'portal');
  const source=fs.readFileSync(asset('portal.js'),'utf8');
  const health=source.slice(source.indexOf('  function renderPortalHealth('),source.indexOf('  function renderPortalDelegations('));
  await page.addScriptTag({content:`const el=id=>document.getElementById(id);const escapeHtml=value=>String(value);${health}`});
  await page.evaluate(()=>{
    const target=document.createElement('section');target.id='test-health';document.body.append(target);
    window.statusChecks=0;const old=window.fixture;window.fixture=page=>{window.statusChecks++;return old(page);};
    renderPortalHealth(target,{status:'degraded',checks:{payment_template:'missing',order_storage:'degraded'},due_order_retries:1});
  });
  await expect(page.locator('#test-health')).toContainText('activate a validated payment template');
  await page.locator('#test-health').getByRole('button',{name:'Check app status',exact:true}).click();
  await expect.poll(()=>page.evaluate(()=>window.statusChecks)).toBe(1);
});
