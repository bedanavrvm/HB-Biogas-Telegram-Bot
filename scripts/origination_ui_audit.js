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
  { key: 'applicant_full_name', label: 'Applicant full name', type: 'text', section_key: 'applicant' },
  { key: 'applicant_phone', label: 'Phone number', type: 'phone', section_key: 'applicant' },
  { key: 'applicant_national_id', label: 'National ID', type: 'national_id', section_key: 'applicant' },
  { key: 'applicant_dob', label: 'Date of birth', type: 'date', section_key: 'applicant' },
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
  applicant_summary: { name: `Synthetic Applicant ${id}`, national_id: '••••5678', phone: '••••••5678' },
  form_schema: { sections, fields }, form_payload: {}, product_terms: {}, product_requirements: {},
  product_custom_values: {}, product_selected_fee_keys: [], requirement_evidence: [],
  document_packet: {
    primary_ready: true, ready: false,
    documents: [
      { key: 'primary', name: 'Main LAF', role: 'primary', order: 0, inclusion_mode: 'required', applicable: true, selected: true, complete: true, previewed: true, schema: { fields: [] }, field_payload: {} },
      { key: 'guarantor_consent', name: 'Guarantor and home visit forms', role: 'supporting', order: 10, inclusion_mode: 'optional', officer_selectable: true, applicable: true, selected: true, complete: false, previewed: false, missing_fields: ['guarantor_name'], schema: { fields: [
        { key: 'guarantor_name', label: 'Guarantor name', type: 'text', required: true },
        { key: 'secured_assets', label: 'Secured assets', type: 'repeating_group', required: true, structure: { min_items: 1, max_items: 11, columns: [
          { key: 'description', label: 'Asset description', type: 'text', required: true },
          { key: 'estimated_value', label: 'Estimated value', type: 'money', required: true },
        ] } },
      ] }, field_payload: { secured_assets: [{ row_id: '00000000-0000-4000-8000-000000000001', description: 'Synthetic cooker', estimated_value: '12500.00' }] } },
    ],
  },
});
const applications = Array.from({ length: 16 }, (_, index) => application(index + 1));

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

async function installApiMocks(page, delayMs = 0, options = {}) {
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
      branches: ['Embu', 'Nakuru'], capabilities: { user_id: 1, can_create: true, can_review: true, can_start_signing: true },
      location_catalog: { branches: [], counties: [], branch_service_areas: {} },
    });
    if (apiPath === '/applications/' && request.method() === 'GET') return json({
      applications, counts: { draft: 16, correction_required: 2, ready_for_review: 3, reviewed: 1 },
      capabilities: { user_id: 1, can_create: true, can_review: true, can_start_signing: true },
      pagination: { page: 1, pages: 1, total: applications.length },
    });
    if (apiPath === '/applications/' && request.method() === 'POST') {
      createCalls += 1;
      return json({ ok: true, application: application(99) });
    }
    const signedPacket = apiPath.match(/^\/applications\/(\d+)\/signed-packet\/$/);
    if (signedPacket && request.method() === 'GET') {
      options.signedPacketRequests?.push({
        preview: url.searchParams.get('preview_format') === 'image',
        download: url.searchParams.get('download') === '1',
      });
      if (url.searchParams.get('preview_format') === 'image') return route.fulfill({
        status: 200, contentType: 'image/svg+xml', headers: { 'X-Preview-Page-Count': '1' },
        body: '<svg xmlns="http://www.w3.org/2000/svg" width="600" height="850"><rect width="100%" height="100%" fill="white"/><text x="40" y="80" font-size="24">Archived signed LAF</text></svg>',
      });
      return route.fulfill({
        status: 200, contentType: 'application/pdf',
        headers: { 'Content-Disposition': 'attachment; filename="JBL-2026-0001-SIGNED.pdf"' },
        body: '%PDF-synthetic-archived-packet',
      });
    }
    const testSigningAction = apiPath.match(/^\/applications\/(\d+)\/test-signing\/action\/$/);
    if (testSigningAction && request.method() === 'POST') {
      const body = JSON.parse(request.postData() || '{}');
      options.testSigningBodies?.push(body);
      const item = options.testSigningActionFactory
        ? options.testSigningActionFactory(Number(testSigningAction[1]), body)
        : (options.detailFactory || application)(Number(testSigningAction[1]));
      return json({ ok: true, replayed: false, application: item });
    }
    const detail = apiPath.match(/^\/applications\/(\d+)\/$/);
    if (detail && request.method() === 'GET') return json({ ok: true, application: (options.detailFactory || application)(Number(detail[1])) });
    if (detail && request.method() === 'PATCH') return json({ ok: true, application: { ...application(Number(detail[1])), revision: 2 } });
    return route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ error: `Unmocked ${request.method()} ${apiPath}` }) });
  });
  return () => createCalls;
}

