/* Local-only, synthetic-data visual audit for the Loan Origination Mini App. */
const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

const baseUrl = process.env.ORIGINATION_AUDIT_URL || 'http://127.0.0.1:8765/origination/';
const outputDir = process.env.ORIGINATION_AUDIT_OUTPUT || path.join(process.cwd(), 'origination-ui-audit');
const viewports = [
  { name: 'phone-320', width: 320, height: 568 },
  { name: 'phone-360', width: 360, height: 800 },
  { name: 'phone-390', width: 390, height: 844 },
  { name: 'phone-430', width: 430, height: 932 },
  { name: 'tablet-768', width: 768, height: 1024 },
];

const fields = [
  { key: 'applicant_name', label: 'Applicant name', type: 'text', section_key: 'applicant' },
  { key: 'applicant_phone', label: 'Phone number', type: 'phone', section_key: 'applicant' },
  { key: 'national_id', label: 'National ID', type: 'national_id', section_key: 'applicant' },
  { key: 'date_of_birth', label: 'Date of birth', type: 'date', section_key: 'applicant' },
  { key: 'county', label: 'County', type: 'county', section_key: 'applicant' },
  { key: 'applicant_notes', label: 'Applicant notes', type: 'textarea', width: 'full', section_key: 'applicant' },
  { key: 'business_name', label: 'Business name', type: 'text', section_key: 'business' },
  { key: 'business_type', label: 'Business type', type: 'choice', options: ['Retail', 'Farming'], section_key: 'business' },
  { key: 'loan_amount', label: 'Loan amount', type: 'money', section_key: 'loan' },
  { key: 'loan_purpose', label: 'Loan purpose', type: 'textarea', section_key: 'loan', width: 'full' },
];
const sections = [
  { key: 'applicant', label: 'Applicant', help_text: 'Identity and contact details' },
  { key: 'business', label: 'Business', help_text: 'Enterprise details' },
  { key: 'loan', label: 'Loan', help_text: 'Facility details' },
];
const application = id => ({
  id, reference_number: `JBL-2026-${String(id).padStart(4, '0')}`, product_name: id % 2 ? 'Jawabu Express' : 'Biogas Asset Finance',
  branch: 'Embu', officer_name: 'Synthetic Officer', status: 'draft', revision: 1,
  form_schema: { sections, fields }, form_payload: {}, product_terms: {}, product_requirements: {},
  product_custom_values: {}, product_selected_fee_keys: [], requirement_evidence: [],
});
const applications = Array.from({ length: 16 }, (_, index) => application(index + 1));

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

async function installApiMocks(page, delayMs = 0) {
  let createCalls = 0;
  await page.route('https://telegram.org/**', route => route.abort());
  await page.route('**/api/origination/api/**', async route => {
    if (delayMs) await new Promise(resolve => setTimeout(resolve, delayMs));
    const request = route.request();
    const url = new URL(request.url());
    const apiPath = url.pathname.replace('/api/origination/api', '');
    const json = body => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
    if (apiPath === '/products/' && request.method() === 'GET') return json({
      products: [{ product_key: 'express', name: 'Jawabu Express' }, { product_key: 'biogas', name: 'Biogas Asset Finance' }],
      branches: ['Embu', 'Nakuru'], capabilities: { can_create: true, can_review: true, can_start_signing: true },
      location_catalog: { branches: [], counties: [], branch_service_areas: {} },
    });
    if (apiPath === '/applications/' && request.method() === 'GET') return json({
      applications, counts: { draft: 16, correction_required: 2, ready_for_review: 3, reviewed: 1 },
      capabilities: { can_create: true, can_review: true, can_start_signing: true },
      pagination: { page: 1, pages: 1, total: applications.length },
    });
    if (apiPath === '/applications/' && request.method() === 'POST') {
      createCalls += 1;
      return json({ ok: true, application: application(99) });
    }
    const detail = apiPath.match(/^\/applications\/(\d+)\/$/);
    if (detail && request.method() === 'GET') return json({ ok: true, application: application(Number(detail[1])) });
    if (detail && request.method() === 'PATCH') return json({ ok: true, application: { ...application(Number(detail[1])), revision: 2 } });
    return route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ error: `Unmocked ${request.method()} ${apiPath}` }) });
  });
  return () => createCalls;
}

