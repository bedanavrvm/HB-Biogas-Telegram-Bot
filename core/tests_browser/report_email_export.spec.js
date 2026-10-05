'use strict';
const fs = require('node:fs');
const path = require('node:path');
const {test, expect} = require('playwright/test');
const root = path.resolve(__dirname, '../..');
const script = path.join(root, 'core/static/miniapp/report_email_export.js');
const css = path.join(root, 'core/static/miniapp/report_email_export.css');
let emailPreview;
function renderPreview() {
  if (emailPreview) return emailPreview;
  const {execFileSync}=require('node:child_process');
  const python=path.join(root,'.venv',process.platform==='win32'?'Scripts/python.exe':'bin/python');
  const code=`import os,json
os.environ['DJANGO_SETTINGS_MODULE']='config.settings'
import django
django.setup()
from report_delivery.rendering import email_context
from django.template.loader import render_to_string
snapshot={'preset':'complaints','period':{'from':'2026-10-01','to':'2026-10-05'},'run_at':'2026-10-05T09:30:00+03:00','summary':{'Complaints received':128,'Open':37,'Resolved':91,'Needs details':0,'Median resolution (hours)':18.5,'Median HB response (hours)':4.2,'Resolved on time (%)':87.5},'charts':[{'title':'Complaint categories','labels':['Installation follow-up','Commissioning','Unit maintenance','Customer support'],'datasets':[{'label':'Complaints','values':[54,32,27,15]}]}],'total_rows':128,'exported_rows':128,'rows':[],'applied_filters':{'branch':'Training branch','status':'Open'},'export_limit':2000}
print(json.dumps(render_to_string('report_delivery/email.html',email_context(snapshot))))`;
  emailPreview=JSON.parse(execFileSync(fs.existsSync(python)?python:'python',['-c',code],{cwd:root,encoding:'utf8',env:{...process.env,DJANGO_SECRET_KEY:'synthetic-email-preview-only-abcdefghijklmnopqrstuvwxyz0123456789',DATABASE_URL:'sqlite:///unused-email-preview.sqlite3'}}));
  return emailPreview;
}

for (const app of ['portal', 'tat_tracker', 'complaint_cases']) for (const width of [320,360,390,430,1280]) {
  test(`${app} email dialog fits ${width}px, retains filters and closes without navigation`, async ({page}, info) => {
    await page.setViewportSize({width,height:740});
    await page.setContent('<style>body{margin:0;padding:12px;font-family:Arial}header{display:flex;justify-content:space-between}</style><header><h2>Reports</h2><div class="report-email-actions"><button>Download Excel</button><button id="email"></button></div></header>');
    await page.addStyleTag({path:css}); await page.addScriptTag({path:script});
    await page.evaluate(app => {
      window.__calls=[];
      window.__filters={branch:'Training branch with a long descriptive name', search:'Synthetic case', date_from:'2026-10-01',date_to:'2026-10-05',metric:'hb_response',metric_value:'late'};
      MiniAppReportEmailExport.attach(document.getElementById('email'), () => ({workflow:app, title:'Filtered report', filters:window.__filters,
        post:async body => {window.__calls.push(body);return {delivery_id:'synthetic',status:'accepted'};}}));
    }, app);
    await page.getByRole('button',{name:'Email report',exact:true}).click();
    await expect(page.getByLabel('Email address')).toBeFocused();
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    const close = await page.getByRole('button',{name:'Close email report'}).boundingBox();
    const heading = await page.locator('.report-email-dialog header').boundingBox();
    expect(Math.abs(close.x+close.width-heading.x-heading.width)).toBeLessThan(2);
    await page.getByLabel('Email address').fill('management@example.invalid');
    await page.screenshot({path:info.outputPath(`email-${app}-${width}.png`)});
    await page.evaluate(()=>window.__filters.branch='Changed after dialog opened');
    await page.getByRole('button',{name:'Send',exact:true}).click();
    await expect(page.getByRole('status')).toHaveText('Accepted for delivery.');
    expect(await page.evaluate(()=>window.__calls[0].filters.branch)).toContain('Training branch');
    expect(await page.evaluate(()=>window.__calls.length)).toBe(1);
    await page.getByRole('button',{name:'Close email report'}).click();
    await expect(page.locator('dialog')).toHaveCount(0);
    await expect(page.getByRole('button',{name:'Email report',exact:true})).toBeFocused();
  });
}

