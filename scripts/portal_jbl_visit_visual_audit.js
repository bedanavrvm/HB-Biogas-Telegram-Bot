/* Synthetic local Playwright audit for the rendered Portal JBL Visit workspace. */
'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const { chromium } = require('playwright');

const baseUrl = process.env.PORTAL_JBL_AUDIT_URL || 'http://127.0.0.1:8007';
const outputDir = process.env.PORTAL_JBL_AUDIT_OUTPUT || path.join(os.tmpdir(), 'portal-jbl-visit-ui-audit');
const viewports = [
  { name: 'phone-320', width: 320, height: 640 },
  { name: 'phone-390', width: 390, height: 844 },
  { name: 'desktop-1024', width: 1024, height: 900 },
];

const farmer = {
  id: '10000000-0000-4000-8000-000000000001',
  customer_name: 'David Mugambi', national_id: '23215888', primary_phone: '254721997481',
  county: 'Embu', county_ref_code: 'EMBU', sub_county: '', village: '', branch: 'Embu',
  hbg_visit_date: '2026-05-02', hbg_visit_date_label: '02-05-26', hb_sales_person: 'Michael Mugambi',
  jbl_visit_date: '', jbl_visit_status: '', jbl_officer: '', jbl_visit_comment: '',
  jbl_media_count: 3, latitude: '', longitude: '', workflow_revision: 1,
};

function json(route, payload, status = 200) {
  return route.fulfill({ status, contentType: 'application/json', body: JSON.stringify({ ok: status < 400, ...payload }) });
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

async function installMocks(page) {
  await page.addInitScript(() => {
    window.__jblAuditHaptics = [];
    window.Telegram = { WebApp: {
      initData: 'synthetic', colorScheme: 'light', themeParams: {},
      ready() {}, expand() {}, disableVerticalSwipes() {}, openLink() {},
      BackButton: { show() {}, hide() {}, onClick() {}, offClick() {} },
      HapticFeedback: {
        impactOccurred(kind) { window.__jblAuditHaptics.push(`impact:${kind}`); },
        notificationOccurred(kind) { window.__jblAuditHaptics.push(`notification:${kind}`); },
      },
      onEvent() {}, offEvent() {},
    } };
    const track = { stop() {} };
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { getUserMedia: async () => ({ getTracks: () => [track] }) },
    });
    Object.defineProperty(HTMLMediaElement.prototype, 'srcObject', {
      configurable: true,
      get() { return this.__syntheticStream || null; },
      set(value) { this.__syntheticStream = value; },
    });
    HTMLMediaElement.prototype.play = async function play() {
      Object.defineProperty(this, 'videoWidth', { configurable: true, value: 1280 });
      Object.defineProperty(this, 'videoHeight', { configurable: true, value: 960 });
    };
    HTMLCanvasElement.prototype.getContext = function getContext() { return { drawImage() {} }; };
    HTMLCanvasElement.prototype.toBlob = function toBlob(callback, type) {
      callback(new Blob(['synthetic-camera-frame'], { type: type || 'image/jpeg' }));
    };
  });
  await page.route('https://telegram.org/**', route => route.fulfill({ status: 200, contentType: 'application/javascript', body: '' }));
  await page.route('**/api/portal/**', route => {
    const apiPath = new URL(route.request().url()).pathname.replace('/api/portal', '');
    if (apiPath === '/meta/') return json(route, {
      capabilities: ['portal.jbl_queue.view', 'portal.jbl_visit.write', 'portal.jbl_media.view', 'portal.jbl_media.write'],
      jbl_visit_statuses: ['Approved', 'Awaiting Analysis', 'Rejected', 'Rescheduled'],
      branches: ['Embu'], counties: ['Embu'], business_date: '2026-09-03',
      location_catalog: { counties: [{ code: 'EMBU', name: 'Embu' }] },
      jbl_visit_media_max_bytes: 20 * 1024 * 1024,
      jbl_visit_media_max_files: 6,
      jbl_visit_media_max_total_bytes: 40 * 1024 * 1024,
      jbl_visit_draft_fields: ['jbl-date', 'jbl-status', 'jbl-officer', 'jbl-county', 'jbl-sub-county', 'jbl-village', 'jbl-comment', 'jbl-lat', 'jbl-lng', 'jbl-location-unavailable'],
      voice_input: { enabled: true, fields: ['jbl_visit_comment'] },
    });
    if (apiPath.endsWith('/draft/')) return json(route, { draft: null });
    if (apiPath === '/location-options/') return json(route, {
      counties: [{ code: 'EMBU', name: 'Embu' }], sub_counties: [{ code: 'MANYATTA', name: 'Manyatta' }],
      selected_county: { code: 'EMBU', name: 'Embu' },
    });
    if (apiPath.endsWith('/media/list/')) return json(route, { media: [{
      id: 'legacy-1', category: 'LEGACY', name: 'Older visit attachment with a deliberately long descriptive filename.pdf',
      preview_url: '', open_url: '/synthetic-media-open/', mime_type: 'application/pdf',
    }] });
    if (apiPath === '/settings/personal/') return json(route, { preferences: {} });
    if (apiPath === '/maintenance/') return json(route, { active: false });
    if (apiPath === '/navigation/') return route.fulfill({ status: 200, contentType: 'text/html', body: '' });
    return json(route, { items: [], pagination: { page: 1, pages: 1, total: 0 } });
  });
}