function signingApplication(id, completedSlot = '') {
  const item = application(id);
  item.status = 'signing_pending';
  item.signing_package = {
    id: '00000000-0000-4000-8000-000000000777',
    test_stamps: [],
    test_signing: {
      enabled: true, test_mode: true, completed: false,
      slots: [
        { key: 'applicant_signature', label: 'Applicant signature', document_key: 'primary', role: 'applicant', type: 'signature', required: true, completed: completedSlot === 'applicant_signature', actor_name: completedSlot === 'applicant_signature' ? 'Synthetic Tester' : '', capture_method: completedSlot === 'applicant_signature' ? 'drawn' : '' },
        { key: 'officer_signature', label: 'Officer signature', document_key: 'primary', role: 'officer', type: 'signature', required: true, completed: completedSlot === 'officer_signature', actor_name: completedSlot === 'officer_signature' ? 'Synthetic Tester' : '', capture_method: completedSlot === 'officer_signature' ? 'typed' : '' },
      ],
    },
  };
  return item;
}

function verifiedSigningApplication(id, accessMode = '') {
  const item = application(id);
  item.status = 'signing_pending';
  item.signing_package = {
    id: '00000000-0000-4000-8000-000000000888',
    test_signing: { enabled: false, test_mode: false, slots: [] },
    verified_signing: {
      enabled: true, test_mode: false, archive_status: 'pending', production_stamps: [],
      participants: [{
        role: 'borrower', label: 'Borrower', staff: false, phone_mapped: true,
        access_mode: accessMode || 'self_service',
        session_id: accessMode ? '00000000-0000-4000-8000-000000000999' : '',
        session_status: accessMode ? 'dispatched' : '',
        slots: [{ key: 'borrower_signature', label: 'Borrower signature', document_key: 'primary', type: 'signature', required: true, completed: false }],
      }],
    },
  };
  return item;
}