test('Lost response retains destination and reuses the exact request key', async ({page}) => {
  await page.setContent('<button id="email">Email</button>'); await page.addStyleTag({path:css}); await page.addScriptTag({path:script});
  await page.evaluate(()=>{
    window.__calls=[];
    MiniAppReportEmailExport.attach(document.getElementById('email'), {workflow:'tat_tracker',filters:{branch:'Training'},post:async body=>{
      window.__calls.push(body); if(window.__calls.length===1)throw new Error('Synthetic lost response');
      return {delivery_id:'synthetic',status:'accepted'};
    }});
  });
  await page.getByRole('button',{name:'Email report',exact:true}).click(); await page.getByLabel('Email address').fill('management@example.invalid');
  await page.getByRole('button',{name:'Send',exact:true}).click();
  await expect(page.getByRole('status')).toHaveText('Synthetic lost response');
  await expect(page.getByLabel('Email address')).toHaveValue('management@example.invalid');
  await page.getByRole('button',{name:'Retry',exact:true}).click();
  expect(await page.evaluate(()=>window.__calls[0].client_request_id===window.__calls[1].client_request_id)).toBe(true);
});

test('Double submission is single-flight and dialog can close while delivery continues', async ({page}) => {
  await page.setContent('<button id="email">Email</button>'); await page.addScriptTag({path:script});
  await page.evaluate(()=>{window.__calls=0;MiniAppReportEmailExport.attach(document.getElementById('email'),{post:()=>{window.__calls++;return new Promise(resolve=>window.__resolve=resolve);}});});
  await page.getByRole('button',{name:'Email report',exact:true}).click();await page.getByLabel('Email address').fill('management@example.invalid');
  const close=await page.getByRole('button',{name:'Close email report'}).boundingBox();expect(close.width).toBeLessThanOrEqual(40);
  await page.getByRole('button',{name:'Send',exact:true}).click();await page.locator('form').evaluate(form=>form.dispatchEvent(new Event('submit',{cancelable:true})));
  expect(await page.evaluate(()=>window.__calls)).toBe(1);
  await page.getByRole('button',{name:'Close email report'}).click();
  await page.evaluate(()=>window.__resolve({status:'accepted'}));await expect(page.locator('dialog')).toHaveCount(0);
});

test('Real report templates load the shared email control before their controllers', async () => {
  for(const [file,controller] of [['core/templates/base_shell.html','portal_curated_reports.js'],['core/templates/tat_tracker/app.html','tat_tracker.js'],['core/templates/complaint_cases/app.html','complaint_cases.js']]) {
    const html=fs.readFileSync(path.join(root,file),'utf8');
    expect(html.indexOf('report_email_export.js')).toBeLessThan(html.indexOf(controller));
    expect(html).toContain('report_email_export.css');
  }
});

for(const width of [320,390,640])test(`Generated management email fits ${width}px`,async({page},info)=>{
  await page.setViewportSize({width,height:900});await page.setContent(renderPreview());
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await expect(page.getByRole('heading',{name:'Complaints overview',exact:true})).toBeVisible();
  await page.screenshot({path:info.outputPath(`management-email-${width}.png`),fullPage:true});
});

test('Real TAT report header keeps email beside export and strips launch credentials',async({page},info)=>{
  await page.setViewportSize({width:320,height:740});
  const template=fs.readFileSync(path.join(root,'core/templates/tat_tracker/app.html'),'utf8');
  const header=template.slice(template.indexOf('<div class="report-title-row">'),template.indexOf('<nav class="report-mode-tabs"'));
  await page.setContent(`<main class="tat-app"><section class="tat-report">${header}</section></main>`);
  await page.addStyleTag({path:path.join(root,'core/static/miniapp/base.css')});await page.addStyleTag({path:path.join(root,'core/static/miniapp/tat_tracker.css')});await page.addStyleTag({path:css});await page.addScriptTag({path:script});
  const source=fs.readFileSync(path.join(root,'core/static/miniapp/tat_tracker.js'),'utf8');
  const start=source.indexOf("  window.MiniAppReportEmailExport?.attach($('tatReportEmail')");const end=source.indexOf('\n  });',start)+7;
  await page.addScriptTag({content:`const $=id=>document.getElementById(id);const state={report:{view:'current'}};const tg=null;const setStatus=()=>{};function reportPayload(){return {init_data:'synthetic-secret',token:'synthetic-token',group_id:'synthetic',view:'current',branch:'Training',search:'Synthetic',date_from:'2026-10-01',date_to:'2026-10-05'};}async function api(url,payload){window.__tatEmail={url,payload};return {status:'accepted',delivery_id:'synthetic'};}${source.slice(start,end)}`});
  const email=await page.getByRole('button',{name:'Email report',exact:true}).boundingBox();const download=await page.locator('#tatReportExport').boundingBox();
  expect(Math.abs(email.y-download.y)).toBeLessThan(4);expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.getByRole('button',{name:'Email report',exact:true}).click();await page.getByLabel('Email address').fill('management@example.invalid');
  await page.screenshot({path:info.outputPath('tat-real-email-320.png')});
  await page.getByRole('button',{name:'Send',exact:true}).click();
  const sent=await page.evaluate(()=>window.__tatEmail);expect(sent.url).toBe('/api/tat-tracker/reports/email/');expect(sent.payload.filters.init_data).toBeUndefined();expect(sent.payload.filters.search).toBe('Synthetic');
});
