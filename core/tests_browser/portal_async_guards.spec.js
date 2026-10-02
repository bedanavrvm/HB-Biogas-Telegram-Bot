'use strict';

const path = require('node:path');
const { test, expect } = require('playwright/test');

const asset = name => path.resolve(__dirname, '..', 'static', 'miniapp', name);

test('HB Action keeps the newest workstream when earlier results arrive late', async ({ page }) => {
  await page.setContent(`
    <div id="portal-screen" data-screen="hb_actions"></div>
    <button data-hb-queue="installation">Installation</button>
    <button data-hb-queue="commissioning">Commissioning</button>
    <div id="hb-action-counts"></div><div id="hb-action-list"></div><div id="hb-action-pagination"></div>
  `);
  await page.addScriptTag({ path: asset('portal_hb_actions.js') });
  await page.evaluate(() => {
    window.history.replaceState = () => {};
    window.requests = [];
    PortalMiniAppHbActions.init({
      portalApi: { apiFetch: path => new Promise(resolve => window.requests.push({ path, resolve })) },
      escapeHtml: value => String(value ?? ''),
    });
    PortalMiniAppHbActions.load();
  });
  await page.locator('[data-hb-queue="commissioning"]').click();
  await expect.poll(() => page.evaluate(() => window.requests.length)).toBe(2);
  await page.evaluate(() => {
    window.requests[1].resolve({ ok: true, data: { ok: true, counts: {}, items: [{
      customer_name: 'Commissioning customer', detail_url: '/case-2/',
      commissioning_status: 'not_commissioned', commissioning_status_label: 'Not commissioned',
    }] } });
  });
  await expect(page.locator('#hb-action-list')).toContainText('Commissioning customer');
  await page.evaluate(() => {
    window.requests[0].resolve({ ok: true, data: { ok: true, counts: {}, items: [{
      customer_name: 'Installation customer', detail_url: '/case-1/',
      installation_status: 'open', installation_status_label: 'Not installed',
    }] } });
  });
  await expect(page.locator('#hb-action-list')).toContainText('Commissioning customer');
  await expect(page.locator('#hb-action-list')).not.toContainText('Installation customer');
});

test('HB document Back closes preview and ignores a late response', async ({ page }) => {
  await page.route('http://miniapp.test/**', route => route.fulfill({contentType: 'text/html', body: '<!doctype html><title>HB action</title>'}));
  await page.goto('http://miniapp.test/portal/s/hb-actions/case-1/?workstream=installation');
  await page.setContent(`<div id="portal-screen" data-screen="hb_actions" data-hb-action-farmer-id="case-1"></div>
    <a id="hb-action-invoice" href="/invoice/" data-mode="preview" data-preview-title="Invoice">Invoice</a>
    <a id="hb-action-signed-order" href="/order/" data-mode="preview" data-preview-title="Signed order">Signed order</a>
    <div id="media-viewer-overlay"><button id="media-viewer-close">Close</button><h2 id="media-viewer-title"></h2><p id="media-viewer-sub"></p><div id="media-viewer-content"></div></div>`);
  await page.addScriptTag({path: asset('portal_hb_actions.js')});
  await page.evaluate(() => {
    window.previewRequests = [];
    window.SecureMediaViewer = {
      fetchAuthorizedBlob: () => new Promise(resolve => window.previewRequests.push(resolve)),
      renderBlob: (target) => {target.textContent = 'Document loaded'; return 'blob:test';},
      revoke() {},
    };
    window.PortalMiniAppHbActions.init({
      escapeHtml: value => String(value ?? ''),
      portalApi: {initDataHeader: () => ({})},
      showToast() {},
    });
  });
  await page.locator('#hb-action-invoice').click();
  await expect(page.locator('#media-viewer-overlay')).toHaveClass(/open/);
  await page.evaluate(() => window.history.back());
  await expect(page.locator('#media-viewer-overlay')).not.toHaveClass(/open/);
  await page.evaluate(() => window.previewRequests[0](new Blob(['late'], {type: 'text/html'})));
  await expect(page.locator('#media-viewer-content')).toBeEmpty();
  await page.locator('#hb-action-signed-order').click();
  await page.evaluate(() => window.previewRequests[1](new Blob(['order'], {type: 'application/pdf'})));
  await expect(page.locator('#media-viewer-content')).toHaveText('Document loaded');
  await page.locator('#media-viewer-close').click();
  await expect(page.locator('#media-viewer-overlay')).not.toHaveClass(/open/);
  await expect(page).toHaveURL(/\/hb-actions\/case-1\/\?workstream=installation/);
});

test('invoice list keeps newer search results when an earlier request finishes later', async ({ page }) => {
  await page.setContent(`
    <div id="portal-screen" data-screen="invoices" data-invoice-view="inbox"></div>
    <div id="invoice-pool-summary"></div><div id="invoice-pool-list"></div><div id="pg-invoices"></div>
  `);
  await page.addScriptTag({ path: asset('portal_helpers.js') });
  await page.addScriptTag({ path: asset('portal_invoices.js') });
  await page.evaluate(() => {
    window.requests = [];
    PortalMiniAppInvoices.init({
      apiFetch: path => new Promise(resolve => window.requests.push({ path, resolve })),
      escapeHtml: value => String(value ?? ''),
      state: { capabilities: new Set() },
    });
    PortalMiniAppInvoices.load(1);
    PortalMiniAppInvoices.load(1);
  });
  await expect.poll(() => page.evaluate(() => window.requests.length)).toBe(2);
  await page.evaluate(() => {
    window.requests[1].resolve({ ok: true, data: { ok: true, summary: {}, invoices: [{
      id: 'new', invoice_no: '102', customer_name: 'New result', status: 'unmatched',
    }], pagination: {} } });
  });
  await expect(page.locator('#invoice-pool-list')).toContainText('New result');
  await page.evaluate(() => {
    window.requests[0].resolve({ ok: true, data: { ok: true, summary: {}, invoices: [{
      id: 'old', invoice_no: '101', customer_name: 'Old result', status: 'unmatched',
    }], pagination: {} } });
  });
  await expect(page.locator('#invoice-pool-list')).toContainText('New result');
  await expect(page.locator('#invoice-pool-list')).not.toContainText('Old result');
});
