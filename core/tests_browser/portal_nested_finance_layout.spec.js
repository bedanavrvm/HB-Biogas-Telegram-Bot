'use strict';

const path = require('node:path');
const { test, expect } = require('playwright/test');

const asset = name => path.resolve(__dirname, '../static/miniapp', name);

async function loadPortalStyles(page) {
  for (const name of ['base.css', 'components.css', 'workflow_standard.css', 'portal.css']) {
    await page.addStyleTag({ path: asset(name) });
  }
}

async function assertNoHorizontalOverflow(page, width) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
}

test('mobile notification bell stays fixed and payment approval tabs retain native navigation', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 568 });
  await page.setContent(`<body class="workflow-standard portal-app"><header class="app-shell-header"><button class="shell-menu-button">Menu</button><div class="shell-title"><h1>Pipeline Portal</h1></div><button id="portal-notification-button" class="portal-notification-button"><span hidden>0</span></button><div class="shell-actor"><span>Active</span></div></header><main id="content"><div id="portal-screen" data-screen="payment_approvals" data-payment-batch-id=""><section id="page-payments" class="page active"><nav class="portal-invoice-tabs payment-batch-filters"><button class="active" data-payment-batch-filter="in_review"><span>Awaiting review</span><span class="count-pill" data-payment-batch-count="in_review">0</span></button><button data-payment-batch-filter="review_complete"><span>Ready to generate</span><span class="count-pill" data-payment-batch-count="review_complete">0</span></button></nav><div id="payments-batches"></div></section></div></main></body>`);
  await loadPortalStyles(page);
  await page.addScriptTag({ path: asset('portal_payments.js') });
  await page.evaluate(() => {
    window.__paymentDestination = '';
    window.PortalAppShell = { navigateUrl(url) { window.__paymentDestination = url; } };
    window.PortalMiniAppPayments.init({
      el: id => document.getElementById(id), escapeHtml: value => String(value ?? ''),
      state: { capabilities: new Set(['portal.payment.review']) },
      showToast() {},
      apiFetch: async () => ({ ok: true, data: { ok: true, batches: [{
        id: 'a63ee1b5-a446-447b-a195-d83dfcc230e3', payment_number: 12,
        status: 'in_review', status_label: 'In review', payment_mode_summary: 'Mixed',
        total_amount: '54000', counts: { total: 1, approved: 0, returned: 0, pending: 1 },
      }] } }),
    });
    return window.PortalMiniAppPayments.load();
  });

  await expect(page.locator('#portal-notification-button')).toHaveCSS('width', '32px');
  await expect(page.locator('#portal-notification-button')).toHaveCSS('flex-grow', '0');
  await expect(page.locator('[data-payment-batch-count="in_review"]')).toHaveText('1');
  await expect(page.locator('[data-payment-batch-count="review_complete"]')).toHaveText('0');
  const card = page.locator('.payment-batch-card');
  await expect(card).toHaveAttribute('href', '/portal/s/approvals/payments/a63ee1b5-a446-447b-a195-d83dfcc230e3/');
  await card.click();
  expect(await page.evaluate(() => window.__paymentDestination)).toBe('/portal/s/approvals/payments/a63ee1b5-a446-447b-a195-d83dfcc230e3/');
  await assertNoHorizontalOverflow(page, 320);
});

