'use strict';
const fs = require('node:fs');
const path = require('node:path');
const { test, expect } = require('playwright/test');
const root = path.resolve(__dirname, '../..');
const asset = name => path.join(root, 'core/static/miniapp', name);
const { initData } = require('./fixtures/local_mcp_fixtures.js');

async function openReport(page) {
  const template = fs.readFileSync(path.join(root, 'core/templates/complaint_cases/app.html'), 'utf8')
    .replace('{% include "complaint_cases/lucide_icons.html" %}', fs.readFileSync(path.join(root, 'core/templates/complaint_cases/lucide_icons.html'), 'utf8'))
    .replace("{% static 'miniapp/jawabu-logo.png' %}", `data:image/png;base64,${fs.readFileSync(asset('jawabu-logo.png')).toString('base64')}`)
    .replace(/{#[\s\S]*?#}/g, '').replace(/{%[^%]*%}/g, '')
    .replace(/<script[^>]*>[\s\S]*?<\/script>/g, '').replace(/<link[^>]*>/g, '');
  await page.setContent(template);
  await page.addStyleTag({ path: asset('base.css') });
  await page.addStyleTag({ path: asset('vendor-ag-grid-community-36.1.0.min.css') });
  await page.addStyleTag({ path: asset('vendor-ag-grid-theme-quartz-36.1.0.min.css') });
  await page.addStyleTag({ path: asset('complaint_cases.css') });
  await page.evaluate(initData => {
    document.body.dataset.groupId = '-100-synthetic-report';
    const app = { initData, BackButton: { onClick() {}, show() {}, hide() {} }, onEvent() {} };
    window.MiniAppUtils = { initTelegram: () => app, setCloseProtection() {}, haptic() {}, bindMiniAppTheme(_app, handler) {window.__reportThemeChanged=handler;} };
    window.__reportQueries = [];
    const summary = { total: 12, pending: 8, resolved: 4, time_granularity: 'month',
      filter_options: { branches:[{label:'Training branch',count:12}], categories:[{label:'A long synthetic complaint category used to check wrapping',count:12}] },
      by_category:[{label:'A long synthetic complaint category used to check wrapping',count:12}],
      activity:[{label:'2026-09',received:12,resolved:4}],
      open_age:[{key:'under_3',label:'Under 3 days',count:8}],
      timing:{median_resolution_hours:30,on_time_percent:75,resolution_count:4,on_time:3,late:1,response_count:3,response_unavailable:9},
      resolution_trend:[{label:'2026-09',hours:30,count:4}],
      response_trend:[{label:'2026-09',hours:5,count:3}],
      resolution_by_category:[{label:'A long synthetic complaint category used to check wrapping',hours:30,count:4}],
      reopenings:[{label:'2026-09',count:2}] };
    window.ComplaintCasesMiniAppApi = {
      async postJson(route, payload) {
        if (route === 'bootstrap/') return { data: { actor:{name:'Training IT',role:'IT',capabilities:['complaint.queue.view','complaint.reports.view','complaint.case.export']},counts:{},branches:[],categories:[],category_catalogue:[] } };
        if (route === 'cases/') return {cases:[],pagination:{page:1,pages:1,total:0},start_index:0};
        window.__reportQueries.push({route,payload}); return {};
      },
      async getJson(route, params) {
        window.__reportQueries.push({route,params});
        if(route === 'reports/summary/') return summary;
        const count=params.metric ? 4 : 12;
        return {results:Array.from({length:count},(_,index)=>({complaint_id:`CMP-TRAIN-${index+1}`,date_reported:'2026-09-12T08:00:00+03:00',status:index<4?'CLOSED':'OPEN',customer_name:`Training customer ${index+1}`,customer_id:'000000',phone_number:'0700000000',branch_region:'Training branch',complaint_category:'Synthetic product issue',days_open:4,resolution_hours:index<4?30:null,hb_response_hours:5})),count,page:1,page_size:50};
      },
    };
  }, initData);
  await page.addScriptTag({ path: asset('vendor-chartjs-4.5.1.umd.min.js') });
  await page.addScriptTag({ path: path.join(root, 'node_modules/ag-grid-community/dist/ag-grid-community.min.js') });
  await page.addScriptTag({ path: asset('complaint_report_charts.js') });
  await page.addScriptTag({ path: asset('complaint_cases.js') });
  await expect(page.locator('#globalWorkspaceBtn')).toBeVisible();
  await page.locator('#globalWorkspaceBtn').click();
  await expect(page.locator('#globalResultCount')).toHaveText('12 complaints found');
}

for (const width of [320, 360, 390, 430, 768, 1280]) {
  test(`complaint reports fit ${width}px, carousel and drill-down stay aligned`, async ({ page }, testInfo) => {
    const errors=[];page.on('pageerror',error=>errors.push(error.message));
    await page.setViewportSize({width,height:850});
    await openReport(page);
    for(const dark of [false,true]) {
      await page.evaluate(dark=>{document.documentElement.dataset.miniappColorScheme=dark?'dark':'light';window.__reportThemeChanged();},dark);
      await expect(page.locator('#complaintChartPosition')).toHaveText('1 of 8');
      await expect(page.locator('[data-complaint-chart="activity"]')).toBeVisible();
      expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
      if(dark)expect(await page.locator('#complaintReportGrid .ag-root-wrapper').evaluate(node=>getComputedStyle(node).backgroundColor)).not.toBe('rgb(255, 255, 255)');
      await page.screenshot({path:testInfo.outputPath(`report-${width}-${dark?'dark':'light'}.png`),fullPage:true});
    }
    await page.locator('#openComplaintReportFilters').click();
    await expect(page.locator('#globalFilters select[name="date_basis"]')).toBeVisible();
    const heading=await page.locator('.complaint-report-filter-head').boundingBox();
    const close=await page.locator('#closeComplaintReportFilters').boundingBox();
    expect(heading.x+heading.width-close.x-close.width).toBeLessThan(16);
    expect(Math.abs(heading.y+heading.height/2-close.y-close.height/2)).toBeLessThan(8);
    await page.screenshot({path:testInfo.outputPath(`filters-${width}.png`)});
    await page.locator('#closeComplaintReportFilters').click();
    const activity=page.locator('[data-complaint-chart="activity"]');
    await activity.locator('select[aria-label="Activity type"]').selectOption('1');
    await activity.locator('select').last().selectOption('0');
    await activity.getByRole('button',{name:'Show cases'}).click();
    await expect(page.locator('#complaintChartSelection')).toContainText('Resolved');
    await expect(page.locator('#globalResultCount')).toHaveText('4 complaints found');
    expect(await page.evaluate(()=>window.__reportQueries.filter(x=>x.route==='reports/data/').at(-1).params)).toMatchObject({date_basis:'closures',metric:'closures',date_from:'2026-09-01',date_to:'2026-09-30'});
    await page.locator('#exportResultsBtn').click();
    await expect(page.locator('#exportConfirm')).toBeVisible();
    expect(await page.evaluate(()=>window.__reportQueries.filter(x=>x.route==='reports/summary/').at(-1).params.metric)).toBe('closures');
    await page.locator('#cancelExportBtn').click();
    await expect(page.locator('#exportResultsBtn')).toBeFocused();
    await page.locator('#complaintChartSelection').click();
    await expect(page.locator('#globalResultCount')).toHaveText('12 complaints found');
    await page.evaluate(()=>{
      const form=document.getElementById('globalFilters');
      form.elements.date_mode.value='custom';form.elements.date_from.value='2026-09-10';form.elements.date_to.value='2026-09-20';
      form.dispatchEvent(new Event('submit',{cancelable:true,bubbles:true}));
    });
    await expect(page.locator('#globalResultCount')).toHaveText('12 complaints found');
    await activity.locator('select').last().selectOption('0');
    await activity.getByRole('button',{name:'Show cases'}).click();
    await expect(page.locator('#globalResultCount')).toHaveText('4 complaints found');
    expect(await page.evaluate(()=>window.__reportQueries.filter(x=>x.route==='reports/data/').at(-1).params)).toMatchObject({date_from:'2026-09-10',date_to:'2026-09-20'});
    await page.locator('#complaintChartNext').click();
    await expect(page.locator('[data-complaint-chart="age"]')).toBeVisible();
    for(let index=0;index<6;index++)await page.locator('#complaintChartNext').click();
    await expect(page.locator('#complaintChartPosition')).toHaveText('8 of 8');
    await expect(page.locator('[data-complaint-chart="reopened"]')).toBeVisible();
    await page.locator('#complaintChartPrevious').click();
    await page.locator('#complaintChartPrevious').click();
    await page.screenshot({path:testInfo.outputPath(`category-time-${width}.png`)});
    expect(errors).toEqual([]);
  });
}

test('empty timing charts remain honest and keyboard-friendly', async ({page})=>{
  await openReport(page);
  await page.evaluate(()=>window.ComplaintReportCharts.render({timing:{}},{onSelect(){},formatPeriod:value=>value}));
  await expect(page.locator('[data-complaint-chart="resolution"] .chart-state')).toHaveText('Timing unavailable for this period.');
  await expect(page.locator('[data-complaint-chart="response"] .chart-state')).toHaveText('Timing unavailable for this period.');
  await expect(page.locator('.chart-drill-controls')).toHaveCount(0);
  await page.locator('#complaintChartNext').focus();
  await page.keyboard.press('Enter');
  await expect(page.locator('#complaintChartPosition')).toHaveText('2 of 8');
});

test('trend grouping stays synchronized and chart borders match their purpose', async ({page}, info)=>{
  await page.setViewportSize({width:320,height:850});
  await openReport(page);
  await expect(page.locator('.chart-granularity select')).toHaveCount(4);
  let current = 0;
  for (const [key, grouping, target] of [['resolution','day',2], ['response','week',6], ['reopened','year',7], ['activity','month',0]]) {
    while(current !== target) {
      await page.locator(current < target ? '#complaintChartNext' : '#complaintChartPrevious').click();
      current += current < target ? 1 : -1;
    }
    await page.locator(`[data-complaint-chart="${key}"] .chart-granularity select`).selectOption(grouping);
    await expect.poll(()=>page.evaluate(()=>window.__reportQueries.filter(item=>item.route==='reports/summary/').at(-1).params.granularity)).toBe(grouping);
    expect(await page.locator('.chart-granularity select').evaluateAll(nodes=>nodes.map(node=>node.value))).toEqual(Array(4).fill(grouping));
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    await page.screenshot({path:info.outputPath(`${key}-320.png`)});
  }
  const widths = await page.evaluate(()=>Array.from(document.querySelectorAll('[data-complaint-chart] canvas')).flatMap(canvas=>{
    const chart=Chart.getChart(canvas);return chart ? chart.data.datasets.map(dataset=>({type:chart.config.type,width:dataset.borderWidth ?? Chart.defaults.elements.line.borderWidth})) : [];
  }));
  expect(widths.filter(item=>item.type==='bar').every(item=>item.width===0)).toBe(true);
  expect(widths.filter(item=>item.type==='line').every(item=>item.width>0)).toBe(true);
});