async function waitForList(page) {
  await page.goto(baseUrl, { waitUntil: 'domcontentloaded' });
  await page.locator('.application-card').first().waitFor();
}

async function assertSelectIsVisible(select, context) {
  const result = await select.evaluate(node => {
    const parseRgb = value => (value.match(/[\d.]+/g) || []).slice(0, 3).map(Number);
    const luminance = value => parseRgb(value).map(component => {
      const channel = component / 255;
      return channel <= .03928 ? channel / 12.92 : ((channel + .055) / 1.055) ** 2.4;
    }).reduce((sum, channel, index) => sum + channel * [.2126, .7152, .0722][index], 0);
    const trigger = node._originationSelectTrigger;
    const style = getComputedStyle(trigger);
    const optionStyle = getComputedStyle(node.options[0]);
    const values = [luminance(style.color), luminance(style.backgroundColor)].sort((a, b) => b - a);
    return {
      text: node.options[node.selectedIndex]?.textContent?.trim() || '',
      contrast: (values[0] + .05) / (values[1] + .05),
      textFill: style.webkitTextFillColor,
      color: style.color,
      optionColor: optionStyle.color,
      optionBackground: optionStyle.backgroundColor,
      triggerVisible: Boolean(trigger && trigger.getClientRects().length),
    };
  });
  assert(result.triggerVisible, `${context}: custom dropdown trigger is not visible`);
  assert(result.text, `${context}: selected option has no visible label`);
  assert(result.contrast >= 4.5, `${context}: select contrast is only ${result.contrast.toFixed(2)}:1`);
  assert(result.textFill === result.color, `${context}: WebKit text fill does not match select text (${result.textFill} / ${result.color})`);
  assert(result.optionColor !== result.optionBackground, `${context}: option foreground and background are identical`);
}