function archivedSigningApplication(id) {
  const item = verifiedSigningApplication(id, 'self_service');
  item.status = 'fully_signed';
  item.signing_package.verified_signing.archive_status = 'uploaded';
  item.signing_package.verified_signing.signed_packet_available = true;
  item.signing_package.verified_signing.archived_at = '2026-08-21T18:00:00+03:00';
  const participant = item.signing_package.verified_signing.participants[0];
  participant.session_status = 'verified';
  participant.slots[0].completed = true;
  return item;
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
  assert((await page.locator('.application-card').first().textContent()).includes('Synthetic Applicant 1'), `${viewport.name}: queue card does not lead with Applicant identity`);
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
  const dateTrigger = page.locator('[data-field="applicant_dob"] + .origination-date-trigger');
  await dateTrigger.waitFor();
  await dateTrigger.click();
  assert(await page.locator('#origination-date-year option').count() >= 100, `${viewport.name}: date picker does not support direct traversal across years`);
  await page.screenshot({ path: path.join(outputDir, `${viewport.name}-date-picker.png`) });
  await page.locator('#origination-date-days .origination-calendar-day:not([disabled])').first().click();
  assert(/^\d{4}-\d{2}-\d{2}$/.test(await page.locator('[data-field="applicant_dob"]').inputValue()), `${viewport.name}: custom calendar did not store an ISO date`);
  await page.screenshot({ path: path.join(outputDir, `${viewport.name}-editor.png`), fullPage: true });
  await page.locator('#origination-section-picker').click();
  await page.locator('[data-section-index="1"]').click();
  assert(await page.evaluate(() => scrollY <= 1), `${viewport.name}: section change did not reset scroll`);
  await page.locator('#origination-section-picker').click();
  await page.locator('[data-section-index="2"]').click();
  const amountInput = page.locator('[data-field="loan_amount"]');
  assert(await amountInput.getAttribute('type') === 'text', `${viewport.name}: money field still uses a browser-native number control`);
  assert(await amountInput.getAttribute('inputmode') === 'decimal', `${viewport.name}: money field lost its decimal keyboard hint`);
  await page.locator('#origination-section-picker').click();
  await page.locator('[data-section-index="3"]').click();
  await page.locator('[data-document-select="guarantor_consent"]').waitFor();
  assert(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth <= 1), `${viewport.name}: supporting-document selection overflows`);
  await page.locator('#origination-section-picker').click();
  await page.locator('[data-section-index="4"]').click();
  await page.locator('[data-document-field="guarantor_name"]').waitFor();
  assert(await page.locator('[data-repeat-row]').count() === 1, `${viewport.name}: repeatable asset row did not render`);
  await page.locator('[data-repeat-add]').click();
  assert(await page.locator('[data-repeat-row]').count() === 2, `${viewport.name}: repeatable asset row could not be added`);
  assert(await page.locator('[data-repeat-total]').textContent() === '12,500.00', `${viewport.name}: asset total is not visible`);
  assert(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth <= 1), `${viewport.name}: supporting-document form overflows`);
  await page.screenshot({ path: path.join(outputDir, `${viewport.name}-supporting-document.png`), fullPage: true });
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
    return input && input.getBoundingClientRect().bottom <= (visualViewport?.height || innerHeight) - 3;
  });
  const keyboardState = await page.evaluate(() => ({
    mainVisible: window.__telegramAudit.mainVisible,
    actionPosition: getComputedStyle(document.querySelector('.wizard-actions')).position,
    actionDisplay: getComputedStyle(document.querySelector('.wizard-actions')).display,
  }));
  assert(!keyboardState.mainVisible, 'Telegram MainButton remained over the contracted keyboard viewport');
  assert(keyboardState.actionPosition === 'static', `Wizard actions stayed ${keyboardState.actionPosition} while the keyboard input was active`);
  assert(keyboardState.actionDisplay === 'none', `Wizard action overlay remained ${keyboardState.actionDisplay} above the keyboard`);
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

