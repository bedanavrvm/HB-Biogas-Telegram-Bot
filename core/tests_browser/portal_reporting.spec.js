'use strict';
const path=require('node:path');
const fs=require('node:fs');
const {test,expect}=require('playwright/test');
const asset=name=>path.resolve(__dirname,'../static/miniapp',name);

async function open(page,{chartsUnavailable=false}={}) {
  await page.route('https://portal-report.test/**',route=>route.fulfill({contentType:'text/html',body:'<!doctype html><html><body class="workflow-standard portal-app"><main style="max-width:1000px;margin:auto;padding:12px"><div id="portal-reports-root"></div></main></body></html>'}));
  await page.goto('https://portal-report.test/portal/s/reports/');
  for(const name of ['base.css','portal.css','workflow_standard.css','portal_report_insights.css'])await page.addStyleTag({content:fs.readFileSync(asset(name),'utf8').replace(/^@import[^\r\n]*(?:\r?\n|$)/gm,'')});
  if(!chartsUnavailable)await page.addScriptTag({path:asset('vendor-chartjs-4.5.1.umd.min.js')});
  await page.addScriptTag({path:asset('components.js')});
  await page.addScriptTag({path:asset('portal_helpers.js')});
  await page.addScriptTag({path:asset('ag_grid_zoom.js')});
  await page.addScriptTag({path:asset('vendor-ag-grid-community-36.1.0.min.js')});
  for(const name of ['vendor-ag-grid-community-36.1.0.min.css','vendor-ag-grid-quartz-font-36.1.0.min.css','vendor-ag-grid-theme-quartz-36.1.0.min.css'])await page.addStyleTag({path:asset(name)});
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

for(const width of [320,360,390,430,768,1280])for(const preset of ['pipeline','outcomes','finance']) {
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
    await page.locator('.portal-chart-settings summary').first().click();
    await page.locator('[data-type="doughnut"]').first().click();
    expect(await page.evaluate(()=>Object.values(Chart.instances).some(c=>c.config.type==='doughnut'))).toBe(true);
    await page.evaluate(()=>{document.documentElement.style.setProperty('--tg-theme-text-color','#f4f4f8');document.documentElement.style.setProperty('--tg-theme-bg-color','#17171e');document.documentElement.style.setProperty('--tg-theme-secondary-bg-color','#20202c');document.documentElement.style.setProperty('--tg-theme-hint-color','#a8a8b3');window.__theme();});
    await expect(page.locator('#portal-report-grid .ag-row').first()).toBeVisible();
    await expect(page.locator('#portal-report-grid .ag-cell[col-id="customer_name"]').first()).toHaveCSS('color','rgb(244, 244, 248)');
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
  const card=page.locator('[data-chart="stages"]');await card.locator('.portal-chart-cases summary').click();await card.locator('[data-bucket]').selectOption('training');await card.getByRole('button',{name:'Show cases'}).click();
  await expect(page.locator('.portal-chart-selection')).toContainText('Training branch');await page.locator('[data-action="export"]').click();
  await expect.poll(()=>page.evaluate(()=>window.__downloads.length)).toBe(1);
  const calls=await page.evaluate(()=>window.__calls);const exported=calls.find(c=>c.url.includes('export')).body.filters;
  expect(exported).toMatchObject({branch:'Training branch',date_mode:'custom',from:'2026-09-01',to:'2026-09-30',chart_key:'stages',bucket_key:'training',series_key:'Cases'});
  await page.locator('[data-page="2"]').click();await expect.poll(()=>page.evaluate(()=>window.__calls.at(-1).body.page)).toBe(2);
  await expect(page.locator('#portal-report-grid a[href="/portal/cases/00000000-0000-0000-0000-000000000001/"]')).toContainText('JBL-100');
  await page.locator('[data-action="clear"]').click();await expect(page.locator('.portal-chart-selection')).toHaveCount(0);
});

async function clickChartDatum(page, chartId, index=0, dataset=0) {
  const canvas=page.locator(`[data-chart="${chartId}"] canvas`);
  await canvas.scrollIntoViewIfNeeded();
  const point=await canvas.evaluate((node,{index,dataset})=>{
    const chart=Chart.getChart(node),element=chart.getDatasetMeta(dataset).data[index];
    const center=element.getCenterPoint(),rect=node.getBoundingClientRect();
    return {x:rect.left+center.x,y:rect.top+center.y};
  },{index,dataset});
  await page.mouse.click(point.x,point.y);
}

