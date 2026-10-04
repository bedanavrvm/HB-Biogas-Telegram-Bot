'use strict';
const path=require('node:path');
const fs=require('node:fs');
const {test,expect}=require('playwright/test');
const asset=name=>path.resolve(__dirname,'../static/miniapp',name);

async function open(page,{chartsUnavailable=false}={}) {
  await page.route('https://portal-report.test/**',route=>route.fulfill({contentType:'text/html',body:'<!doctype html><html><body class="workflow-standard portal-app"><main style="max-width:1000px;margin:auto;padding:12px"><h1>Reports</h1><p>Explore workload, decisions and finance for the cases you can access.</p><div id="portal-reports-root"></div></main></body></html>'}));
  await page.goto('https://portal-report.test/portal/s/reports/');
  for(const name of ['base.css','portal.css','workflow_standard.css','portal_report_insights.css'])await page.addStyleTag({content:fs.readFileSync(asset(name),'utf8').replace(/^@import[^\r\n]*(?:\r?\n|$)/gm,'')});
  if(!chartsUnavailable)await page.addScriptTag({path:asset('vendor-chartjs-4.5.1.umd.min.js')});
  await page.addScriptTag({path:asset('components.js')});
  await page.evaluate(()=>{
    window.__calls=[];window.__downloads=[];window.__theme=null;window.__holdNext=false;window.__release=null;
    window.PortalAppShell={downloadPortalFile:v=>window.__downloads.push(v),showToast:()=>{}};
    window.MiniAppAssetLoader={loadScript:()=>Promise.reject(new Error('Synthetic asset outage'))};
    window.__result=(body)=>{
      const preset=body.preset;
      const names=preset==='pipeline'?[['stages','Cases by pipeline stage'],['received','Cases received over time'],['age','Current-stage backlog age'],['branch','Cases by branch'],['county','Cases by county']]:preset==='outcomes'?[['activity','Visits and decisions over time'],['visits','Visit outcomes'],['credit','Credit decisions'],['final','Final decisions'],['duration','Completed-stage turnaround'],['sla','Completed stages against target']]:[['activity','Order and invoice activity'],['invoice_trend','Invoice value over time'],['finance_branch','Financial comparison by branch'],['finance_county','Financial comparison by county']];
      return {preset,period:preset==='pipeline'?null:{from:'2026-10-01',to:'2026-10-04'},applied_filters:{date_mode:preset==='pipeline'?'all':'month',granularity:'month',...body.filters},filter_options:{branches:['Training branch','Other training branch'],counties:['Training county'],products:['TRAINING']},
        summary:{'Cases in scope':12,'Awaiting visit':4,'Credit analysis':3,'Invoice amount':'123456.78'},total_rows:body.filters.chart_key?4:12,shown_rows_limit:12,pagination:{page:body.page||1,pages:2,page_size:50},columns:[{key:'case_id',label:'Case reference',type:'text'},{key:'customer_name',label:'Customer name',type:'text'},{key:'branch',label:'Branch',type:'text'}],rows:[{case_id:'JBL-100',record_id:'00000000-0000-0000-0000-000000000001',customer_name:'Synthetic reporting customer',branch:'Training branch'}],
        charts:names.map(([id,title],i)=>({id,title,type:i===1?'line':'bar',unit:id==='duration'?'hours':preset==='finance'&&id!=='activity'?'KES':'cases',context:preset==='finance'?'Current recorded values for cases in this period':'Current authorized cases',labels:['Training branch','Other training branch'],bucket_keys:['training','other'],datasets:[{key:'Cases',label:'Cases',values:['4','8']}],values:['4','8'],...(id==='duration'?{sample_counts:{training:4,other:8}}:{})}))};
    };
    window.PortalMiniAppApi={postJson:async(url,body)=>{window.__calls.push({url,body});if(url.includes('export'))return {ok:true,data:{ok:true,download_url:'/synthetic-download',filename:'portal-report.xlsx'}};const response={ok:true,data:{ok:true,result:window.__result(body)}};if(window.__holdNext){window.__holdNext=false;await new Promise(resolve=>{window.__release=()=>resolve();});}return response;}};
    window.__tg={onEvent:(name,handler)=>{window.__theme=handler;},offEvent:()=>{window.__theme=null;}};
  });
  await page.addScriptTag({path:asset('portal_curated_reports.js')});
  await page.evaluate(()=>PortalMiniAppReports.load({tg:window.__tg}));
  await expect(page.locator('.portal-insight-chart')).toHaveCount(5);
}

for(const width of [320,390,430,1280])for(const preset of ['pipeline','outcomes','finance']) {
  test(`${preset} reports fit ${width}px and support chart views`,async({page},info)=>{
    await page.setViewportSize({width,height:900});await page.emulateMedia({reducedMotion:'reduce'});await open(page);
    if(preset!=='pipeline')await page.locator(`[data-preset="${preset}"]`).click();
    await expect(page.locator('[role="tab"][aria-selected="true"]')).toHaveAttribute('data-preset',preset);
    await expect(page.locator('.portal-chart-status')).toHaveCount(0);
    await expect.poll(()=>page.evaluate(()=>Object.keys(Chart.instances).length)).toBe(preset==='pipeline'?5:preset==='outcomes'?6:4);
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    await page.screenshot({path:info.outputPath(`${preset}-${width}.png`),fullPage:true});
    await page.locator('[data-action="next"]').click();await expect(page.locator('#portal-chart-position')).toContainText('2 of');
    await page.locator('[data-display="list"]').click();await expect(page.locator('#portal-insight-charts')).toHaveClass(/list/);
    await page.locator('[data-type="doughnut"]').first().click();
    expect(await page.evaluate(()=>Object.values(Chart.instances).some(c=>c.config.type==='doughnut'))).toBe(true);
    await page.evaluate(()=>{document.documentElement.style.setProperty('--tg-theme-text-color','#f4f4f8');document.documentElement.style.setProperty('--tg-theme-bg-color','#17171e');document.documentElement.style.setProperty('--tg-theme-secondary-bg-color','#20202c');document.documentElement.style.setProperty('--tg-theme-hint-color','#a8a8b3');window.__theme();});
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    await page.screenshot({path:info.outputPath(`${preset}-${width}-dark.png`),fullPage:true});
    await page.evaluate(()=>PortalMiniAppReports.unmount());expect(await page.evaluate(()=>Object.keys(Chart.instances).length)).toBe(0);
  });
}

