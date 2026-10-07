'use strict';
const path = require('node:path');
const {test, expect} = require('playwright/test');
const {mountPortalShell} = require('./fixtures/portal_shell');
const asset = name => path.resolve(__dirname, '../static/miniapp', name);

async function mountRecord(page, {width = 390, writable = true, status = 'matched', source = true} = {}) {
  await page.setViewportSize({width, height: 900});
  await mountPortalShell(page, '<section id="portal-screen" data-screen="invoices" data-invoice-view="detail" data-invoice-id="synthetic-invoice"><div id="invoice-detail-page" class="invoice-detail-page"></div></section>');
  await page.addScriptTag({path: asset('utils.js')});
  await page.addScriptTag({path: asset('portal_invoices.js')});
  await page.evaluate(async ({writable, status, source}) => {
    const person = {name: 'Synthetic Applicant With A Long Family Name', national_id: 'TEST-ID-123'};
    window.__invoiceRequests = [];
    PortalMiniAppInvoices.init({state: {capabilities: new Set(writable ? ['portal.invoice.view', 'portal.invoice.write'] : ['portal.invoice.view'])}, showToast() {},
      apiFetch: async (url, options) => {
        window.__invoiceRequests.push({url, method: options?.method || 'GET'});
        return {ok: true, data: {ok: true, invoice: {id: 'synthetic-invoice', status, invoice_no: 'TEST-104', invoice_date: '07-Oct-2026', customer_name: person.name, customer_id: person.national_id, customer_phone: '+254000000000', invoice_amount: '125000', payment: '25000', balance_due: '100000', total_after_discount: '125000', discount: '0', page: 1, matched_order_number: 'HB-104',
          identity: {status_label: 'Matched', invoice_identity: person, lead_identity: person, applicant_identity: person}},
          batch: {original_filename: 'synthetic-invoice.pdf'}, events: [], duplicates: [], source_pdf_url: source ? '/synthetic/invoice.pdf' : ''}};
      }});
    await PortalMiniAppInvoices.load();
  }, {writable, status, source});
}

for (const width of [320, 390, 430, 768]) {
  test(`invoice record actions and biodata use available width at ${width}px`, async ({page}, info) => {
    await mountRecord(page, {width});
    await expect(page.getByRole('link', {name:'Call +254000000000'})).toHaveCount(2);
    for (const dark of [false, true]) {
      await page.evaluate(dark => {
        document.documentElement.dataset.miniappColorScheme = dark ? 'dark' : 'light';
        const theme = dark ? {bg: '#17171e', secondary: '#20202c', text: '#ffffff', hint: '#a8a8b3'} : {bg: '#f5f7f8', secondary: '#ffffff', text: '#17212b', hint: '#6d7a86'};
        for (const [key, value] of Object.entries({bg: theme.bg, 'secondary-bg': theme.secondary, text: theme.text, hint: theme.hint, button: '#2481cc'})) document.documentElement.style.setProperty(`--tg-theme-${key}-color`, value);
      }, dark);
      const actions = page.locator('.invoice-record-summary .invoice-detail-actions');
      const row = await actions.boundingBox();
      const boxes = await actions.locator(':scope > button').evaluateAll(nodes => nodes.map(node => {const box = node.getBoundingClientRect(); return {x: box.x, y: box.y, width: box.width, height: box.height};}));
      expect(boxes).toHaveLength(5);
      expect(Math.max(...boxes.map(box => box.width)) - Math.min(...boxes.map(box => box.width))).toBeLessThan(1);
      expect(boxes[0].x).toBeCloseTo(row.x, 0);
      expect(boxes.at(-1).x + boxes.at(-1).width).toBeCloseTo(row.x + row.width, 0);
      boxes.forEach(box => {expect(box.y).toBeCloseTo(boxes[0].y, 0); expect(box.height).toBeGreaterThanOrEqual(44);});
      const icons = await actions.locator('svg').evaluateAll(nodes => nodes.map(node => node.getBoundingClientRect().width));
      expect(icons).toHaveLength(5);
      icons.forEach(width => expect(width).toBe(17));
      await expect(page.locator('.invoice-parsed-group')).toHaveCount(3);
      await expect(page.locator('.invoice-person-lead strong')).toHaveText('Synthetic Applicant With A Long Family Name');
      expect(await page.locator('.invoice-identity-comparison span').first().evaluate(node => parseFloat(getComputedStyle(node).fontSize))).toBeGreaterThanOrEqual(12);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await page.screenshot({path: info.outputPath(`invoice-record-${width}-${dark ? 'dark' : 'light'}.png`), fullPage: true});
      await page.locator('#content').evaluate(node => { node.scrollTop = node.scrollHeight; });
      await page.screenshot({path: info.outputPath(`invoice-fields-${width}-${dark ? 'dark' : 'light'}.png`)});
      await page.locator('#content').evaluate(node => { node.scrollTop = 0; });
    }
    await page.getByRole('button', {name: 'Edit parsed fields'}).click();
    await expect(page.locator('.invoice-parsed-edit-form')).toBeVisible();
    await expect(page.locator('.invoice-parsed-grid')).toBeHidden();
    await page.locator('.invoice-parsed-edit-cancel').click();
    await expect(page.locator('.invoice-parsed-grid')).toBeVisible();
    await expect(page.locator('.invoice-parsed-edit-toggle svg')).toHaveCount(1);
    expect(await page.evaluate(() => window.__invoiceRequests.every(request => request.method === 'GET'))).toBe(true);
  });
}

test('read-only invoice has no editing actions or empty action rows', async ({page}) => {
  await mountRecord(page, {width: 320, writable: false, source: false});
  await expect(page.locator('.invoice-record-action')).toHaveCount(0);
  await expect(page.locator('.invoice-detail-actions')).toHaveCount(0);
  await expect(page.locator('.invoice-parsed-grid')).toBeVisible();
});

test('ignored invoice retains the restore action', async ({page}) => {
  await mountRecord(page, {width: 320, status: 'ignored'});
  await expect(page.getByRole('button', {name: 'Restore invoice'})).toBeVisible();
  await expect(page.getByRole('button', {name: 'Match invoice', exact: true})).toBeVisible();
  await expect(page.getByRole('button', {name: 'Ignore invoice', exact: true})).toHaveCount(0);
});