test('real bar and line clicks filter cases in place, preserve table state and export selection',async({page})=>{
  await page.setViewportSize({width:390,height:844});await page.emulateMedia({reducedMotion:'reduce'});await open(page);
  await page.evaluate(()=>{window.__gridNode=document.querySelector('#portal-report-grid');window.__chartIds=Object.keys(Chart.instances);});
  await clickChartDatum(page,'stages');
  await expect(page.locator('.portal-chart-selection')).toContainText('Training branch');
  await expect.poll(()=>page.evaluate(()=>window.__calls.at(-1).body.filters.bucket_key)).toBe('training');
  expect(await page.evaluate(()=>document.querySelector('#portal-report-grid')===window.__gridNode)).toBe(true);
  expect(await page.evaluate(()=>Object.keys(Chart.instances))).toEqual(await page.evaluate(()=>window.__chartIds));
  await expect(page.getByRole('region',{name:'Case results'}).or(page.locator('.portal-curated-results'))).toBeFocused();
  await page.locator('[data-miniapp-table-zoom-in]').click();
  await page.getByRole('button',{name:'Next',exact:true}).click();
  await expect(page.locator('[data-miniapp-table-zoom-reset]')).toHaveText('110%');
  await expect(page.locator('#portal-report-grid .ag-cell[col-id="row_number"]').first()).toHaveText('51');
  await page.locator('[data-action="export"]').click();
  expect(await page.evaluate(()=>window.__calls.at(-1).body.filters.chart_key)).toBe('stages');
  await page.locator('[data-action="clear"]').click();await expect(page.locator('.portal-chart-selection')).toHaveCount(0);
  await page.locator('[data-action="next"]').click();await expect(page.locator('#portal-chart-position')).toHaveText('2 of 5');
  await clickChartDatum(page,'received',1);
  await expect.poll(()=>page.evaluate(()=>window.__calls.at(-1).body.filters.chart_key)).toBe('received');
  expect(await page.evaluate(()=>window.__calls.at(-1).body.filters.bucket_key)).toBe('other');
  await expect(page.locator('#portal-chart-position')).toHaveText('2 of 5');
  expect(await page.evaluate(()=>document.querySelector('#portal-report-grid')===window.__gridNode)).toBe(true);
});

for(const count of [0,1,7,8,50])test(`grid uses space appropriate to ${count} results`,async({page})=>{
  await page.setViewportSize({width:320,height:844});await open(page);
  await page.evaluate(count=>{const original=window.__result;window.__result=body=>{const r=original(body);r.total_rows=count;r.pagination.pages=1;r.rows=Array.from({length:count},(_,i)=>({...r.rows[0],case_id:`JBL-${100+i}`}));return r;};return PortalMiniAppReports.load();},count);
  const height=await page.locator('#portal-report-grid').evaluate(n=>n.offsetHeight);
  expect(height).toBeLessThanOrEqual(36+Math.max(1,Math.min(8,count))*36+20);
  if(count>=8)await expect(page.locator('#portal-report-grid .ag-row[row-index="7"]')).toBeVisible();
  if(!count)await expect(page.locator('#portal-report-grid')).toContainText('No cases match these filters.');
  await expect(page.locator('.pagination')).toBeHidden();
});

test('mobile charts have no offscreen-card height and search sits next to results',async({page},info)=>{
  await page.setViewportSize({width:320,height:844});await open(page);
  const box=await page.locator('#portal-insight-charts').boundingBox(),card=await page.locator('[data-chart="stages"]').boundingBox();
  expect(box.height-card.height).toBeLessThan(3);
  expect(card.height).toBeLessThan(270);
  const search=await page.locator('#portal-report-search').boundingBox(),grid=await page.locator('#portal-report-grid').boundingBox();
  expect(search.y).toBeGreaterThan(card.y+card.height);
  expect(grid.y-search.y-search.height).toBeLessThan(65);
  await page.screenshot({path:info.outputPath('compact-results-320.png'),fullPage:true});
});

