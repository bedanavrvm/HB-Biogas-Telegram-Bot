'use strict';
const fs = require('node:fs');
const path = require('node:path');
const {test, expect} = require('playwright/test');
const {mountPortalShell} = require('./fixtures/portal_shell');
const asset = name => path.resolve(__dirname, '../static/miniapp', name);
const template = fs.readFileSync(path.resolve(__dirname, '../templates/portal/portal.html'), 'utf8')
  .replace(/{%[^]*?%}/g, '').replace(/{{[^]*?}}/g, '');

for (const width of [320, 1280]) for (const partner of ['HB', 'ECOCONSERVE']) for (const draft of [true, false]) {
  test(`payment preview uses its payment number, not ${partner} order number: ${draft ? 'draft' : 'generated'} ${width}px`, async ({page}, info) => {
    await page.setViewportSize({width, height: 844});
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await mountPortalShell(page, `<main id="portal-screen" data-screen="payments" data-payment-batch-id="synthetic-payment">
      <section id="payments-detail" class="payment-detail"><header class="payment-detail-header">
        <button id="payments-detail-back">Back</button><div class="payment-detail-heading"><h2 id="payments-detail-title"></h2><p id="payments-detail-meta"></p></div><strong id="payments-detail-total"></strong>
      </header><div id="payments-detail-feedback"></div><div id="payments-progress"></div>
      <section id="payments-current-section"><header id="payments-current-heading"><h3>Cases</h3></header><div id="payments-current-cases"></div></section>
      <section id="payments-held-section"><div id="payments-held-items"></div></section><div id="payments-activity"></div><div id="payments-primary-action"></div></section></main>`);
    await page.evaluate(html => {
      document.body.classList.add('portal-app', 'workflow-standard');
      const source = document.createElement('template'); source.innerHTML = html;
      for (const id of ['payment-preview-overlay', 'requisition-preview-overlay']) {
        document.body.appendChild(source.content.querySelector('#' + id).cloneNode(true));
      }
    }, template);
    await page.addScriptTag({path: asset('portal_helpers.js')});
    await page.addScriptTag({path: asset('portal_requisitions.js')});
    await page.addScriptTag({path: asset('portal_payments.js')});
    await page.evaluate(async ({partner, draft}) => {
      const order = partner === 'ECOCONSERVE' ? 'ECO-37' : 'HB-37';
      window.previewRequests = [];
      const deps = {
        el: id => document.getElementById(id), escapeHtml: value => String(value ?? ''), fmtDate: value => value || '',
        state: {capabilities: new Set(['portal.payment.view', 'portal.payment.prepare']), requisitionPartner: partner},
        setButtonLoading() {}, showToast() {},
        apiFetch: async url => {
          previewRequests.push(url);
          if (url.endsWith('/preview/')) return {ok: true, data: {ok: true, preview: {
            draft, payment_number: draft ? '' : 89, order_numbers: [order], ready_count: 1,
            rows: [{name: 'Synthetic Applicant', cust_no: 'TRAINING', order_no: order, hb_invoice_amount: '1000', payment_mode: 'CASH'}],
            totals: {hb_invoice_amount: '1000'},
          }}};
          return {ok: true, data: {ok: true, batch: {id: 'synthetic-payment', status: draft ? 'draft' : 'awaiting_scan',
            status_label: draft ? 'Draft' : 'Awaiting signed scan', payment_number: draft ? null : 89,
            counts: {total: 1, pending: 0, approved: 1, returned: 0}, total_amount: '1000',
            cases: [{farmer_id: 'training-case', customer_name: 'Synthetic Applicant', amount: '1000', decision: 'approved', payment_mode: 'CASH'}],
            activity: [], held_items: [],
          }}};
        },
      };
      PortalMiniAppRequisitions.init(deps);
      PortalMiniAppPayments.init({...deps, requisitions: PortalMiniAppRequisitions});
      await PortalMiniAppPayments.load();
    }, {partner, draft});
    await page.getByRole('button', {name: 'Preview payment', exact: true}).click();
    await expect(page.locator('#payment-preview-overlay')).toHaveClass(/open/);
    await expect(page.locator('#requisition-preview-overlay')).not.toHaveClass(/open/);
    const header = page.locator('#payment-preview-content .payment-print-preview > header');
    await expect(header).toContainText('Payment No:');
    await expect(header).toContainText(draft ? 'Not assigned' : '89');
    await expect(header).not.toContainText('Order No:');
    await expect(header).not.toContainText('37');
    await expect(page.locator('#payment-preview-content')).not.toContainText('Requisition Form');
    expect(await page.evaluate(() => previewRequests.filter(url => url.endsWith('/preview/'))))
      .toEqual(['/payments/batches/synthetic-payment/preview/']);
    await page.locator('[data-payment-preview-view="sheet"]').click();
    await expect(page.locator('.payment-print-scroll')).toContainText(partner === 'ECOCONSERVE' ? 'ECO-37' : 'HB-37');
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({path: info.outputPath(`payment-${partner}-${draft ? 'draft' : 'generated'}-${width}.png`)});
    expect(errors).toEqual([]);
  });
}
