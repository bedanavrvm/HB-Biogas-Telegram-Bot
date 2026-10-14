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
if snapshot['preset'] in {'complaints','cmp_tat','cmp_open'}:
    snapshot['comparison']={'label':'01-10-26 to 05-10-26 vs 01-09-26 to 05-09-26 · equal elapsed time','metrics':{'Reported':{'text':'+12 vs previous','tone':'muted'},'Resolved on time (%)':{'text':'+5.5 pp vs previous','tone':'good'}}}
    snapshot['summary']={'Reported':128,'Resolved in period':91,'Open now':37,'Resolved on time (%)':87.5,'Median resolution (hours)':18.5,'Median HB response (hours)':4.2}
    snapshot['management']={'resolved':91,'on_time':70,'late':10,'no_target':11,'targets_hours':['72'],'resolution_count':91,'response_count':91,'resolution_hours':18.5,'open':37,'late_open':10,'previous_on_time':66,'previous_target_count':80,'previous_from':'2026-09-01','previous_to':'2026-09-05'}
    snapshot['comparison']['metrics'].update({'Reported':{'paired_values':{'current':128,'previous':116}},'Resolved in period':{'paired_values':{'current':91,'previous':80}},'Resolved on time (%)':{'paired_values':{'current':87.5,'previous':82}},'Median resolution (hours)':{'paired_values':{'current':18.5,'previous':25}}})
    trend={'title':'Reported vs resolved','type':'line','presentation':'chart','context':'Distinct complaints per day.','labels':['01-10-26','02-10-26','03-10-26','04-10-26','05-10-26'],'datasets':[{'label':'Reported','values':[12,20,32,40,24]},{'label':'Resolved','values':[15,12,24,20,20]}]}
    age={'title':'Open-case age','presentation':'rows','context':'All currently unresolved complaints, including older cases.','labels':['Under 3 days','3–7 days','8–14 days','Over 14 days'],'datasets':[{'label':'Complaints','values':[10,9,8,10]}]}
    snapshot['email_sections']=[trend,age,*snapshot['charts']]
    if snapshot['preset']=='cmp_tat':
        snapshot['summary']={'Median resolution (hours)':18.5,'Median HB response (hours)':4.2,'Resolved on time (%)':87.5,'Reopened in period':3}
        snapshot['email_sections']=[{**trend,'title':title,'datasets':[{'label':'Hours','values':values}]} for title,values in [('Resolution time',[30,25,None,19,18.5]),('HB response time',[8,7,6,4.5,4.2])]]+[{'title':'Resolution targets','labels':['On time','Late','No target'],'datasets':[{'label':'Complaints','values':[70,10,11]}]},{'title':'Slowest complaint types','labels':['Installation and commissioning follow-up','Unit maintenance'],'datasets':[{'label':'Median hours','values':[26,18.5]},{'label':'Samples','values':[30,21]}]}]
    elif snapshot['preset']=='cmp_open':
        snapshot['summary']={'Open now':37,'Over 14 days':10,'No HB response':12,'Oldest open (hours)':184.53}
        snapshot['comparison']={'label':'Current snapshot · includes older unresolved complaints.'}
        snapshot['email_sections']=[age,{'title':'Open cases by branch','labels':['Training branch with a long descriptive name','Second training branch'],'datasets':[{'label':'Open','values':[25,12]},{'label':'Over 14 days','values':[7,3]},{'label':'No HB response','values':[8,4]}]}]
if snapshot['preset']=='tat':
    snapshot.update(summary={'Cases received':128,'Completed cases':91,'Disbursed':80,'Declined':11,'Within or near target (%)':87.5,'Median TAT (minutes)':150,'No target available':3},charts=[{'title':'Completed actions','type':'line','labels':['01 Oct','02 Oct','03 Oct'],'datasets':[{'label':'Completed','values':[21,32,38]}]}])
    snapshot['applied_filters']={'branch':'Training branch','view':'performance'}