test('draft filters cancel cleanly; drill, paging and export share applied filters',async({page})=>{
  await open(page);await page.locator('[data-action="filters"]').click();
  await page.locator('[name="branch"]').selectOption('Training branch');await page.keyboard.press('Escape');
  await page.locator('[data-action="filters"]').click();await expect(page.locator('[name="branch"]')).toHaveValue('');
  await page.locator('[name="branch"]').selectOption('Training branch');await page.locator('[name="date_mode"]').selectOption('custom');
  await page.locator('[name="from"]').fill('2026-09-01');await page.locator('[name="to"]').fill('2026-09-30');await page.getByRole('button',{name:'Apply filters',exact:true}).click();
  await expect(page.locator('.portal-report-filter-bar')).toContainText('Training branch');
  const card=page.locator('[data-chart="stages"]');await card.locator('[data-bucket]').selectOption('training');await card.getByRole('button',{name:'Show cases'}).click();
  await expect(page.locator('.portal-chart-selection')).toContainText('Training branch');await page.locator('[data-action="export"]').click();
  await expect.poll(()=>page.evaluate(()=>window.__downloads.length)).toBe(1);
  const calls=await page.evaluate(()=>window.__calls);const exported=calls.find(c=>c.url.includes('export')).body.filters;
  expect(exported).toMatchObject({branch:'Training branch',date_mode:'custom',from:'2026-09-01',to:'2026-09-30',chart_key:'stages',bucket_key:'training',series_key:'Cases'});
  await page.locator('[data-page="2"]').click();await expect.poll(()=>page.evaluate(()=>window.__calls.at(-1).body.page)).toBe(2);
  await expect(page.locator('a[href="/portal/cases/00000000-0000-0000-0000-000000000001/"]')).toContainText('JBL-100');
  await page.locator('[data-action="clear"]').click();await expect(page.locator('.portal-chart-selection')).toHaveCount(0);
});

test('stale response cannot replace a newly selected section',async({page})=>{
  await open(page);await page.evaluate(()=>{window.__holdNext=true;});await page.locator('[data-preset="outcomes"]').click();
  await expect.poll(()=>page.evaluate(()=>typeof window.__release)).toBe('function');await page.locator('[data-preset="finance"]').click();
  await expect(page.locator('[data-chart="finance_branch"]')).toHaveCount(1);await page.evaluate(()=>window.__release());
  await expect(page.locator('[data-chart="finance_branch"]')).toHaveCount(1);await expect(page.locator('[data-chart="duration"]')).toHaveCount(0);
});

test('return from a retained Case History detour rechecks data and keeps filters and page',async({page})=>{
  await open(page);await page.locator('[data-action="filters"]').click();await page.locator('[name="branch"]').selectOption('Training branch');await page.getByRole('button',{name:'Apply filters',exact:true}).click();
  await expect(page.locator('.portal-report-filter-bar')).toContainText('Training branch');await page.locator('[data-page="2"]').click();await expect.poll(()=>page.evaluate(()=>window.__calls.at(-1).body.page)).toBe(2);
  await page.evaluate(async()=>{const original=document.getElementById('portal-reports-root');PortalMiniAppReports.unmount();const history=document.createElement('div');history.textContent='Synthetic Case History';original.replaceWith(history);history.replaceWith(original);await PortalMiniAppReports.load({tg:window.__tg});});
  await expect(page.locator('.portal-report-filter-bar')).toContainText('Training branch');expect(await page.evaluate(()=>window.__calls.at(-1).body)).toMatchObject({page:2,filters:{branch:'Training branch'}});
});

test('failed chart asset leaves cases, drill selectors and exports usable',async({page})=>{
  await open(page,{chartsUnavailable:true});await expect(page.locator('.portal-chart-state').first()).toContainText('Charts unavailable');
  await expect(page.locator('.portal-report-table')).toContainText('Synthetic reporting customer');await page.locator('[data-action="export"]').click();await expect.poll(()=>page.evaluate(()=>window.__downloads.length)).toBe(1);
});

test('keyboard chart navigation, modal back handling and empty charts',async({page})=>{
  await page.emulateMedia({reducedMotion:'reduce'});await open(page);await page.locator('#portal-insight-charts').focus();await page.keyboard.press('ArrowRight');await expect(page.locator('#portal-chart-position')).toContainText('2 of');
  await page.locator('[data-action="filters"]').click();expect(await page.evaluate(()=>PortalMiniAppReports.canHandleBack())).toBe(true);await page.evaluate(()=>PortalMiniAppReports.handleBack());await expect(page.locator('[data-action="filters"]')).toBeFocused();
  await page.evaluate(()=>{const result=window.__result;window.__result=body=>{const r=result(body);r.charts.forEach(c=>{c.labels=[];c.bucket_keys=[];c.datasets=[];});r.rows=[];r.total_rows=0;return r;};return PortalMiniAppReports.load();});
  await expect(page.locator('.portal-chart-state').first()).toContainText('No matching data');await expect(page.locator('.portal-report-table')).toContainText('No cases match');
});