test('invoice filters use the shared compact sheet without overflowing a 320px phone', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 568 });
  await page.setContent(`<body class="workflow-standard portal-app"><main id="content"><div id="portal-screen" data-screen="invoices" data-invoice-view="inbox"><section id="page-invoices" class="page active">
    <section class="portal-queue-tools invoice-list-toolbar" aria-label="Invoice search and filters">
      <div class="portal-queue-tools-primary">
        <label class="portal-queue-search" for="invoice-pool-search"><span aria-hidden="true">⌕</span><input type="search" id="invoice-pool-search" placeholder="Search invoice, customer, ID, phone, order, or file"><button type="button" id="invoice-pool-search-clear" hidden>×</button></label>
        <button type="button" class="miniapp-filter-trigger" id="invoice-filter-trigger"><span>Filters</span><span class="miniapp-filter-count" id="invoice-filter-count" hidden>0</span></button>
      </div>
      <div class="miniapp-filter-chips" id="invoice-filter-chips"></div>
      <div class="miniapp-sheet-overlay" id="invoice-filter-overlay" aria-hidden="true" hidden><aside class="miniapp-sheet" id="invoice-filter-sheet" role="dialog">
        <header class="miniapp-sheet-header"><div><strong>Filter invoices</strong><p>Show invoices that need a specific kind of review.</p></div><button type="button" data-miniapp-sheet-close>×</button></header>
        <form class="miniapp-sheet-body" id="invoice-filter-form"><label for="invoice-pool-review">Show<select id="invoice-pool-review"><option value="">All records on this page</option><option value="duplicates">Possible duplicates</option></select></label><footer class="miniapp-sheet-actions"><button class="btn btn-secondary" id="invoice-pool-clear" type="button">Reset</button><button class="btn btn-primary" type="submit">Done</button></footer></form>
      </aside></div>
    </section>
    <div id="invoice-pool-summary"></div><div id="invoice-pool-list"></div><div id="pg-invoices"></div><div id="invoice-bulk-toolbar"></div>
  </section></div></main><div id="toast"></div></body>`);
  await loadPortalStyles(page);
  await page.addScriptTag({ path: asset('components.js') });
  await page.addScriptTag({ path: asset('portal_invoices.js') });
  await page.evaluate(() => {
    window.PortalMiniAppInvoices.init({
      el: id => document.getElementById(id),
      escapeHtml: value => String(value ?? ''),
      state: { capabilities: new Set(['portal.invoice.view']) },
      apiFetch: async () => ({ ok: true, data: { ok: true, summary: {}, invoices: [], pagination: { page: 1, pages: 1 } } }),
      showToast() {},
    });
  });

  await assertNoHorizontalOverflow(page, 320);
  await page.locator('#invoice-filter-trigger').click();
  await expect(page.locator('#invoice-filter-overlay')).toBeVisible();
  await assertNoHorizontalOverflow(page, 320);
  const sheet = await page.locator('#invoice-filter-sheet').boundingBox();
  expect(sheet.x).toBeGreaterThanOrEqual(0);
  expect(sheet.x + sheet.width).toBeLessThanOrEqual(320);
  const actions = await page.locator('#invoice-filter-form .miniapp-sheet-actions').boundingBox();
  expect(Math.abs(actions.y + actions.height - 568)).toBeLessThanOrEqual(14);
  await page.locator('#invoice-pool-review').selectOption('duplicates');
  await expect(page.locator('#invoice-filter-count')).toHaveText('1');
  await expect(page.locator('#invoice-filter-chips')).toContainText('Possible duplicates');
  await page.locator('#invoice-filter-form button[type="submit"]').click();
  await expect(page.locator('#invoice-filter-overlay')).toBeHidden();
});