async function auditTestSignatureCapture(browser) {
  const page = await browser.newPage({ viewport: { width: 320, height: 568 } });
  const pageErrors = [];
  const actionBodies = [];
  page.on('pageerror', error => pageErrors.push(error.message || String(error)));
  await installApiMocks(page, 0, {
    detailFactory: id => signingApplication(id),
    testSigningBodies: actionBodies,
    testSigningActionFactory: (id, body) => signingApplication(id, body.slot_key),
  });
  await waitForList(page);
  await page.locator('.application-card').first().click();
  await page.locator('#origination-section-picker').click();
  await page.locator('[data-section-index]').last().click();

  await page.locator('[data-test-sign-slot]').first().click();
  const sheet = page.locator('#origination-sheet');
  const canvas = page.locator('[data-test-signature-canvas]');
  await canvas.waitFor();
  const metrics = await sheet.evaluate(node => ({
    bottom: node.getBoundingClientRect().bottom,
    viewportHeight: innerHeight,
    overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
  }));
  assert(metrics.bottom <= metrics.viewportHeight + 1, `TEST signature sheet exceeds the ${metrics.viewportHeight}px viewport (${metrics.bottom}px)`);
  assert(metrics.overflow <= 1, `TEST signature sheet causes ${metrics.overflow}px horizontal overflow`);
  const box = await canvas.boundingBox();
  await page.mouse.move(box.x + 28, box.y + 112);
  await page.mouse.down();
  await page.mouse.move(box.x + 82, box.y + 42, { steps: 5 });
  await page.mouse.move(box.x + 142, box.y + 118, { steps: 5 });
  await page.mouse.move(box.x + 244, box.y + 46, { steps: 6 });
  await page.mouse.up();
  await page.screenshot({ path: path.join(outputDir, 'phone-320-test-signature-drawn.png') });
  await page.locator('[data-test-signature-confirm]').click();
  await page.waitForFunction(() => document.getElementById('origination-sheet-overlay').hidden);
  assert(actionBodies.length === 1, `Drawn TEST signature made ${actionBodies.length} requests`);
  assert(actionBodies[0].signature_capture?.method === 'drawn', 'Drawn TEST signature request lost its capture method');
  assert(actionBodies[0].signature_capture?.strokes?.[0]?.length >= 2, 'Drawn TEST signature request has no usable stroke');

  await page.locator('.signing-test-slot:not(.is-complete) [data-test-sign-slot]').click();
  assert(await page.locator('#origination-toast').isHidden(), 'A stale toast covers the TEST signature sheet controls');
  await page.locator('[data-test-signature-mode="typed"]').click();
  await page.locator('[data-test-signature-name]').fill('Synthetic Test Signer');
  assert((await page.locator('[data-test-signature-typed-preview]').textContent()).trim() === 'Synthetic Test Signer', 'Typed signature preview did not update');
  await page.screenshot({ path: path.join(outputDir, 'phone-320-test-signature-typed.png') });
  await page.locator('[data-test-signature-confirm]').click();
  await page.waitForFunction(() => document.getElementById('origination-sheet-overlay').hidden);
  assert(actionBodies.length === 2, `Typed TEST signature made ${actionBodies.length - 1} requests`);
  assert(actionBodies[1].signature_capture?.method === 'typed', 'Typed TEST signature request lost its capture method');
  assert(actionBodies[1].signature_capture?.name === 'Synthetic Test Signer', 'Typed TEST signature request changed the entered test name');
  assert(!pageErrors.length, `TEST signature interaction raised a browser error: ${pageErrors.join(' | ')}`);
  await page.close();
}

async function auditVerifiedSigningControls(browser, width, accessMode = '') {
  const page = await browser.newPage({ viewport: { width, height: width === 320 ? 568 : 844 } });
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error.message || String(error)));
  await installApiMocks(page, 0, { detailFactory: id => verifiedSigningApplication(id, accessMode) });
  await waitForList(page);
  await page.locator('.application-card').first().click();
  await page.locator('#origination-section-picker').click();
  await page.locator('[data-section-index]').last().click();
  await page.locator('.signing-verified-panel').waitFor();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  assert(overflow <= 1, `Verified signing controls cause ${overflow}px horizontal overflow at ${width}px`);
  if (!accessMode) {
    await page.locator('[data-create-signer-session][data-access-mode="self_service"]').waitFor();
    assert(await page.getByText("Send to signer's phone", { exact: true }).isVisible(), 'Remote signing is not the primary staff action');
    assert(await page.getByText('In-person assisted signing', { exact: true }).isVisible(), 'Assisted fallback is not available');
  } else {
    assert(await page.getByText('Assisted signing', { exact: true }).isVisible(), 'Assisted signing badge is missing');
    assert(await page.getByText('Send remotely instead', { exact: true }).isVisible(), 'Remote mode switch is missing');
  }
  await page.screenshot({ path: path.join(outputDir, `phone-${width}-verified-signing-${accessMode || 'remote-default'}.png`), fullPage: true });
  assert(!pageErrors.length, `Verified signing controls raised a browser error: ${pageErrors.join(' | ')}`);
  await page.close();
}

