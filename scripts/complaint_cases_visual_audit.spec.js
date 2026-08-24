const { test, expect } = require('playwright/test');

const cases = Array.from({ length: 23 }, (_, index) => ({
  id: `00000000-0000-0000-0000-0000000000${String(index + 1).padStart(2, '0')}`,
  case_id: `CMP-2026-${String(index + 1).padStart(3, '0')}`,
  customer_name: `Synthetic customer ${index + 1}`,
  customer_phone: `2547000000${String(index + 1).padStart(2, '0')}`,
  customer_id: `TEST-${index + 1}`,
  branch: index % 2 ? 'Embu' : 'Nakuru',
  category: index % 2 ? 'Service complaint' : 'Product issue',
  description: 'Synthetic layout-only complaint. No operational data is used.',
  status: index % 3 === 0 ? 'In Progress' : 'Open',
  recorded_at: '18 Aug 2026 10:00',
  reported_at: '18 Aug 2026 10:00',
  days_open: 1,
  revision: 2,
  priority: index % 3 === 0 ? 'high' : 'normal',
  assigned_to: index % 2 ? null : { id: '2', name: 'Synthetic Officer' },
  customer_match_status: 'unmatched',
  sync_status: index === 0 ? 'failed' : 'success',
  sync_error: index === 0 ? 'Publication pending.' : '',
  sla: {
    state: index === 0 ? 'overdue' : 'on_track', elapsed_hours: 30,
    remaining_hours: index === 0 ? -6 : 42, target_hours: 72, due_at: '19 Aug 2026 10:00',
  },
}));

function json(route, payload) {
  return route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ ok: true, ...payload }),
  });
}

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    window.Telegram = { WebApp: {
      initData: 'synthetic-init-data', ready() {}, expand() {},
      BackButton: { show() {}, hide() {}, onClick(callback) { window.__complaintBackHandler = callback; } },
      enableClosingConfirmation() {}, disableClosingConfirmation() {},
      onEvent() {}, openLink() {},
    } };
  });
  await page.route('https://telegram.org/js/telegram-web-app.js', (route) => route.fulfill({
    status: 200,
    contentType: 'application/javascript',
    body: `window.Telegram = { WebApp: {
      initData: 'synthetic-init-data', ready() {}, expand() {},
      BackButton: { show() {}, hide() {}, onClick(callback) { window.__complaintBackHandler = callback; } },
      enableClosingConfirmation() {}, disableClosingConfirmation() {},
      onEvent() {}, openLink() {}
    } };`,
  }));
  await page.route('**/api/complaints/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/bootstrap/')) return json(route, { data: {
      actor: { name: 'Synthetic Manager', is_manager: true, capabilities: [
        'complaint.queue.view', 'complaint.case.create', 'complaint.case.update',
        'complaint.case.claim', 'complaint.case.assign', 'complaint.case.close',
        'complaint.case.reopen', 'complaint.case.evidence.view', 'complaint.case.evidence.manage',
        'complaint.case.source.view', 'complaint.case.sync.retry',
      ] },
      statuses: ['Open', 'In Progress', 'Closed'], branches: ['Embu', 'Nakuru'],
      categories: ['Product issue', 'Service complaint'],
      assignees: [{ id: '2', name: 'Synthetic Officer' }],
      counts: { open: 15, in_progress: 8, closed: 0, total: 23, overdue: 1 }, personal: {}, account: {},
    } });
    if (/\/cases\/CMP-2026-\d+\/$/.test(path)) {
      const item = cases.find((row) => path.includes(row.case_id)) || cases[0];
      return json(route, { case: { ...item, updates: [], evidence: [], location: {} } });
    }
    if (path.endsWith('/cases/')) {
      const payload = route.request().postDataJSON();
      let filtered = cases.slice();
      if (payload.status === 'Open') filtered = filtered.filter((item) => item.status === 'Open');
      else if (payload.status === 'In Progress') filtered = filtered.filter((item) => item.status === 'In Progress');
      else if (payload.status === 'Closed') filtered = [];
      if (payload.branch) filtered = filtered.filter((item) => item.branch === payload.branch);
      if (payload.priority) filtered = filtered.filter((item) => item.priority === payload.priority);
      if (payload.assignment === 'mine') filtered = filtered.filter((item) => item.assigned_to);
      if (payload.assignment === 'unassigned') filtered = filtered.filter((item) => !item.assigned_to);
      if (payload.sla === 'overdue') filtered = filtered.filter((item) => item.sla.state === 'overdue');
      if (payload.query) {
        const query = String(payload.query).toLowerCase();
        filtered = filtered.filter((item) => `${item.case_id} ${item.customer_name} ${item.customer_phone} ${item.customer_id}`.toLowerCase().includes(query));
      }
      const pageNumber = Math.max(1, Number(payload.page || 1));
      const pages = Math.max(1, Math.ceil(filtered.length / 10));
      const currentPage = Math.min(pageNumber, pages);
      const start = (currentPage - 1) * 10;
      return json(route, {
        cases: filtered.slice(start, start + 10), next_cursor: '', start_index: filtered.length ? start + 1 : 0,
        pagination: { page: currentPage, pages, total: filtered.length, page_size: 10 },
      });
    }
    return json(route, {});
  });
});