test('operational GPS cards and JBL media errors retain their compact mobile geometry', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 568 });
  await page.setContent(`<body class="workflow-standard portal-app"><main id="content">
    <div class="sheet-overlay operational-detail-sheet final-review-sheet open"><div class="sheet-panel"><section id="sheet-map-container" class="operational-gps-summary"><div class="sheet-map-heading"><span class="sheet-map-location-icon">⌖</span><span class="sheet-map-copy"><strong>Recorded GPS</strong><span id="sheet-map-meta">GPS: -1.234567, 36.987654</span></span><span class="sheet-map-actions"><button class="map-refresh-button">↻</button><a><span>Open Maps</span></a></span></div><div id="sheet-map"></div></section></div></div>
    <section class="sheet-overlay jbl-visit-sheet open"><div class="jbl-document-slot invalid"><span>Front</span><label class="jbl-slot-picker jbl-media-icon-button">⌕</label><small class="jbl-field-error">Capture Client ID front.</small></div></section>
  </main></body>`);
  await loadPortalStyles(page);
  await expect(page.locator('.operational-gps-summary #sheet-map')).toHaveCSS('height', '170px');
  await expect(page.locator('.operational-gps-summary .sheet-map-location-icon')).toHaveCSS('display', 'grid');
  const label = await page.locator('.jbl-document-slot > span').boundingBox();
  const picker = await page.locator('.jbl-document-slot .jbl-slot-picker').boundingBox();
  const error = await page.locator('.jbl-document-slot .jbl-field-error').boundingBox();
  expect(error.y).toBeGreaterThanOrEqual(Math.max(label.y + label.height, picker.y + picker.height));
  await assertNoHorizontalOverflow(page, 320);
});

