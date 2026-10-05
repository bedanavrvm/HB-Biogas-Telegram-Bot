'use strict';
const fs = require('node:fs');
const path = require('node:path');
const {test,expect}=require('playwright/test');
const root=path.resolve(__dirname,'../..');
const script=fs.readFileSync(path.join(root,'core/static/miniapp/report_email_settings.js'),'utf8');
const style=fs.readFileSync(path.join(root,'core/static/miniapp/report_email_settings.css'),'utf8');

test('Portal Add report opens recipients and cadence in the real Settings shell with delivery disabled',async({page})=>{
  const {mountPortalShell}=require('./fixtures/portal_shell');
  const template=fs.readFileSync(path.join(root,'core/templates/portal/portal.html'),'utf8');
  const section=template.match(/<section id="portal-report-email-settings"[^]*?<\/section>/)[0].replace(' hidden>','>');
  await page.setViewportSize({width:360,height:740});
  await mountPortalShell(page,`<main class="page active">${section}</main>`);
  await page.addScriptTag({content:script});
  await page.evaluate(()=>window.MiniAppReportEmailSettings.mount(document.getElementById('portal-report-email-manager'),async()=>({data:{enabled:false,presets:['pipeline','outcomes','finance'],groups:[{id:1,label:'Synthetic group'}],schedules:[]}})));
  await page.getByRole('button',{name:'Manage reports'}).click();
  await page.getByRole('button',{name:'Add report'}).click();
  await expect(page.getByLabel('Recipients',{exact:true})).toBeVisible();
  await expect(page.getByRole('combobox',{name:'Frequency',exact:true})).toBeVisible();
  await expect(page.getByLabel('Time (Nairobi)',{exact:true})).toBeVisible();
  await page.screenshot({path:'test-results/portal-add-report-real-settings.png',fullPage:true});
});

test('Add report remains usable without WebView crypto helpers and focuses the editor',async({page})=>{
  await page.setContent('<section id="settings"></section>');
  await page.addScriptTag({content:script});
  await page.evaluate(()=>{
    Object.defineProperty(window.crypto,'randomUUID',{value:undefined,configurable:true});
    Object.defineProperty(window.crypto,'getRandomValues',{value:undefined,configurable:true});
    window.MiniAppReportEmailSettings.mount(document.getElementById('settings'),async()=>({data:{enabled:false,presets:['pipeline'],groups:[{id:1,label:'Synthetic group'}],schedules:[]}}));
  });
  await page.getByRole('button',{name:'Manage reports'}).click();
  await page.getByRole('button',{name:'Add report'}).click();
  await expect(page.getByLabel('Report name',{exact:true})).toBeVisible();
  await expect(page.getByLabel('Report name',{exact:true})).toBeFocused();
});

for(const app of ['portal','tat','complaints']) {
  test(`${app} recipient settings fit mobile and save configured addresses`,async({page})=>{
    for(const width of [320,360,390,430]) {
      await page.setViewportSize({width,height:740});
      await page.setContent(`<style>body{margin:0;padding:12px;font-family:Arial;box-sizing:border-box}button{border:1px solid #ccd5df;border-radius:8px;background:white;padding:8px;color:#243244}#settings{padding:12px;border:1px solid #e3e6eb;border-radius:12px}${style}</style><section id="settings"></section>`);
      await page.evaluate(app=>{document.body.className=app==='portal'?'portal-app':app==='complaints'?'complaint-cases-app':'';document.getElementById('settings').className=app==='portal'?'portal-settings-card':app==='tat'?'form-card':'panel';},app);
      await page.addStyleTag({path:path.join(root,'core/static/miniapp/base.css')});
      await page.addStyleTag({path:path.join(root,`core/static/miniapp/${app==='portal'?'portal':app==='tat'?'tat_tracker':'complaint_cases'}.css`)});
      await page.addStyleTag({content:style});
      await page.addScriptTag({content:script});
      await page.evaluate(app=>{
        window.confirm=()=>true;
        window.calls=[];
        const config={enabled:true,presets:[app==='portal'?'pipeline':app==='tat'?'tat':'complaints'],groups:[{id:1,label:'Synthetic test group'}],schedules:[]};
        window.MiniAppReportEmailSettings.mount(document.getElementById('settings'),async payload=>{window.calls.push(payload);return {data:config};});
      },app);
      await page.getByRole('button',{name:'Manage reports'}).click();
      await page.getByRole('button',{name:'Add report'}).click();
      await page.getByLabel('Report name',{exact:true}).fill('Synthetic report');
      await page.getByLabel('Recipients',{exact:true}).fill('first@example.invalid\nsecond@example.invalid');
      await page.getByLabel('Active',{exact:true}).check();
      expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
      await page.screenshot({path:`test-results/${app}-email-settings-${width}.png`,fullPage:true});
      await page.getByRole('button',{name:'Save',exact:true}).click();
      await expect(page.getByRole('status')).toHaveText('Report settings saved.');
      expect(await page.evaluate(()=>window.calls.at(-1).recipients)).toEqual(['first@example.invalid','second@example.invalid']);
      expect(await page.evaluate(()=>window.calls.at(-1).active)).toBe(true);
    }
  });
}

