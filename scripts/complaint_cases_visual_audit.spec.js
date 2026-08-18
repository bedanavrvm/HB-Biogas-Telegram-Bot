const { test, expect } = require('@playwright/test');

const cases = Array.from({ length: 8 }, (_, index) => ({
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
      BackButton: { show() {}, hide() {}, onClick() {} },
      enableClosingConfirmation() {}, disableClosingConfirmation() {},
      onEvent() {}, openLink() {},
    } };
  });
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
      counts: { open: 6, in_progress: 2, closed: 0 }, personal: {}, account: {},
    } });
    if (/\/cases\/CMP-2026-\d+\/$/.test(path)) {
      const item = cases.find((row) => path.includes(row.case_id)) || cases[0];
      return json(route, { case: { ...item, updates: [], evidence: [], location: {} } });
    }
    if (path.endsWith('/cases/')) return json(route, { cases, next_cursor: 'synthetic-next' });
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
    const queueLayout = await page.evaluate(() => ({
      documentWidth: document.documentElement.scrollWidth,
      viewportWidth: document.documentElement.clientWidth,
      firstCaseTop: document.querySelector('.case-row').getBoundingClientRect().top,
      controlHeight: document.querySelector('#branchFilter').getBoundingClientRect().height,
    }));
    expect(queueLayout.documentWidth).toBeLessThanOrEqual(queueLayout.viewportWidth);
    expect(queueLayout.firstCaseTop).toBeLessThan(viewport.height);
    expect(queueLayout.controlHeight).toBeLessThanOrEqual(44);

    await page.locator('.case-row').first().click();
    await expect(page.locator('#detailView')).toBeVisible();
    await expect(page.locator('#detailSla')).toContainText('Overdue');
    const detailWidth = await page.evaluate(() => document.documentElement.scrollWidth);
    expect(detailWidth).toBeLessThanOrEqual(viewport.width);
  });
}
