'use strict';
const path = require('node:path');
const {test, expect} = require('playwright/test');
const asset = name => path.resolve(__dirname, '../static/miniapp', name);
const {mountPortalShell} = require('./fixtures/portal_shell');

test('rendered PDF pages use the same zoomable image viewer, not a native PDF frame', async ({page}) => {
  await page.setContent('<div id="preview"></div>');
  await page.addScriptTag({path:asset('secure_media_viewer.js')});
  await page.evaluate(() => {
    const png = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j7ioAAAAASUVORK5CYII=';
    SecureMediaViewer.renderBlob(document.getElementById('preview'), new Blob([
      `<html><body><figure><img src="${png}" alt="Page 1"></figure><figure><img src="${png}" alt="Page 2"></figure></body></html>`,
    ], {type:'text/html'}));
  });
  await expect(page.locator('#preview img')).toHaveCount(1);
  await expect(page.getByRole('button', {name:'Next page'})).toBeVisible();
  await expect(page.locator('#preview iframe')).toHaveCount(0);
  await page.getByRole('button', {name:'Next page'}).click();
  await expect(page.locator('#preview img')).toHaveAttribute('alt','Page 2');
  const stage = page.locator('.secure-media-stage');
  await stage.dispatchEvent('pointerdown', {pointerId:1, clientX:100, clientY:100});
  await stage.dispatchEvent('pointerdown', {pointerId:2, clientX:200, clientY:100});
  await stage.dispatchEvent('pointermove', {pointerId:2, clientX:300, clientY:100});
  await expect(stage).toHaveAttribute('data-zoom','2');
  await stage.dispatchEvent('pointerup', {pointerId:1, clientX:0, clientY:100});
  await stage.dispatchEvent('pointerup', {pointerId:2, clientX:300, clientY:100});
  await expect(page.locator('#preview img')).toHaveAttribute('alt','Page 2');
  await page.getByRole('button', {name:'Reset zoom'}).click();
  await stage.dispatchEvent('pointerdown', {pointerId:3, clientX:100, clientY:100});
  await stage.dispatchEvent('pointerup', {pointerId:3, clientX:230, clientY:100});
  await expect(page.locator('#preview img')).toHaveAttribute('alt','Page 1');
});

test('closing a pending HTML preview prevents late rendering and untrusted HTML never executes', async ({page}) => {
  await page.setContent('<div id="preview"></div>');
  await page.addScriptTag({path:asset('secure_media_viewer.js')});
  await page.evaluate(() => {
    const blob = new Blob(['synthetic'], {type:'text/html'});
    blob.text = () => new Promise(resolve => window.finishPreview = resolve);
    const url = SecureMediaViewer.renderBlob(document.getElementById('preview'), blob);
    SecureMediaViewer.revoke(url);
    finishPreview('<figure><img src="https://untrusted.invalid/customer"></figure><script>window.previewExecuted=true</script>');
  });
  await expect(page.locator('#preview')).toBeEmpty();
  expect(await page.evaluate(() => window.previewExecuted)).toBeUndefined();
});

test('clients with existing gesture controllers keep one image and no duplicate controls', async ({page}) => {
  await page.setContent('<div id="preview"></div>');
  await page.addScriptTag({path:asset('secure_media_viewer.js')});
  await page.evaluate(() => SecureMediaViewer.renderBlob(document.getElementById('preview'), new Blob(['synthetic'], {type:'image/png'}), {gestures:false}));
  await expect(page.locator('#preview > img')).toHaveCount(1);
  await expect(page.locator('#preview button')).toHaveCount(0);
  await expect(page.locator('#preview .secure-media-stage')).toHaveCount(0);
});

for (const width of [320, 430, 768, 1280]) {
  test(`corrected-invoice dialog uses aligned compact real components at ${width}px`, async ({page}, info) => {
    await page.setViewportSize({width, height:900});
    await mountPortalShell(page, '<div id="portal-screen" data-screen="invoices" data-invoice-view="detail" data-invoice-id="training-invoice"><div id="invoice-detail-page"></div></div>');
    await page.evaluate(() => document.body.classList.add('portal-app', 'workflow-standard'));
    await page.addScriptTag({path:asset('portal_invoices.js')});
    await page.evaluate(async () => {
      PortalMiniAppInvoices.init({state:{capabilities:new Set(['portal.invoice.write','portal.invoice_identity.manage'])},
        tg:{initData:'synthetic-only'}, showToast() {}, apiFetch:async () => ({ok:true, data:{ok:true, invoice:{
          id:'training-invoice', revision:1, status:'matched', invoice_no:'TRAIN-10', customer_name:'Training Invoice Holder', customer_id:'99999992',
          identity:{blocker:'invoice_name_change_required', status_label:'Correction required', discrepancy_codes:['national_id_mismatch'],
            invoice_identity:{name:'Training Invoice Holder', national_id:'99999992'},
            applicant_identity:{name:'Training Applicant', national_id:'99999991'}},
        }, events:[], duplicates:[]}})});
      await PortalMiniAppInvoices.load(1);
    });
    await page.locator('.invoice-name-change-start').click();
    const dialog = page.getByRole('dialog');
    await expect(dialog.getByRole('heading', {name:'Request corrected invoice'})).toBeVisible();
    const close = await dialog.getByRole('button', {name:'Close', exact:true}).boundingBox();
    const header = await dialog.locator('.sheet-header').boundingBox();
    // Chromium can return 43.99998px while a transform settles.
    expect(close.width).toBeCloseTo(44, 1);
    expect(close.height).toBeCloseTo(44, 1);
    expect(header.x + header.width - close.x - close.width).toBeLessThan(20);
    const panel = await dialog.locator('.sheet-panel').boundingBox();
    expect(panel.height).toBeLessThan(760);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    await expect(dialog.locator('.invoice-workflow-context')).toHaveCount(2);
    await page.waitForTimeout(300);
    await page.screenshot({path:info.outputPath(`invoice-correction-${width}.png`)});
  });
}