test('an empty payment detail route exposes one compact build step at 320px', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 568 });
  await page.setContent(`<body class="workflow-standard portal-app"><main id="content"><div id="portal-screen" data-screen="payments" data-payment-batch-id="batch-1"><section id="page-payments" class="page active">
    <header class="portal-queue-header"><div><h1>Payments</h1><p class="meta">Prepare, review and complete payment batches</p></div><div class="payment-header-actions"><button id="payments-refresh">↻</button><button class="btn btn-primary" id="payments-new">New batch</button></div></header>
    <nav class="portal-invoice-tabs payment-batch-filters"><button class="active" data-payment-batch-filter="open"><span>Open</span><span class="count-pill" data-payment-batch-count="open">0</span></button><button data-payment-batch-filter="completed"><span>Completed</span><span class="count-pill" data-payment-batch-count="completed">0</span></button><button data-payment-batch-filter="cancelled"><span>Cancelled</span><span class="count-pill" data-payment-batch-count="cancelled">0</span></button><button data-payment-batch-filter="all"><span>All</span><span class="count-pill" data-payment-batch-count="all">0</span></button></nav><div id="payments-batches" class="payment-batch-list"></div>
    <section id="payments-detail" class="payment-detail" hidden><header class="payment-detail-header"><button class="case-history-back" id="payments-detail-back">←</button><div><h2 id="payments-detail-title"></h2><p id="payments-detail-meta"></p></div><strong id="payments-detail-total"></strong></header><div id="payments-progress" class="payment-progress"></div>
      <section id="payments-current-section" class="payment-detail-section"><header><span class="payment-step">Batch cases</span><h3>Cases in this batch</h3></header><div id="payments-current-cases" class="payment-current-cases"></div></section>
      <section id="payments-add-panel" class="payment-detail-section payment-add-section"><header><span class="payment-step" id="payments-add-step">Add cases</span><h3 id="payments-add-title">Choose cases and payment modes</h3><p id="payments-add-help"></p></header><div class="payment-search-row"><label><span>Add cases</span><input id="payments-search" type="search" placeholder="Search customer, ID, phone, invoice or order"></label><strong id="payments-result-count">0 found</strong></div><div class="payment-filter-chips" id="payments-filter-chips" role="group"><button class="active" data-payment-filter="ready" aria-pressed="true"><span>Ready</span><b data-payment-filter-count="ready">0</b></button><button data-payment-filter="blocked" aria-pressed="false"><span>Needs review</span><b data-payment-filter-count="blocked">0</b></button><button data-payment-filter="pending" aria-pressed="false"><span>Other batch</span><b data-payment-filter-count="pending">0</b></button></div><div class="payment-selection-bar"><strong id="payments-selected-count">0 selected</strong><button id="payments-clear-selection">Clear</button><button class="btn btn-primary" id="payments-add-selected">Add selected</button></div><div id="payments-list" class="payment-candidate-list"></div></section>
      <div id="payments-detail-feedback" class="payment-detail-feedback"></div><details class="payment-activity"><summary>Batch activity</summary><div id="payments-activity"></div></details><div id="payments-primary-action" class="payment-primary-action"></div>
    </section>
  </section></div></main><div id="toast"></div></body>`);
  await loadPortalStyles(page);
  await page.addScriptTag({ path: asset('portal_payments.js') });
  await page.evaluate(() => {
    const emptyBatch = { id: 'batch-1', status: 'draft', status_label: 'Draft', payment_mode_summary: 'Payment modes chosen per case', total_amount: '0', revision: 1, counts: { total: 0, approved: 0, returned: 0, pending: 0 }, cases: [], activity: [] };
    window.PortalMiniAppPayments.init({
      el: id => document.getElementById(id), escapeHtml: value => String(value ?? ''),
      state: { capabilities: new Set(['portal.payment.prepare']) },
      setButtonLoading() {}, showToast() {}, openPortalLink() {},
      apiFetch: async (url, options = {}) => {
        if (url === '/payments/batches/' && options.method === 'POST') return { ok: true, data: { ok: true, batch: emptyBatch } };
        if (url === '/payments/batches/') return { ok: true, data: { ok: true, batches: [emptyBatch] } };
        if (url.startsWith('/payments/batches/batch-1/')) return { ok: true, data: { ok: true, batch: emptyBatch } };
        if (url.startsWith('/payments/candidates/')) return { ok: true, data: { ok: true, ready: [{farmer_id: 'farmer-1', customer_name: 'Jane Wanjiku', national_id: '12345678', row: {hb_invoice_amount: '1000', repayment_dates: '10TH'}}], blocked: [], pending_review: [] } };
        return { ok: false, data: { ok: false, error: 'Unexpected test request' } };
      },
    });
    return window.PortalMiniAppPayments.load();
  });
  await expect(page.locator('#payments-add-panel')).toBeVisible();
  await expect(page.locator('#payments-search')).toBeVisible();
  await expect(page.locator('[data-payment-filter="ready"]')).toHaveAttribute('aria-pressed', 'true');
  await expect(page.locator('[data-payment-filter-count="ready"]')).toHaveText('1');
  await page.locator('[data-payment-filter="blocked"]').click();
  await expect(page.locator('[data-payment-filter="blocked"]')).toHaveAttribute('aria-pressed', 'true');
  await page.locator('[data-payment-filter="ready"]').click();
  await expect(page.locator('.payment-candidate-cash-toggle')).toHaveAttribute('aria-label', 'Switch this case to Cash');
  await expect(page.locator('.payment-candidate-cash-toggle .sr-only')).toHaveText('Loan - Jawabu');
  await page.locator('.payment-candidate-cash-toggle').click();
  await expect(page.locator('.payment-candidate-cash-toggle')).toHaveAttribute('aria-pressed', 'true');
  await expect(page.locator('.payment-candidate-cash-toggle .sr-only')).toHaveText('Cash');
  await expect(page.locator('#payments-current-section')).toBeHidden();
  await expect(page.locator('#payments-progress')).toBeHidden();
  await expect(page.locator('.payment-activity')).toBeHidden();
  await expect(page.locator('#payments-primary-action')).toBeEmpty();
  await expect(page.locator('#payments-add-panel')).toBeVisible();
  await expect(page.locator('#payments-detail-title')).toHaveText('Payment batch');
  await expect(page.locator('#payments-detail-feedback')).toBeHidden();
  await page.evaluate(() => {
    window.__paymentBackDestination = '';
    window.PortalAppShell = { navigateUrl(url) { window.__paymentBackDestination = url; } };
  });
  await page.locator('#payments-detail-back').click();
  expect(await page.evaluate(() => window.__paymentBackDestination)).toBe('/portal/s/payments/');
  await assertNoHorizontalOverflow(page, 320);
});