async function auditViewport(browser, viewport) {
  const page = await browser.newPage({ viewport });
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error.message || String(error)));
  await installApiMocks(page);
  await waitForList(page);
  const metrics = await page.evaluate(() => {
    const first = document.querySelector('.application-card').getBoundingClientRect();
    const cards = [...document.querySelectorAll('.application-card')].map(item => item.getBoundingClientRect());
    return {
      overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      firstTop: first.top,
      visibleCards: cards.filter(card => card.top >= 0 && card.bottom <= innerHeight).length,
    };
  });
  assert(metrics.overflow <= 1, `${viewport.name}: horizontal overflow ${metrics.overflow}px`);
  assert(metrics.firstTop <= 320, `${viewport.name}: first card begins at ${metrics.firstTop}px`);
  assert(metrics.visibleCards >= 3, `${viewport.name}: only ${metrics.visibleCards} complete cards visible`);
  await page.screenshot({ path: path.join(outputDir, `${viewport.name}-list.png`), fullPage: true });

  const start = page.locator('#origination-start');
  await start.focus();
  await start.click();
  await page.locator('#origination-sheet').waitFor();
  await assertSelectIsVisible(page.locator('#origination-create-branch'), `${viewport.name} creation branch`);
  await page.locator('#origination-create-branch + .origination-select-trigger').click();
  const optionLabels = await page.locator('#origination-select-options .origination-select-option').allTextContents();
  assert(optionLabels.some(label => label.trim() === 'Embu'), `${viewport.name}: branch option labels are not rendered in the custom picker`);
  await page.screenshot({ path: path.join(outputDir, `${viewport.name}-select-options.png`) });
  await page.locator('#origination-select-close').click();
  await page.waitForFunction(() => document.activeElement?.classList.contains('origination-select-trigger'));
  assert(await page.locator('#origination-sheet').evaluate(sheet => sheet.getBoundingClientRect().bottom <= innerHeight + 1), `${viewport.name}: sheet exceeds live viewport`);
  await page.locator('[data-sheet-cancel]').focus();
  await page.keyboard.press('Tab');
  assert(await page.locator('#origination-sheet-close').evaluate(node => document.activeElement === node), `${viewport.name}: sheet focus escaped instead of wrapping`);
  await page.screenshot({ path: path.join(outputDir, `${viewport.name}-create-sheet.png`) });
  await page.locator('#origination-sheet-close').click();
  await page.waitForFunction(() => document.activeElement?.id === 'origination-start');

  await page.locator('#origination-open-filters').click();
  await page.screenshot({ path: path.join(outputDir, `${viewport.name}-filters.png`) });
  await page.keyboard.press('Escape');

  await page.locator('.application-card').nth(8).scrollIntoViewIfNeeded();
  const before = await page.evaluate(() => scrollY);
  await page.locator('.application-card').nth(8).click();
  await page.locator('.wizard-progress-compact').waitFor();
  assert(await page.evaluate(() => scrollY <= 1), `${viewport.name}: editor did not reset scroll`);
  assert(await page.locator('input[type="date"]').count() === 0, `${viewport.name}: browser-native date input remains in the editor`);
  const dateTrigger = page.locator('[data-field="date_of_birth"] + .origination-date-trigger');
  await dateTrigger.waitFor();
  await dateTrigger.click();
  await page.screenshot({ path: path.join(outputDir, `${viewport.name}-date-picker.png`) });
  await page.locator('#origination-date-days .origination-calendar-day:not([disabled])').first().click();
  assert(/^\d{4}-\d{2}-\d{2}$/.test(await page.locator('[data-field="date_of_birth"]').inputValue()), `${viewport.name}: custom calendar did not store an ISO date`);
  await page.screenshot({ path: path.join(outputDir, `${viewport.name}-editor.png`), fullPage: true });
  await page.locator('#origination-section-picker').click();
  await page.locator('[data-section-index="1"]').click();
  assert(await page.evaluate(() => scrollY <= 1), `${viewport.name}: section change did not reset scroll`);
  await page.locator('#origination-section-picker').click();
  await page.locator('[data-section-index="2"]').click();
  const amountInput = page.locator('[data-field="loan_amount"]');
  assert(await amountInput.getAttribute('type') === 'text', `${viewport.name}: money field still uses a browser-native number control`);
  assert(await amountInput.getAttribute('inputmode') === 'decimal', `${viewport.name}: money field lost its decimal keyboard hint`);
  await page.locator('#origination-back').click();
  await page.locator('.application-card').first().waitFor();
  await page.waitForFunction(expected => Math.abs(scrollY - expected) <= 5, before);
  const restored = await page.evaluate(() => scrollY);
  assert(Math.abs(restored - before) <= 5, `${viewport.name}: list scroll was not restored (${before} -> ${restored})`);
  assert(!pageErrors.length, `${viewport.name}: browser error during field interaction: ${pageErrors.join(' | ')}`);
  await page.close();
  return metrics;
}