test('sent-letter download names the file and agreement upload sends the file with attestation', async ({page}) => {
  await mountPortalShell(page, '<div id="portal-screen" data-screen="invoices" data-invoice-view="detail" data-invoice-id="training-invoice"><div id="invoice-detail-page"></div></div>');
  await page.addScriptTag({path:asset('portal_invoices.js')});
  await page.evaluate(async () => {
    window.downloadCalls = []; window.uploadCalls = []; window.notices = [];
    PortalMiniAppInvoices.init({state:{capabilities:new Set(['portal.invoice.write','portal.invoice_identity.manage'])},
      tg:{initData:'synthetic-only'}, showToast:message => notices.push(message),
      downloadPortalFile:values => downloadCalls.push(values),
      portalApi:{postForm:async (url,form,tg) => {
        uploadCalls.push({url, filename:form.get('signed_letter').name, confirmed:form.get('confirmed'), initData:tg.initData});
        return {ok:true, data:{ok:true}};
      }}, apiFetch:async () => ({ok:true, data:{ok:true, invoice:{
        id:'training-invoice', status:'matched', invoice_no:'TRAIN-10', customer_name:'Training holder',
        identity:{status_label:'Waiting for corrected invoice', discrepancy_codes:['national_id_mismatch'],
          invoice_identity:{name:'Training holder', national_id:'99999992'}, applicant_identity:{name:'Training applicant', national_id:'99999991'},
          name_change:{id:'training-change', batch_id:'training-request', batch_status:'awaiting_replacements',
            status:'awaiting_replacement', original_invoice_id:'training-invoice',
            latest_letter:{id:'training-letter', filename:'Training-name-change.docx', download_url:'/synthetic-letter/', version:1}}},
      }, events:[], duplicates:[]}})});
    await PortalMiniAppInvoices.load(1);
  });
  await page.locator('.invoice-name-change-download').click();
  await expect(page.getByRole('dialog')).toContainText('Training-name-change.docx');
  await page.getByRole('button', {name:'Download', exact:true}).click();
  expect(await page.evaluate(() => downloadCalls[0].filename)).toBe('Training-name-change.docx');
  expect(await page.evaluate(() => notices.some(message => message.includes('Training-name-change.docx')))).toBe(true);
  await page.locator('.invoice-name-change-agreement').click();
  await page.locator('#invoice-signed-letter').setInputFiles({name:'Training-agreed.pdf', mimeType:'application/pdf', buffer:Buffer.from('%PDF-synthetic-fixture')});
  await page.locator('input[name="confirmed"]').check();
  await page.getByRole('button', {name:'Save agreement', exact:true}).click();
  await expect.poll(() => page.evaluate(() => uploadCalls.length)).toBe(1);
  expect(await page.evaluate(() => uploadCalls[0])).toEqual({url:'/invoice-name-changes/training-letter/agreement/',
    filename:'Training-agreed.pdf', confirmed:'yes', initData:'synthetic-only'});
});

test('receipt-origin editable batch retains the case search after refresh', async ({page}) => {
  await mountPortalShell(page, `<div id="portal-screen" data-screen="payments" data-payment-batch-id="training-batch">
    <section id="payments-detail"><h2 id="payments-detail-title"></h2><p id="payments-detail-meta"></p><b id="payments-detail-total"></b>
    <div id="payments-current-cases"></div><div id="payments-activity"></div><div id="payments-primary-action"></div>
    <section id="payments-add-panel"><input id="payments-search" type="search"><div id="payments-list"></div>
    <span id="payments-result-count"></span><span id="payments-selected-count"></span><button id="payments-clear-selection">Clear</button>
    <button id="payments-add-selected">Add selected</button></section></section></div>`);
  await page.addScriptTag({path:asset('portal_payments.js')});
  await page.evaluate(async () => {
    PortalMiniAppPayments.init({el:id=>document.getElementById(id), escapeHtml:value=>String(value ?? ''),
      state:{capabilities:new Set(['portal.payment.prepare'])}, showToast() {},
      apiFetch:async url => ({ok:true, data:url.startsWith('/payments/candidates/') ? {ok:true, ready:[], blocked:[], pending_review:[]} : {
        ok:true, batch:{id:'training-batch', receipt_batch_id:'training-delivery', status:'draft', revision:1,
          total_amount:'0', counts:{total:0}, cases:[], held_items:[], activity:[]}}})});
    await PortalMiniAppPayments.load();
  });
  await expect(page.locator('#payments-search')).toBeVisible();
  await page.evaluate(() => PortalMiniAppPayments.load());
  await expect(page.locator('#payments-search')).toBeVisible();
});