async function auditPublicSigningPage(browser, width, accessMode) {
  const page = await browser.newPage({ viewport: { width, height: width === 320 ? 568 : 844 } });
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error.message || String(error)));
  await page.route('**/origination/sign/api/**', route => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith('/session/')) return route.fulfill({
      status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, session: {
        reference: 'ESIGN-SYNTHETIC', signer_role: 'borrower', phone_masked: '******5678',
        shared_phone_override: false, access_mode: accessMode, status: 'pending', consented: false,
        reviewed_pages: [], otp: {}, documents: [{ key: 'main', name: 'Main LAF', page_count: 1 }],
      } }),
    });
    if (url.pathname.endsWith('/packet/')) return route.fulfill({
      status: 200, contentType: 'image/svg+xml', headers: { 'X-Preview-Page-Count': '1' },
      body: '<svg xmlns="http://www.w3.org/2000/svg" width="600" height="850"><rect width="100%" height="100%" fill="white"/><text x="40" y="80" font-size="24">Synthetic loan packet</text></svg>',
    });
    return route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ error: 'Unmocked public signing endpoint' }) });
  });
  const publicUrl = new URL('/s/#synthetic-public-signing-token', baseUrl).href;
  await page.goto(publicUrl, { waitUntil: 'domcontentloaded' });
  await page.locator('#sign-content:not([hidden])').waitFor();
  await page.locator('#packet-page:not([hidden])').waitFor();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  assert(overflow <= 1, `Public signing page causes ${overflow}px horizontal overflow at ${width}px`);
  const label = accessMode === 'assisted' ? 'Assisted signing' : 'Remote signing';
  assert(await page.getByText(label, { exact: true }).isVisible(), `${label} badge is missing on the public page`);
  const assistedConfirmation = page.locator('#assisted-confirmation');
  assert(accessMode === 'assisted' ? await assistedConfirmation.isVisible() : await assistedConfirmation.isHidden(), `Assisted confirmation visibility is wrong for ${accessMode}`);
  assert(!page.url().includes('synthetic-public-signing-token'), 'Signing bearer token remained visible after public page bootstrap');
  await page.screenshot({ path: path.join(outputDir, `phone-${width}-public-${accessMode}.png`), fullPage: true });
  assert(!pageErrors.length, `Public ${accessMode} signing page raised a browser error: ${pageErrors.join(' | ')}`);
  await page.close();
}

async function auditArchivedSignedPacketAccess(browser) {
  const page = await browser.newPage({ viewport: { width: 390, height: 844 }, acceptDownloads: true });
  const pageErrors = [];
  const signedPacketRequests = [];
  page.on('pageerror', error => pageErrors.push(error.message || String(error)));
  await installApiMocks(page, 0, {
    detailFactory: id => archivedSigningApplication(id), signedPacketRequests,
  });
  await waitForList(page);
  await page.locator('.application-card').first().click();
  await page.locator('#origination-section-picker').click();
  await page.locator('[data-section-index]').last().click();
  await page.getByText('Archived signed packet', { exact: true }).waitFor();
  assert(await page.getByText('View signed LAF', { exact: true }).isVisible(), 'Archived signed LAF view action is missing');
  assert(await page.getByText('Download PDF', { exact: true }).isVisible(), 'Archived signed LAF download action is missing');
  assert(await page.locator('.wizard-actions').count() === 0, 'Read-only archived packet is obscured by a sticky action footer');
  await page.screenshot({ path: path.join(outputDir, 'phone-390-archived-signed-packet-actions.png'), fullPage: true });

  await page.getByText('View signed LAF', { exact: true }).click();
  await page.locator('#document-preview-image[src]').waitFor();
  assert(await page.locator('#preview-title').textContent() === 'Archived signed packet', 'Archived preview title is not explicit');
  const viewerLayout = await page.evaluate(() => {
    const header = document.querySelector('.preview-header');
    const close = document.querySelector('#preview-close');
    const toolbar = document.querySelector('.preview-toolbar');
    const first = toolbar?.querySelector('button');
    return {
      headerTop: header?.getBoundingClientRect().top,
      closeTop: close?.getBoundingClientRect().top,
      closeWidth: close?.getBoundingClientRect().width,
      toolbarLeft: toolbar?.getBoundingClientRect().left,
      firstLeft: first?.getBoundingClientRect().left,
    };
  });
  assert(Math.abs(viewerLayout.headerTop - viewerLayout.closeTop) <= 12, 'Archived viewer close control wraps below its header');
  assert(viewerLayout.closeWidth <= 48, `Archived viewer close control wastes ${viewerLayout.closeWidth}px of header width`);
  assert(viewerLayout.firstLeft >= viewerLayout.toolbarLeft, 'Archived viewer clips its first toolbar action');
  await page.screenshot({ path: path.join(outputDir, 'phone-390-archived-signed-packet-preview.png') });
  await page.locator('#preview-close').click();
  const downloadPromise = page.waitForEvent('download');
  await page.getByText('Download PDF', { exact: true }).click();
  const download = await downloadPromise;
  assert(download.suggestedFilename() === 'JBL-2026-0001-SIGNED.pdf', `Unexpected signed packet filename: ${download.suggestedFilename()}`);
  assert(signedPacketRequests.some(item => item.preview), 'Archived packet preview did not use the signed-packet endpoint');
  assert(signedPacketRequests.some(item => item.download), 'Archived packet download did not use the signed-packet endpoint');
  assert(!pageErrors.length, `Archived packet access raised a browser error: ${pageErrors.join(' | ')}`);
  await page.close();
}

