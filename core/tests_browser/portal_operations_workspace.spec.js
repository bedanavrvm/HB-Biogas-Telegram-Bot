'use strict';
const fs = require('node:fs');
const path = require('node:path');
const {test, expect} = require('playwright/test');
const {mountPortalShell} = require('./fixtures/portal_shell');
const template = fs.readFileSync(path.resolve(__dirname, '../templates/portal/portal.html'), 'utf8');
const asset = name => path.resolve(__dirname, '../static/miniapp', name);
const clean = html => html.replace(/{%[^]*?%}/g, '').replace(/{{[^]*?}}/g, '');
async function mount(page, html) {
  await mountPortalShell(page, html);
  // portal.js applies these classes at startup in the actual application.
  await page.evaluate(() => document.body.classList.add('portal-app', 'workflow-standard'));
}

for (const width of [320, 430, 768, 1280]) {
  test(`SysUp offers inline field choices and preserves corrections after conflict at ${width}px`, async ({page}, info) => {
    await page.setViewportSize({width, height:900});
    await mount(page, '<div id="portal-screen" data-screen="imports"><div id="portal-import-list"></div><div id="portal-import-review" hidden></div></div>');
    await page.evaluate(() => {
      window.Telegram = {WebApp:{initData:'synthetic-only'}};
      window.sysupCalls = [];
      const batch = {id:'training-upload', kind:'sysup', portal_revision:3, total_rows:1,
        source_filename:'synthetic.csv', source_table:{headers:['Name'], rows:[['Training System Applicant']]},
        review_rows:[{'Name':'Training System Applicant', 'ID NO':'99999991', 'LGF Balance':'6000',
          'Import Status':'ready', 'Matched Farmer ID':'training-case', row_fingerprint:'training-fingerprint',
          'Match Candidates':[{id:'training-case', customer_name:'Training Portal Applicant', workflow_revision:4,
            fields:{Name:'Training Portal Applicant', 'LGF Balance':'0'}}]}]};
      window.PortalMiniAppApi = {
        apiFetch:async url => ({ok:true, data:{ok:true, batches:[batch], batch}}),
        postJson:async (url,payload) => {sysupCalls.push({url,payload}); return {ok:false,data:{error:'This case changed. Refresh its values.'}};},
      };
    });
    await page.addScriptTag({path:asset('portal_imports.js')});
    await page.evaluate(() => PortalMiniAppImports.load());
    await page.getByRole('button',{name:'Review rows',exact:true}).click();
    await expect(page.locator('#portal-import-review .portal-import-review-heading')).toHaveCount(1);
    await expect(page.locator('#portal-import-review-close svg')).toHaveCount(1);
    await page.locator('.sysup-field-review>summary').click();
    await page.getByRole('combobox',{name:'Value to keep for Name',exact:true}).selectOption('portal');
    await page.getByRole('textbox',{name:'SysUp LGF Balance',exact:true}).fill('0');
    await page.getByRole('button',{name:'Commit selected',exact:true}).click();
    await expect(page.locator('#portal-import-feedback')).toContainText('This case changed');
    await expect(page.getByRole('textbox',{name:'SysUp LGF Balance',exact:true})).toHaveValue('0');
    expect(await page.locator('.portal-import-review-grid th').first().evaluate(node => getComputedStyle(node).backgroundColor)).not.toBe('rgba(0, 0, 0, 0)');
    expect(await page.evaluate(() => sysupCalls[0].payload.rows[0])).toMatchObject({
      approved:true, case_revision:4, field_choices:{Name:'portal'}, source_corrections:{'LGF Balance':'0'},
    });
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    await page.screenshot({path:info.outputPath(`sysup-review-${width}.png`)});
  });

  test(`order archive detail keeps summary and icon actions aligned at ${width}px`, async ({page}, info) => {
    await page.setViewportSize({width, height: 900});
    const start = template.indexOf('<div class="sheet-overlay" id="batch-detail-overlay"');
    const end = template.indexOf('<!--', start + 10);
    await mount(page, clean(template.slice(start, end)));
    await page.addScriptTag({path: asset('portal_helpers.js')});
    await page.addScriptTag({path: asset('portal_requisitions.js')});
    await page.evaluate(async () => {
      PortalMiniAppRequisitions.init({state: {capabilities: new Set(['portal.requisition.finalize']),
        selectedRequisitions: new Set(), selectedRequisitionRevisions: new Map()},
        el: id => document.getElementById(id), showToast() {}, getCookie: () => '',
        escapeHtml: PortalMiniAppHelpers.escapeHtml, summaryGrid: PortalMiniAppHelpers.summaryGrid,
        batchClientRows: PortalMiniAppHelpers.batchClientRows,
        apiFetch: async () => ({ok: true, data: {ok: true, batch: {
          id: 'training-order', order_number: 'HB-10', version: 2, requisition_date: '2026-10-06',
          farmer_count: 2, can_cancel: true, finalized: false, drive_url: 'https://example.invalid/training',
          drive_sync_status: 'succeeded', invoice_summary: {invoiced_count: 0, pending_invoice_count: 2},
          farmers: [{id: 'training-1', customer_name: 'Training Applicant Long Customer Name',
            national_id: '99999991', branch: 'Limuru', primary_phone: '0700000091'}],
        }}})});
      await PortalMiniAppRequisitions.openBatchDetail('training-order');
    });
    await expect(page.locator('#batch-detail-title')).toHaveText('Order HB-10');
    await expect(page.locator('#batch-detail-overlay')).toHaveCSS('opacity', '1');
    await expect(page.locator('#batch-detail-overlay .sheet-panel')).toHaveCSS('opacity', '1');
    await expect(page.locator('#batch-detail-sub')).toContainText('Awaiting signed copy');
    await expect(page.getByRole('button', {name: 'Upload invoices', exact: true})).toHaveCount(0);
    const tiles = await page.locator('#batch-detail-summary>div').evaluateAll(nodes => nodes.map(node => node.getBoundingClientRect().y));
    expect(Math.max(...tiles) - Math.min(...tiles)).toBeLessThan(2);
    const actions = await page.locator('#batch-detail-actions button').evaluateAll(nodes => nodes.map(node => {
      const box = node.getBoundingClientRect(); return {y: box.y, width: box.width, height: box.height};
    }));
    expect(Math.max(...actions.map(box => box.y)) - Math.min(...actions.map(box => box.y))).toBeLessThan(2);
    for (const box of actions) {expect(box.width).toBeGreaterThanOrEqual(44); expect(box.height).toBeGreaterThanOrEqual(44);}
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    await page.screenshot({path: info.outputPath(`order-detail-verified-${width}.png`)});
  });

  test(`order selection stays compact until explicitly prepared at ${width}px`, async ({page}, info) => {
    await page.setViewportSize({width, height: 900});
    const start = template.indexOf('<div id="requisition-batch-panel"');
    const end = template.indexOf('<div id="req-list"', start);
    await mount(page, `<div id="portal-screen" data-screen="requisition">${clean(template.slice(start, end))}<div id="req-list"><input class="farmer-card-checkbox" data-id="training-case"></div></div>`);
    await page.addScriptTag({path: asset('portal_requisitions.js')});
    await page.evaluate(() => {
      window.opsState = {capabilities: new Set(['portal.requisition.finalize', 'portal.requisition.write']),
        selectedRequisitions: new Set(['training-case']), selectedRequisitionRevisions: new Map([['training-case', 1]]), requisitionPartner: 'HB'};
      PortalMiniAppRequisitions.init({state: opsState, el: id => document.getElementById(id),
        apiFetch: async () => ({ok: true, data: {ok: true, order_number: `${opsState.requisitionPartner === 'HB' ? 'HB' : 'ECO'}-10`}}),
        showToast() {}, loadQueue() {}, escapeHtml: value => String(value ?? '')});
      PortalMiniAppRequisitions.updateBatchPanel();
    });
    await expect(page.locator('#batch-prepare-fields')).toBeHidden();
    await page.locator('#batch-prepare-order').click();
    await expect(page.locator('#batch-prepare-fields')).toBeVisible();
    await expect(page.locator('#batch-order-num')).toHaveValue('HB-10');
    await expect(page.locator('#batch-order-num')).toHaveAttribute('readonly');
    await expect(page.locator('#batch-selected-count')).toContainText('1 selected');
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    await page.screenshot({path: info.outputPath(`prepare-order-${width}.png`)});
  });

  test(`pending invoice deliveries are compact and archiving keeps invoices at ${width}px`, async ({page}, info) => {
    await page.setViewportSize({width, height: 900});
    const start = template.indexOf('<section id="payments-receipts-panel"');
    const end = template.indexOf('</section>', start) + '</section>'.length;
    await mount(page, `<div id="portal-screen" data-screen="payments"><div id="payments-batches"></div>${clean(template.slice(start, end))}</div>`);
    await page.addScriptTag({path: asset('utils.js')});
    await page.addScriptTag({path: asset('portal_payments.js')});
    await page.evaluate(async () => {
      window.receiptCalls = [];
      const receipts = [
        {id: 'training-delivery', revision: 1, total_count: 3, counts: {matched: 2, review: 1}, status: 'open', created_at: '2026-10-06T10:00:00Z'},
        {id: 'finished-delivery', total_count: 1, counts: {matched: 1}, status: 'payment_created'},
      ];
      PortalMiniAppPayments.init({el: id => document.getElementById(id), escapeHtml: value => String(value ?? ''),
        state: {capabilities: new Set(['portal.payment.prepare'])}, showToast() {}, fmtDate: () => '06-Oct-2026',
        setButtonLoading: MiniAppUtils.setButtonLoading, tg: {initData: 'synthetic-only'},
        portalApi: {postJson: async (url, payload) => {receiptCalls.push({url, payload}); return {ok: true, data: {ok: true}};}},
        apiFetch: async url => ({ok: true, data: {ok: true, batches: url.startsWith('/invoice-receipts/') ? receipts : []}})});
      await PortalMiniAppPayments.load();
    });
    await expect(page.locator('.payment-receipt-row')).toHaveCount(1);
    await expect(page.locator('#payments-receipts-panel>header')).toHaveCSS('display', 'flex');
    const heading = await page.locator('#payments-receipts-panel h2').boundingBox();
    const archive = await page.locator('#payments-receipts-toggle').boundingBox();
    expect(Math.abs(heading.y + heading.height / 2 - archive.y - archive.height / 2)).toBeLessThan(3);
    await expect(page.locator('.payment-receipt-row')).toContainText('2 ready');
    const row = await page.locator('.payment-receipt-row').boundingBox();
    expect(row.height).toBeLessThan(120);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    await page.screenshot({path: info.outputPath(`deliveries-${width}.png`)});
    page.once('dialog', dialog => dialog.accept());
    await page.getByRole('button', {name: 'Archive delivery', exact: true}).click();
    await expect.poll(() => page.evaluate(() => receiptCalls.length)).toBe(1);
    expect(await page.evaluate(() => receiptCalls[0])).toEqual({url: '/invoice-receipts/training-delivery/archive/', payload: {archived: true, revision: 1}});
  });

  test(`invoice record distinguishes people and aligns parsed values at ${width}px`, async ({page}, info) => {
    await page.setViewportSize({width, height: 900});
    await mount(page, '<div id="portal-screen" data-screen="invoices" data-invoice-view="detail" data-invoice-id="training-invoice"><div id="invoice-detail-page"></div></div>');
    await page.addScriptTag({path: asset('portal_invoices.js')});
    await page.evaluate(async () => {
      const person = {name: 'Training Applicant With A Long Name', national_id: '99999991'};
      PortalMiniAppInvoices.init({state: {capabilities: new Set(['portal.invoice.write'])}, tg: {initData: 'synthetic-only'},
        showToast() {}, apiFetch: async () => ({ok: true, data: {ok: true, invoice: {
          id: 'training-invoice', invoice_no: 'TRAIN-10', customer_name: person.name, customer_id: person.national_id,
          status: 'matched', invoice_amount: '90000', balance_due: '80000', payment: '10000',
          identity: {invoice_identity: person, lead_identity: person, applicant_identity: person, status_label: 'Matched'},
        }, events: [], duplicates: []}})});
      await PortalMiniAppInvoices.load(1);
    });
    await expect(page.locator('.invoice-person-lead')).toContainText('Lead');
    await expect(page.locator('.invoice-person-applicant')).toContainText('System applicant');
    await expect(page.locator('.invoice-parsed-grid .name').first()).toHaveCSS('font-size', '14px');
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    await page.screenshot({path: info.outputPath(`invoice-record-${width}.png`), fullPage: true});
  });
}
