'use strict';
const fs = require('node:fs');
const path = require('node:path');
const {test, expect} = require('playwright/test');
const {mountPortalShell} = require('./fixtures/portal_shell');
const asset = name => path.resolve(__dirname, '../static/miniapp', name);
const partial = fs.readFileSync(path.resolve(__dirname, '../templates/portal/partials/hb_deposit_detail.html'), 'utf8').replace(/{%[^]*?%}/g, '');

test('HB Deposits tab loads financial holds and keeps filtering/paging separate from installation', async ({page}) => {
  const template = fs.readFileSync(path.resolve(__dirname, '../templates/portal/portal.html'), 'utf8');
  const start = template.indexOf('<header class="portal-queue-header"><div><h1>HB Actions');
  const end = template.indexOf('<div id="hb-action-pagination"', start);
  const markup = template.slice(start, template.indexOf('</div>', end) + 6);
  await mountPortalShell(page, `<div id="portal-screen" data-screen="hb_actions"><section class="page active">${markup}</section></div>`);
  await page.addScriptTag({path:asset('portal_hb_deposits.js')});
  await page.addScriptTag({path:asset('portal_hb_actions.js')});
  await page.evaluate(() => {
    history.replaceState = () => {};
    window.hbQueries = [];
    window.PortalMiniAppHbActions.init({escapeHtml:value=>String(value??''), portalApi:{apiFetch:async url=>{
      window.hbQueries.push(url);
      return {ok:true,data:{ok:true,counts:{awaiting:31,cleared:2,all:33},page:1,pages:2,items:[{
        customer_name:'Synthetic awaiting-deposit applicant', case_reference:'JBL-1', recorded_amount:'2000.00',shortfall:'3000.00',deposit_hold:true,detail_url:'/portal/s/hb-actions/synthetic/?workstream=deposits',
      }]}};
    }}});
  });
  await page.locator('[data-hb-queue="deposits"]').click();
  await expect(page.locator('#hb-action-list')).toContainText('Awaiting deposit');
  await expect(page.locator('#hb-action-counts')).toContainText('Awaiting Deposit31');
  await page.locator('[data-state="cleared"]').click();
  await expect.poll(() => page.evaluate(() => window.hbQueries.at(-1))).toContain('state=cleared');
  await page.locator('[data-page="2"]').click();
  await expect.poll(() => page.evaluate(() => window.hbQueries.at(-1))).toContain('page=2');
  expect(await page.evaluate(() => window.hbQueries.every(url=>url.startsWith('/hb-deposits/')))).toBe(true);
});

async function mountDeposit(page, {canEdit = true, visited = false, dark = false} = {}) {
  await mountPortalShell(page, `<div id="portal-screen" data-screen="hb_actions" data-hb-action-farmer-id="synthetic-case"><section id="page-hb-actions" class="page active">${partial}</section></div>`);
  await page.evaluate(dark => {
    document.body.classList.add('portal-app', 'workflow-standard');
    document.documentElement.dataset.miniappColorScheme = dark ? 'dark' : 'light';
    if (dark) {
      for (const [key, value] of Object.entries({bg:'#111827', 'secondary-bg':'#1f2937', text:'#f9fafb', hint:'#cbd5e1', button:'#38bdf8', 'button-text':'#082f49'})) {
        document.documentElement.style.setProperty(`--tg-theme-${key}-color`, value);
      }
    }
    window.depositRequests = []; window.depositToasts = []; window.depositFail = false;
    window.depositData = {
      id: 'synthetic-case', customer_name: 'Synthetic Deposit Applicant With A Long Name', case_reference: 'SYNTHETIC-1',
      national_id: '99999981', primary_phone: '254700000081', branch: 'Synthetic branch', source: 'jawabu_farmup_review',
      workflow_revision: 1, recorded_amount: '2000.00', required_amount: '5000.00', shortfall: '3000.00',
      deposit_hold: true, can_edit: true, visit_recorded: false, reason: 'Awaiting HB deposit: KES 3,000.00 outstanding.',
      activity: [{action: 'hb_deposit_updated', actor: 'Synthetic HB colleague', occurred_at: '19-10-2026 16:00 EAT', old_values: {deposit_paid_hbg:'0.00'}, new_values: {deposit_paid_hbg:'2000.00'}, reason: 'Initial recorded total'}],
    };
  }, dark);
  await page.evaluate(({canEdit, visited}) => { window.depositData.can_edit = canEdit; window.depositData.visit_recorded = visited; }, {canEdit, visited});
  await page.addScriptTag({path: asset('utils.js')});
  await page.addScriptTag({path: asset('portal_hb_deposits.js')});
  await page.evaluate(() => {
    const escapeHtml = value => { const span = document.createElement('span'); span.textContent = String(value ?? ''); return span.innerHTML; };
    window.PortalMiniAppHbDeposits.init({escapeHtml, showToast: value => window.depositToasts.push(value), portalApi: {apiFetch: async (url, options = {}) => {
      if (options.method === 'POST') {
        window.depositRequests.push({url, ...options});
        if (window.depositFail) throw new Error('Synthetic interrupted response');
        if (window.depositConflict) return {ok:false,data:{ok:false,code:'workflow_revision_conflict',error:'This case changed.'}};
        const payload = JSON.parse(options.body);
        window.depositData = {...window.depositData, workflow_revision:2, recorded_amount: payload.amount, shortfall: '0.00', deposit_hold:false};
      }
      return {ok:true,data:{ok:true,deposit:structuredClone(window.depositData)}};
    }}});
    window.PortalMiniAppHbDeposits.load();
  });
  await expect(page.locator('#hb-deposit-content')).toBeVisible();
  await expect(page.getByRole('heading', {name:'HB deposit',exact:true})).toBeInViewport();
}

