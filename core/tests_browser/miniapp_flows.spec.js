'use strict';

const path = require('node:path');
const fs = require('node:fs');
const { test, expect } = require('playwright/test');

const root = path.resolve(__dirname, '..', '..');
const asset = (name) => path.join(root, 'core', 'static', 'miniapp', name);

async function loadUtilities(page) {
  await page.addScriptTag({ path: asset('utils.js') });
}

test('Complaints and TAT follow Telegram theme independently of the device theme', async ({ page }) => {
  await page.emulateMedia({ colorScheme: 'light' });
  await page.setContent('<input id="nativeControl" type="date"><div id="tatGrid" class="ag-theme-quartz tat-report-grid"></div>');
  await page.addStyleTag({ path: asset('base.css') });
  await page.addStyleTag({ path: asset('complaint_cases.css') });
  await loadUtilities(page);
  await page.evaluate(() => {
    window.__themeEvents = {};
    window.__themeChrome = {};
    window.__themeWebApp = {
      colorScheme: 'dark',
      themeParams: { bg_color: '#101714', secondary_bg_color: '#18231e' },
      onEvent(name, callback) { window.__themeEvents[name] = callback; },
      setHeaderColor(value) { window.__themeChrome.header = value; },
      setBackgroundColor(value) { window.__themeChrome.background = value; },
      setBottomBarColor(value) { window.__themeChrome.bottom = value; },
    };
    window.MiniAppUtils.bindMiniAppTheme(window.__themeWebApp);
  });

  await expect(page.locator('html')).toHaveAttribute('data-miniapp-color-scheme', 'dark');
  expect(await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--raised').trim())).toBe('#202d27');
  expect(await page.locator('#nativeControl').evaluate(node => getComputedStyle(node).colorScheme)).toContain('dark');
  expect(await page.evaluate(() => window.__themeChrome)).toEqual({
    header: '#101714', background: '#101714', bottom: '#18231e',
  });

  await page.emulateMedia({ colorScheme: 'dark' });
  await page.evaluate(() => {
    window.__themeWebApp.colorScheme = 'light';
    window.__themeWebApp.themeParams = { bg_color: '#f3f6f8', bottom_bar_bg_color: '#ffffff' };
    window.__themeEvents.themeChanged();
  });
  await expect(page.locator('html')).toHaveAttribute('data-miniapp-color-scheme', 'light');
  expect(await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--raised').trim())).toBe('#fff');
  expect(await page.locator('#nativeControl').evaluate(node => getComputedStyle(node).colorScheme)).toContain('light');

  await page.addStyleTag({ path: asset('vendor-ag-grid-community-36.1.0.min.css') });
  await page.addStyleTag({ path: asset('vendor-ag-grid-quartz-font-36.1.0.min.css') });
  await page.addStyleTag({ path: asset('vendor-ag-grid-theme-quartz-36.1.0.min.css') });
  await page.addStyleTag({ path: asset('tat_tracker.css') });
  await page.evaluate(() => {
    window.__themeWebApp.colorScheme = 'dark';
    window.__themeWebApp.themeParams = { bg_color: '#0f172a', secondary_bg_color: '#1e293b' };
    window.__themeEvents.themeChanged();
  });
  expect(await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--tat-danger-text').trim())).toBe('#ffaaa3');
  expect(await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--tat-border').trim())).toBe('rgba(255, 255, 255, 0.12)');
  expect(await page.locator('#tatGrid').evaluate(node => getComputedStyle(node).getPropertyValue('--ag-background-color').trim())).toBe('#1e293b');
});

test('Complaint management report contains horizontal grid scrolling and Telegram back navigation', async ({ page }) => {
  const template = fs.readFileSync(path.join(root, 'core', 'templates', 'complaint_cases', 'app.html'), 'utf8')
    .replace(/{% load static %}/g, '')
    .replace(/{% include [^%]+%}/g, '')
    .replace(/{% static '[^']+' %}/g, '')
    .replace(/<script[^>]*>[\s\S]*?<\/script>/g, '')
    .replace(/<link[^>]*>/g, '');
  await page.setViewportSize({ width: 360, height: 780 });
  await page.setContent(template);
  await page.addStyleTag({ path: asset('vendor-ag-grid-community-36.1.0.min.css') });
  await page.addStyleTag({ path: asset('vendor-ag-grid-quartz-font-36.1.0.min.css') });
  await page.addStyleTag({ path: asset('vendor-ag-grid-theme-quartz-36.1.0.min.css') });
  await page.addStyleTag({ path: asset('complaint_cases.css') });
  await page.evaluate(() => {
    document.body.dataset.groupId = '-100-report-test';
    window.__backVisible = false; window.__backHandler = null; window.__reportRequests = []; window.__sharedFiles = [];
    window.__reportDataDelays = []; window.__reportAborted = 0;
    const webApp = {
      initData: 'synthetic-signed-init-data',
      platform: 'android',
      BackButton: {
        onClick(callback) { window.__backHandler = callback; },
        show() { window.__backVisible = true; },
        hide() { window.__backVisible = false; },
      },
      onEvent() {}, disableVerticalSwipes() {},
    };
    window.Telegram = { WebApp: webApp };
    window.MiniAppUtils = { initTelegram: () => webApp, haptic() {}, setCloseProtection() {} };
    window.ComplaintCasesMiniAppApi = {
      async postJson(path) {
        if (path === 'bootstrap/') return { data: {
          actor: { name: 'IT Manager', role: 'IT', capabilities: ['complaint.queue.view', 'complaint.reports.view', 'complaint.case.export'] },
          counts: { pending: 1, resolved: 0, total: 1 }, branches: [], categories: [], category_catalogue: [],
          evidence_limits: { max_files: 10, max_file_size_mb: 10, max_total_upload_mb: 30 },
        } };
        if (path === 'cases/') return { cases: [], pagination: { page: 1, pages: 1, total: 0 }, start_index: 0 };
        return { data: {} };
      },
      async getJson(path, params, _initData, _utils, requestSettings) {
        window.__reportRequests.push({ path, params: Object.assign({}, params || {}) });
        if (path === 'reports/summary/') return {
          total: 1, pending: 1, resolved: 0, needs_details: 0,
          by_branch: [{ label: 'Nakuru', count: 1 }], by_category: [{ label: 'Leakage', count: 1 }],
          by_time: (params?.granularity || 'month') === 'day'
            ? Array.from({ length: 31 }, (_, index) => ({ label: `2026-07-${String(index + 1).padStart(2, '0')}`, count: (index % 4) + 1 }))
            : [{ label: ({ week: '2026-08-31', month: '2026-09', year: '2026' })[params?.granularity || 'month'], count: 1 }],
          time_granularity: params?.granularity || 'month',
          filter_options: { branches: [{ label: 'Nakuru', count: 1 }], categories: [{ label: 'Leakage', count: 1 }] },
        };
        const delay = path === 'reports/data/' ? (window.__reportDataDelays.shift() || 0) : 0;
        if (delay) await new Promise((resolve, reject) => {
          const timer = setTimeout(resolve, delay);
          requestSettings?.signal?.addEventListener('abort', () => {
            clearTimeout(timer); window.__reportAborted += 1;
            reject(new DOMException('The request was cancelled.', 'AbortError'));
          }, { once: true });
        });
        return { results: [{
          complaint_id: 'CMP000001', date_reported: '2026-09-01T10:00:00+03:00', status: 'Pending', needs_details: false,
          customer_name: 'TEST CUSTOMER', customer_id: '12345678', phone_number: '254700000000', reported_by: 'Officer',
          branch_region: 'Nakuru', complaint_category: 'Leakage', complaint_description: 'A sufficiently wide complaint description',
          source: 'complaint_mini_app', gps_link: '', attachments: 0, resolution_details: '', date_resolved: '2026-09-02T14:00:00+03:00', days_open: 1,
        }], count: 1, page: 1, page_size: 50 };
      },
      async postBlob() {
        return {
          blob: new Blob(['synthetic-xlsx'], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }),
          filename: 'Complaint-Cases-Test.xlsx',
        };
      },
    };
    Object.defineProperty(navigator, 'canShare', {
      configurable: true,
      value: payload => Boolean(payload?.files?.length),
    });
    Object.defineProperty(navigator, 'share', {
      configurable: true,
      value: async payload => {
        window.__sharedFiles = payload.files.map(file => ({ name: file.name, type: file.type, size: file.size }));
      },
    });
  });
  await page.addScriptTag({ path: asset('vendor-ag-grid-community-36.1.0.min.js') });
  await page.addScriptTag({ path: asset('vendor-chartjs-4.5.1.umd.min.js') });
  await page.addScriptTag({ path: asset('complaint_cases.js') });
  await page.locator('#globalWorkspaceBtn').click();
  await expect(page.locator('#globalView')).toBeVisible();
  await expect(page.locator('.ag-row')).toHaveCount(1);
  await expect(page.locator('.ag-header-cell-movable')).toHaveCount(0);
  await expect(page.locator('.ag-header-cell-resize:visible')).toHaveCount(0);
  await expect(page.locator('.ag-cell[col-id="date_reported"]')).toHaveText('01-09-26');
  await expect(page.locator('.report-status')).toHaveCSS('background-color', 'rgba(0, 0, 0, 0)');
  await expect.poll(() => page.evaluate(() => document.fonts.check('16px agGridQuartz'))).toBe(true);
  await expect(page.locator('.ag-header-cell[col-id="complaint_id"] .ag-sort-indicator-icon:visible')).toHaveCount(0);
  await expect(page.locator('.ag-header-cell[col-id="date_reported"] .ag-sort-indicator-icon:visible')).toHaveCount(1);
  await page.locator('.ag-header-cell[col-id="date_reported"]').click();
  await expect(page.locator('.ag-header-cell[col-id="date_reported"]')).toHaveAttribute('aria-sort', 'ascending');
  await expect(page.locator('.ag-header-cell[col-id="date_reported"] .ag-sort-indicator-icon:visible .ag-icon-asc')).toHaveCount(1);
  await expect.poll(() => page.evaluate(() => window.Chart.getChart('timeChart')?.data.labels[0])).toBe('01-09-26');
  const monthlyPlotHeight = await page.evaluate(() => window.Chart.getChart('timeChart').chartArea.height);
  await page.locator('.ag-body-horizontal-scroll-viewport').evaluate(node => {
    node.scrollLeft = node.scrollWidth;
    node.dispatchEvent(new Event('scroll'));
  });
  await expect(page.locator('.ag-cell[col-id="date_resolved"]')).toHaveText('02-09-26');

  await page.locator('#reportDateMode').selectOption('month');
  await page.locator('input[name="report_month"]').fill('2026-07');
  await page.locator('input[name="report_month"]').dispatchEvent('change');
  await expect.poll(() => page.evaluate(() => window.__reportRequests.filter(item => item.params.date_from === '2026-07-01').length)).toBe(2);
  const julyRequests = await page.evaluate(() => window.__reportRequests.filter(item => item.params.date_from === '2026-07-01'));
  expect(julyRequests.map(item => item.path).sort()).toEqual(['reports/data/', 'reports/summary/']);
  expect(julyRequests.every(item => item.params.date_to === '2026-07-31')).toBe(true);
  await expect(page.locator('#reportPeriodLabel')).toContainText('July 2026');

  const requestsBeforePie = await page.evaluate(() => window.__reportRequests.length);
  await page.locator('[data-category-chart="pie"]').click();
  await expect(page.locator('[data-category-chart="pie"]')).toHaveAttribute('aria-pressed', 'true');
  expect(await page.evaluate(() => window.__reportRequests.length)).toBe(requestsBeforePie);
  const dataRequestsBeforeGrouping = await page.evaluate(() => window.__reportRequests.filter(item => item.path === 'reports/data/').length);
  await page.locator('#reportGranularity').selectOption('week');
  await expect.poll(() => page.evaluate(() => window.__reportRequests.some(item => item.path === 'reports/summary/' && item.params.granularity === 'week'))).toBe(true);
  await expect.poll(() => page.evaluate(() => window.Chart.getChart('timeChart')?.data.labels[0])).toBe('31-08-26');
  const timeAxis = await page.evaluate(() => {
    const ticks = window.Chart.getChart('timeChart').options.scales.x.ticks;
    return { maxRotation: ticks.maxRotation, minRotation: ticks.minRotation, maxTicksLimit: ticks.maxTicksLimit, fontSize: ticks.font.size };
  });
  expect(timeAxis).toEqual({ maxRotation: 0, minRotation: 0, maxTicksLimit: 4, fontSize: 9 });
  await page.locator('#reportGranularity').selectOption('day');
  await expect.poll(() => page.evaluate(() => window.Chart.getChart('timeChart')?.data.labels.at(-1))).toBe('31-07-26');
  const dailyPlotHeight = await page.evaluate(() => window.Chart.getChart('timeChart').chartArea.height);
  expect(Math.abs(dailyPlotHeight - monthlyPlotHeight)).toBeLessThanOrEqual(2);
  await page.locator('#reportGranularity').selectOption('year');
  await expect.poll(() => page.evaluate(() => window.Chart.getChart('timeChart')?.data.labels[0])).toBe('01-01-26');
  expect(await page.evaluate(() => window.__reportRequests.filter(item => item.path === 'reports/data/').length)).toBe(dataRequestsBeforeGrouping);

  const dataRequestsBeforeRace = await page.evaluate(() => window.__reportRequests.filter(item => item.path === 'reports/data/').length);
  await page.evaluate(() => { window.__reportDataDelays = [250, 10]; });
  await page.locator('select[name="status"]').selectOption('pending');
  await expect.poll(() => page.evaluate(() => window.__reportRequests.filter(item => item.path === 'reports/data/').length)).toBe(dataRequestsBeforeRace + 1);
  await page.locator('select[name="status"]').selectOption('resolved');
  await expect.poll(() => page.evaluate(() => window.__reportRequests.filter(item => item.path === 'reports/data/').length)).toBe(dataRequestsBeforeRace + 2);
  await expect.poll(() => page.evaluate(() => window.__reportAborted)).toBe(1);
  await expect(page.locator('.ag-overlay-loading-center:visible')).toHaveCount(0);
  await expect(page.locator('.ag-row')).toHaveCount(1);

  for (const width of [320, 360, 390]) {
    await page.setViewportSize({ width, height: 780 });
    const overflow = await page.evaluate(() => ({
      document: document.documentElement.scrollWidth - window.innerWidth,
      grid: document.querySelector('.ag-body-horizontal-scroll-viewport').scrollWidth - document.querySelector('.ag-body-horizontal-scroll-viewport').clientWidth,
      backVisible: window.__backVisible,
    }));
    expect(overflow.document).toBeLessThanOrEqual(1);
    expect(overflow.grid).toBeGreaterThan(0);
    expect(overflow.backVisible).toBe(true);
  }
  await page.emulateMedia({ colorScheme: 'light' });
  const lightSurface = await page.locator('#complaintReportGrid').evaluate(node => getComputedStyle(node).getPropertyValue('--ag-background-color'));
  await page.emulateMedia({ colorScheme: 'dark' });
  const darkSurface = await page.locator('#complaintReportGrid').evaluate(node => getComputedStyle(node).getPropertyValue('--ag-background-color'));
  expect(darkSurface).not.toBe(lightSurface);

  await page.locator('#exportAllBtn').click();
  await expect(page.locator('#exportConfirm')).toBeVisible();
  await page.locator('#confirmExportBtn').click();
  await expect.poll(() => page.evaluate(() => window.__sharedFiles.length)).toBe(1);
  expect(await page.evaluate(() => window.__sharedFiles[0])).toMatchObject({
    name: 'Complaint-Cases-Test.xlsx',
    type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  });
  await expect(page.locator('#downloadResultTitle')).toHaveText('Excel file ready');
  await expect(page.locator('#openExportBtn')).toBeVisible();

  await page.evaluate(() => window.__backHandler());
  await expect(page.locator('#queueView')).toBeVisible();
});

test('Complaint camera stops when Telegram deactivates the Mini App', async ({ page }) => {
  const template = fs.readFileSync(path.join(root, 'core', 'templates', 'complaint_cases', 'app.html'), 'utf8')
    .replace(/{% load static %}/g, '')
    .replace(/{% include [^%]+%}/g, '')
    .replace(/{% static '[^']+' %}/g, '')
    .replace(/<script[^>]*>[\s\S]*?<\/script>/g, '')
    .replace(/<link[^>]*>/g, '');
  await page.setContent(template);
  await page.evaluate(() => {
    document.body.dataset.groupId = '-100-camera-test';
    window.__cameraTrackStopped = 0;
    window.__telegramEvents = {};
    Object.defineProperty(HTMLMediaElement.prototype, 'srcObject', {
      configurable: true,
      get() { return this.__syntheticStream || null; },
      set(value) { this.__syntheticStream = value; },
    });
    HTMLMediaElement.prototype.play = async function () {};
    navigator.mediaDevices = {
      async getUserMedia() {
        return { getTracks: () => [{ stop() { window.__cameraTrackStopped += 1; } }] };
      },
    };
    const webApp = {
      initData: 'synthetic-signed-init-data',
      BackButton: { onClick() {}, show() {}, hide() {} },
      onEvent(name, callback) { window.__telegramEvents[name] = callback; },
    };
    window.Telegram = { WebApp: webApp };
    window.MiniAppUtils = {
      initTelegram: () => webApp,
      createRequestId: prefix => `${prefix}-synthetic-request`,
      setCloseProtection() {},
    };
    window.ComplaintCasesMiniAppApi = {
      async postJson(path) {
        if (path === 'bootstrap/') return { data: {
          actor: { name: 'Manager', role: 'MANAGER', capabilities: ['complaint.case.create'] },
          counts: { pending: 0, resolved: 0, total: 0 }, branches: [], categories: [],
          evidence_limits: { max_files: 10, max_file_size_mb: 10, max_total_upload_mb: 30 },
        } };
        if (path === 'cases/') return { cases: [], pagination: { page: 1, pages: 1, total: 0 }, start_index: 0 };
        return { data: {} };
      },
    };
  });
  await page.addScriptTag({ path: asset('complaint_cases.js') });
  await page.locator('#newCaseBtn').click();
  await page.locator('[data-camera-target="create"]').click();
  await expect(page.locator('#cameraOverlay')).toBeVisible();

  const stopped = await page.evaluate(() => {
    window.__telegramEvents.deactivated();
    return window.__cameraTrackStopped;
  });

  expect(stopped).toBe(1);
  await expect(page.locator('#cameraOverlay')).toBeHidden();
});

test('Complaint camera captures multiple photos and the viewer navigates deletes and retakes', async ({ page }) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error.message));
  const template = fs.readFileSync(path.join(root, 'core', 'templates', 'complaint_cases', 'app.html'), 'utf8')
    .replace(/{% load static %}/g, '')
    .replace(/{% include [^%]+%}/g, '')
    .replace(/{% static '[^']+' %}/g, '')
    .replace(/<script[^>]*>[\s\S]*?<\/script>/g, '')
    .replace(/<link[^>]*>/g, '');
  await page.setContent(template);
  await page.addStyleTag({ path: asset('complaint_cases.css') });
  await page.evaluate(() => {
    document.body.dataset.groupId = '-100-camera-gallery-test';
    Object.defineProperty(HTMLMediaElement.prototype, 'srcObject', {
      configurable: true,
      get() { return this.__syntheticStream || null; },
      set(value) { this.__syntheticStream = value; },
    });
    HTMLMediaElement.prototype.play = async function () {};
    const cameraVideo = document.getElementById('cameraVideo');
    Object.defineProperty(cameraVideo, 'videoWidth', { configurable: true, get: () => 1280 });
    Object.defineProperty(cameraVideo, 'videoHeight', { configurable: true, get: () => 960 });
    const cameraCanvas = document.getElementById('cameraCanvas');
    Object.defineProperty(cameraCanvas, 'getContext', {
      configurable: true, value: () => ({ drawImage() {} }),
    });
    Object.defineProperty(cameraCanvas, 'toBlob', {
      configurable: true,
      value: callback => callback(new Blob(['synthetic-photo'], { type: 'image/jpeg' })),
    });
    navigator.mediaDevices = {
      async getUserMedia() { return { getTracks: () => [{ stop() {} }] }; },
    };
    Object.defineProperty(navigator, 'geolocation', {
      configurable: true,
      value: { getCurrentPosition(success) { success({ coords: { latitude: -1.2612164, longitude: 36.8423884 } }); } },
    });
    const webApp = {
      initData: 'synthetic-signed-init-data',
      BackButton: { onClick() {}, show() {}, hide() {} },
      onEvent() {},
    };
    window.Telegram = { WebApp: webApp };
    window.__requestSequence = 0;
    window.MiniAppUtils = {
      initTelegram: () => webApp,
      createRequestId: prefix => `${prefix}-synthetic-${++window.__requestSequence}`,
      setCloseProtection() {},
    };
    window.SecureMediaViewer = {
      renderBlob(container, blob, options) {
        const image = document.createElement('img');
        image.className = 'media-viewer-image'; image.alt = options?.name || ''; container.replaceChildren(image);
        return URL.createObjectURL(blob);
      },
      revoke(url) { if (url) URL.revokeObjectURL(url); },
    };
    window.ComplaintCasesMiniAppApi = {
      async postJson(path) {
        if (path === 'bootstrap/') return { data: {
          actor: { name: 'Officer', role: 'OFFICER', capabilities: ['complaint.case.create'] },
          counts: { pending: 0, resolved: 0, total: 0 }, branches: [], categories: [],
          evidence_limits: { max_files: 10, max_file_size_mb: 10, max_total_upload_mb: 30 },
        } };
        if (path === 'cases/') return { cases: [], pagination: { page: 1, pages: 1, total: 0 }, start_index: 0 };
        return { data: {} };
      },
    };
  });
  await page.addScriptTag({ path: asset('complaint_cases.js') });

  await page.locator('#newCaseBtn').click();
  for (const width of [320, 360, 390]) {
    await page.setViewportSize({ width, height: 780 });
    const attachmentActions = await page.locator('.create-evidence-picker').evaluate(picker => {
      const bounds = picker.getBoundingClientRect();
      const buttons = Array.from(picker.querySelectorAll('.evidence-actions button')).map(button => {
        const box = button.getBoundingClientRect();
        return { left: box.left, right: box.right, top: box.top, width: box.width, scrollWidth: button.scrollWidth };
      });
      return { left: bounds.left, right: bounds.right, scrollWidth: picker.scrollWidth, clientWidth: picker.clientWidth, buttons };
    });
    expect(attachmentActions.buttons).toHaveLength(2);
    expect(Math.abs(attachmentActions.buttons[0].width - attachmentActions.buttons[1].width)).toBeLessThanOrEqual(1);
    expect(Math.abs(attachmentActions.buttons[0].top - attachmentActions.buttons[1].top)).toBeLessThanOrEqual(1);
    expect(attachmentActions.buttons.every(button => button.left >= attachmentActions.left && button.right <= attachmentActions.right + 1)).toBe(true);
    expect(attachmentActions.scrollWidth).toBeLessThanOrEqual(attachmentActions.clientWidth);
  }
  await page.locator('#captureLocationBtn').click();
  await expect(page.locator('#captureLocationBtn')).toContainText('Location Captured');
  await expect(page.locator('#captureLocationBtn')).toHaveClass(/location-success/);
  await expect(page.locator('#captureState')).toHaveText('GPS: -1.261216, 36.842388');
  await expect(page.locator('#captureState')).toHaveClass(/location-coordinate/);
  await page.locator('[data-camera-target="create"]').click();
  expect(await page.locator('#cameraVideo').evaluate(video => [video.videoWidth, video.videoHeight])).toEqual([1280, 960]);
  await page.locator('#cameraCaptureBtn').click();
  await page.waitForTimeout(100);
  expect(pageErrors).toEqual([]);
  await expect(page.locator('#toast')).toContainText('Photo added');
  await expect(page.locator('#createSelectedEvidence li')).toHaveCount(1);
  await page.locator('#cameraCaptureBtn').click();
  await expect(page.locator('#createSelectedEvidence li')).toHaveCount(2);
  expect(pageErrors).toEqual([]);
  await expect(page.locator('#cameraOverlay')).toBeVisible();
  await expect(page.locator('#cameraCaptureState')).toContainText('2 photos added this session');
  await page.locator('#cameraCancelBtn').click();
  await expect(page.locator('#createSelectedEvidence li')).toHaveCount(2);

  await page.locator('#createSelectedEvidence .view-file').first().click();
  await expect(page.locator('#mediaViewerOverlay')).toBeVisible();
  await expect(page.locator('#mediaViewerSub')).toContainText('1 of 2');
  const viewerHeader = await page.evaluate(() => {
    const subtitle = document.getElementById('mediaViewerSub');
    const close = document.getElementById('mediaViewerClose');
    subtitle.textContent = `${'very-long-evidence-file-name-'.repeat(20)}.jpg`;
    const closeBox = close.getBoundingClientRect();
    return {
      closeWidth: closeBox.width,
      closeRight: closeBox.right,
      viewportWidth: window.innerWidth,
      filenameClipped: subtitle.scrollWidth > subtitle.clientWidth,
    };
  });
  expect(viewerHeader.closeWidth).toBe(40);
  expect(viewerHeader.closeRight).toBeLessThanOrEqual(viewerHeader.viewportWidth);
  expect(viewerHeader.filenameClipped).toBe(true);

  const dispatchViewerPointers = sequence => page.evaluate(events => {
    const target = document.getElementById('mediaViewerContent');
    events.forEach(item => target.dispatchEvent(new PointerEvent(item.type, {
      bubbles: true, cancelable: true, pointerId: item.id, pointerType: 'touch',
      clientX: item.x, clientY: item.y, buttons: item.type === 'pointerup' ? 0 : 1,
    })));
  }, sequence);
  await dispatchViewerPointers([
    { type: 'pointerdown', id: 1, x: 320, y: 300 },
    { type: 'pointermove', id: 1, x: 90, y: 305 },
    { type: 'pointerup', id: 1, x: 90, y: 305 },
  ]);
  await expect(page.locator('#mediaViewerSub')).toContainText('2 of 2');
  await dispatchViewerPointers([
    { type: 'pointerdown', id: 2, x: 80, y: 300 },
    { type: 'pointermove', id: 2, x: 310, y: 295 },
    { type: 'pointerup', id: 2, x: 310, y: 295 },
  ]);
  await expect(page.locator('#mediaViewerSub')).toContainText('1 of 2');

  await dispatchViewerPointers([
    { type: 'pointerdown', id: 3, x: 100, y: 300 },
    { type: 'pointerdown', id: 4, x: 200, y: 300 },
    { type: 'pointermove', id: 4, x: 300, y: 300 },
    { type: 'pointerup', id: 4, x: 300, y: 300 },
    { type: 'pointerup', id: 3, x: 100, y: 300 },
  ]);
  await expect(page.locator('#mediaViewerContent')).toHaveAttribute('data-zoom', '200');
  await expect.poll(() => page.locator('#mediaViewerContent .media-viewer-image').evaluate(image => image.style.width)).toBe('200%');
  await dispatchViewerPointers([
    { type: 'pointerdown', id: 5, x: 50, y: 300 },
    { type: 'pointerdown', id: 6, x: 250, y: 300 },
    { type: 'pointermove', id: 6, x: 100, y: 300 },
    { type: 'pointerup', id: 6, x: 100, y: 300 },
    { type: 'pointerup', id: 5, x: 50, y: 300 },
  ]);
  await expect(page.locator('#mediaViewerContent')).toHaveAttribute('data-zoom', '50');
  await page.locator('#mediaViewerNext').click();
  await expect(page.locator('#mediaViewerSub')).toContainText('2 of 2');
  await expect(page.locator('#mediaViewerContent')).toHaveAttribute('data-zoom', '100');
  await page.locator('#mediaViewerDelete').click();
  await expect(page.locator('#createSelectedEvidence li')).toHaveCount(1);
  await expect(page.locator('#mediaViewerSub')).toContainText('1 of 1');

  await page.locator('#mediaViewerRetake').click();
  await expect(page.locator('#cameraOverlay')).toBeVisible();
  await expect(page.locator('#cameraTitle')).toHaveText('Retake Photo');
  await expect(page.locator('#createSelectedEvidence li')).toHaveCount(1);
  await page.locator('#cameraCaptureBtn').click();
  await expect(page.locator('#cameraOverlay')).toBeHidden();
  await expect(page.locator('#mediaViewerOverlay')).toBeVisible();
  await expect(page.locator('#createSelectedEvidence li')).toHaveCount(1);
  await expect(page.locator('#mediaViewerSub')).toContainText('1 of 1');
});

test('Mini App bootstrap initializes Telegram once', async ({ page }) => {
  await page.setContent('<main id="app">Ready</main>');
  await page.evaluate(() => {
    window.__telegramCalls = { ready: 0, expand: 0, swipes: 0 };
    window.Telegram = { WebApp: {
      initData: 'synthetic-signed-init-data',
      ready() { window.__telegramCalls.ready += 1; },
      expand() { window.__telegramCalls.expand += 1; },
      disableVerticalSwipes() { window.__telegramCalls.swipes += 1; },
      disableClosingConfirmation() {},
    } };
  });
  await loadUtilities(page);
  await page.addScriptTag({ path: asset('telegram.js') });
  const result = await page.evaluate(() => {
    window.MiniAppTelegram.init();
    window.MiniAppTelegram.init();
    return window.__telegramCalls;
  });
  expect(result).toEqual({ ready: 1, expand: 1, swipes: 1 });
});

test('authentication failure renders reviewed Portal guidance', async ({ page }) => {
  await page.route('http://miniapp.test/**', route => route.fulfill({
    contentType: 'text/html',
    body: `<!doctype html><style>
      #sidebar { position: fixed; z-index: 2; width: 240px; height: 100%; transform: translateX(-100%); }
      #sidebar.open { transform: translateX(0); }
      #sidebar-backdrop { display: none; position: fixed; inset: 0; z-index: 1; }
      #sidebar-backdrop.open { display: block; }
    </style><body>
      <nav id="sidebar"><a class="shell-nav-link" data-screen="dashboard" href="/portal/s/dashboard/">Dashboard</a></nav>
      <button id="shell-menu-button" aria-expanded="false">Menu</button><div id="sidebar-backdrop"></div>
      <main id="content"><section id="portal-screen" data-top-level="true"></section></main>
    </body>`,
  }));
  await page.addInitScript(() => {
    window.Telegram = { WebApp: {
      ready() {}, expand() {}, disableVerticalSwipes() {}, disableClosingConfirmation() {},
      themeParams: {}, onEvent() {},
      BackButton: { onClick() {}, offClick() {}, show() {}, hide() {} },
      MainButton: { onClick() {}, offClick() {}, show() {}, hide() {}, setText() {} },
    } };
    window.PortalAppShell = { activate() {} };
  });
  await page.goto('http://miniapp.test/portal/s/dashboard/');
  await loadUtilities(page);
  await page.addScriptTag({ path: asset('miniapp-nav.js') });
  await page.evaluate(() => {
    const target = document.getElementById('portal-screen');
    document.body.dispatchEvent(new CustomEvent('htmx:responseError', {
      bubbles: true,
      detail: { target, xhr: { status: 403 } },
    }));
  });
  await expect(page.getByRole('alert')).toContainText(
    'Your Telegram account is not authorized for this Portal screen.',
  );
});

test('double-submit protection shares one browser request', async ({ page }) => {
  await page.setContent('<button id="submit">Submit</button>');
  await loadUtilities(page);
  const result = await page.evaluate(async () => {
    let calls = 0;
    let release;
    const operation = () => {
      calls += 1;
      return new Promise(resolve => { release = resolve; });
    };
    const first = window.MiniAppUtils.singleFlight('same-action-12345678', operation);
    const second = window.MiniAppUtils.singleFlight('same-action-12345678', operation);
    await Promise.resolve();
    const samePromise = first === second;
    release({ ok: true });
    await Promise.all([first, second]);
    return { calls, samePromise };
  });
  expect(result).toEqual({ calls: 1, samePromise: true });
});

test('mobile navigation closes its drawer and Telegram Back stays inside Portal', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.route('http://miniapp.test/**', route => route.fulfill({
    contentType: 'text/html',
    body: `<!doctype html><style>
      #sidebar { position: fixed; z-index: 2; width: 240px; height: 100%; transform: translateX(-100%); }
      #sidebar.open { transform: translateX(0); }
      #sidebar-backdrop { display: none; position: fixed; inset: 0; z-index: 1; }
      #sidebar-backdrop.open { display: block; }
    </style><body>
      <button id="shell-menu-button" aria-expanded="false">Menu</button>
      <aside id="sidebar"><a class="shell-nav-link" data-screen="all" href="http://miniapp.test/portal/s/all/">All cases</a></aside>
      <div id="sidebar-backdrop"></div><main id="content"><section id="portal-screen"></section></main>
    </body>`,
  }));
  await page.addInitScript(() => {
    window.__htmxCalls = [];
    window.Telegram = { WebApp: {
      ready() {}, expand() {}, disableVerticalSwipes() {}, disableClosingConfirmation() {},
      themeParams: {}, onEvent() {},
      BackButton: {
        onClick(callback) { window.__backHandler = callback; }, offClick() {}, show() {}, hide() {},
      },
      MainButton: { onClick() {}, offClick() {}, show() {}, hide() {}, setText() {} },
    } };
    window.PortalAppShell = { activate() {} };
    window.htmx = { ajax(method, url, options) { window.__htmxCalls.push({ method, url, options }); } };
  });
  await page.goto('http://miniapp.test/portal/cases/synthetic-case/');
  await loadUtilities(page);
  await page.addScriptTag({ path: asset('miniapp-nav.js') });
  await page.locator('#shell-menu-button').click();
  await expect(page.locator('#sidebar')).toHaveClass(/open/);
  await page.mouse.click(370, 420);
  await expect(page.locator('#sidebar')).not.toHaveClass(/open/);
  await page.waitForFunction(() => typeof window.__backHandler === 'function');
  const calls = await page.evaluate(() => {
    window.__backHandler();
    return window.__htmxCalls;
  });
  expect(calls).toHaveLength(1);
  expect(calls[0].url).toBe('http://miniapp.test/portal/s/all/');
  expect(calls[0].options.pushURL).toBe(true);
});

test('multipart upload failure can retry with the same request key', async ({ page }) => {
  await page.setContent('<main>Upload</main>');
  await page.evaluate(() => {
    window.__requests = [];
    window.__attempt = 0;
    window.fetch = async (url, options) => {
      window.__requests.push({
        url,
        requestId: options.headers['X-Request-ID'],
        idempotencyKey: options.headers['Idempotency-Key'],
      });
      window.__attempt += 1;
      if (window.__attempt === 1) throw new TypeError('synthetic network failure');
      return new Response(JSON.stringify({ ok: true }), {
        status: 200, headers: { 'Content-Type': 'application/json' },
      });
    };
  });
  await loadUtilities(page);
  await page.addScriptTag({ path: asset('order_approval_api.js') });
  const result = await page.evaluate(async () => {
    const form = new FormData();
    form.set('group_id', '-100-synthetic');
    try { await window.OrderApprovalMiniAppApi.postForm('/api/order-approval/webapp/submit/', form); } catch (_) {}
    const response = await window.OrderApprovalMiniAppApi.postForm('/api/order-approval/webapp/submit/', form);
    return { response, key: form.get('client_request_id'), requests: window.__requests };
  });
  expect(result.response.ok).toBe(true);
  expect(result.requests).toHaveLength(2);
  expect(result.requests[0].requestId).toBe(result.key);
  expect(result.requests[1].requestId).toBe(result.key);
  expect(result.requests[1].idempotencyKey).toBe(result.key);
});

function signingHtml() {
  return `<!doctype html><body>
    <main class="sign-shell" data-session-url="/api/origination/sign/api/session/">
      <div id="sign-status"></div><section id="sign-content" hidden>
        <strong id="sign-reference"></strong><strong id="sign-role"></strong><strong id="sign-phone"></strong>
        <div id="signing-mode-banner"></div><span id="signing-mode-label"></span><span id="signing-mode-detail"></span>
        <div id="shared-phone-warning" hidden></div><div id="document-list"></div>
        <span id="packet-consent-text"></span><div id="preview-loading"></div><img id="packet-page" hidden>
        <span id="page-label"></span><button id="page-prev"></button><button id="page-next"></button>
        <canvas id="signature-pad" width="800" height="260"></canvas><button id="signature-clear"></button>
        <button id="mode-drawn" class="active"></button><button id="mode-typed"></button>
        <div id="draw-panel"></div><label id="type-panel" hidden><input id="typed-name"></label>
        <label><input id="packet-consent" type="checkbox"></label>
        <label id="assisted-confirmation" hidden><input id="assisted-consent" type="checkbox"></label>
        <button id="save-signature">Save signature</button><button id="send-otp" disabled>Send code</button>
        <div id="otp-panel" hidden><input id="otp-code"><span id="otp-detail"></span>
          <button id="verify-otp">Verify</button></div>
      </section>
    </main>
  </body>`;
}

test('Origination signing completes its happy path with test-mode services', async ({ page }) => {
  let session = {
    test_mode: true,
    reference: 'SYNTHETIC-LAF-001', signer_role: 'borrower', phone_masked: '+254 *** 001',
    shared_phone_override: false, access_mode: 'remote', documents: [{ key: 'laf', name: 'Loan form', page_count: 1 }],
    reviewed_pages: [], consented: false, status: 'pending', otp: {}, packet_version: 'test-v1',
  };
  await page.route('http://miniapp.test/**', async route => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith('/packet/')) {
      return route.fulfill({
        status: 200, body: 'synthetic-image', contentType: 'image/png',
        headers: { 'X-Preview-Page-Count': '1', 'X-Signing-Packet-Version': 'test-v1' },
      });
    }
    if (url.pathname.endsWith('/consent/')) session = { ...session, consented: true, reviewed_pages: [1] };
    if (url.pathname.endsWith('/otp/')) session = { ...session, otp: { expires_at: '2026-08-31T22:00:00Z' } };
    if (url.pathname.endsWith('/verify/')) {
      session = { ...session, status: 'verified', completion_text: 'Synthetic signing complete.' };
    }
    return route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ ok: true, session }),
    });
  });
  await page.route('http://miniapp.test/sign', route => route.fulfill({
    status: 200, contentType: 'text/html', body: signingHtml(),
  }));
  await page.goto('http://miniapp.test/sign#synthetic-test-token');
  await loadUtilities(page);
  await page.addScriptTag({ path: asset('origination_signing.js') });
  await expect(page.locator('#sign-content')).toBeVisible();
  await expect(page.locator('#page-label')).toHaveText('1 / 1');
  await page.locator('#mode-typed').click();
  await page.locator('#typed-name').fill('Synthetic Borrower');
  await page.locator('#packet-consent').check();
  await page.locator('#save-signature').click();
  await expect(page.locator('#sign-status')).toContainText('signature is ready');
  await page.locator('#send-otp').click();
  await expect(page.locator('#otp-panel')).toBeVisible();
  await page.locator('#otp-code').fill('123456');
  await page.locator('#verify-otp').click();
  await expect(page.locator('#sign-status')).toHaveText('Synthetic signing complete.');
});
