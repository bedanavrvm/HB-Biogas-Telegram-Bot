/* Synthetic local Playwright audit for the shared Unfold and Origination admin UI. */
const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

const base = process.env.ADMIN_AUDIT_URL || 'http://127.0.0.1:8766';
const output = process.env.ADMIN_AUDIT_OUTPUT || path.join(process.cwd(), 'admin-ui-audit');
const productId = '00000000-0000-0000-0000-000000000222';
const templateId = '00000000-0000-0000-0000-000000000111';
const allViewports = [
  { name: 'phone-320', width: 320, height: 568 },
  { name: 'phone-390', width: 390, height: 844 },
  { name: 'tablet-768', width: 768, height: 1024 },
  { name: 'desktop-1024', width: 1024, height: 768 },
  { name: 'desktop-1440', width: 1440, height: 900 },
];
const requestedViewport = process.env.ADMIN_AUDIT_VIEWPORT || '';
const viewports = requestedViewport
  ? allViewports.filter(item => item.name === requestedViewport)
  : allViewports;
assertViewportSelection();
const routes = [
  ['dashboard', '/admin/'],
  ['product-list', '/admin/core/product/'],
  ['product-add', '/admin/core/product/add/'],
  ['user-inlines', '/admin/auth/user/1/change/'],
  ['origination-list', '/admin/core/originationproductdefinition/'],
  ['origination-builder', `/admin/core/originationproductdefinition/${productId}/change/`],
  ['version-history', `/admin/core/originationproductdefinition/${productId}/version-history/`],
  ['template-list', '/admin/core/originationdocumenttemplate/'],
  ['template-change', `/admin/core/originationdocumenttemplate/${templateId}/change/`],
];

function assert(condition, message) { if (!condition) throw new Error(message); }
function assertViewportSelection() {
  if (requestedViewport && !viewports.length) throw new Error(`Unknown viewport: ${requestedViewport}`);
}

async function login(page) {
  await page.goto(`${base}/admin/login/`);
  await page.locator('input[name="username"]').fill('ui-audit-admin');
  await page.locator('input[name="password"]').fill('audit-password');
  await Promise.all([page.waitForURL('**/admin/**'), page.locator('button[type="submit"], input[type="submit"]').click()]);
}

async function assertContained(page, label) {
  const values = await page.evaluate(() => ({
    documentOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    bodyOverflow: document.body.scrollWidth - document.body.clientWidth,
    offenders: [...document.querySelectorAll('body *')].map(node => {
      const rect = node.getBoundingClientRect();
      return { tag: node.tagName, id: node.id, className: String(node.className || '').slice(0, 120), left: rect.left, right: rect.right, width: rect.width };
    }).filter(item => item.right > innerWidth + 2 || item.left < -2).sort((a, b) => b.right - a.right).slice(0, 6),
  }));
  assert(values.documentOverflow <= 1 && values.bodyOverflow <= 1, `${label}: document overflow ${JSON.stringify(values)}`);
}

async function auditSharedPages(browser, viewport) {
  const context = await browser.newContext({ viewport });
  const page = await context.newPage();
  await login(page);
  for (const [name, route] of routes) {
    const response = await page.goto(`${base}${route}`, { waitUntil: 'domcontentloaded' });
    assert(response && response.status() < 400, `${viewport.name}/${name}: HTTP ${response?.status()}`);
    await assertContained(page, `${viewport.name}/${name}`);
    assert(await page.locator('#nav-sidebar').count(), `${viewport.name}/${name}: Unfold sidebar selector no longer matches`);
    if (name.endsWith('list')) assert(await page.locator('#changelist-form').count(), `${viewport.name}/${name}: changelist selector no longer matches`);
    if (['product-add', 'user-inlines', 'origination-builder', 'template-change'].includes(name)) {
      assert(await page.locator('body.change-form').count(), `${viewport.name}/${name}: change-form selector no longer matches`);
    }
    if (name === 'user-inlines') assert(await page.locator('.inline-group').count(), `${viewport.name}/${name}: inline selector no longer matches`);
    if (name === 'origination-builder') {
      assert(await page.locator('#origination-product-builder').count(), `${viewport.name}: product builder missing`);
      const builderOverflow = await page.locator('#origination-product-builder').evaluate(node => node.scrollWidth - node.clientWidth);
      assert(builderOverflow <= 1, `${viewport.name}: product builder overflow ${builderOverflow}px`);
    }
    if (['dashboard', 'origination-builder', 'version-history'].includes(name)) {
      await page.screenshot({ path: path.join(output, `${viewport.name}-${name}.png`), fullPage: true });
    }
  }
  await context.close();
}

