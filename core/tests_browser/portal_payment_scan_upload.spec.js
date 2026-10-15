'use strict';
const path = require('node:path');
const {test, expect} = require('playwright/test');
const {mountPortalShell} = require('./fixtures/portal_shell');
const asset = name => path.resolve(__dirname, '../static/miniapp', name);

async function mount(page, {response = 'accepted', confirm = true, sharedDialog = false,
  filename = 'Training signed payment 89.pdf', mimeType = 'application/pdf'} = {}) {
  await mountPortalShell(page, `<div id="portal-screen" data-screen="payments" data-payment-batch-id="training-batch">
    <section id="payments-detail"><header class="payment-detail-header"><button id="payments-detail-back">Back</button>
      <div class="payment-detail-heading"><h2 id="payments-detail-title"></h2><p id="payments-detail-meta"></p></div><strong id="payments-detail-total"></strong></header>
      <div id="payments-detail-feedback"></div><div id="payments-progress"></div>
      <section id="payments-current-section"><header id="payments-current-heading"><h3>Cases</h3></header><div id="payments-current-cases"></div></section>
      <section id="payments-held-section"><div id="payments-held-items"></div></section><div id="payments-activity"></div><div id="payments-primary-action"></div>
    </section><div id="test-feedback" role="status"></div></div>`);
  await page.evaluate(() => document.body.classList.add('portal-app', 'workflow-standard'));
  await page.addScriptTag({path: asset('portal_helpers.js')});
  if (sharedDialog) await page.addScriptTag({path: asset('portal_dialogs.js')});
  await page.addScriptTag({path: asset('portal_payments.js')});
  await page.evaluate(async ({response, confirm}) => {
    window.uploads = []; window.confirmations = [];
    window.confirm = message => { confirmations.push(message); return confirm; };
    let completed = false;
    const batch = () => ({id: 'training-batch', payment_number: 89, current_document_id: 'training-document-v2',
      status: completed ? 'completed' : 'awaiting_scan', status_label: completed ? 'Completed' : 'Awaiting signed scan',
      counts: {total: 1, approved: 1, pending: 0, returned: 0}, cases: [], activity: [], held_items: [], total_amount: '1000'});
    PortalMiniAppPayments.init({
      el: id => document.getElementById(id), escapeHtml: value => String(value ?? ''), getCookie: () => '',
      state: {capabilities: new Set(['portal.payment.view', 'portal.payment.prepare', 'portal.documents.sign'])},
      apiFetch: async url => ({ok: true, data: {ok: true, batch: batch(), batches: [batch()]}}),
      setButtonLoading(button, loading) {button.disabled = loading;},
      showToast(message, type) {document.getElementById('test-feedback').textContent = message; window.lastToast = {message, type};},
      portalApi: {postForm: async (url, form) => {
        uploads.push({url, filename: form.get('signed_scan')?.name, attested: form.get('attested_complete')});
        if (form.get('attested_complete') !== 'true') return {ok: false, status: 400, data: {ok: false,
          error: 'Confirm that the scan is complete, signed, stamped, readable, and matches this exact document version.'}};
        if (response === 'rejected') return {ok: false, status: 400, data: {ok: false, error: 'The payment details changed. Review them again.'}};
        if (response === 'pending') return {ok: true, status: 202, data: {ok: false, pending_retry: true, signoff: {id: 'retained-scan'}}};
        if (response === 'delayed') await new Promise(resolve => {window.finishUpload = resolve;});
        completed = true;
        return {ok: true, status: 200, data: {ok: true, signoff: {status: 'signed_approved'}}};
      }},
    });
    await PortalMiniAppPayments.load();
  }, {response, confirm});
  await page.locator('#payments-scan-file').setInputFiles({name: filename,
    mimeType, buffer: Buffer.from('synthetic-signed-payment')});
}

test('payment upload sends the explicit attestation required by the endpoint', async ({page}, info) => {
  await page.setViewportSize({width: 320, height: 844});
  await mount(page);
  await page.locator('#payments-upload-scan').click();
  await expect.poll(() => page.evaluate(() => uploads[0]?.attested)).toBe('true');
  expect(await page.evaluate(() => uploads)).toEqual([{url: '/document-signoffs/payment/training-document-v2/upload/',
    filename: 'Training signed payment 89.pdf', attested: 'true'}]);
  await expect(page.locator('#test-feedback')).toContainText('Payment completed');
  expect(await page.evaluate(() => confirmations.length)).toBe(1);
  expect(await page.evaluate(() => confirmations[0])).toMatch(/89/);
  expect(await page.evaluate(() => confirmations[0])).toMatch(/signed.*stamped.*readable/i);
  await expect(page.locator('#payments-scan-file')).toHaveCount(0);
  await page.screenshot({path: info.outputPath('payment-upload-complete-320.png')});
});