for (const viewport of [
  { width: 320, height: 640 }, { width: 390, height: 844 }, { width: 768, height: 900 },
]) {
  test(`compact complaint queue and detail at ${viewport.width}px`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await page.goto('http://127.0.0.1:8007/complaints/?group_id=-100synthetic');
    await expect(page.locator('.case-row').first()).toBeVisible();
    await expect(page.locator('.case-row')).toHaveCount(10);
    await expect(page.locator('.queue-number').first()).toHaveText('#1');
    await expect(page.locator('#queuePagination')).toBeVisible();
    const queueLayout = await page.evaluate(() => ({
      documentWidth: document.documentElement.scrollWidth,
      viewportWidth: document.documentElement.clientWidth,
      firstCaseTop: document.querySelector('.case-row').getBoundingClientRect().top,
    }));
    expect(queueLayout.documentWidth).toBeLessThanOrEqual(queueLayout.viewportWidth);
    expect(queueLayout.firstCaseTop).toBeLessThan(viewport.height);
    await page.screenshot({ path: `test-results/complaint-cases-queue-${viewport.width}.png` });

    await page.locator('#openQueueFiltersBtn').click();
    await expect(page.locator('#queueFilterOverlay')).toBeVisible();
    await page.screenshot({ path: `test-results/complaint-cases-filters-${viewport.width}.png` });
    const sheetLayout = await page.evaluate(() => {
      const sheet = document.querySelector('#queueFilterSheet').getBoundingClientRect();
      const header = document.querySelector('#queueFilterSheet > header').getBoundingClientRect();
      const close = document.querySelector('#closeQueueFiltersBtn').getBoundingClientRect();
      return {
        sheetRight: sheet.right, closeRight: close.right, closeTop: close.top,
        closeWidth: close.width, closeHeight: close.height, headerTop: header.top, headerBottom: header.bottom,
        background: getComputedStyle(document.querySelector('#queueFilterSheet')).backgroundColor,
      };
    });
    expect(sheetLayout.sheetRight - sheetLayout.closeRight).toBeLessThanOrEqual(18);
    expect(sheetLayout.closeTop).toBeGreaterThanOrEqual(sheetLayout.headerTop);
    expect(sheetLayout.closeTop).toBeLessThan(sheetLayout.headerBottom);
    expect(sheetLayout.closeWidth).toBeGreaterThanOrEqual(40);
    expect(sheetLayout.closeHeight).toBeGreaterThanOrEqual(40);
    expect(sheetLayout.background).not.toBe('rgba(0, 0, 0, 0)');
    await page.locator('#branchFilter').selectOption('Nakuru');
    await page.locator('#queueFilterForm').evaluate((form) => form.requestSubmit());
    await expect(page.locator('.filter-chip')).toContainText('Nakuru');
    await page.locator('.filter-chip').click();
    await expect(page.locator('.filter-chip')).toHaveCount(0);
    await page.locator('#openQueueFiltersBtn').click();
    await page.evaluate(() => window.__complaintBackHandler());
    await expect(page.locator('#queueFilterOverlay')).toBeHidden();
    await expect(page.locator('#openQueueFiltersBtn')).toBeFocused();

    await page.locator('#queueNextBtn').click();
    await expect(page.locator('.queue-number').first()).toHaveText('#11');
    await page.locator('#queuePreviousBtn').click();
    await expect(page.locator('.queue-number').first()).toHaveText('#1');

    await page.locator('.case-row').first().click();
    await expect(page.locator('#detailView')).toBeVisible();
    await expect(page.locator('#detailSla')).toContainText('Overdue');
    const detailWidth = await page.evaluate(() => document.documentElement.scrollWidth);
    expect(detailWidth).toBeLessThanOrEqual(viewport.width);
    await page.locator('#saveBtn').scrollIntoViewIfNeeded();
    await expect(page.locator('#detailView .sticky-actions')).toHaveCSS('position', 'sticky');
    await page.screenshot({ path: `test-results/complaint-cases-${viewport.width}.png`, fullPage: true });
  });
}