test('failed chart selection retains results and retry updates the same grid',async({page})=>{
  await open(page);
  await page.evaluate(()=>{
    window.__savedGrid=document.querySelector('#portal-report-grid');
    const original=PortalMiniAppApi.postJson;let fail=true;
    PortalMiniAppApi.postJson=async(...args)=>{if(fail){fail=false;throw new Error('Synthetic network failure');}return original(...args);};
  });
  await clickChartDatum(page,'stages');
  await expect(page.locator('.portal-report-status')).toContainText('Synthetic network failure');
  await expect(page.locator('#portal-report-grid')).toContainText('Synthetic reporting customer');
  await page.getByRole('button',{name:'Try again',exact:true}).click();
  await expect(page.locator('.portal-chart-selection')).toContainText('Training branch');
  expect(await page.evaluate(()=>window.__savedGrid===document.querySelector('#portal-report-grid'))).toBe(true);
});

test('latest chart selection wins and empty plot clicks do not change filters',async({page})=>{
  await open(page);await page.evaluate(()=>{window.__holdNext=true;});
  await clickChartDatum(page,'stages',0);
  await expect.poll(()=>page.evaluate(()=>Boolean(window.__release))).toBe(true);
  await clickChartDatum(page,'stages',1);
  await expect(page.locator('.portal-chart-selection')).toContainText('Other training branch');
  await page.evaluate(()=>window.__release());
  await expect(page.locator('.portal-chart-selection')).toContainText('Other training branch');
  const calls=await page.evaluate(()=>window.__calls.length);
  await page.locator('[data-chart="stages"] canvas').click({position:{x:2,y:2}});
  expect(await page.evaluate(()=>window.__calls.length)).toBe(calls);
});

test('mobile controls align, search survives filters, and the grid fits eight rows',async({page},info)=>{
  await page.setViewportSize({width:320,height:844});await open(page);
  await page.locator('#portal-report-search').fill('Synthetic');
  await expect.poll(()=>page.evaluate(()=>window.__calls.at(-1).body.filters.search)).toBe('Synthetic');
  await expect(page.locator('#portal-report-search')).toBeFocused();
  const heading=await page.locator('.portal-report-heading').boundingBox(),exportButton=await page.locator('[data-action="export"]').boundingBox();
  expect(exportButton.width).toBe(40);expect(Math.abs(exportButton.x+exportButton.width-heading.x-heading.width)).toBeLessThan(2);
  const chartTitle=await page.locator('[data-chart="stages"] h3').boundingBox(),settings=await page.locator('[data-chart="stages"] .portal-chart-settings summary').boundingBox();
  expect(Math.abs(chartTitle.y-settings.y)).toBeLessThan(12);
  await page.locator('[data-action="filters"]').click();await page.locator('[name="date_mode"]').selectOption('custom');
  await page.locator('[name="from"]').fill('2026-10-01');await page.locator('[name="to"]').fill('2026-10-04');
  await expect(page.locator('[data-date-display="from"]')).toHaveText('01 Oct 2026');
  const title=await page.locator('#portal-report-filter-title').boundingBox(),close=await page.locator('[data-action="close"]').boundingBox();
  expect(Math.abs(title.y-close.y)).toBeLessThan(20);expect(close.x).toBeGreaterThan(title.x+title.width);
  await page.screenshot({path:info.outputPath('report-filters-320.png')});
  await page.getByRole('button',{name:'Apply filters',exact:true}).click();
  await expect.poll(()=>page.evaluate(()=>window.__calls.at(-1).body.filters.search)).toBe('Synthetic');
  await page.evaluate(()=>{const result=window.__result;window.__result=body=>{const r=result(body);r.rows=Array.from({length:12},(_,i)=>({...r.rows[0],case_id:`JBL-${100+i}`,customer_name:`Training customer ${i+1}`}));return r;};return PortalMiniAppReports.load();});
  await expect(page.locator('#portal-report-grid .ag-row[row-index="7"]')).toBeVisible();
  await page.locator('[data-miniapp-table-zoom-in]').click();await expect(page.locator('[data-miniapp-table-zoom-reset]')).toHaveText('110%');
  await expect(page.locator('#portal-report-grid .ag-row[row-index="7"]')).toBeVisible();
  await page.screenshot({path:info.outputPath('report-eight-rows-320.png'),fullPage:true});
});

test('search debounce is cancelled when reports unmount',async({page})=>{
  await open(page);await page.locator('#portal-report-search').fill('Unsubmitted');
  const before=await page.evaluate(()=>{PortalMiniAppReports.unmount();return window.__calls.length;});
  await page.waitForTimeout(450);expect(await page.evaluate(()=>window.__calls.length)).toBe(before);
});