async function installCalibrationMocks(page) {
  let saveRequests = 0;
  const config = {
    field_overlay_manifest: { defaults: {}, fields: { applicant_name: {
      context_key: 'applicant_name', units: 'pt', page_number: 1,
      box: { x: 100, y: 610, width: 180, height: 30 },
      allowed_area: { x: 100, y: 610, width: 180, height: 30 },
      font: 'Helvetica', font_size: 8, min_font_size: 5, align: 'left', vertical_align: 'bottom', fit: 'shrink', padding: { x: 0, y: 0 },
    } } }, signature_overlay_manifest: { slots: {} }, sample_context: { applicant_name: 'Synthetic Applicant' },
  };
  const state = {
    configuration: config, revision: 1, schema_revision: 1,
    page_sizes: [{ page_number: 1, width: 600, height: 800 }],
    context_keys: [{ id: 'field-1', key: 'applicant_name', label: 'Applicant name', category: 'Applicant', type: 'text', attached: true, aliases: [] }],
    form_sections: [{ key: 'applicant', label: 'Applicant' }], signature_slots: [], published: false, product_published: false,
  };
  const svg = '<svg xmlns="http://www.w3.org/2000/svg" width="600" height="800"><rect width="600" height="800" fill="white"/><text x="50" y="70" font-family="Arial" font-size="22" fill="#172033">Synthetic Loan Application</text><path d="M50 160h500M50 230h500M50 300h500M50 370h500M50 440h500M50 510h500M50 580h500M50 650h500" stroke="#94a3b8"/></svg>';
  await page.route(`**/${templateId}/calibration-state/`, route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(state) }));
  await page.route(`**/${templateId}/calibration-page/**`, route => route.fulfill({ status: 200, contentType: 'image/svg+xml', body: svg }));
  await page.route(`**/${templateId}/calibration-preview/`, route => route.fulfill({ status: 200, contentType: 'image/svg+xml', body: svg }));
  await page.route(`**/${templateId}/calibration-save/`, async route => {
    saveRequests += 1;
    await new Promise(resolve => setTimeout(resolve, 350));
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, revision: 2 }) });
  });
  return () => saveRequests;
}