for (const dark of [false, true]) test(`HB deposit mobile ${dark ? 'dark' : 'light'} audit and safe retry`, async ({page}, info) => {
  await page.setViewportSize({width:390, height:844});
  await mountDeposit(page, {dark});
  await expect(page.locator('#hb-deposit-summary')).toContainText('3,000.00');
  await expect(page.locator('#hb-deposit-activity')).toContainText('Synthetic HB colleague');
  await page.locator('#hb-deposit-amount').fill('1000');
  await page.locator('#hb-deposit-save').click();
  await expect(page.locator('#hb-deposit-error')).toContainText('Explain');
  expect(await page.evaluate(() => window.depositRequests.length)).toBe(0);
  await page.locator('#hb-deposit-amount').fill('5000');
  await page.evaluate(() => { window.depositFail = true; });
  await page.locator('#hb-deposit-save').click();
  await expect(page.locator('#hb-deposit-error')).toContainText('interrupted');
  await page.screenshot({path:info.outputPath(`hb-deposit-${dark ? 'dark' : 'light'}-retry.png`),animations:'disabled'});
  await page.evaluate(() => { window.depositFail = false; });
  await page.locator('#hb-deposit-save').click();
  await expect(page.locator('#hb-deposit-status')).toContainText('requirement met');
  const requests = await page.evaluate(() => window.depositRequests);
  expect(requests[0].headers['Idempotency-Key']).toBe(requests[1].headers['Idempotency-Key']);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({path:info.outputPath(`hb-deposit-${dark ? 'dark' : 'light'}-cleared.png`),animations:'disabled'});
});

test('Operations and already-visited cases retain read-only Activity', async ({page}) => {
  await mountDeposit(page, {canEdit:false, visited:true});
  await expect(page.locator('#hb-deposit-amount')).toBeDisabled();
  await expect(page.locator('#hb-deposit-save')).toBeDisabled();
  await expect(page.locator('#hb-deposit-status')).toContainText('read-only');
  await expect(page.locator('#hb-deposit-activity')).toContainText('Initial recorded total');
});

test('stale deposit feedback preserves input until explicit reload', async ({page}) => {
  await mountDeposit(page);
  await page.locator('#hb-deposit-amount').fill('5000');
  await page.evaluate(() => { window.depositConflict = true; });
  await page.locator('#hb-deposit-save').click();
  await expect(page.locator('#hb-deposit-error')).toContainText('Reload latest');
  await expect(page.locator('#hb-deposit-amount')).toHaveValue('5000');
  page.on('dialog', dialog => dialog.accept());
  await page.locator('#hb-deposit-reload').click();
  await expect(page.locator('#hb-deposit-amount')).toHaveValue('2000.00');
});

test('real JBL card renderer holds low deposits and unlocks cleared cases', async ({page}, info) => {
  await page.setViewportSize({width:390,height:844});
  await mountPortalShell(page, '<div id="queue"></div>');
  const source = fs.readFileSync(asset('portal.js'), 'utf8');
  const start = source.indexOf('  function renderVisitQueueCard(');
  const end = source.indexOf('  function renderOperationalQueueCard(', start);
  const listStart = source.indexOf('  function renderFarmerList(');
  const listEnd = source.indexOf('\n  function ', listStart + 20);
  await page.addScriptTag({content: `
    const escapeHtml = value => {const span=document.createElement('span');span.textContent=String(value ?? '');return span.innerHTML;};
    const locationText = () => 'Synthetic county'; const fmtDate = value => value;
    const hasCapability = () => true; const el = id => document.getElementById(id);
    const state = {queues:{jbl:[]},selectedRequisitions:new Set()};
    window.PortalMiniAppHelpers = {phoneLink: value => '<a href="tel:'+escapeHtml(value)+'">'+escapeHtml(value)+'</a>'};
    window.queueOpens = 0; const openQueueCase = () => window.queueOpens++;
    ${source.slice(start, end)}
    ${source.slice(listStart, listEnd)}
    const farmer={id:'synthetic-case',customer_name:'Synthetic held applicant',primary_phone:'254700000081',deposit:{deposit_hold:true,recorded_amount:'2000.00',shortfall:'3000.00'}};
    window.renderDepositQueue = held => {farmer.deposit.deposit_hold=held;state.queues.jbl=[farmer];renderFarmerList(document.getElementById('queue'),[farmer],{mode:'jbl_visit'},'jbl');};
    window.renderDepositQueue(true);
  `});
  await expect(page.locator('.farmer-card')).toHaveAttribute('aria-disabled', 'true');
  await expect(page.locator('.farmer-card a')).toHaveCount(0);
  await page.locator('.farmer-card').click({force:true});
  expect(await page.evaluate(() => window.queueOpens)).toBe(0);
  await expect(page.locator('.farmer-card')).toContainText('Deposit pending');
  await page.screenshot({path:info.outputPath('jbl-deposit-held.png'),animations:'disabled'});
  await page.evaluate(() => window.renderDepositQueue(false));
  await page.locator('.farmer-card').click();
  expect(await page.evaluate(() => window.queueOpens)).toBe(1);
});
