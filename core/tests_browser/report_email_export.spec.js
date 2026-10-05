'use strict';
const fs = require('node:fs');
const path = require('node:path');
const {test, expect} = require('playwright/test');
const root = path.resolve(__dirname, '../..');
const script = path.join(root, 'core/static/miniapp/report_email_export.js');
const css = path.join(root, 'core/static/miniapp/report_email_export.css');
const emailPreviews = new Map();
function renderPreview(preset='complaints') {
  if (emailPreviews.has(preset)) return emailPreviews.get(preset);
  const {execFileSync}=require('node:child_process');
  const python=path.join(root,'.venv',process.platform==='win32'?'Scripts/python.exe':'bin/python');
  const code=`import os,json
os.environ['DJANGO_SETTINGS_MODULE']='config.settings'
import django
django.setup()
from report_delivery.rendering import build_payload
snapshot={'preset':'complaints','period':{'from':'2026-10-01','to':'2026-10-05'},'run_at':'2026-10-05T09:30:00+03:00','summary':{'Complaints received':128,'Open':37,'Resolved':91,'Needs details':0,'Median resolution (hours)':18.5,'Median HB response (hours)':4.2,'Resolved on time (%)':87.5},'charts':[{'title':'Complaint categories','labels':['Installation follow-up','Commissioning','Unit maintenance','Customer support'],'datasets':[{'label':'Complaints','values':[54,32,27,15]}]}],'total_rows':128,'exported_rows':128,'rows':[],'applied_filters':{'branch':'Training branch','status':'Open'},'export_limit':2000}
snapshot['xlsx_content']='c3ludGhldGlj'
snapshot['charts'].append({'title':'Complaints by branch','labels':['Training branch with a long descriptive name','Second training branch'],'datasets':[{'label':'Complaints','values':[90,38]}]})
snapshot['preset']=${JSON.stringify(preset)}
if snapshot['preset']=='tat':
    snapshot.update(summary={'Cases received':128,'Completed cases':91,'Disbursed':80,'Declined':11,'Within or near target (%)':87.5,'Median TAT (minutes)':150,'No target available':3},charts=[{'title':'Completed actions','type':'line','labels':['01 Oct','02 Oct','03 Oct'],'datasets':[{'label':'Completed','values':[21,32,38]}]}])
    snapshot['applied_filters']={'branch':'Training branch','view':'performance'}
elif snapshot['preset']=='finance':
    snapshot.update(summary={'Cases in scope':128,'Invoice total (KES)':123456789,'Paid (KES)':95000000,'Outstanding (KES)':28456789},charts=[{'title':'Financial amounts by branch','labels':['Training branch with a long descriptive name','Second training branch'],'datasets':[{'label':s,'values':[123456789,98456789]} for s in ['Invoice','Paid','Balance','Deposit']]}])
elif snapshot['preset']=='empty':
    snapshot.update(preset='complaints',summary={},charts=[],total_rows=0,exported_rows=0)
payload=build_payload(snapshot,'management@example.invalid',{})
html=payload['html']
for attachment in payload['attachments']:
    if attachment.get('content_id'):
        html=html.replace('cid:'+attachment['content_id'],'data:'+attachment['content_type']+';base64,'+attachment['content'])
print(json.dumps(html))`;
  const html=JSON.parse(execFileSync(fs.existsSync(python)?python:'python',['-c',code],{cwd:root,encoding:'utf8',env:{...process.env,DJANGO_SECRET_KEY:'synthetic-email-preview-only-abcdefghijklmnopqrstuvwxyz0123456789',DATABASE_URL:'sqlite:///unused-email-preview.sqlite3'}}));
  emailPreviews.set(preset,html);
  return html;
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

for(const width of [320,390,760])test(`Generated management email fits ${width}px`,async({page},info)=>{
  await page.route(/^https?:\/\//,route=>route.abort());
  await page.setViewportSize({width,height:900});await page.setContent(renderPreview());
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await expect(page.getByRole('heading',{name:'Complaints overview',exact:true})).toBeVisible();
  expect(await page.locator('.brand-logo').evaluate(img=>img.naturalWidth)).toBeGreaterThan(0);
  await expect(page.locator('.report-graph')).toHaveCount(2);
  expect(await page.locator('.report-graph').evaluateAll(images=>images.every(img=>img.naturalWidth===600))).toBe(true);
  expect(await page.locator('.metric-label').first().evaluate(el=>getComputedStyle(el).fontSize)).toBe('14px');
  expect(await page.locator('.breakdown-table').first().evaluate(el=>getComputedStyle(el).fontSize)).toBe('16px');
  expect(await page.locator('.email-container').evaluate(el=>getComputedStyle(el).fontFamily)).toContain('Segoe UI');
  await expect(page.getByText('Median resolution',{exact:true})).toBeVisible();
  await expect(page.getByText('87.50%',{exact:true})).toBeVisible();
  const metrics=await page.locator('.metric').evaluateAll(cells=>cells.map(c=>c.getBoundingClientRect().toJSON()));
  expect(Math.abs(metrics[0].y-metrics[1].y)).toBeLessThan(1);
  expect(Math.abs(metrics[0].width-metrics[1].width)).toBeLessThan(1);
  if(width<=600) expect(metrics[2].y).toBeGreaterThan(metrics[0].y);
  else expect(Math.abs(metrics[2].y-metrics[0].y)).toBeLessThan(1);
  const panels=await page.locator('.breakdown-panel').evaluateAll(cells=>cells.map(c=>c.getBoundingClientRect().toJSON()));
  if(width<=600) expect(panels[1].y).toBeGreaterThan(panels[0].y);
  else expect(Math.abs(panels[1].y-panels[0].y)).toBeLessThan(1);
  await page.screenshot({path:info.outputPath(`management-email-${width}.png`),fullPage:true});
});

for(const preset of ['tat','finance','empty']) for(const width of [320,760]) {
  test(`${preset} management email fits ${width}px without invented links`,async({page},info)=>{
    await page.route(/^https?:\/\//,route=>route.abort());
    await page.setViewportSize({width,height:900});await page.setContent(renderPreview(preset));
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    await expect(page.getByText('Detailed Excel attached',{exact:true})).toBeVisible();
    await expect(page.locator('a')).toHaveCount(0);
    if(preset==='tat') await expect(page.getByText('2 hr 30 min',{exact:true})).toBeVisible();
    if(preset==='finance') {
      await expect(page.locator('.breakdown-multi')).toHaveCount(1);
      await expect(page.locator('.breakdown-multi td').first()).toHaveText('123,456,789');
      const values=await page.locator('.metric-value').evaluateAll(cells=>cells.map(c=>c.getBoundingClientRect().height));
      expect(Math.max(...values)).toBeLessThanOrEqual(36);
    }
    if(preset==='empty') await expect(page.getByText('0 of 0 matching cases.',{exact:true})).toBeVisible();
    await page.screenshot({path:info.outputPath(`management-${preset}-${width}.png`),fullPage:true});
  });
}

test('Image-blocked management email retains readable breakdown values',async({page},info)=>{
  await page.route(/^https?:\/\//,route=>route.abort());
  await page.setViewportSize({width:320,height:900});await page.setContent(renderPreview());
  await page.locator('img').evaluateAll(images=>images.forEach(img=>img.remove()));
  await expect(page.locator('.breakdown-table')).toHaveCount(2);
  await expect(page.locator('.breakdown-table').first().getByText('54',{exact:true})).toBeVisible();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.screenshot({path:info.outputPath('management-images-blocked-320.png'),fullPage:true});
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