elif snapshot['preset']=='finance':
    snapshot.update(summary={'Cases in scope':128,'Invoice total (KES)':123456789,'Paid (KES)':95000000,'Outstanding (KES)':28456789},charts=[{'title':'Financial amounts by branch','labels':['Training branch with a long descriptive name','Second training branch'],'datasets':[{'label':s,'values':[123456789,98456789]} for s in ['Invoice','Paid','Balance','Deposit']]}])
elif snapshot['preset']=='empty':
    snapshot.update(preset='complaints',summary={},charts=[],email_sections=[],management={},total_rows=0,exported_rows=0)
elif snapshot['preset']=='late':
    from report_delivery.tests_management_email import ManagementEmailTests
    snapshot=ManagementEmailTests().snapshot('cmp_tat')
    from django.conf import settings
    settings.APP_BASE_URL='https://local-app.example.invalid'
elif snapshot['preset'] in {'polish_overview','polish_tat','polish_open'}:
    from unittest.mock import patch
    from report_delivery.complaint_reports import complaint_email_projection
    from report_delivery.tests_complaint_reports import synthetic_case, stamp
    preset={'polish_overview':'complaints','polish_tat':'cmp_tat','polish_open':'cmp_open'}[snapshot['preset']]
    filters={'date_from':'2026-10-05','date_to':'2026-10-11','branch':'Training'}
    cases=[synthetic_case(i,reported='2026-10-05T09:00',resolved='2026-10-05T09:06',hours=.1,target=True,response='2026-10-05T09:03',category='Installation follow-up') for i in range(4)]
    cases.append(synthetic_case(5,reported='2026-10-03T09:00',resolved='2026-10-11T09:00',hours=192,target=False,response='2026-10-04T09:00',category='Maintenance'))
    cases[3].complaint_timing.update(resolved_at=stamp('2026-10-07T09:00'),resolution_hours=48,
        closures=[stamp('2026-10-05T09:06'),stamp('2026-10-07T09:00')],reopened=[stamp('2026-10-06T09:00')])
    cases += [synthetic_case(10+i,reported='2026-09-30T09:00',category='Maintenance' if i<3 else 'Installation follow-up',branch='Training branch with a longer name' if i<3 else 'Second branch',age='8_14',response='2026-10-01T09:00' if i<2 else None) for i in range(5)]
    for case in cases:
        case.complaint_control.sla_target_hours=72
        if case.pk < 4: case.complaint_timing['hb_response_hours']=.05
        else: case.complaint_timing['hb_response_hours']=24 if case.complaint_timing['response_at'] else None
        if case.complaint_status=='Open': case.complaint_timing['elapsed_seconds']=12*86400
    with patch('core.services.complaint_register._apply_report_filters',return_value=object()), patch('report_delivery.complaint_reports.timed_cases',return_value=iter(cases)):
        projection=complaint_email_projection(object(),filters,preset=preset,now=stamp('2026-10-12T12:00'))
    snapshot.update(projection,preset=preset,period={'from':filters['date_from'],'to':filters['date_to']},applied_filters=filters,total_rows=len(cases),exported_rows=len(cases),run_at='2026-10-12T12:00:00+03:00')
elif snapshot['preset'] in {'month','year'}:
    from unittest.mock import patch
    from report_delivery.complaint_reports import complaint_email_projection
    from report_delivery.tests_complaint_reports import synthetic_case, stamp
    annual=snapshot['preset']=='year'
    filters={'date_from':'2026-01-01' if annual else '2026-09-01','date_to':'2026-12-31' if annual else '2026-09-30','date_mode':'year' if annual else 'month'}
    cases=[synthetic_case(i,reported=f'2026-{i+1:02d}-05T09:00',resolved=f'2026-{i+1:02d}-06T09:00') for i in range(12)] if annual else [synthetic_case(i,reported=f'2026-09-{i+1:02d}T09:00',resolved=f'2026-09-{i+1:02d}T15:00') for i in range(30)]
    with patch('core.services.complaint_register._apply_report_filters',return_value=object()), patch('report_delivery.complaint_reports.timed_cases',return_value=iter(cases)):
        snapshot.update(complaint_email_projection(object(),filters,now=stamp('2027-02-01T12:00')))
    snapshot.update(preset='complaints',period={'from':filters['date_from'],'to':filters['date_to']},applied_filters=filters,total_rows=len(cases),exported_rows=len(cases),run_at='2027-02-01T12:00:00+03:00')
