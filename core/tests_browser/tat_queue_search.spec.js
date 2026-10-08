'use strict';
const fs = require('node:fs');
const path = require('node:path');
const {test, expect} = require('playwright/test');
const asset = name => path.resolve(__dirname, '../static/miniapp', name);
const source = fs.readFileSync(path.resolve(__dirname, '../templates/tat_tracker/app.html'), 'utf8');
const markup = source.slice(source.indexOf('<main class="tat-app"'), source.lastIndexOf('</main>') + 7)
  .replace(/{%[\s\S]*?%}|{{[\s\S]*?}}/g, '').replace(/<img[^>]*>/g, '');

async function mount(page, reports = false, native = false) {
  await page.route(/^https?:\/\//, route => route.abort());
  await page.setContent(`<body>${markup}</body>`);
  for (const name of ['base.css','components.css','tat_tracker.css']) await page.addStyleTag({content:fs.readFileSync(asset(name),'utf8').replace(/^@import[^\r\n]*(?:\r?\n|$)/gm,'')});
  await page.evaluate(({reports,native}) => {
    if (native) {
      window.__handlers=new Set(); window.__native={show(){this.visible=true;},hide(){this.visible=false;},setText(){},enable(){},disable(){},hideProgress(){},
        onClick(fn){__handlers.add(fn);},offClick(fn){__handlers.delete(fn);}};
      window.Telegram={WebApp:{initData:'synthetic-only',ready(){},expand(){},onEvent(){},MainButton:__native,BackButton:{show(){},hide(){},onClick(){}}}};
    }
    window.__calls = [];
    const summary = {case_id:'JBL-TEST-1',client_name:'Synthetic Applicant',national_id:'12345678',primary_phone:'712345678',branch:'Training',product:'Training product',status:'Active',amount:'10000',next_stage:'Visit',next_role:'BRO'};
    const home = body => ({queue:body.queue||'role',items:[{...summary,client_name:body.query||summary.client_name}],metrics:{role:1,total:1},pagination:{page:body.page||1,pages:1,total:1,page_size:10},visibility:{}});
    window.TatMiniAppApi = {postJson:async (url, body) => {
      window.__calls.push({url,body});
      if(url.includes('bootstrap')) return {ok:true,data:{authorized:true,user:{name:'Synthetic Officer',roles:['BRO'],capabilities:['tat.home.view','tat.case.search', ...(reports?['tat.reports.view','tat.reports.export','tat.reports.insight.trend']:[])]},products:[],branches:[],statuses:[],...home({})}};
      if(url.includes('/home/')) { if(body.query==='slow') await new Promise(resolve=>setTimeout(resolve,650)); return {ok:true,data:home(body)}; }
      if(url.includes('/detail/')) return {ok:true,data:{summary:{...summary,primary_phone:window.__phone??summary.primary_phone},can_correct_details:true,correction_branches:['Training'],fields:[],events:[]}};
      return {ok:true,data:{}};
    }};
    if (reports) window.fetch = async (url, options) => {
      const body = JSON.parse(options.body); __calls.push({url,body});
      const chart = {id:'trend',title:'Completed actions',basis:'completed_stage_actions',sample_count:2,labels:['2026-10-01','2026-10-02'],
        series:window.__multiTrend ? [{key:'created',label:'Created',values:[1,1]},{key:'disbursed',label:'Disbursed',values:[3,4]}] : [{key:'completed_actions',label:'Actions',values:[1,1]}],drilldown:{available:!window.__historical,reason:'Individual cases aren’t available for this historical total.'}};
      const result = url.includes('/summary/') ? {response_mode:'focused_v1',metrics:{},filters:{},charts:{trend:chart}}
        : {results:[{case_id:body.drill_bucket?'TAT-SELECTED':'TAT-ALL',client_name:'Synthetic Applicant'}],count:body.drill_bucket?1:30,stage_columns:[]};
      return new Response(JSON.stringify({ok:true,data:result}));
    };
  }, {reports,native});
  if (reports) for (const name of ['vendor-chartjs-4.5.1.umd.min.js','vendor-ag-grid-community-36.1.0.min.js']) await page.addScriptTag({path:asset(name)});
  for (const name of ['utils.js','components.js','tat_formatters.js','tat_bro_assignment.js','tat_case_validation.js','tat_tracker.js']) await page.addScriptTag({path:asset(name)});
  await expect(page.locator('#queueList')).toContainText('Synthetic Applicant');
}

test('real TAT queue searches the selected queue, ignores stale responses and preserves query on return', async({page})=>{
  await mount(page);
  await expect(page.locator('#trackerTabs [data-view="search"]')).toHaveCount(0);
  await page.locator('#queueSearchInput').fill('slow');
  await expect.poll(()=>page.evaluate(()=>window.__calls.some(c=>c.body.query==='slow'))).toBe(true);
  await page.locator('#queueSearchInput').fill('Current');
  await expect(page.locator('#queueList')).toContainText('Current');
  await page.waitForTimeout(700);
  await expect(page.locator('#queueList')).not.toContainText('slow');
  await page.locator('[data-home-queue="all"]').click();
  await expect.poll(()=>page.evaluate(()=>window.__calls.filter(c=>c.url.includes('/home/')).at(-1).body)).toMatchObject({query:'Current',queue:'all',page:1});
  await page.locator('#queueList .case-name').first().click();
  await expect(page.locator('#detailView')).toHaveClass(/active/);
  await expect(page.locator('#detailSummary a[href="tel:+254712345678"]')).toHaveCount(1);
  await page.locator('#backBtn').click();
  await expect(page.locator('#queueSearchInput')).toHaveValue('Current');
  await page.locator('#queueSearchInput').fill('');
  await expect(page.locator('#queueList')).toContainText('Synthetic Applicant');
});

for(const width of [320,360,390,430,768,1280]) test(`TAT correction Cancel stays right-aligned at ${width}px`,async({page},info)=>{
  await page.setViewportSize({width,height:850}); await mount(page);
  await page.locator('#queueList .case-name').first().click();
  await page.locator('#correctCaseDetailsBtn').click();
  for(const theme of ['light','dark']) {
    await page.evaluate(value=>{document.documentElement.dataset.miniappColorScheme=value;},theme);
    const header=await page.locator('#caseCorrectionPanel .section-head').boundingBox(), cancel=await page.locator('#cancelCaseCorrectionBtn').boundingBox();
    expect(Math.abs(header.x+header.width-cancel.x-cancel.width-8)).toBeLessThan(2);
    expect(Math.abs(cancel.y+cancel.height/2-header.y-header.height/2)).toBeLessThan(2);
    await page.screenshot({path:info.outputPath(`tat-correction-${width}-${theme}.png`),fullPage:true});
  }
  await page.locator('#cancelCaseCorrectionBtn').click();
  await expect(page.locator('#caseCorrectionPanel')).toBeHidden();
});

test('TAT native correction submit retains validation and hides on Cancel',async({page})=>{
  await mount(page,false,true);
  await page.locator('#queueList .case-name').first().click();
  await page.locator('#correctCaseDetailsBtn').click();
  await expect.poll(()=>page.evaluate(()=>__native.visible&&__handlers.size===1)).toBe(true);
  await page.locator('#caseCorrectionForm [name=client_name]').fill('');
  await page.evaluate(()=>[...__handlers][0]());
  await expect(page.locator('#caseCorrectionForm [name=client_name]')).toHaveAttribute('aria-invalid','true');
  await page.locator('#cancelCaseCorrectionBtn').click();
  await expect.poll(()=>page.evaluate(()=>__handlers.size)).toBe(0);
});

test('real TAT chart click narrows the grid, survives paging and clears with base filters', async ({page}) => {
  await mount(page,true);
  await page.locator('#dashboardWorkspaceBtn').click();
  await expect(page.locator('#tatReportPage')).toHaveText('Page 1 of 2');
  const clickPoint = async () => {
    const point = await page.evaluate(() => {
      const chart=Chart.getChart(document.getElementById('tatTrendChart')); chart.stop(); chart.update('none');
      const p=chart.getDatasetMeta(0).data[0];
      const box=chart.canvas.getBoundingClientRect(); return {x:box.left+p.x,y:box.top+p.y};
    });
    await page.mouse.click(point.x,point.y);
  };
  await clickPoint();
  await expect.poll(() => page.evaluate(() => __calls.filter(c=>c.url.includes('/reports/cases/')).at(-1).body)).toMatchObject({drill_chart:'trend',drill_series:'completed_actions',drill_bucket:'2026-10-01',page:1});
  await expect(page.locator('#tatHeatmapSelection')).toBeVisible();
  await expect(page.locator('#tatReportPage')).toHaveText('Page 1 of 1');
  await page.locator('#tatHeatmapSelection').click();
  await expect(page.locator('#tatReportPage')).toHaveText('Page 1 of 2');
  await clickPoint();
  await page.locator('#openTatReportFiltersBtn').click();
  await page.locator('#tatReportFilters [name=search]').fill('Training');
  await expect(page.locator('#tatHeatmapSelection')).toBeHidden();
  await expect.poll(() => page.evaluate(() => __calls.filter(c=>c.url.includes('/reports/cases/')).at(-1).body.drill_chart || '')).toBe('');
});

test('TAT chart selection identifies the clicked series, not the first tooltip series', async ({page}) => {
  await mount(page,true);
  await page.evaluate(() => { window.__multiTrend=true; });
  await page.locator('#dashboardWorkspaceBtn').click();
  await expect(page.locator('#tatReportPage')).toHaveText('Page 1 of 2');
  const point=await page.evaluate(() => {
    const chart=Chart.getChart(document.getElementById('tatTrendChart')); chart.stop(); chart.update('none');
    const p=chart.getDatasetMeta(1).data[0], box=chart.canvas.getBoundingClientRect();
    return {x:box.left+p.x,y:box.top+p.y};
  });
  await page.mouse.click(point.x,point.y);
  await expect.poll(() => page.evaluate(() => __calls.filter(c=>c.url.includes('/reports/cases/')).at(-1).body)).toMatchObject({drill_series:'disbursed',drill_bucket:'2026-10-01'});
});

test('TAT historical totals explain unavailable case drilldown without changing the grid', async ({page}) => {
  await mount(page,true);
  await page.evaluate(() => { window.__historical=true; });
  await page.locator('#dashboardWorkspaceBtn').click();
  await expect(page.locator('#tatReportPage')).toHaveText('Page 1 of 2');
  const point=await page.evaluate(() => {
    const chart=Chart.getChart(document.getElementById('tatTrendChart')); chart.stop(); chart.update('none');
    const p=chart.getDatasetMeta(0).data[0], box=chart.canvas.getBoundingClientRect();
    return {x:box.left+p.x,y:box.top+p.y};
  });
  await page.mouse.click(point.x,point.y);
  await expect(page.locator('#tatReportPage')).toHaveText('Page 1 of 2');
  expect(await page.evaluate(() => __calls.some(c=>c.body.drill_chart))).toBe(false);
  await expect(page.getByText('Individual cases aren’t available for this historical total.',{exact:true}).first()).toBeVisible();
});

test('TAT report calendar controls use the shared period calculation',async({page})=>{
  await mount(page);
  await page.evaluate(()=>{document.querySelectorAll('.view').forEach(n=>n.classList.remove('active'));document.getElementById('dashboardView').classList.add('active');document.getElementById('tatReportFilterOverlay').hidden=false;});
  await page.locator('#tatReportFilters [name="date_mode"]').selectOption('quarter');
  await page.locator('#tatReportFilters [name="year"]').fill('2025');
  await page.locator('#tatReportFilters [name="quarter"]').selectOption('3');
  expect(await page.locator('#tatReportFilters [name="date_from"]').inputValue()).toBe('2025-07-01');
  expect(await page.locator('#tatReportFilters [name="date_to"]').inputValue()).toBe('2025-09-30');
  await expect(page.locator('#tatReportFilters label[data-report-filter="granularity"]')).toHaveCount(0);
});

test('TAT detail does not make missing or masked contacts dialable',async({page})=>{
  await mount(page);
  for(const phone of ['', '07******78', 'not a phone']) {
    await page.evaluate(value=>{window.__phone=value;},phone);
    await page.locator('#queueList .case-card').first().click();
    await expect(page.locator('#detailSummary a[href^="tel:"]')).toHaveCount(0);
    await page.locator('#backBtn').click();
  }
});
