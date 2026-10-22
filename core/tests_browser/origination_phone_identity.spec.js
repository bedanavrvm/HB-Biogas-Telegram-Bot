'use strict';
const fs = require('node:fs');
const path = require('node:path');
const {test, expect} = require('playwright/test');
const root = path.resolve(__dirname, '../..');
const shell = fs.readFileSync(path.join(root, 'origination/templates/loan_origination/app.html'), 'utf8')
  .replace(/{% static '([^']+)' %}/g, '/static/$1').replace(/{%[\s\S]*?%}/g, '')
  .replace(/<script[\s\S]*?<\/script>/g, '').replace(/<link[^>]+>/g, '');

async function boot(page, {it=true, dark=false, status='draft', failure=false, outcome='matched', pending=false}={}) {
  await page.setViewportSize({width:360,height:800});
  const id = '00000000-0000-4000-8000-000000000058';
  const checks = {allowed:true,enabled:true,environment:'sandbox',revision:1,targets:['primary','alternate'].map((target,index) => ({
    target,field_key:index ? 'applicant_other_phone' : 'applicant_phone', id_field_key:'applicant_id_number',
    subject_token:'synthetic-bound-value',can_check:true,status:'not_checked',freshness:'none',phone_suffix:'0001',id_suffix:'9001',
  }))};
  const app = {id,officer_id:1,revision:1,status,reference_number:'ORG-SYNTHETIC-PHONE',product_name:'Synthetic product',branch:'Synthetic',
    applicant_summary:{name:'Synthetic applicant',phone:'0700000001',national_id:'00099001'},
    form_payload:{applicant_id_number:'00099001',applicant_phone:'0700000001',applicant_other_phone:'0100000001'},
    form_schema:{sections:[{key:'applicant',label:'Applicant'}],fields:[
      {key:'applicant_id_number',type:'national_id',label:'Applicant National ID',section_key:'applicant'},
      {key:'applicant_phone',type:'phone',label:'Applicant phone',section_key:'applicant'},
      {key:'applicant_other_phone',type:'phone',label:'Alternative phone',section_key:'applicant'},
    ]},product_terms:{},document_packet:{documents:[]},...(it?{phone_id_checks:checks}:{})};
  const writes = [];
  await page.route('http://127.0.0.1:8158/**', async route => {
    const url = new URL(route.request().url());
    if (url.pathname === '/') return route.fulfill({contentType:'text/html',body:shell});
    if (url.pathname.endsWith('/products/')) return route.fulfill({json:{ok:true,products:[],branches:[],capabilities:{can_create:true,user_id:1}}});
    if (url.pathname.endsWith('/phone-id-checks/')) {
      if (route.request().method() === 'GET') return route.fulfill({json:{ok:true,phone_id_checks:checks}});
      const body = route.request().postDataJSON(); writes.push(body);
      if (failure) return route.fulfill({status:503,json:{ok:false,error:'Verification unavailable. This is not a mismatch.'}});
      Object.assign(checks.targets.find(item=>item.target===body.target), {
        status:pending?'checking':outcome,freshness:'current',checked_at:'2026-10-19T06:00:00Z',reusable_until:'2026-11-18T06:00:00Z',reused:!body.fresh_check,
      });
      return route.fulfill({status:pending?202:200,json:{ok:true,result:checks.targets.find(item=>item.target===body.target)}});
    }
    if (url.pathname.endsWith(`/applications/${id}/`)) {
      if (route.request().method() === 'PATCH') {
        Object.assign(app.form_payload, route.request().postDataJSON().form_payload);
        app.revision++; checks.revision=app.revision;
      }
      return route.fulfill({json:{ok:true,application:app}});
    }
    if (url.pathname.endsWith('/applications/')) return route.fulfill({json:{ok:true,applications:[app],tab_counts:{action:1,applications:1},
      status_options:[],pagination:{page:1,pages:1,total:1},capabilities:{can_create:true,user_id:1}}});
    return route.abort();
  });
  await page.goto('http://127.0.0.1:8158/');
  await page.evaluate(({dark})=>{
    window.__confirmations=[];
    window.__confirm=true;
    window.Telegram={WebApp:{initData:'synthetic-only',ready(){},expand(){},onEvent(){},
      showPopup(data,callback){window.__confirmations.push(data);callback(window.__confirm?'check':'cancel');},
      BackButton:{show(){},hide(){},onClick(){},offClick(){}}}};
    if(dark){document.documentElement.dataset.telegramTheme='dark';document.documentElement.dataset.miniappColorScheme='dark';
      for(const [key,value] of Object.entries({'bg-color':'#17201e','secondary-bg-color':'#111816','text-color':'#f4f7f5','hint-color':'#a7b5af'}))
        document.documentElement.style.setProperty(`--tg-theme-${key}`,value);}
  },{dark});
  for (const file of ['core/static/miniapp/base.css','core/static/miniapp/workflow_standard.css',
    'origination/static/miniapp/loan_origination.css','origination/static/miniapp/origination_compact.css'])
    await page.addStyleTag({content:fs.readFileSync(path.join(root,file),'utf8').replace(/^@import[^\r\n]*;\s*$/gm,'')});
  for (const file of ['core/static/miniapp/utils.js','origination/static/miniapp/origination_field_rules.js',
    'origination/static/miniapp/phone_identity_checks.js','origination/static/miniapp/loan_origination.js'])
    await page.addScriptTag({path:path.join(root,file)});
  await page.locator('.application-card').click();
  return {writes,app,checks};
}