async function auditRestrictedStorageStart(browser) {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const page = await context.newPage();
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error.message));
  await page.addInitScript(() => {
    Object.defineProperty(window, 'localStorage', {
      configurable: true,
      get() { throw new DOMException('Storage denied by WebView policy', 'SecurityError'); },
    });
    const unavailable = () => { throw new Error('Telegram bridge unavailable'); };
    window.Telegram = { WebApp: {
      initData: '', initDataUnsafe: { user: { id: 999 } }, themeParams: {},
      ready: unavailable, expand: unavailable, onEvent: unavailable,
      BackButton: { show: unavailable, hide: unavailable, onClick: unavailable },
      MainButton: {
        show: unavailable, hide: unavailable, setText: unavailable,
        enable: unavailable, disable: unavailable, showProgress: unavailable,
        hideProgress: unavailable, onClick: unavailable, offClick: unavailable,
      },
    } };
  });
  const getCreateCalls = await installApiMocks(page);
  await waitForList(page);
  await page.locator('#origination-start').click();
  await page.locator('#origination-create-branch + .origination-select-trigger').click();
  await page.locator('#origination-select-options .origination-select-option', { hasText: 'Embu' }).click();
  await page.locator('#origination-create-product + .origination-select-trigger:not([disabled])').waitFor();
  await page.locator('#origination-create-product + .origination-select-trigger').click();
  await page.locator('#origination-select-options .origination-select-option', { hasText: 'Jawabu Express' }).click();
  const submit = page.locator('#origination-create-submit');
  assert(await submit.isVisible(), 'DOM Start application fallback is hidden after Telegram bridge failure');
  await submit.click();
  await page.locator('.wizard-progress-compact').waitFor({ timeout: 5000 });
  assert(getCreateCalls() === 1, `Restricted-storage start made ${getCreateCalls()} create requests`);
  assert(!pageErrors.length, `Restricted-storage start raised a browser error: ${pageErrors.join(' | ')}`);
  await page.screenshot({ path: path.join(outputDir, 'restricted-storage-start.png'), fullPage: true });
  await context.close();
}

(async () => {
  fs.mkdirSync(outputDir, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  try {
    const results = [];
    if (process.env.ORIGINATION_AUDIT_START_ONLY !== 'true') {
      for (const viewport of viewports) results.push({ viewport: viewport.name, ...(await auditViewport(browser, viewport)) });
      await auditTelegramAndSlowNetwork(browser);
      await auditTestSignatureCapture(browser);
      await auditVerifiedSigningControls(browser, 320);
      await auditVerifiedSigningControls(browser, 390, 'assisted');
      await auditPublicSigningPage(browser, 320, 'self_service');
      await auditPublicSigningPage(browser, 390, 'assisted');
      await auditArchivedSignedPacketAccess(browser);
    }
    await auditRestrictedStorageStart(browser);
    console.log(JSON.stringify({ ok: true, outputDir, results }, null, 2));
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error.stack || error); process.exit(1); });