test('payment detail keeps approved case facts compact and available at 320px', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 568 });
  await page.setContent(`<body class="workflow-standard portal-app"><main id="content"><div id="portal-screen" data-screen="payment_approvals" data-payment-batch-id="batch-2"><section id="page-payments" class="page active">
    <section id="payments-detail" class="payment-detail"><header class="payment-detail-header"><button class="case-history-back" id="payments-detail-back">Back</button><div class="payment-detail-heading"><h2 id="payments-detail-title"></h2><p id="payments-detail-meta"></p></div><strong id="payments-detail-total"></strong></header><div id="payments-detail-feedback"></div><div id="payments-progress" class="payment-progress"></div>
      <section id="payments-current-section" class="payment-detail-section"><header id="payments-current-heading"><h3>Needs attention</h3></header><div id="payments-current-cases" class="payment-current-cases"></div></section>
      <details class="payment-activity"><summary>Batch activity</summary><div id="payments-activity"></div></details><div id="payments-primary-action"></div>
    </section></section></div></main></body>`);
  await loadPortalStyles(page);
  await page.addScriptTag({ path: asset('portal_payments.js') });
  await page.evaluate(() => {
    const batch = {
      id: 'batch-2', payment_number: 24, status: 'completed', status_label: 'Completed', payment_mode_summary: 'Loan - Jawabu', total_amount: '54000', revision: 2,
      counts: { total: 1, approved: 1, returned: 0, pending: 0 }, activity: [],
      cases: [{ farmer_id: 'case-2', case_reference: 'JBL-24', customer_name: 'Jane Wanjiku', national_id: '12345678', primary_phone: '254712345678', branch: 'Embu Central', loan_officer: 'Mary Officer', invoice_number: 'INV-24', order_number: 'ORD-24', amount: '54000', preferred_repayment_date: '10TH', payment_mode: 'LOAN-JAWABU', payment_mode_label: 'Loan - Jawabu', decision: 'approved', comment: '', changed_since_review: false }],
    };
    window.PortalMiniAppPayments.init({
      el: id => document.getElementById(id), escapeHtml: value => String(value ?? ''),
      state: { capabilities: new Set(['portal.payment.review']) }, showToast() {}, openPortalLink() {},
      apiFetch: async () => ({ ok: true, data: { ok: true, batch } }),
    });
    return window.PortalMiniAppPayments.load();
  });
  await expect(page.locator('#payments-detail-title')).toHaveText('Payment #24');
  await expect(page.locator('#payments-detail-total')).toHaveText('KES 54,000');
  await expect(page.locator('#payments-current-section header')).toBeHidden();
  await expect(page.locator('.payment-progress .payment-progress-total')).toHaveCount(0);
  await expect(page.locator('.payment-approved-summary')).toHaveCount(0);
  await expect(page.locator('.payment-approved-cases summary')).toContainText('Approved');
  await page.locator('.payment-approved-cases summary').click();
  await expect(page.locator('.payment-approved-case-list')).toContainText('Jane Wanjiku');
  await expect(page.locator('.payment-approved-case-list')).toContainText('ID 12345678');
  await expect(page.locator('.payment-approved-case-list')).toContainText('254712345678');
  await expect(page.locator('.payment-approved-case-list')).toContainText('Embu Central');
  await expect(page.locator('.payment-approved-case-list')).toContainText('Mary Officer');
  await expect(page.locator('.payment-approved-case-list .payment-case-open')).toHaveText('View case');
  const headerBounds = await page.evaluate(() => {
    const header = document.querySelector('.payment-detail-header').getBoundingClientRect();
    const items = ['payments-detail-back', 'payments-detail-title', 'payments-detail-total'].map((id) => document.getElementById(id).getBoundingClientRect());
    return { header: {y: header.y, bottom: header.bottom, height: header.height}, items: items.map(({y, bottom}) => ({y, bottom})) };
  });
  // The title and status use a deliberate two-line block; the return control
  // and total must still be contained in that same header, not a second row.
  expect(headerBounds.header.height).toBeLessThanOrEqual(64);
  headerBounds.items.forEach((item) => {
    expect(item.y).toBeGreaterThanOrEqual(headerBounds.header.y);
    expect(item.bottom).toBeLessThanOrEqual(headerBounds.header.bottom);
  });
  await assertNoHorizontalOverflow(page, 320);
  for (const viewport of [{width: 360, height: 800}, {width: 430, height: 932}]) {
    await page.setViewportSize(viewport);
    await assertNoHorizontalOverflow(page, viewport.width);
    await expect(page.locator('#payments-detail-total')).toBeVisible();
  }
});