async function auditCalibration(browser, viewport) {
  const context = await browser.newContext({ viewport });
  const page = await context.newPage();
  const saveRequests = await installCalibrationMocks(page);
  await login(page);
  await page.goto(`${base}/admin/core/originationdocumenttemplate/${templateId}/calibrate/`, { waitUntil: 'domcontentloaded' });
  await page.locator('.calibration-box').waitFor();
  await assertContained(page, `${viewport.name}/calibration`);

  if (viewport.width <= 850) {
    assert(await page.locator('.calibration-mobile-dock').isVisible(), `${viewport.name}: mobile tool dock missing`);
    await page.locator('#cal-mobile-fields').click();
    assert(await page.locator('#calibration-sidebar').getAttribute('role') === 'dialog', `${viewport.name}: fields sheet lacks dialog role`);
    assert(await page.locator('#calibration-sidebar').getAttribute('aria-modal') === 'true', `${viewport.name}: fields sheet lacks aria-modal`);
    await page.locator('#calibration-sidebar').evaluate(sidebar => {
      const items = [...sidebar.querySelectorAll('button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [href]')]
        .filter(item => !item.hidden && item.getClientRects().length);
      items.at(-1).focus();
    });
    await page.keyboard.press('Tab');
    assert(await page.locator('#calibration-sheet-close').evaluate(node => document.activeElement === node), `${viewport.name}: fields-sheet focus did not wrap`);
    await page.keyboard.press('Escape');
    await page.waitForFunction(() => document.activeElement?.id === 'cal-mobile-fields');
  } else {
    const columns = await page.locator('.calibration-workspace').evaluate(node => getComputedStyle(node).gridTemplateColumns.split(' ').length);
    assert(columns === 2, `${viewport.name}: desktop calibration is not two-pane`);
  }

  const before = Number(await page.locator('#cal-x').inputValue());
  const box = await page.locator('.calibration-box').boundingBox();
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2 + 30, box.y + box.height / 2, { steps: 4 });
  await page.mouse.up();
  const after = Number(await page.locator('#cal-x').inputValue());
  assert(Math.abs((after - before) - 30) < .75, `${viewport.name}: 100% drag produced ${after - before} PDF points`);

  const touchBefore = Number(await page.locator('#cal-x').inputValue());
  const touchBox = await page.locator('.calibration-box').boundingBox();
  const touchStart = { x: touchBox.x + touchBox.width / 2, y: touchBox.y + touchBox.height / 2 };
  await page.locator('.calibration-box').dispatchEvent('pointerdown', {
    pointerId: 31, pointerType: 'touch', isPrimary: true, button: 0,
    clientX: touchStart.x, clientY: touchStart.y,
  });
  await page.evaluate(({ x, y }) => {
    window.dispatchEvent(new PointerEvent('pointermove', {
      bubbles: true, pointerId: 31, pointerType: 'touch', isPrimary: true,
      clientX: x + 20, clientY: y,
    }));
    window.dispatchEvent(new PointerEvent('pointerup', {
      bubbles: true, pointerId: 31, pointerType: 'touch', isPrimary: true,
      clientX: x + 20, clientY: y,
    }));
  }, touchStart);
  const touchAfter = Number(await page.locator('#cal-x').inputValue());
  assert(Math.abs((touchAfter - touchBefore) - 20) < .75, `${viewport.name}: touch drag produced ${touchAfter - touchBefore} PDF points`);

  if (viewport.width <= 850) await page.locator('#cal-mobile-view').click();
  for (const targetZoom of [.5, 1, 1.5, 2]) {
    while (Number((await page.locator('#cal-zoom-label').textContent()).replace('%', '')) / 100 < targetZoom) await page.locator('#cal-zoom-in').click();
    while (Number((await page.locator('#cal-zoom-label').textContent()).replace('%', '')) / 100 > targetZoom) await page.locator('#cal-zoom-out').click();
    const delta = await page.evaluate(() => window.__originationCalibrationGeometry.screenDeltaToPage(40, -20, { units: 'pt' }));
    assert(Math.abs(delta.x - 40 / targetZoom) < .01, `${viewport.name}: zoom ${targetZoom} coordinate drift`);
  }
  if (viewport.width <= 850) {
    await page.locator('#calibration-view-close').click();
    await page.waitForTimeout(250);
  }

  await page.evaluate(() => document.documentElement.classList.add('dark'));
  const overlay = await page.locator('.calibration-box.selected').evaluate(node => getComputedStyle(node).borderTopColor);
  assert(overlay === 'rgb(224, 68, 0)', `${viewport.name}: dark-mode overlay lost fixed contrast (${overlay})`);
  if (viewport.width <= 850) {
    const dockBackground = await page.locator('.calibration-mobile-dock').evaluate(node => getComputedStyle(node).backgroundColor);
    assert(dockBackground === 'rgb(15, 23, 42)', `${viewport.name}: dark mobile dock has ${dockBackground}`);
  }
  await page.screenshot({ path: path.join(output, `${viewport.name}-calibration-dark.png`) });

  await page.evaluate(() => { const button = document.getElementById('calibration-save'); button.click(); button.click(); });
  await page.waitForFunction(() => document.getElementById('calibration-save').disabled === false);
  assert(saveRequests() === 1, `${viewport.name}: double save made ${saveRequests()} requests`);
  await context.close();
}

(async () => {
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  try {
    for (const viewport of viewports) {
      await auditSharedPages(browser, viewport);
      await auditCalibration(browser, viewport);
    }
    console.log(JSON.stringify({ ok: true, output, viewports: viewports.map(item => item.name) }, null, 2));
  } finally { await browser.close(); }
})().catch(error => { console.error(error.stack || error); process.exit(1); });