for(const dark of [false,true]) test(`IT inline primary and alternate actions fit a phone (${dark?'dark':'light'})`,async({page},info)=>{
  const {writes}=await boot(page,{dark});
  await expect(page.getByRole('button',{name:'Check primary Applicant phone against ID'})).toBeVisible();
  await expect(page.getByRole('button',{name:'Check alternate Applicant phone against ID'})).toBeVisible();
  expect((await page.getByRole('button',{name:'Check primary Applicant phone against ID'}).boundingBox()).height).toBeGreaterThanOrEqual(44);
  await page.screenshot({path:info.outputPath(`phone-check-${dark?'dark':'light'}.png`),fullPage:true});
  await page.getByRole('button',{name:'Check primary Applicant phone against ID'}).click();
  await expect(page.locator('[data-phone-id-target=primary]')).toContainText('Registration matched');
  await expect(page.locator('[data-phone-id-target=primary]')).toContainText('Reused');
  expect(writes).toHaveLength(1);
  expect(writes[0]).toMatchObject({target:'primary',confirmed:true,confirmation_version:1});
  expect(writes[0]).not.toHaveProperty('phone');expect(writes[0]).not.toHaveProperty('national_id');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.screenshot({path:info.outputPath('phone-check-reused.png'),fullPage:true});
});

for(const dark of [false,true]) test(`refresh icon explicitly requests a fresh check (${dark?'dark':'light'})`,async({page},info)=>{
  const {writes}=await boot(page,{dark,outcome:'not_matched'});
  await page.getByRole('button',{name:'Check primary Applicant phone against ID',exact:true}).click();
  const host=page.locator('[data-phone-id-target=primary]');
  await host.getByLabel('Phone registration details').click();
  const again=page.getByRole('button',{name:'Check primary Applicant phone against ID again',exact:true});
  await expect(again).toBeVisible();
  await expect(host).toContainText('Sandbox');
  expect(await again.locator('svg').count()).toBe(1);
  expect((await again.boundingBox()).width).toBeGreaterThanOrEqual(44);
  expect((await again.boundingBox()).height).toBeGreaterThanOrEqual(44);
  await page.screenshot({path:info.outputPath(`phone-check-again-${dark?'dark':'light'}.png`),fullPage:true});
  await page.evaluate(()=>window.__confirm=false);
  await again.click();
  expect(writes).toHaveLength(1);
  await page.evaluate(()=>window.__confirm=true);
  await again.evaluate(button=>{button.click();button.click();});
  await expect.poll(()=>writes.length).toBe(2);
  expect(writes[1]).toMatchObject({fresh_check:true,confirmed:true,confirmation_version:1});
  expect(writes[1].client_request_id).not.toBe(writes[0].client_request_id);
  expect(await page.evaluate(()=>window.__confirmations.at(-1).message)).toContain('charge');
  await expect(host).not.toContainText('Reused');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});