elif snapshot['preset']=='cross_year':
    from report_delivery.tests_management_email import ManagementEmailTests
    snapshot=ManagementEmailTests().snapshot()
    snapshot['period']={'from':'2025-12-20','to':'2026-01-10'}
    snapshot['management'].update(previous_from='2025-11-28',previous_to='2025-12-19')
    snapshot['applied_filters'].pop('branch',None)
payload=build_payload(snapshot,'management@example.invalid',{})
html=payload['html']
for attachment in payload['attachments']:
    if attachment.get('content_id'):
        html=html.replace('cid:'+attachment['content_id'],'data:'+attachment['content_type']+';base64,'+attachment['content'])
print(json.dumps(html))`;
  const html=JSON.parse(execFileSync(fs.existsSync(python)?python:'python',['-c',code],{cwd:root,encoding:'utf8',env:{...process.env,DJANGO_SECRET_KEY:'synthetic-email-preview-only-abcdefghijklmnopqrstuvwxyz0123456789',DATABASE_URL:'sqlite:///:memory:'}}));
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

for(const width of [320,360,390,430,768,1280])test(`Generated management email fits ${width}px`,async({page},info)=>{
  await page.route(/^https?:\/\//,route=>route.abort());
  await page.setViewportSize({width,height:900});await page.setContent(renderPreview());
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await expect(page.getByRole('heading',{name:'Complaints overview',exact:true})).toBeVisible();
  expect(await page.locator('.brand-logo').evaluate(img=>img.naturalWidth)).toBeGreaterThan(0);
  await expect(page.locator('.report-graph')).toHaveCount(1);
  expect(await page.locator('.report-graph').evaluateAll(images=>images.every(img=>img.naturalWidth===840))).toBe(true);
  expect(await page.locator('.report-graph').evaluateAll(images=>images.every(img=>img.getBoundingClientRect().height<=240))).toBe(true);
  expect(await page.locator('.metric-label').first().evaluate(el=>getComputedStyle(el).fontSize)).toBe('12px');
  expect(await page.locator('.breakdown-table').first().evaluate(el=>getComputedStyle(el).fontSize)).toBe('14px');
  expect(await page.locator('.email-container').evaluate(el=>getComputedStyle(el).fontFamily)).toContain('Segoe UI');
  await expect(page.getByText('Median resolution',{exact:true})).toBeVisible();
  await expect(page.getByText('88%',{exact:true})).toBeVisible();
  const metrics=await page.locator('.metric').evaluateAll(cells=>cells.map(c=>c.getBoundingClientRect().toJSON()));
  expect(Math.abs(metrics[0].y-metrics[1].y)).toBeLessThan(1);
  expect(Math.abs(metrics[0].width-metrics[1].width)).toBeLessThan(1);
  expect(Math.max(...metrics.map(metric=>metric.height))-Math.min(...metrics.map(metric=>metric.height))).toBeLessThan(1);
  if(width<=600) expect(metrics[2].y).toBeGreaterThan(metrics[0].y);
  else expect(Math.abs(metrics[2].y-metrics[0].y)).toBeLessThan(1);
  expect(await page.locator('.email-container').evaluate(el=>el.getBoundingClientRect().width)).toBeLessThanOrEqual(900);
  const attention=await page.getByRole('heading',{name:'Needs attention'}).boundingBox();
  const chart=await page.locator('.report-graph').boundingBox();
  expect(attention.y).toBeLessThan(chart.y);
  await page.screenshot({path:info.outputPath(`management-email-${width}.png`),fullPage:true});
});

for(const preset of ['tat','finance','empty','cmp_tat','cmp_open','month','year']) for(const width of [320,430,1280]) {
  test(`${preset} management email fits ${width}px without invented links`,async({page},info)=>{
    await page.route(/^https?:\/\//,route=>route.abort());
    await page.setViewportSize({width,height:900});await page.setContent(renderPreview(preset));
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    await expect(page.getByText('Full detail in the attached Excel.',{exact:true})).toBeVisible();
    await expect(page.locator('a')).toHaveCount(0);
    // Secondary metrics are in the text alternative/Excel, not extra KPI rows.
    if(preset==='tat') await expect(page.locator('.metric')).toHaveCount(4);
    if(preset==='finance') {
      await expect(page.locator('.breakdown-multi')).toHaveCount(1);
      await expect(page.locator('.breakdown-multi td').first()).toHaveText('123,456,789');
      const values=await page.locator('.metric-value').evaluateAll(cells=>cells.map(c=>c.getBoundingClientRect().height));
      expect(Math.max(...values)).toBeLessThanOrEqual(36);
    }
    if(preset==='empty') await expect(page.getByText('No cases match this report.',{exact:true})).toBeVisible();
    if(['month','year'].includes(preset)) {
      await expect(page.locator('.report-graph')).toHaveCount(2);
      expect(await page.locator('.report-graph').first().evaluate(img=>img.naturalWidth)).toBe(840);
      await expect(page.getByText('Complaints reported and resolved by date. Resolutions include older complaints.',{exact:true})).toBeVisible();
      await expect(page.getByText(/partial bucket|Latest.*bucket/)).toHaveCount(0);
    }
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

for (const width of [320,430,600,1280]) for (const colorScheme of ['light','dark']) {
  test(`Decision-first email ${colorScheme} at ${width}px keeps bad news honest`, async ({page},info) => {
    await page.route(/^https?:\/\//,route=>route.abort());
    await page.emulateMedia({colorScheme});
    await page.setViewportSize({width,height:900});
    await page.setContent(renderPreview('late'));
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    expect(await page.locator('.email-container').evaluate(el=>el.getBoundingClientRect().width)).toBeLessThanOrEqual(900);
    if(width===1280) expect(await page.locator('.email-container').evaluate(el=>el.getBoundingClientRect().width)).toBe(900);
    await expect(page.locator('.report-verdict')).toHaveCount(0);
    await expect(page.locator('.eligibility-note')).toContainText('Target 3.0 days');
    await expect(page.locator('.eligibility-note')).toContainText('3 of 3');
    await expect(page.getByText(/Based on/)).toHaveCount(0);
    await expect(page.getByText(/n=\d|low volume/)).toHaveCount(0);
    await expect(page.locator('.metric-comparison.metric-worse').filter({hasText:'▼ 50 pts lower'})).toBeVisible();
    await expect(page.locator('.metric-value.metric-worse').filter({hasText:'0%'})).toBeVisible();
    await expect(page.getByRole('link')).toHaveCount(0);
    for(const label of ['Time','Cases']) {
      const heading=page.getByRole('columnheader',{name:label,exact:true});
      await expect(heading).toBeVisible();
      expect((await heading.boundingBox()).height).toBeLessThan(30);
    }
    const bad=await page.locator('.metric-value.metric-worse').filter({hasText:'0%'}).evaluate(el=>getComputedStyle(el).color);
    expect(bad).toBe(colorScheme==='dark'?'rgb(255, 168, 157)':'rgb(180, 35, 24)');
    if(colorScheme==='dark') expect(await page.locator('.breakdown-table td').last().evaluate(el=>getComputedStyle(el).color)).toBe('rgb(198, 205, 216)');
    await expect(page.locator('.report-graph')).toHaveCount(1);
    await page.screenshot({path:info.outputPath(`decision-email-${colorScheme}-${width}.png`),fullPage:true});
  });
}

for (const preset of ['polish_overview','polish_tat','polish_open']) for (const width of [320,390,430,768,1280]) for (const colorScheme of ['light','dark']) {
  test(`Polished ${preset} ${colorScheme} fits ${width}px with unique aligned panels`, async ({page},info) => {
    await page.route(/^https?:\/\//,route=>route.abort());
    await page.emulateMedia({colorScheme});
    await page.setViewportSize({width,height:900});
    await page.setContent(renderPreview(preset));
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    await expect(page.locator('a')).toHaveCount(0);
    const images=page.locator('.report-graph');
    const count=await images.count();
    expect(count).toBeGreaterThanOrEqual(2);
    expect(count).toBe(2);
    const sources=await images.evaluateAll(items=>items.map(item=>item.src));
    expect(new Set(sources).size).toBe(count);
    const headings=await page.locator('h2').allTextContents();
    expect(new Set(headings).size).toBe(headings.length);
    const attention=page.locator('.attention-section');
    await expect(attention.locator('.report-graph')).toHaveCount(0);
    const attentionBox=await attention.boundingBox(),bodyBox=await page.locator('.email-body').boundingBox();
    expect(attentionBox.width).toBeGreaterThan(bodyBox.width-45);
    await expect(page.locator('.brand-name .data-as-of')).toContainText('Data as of');
    await expect(page.locator('.report-stamp br')).toHaveCount(0);
    const stamp=await page.locator('.report-stamp').evaluate(el=>({height:el.getBoundingClientRect().height,line:parseFloat(getComputedStyle(el).lineHeight),width:el.clientWidth,scroll:el.scrollWidth}));
    expect(stamp.height).toBeLessThanOrEqual(stamp.line+1);expect(stamp.scroll).toBeLessThanOrEqual(stamp.width);
    if(width>600) {
      const charts=await images.evaluateAll(nodes=>nodes.map(el=>el.getBoundingClientRect().toJSON()));
      expect(Math.abs(charts[0].y-charts[1].y)).toBeLessThan(1);
      expect(Math.abs(charts[0].width-charts[1].width)).toBeLessThan(1);
      expect(Math.abs(charts[0].height-charts[1].height)).toBeLessThan(1);
    }
    await expect(page.locator('.metric-comparison')).toHaveCount(4);
    expect(await page.locator('.metric-content').evaluateAll(items=>Math.max(...items.map(el=>el.offsetHeight))-Math.min(...items.map(el=>el.offsetHeight)))).toBeLessThanOrEqual(1);
    for (const row of await page.locator('.panel-row').all()) {
      const cells=await row.locator(':scope > tbody > tr > .panel-cell').evaluateAll(items=>items.map(el=>el.getBoundingClientRect().toJSON()));
      if(cells.length===2) {
        if(width>600) {
          expect(Math.abs(cells[0].y-cells[1].y)).toBeLessThan(1);
          expect(Math.abs(cells[0].width-cells[1].width)).toBeLessThan(1);
          expect(Math.abs(cells[0].height-cells[1].height)).toBeLessThan(1);
        } else expect(cells[1].y).toBeGreaterThan(cells[0].y);
      }
    }
    if(preset==='polish_tat') {
      await expect(page.locator('.metric-label').first()).toHaveText('Resolved on time');
      await expect(page.locator('.metric-value').nth(1)).toHaveText('Under 1 hour');
      await expect(page.getByText(/Longest resolution: 8.0 days/)).toBeVisible();
    }
    if(preset==='polish_open') await expect(page.getByRole('heading',{name:'Open-case age',exact:true})).toHaveCount(1);
    await page.screenshot({path:info.outputPath(`${preset}-${colorScheme}-${width}.png`),fullPage:true});
  });
}

for(const width of [320,390,1280])test(`Email cross-year comparison remains one row at ${width}px`,async({page},info)=>{
  await page.route(/^https?:\/\//,route=>route.abort());await page.setViewportSize({width,height:900});
  await page.setContent(renderPreview('cross_year'));
  const stamp=await page.locator('.report-stamp').evaluate(el=>({height:el.offsetHeight,line:parseFloat(getComputedStyle(el).lineHeight),width:el.clientWidth,scroll:el.scrollWidth}));
  expect(stamp.height).toBeLessThanOrEqual(stamp.line+1);expect(stamp.scroll).toBeLessThanOrEqual(stamp.width);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.screenshot({path:info.outputPath(`cross-year-email-${width}.png`),fullPage:true});
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