async function openVisit(page) {
  await page.goto(`${baseUrl}/portal/s/jbl/`, { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => window.PortalMiniAppFarmerSheet?.openFarmerSheet);
  await page.waitForTimeout(250);
  await page.evaluate(value => window.PortalMiniAppFarmerSheet.openFarmerSheet(value, 'jbl_visit'), farmer);
  await page.locator('#sheet-overlay.jbl-visit-sheet.open').waitFor();
  await page.locator('#jbl-status').waitFor();
  // Capture the settled UI, not a translucent frame from the 200 ms overlay
  // animation (which would make the queue beneath the sheet appear to leak).
  await page.waitForTimeout(250);
}

(async () => {
  fs.mkdirSync(outputDir, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  try {
    for (const viewport of viewports) {
      const page = await browser.newPage({ viewport });
      const pageErrors = [];
      page.on('pageerror', error => pageErrors.push(error.message));
      await installMocks(page);
      await openVisit(page);

      const layout = await page.evaluate(() => {
        const rows = [...document.querySelectorAll('.jbl-details-grid .form-row')].map(row => {
          const box = row.getBoundingClientRect();
          return { width: Math.round(box.width), height: Math.round(box.height) };
        });
        const overlay = document.querySelector('#sheet-overlay');
        const panel = overlay.querySelector('.sheet-panel').getBoundingClientRect();
        const back = document.querySelector('#sheet-back').getBoundingClientRect();
        return {
          documentWidth: document.documentElement.scrollWidth,
          viewportWidth: document.documentElement.clientWidth,
          rows,
          backLeft: Math.round(back.left - panel.left),
          languageButtons: document.querySelectorAll('.voice-language-button').length,
          languageText: document.querySelector('.voice-language-button')?.textContent.trim(),
          visibleMediaActionText: [...document.querySelectorAll('.jbl-media-icon-button span:not(.sr-only)')].map(node => node.textContent.trim()),
          inputBorders: [...document.querySelectorAll('.jbl-details-grid input:not([type="hidden"]), .jbl-details-grid select')].map(node => getComputedStyle(node).borderWidth),
          mediaCategories: [...document.querySelectorAll('.jbl-media-grid .media-category-upload')].map(node => ({
            width: Math.round(node.getBoundingClientRect().width),
            title: node.querySelector('.jbl-media-category-heading > span')?.textContent.trim(),
          })),
          biodataAlignment: [...document.querySelectorAll('#sheet-info .info-row')].map(node => {
            const cell = node.getBoundingClientRect();
            const label = node.querySelector('.ir-label')?.getBoundingClientRect();
            const value = node.querySelector('.ir-value')?.getBoundingClientRect();
            return {
              textAlign: getComputedStyle(node).textAlign,
              alignedStart: Boolean(label && value && Math.abs(label.left - value.left) <= 1),
              cellStart: Boolean(label && label.left - cell.left <= 13),
            };
          }),
          panelWidth: Math.round(panel.width),
        };
      });
      assert(layout.documentWidth <= layout.viewportWidth, `${viewport.name}: document overflows horizontally`);
      assert(layout.rows.length === 6, `${viewport.name}: expected six visit detail cells`);
      for (let index = 0; index < layout.rows.length; index += 2) {
        assert(Math.abs(layout.rows[index].width - layout.rows[index + 1].width) <= 1, `${viewport.name}: field pair widths are asymmetric`);
        assert(Math.abs(layout.rows[index].height - layout.rows[index + 1].height) <= 1, `${viewport.name}: field pair heights are asymmetric`);
      }
      assert(layout.backLeft <= 16, `${viewport.name}: back button is not aligned to the left edge`);
      assert(layout.languageButtons === 1 && layout.languageText === 'Auto', `${viewport.name}: language selector must show one current value`);
      assert(layout.visibleMediaActionText.length === 0, `${viewport.name}: media icons repeat visible action text`);
      assert(layout.inputBorders.every(value => value === '0px'), `${viewport.name}: fields have redundant inner borders`);
      assert(layout.mediaCategories.length === 2, `${viewport.name}: expected two media categories`);
      assert(Math.abs(layout.mediaCategories[0].width - layout.mediaCategories[1].width) <= 1, `${viewport.name}: media categories are asymmetric`);
      assert(layout.mediaCategories[0].title === 'LAF' && layout.mediaCategories[1].title === 'Visit Photos', `${viewport.name}: media category titles are clipped or incorrect`);
      assert(layout.biodataAlignment.length === 4, `${viewport.name}: expected four biodata cells`);
      assert(layout.biodataAlignment.every(item => item.textAlign === 'left' && item.alignedStart && item.cellStart), `${viewport.name}: biodata labels and values are not left-aligned`);
      if (viewport.width >= 760) assert(layout.panelWidth <= 680, `${viewport.name}: desktop dialog is too wide`);

      await page.screenshot({ path: path.join(outputDir, `jbl-visit-${viewport.name}.png`), fullPage: true });

      await page.locator('#jbl-visit-photo-camera').click();
      await page.waitForTimeout(300);
      const cameraState = await page.evaluate(() => ({
        hidden: document.querySelector('#jbl-live-camera')?.hidden,
        toast: document.querySelector('#toast')?.textContent.trim(),
        hasGetUserMedia: typeof navigator.mediaDevices?.getUserMedia === 'function',
      }));
      assert(cameraState.hidden === false, `${viewport.name}: camera did not open (${JSON.stringify(cameraState)})`);
      await page.locator('#jbl-camera-shutter:not([disabled])').waitFor();
      const closeWidth = await page.locator('#jbl-camera-close').evaluate(node => Math.round(node.getBoundingClientRect().width));
      assert(closeWidth <= 32, `${viewport.name}: camera close control stretches to ${closeWidth}px`);
      const cameraViewportHeight = await page.locator('.jbl-camera-viewport').evaluate(node => Math.round(node.getBoundingClientRect().height));
      assert(cameraViewportHeight >= 320, `${viewport.name}: camera viewport is vertically cramped (${cameraViewportHeight}px)`);
      const shutterShape = await page.locator('#jbl-camera-shutter').evaluate(node => {
        const outer = node.getBoundingClientRect();
        const inner = node.querySelector('[aria-hidden="true"]')?.getBoundingClientRect();
        return {
          outerWidth: Math.round(outer.width), outerHeight: Math.round(outer.height),
          innerWidth: Math.round(inner?.width || 0), innerHeight: Math.round(inner?.height || 0),
          radius: getComputedStyle(node).borderRadius,
        };
      });
      assert(shutterShape.outerWidth === shutterShape.outerHeight && shutterShape.innerWidth === shutterShape.innerHeight && shutterShape.radius === '50%', `${viewport.name}: camera shutter is distorted (${JSON.stringify(shutterShape)})`);
      await page.screenshot({ path: path.join(outputDir, `jbl-camera-${viewport.name}.png`), fullPage: true });
      await page.locator('#jbl-camera-shutter').click();
      await page.locator('#jbl-visit-photo-media-name').waitFor({ state: 'visible' });
      const captureSummary = (await page.locator('#jbl-visit-photo-media-name').textContent()).trim();
      assert(captureSummary.startsWith('1 selected'), `${viewport.name}: camera shutter did not add the photo (${captureSummary})`);
      const captureHaptics = await page.evaluate(() => window.__jblAuditHaptics || []);
      assert(captureHaptics.includes('notification:success'), `${viewport.name}: camera capture has no success haptic`);
      await page.locator('#jbl-camera-close').click();
      const capturedActions = await page.locator('#jbl-visit-photo-media-previews .jbl-media-preview-open, #jbl-visit-photo-media-previews .jbl-media-remove').evaluateAll(nodes => nodes.map(node => {
        const box = node.getBoundingClientRect();
        const icon = node.querySelector('svg')?.getBoundingClientRect();
        return { width: Math.round(box.width), height: Math.round(box.height), iconWidth: Math.round(icon?.width || 0) };
      }));
      assert(capturedActions.length === 2 && capturedActions.every(item => item.width >= 40 && item.height >= 40 && item.iconWidth >= 20), `${viewport.name}: captured-photo View/Delete controls are too small (${JSON.stringify(capturedActions)})`);
      await page.screenshot({ path: path.join(outputDir, `jbl-captured-photo-${viewport.name}.png`), fullPage: true });
      await page.locator('#jbl-visit-photo-media-previews .jbl-media-preview-open').click();
      await page.locator('#media-viewer-overlay.open').waitFor();
      const viewerClose = await page.locator('#media-viewer-close').evaluate(node => {
        const box = node.getBoundingClientRect();
        const icon = node.querySelector('svg')?.getBoundingClientRect();
        return { width: Math.round(box.width), height: Math.round(box.height), iconWidth: Math.round(icon?.width || 0) };
      });
      assert(viewerClose.width >= 40 && viewerClose.height >= 40 && viewerClose.iconWidth >= 20, `${viewport.name}: media viewer Close control is too small (${JSON.stringify(viewerClose)})`);
      await page.locator('#media-viewer-close').click();

      await page.locator('#btn-view-client-media').click();
      await page.locator('.media-link-unavailable').waitFor();
      const unavailable = (await page.locator('.media-link-unavailable').textContent()).trim();
      assert(unavailable === 'No preview', `${viewport.name}: unavailable-preview copy is too long`);
      await page.screenshot({ path: path.join(outputDir, `jbl-client-media-${viewport.name}.png`), fullPage: true });
      assert(pageErrors.length === 0, `${viewport.name}: page errors: ${pageErrors.join('; ')}`);
      await page.close();
    }
  } finally {
    await browser.close();
  }
  process.stdout.write(`Portal JBL Visit visual audit passed. Screenshots: ${outputDir}\n`);
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
