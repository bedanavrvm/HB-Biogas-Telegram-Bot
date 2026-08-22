/* Synthetic local Playwright audit for the TAT private inbox and confirmation sheet. */
const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

const baseUrl = process.env.TAT_AUDIT_URL || 'http://127.0.0.1:8765/api/tat-tracker/?group_id=-100-synthetic';
const outputDir = process.env.TAT_AUDIT_OUTPUT || path.join(process.cwd(), 'tat-private-task-ui-audit');
const viewports = [
  { name: 'phone-320', width: 320, height: 568 },
  { name: 'phone-390', width: 390, height: 844 },
];

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

const task = {
  task_id: '00000000-0000-4000-8000-000000000101',
  case_id: 'JBL-BS-SYNTHETIC-01',
  stage_key: 'mpesa_to_admin',
  stage_label: 'MPESA sent to Admin',
  role: 'BRO', kind: 'primary', branch: 'Nakuru', product: 'Business',
  workflow_revision: 1, unread: true, delivery_state: 'delivered',
  created_at: '2026-08-22T09:00:00+03:00',
};

const bootstrap = {
  authorized: true,
  user: { name: 'Synthetic Officer', roles: ['BRO'], capabilities: ['tat.home.view', 'tat.case.search'] },
  workflow_mode: { mode: 'production', is_pilot: false, mode_version: 1 },
  products: [{ key: 'business', label: 'Business' }], branches: ['Nakuru'],
  bro_names: ['Synthetic Officer'], action_required: [], recent: [],
  pagination: { action_required: { total: 0 }, recent: { total: 0 } },
  task_inbox: { items: [task], unread_count: 1, total: 1 },
  private_alerts: { status: 'connected', connected: true },
  personal: { default_screen: 'home', compact_cards: true, default_filters: {} },
};

const detail = {
  summary: {
    case_id: task.case_id, client_name: 'Synthetic Applicant', product: 'Business',
    product_key: 'business', branch: 'Nakuru', status: 'Active', amount: '25000',
    national_id: '00000000', primary_phone: '254700000000', next_stage: task.stage_label,
    workflow_revision: 1, created_at: task.created_at, updated_at: task.created_at,
  },
  fields: [{
    key: task.stage_key, label: task.stage_label, role: 'BRO', kind: 'timestamp',
    value: '', raw_value: '', editable: true, locked_reason: '', options: [],
  }],
  remarks: '', events: [], timeline: [], product_requirements: [],
  product_custom_values: {}, correction_branches: ['Nakuru'], can_correct_details: false,
};

let updateCalls = 0;
let stamped = false;
let currentKind = 'timestamp';

async function installMocks(page) {
  await page.route('https://telegram.org/**', route => route.abort());
  await page.route('https://unpkg.com/**', route => route.abort());
  await page.route('https://fonts.googleapis.com/**', route => route.abort());
  await page.route('https://fonts.gstatic.com/**', route => route.abort());
  await page.route('**/tat-tracker/**', async route => {
    const url = new URL(route.request().url());
    if (route.request().resourceType() !== 'fetch' && route.request().resourceType() !== 'xhr') return route.continue();
    const json = data => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, data }) });
    if (url.pathname.endsWith('/bootstrap/')) return json(bootstrap);
    if (url.pathname.endsWith('/detail/')) return json(detail);
    if (url.pathname.endsWith('/update/')) {
      updateCalls += 1;
      stamped = true;
      detail.fields[0].value = currentKind === 'dropdown' ? 'Approved' : '22-Aug-2026 09:00';
      detail.fields[0].editable = false;
      return json(detail);
    }
    if (url.pathname.endsWith('/tasks/')) return json({
      ...(stamped ? { items: [], unread_count: 0, total: 0 } : bootstrap.task_inbox),
      private_alerts: bootstrap.private_alerts,
    });
    if (url.pathname.endsWith('/home/')) return json(bootstrap);
    return json({});
  });
}

(async () => {
  fs.mkdirSync(outputDir, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  try {
    for (const viewport of viewports) {
      stamped = false;
      currentKind = viewport.width >= 390 ? 'dropdown' : 'timestamp';
      detail.fields[0].value = '';
      detail.fields[0].editable = true;
      detail.fields[0].kind = currentKind;
      detail.fields[0].options = currentKind === 'dropdown' ? ['Approved', 'Rejected'] : [];
      const page = await browser.newPage({ viewport });
      await installMocks(page);
      await page.goto(baseUrl, { waitUntil: 'domcontentloaded' });
      await page.locator('#privateTaskSection:not([hidden])').waitFor();
      const layout = await page.evaluate(() => ({
        documentWidth: document.documentElement.scrollWidth,
        viewportWidth: document.documentElement.clientWidth,
        taskTop: document.querySelector('.task-inbox-card').getBoundingClientRect().top,
        taskWidth: document.querySelector('.task-inbox-card').getBoundingClientRect().width,
      }));
      assert(layout.documentWidth <= layout.viewportWidth + 1, `${viewport.name}: document-level horizontal overflow`);
      assert(layout.taskTop < viewport.height * 0.75, `${viewport.name}: first private task wastes too much vertical space`);
      assert(layout.taskWidth >= viewport.width - 40, `${viewport.name}: task card does not use the compact viewport width`);

      await page.locator('.task-inbox-card').click();
      const control = page.locator(currentKind === 'dropdown' ? '.stage-action-wrap select' : '.stage-action-wrap button');
      await control.waitFor();
      assert(await page.locator('#stageConfirmSheet').count() === 0, `${viewport.name}: redundant confirmation card remains in the Mini App`);
      const callsBefore = updateCalls;
      if (currentKind === 'dropdown') await control.selectOption('Approved');
      else await control.click();
      await page.locator('.stage-row.done').waitFor();
      assert(updateCalls === callsBefore + 1, `${viewport.name}: one stage action did not produce exactly one update request`);
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1);
      assert(overflow, `${viewport.name}: stamped detail causes horizontal overflow`);
      await page.screenshot({ path: path.join(outputDir, `${viewport.name}.png`), fullPage: true });
      await page.close();
    }
  } finally {
    await browser.close();
  }
  process.stdout.write(`TAT private-task visual audit passed: ${outputDir}\n`);
})().catch(error => {
  process.stderr.write(`${error.stack || error}\n`);
  process.exit(1);
});