test('Save is single flight and preserves editor on failure',async({page})=>{
  await page.setContent('<section id="settings"></section>');await page.addScriptTag({content:script});
  await page.evaluate(()=>{
    window.confirm=()=>true;window.saveCalls=0;
    window.MiniAppReportEmailSettings.mount(document.getElementById('settings'),async p=>{
      if(p.action==='list')return {data:{enabled:false,presets:['complaints'],groups:[{id:1,label:'Test'}],schedules:[]}};
      window.saveCalls++;return new Promise((_,reject)=>window.fail=()=>reject(new Error('Synthetic connection lost')));
    });
  });
  await page.getByRole('button',{name:'Manage reports'}).click();await page.getByRole('button',{name:'Add report'}).click();
  await page.getByLabel('Report name',{exact:true}).fill('Test');await page.getByLabel('Recipients',{exact:true}).fill('reports@example.invalid');
  await page.getByRole('button',{name:'Save',exact:true}).click();await expect(page.getByRole('button',{name:'Save',exact:true})).toBeDisabled();
  await page.getByRole('button',{name:'Save',exact:true}).evaluate(b=>b.click());
  expect(await page.evaluate(()=>window.saveCalls)).toBe(1);
  await page.evaluate(()=>window.fail());
  await expect(page.getByLabel('Recipients',{exact:true})).toHaveValue('reports@example.invalid');
  await expect(page.getByRole('status')).toHaveText('Synthetic connection lost');
});

test('Complaints header settings closes with Back and preserves the report editor',async({page})=>{
  const {initData}=require('./fixtures/local_mcp_fixtures.js');
  const template=fs.readFileSync(path.join(root,'core/templates/complaint_cases/app.html'),'utf8')
    .replace('{% include "complaint_cases/lucide_icons.html" %}',fs.readFileSync(path.join(root,'core/templates/complaint_cases/lucide_icons.html'),'utf8'))
    .replace("{% static 'miniapp/jawabu-logo.png' %}",`data:image/png;base64,${fs.readFileSync(path.join(root,'core/static/miniapp/jawabu-logo.png')).toString('base64')}`)
    .replace(/\{%[^]*?%\}/g,'').replace(/<script[^]*?<\/script>/g,'').replace(/<link[^>]+>/g,'');
  await page.setViewportSize({width:320,height:740});await page.setContent(template);
  for(const asset of ['base.css','complaint_cases.css','report_email_settings.css'])await page.addStyleTag({path:path.join(root,'core/static/miniapp',asset)});
  await page.evaluate(initData=>{
    const app={initData,BackButton:{onClick(fn){window.back=fn;},show(){},hide(){}},onEvent(){}};
    window.MiniAppUtils={initTelegram:()=>app,setCloseProtection(){},haptic(){}};
    window.ComplaintCasesMiniAppApi={async postJson(route){
      if(route==='bootstrap/')return {data:{actor:{name:'Synthetic IT',role:'IT',capabilities:['complaint.queue.view']},counts:{},branches:[],categories:[],category_catalogue:[]}};
      if(route==='settings/reports/')return {data:{enabled:false,presets:['complaints'],groups:[{id:1,label:'Synthetic group'}],schedules:[]}};
      return {cases:[],pagination:{page:1,pages:1,total:0},start_index:0};
    }};
  },initData);
  await page.addScriptTag({content:script});
  await page.addScriptTag({path:path.join(root,'core/static/miniapp/complaint_cases.js')});
  await page.locator('#complaintSettingsBtn').click();await expect(page.locator('#complaintSettingsOverlay')).toBeVisible();
  await page.getByRole('button',{name:'Manage reports'}).click();await page.getByRole('button',{name:'Add report'}).click();
  await page.getByLabel('Recipients',{exact:true}).fill('reports@example.invalid');
  await page.screenshot({path:'test-results/complaints-settings-sheet-320.png'});
  await page.evaluate(()=>window.back());await expect(page.locator('#complaintSettingsOverlay')).toBeHidden();
  await expect(page.locator('#complaintSettingsBtn')).toBeFocused();
  await page.locator('#complaintSettingsBtn').click();await expect(page.getByLabel('Recipients',{exact:true})).toHaveValue('reports@example.invalid');
  await page.keyboard.press('Escape');await expect(page.locator('#complaintSettingsOverlay')).toBeHidden();
});