test('time grouping uses applied filters and chart options remain collapsed',async({page})=>{
  await open(page);await expect(page.locator('[data-chart="stages"] [data-granularity]')).toHaveCount(0);
  await page.locator('[data-action="next"]').click();
  await expect(page.locator('[data-chart="received"] [data-granularity="week"]')).toBeHidden();
  await page.locator('[data-chart="received"] .portal-chart-settings summary').click();
  await page.locator('[data-chart="received"] [data-granularity="week"]').click();
  await expect.poll(()=>page.evaluate(()=>window.__calls.at(-1).body.filters.granularity)).toBe('week');
  await expect(page.locator('[data-chart="received"] [data-granularity="week"]')).toHaveAttribute('aria-pressed','true');
  await expect(page.locator('[data-chart="received"] .portal-chart-settings')).not.toHaveAttribute('open');
});

test('holding a report cell copies its value and confirms it',async({page})=>{
  await open(page);
  await page.evaluate(()=>{window.__copied=[];window.__toasts=[];Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async value=>window.__copied.push(value)}});window.PortalAppShell.showToast=message=>window.__toasts.push(message);});
  const cell=page.locator('#portal-report-grid .ag-row[row-index="0"] [col-id="customer_name"]');
  await cell.scrollIntoViewIfNeeded();const box=await cell.boundingBox();
  await page.mouse.move(box.x+10,box.y+10);await page.mouse.down();await page.waitForTimeout(550);await page.mouse.up();
  await expect.poll(()=>page.evaluate(()=>window.__copied)).toEqual(['Synthetic reporting customer']);
  await expect.poll(()=>page.evaluate(()=>window.__toasts)).toContain('Synthetic reporting customer copied');
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
  await expect(page.locator('#portal-report-grid')).toContainText('Synthetic reporting customer');await page.locator('[data-action="export"]').click();await expect.poll(()=>page.evaluate(()=>window.__downloads.length)).toBe(1);
});

test('keyboard chart navigation, modal back handling and empty charts',async({page})=>{
  await page.emulateMedia({reducedMotion:'reduce'});await open(page);await page.locator('#portal-insight-charts').focus();await page.keyboard.press('ArrowRight');await expect(page.locator('#portal-chart-position')).toContainText('2 of');
  await page.locator('[data-action="filters"]').click();expect(await page.evaluate(()=>PortalMiniAppReports.canHandleBack())).toBe(true);await page.evaluate(()=>PortalMiniAppReports.handleBack());await expect(page.locator('[data-action="filters"]')).toBeFocused();
  await page.evaluate(()=>{const result=window.__result;window.__result=body=>{const r=result(body);r.charts.forEach(c=>{c.labels=[];c.bucket_keys=[];c.datasets=[];});r.rows=[];r.total_rows=0;return r;};return PortalMiniAppReports.load();});
  await expect(page.locator('.portal-chart-state').first()).toContainText('No matching data');await expect(page.locator('#portal-report-grid')).toContainText('No cases match');
});

test('Email action shares real Portal search/drill filters and stays beside export',async({page},info)=>{
  await page.setViewportSize({width:320,height:900});await open(page);
  await page.addStyleTag({path:asset('report_email_export.css')});await page.addScriptTag({path:asset('report_email_export.js')});
  await page.evaluate(()=>{const post=PortalMiniAppApi.postJson;PortalMiniAppApi.postJson=async(url,body)=>{
    if(url.includes('/email/')){window.__calls.push({url,body});return {ok:true,data:{ok:true,status:'accepted',delivery_id:'synthetic'}};}return post(url,body);
  };});
  await page.locator('#portal-report-search').fill('Synthetic');await page.waitForTimeout(450);
  await page.getByRole('button',{name:'Email report',exact:true}).click();await page.getByLabel('Email address').fill('management@example.invalid');
  await page.screenshot({path:info.outputPath('portal-real-email-320.png'),fullPage:true});
  await page.getByRole('button',{name:'Send',exact:true}).click();await expect(page.locator('.report-email-dialog [role=status]')).toHaveText('Accepted for delivery.');
  expect(await page.evaluate(()=>window.__calls.at(-1).body.filters.search)).toBe('Synthetic');
  await page.keyboard.press('Escape');await expect(page.locator('dialog.report-email-dialog')).toHaveCount(0);
});