async function auditTelegramAndSlowNetwork(browser) {
  const page = await browser.newPage({ viewport: { width: 360, height: 800 } });
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error.message || String(error)));
  await page.addInitScript(() => {
    const state = { mainVisible: false, backVisible: false, mainText: '', mainHandler: null, backHandler: null };
    window.__telegramAudit = state;
    window.Telegram = { WebApp: {
      initData: 'synthetic', initDataUnsafe: { user: { id: 1 } }, colorScheme: 'dark',
      themeParams: { bg_color: '#17212b', secondary_bg_color: '#0e1621', text_color: '#f5f5f5', hint_color: '#a8b2bd', button_color: '#2ea66f', button_text_color: '#ffffff' },
      ready() {}, expand() {}, onEvent() {}, viewportHeight: 800, viewportStableHeight: 800,
      BackButton: { show() { state.backVisible = true; }, hide() { state.backVisible = false; }, onClick(fn) { state.backHandler = fn; } },
      MainButton: { show() { state.mainVisible = true; }, hide() { state.mainVisible = false; }, setText(value) { state.mainText = value; }, enable() {}, disable() {}, showProgress() {}, hideProgress() {}, onClick(fn) { state.mainHandler = fn; }, offClick(fn) { if (state.mainHandler === fn) state.mainHandler = null; } },
    } };
  });
  const getCreateCalls = await installApiMocks(page, 350);
  await waitForList(page);
  const contrast = await page.locator('.status-chip').first().evaluate(node => {
    const rgb = value => (value.match(/[\d.]+/g) || []).slice(0, 3).map(Number);
    const luminance = value => rgb(value).map(component => {
      const channel = component / 255;
      return channel <= .03928 ? channel / 12.92 : ((channel + .055) / 1.055) ** 2.4;
    }).reduce((sum, channel, index) => sum + channel * [.2126, .7152, .0722][index], 0);
    const style = getComputedStyle(node);
    const values = [luminance(style.color), luminance(style.backgroundColor)].sort((a, b) => b - a);
    return (values[0] + .05) / (values[1] + .05);
  });
  assert(contrast >= 4.5, `Dark-theme status badge contrast is only ${contrast.toFixed(2)}:1`);
  await page.setViewportSize({ width: 360, height: 520 });
  await page.waitForFunction(() => getComputedStyle(document.documentElement).getPropertyValue('--origination-live-height').trim() === '520px');
  await page.setViewportSize({ width: 360, height: 800 });
  await page.locator('#origination-start').click();
  await assertSelectIsVisible(page.locator('#origination-create-branch'), 'Telegram dark creation branch');
  await page.locator('#origination-create-branch + .origination-select-trigger').click();
  await page.locator('#origination-select-options .origination-select-option', { hasText: 'Embu' }).click();
  await page.locator('#origination-create-product + .origination-select-trigger:not([disabled])').waitFor();
  await page.locator('#origination-create-product + .origination-select-trigger').click();
  await page.locator('#origination-select-options .origination-select-option', { hasText: 'Jawabu Express' }).click();
  await assertSelectIsVisible(page.locator('#origination-create-product'), 'Telegram dark creation product');
  const telegramState = await page.evaluate(() => ({ ...window.__telegramAudit, mainHandler: Boolean(window.__telegramAudit.mainHandler), backHandler: Boolean(window.__telegramAudit.backHandler) }));
  assert(telegramState.mainVisible && telegramState.mainText === 'Start application', 'Telegram MainButton does not own the creation action');
  assert(await page.locator('[data-primary-action]').isHidden(), 'DOM primary remained visible with Telegram MainButton');
  await page.evaluate(() => { window.__telegramAudit.mainHandler(); window.__telegramAudit.mainHandler(); });
  await page.locator('.wizard-progress-compact').waitFor({ timeout: 5000 });
  assert(getCreateCalls() === 1, `Slow-network double tap made ${getCreateCalls()} create requests`);
  const notes = page.locator('[data-field="applicant_notes"]');
  await notes.focus();
  await page.setViewportSize({ width: 360, height: 420 });
  await page.waitForFunction(() => document.body.classList.contains('origination-input-active'));
  await page.waitForFunction(() => {
    const input = document.querySelector('[data-field="applicant_notes"]');
    return input && input.getBoundingClientRect().bottom <= (visualViewport?.height || innerHeight) - 67;
  });
  const keyboardState = await page.evaluate(() => ({
    mainVisible: window.__telegramAudit.mainVisible,
    actionPosition: getComputedStyle(document.querySelector('.wizard-actions')).position,
  }));
  assert(keyboardState.mainVisible, 'Focusing a field unexpectedly reconfigured Telegram MainButton ownership');
  assert(keyboardState.actionPosition === 'static', `Wizard actions stayed ${keyboardState.actionPosition} while the keyboard input was active`);
  await page.screenshot({ path: path.join(outputDir, 'telegram-keyboard-active.png') });
  await page.evaluate(() => document.activeElement?.blur());
  await page.setViewportSize({ width: 360, height: 800 });
  await page.waitForFunction(() => !document.body.classList.contains('origination-input-active'));
  await page.screenshot({ path: path.join(outputDir, 'telegram-dark-slow-network.png') });
  await page.evaluate(() => window.__telegramAudit.backHandler());
  await page.locator('.application-card').first().waitFor();
  assert(!(await page.evaluate(() => window.__telegramAudit.backVisible)), 'Telegram BackButton remained visible after returning to the list');
  assert(!pageErrors.length, `Telegram field interaction raised a browser error: ${pageErrors.join(' | ')}`);
  await page.close();
}

(async () => {
  fs.mkdirSync(outputDir, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  try {
    const results = [];
    for (const viewport of viewports) results.push({ viewport: viewport.name, ...(await auditViewport(browser, viewport)) });
    await auditTelegramAndSlowNetwork(browser);
    console.log(JSON.stringify({ ok: true, outputDir, results }, null, 2));
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error.stack || error); process.exit(1); });
