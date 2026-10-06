'use strict';

const fs = require('node:fs');
const path = require('node:path');
const {test, expect} = require('playwright/test');
const {mountPortalShell} = require('./fixtures/portal_shell');

const asset = name => path.resolve(__dirname, '../static/miniapp', name);
const template = fs.readFileSync(path.resolve(__dirname, '../templates/portal/portal.html'), 'utf8');
const syntheticInitData = 'synthetic-telegram-session';

async function mountUpload(page) {
  const markup = template.slice(template.indexOf('      <form id="invoice-pool-upload-form"'),
    template.indexOf('    <div class="batch-summary-grid" id="invoice-pool-summary"'));
  await mountPortalShell(page, `<div id="portal-screen" data-screen="invoices" data-invoice-view="upload"><div class="batch-panel">${markup}<div id="invoice-pool-list"></div><div id="pg-invoices"></div></div>`);
  await page.evaluate(() => document.body.classList.add('portal-app', 'workflow-standard'));
  await page.clock.install();
  await page.addScriptTag({path: asset('utils.js')});
  await page.addScriptTag({path: asset('portal_api.js')});
  await page.addScriptTag({path: asset('portal_invoices.js')});
  await page.evaluate(initData => {
    window.uploadCalls = 0;
    window.notices = [];
    window.fetch = (url, options) => {
      if (!url.endsWith('/invoice-pool/upload/')) throw new Error('Unexpected network request');
      window.uploadCalls++;
      window.uploadKey = options.body.get('client_request_id');
      return new Promise((resolve, reject) => {
        window.finishUpload = () => resolve(new Response(JSON.stringify({ok: true, total_uploaded: 1,
          auto_matched_count: 1, auto_matched: [{filename: 'training.pdf', invoice_no: 'TRAIN-1', customer_name: 'Training Applicant'}]}),
          {status: 200, headers: {'Content-Type': 'application/json'}}));
        window.failUpload = () => reject(new TypeError('Synthetic connection lost'));
        window.rejectUpload = () => resolve(new Response(JSON.stringify({ok: false, error: 'PDF could not be read.'}), {status: 400}));
        window.invalidUploadResponse = () => resolve(new Response('<html>Gateway page</html>'));
        options.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')));
      });
    };
    PortalMiniAppInvoices.init({portalApi: PortalMiniAppApi, tg: {initData},
      state: {capabilities: new Set()}, getCookie: () => '',
      apiFetch: async () => ({ok: true, data: {ok: true, invoices: [], batches: [], summary: {}, pagination: {}}}),
      showToast: message => window.notices.push(message),
      setButtonLoading: MiniAppUtils.setButtonLoading,
    });
  }, syntheticInitData);
  await page.locator('#invoice-pool-file').setInputFiles({name: 'training.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-synthetic')});
}

test('invoice upload waits for success beyond the ordinary queue timeout', async ({page}, info) => {
  await page.setViewportSize({width: 390, height: 844});
  await mountUpload(page);
  await page.locator('#invoice-pool-upload-submit').click();
  await expect.poll(() => page.evaluate(() => window.uploadCalls)).toBe(1);
  await page.clock.fastForward(27000);
  await expect(page.locator('#invoice-pool-upload-result')).not.toContainText('did not finish');
  await expect(page.locator('#invoice-pool-upload-submit')).toBeDisabled();
  await page.locator('#invoice-pool-upload-form').evaluate(form => form.dispatchEvent(new Event('submit', {bubbles: true, cancelable: true})));
  expect(await page.evaluate(() => window.uploadCalls)).toBe(1);
  await page.screenshot({path: info.outputPath('upload-pending-390.png')});
  await page.evaluate(() => window.finishUpload());
  await expect(page.locator('#invoice-pool-upload-result')).toContainText('Successfully uploaded 1 invoice file');
  await expect(page.locator('#invoice-pool-upload-submit')).toBeEnabled();
  expect(await page.evaluate(() => window.uploadKey)).toBeTruthy();
  await page.screenshot({path: info.outputPath('upload-confirmed-390.png')});
});

for (const failure of ['connection', 'invalid_response', 'rejected', 'rendering']) {
  test(`invoice upload distinguishes ${failure} from an unconfirmed save`, async ({page}) => {
    await mountUpload(page);
    await page.locator('#invoice-pool-upload-submit').click();
    await page.evaluate(failure => {
      if (failure === 'connection') window.failUpload();
      else if (failure === 'invalid_response') window.invalidUploadResponse();
      else if (failure === 'rejected') window.rejectUpload();
      else {
        window.lucide = {createIcons() {throw new Error('Synthetic icon rendering failure');}};
        window.finishUpload();
      }
    }, failure);
    const message = failure === 'rejected' ? 'PDF could not be read.' : failure === 'rendering'
      ? 'Upload confirmed. Refresh to see the results.' : 'Could not confirm the upload. Check Recent uploads before retrying.';
    await expect(page.locator('#invoice-pool-upload-result')).toContainText(message);
    await expect(page.locator('#invoice-pool-upload-result')).not.toContainText('did not finish');
    await expect(page.locator('#invoice-pool-upload-submit')).toBeEnabled();
    expect(await page.locator('#invoice-pool-file').evaluate(input => input.files.length)).toBe(failure === 'rendering' ? 0 : 1);
  });
}