test('cancel and non-IT views perform no verification writes',async({page})=>{
  const {writes}=await boot(page);
  await page.evaluate(()=>window.__confirm=false);
  await page.getByRole('button',{name:'Check primary Applicant phone against ID'}).click();
  expect(writes).toHaveLength(0);
  expect(await page.evaluate(()=>window.__confirmations.length)).toBe(1);
});

test('non-IT has no verification controls',async({page})=>{
  await boot(page,{it:false});
  await expect(page.locator('[data-phone-id-target]')).toHaveCount(0);
});

test('invalid values hide action and failures leave the form usable',async({page},info)=>{
  const {writes}=await boot(page,{failure:true});
  const action=page.getByRole('button',{name:'Check primary Applicant phone against ID'});
  await action.click();
  await expect(page.locator('#origination-toast')).toContainText('Verification unavailable');
  await expect(page.locator('[data-field=applicant_phone]')).toBeEnabled();
  expect(writes).toHaveLength(1);
  await page.screenshot({path:info.outputPath('phone-check-unavailable.png'),fullPage:true});
  await page.locator('[data-field=applicant_phone]').fill('invalid');
  await expect(action).toHaveCount(0);
});

test('completed application offers advisory checks without editing or approval',async({page})=>{
  await boot(page,{status:'completed'});
  await expect(page.locator('.editor-contacts a[href="tel:+254700000001"]')).toBeVisible();
  await expect(page.locator('[data-field=applicant_phone]')).toHaveCount(0);
  await page.getByRole('button',{name:'Check alternate Applicant phone against ID'}).click();
  await expect(page.locator('[data-phone-id-target=alternate]')).toContainText('Registration matched');
  await expect(page.getByRole('heading',{name:'Application completed'})).toBeVisible();
});

test('concurrent application edits require a refresh before disclosure',async({page})=>{
  const {checks,writes}=await boot(page);
  checks.revision=2;
  await page.getByRole('button',{name:'Check primary Applicant phone against ID'}).click();
  await expect(page.locator('#origination-toast')).toContainText('Application changed');
  expect(writes).toHaveLength(0);
  expect(await page.evaluate(()=>window.__confirmations.length)).toBe(0);
});

test('mismatch is neutral advisory feedback, not an approval gate',async({page},info)=>{
  await boot(page,{outcome:'not_matched'});
  await page.getByRole('button',{name:'Check alternate Applicant phone against ID'}).click();
  await expect(page.locator('[data-phone-id-target=alternate]')).toContainText('Registration does not match this ID');
  await expect(page.locator('[data-field=applicant_phone]')).toBeEnabled();
  await page.screenshot({path:info.outputPath('phone-check-mismatch.png'),fullPage:true});
});

test('double click dispatches once and polling is read-only',async({page},info)=>{
  const {checks,writes}=await boot(page,{pending:true});
  await page.getByRole('button',{name:'Check primary Applicant phone against ID'}).evaluate(button=>{button.click();button.click();});
  await expect(page.locator('[data-phone-id-target=primary]')).toContainText('Checking registration');
  await expect(page.locator('[data-phone-id-target=primary] button')).toBeDisabled();
  await page.screenshot({path:info.outputPath('phone-check-loading.png'),fullPage:true});
  Object.assign(checks.targets[0],{status:'matched',reused:false});
  await expect(page.locator('[data-phone-id-target=primary]')).toContainText('Registration matched');
  expect(writes).toHaveLength(1);
});
