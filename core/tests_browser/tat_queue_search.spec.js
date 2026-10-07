'use strict';
const fs = require('node:fs');
const path = require('node:path');
const {test, expect} = require('playwright/test');
const asset = name => path.resolve(__dirname, '../static/miniapp', name);
const source = fs.readFileSync(path.resolve(__dirname, '../templates/tat_tracker/app.html'), 'utf8');
const markup = source.slice(source.indexOf('<main class="tat-app"'), source.lastIndexOf('</main>') + 7)
  .replace(/{%[\s\S]*?%}|{{[\s\S]*?}}/g, '').replace(/<img[^>]*>/g, '');

async function mount(page) {
  await page.route(/^https?:\/\//, route => route.abort());
  await page.setContent(`<body>${markup}</body>`);
  for (const name of ['base.css','components.css','tat_tracker.css']) await page.addStyleTag({content:fs.readFileSync(asset(name),'utf8').replace(/^@import[^\r\n]*(?:\r?\n|$)/gm,'')});
  await page.evaluate(() => {
    window.__calls = [];
    const summary = {case_id:'JBL-TEST-1',client_name:'Synthetic Applicant',national_id:'12345678',primary_phone:'712345678',branch:'Training',product:'Training product',status:'Active',amount:'10000',next_stage:'Visit',next_role:'BRO'};
    const home = body => ({queue:body.queue||'role',items:[{...summary,client_name:body.query||summary.client_name}],metrics:{role:1,total:1},pagination:{page:body.page||1,pages:1,total:1,page_size:10},visibility:{}});
    window.TatMiniAppApi = {postJson:async (url, body) => {
      window.__calls.push({url,body});
      if(url.includes('bootstrap')) return {ok:true,data:{authorized:true,user:{name:'Synthetic Officer',roles:['BRO'],capabilities:['tat.home.view','tat.case.search']},products:[],branches:[],statuses:[],...home({})}};
      if(url.includes('/home/')) { if(body.query==='slow') await new Promise(resolve=>setTimeout(resolve,650)); return {ok:true,data:home(body)}; }
      if(url.includes('/detail/')) return {ok:true,data:{summary:{...summary,primary_phone:window.__phone??summary.primary_phone},fields:[],events:[]}};
      return {ok:true,data:{}};
    }};
  });
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
  await page.locator('#queueList .case-card').first().click();
  await expect(page.locator('#detailView')).toHaveClass(/active/);
  await expect(page.locator('#detailSummary a[href="tel:+254712345678"]')).toHaveCount(1);
  await page.locator('#backBtn').click();
  await expect(page.locator('#queueSearchInput')).toHaveValue('Current');
  await page.locator('#queueSearchInput').fill('');
  await expect(page.locator('#queueList')).toContainText('Synthetic Applicant');
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