test('ordinary Portal reads retain their bounded timeout', async ({page}) => {
  await mountUpload(page);
  await page.evaluate(() => {
    window.fetch = (url, options) => new Promise((resolve, reject) => {
      options.signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')));
    });
    window.readResult = null;
    PortalMiniAppApi.apiFetch('/invoice-pool/').then(result => {window.readResult = result;});
  });
  await page.clock.fastForward(21000);
  expect(await page.evaluate(() => window.readResult)).toMatchObject({ok: false, status: 0, data: {error: 'The request took too long. Check your connection and try again.'}});
});

for (const width of [320, 430]) test(`payment invoice preview authenticates, retries and preserves delivery choices at ${width}px`, async ({page}, info) => {
  await page.setViewportSize({width, height: 844});
  await page.route('http://127.0.0.1:8007/**', route => route.fulfill({contentType: 'text/html', body: '<body></body>'}));
  await page.goto('http://127.0.0.1:8007/portal/s/payments/');
  const dialogs = template.slice(template.indexOf('  <dialog id="payment-receipt-dialog"'), template.indexOf('  <dialog id="payment-submit-confirm"'));
  await mountPortalShell(page, `<div id="portal-screen" data-screen="payments"><div id="payments-batches"></div><div id="payments-receipts-list"></div></div>${dialogs}`);
  await page.evaluate(() => document.body.classList.add('portal-app', 'workflow-standard'));
  await page.addScriptTag({path: asset('utils.js')});
  await page.addScriptTag({path: asset('portal_api.js')});
  await page.addScriptTag({path: asset('secure_media_viewer.js')});
  await page.addScriptTag({path: asset('portal_payments.js')});
  await page.evaluate(async initData => {
    const receipt = {id: 'delivery-1', status: 'open', total_count: 1, counts: {matched: 1}, items: [
      {id: 'invoice-1', invoice_no: 'TRAIN-1', farmer_id: 'case-1', applicant_name: 'Training Applicant',
        status: 'matched', source_filename: 'training.pdf', preview_url: '/synthetic/preview/'}]};
    window.denyPreview = false;
    window.previewAuthenticated = false;
    window.fetch = async (url, options) => {
      if (url !== '/synthetic/preview/') throw new Error('Unexpected preview request');
      const authenticated = options.headers['X-Telegram-Init-Data'] === initData;
      window.previewAuthenticated = authenticated;
      if (authenticated && window.denyPreview) return new Response(JSON.stringify({error: 'You do not have access to this invoice.'}), {status: 403});
      return authenticated ? new Response('<html>Only synthetic invoice evidence</html>', {headers: {'Content-Type': 'text/html'}})
        : new Response(JSON.stringify({error: 'Telegram authentication data is missing.'}), {status: 401});
    };
    PortalMiniAppPayments.init({el: id => document.getElementById(id), escapeHtml: value => String(value ?? ''),
      portalApi: PortalMiniAppApi, tg: {initData}, state: {capabilities: new Set(['portal.payment.prepare'])}, showToast() {},
      apiFetch: async url => ({ok: true, data: {ok: true, ...(url.includes('/invoice-receipts/delivery-1/')
        ? {receipt_batch: receipt} : url.includes('/invoice-receipts/') ? {batches: [receipt]} : {batches: []})}}),
    });
    await PortalMiniAppPayments.load();
  }, syntheticInitData);
  await page.locator('.payment-open-receipt').click();
  await page.locator('[data-payment-receipt-dialog-cash]').click();
  await page.locator('.payment-receipt-invoice-preview').click();
  await expect(page.locator('#payment-receipt-preview-content iframe')).toHaveCount(1);
  await expect(page.locator('#payment-receipt-preview-content')).not.toContainText('authentication data is missing');
  await expect(page.locator('#payment-receipt-dialog')).toHaveAttribute('open', '');
  expect(await page.evaluate(() => window.previewAuthenticated)).toBe(true);
  await page.screenshot({path: info.outputPath(`invoice-preview-${width}.png`)});
  await page.locator('#payment-receipt-preview-close').click();
  await expect(page.locator('[data-payment-receipt-dialog-cash]')).toHaveAttribute('aria-pressed', 'true');
  await page.evaluate(() => {window.denyPreview = true;});
  await page.locator('.payment-receipt-invoice-preview').click();
  await expect(page.locator('#payment-receipt-preview-content')).toContainText('You do not have access to this invoice.');
  await expect(page.locator('#payment-receipt-preview-content iframe')).toHaveCount(0);
  await page.evaluate(() => {window.denyPreview = false;});
  await page.locator('#payment-receipt-preview-content').getByRole('button', {name: 'Retry'}).click();
  await expect(page.locator('#payment-receipt-preview-content iframe')).toHaveCount(1);
  await page.goBack();
  await expect(page.locator('#payment-receipt-preview')).not.toBeVisible();
  await expect(page.locator('#payment-receipt-dialog')).toHaveAttribute('open', '');
  await expect(page.locator('[data-payment-receipt-dialog-cash]')).toHaveAttribute('aria-pressed', 'true');
});
