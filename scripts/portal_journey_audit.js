/* Read-only rendered-page audit. All API traffic is synthetic, never forwarded. */
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');
const base = 'http://127.0.0.1:8007';
const output = path.resolve('test-results/portal-journey-audit');
const caseId = '10000000-0000-4000-8000-000000000001';
const batchId = '20000000-0000-4000-8000-000000000001';
const capabilities = [...new Set(fs.readFileSync('core/services/workflow_capabilities.py', 'utf8').match(/portal\.[a-z_.]+/g))];
const farmer = {id: caseId, customer_name: 'Synthetic Customer With A Deliberately Long Name', national_id: '123456', primary_phone: '254700000001', branch: 'Synthetic Branch', county: 'Synthetic County', current_pipeline_state: 'Awaiting Credit Analysis', workflow_revision: 1};
const cases = Array.from({length: 50}, (_, n) => ({farmer_id: n ? `synthetic-${n}` : caseId, customer_name: `Synthetic Customer ${n + 1} With A Long Name`, national_id: '123456', primary_phone: '254700000001', branch: 'Synthetic Branch', loan_officer: 'Synthetic Officer', payment_mode: 'LOAN-JAWABU', payment_mode_label: 'Loan - Jawabu', amount: '44500', decision: n % 3 ? 'approved' : 'pending', comment: 'Synthetic reviewed comment'}));
const batch = {id: batchId, revision: 1, status: 'draft', status_label: 'Draft', counts: {total: 50, approved: 33, pending: 17, returned: 0}, total_amount: '2225000', cases, activity: [], held_items: [], receipt_batch_id: 'synthetic-delivery'};
const meta = {capabilities, access_policy_version: 'synthetic-audit', actor: {name: 'Synthetic Tester', roles: ['IT']}, branches: ['Synthetic Branch'], counties: ['Synthetic County'], location_catalog: {branches: [], counties: [], sub_counties: []}, jbl_visit_statuses: ['Approved', 'Rejected', 'Rescheduled'], credit_decisions: ['Approved', 'Rejected', 'Deferred'], final_decisions: ['Approved', 'Rejected', 'Deferred'], imab_created_options: ['Yes', 'No'], business_date: '2026-10-01', voice_input: {enabled: false, fields: []}};
const invoices = Array.from({length: 12}, (_, n) => ({id: `synthetic-invoice-${n}`, customer_name: `Synthetic Invoice Holder ${n}`, invoice_no: `SYN-${n}`, customer_id: '123456', status: 'unmatched', invoice_amount: '44500', balance_due: '44500', created_at: '2026-10-01T09:00:00+03:00', duplicate_count: n ? 0 : 2, payment_readiness: {}}));
function payload(url) {
  const p = url.pathname.replace('/api/portal', '');
  if (p === '/meta/') return meta;
  if (p === '/dashboard/') return {as_of: '2026-10-01T09:00:00+03:00', scope: {label: 'Synthetic Branch'}, home: {actions: [{label: farmer.customer_name, detail: 'Log JBL visit', context: 'Synthetic Branch', url: '/portal/s/jbl/?focus=' + caseId}], queues: [{label: 'Visits to log', count: 10, url: '/portal/s/jbl/'}], shortcuts: [], system_health: []}, counts: {}};
  if (p === '/payments/batches/') {
    const all = Array.from({length: 50}, (_, n) => ({...batch, id: `synthetic-batch-${n}`, payment_number: n + 1, cases: undefined}));
    const search = url.searchParams.get('search') || '';
    const filtered = search ? all.filter(item => String(item.payment_number) === search) : all;
    const pages = Math.max(1, Math.ceil(filtered.length / 10));
    const page = Math.min(pages, Math.max(1, Number(url.searchParams.get('page') || 1)));
    return {batches: filtered.slice((page - 1) * 10, page * 10), counts: {open: filtered.length, all: filtered.length, completed: 0, cancelled: 0}, pagination: {page, pages, total: filtered.length, page_size: 10}};
  }
  if (p === `/payments/batches/${batchId}/`) return {batch};
  if (p === '/invoice-receipts/') return {batches: []};
  if (p === '/invoice-pool/') return {invoices, batches: [], summary: {invoice_count: 12, needs_action_count: 12}, pagination: {page: 1, pages: 1, total: 12}, filters: {}};
  if (p === '/hb-actions/') return {items: Array.from({length: 10}, (_, n) => ({...farmer, customer_name: `Synthetic Installation ${n}`, installation_status: 'open', installation_status_label: 'Not installed', detail_url: `/portal/s/hb-actions/${caseId}/?workstream=installation`})), counts: {open: 10, installed: 0}, page: 1, pages: 1};
  if (p.endsWith('-queue/') || p === '/farmers/') return {farmers: Array.from({length: 10}, (_, n) => ({...farmer, customer_name: `Synthetic Customer ${n}`})), pagination: {page: 1, pages: 1, total: 10}, filter_options: {branches: ['Synthetic Branch'], counties: ['Synthetic County']}};
  if (p === '/settings/') return {data: {preferences: {}, screens: [], queues: [], branches: []}};
  if (p === '/publication/pump/') return {changed: false, poll_after_seconds: 60};
  return {items: [], batches: [], data: [], farmers: [], results: [], records: [], rows: [], counts: {}, pagination: {page: 1, pages: 1, total: 0}, filters: {}};
}
async function install(page, observation) {
  await page.addInitScript(() => {window.Telegram = {WebApp: {initData: 'synthetic', colorScheme: 'light', themeParams: {}, ready(){}, expand(){}, disableVerticalSwipes(){}, onEvent(){}, offEvent(){}, BackButton: {show(){}, hide(){}, onClick(){}, offClick(){}}}};});
  await page.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.origin !== base) return route.fulfill({status: 200, body: '', contentType: 'application/javascript'});
    if (!url.pathname.startsWith('/api/')) return route.continue();
    observation.requests.push({path: url.pathname + url.search, method: route.request().method()});
    if (url.pathname === '/api/portal/navigation/') return route.fulfill({status: 200, body: '', contentType: 'text/html'});
    if (url.pathname.endsWith('/fragment/')) {
      const queue = url.pathname.split('/')[4] || 'jbl';
      const html = '<span data-portal-result-count data-total="10">10 matching cases</span>' + Array.from({length:10}, (_, n) => `<article class="farmer-card htmx-farmer-card operational-farmer-card" data-farmer-id="${caseId}" data-qkey="${queue}"><div class="fc-top"><span class="fc-name">Synthetic Customer ${n + 1}</span><span class="badge">Awaiting Credit Analysis</span></div><div class="fc-bottom">Synthetic County · Synthetic Branch</div></article>`).join('');
      return route.fulfill({status:200,contentType:'text/html',body:html});
    }
    const allowed = route.request().method() === 'GET' || url.pathname.endsWith('/publication/pump/');
    const data = payload(url);
    if (observation.approval && data.batch) data.batch = {...data.batch,status:'in_review'};
    return route.fulfill({status: allowed ? 200 : 403, contentType: 'application/json', body: JSON.stringify(allowed ? {ok: true, ...data} : {ok: false, error: 'Synthetic audit blocks writes.'})});
  });
  page.on('pageerror', error => observation.errors.push(error.message));
}
async function geometry(page) {
  return page.evaluate(() => ({width: innerWidth, documentWidth: document.documentElement.scrollWidth, height: document.documentElement.scrollHeight,
    scrollContainers: [...document.querySelectorAll('main,#payments-current-cases,#payments-batches')].map(n=>({id:n.id,height:n.clientHeight,scrollHeight:n.scrollHeight})),
    headings: [...document.querySelectorAll('h1,h2,h3')].filter(n => n.getClientRects().length).map(n => n.textContent.trim()),
    clipped: [...document.querySelectorAll('button,a,input,select')].filter(n => {const r=n.getBoundingClientRect(); return r.width && (r.right > innerWidth + 2 || r.left < -2) && !n.closest('.sheet-overlay:not(.open),.portal-sidebar');}).map(n => ({id:n.id, text:n.textContent.trim().slice(0,65)})),
    tinyControls: [...document.querySelectorAll('button')].filter(n => {const r=n.getBoundingClientRect(); return r.width > 0 && r.height > 0 && (r.width < 24 || r.height < 24);}).map(n=>({id:n.id, text:n.textContent.trim().slice(0,50)})),
    text: document.querySelector('main')?.innerText.slice(0,5000) || ''}));
}
module.exports = {install, geometry, base, output, batchId, batch};
if (require.main === module) (async () => {
  fs.mkdirSync(output, {recursive: true});
  const browser = await chromium.launch();
  const report = [];
  try {
    for (const width of [320,390,1280]) {
      for (const screen of ['dashboard','jbl','my_visits','credit','final','requisition','all','deferred','batches','hb-actions','invoices','payments','history','farmup','imports','settings', `payments/${batchId}`]) {
        const observation = {screen,width,requests:[],errors:[]};
        const page = await browser.newPage({viewport:{width,height:800}});
        await install(page, observation);
        const route = screen === 'hb-actions' ? 'hb-actions' : screen;
        await page.goto(`${base}/portal/s/${route}/`, {waitUntil:'networkidle'});
        await page.waitForTimeout(250);
        observation.geometry = await geometry(page);
        observation.screenshot = path.join(output,`${screen.replaceAll('/','-')}-${width}.png`);
        await page.screenshot({path:observation.screenshot,fullPage:true});
        if (width===390 && screen==='dashboard') {
          await page.context().setOffline(true);
          await page.locator('#dashboard-refresh').click();
          await page.waitForTimeout(300);
          observation.offline = await geometry(page);
          await page.screenshot({path:path.join(output,'home-offline-refresh.png'),fullPage:true});
          await page.context().setOffline(false);
        }
        if (screen.startsWith('payments/')) {
          await page.locator('.payment-current-case > summary').first().click().catch(e=>observation.errors.push(e.message));
          observation.expanded = await geometry(page);
          await page.screenshot({path:path.join(output,`payment-expanded-${width}.png`),fullPage:true});
          await page.screenshot({path:path.join(output,`payment-expanded-viewport-${width}.png`)});
        }
        report.push(observation); await page.close();
      }
    }
  } finally {await browser.close(); fs.writeFileSync(path.join(output,'observations.json'),JSON.stringify(report,null,2));}
  console.log(JSON.stringify(report.map(r=>({screen:r.screen,width:r.width,overflow:r.geometry.documentWidth>r.width,errors:r.errors,clipped:r.geometry.clipped.length,tiny:r.geometry.tinyControls.length})),null,2));
})().catch(error=>{console.error(error);process.exitCode=1;});