test('a payment detail load failure keeps Back available with a specific retry message', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 568 });
  await page.setContent(`<body class="workflow-standard portal-app"><main id="content"><div id="portal-screen" data-screen="payments" data-payment-batch-id="missing-batch"><section id="page-payments" class="page active"><section id="payments-detail" class="payment-detail"><header class="payment-detail-header"><button id="payments-detail-back">Back</button><div><h2 id="payments-detail-title">Payment batch</h2><p id="payments-detail-meta"></p></div></header><div id="payments-detail-feedback" class="payment-detail-feedback"></div><div id="payments-progress"></div><section id="payments-current-section"><div id="payments-current-cases"></div></section><details class="payment-activity"><div id="payments-activity"></div></details><div id="payments-primary-action"></div></section></section></div></main></body>`);
  await loadPortalStyles(page);
  await page.addScriptTag({ path: asset('portal_payments.js') });
  await page.evaluate(() => {
    window.__paymentBackDestination = '';
    window.PortalAppShell = { navigateUrl(url) { window.__paymentBackDestination = url; } };
    window.PortalMiniAppPayments.init({
      el: id => document.getElementById(id), escapeHtml: value => String(value ?? ''),
      state: { capabilities: new Set(['portal.payment.prepare']) }, showToast() {},
      apiFetch: async () => ({ ok: false, data: { ok: false, error: 'You do not have access to this payment batch.' } }),
    });
    return window.PortalMiniAppPayments.load();
  });
  await expect(page.locator('#payments-detail-feedback')).toContainText('You do not have access to this payment batch.');
  await expect(page.locator('#payments-detail-retry')).toBeVisible();
  await page.locator('#payments-detail-back').click();
  expect(await page.evaluate(() => window.__paymentBackDestination)).toBe('/portal/s/payments/');
  await assertNoHorizontalOverflow(page, 320);
});

test('official payment settings stack controls on a 320px phone', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 568 });
  await page.setContent(`<body class="workflow-standard portal-app"><main id="content"><section id="page-settings" class="page active"><section id="portal-payment-sequence-settings" class="portal-settings-card"><div class="portal-settings-heading"><span class="settings-eyebrow">OPERATIONS</span><h2>Official payment number</h2><p>Set the next number only when aligning the Portal with the official payment register.</p></div><div class="portal-settings-grid payment-sequence-settings-grid"><label>Next payment number<input id="payments-sequence-next" type="number" value="12"></label><label>Reason<input id="payments-sequence-reason" type="text" placeholder="Reason for the register alignment"></label></div><div class="portal-settings-action-row"><small id="payments-sequence-status">Next official payment: 12</small><button class="btn btn-primary" id="payments-sequence-save">Save official number</button></div></section></section></main></body>`);
  await loadPortalStyles(page);
  await assertNoHorizontalOverflow(page, 320);
  const status = await page.locator('#payments-sequence-status').boundingBox();
  const button = await page.locator('#payments-sequence-save').boundingBox();
  expect(button.y).toBeGreaterThan(status.y + status.height - 1);
  expect(button.width).toBeGreaterThan(250);
});
