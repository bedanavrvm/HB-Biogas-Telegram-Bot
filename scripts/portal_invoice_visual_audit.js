/* Synthetic local Playwright audit for Invoice Review and Name Changes. */
const fs = require('fs');
const os = require('os');
const path = require('path');
const { chromium } = require('playwright');

const baseUrl = process.env.PORTAL_INVOICE_AUDIT_URL || 'http://127.0.0.1:8007';
const outputDir = process.env.PORTAL_INVOICE_AUDIT_OUTPUT || path.join(os.tmpdir(), 'portal-invoice-ui-audit');
const viewports = [
  { name: 'phone-320', width: 320, height: 640 },
  { name: 'phone-390', width: 390, height: 844 },
  { name: 'tablet-768', width: 768, height: 900 },
];

const invoices = Array.from({ length: 10 }, (_, index) => ({
  id: `10000000-0000-4000-8000-${String(index + 1).padStart(12, '0')}`,
  batch_id: '20000000-0000-4000-8000-000000000001',
  batch_filename: 'synthetic-invoices.pdf', page: index + 1,
  invoice_no: `INV-${String(index + 1).padStart(3, '0')}`,
  customer_name: index === 0 ? 'Synthetic Invoice Holder' : `Synthetic Holder ${index + 1}`,
  customer_id: index === 0 ? '87654321' : `TEST${index + 1}`,
  customer_phone: '254700000001', invoice_amount: '54000', balance_due: '43500',
  status: index < 2 ? 'ambiguous' : 'unmatched', duplicate_count: index === 0 ? 2 : 0,
  payment_readiness: {}, identity: null, created_at: '2026-08-25T09:00:00+03:00',
}));

const nameChanges = Array.from({ length: 4 }, (_, index) => ({
  id: `30000000-0000-4000-8000-${String(index + 1).padStart(12, '0')}`,
  batch_id: '', batch_reference: '', batch_status: '', status: 'draft',
  applicant_name: `Synthetic Applicant ${index + 1}`,
  invoice_holder_name: `Synthetic Spouse ${index + 1}`,
  original_invoice_id: invoices[index].id, original_invoice_no: invoices[index].invoice_no,
  age_days: index * 3, revision: 1, created_at: '2026-08-20T09:00:00+03:00',
  updated_at: '2026-08-25T09:00:00+03:00',
}));

function json(route, payload, status = 200) {
  return route.fulfill({ status, contentType: 'application/json', body: JSON.stringify({ ok: status < 400, ...payload }) });
}

async function installMocks(page) {
  await page.addInitScript(() => {
    window.Telegram = { WebApp: {
      initData: 'synthetic', ready() {}, expand() {}, openLink() {},
      BackButton: { show() {}, hide() {}, onClick() {}, offClick() {} }, onEvent() {}, offEvent() {},
    } };
  });
  await page.route('https://telegram.org/**', route => route.fulfill({ status: 200, contentType: 'application/javascript', body: '' }));
  await page.route('**/api/portal/**', route => {
    const url = new URL(route.request().url());
    const apiPath = url.pathname.replace('/api/portal', '');
    if (apiPath === '/meta/') return json(route, {
      capabilities: ['portal.invoice.view', 'portal.invoice.write', 'portal.invoice_identity.manage'],
      branches: [], counties: [], location_catalog: { branches: [], counties: [] },
    });
    if (apiPath === '/invoice-pool/') return json(route, {
      summary: { batch_count: 1, invoice_count: 10, needs_action_count: 10, matched_count: 0, ignored_count: 0 },
      batches: [], invoices, pagination: { page: 1, pages: 1, total: 10 }, filters: {},
    });
    if (apiPath === '/invoice-name-changes/') return json(route, {
      items: nameChanges, batches: [], pagination: { page: 1, pages: 1, total: 4 },
      counts: { ready: 4, draft_letters: 0, awaiting_replacement: 0, completed: 0, withdrawn: 0 },
      segment: 'ready',
    });
    if (apiPath === '/settings/personal/') return json(route, { preferences: {} });
    if (apiPath === '/maintenance/') return json(route, { active: false });
    if (apiPath === '/navigation/') return route.fulfill({ status: 200, contentType: 'text/html', body: '' });
    return json(route, {});
  });
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

(async () => {
  fs.mkdirSync(outputDir, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  try {
    for (const viewport of viewports) {
      const page = await browser.newPage({ viewport });
      page.on('pageerror', error => console.error(`[${viewport.name}] page error:`, error.message));
      page.on('console', message => { if (message.type() === 'error') console.error(`[${viewport.name}] console:`, message.text()); });
      await installMocks(page);
      await page.goto(`${baseUrl}/portal/s/invoices/`, { waitUntil: 'domcontentloaded' });
      await page.locator('.invoice-pool-card').first().waitFor();
      const invoiceLayout = await page.evaluate(() => ({
        documentWidth: document.documentElement.scrollWidth,
        viewportWidth: document.documentElement.clientWidth,
        cardCount: document.querySelectorAll('.invoice-pool-card').length,
        primaryActions: Array.from(document.querySelectorAll('.invoice-pool-card')).every(card => card.querySelectorAll(':scope > .invoice-card-actions > .btn-primary').length <= 1),
      }));
      assert(invoiceLayout.documentWidth <= invoiceLayout.viewportWidth, `${viewport.name}: invoice page overflows horizontally`);
      assert(invoiceLayout.cardCount === 10, `${viewport.name}: invoice page should show ten synthetic records`);
      assert(invoiceLayout.primaryActions, `${viewport.name}: invoice card exposes multiple primary actions`);
      await page.screenshot({ path: path.join(outputDir, `invoice-review-${viewport.name}.png`), fullPage: true });

      await page.goto(`${baseUrl}/portal/s/invoices/name-changes/`, { waitUntil: 'domcontentloaded' });
      await page.locator('.invoice-name-change-card').first().waitFor();
      const nameChangeLayout = await page.evaluate(() => ({
        documentWidth: document.documentElement.scrollWidth,
        viewportWidth: document.documentElement.clientWidth,
        tabScrollWidth: document.querySelector('#invoice-name-change-tabs').scrollWidth,
        tabClientWidth: document.querySelector('#invoice-name-change-tabs').clientWidth,
        headerDisplay: getComputedStyle(document.querySelector('.invoice-page-header')).display,
        headerWidth: document.querySelector('.invoice-page-header > div').getBoundingClientRect().width,
        compactMedia: window.matchMedia('(max-width: 420px)').matches,
      }));
      assert(nameChangeLayout.documentWidth <= nameChangeLayout.viewportWidth, `${viewport.name}: name-change page overflows horizontally`);
      assert(nameChangeLayout.headerWidth >= Math.min(240, nameChangeLayout.viewportWidth - 40), `${viewport.name}: name-change header is compressed (${JSON.stringify(nameChangeLayout)})`);
      await page.locator('.name-change-select').first().check();
      await page.locator('#invoice-name-change-selection').waitFor({ state: 'visible' });
      await page.screenshot({ path: path.join(outputDir, `invoice-name-changes-${viewport.name}.png`), fullPage: true });
      await page.close();
    }
  } finally {
    await browser.close();
  }
  process.stdout.write(`Portal invoice visual audit passed. Screenshots: ${outputDir}\n`);
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