test('cancelling signed-copy confirmation keeps the file and sends no upload', async ({page}) => {
  await mount(page, {confirm: false});
  await page.locator('#payments-upload-scan').click();
  expect(await page.evaluate(() => uploads)).toEqual([]);
  expect(await page.locator('#payments-scan-file').evaluate(input => input.files[0].name)).toBe('Training signed payment 89.pdf');
  await expect(page.locator('#payments-upload-scan')).toBeEnabled();
});

test('a rejected payment scan preserves the selected file for recovery', async ({page}) => {
  await mount(page, {response: 'rejected'});
  await page.locator('#payments-upload-scan').click();
  await expect(page.locator('#test-feedback')).toContainText('payment details changed');
  expect(await page.locator('#payments-scan-file').evaluate(input => input.files.length)).toBe(1);
  await expect(page.locator('#payments-upload-scan')).toBeEnabled();
});

test('a retained scan needing Drive retry never claims payment completion', async ({page}) => {
  await mount(page, {response: 'pending'});
  await page.locator('#payments-upload-scan').click();
  await expect(page.locator('#test-feedback')).toContainText('Document History');
  await expect(page.locator('#test-feedback')).not.toContainText('Payment completed');
  expect(await page.evaluate(() => lastToast.type)).toBe('warning');
  await expect(page.locator('#payments-upload-scan')).toBeEnabled();
});

test('repeated clicks while a signed-copy upload is pending send one request', async ({page}) => {
  await mount(page, {response: 'delayed'});
  await page.locator('#payments-upload-scan').evaluate(button => {button.click(); button.dispatchEvent(new MouseEvent('click', {bubbles: true}));});
  await expect.poll(() => page.evaluate(() => uploads.length)).toBe(1);
  await page.evaluate(() => finishUpload());
  await expect(page.locator('#test-feedback')).toContainText('Payment completed');
  expect(await page.evaluate(() => uploads.length)).toBe(1);
});

test('the shared confirmation works on a narrow phone in both themes', async ({page}, info) => {
  await page.setViewportSize({width: 320, height: 844});
  await mount(page, {sharedDialog: true});
  await page.locator('#payments-upload-scan').click();
  const dialog = page.getByRole('dialog', {name: 'Upload signed copy?'});
  await expect(dialog).toBeVisible();
  await expect(dialog.locator('input, textarea, select')).toHaveCount(0);
  await expect(dialog.getByRole('button', {name: 'Cancel'})).toBeFocused();
  await expect(page.locator('#payments-upload-scan')).toBeDisabled();
  expect(await page.evaluate(() => uploads.length)).toBe(0);
  for (const dark of [false, true]) {
    await page.evaluate(dark => {
      document.documentElement.dataset.miniappColorScheme = dark ? 'dark' : 'light';
      const colors = dark ? {bg:'#17171e', 'secondary-bg':'#20202c', text:'#ffffff', hint:'#a8a8b3'}
        : {bg:'#f5f7f8', 'secondary-bg':'#ffffff', text:'#17212b', hint:'#6d7a86'};
      for (const [key, value] of Object.entries(colors)) document.documentElement.style.setProperty('--tg-theme-' + key + '-color', value);
    }, dark);
    const rect = await dialog.boundingBox();
    expect(rect.x).toBeGreaterThanOrEqual(12);
    expect(rect.x + rect.width).toBeLessThanOrEqual(308);
    expect(rect.height).toBeLessThan(300);
    await page.screenshot({path: info.outputPath(`payment-scan-confirmation-320-${dark ? 'dark' : 'light'}.png`)});
  }
  await dialog.getByRole('button', {name: 'Cancel'}).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.locator('#payments-upload-scan')).toBeEnabled();
  expect(await page.evaluate(() => uploads.length)).toBe(0);
  expect(await page.locator('#payments-scan-file').evaluate(input => input.files.length)).toBe(1);
  await page.locator('#payments-upload-scan').click();
  await dialog.getByRole('button', {name: 'Upload', exact: true}).click();
  await expect(page.locator('#test-feedback')).toContainText('Payment completed');
  expect(await page.evaluate(() => uploads)).toHaveLength(1);
  expect(await page.evaluate(() => confirmations)).toEqual([]);
});

for (const [extension, mimeType] of [['jpg', 'image/jpeg'], ['png', 'image/png']]) {
  test(`signed payment ${extension.toUpperCase()} sends the same confirmed upload`, async ({page}) => {
    const filename = `Training signed payment 89.${extension}`;
    await mount(page, {filename, mimeType});
    await page.locator('#payments-upload-scan').click();
    await expect(page.locator('#test-feedback')).toContainText('Payment completed');
    expect(await page.evaluate(() => uploads[0])).toMatchObject({filename, attested: 'true'});
  });
}
