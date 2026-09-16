'use strict';
const path = require('node:path');
const { test, expect } = require('playwright/test');
const asset = name => path.resolve(__dirname, '../static/miniapp', name);
const queueIds = { jbl: 'jbl-list', credit: 'credit-list', final: 'final-list', requisition: 'req-list', deferred: 'deferred-list', my_visits: 'my-visits-list', all: 'all-list' };

async function boot(page, queue, serverCards = false, capabilities = null) {
  await page.setViewportSize({ width: 390, height: 740 });
  await page.route('http://miniapp.test/**', route => {
    const url = new URL(route.request().url());
    if (url.pathname.startsWith('/portal/cases/')) {
      return route.fulfill({ contentType: 'text/html', body: `<div id="portal-screen" data-screen="case_history" data-case-farmer-id="case-1" data-top-level="false"><section id="page-case_history"><a class="case-history-back" href="/portal/s/${queue}/" data-return-screen="${queue}" aria-label="Back"><span class="sr-only">Back</span></a><div id="case-history-selected"><div id="case-history-content"></div></div></section></div>` });
    }
    return route.fulfill({ contentType: 'text/html', body: '<!doctype html><title>Portal queue</title>' });
  });
  await page.goto(`http://miniapp.test/portal/s/${queue}/`);
  await page.setContent(`<main id="content" style="height:600px;overflow:auto"><div id="portal-screen" data-screen="${queue}" data-top-level="true"><section id="page-${queue}" class="page active">
    <input data-portal-queue-search value=""><div id="requisition-batch-panel"><span id="batch-selected-count"></span><input type="date" id="batch-req-date"><button id="btn-generate-requisition">Prepare selected batch</button><button id="batch-clear-selection">Clear selection</button></div>
    <div style="height:450px"></div><div id="${queueIds[queue]}"></div><div style="height:700px"></div></section></div>
    <div class="sheet-overlay" id="sheet-overlay"><div id="sheet-navigation"><button id="sheet-back"><span></span></button></div><div id="sheet-avatar"></div><div id="sheet-header-state"></div><div id="sheet-header-status"></div><button id="sheet-close" class="sheet-close-button"></button><h2 id="sheet-name"></h2><p id="sheet-sub"></p><ul id="sheet-info"></ul><div class="sheet-quick-actions"><section id="sheet-client-media"></section><a id="case360-toggle"></a></div><div id="sheet-gate-warning"></div><div id="sheet-form"></div><div id="sheet-footer"></div></div>
    <div class="sheet-overlay" id="media-viewer-overlay"><button class="sheet-close-button" id="media-viewer-close">Close media</button></div></main><div id="toast"></div>`);
  await page.addStyleTag({ content: '.sheet-overlay{display:none}.sheet-overlay.open{display:block}.farmer-card{padding:12px;border:1px solid #ddd;cursor:pointer}.sheet-close-button{width:28px;height:28px}' });
  for (const name of ['utils.js', 'components.js', 'portal_helpers.js', 'portal_queues.js', 'portal_filters.js', 'portal_case_navigation.js', 'portal_farmer_sheet.js', 'portal_requisitions.js']) await page.addScriptTag({ path: asset(name) });
  await page.evaluate(({ serverCards, capabilities }) => {
    window.__writes = [];
    window.__revision = 7;
    window.__backHandler = null;
    window.Telegram = { WebApp: { ready() {}, expand() {}, onEvent() {}, BackButton: {
      onClick(fn) { window.__backHandler = fn; }, offClick() {}, show() {}, hide() {},
    } } };
    const originalInit = window.PortalMiniAppRequisitions.init;
    window.PortalMiniAppRequisitions.init = deps => { window.__state = deps.state; originalInit(deps); };
    const farmer = () => ({ id: 'case-1', customer_name: 'Synthetic farmer', workflow_revision: window.__revision, final_decision: 'Approved', deferred_stage: 'credit', deferred_at: '2026-09-01', deferred_until: '2026-12-01', credit_decision: 'Deferred / On Hold', location_label: '-', jbl_visit_status: 'Visited' });
    window.PortalMiniAppApi = {
      initDataHeader: () => ({}),
      apiFetch: async url => {
        if (url === '/meta/') return { ok: true, data: { ok: true, capabilities: capabilities || ['portal.case.read', 'portal.requisition.write', 'portal.requisition.finalize', 'portal.requisition.view', 'portal.jbl_queue.view', 'portal.jbl_followup.view', 'portal.credit_queue.view', 'portal.final_review.view', 'portal.deferred.view', 'portal.jbl_visit.write', 'portal.credit.write', 'portal.final_review.write'], access_policy_version: 1 } };
        if (url === '/settings/') return { ok: true, data: { ok: true, data: {} } };
        if (url.startsWith('/farmers/case-1/')) return { ok: true, data: { ok: true, farmer: farmer(), case360: { identity: { customer_name: 'Synthetic farmer' }, intake: {}, stages: {}, timeline: [], documents: {} } } };
        return { ok: true, data: { ok: true, farmers: [farmer()], pagination: { page: 1, pages: 1 } } };
      },
      fetchHtml: async url => {
        const key = url.match(/\/queues\/(\w+)\//)[1];
        return `<div class="farmer-card htmx-farmer-card" data-farmer-id="case-1" data-qkey="${key}">${key === 'requisition' ? `<input type="checkbox" class="farmer-card-checkbox" data-id="case-1" data-revision="${window.__revision}">` : ''}Synthetic farmer</div>`;
      },
      postJson: async (url, payload) => { window.__writes.push({ url, payload }); return { ok: false, data: { ok: false, error: 'This case changed. Review it before preparing the order.' } }; },
    };
    if (serverCards) window.htmx = { config: {} };
  }, { serverCards, capabilities });
  await page.addScriptTag({ path: asset('portal.js') });
  await page.addScriptTag({ path: asset('miniapp-nav.js') });
  await expect(page.locator('.farmer-card')).toHaveCount(1);
}

test('Case History uses one compact mobile back control', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 568 });
  await page.setContent(`<body class="workflow-standard portal-app"><main id="content"><div id="portal-screen" data-screen="case_history"><section id="page-case_history" class="page active"><header class="case-history-page-header"><a class="case-history-back" href="/portal/s/jbl/" aria-label="Back to JBL Visit"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m12 19-7-7 7-7"></path><path d="M19 12H5"></path></svg><span class="sr-only">Back to JBL Visit</span></a><div><h1>Complete Case History</h1><p class="meta">Full customer record, workflow timeline, TAT, documents, and data quality</p></div></header></section></div></main></body>`);
  for (const name of ['base.css', 'workflow_standard.css', 'portal.css']) await page.addStyleTag({ path: asset(name) });
  const back = page.locator('.case-history-back');
  await expect(back).toHaveCount(1);
  await expect(page.locator('.case-history-action')).toHaveCount(0);
  const box = await back.boundingBox();
  expect(box.width).toBe(44);
  expect(box.height).toBe(44);
  expect(await back.evaluate(node => getComputedStyle(node).borderTopWidth)).toBe('0px');
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(320);
});

for (const serverCards of [false, true]) {
  const rendering = serverCards ? 'server fragments' : 'client cards';
  test(`Portal ${rendering}: selection and captured revisions survive history and all Back controls`, async ({ page }, testInfo) => {
    await boot(page, 'requisition', serverCards);
    await page.locator('.farmer-card-checkbox').check();
    await expect(page).toHaveURL(/\/s\/requisition\/$/);
    await page.locator('#batch-req-date').fill('2026-09-14');
    await page.locator('[data-portal-queue-search]').fill('Ephemeral search');
    await page.evaluate(() => {
      window.__state.searches.requisition = 'Ephemeral search';
      window.__state.pages.requisition = 3;
      window.__state.filtersByQueue.requisition = { county: 'Kiambu', ordering: 'newest' };
      document.getElementById('content').scrollTop = 300;
    });
    await page.locator('.farmer-card').click({ position: { x: 140, y: 10 } });
    await expect(page).toHaveURL(/\/cases\/case-1\/\?from=requisition$/);
    await expect(page.locator('#portal-screen')).toHaveAttribute('data-screen', 'case_history');
    await page.evaluate(() => { window.__revision = 8; });
    await page.locator('.case-history-back').click();
    await expect(page.locator('.farmer-card-checkbox')).toBeChecked();
    await expect(page.locator('#batch-req-date')).toHaveValue('2026-09-14');
    await expect(page.locator('[data-portal-queue-search]')).toHaveValue('Ephemeral search');
    await expect.poll(() => page.evaluate(() => window.__state.selectedRequisitionRevisions.get('case-1'))).toBe(7);
    await expect.poll(() => page.evaluate(() => document.getElementById('content').scrollTop)).toBe(300);
    expect(await page.evaluate(() => window.__state.filtersByQueue.requisition.ordering)).toBe('newest');
    // Forward reopens history; Telegram Back uses the same source entry.
    await page.goForward();
    await expect(page.locator('#portal-screen')).toHaveAttribute('data-screen', 'case_history');
    await page.evaluate(() => window.__backHandler());
    await expect(page.locator('.farmer-card-checkbox')).toBeChecked();
    await page.locator('#btn-generate-requisition').click();
    await expect(page.locator('#toast')).toContainText('This case changed');
    expect(await page.evaluate(() => window.__writes[0].payload.workflow_revisions)).toEqual({ 'case-1': 7 });
    expect(await page.evaluate(() => window.__state.selectedRequisitions.size)).toBe(1);
    await page.screenshot({ path: testInfo.outputPath('order-selection-restored.png'), fullPage: true });
    await page.locator('.farmer-card').click({ position: { x: 140, y: 10 } });
    await expect(page).toHaveURL(/\/cases\/case-1/);
    await page.goBack();
    await expect(page.locator('.farmer-card-checkbox')).toBeChecked();
    expect(await page.evaluate(() => Object.values(sessionStorage).join(' ') + Object.values(localStorage).join(' '))).not.toContain('Ephemeral search');
  });

  for (const [queue, button] of [['jbl', '#btn-submit-jbl'], ['credit', '#btn-submit-credit'], ['final', '#btn-submit-final']]) {
    test(`Portal ${rendering}: ${queue} card exposes its original action immediately`, async ({ page }) => {
      await boot(page, queue, serverCards);
      await page.locator('.farmer-card').click();
      await expect(page.locator(button)).toBeVisible();
      await expect(page).toHaveURL(new RegExp('/s/' + queue + '/$'));
      expect(await page.evaluate(() => window.__writes.length)).toBe(0);
    });
  }
  for (const queue of ['all', 'my_visits']) {
    test(`Portal ${rendering}: ${queue} card opens complete history without a work action`, async ({ page }) => {
      await boot(page, queue, serverCards);
      await page.locator('.farmer-card').click();
      await expect(page).toHaveURL(new RegExp('/cases/case-1/\\?from=' + queue + '$'));
      await expect(page.locator('#portal-screen')).toHaveAttribute('data-screen', 'case_history');
      expect(await page.evaluate(() => window.__writes.length)).toBe(0);
    });
  }
}

test('Portal case inspection denial leaves original screen and selection intact', async ({ page }) => {
  await boot(page, 'requisition');
  await page.locator('.farmer-card-checkbox').check();
  await page.route('http://miniapp.test/portal/cases/**', route => route.fulfill({ status: 403, body: 'Denied' }));
  await page.locator('.farmer-card').click({ position: { x: 140, y: 10 } });
  await expect(page.locator('#toast')).toContainText('no longer have access');
  await expect(page.locator('.farmer-card-checkbox')).toBeChecked();
  await expect(page).toHaveURL(/\/s\/requisition\/$/);
});

test('Portal deferred review gates the existing stage action and blocks expired cases', async ({ page }) => {
  await boot(page, 'deferred', false, ['portal.deferred.view', 'portal.case.read']);
  await page.locator('.farmer-card').click();
  await expect(page.locator('#sheet-form')).toContainText('Deferred / On Hold');
  await expect(page.locator('#sheet-overlay')).toHaveClass(/operational-detail-sheet/);
  await expect(page.locator('#sheet-navigation')).toBeVisible();
  await expect(page.locator('#sheet-back')).toContainText('Deferred');
  await expect(page.locator('#sheet-header-state')).toHaveText('Paused');
  await expect(page.locator('.deferred-summary')).toBeVisible();
  await expect(page.locator('#sheet-footer button')).toHaveCount(0);
  await page.evaluate(() => {
    window.__state.capabilities.add('portal.credit.write');
    window.PortalMiniAppFarmerSheet.openFarmerSheet({ id: 'case-1', deferred_stage: 'credit', deferred_until: '2026-09-01', reappraisal_required: true }, 'deferred');
  });
  await expect(page.locator('#sheet-form')).toContainText('Reappraisal required');
  await expect(page.locator('#sheet-footer button')).toHaveCount(0);
  await page.evaluate(() => window.PortalMiniAppFarmerSheet.openFarmerSheet({ id: 'case-1', deferred_stage: 'credit', deferred_until: '2026-12-01' }, 'deferred'));
  await page.locator('#sheet-footer button').click();
  await expect(page.locator('#btn-submit-credit')).toBeVisible();
});

test('Portal unfinished visit and local media survive inspection; nested Back closes media first', async ({ page }) => {
  await boot(page, 'jbl');
  await page.evaluate(() => window.__state.capabilities.add('portal.jbl_media.write'));
  await page.locator('.farmer-card').click();
  await page.locator('#jbl-comment').fill('Synthetic unfinished visit notes');
  const image = await page.evaluate(() => {
    const canvas = document.createElement('canvas'); canvas.width = 256; canvas.height = 256;
    const context = canvas.getContext('2d');
    for (let x = 0; x < 256; x += 8) for (let y = 0; y < 256; y += 8) {
      context.fillStyle = `hsl(${(x * 13 + y * 17) % 360} 80% 50%)`;
      context.fillRect(x, y, 8, 8);
    }
    return canvas.toDataURL('image/jpeg').split(',')[1];
  });
  await page.locator('#jbl-visit-photo-media').setInputFiles({ name: 'synthetic.jpg', mimeType: 'image/jpeg', buffer: Buffer.from(image, 'base64') });
  await expect(page.locator('#jbl-visit-photo-media-name')).toContainText('1 selected');
  await page.locator('#case360-toggle').click();
  await expect(page).toHaveURL(/\/cases\/case-1/);
  await expect(page.locator('#sheet-overlay')).not.toHaveClass(/open/);
  await page.evaluate(() => document.getElementById('media-viewer-overlay').classList.add('open'));
  await page.goBack();
  await expect(page).toHaveURL(/\/cases\/case-1/);
  await expect(page.locator('#media-viewer-overlay')).not.toHaveClass(/open/);
  await expect(page.locator('.case-history-back')).toHaveAttribute('aria-label', 'Back to JBL Visit');
  await page.locator('.case-history-back').click();
  await expect(page.locator('#btn-submit-jbl')).toBeVisible();
  await expect(page.locator('#jbl-comment')).toHaveValue('Synthetic unfinished visit notes');
  await expect(page.locator('#jbl-visit-photo-media-name')).toContainText('1 selected');
});

test('Portal case inspection timeout leaves the source usable', async ({ page }) => {
  await boot(page, 'all');
  await page.evaluate(() => {
    const original = window.fetch;
    window.fetch = (url, options) => String(url).includes('/portal/cases/')
      ? new Promise((resolve, reject) => options.signal.addEventListener('abort', () => reject(new DOMException('Timeout', 'AbortError'))))
      : original(url, options);
  });
  await page.clock.install();
  await page.locator('.farmer-card').click();
  await page.clock.runFor(21000);
  await expect(page.locator('#toast')).toContainText('took too long');
  await expect(page.locator('#portal-screen')).toHaveAttribute('data-screen', 'all');
  await expect(page.locator('#portal-screen')).not.toHaveAttribute('aria-busy', 'true');
});

test('Portal order selection recovery is minimal, expiring and signed-launch/policy bound', async ({ page }) => {
  await page.route('http://localhost/**', route => route.fulfill({ contentType: 'text/html', body: '<main id="content"><div id="requisition-batch-panel"><span id="batch-selected-count"></span><input id="batch-req-date" type="date" value="2026-09-14"></div><div id="req-list"></div></main>' }));
  await page.goto('http://localhost/order');
  await page.addScriptTag({ path: asset('portal_requisitions.js') });
  await page.evaluate(async () => {
    window.newSelectionSession = async (launch, version = 1) => {
      window.selectionState = { accessPolicyVersion: version, capabilities: new Set(['portal.requisition.write']), selectedRequisitions: new Set(), selectedRequisitionRevisions: new Map() };
      window.PortalMiniAppRequisitions.init({ state: window.selectionState, tg: { initData: launch }, el: id => document.getElementById(id) });
      await window.PortalMiniAppRequisitions.restoreSelection();
    };
    await window.newSelectionSession('synthetic-signed-launch-A');
    selectionState.selectedRequisitions.add('case-1');
    selectionState.selectedRequisitionRevisions.set('case-1', 7);
    window.PortalMiniAppRequisitions.updateBatchPanel();
  });
  const stored = await page.evaluate(() => Object.values(sessionStorage).join(' '));
  expect(stored).toContain('case-1');
  expect(stored).not.toContain('signed-launch');
  await page.evaluate(async () => { document.getElementById('batch-req-date').value = ''; await newSelectionSession('synthetic-signed-launch-A'); });
  expect(await page.evaluate(() => selectionState.selectedRequisitionRevisions.get('case-1'))).toBe(7);
  await expect(page.locator('#batch-req-date')).toHaveValue('2026-09-14');
  await page.evaluate(() => newSelectionSession('synthetic-signed-launch-B'));
  expect(await page.evaluate(() => selectionState.selectedRequisitions.size)).toBe(0);
  await page.evaluate(() => newSelectionSession('synthetic-signed-launch-A', 2));
  expect(await page.evaluate(() => selectionState.selectedRequisitions.size)).toBe(0);
  await page.evaluate(async () => {
    await newSelectionSession('synthetic-signed-launch-A', 2);
    selectionState.selectedRequisitions.add('case-1');
    selectionState.selectedRequisitionRevisions.set('case-1', 7);
    PortalMiniAppRequisitions.updateBatchPanel();
    const key = Object.keys(sessionStorage)[0];
    const old = JSON.parse(sessionStorage.getItem(key));
    old.savedAt = Date.now() - 31 * 60 * 1000;
    sessionStorage.setItem(key, JSON.stringify(old));
    await newSelectionSession('synthetic-signed-launch-A', 2);
  });
  expect(await page.evaluate(() => selectionState.selectedRequisitions.size)).toBe(0);
});

test('Portal changed-case preview names the change without advancing the selection revision', async ({ page }) => {
  await boot(page, 'requisition');
  await page.locator('.farmer-card-checkbox').check();
  await page.locator('#batch-req-date').fill('2026-09-14');
  await page.evaluate(() => {
    document.getElementById('content').insertAdjacentHTML('beforeend', `<div id="requisition-preview-overlay" class="sheet-overlay"><p id="requisition-preview-sub"></p><div id="requisition-preview-summary"></div><div id="requisition-preview-warnings"></div><div id="requisition-preview-list"></div><div id="requisition-preview-progress"><span></span><span></span></div><p id="requisition-finalize-note"></p><button id="requisition-preview-cancel"></button><button id="requisition-preview-confirm"></button></div>`);
    PortalMiniAppApi.postJson = async () => ({ ok: true, data: { ok: true,
      workflow_revisions: { 'case-1': 8 }, preview_token: 'synthetic-preview', order_number: '1',
      requisition_date: '2026-09-14', ready_count: 1, blocked_count: 0,
      ready: [{ farmer: { id: 'case-1', customer_name: 'Synthetic updated farmer' } }], blocked: [], warnings: [],
    } });
  });
  await page.locator('#btn-generate-requisition').click();
  await expect(page.locator('#requisition-preview-warnings')).toContainText('Changed since selection: Synthetic updated farmer');
  expect(await page.evaluate(() => window.__state.selectedRequisitionRevisions.get('case-1'))).toBe(7);
  expect(await page.evaluate(() => window.__state.pendingRequisitionPayload.workflow_revisions['case-1'])).toBe(8);
});

test('Portal inspection preserves edits but remains blocked during a write', async ({ page }) => {
  await boot(page, 'all');
  await page.evaluate(() => MiniAppUtils.setCloseProtection('network-write:synthetic', true));
  await page.locator('.farmer-card').click();
  await expect(page).toHaveURL(/\/s\/all\/$/);
  await page.evaluate(() => MiniAppUtils.setCloseProtection('network-write:synthetic', false));
  await page.locator('.farmer-card').click();
  await expect(page).toHaveURL(/\/cases\/case-1/);
});

test('Portal a failed repeat inspection preserves the existing Forward entry', async ({ page }) => {
  await boot(page, 'requisition');
  await page.locator('.farmer-card-checkbox').check();
  await page.locator('.farmer-card').click({ position: { x: 140, y: 10 } });
  await expect(page).toHaveURL(/\/cases\/case-1/);
  await page.goBack();
  await expect(page.locator('.farmer-card-checkbox')).toBeChecked();
  await page.route('http://miniapp.test/portal/cases/**', route => route.fulfill({ status: 503, body: 'Unavailable' }));
  await page.locator('.farmer-card').click({ position: { x: 140, y: 10 } });
  await expect(page.locator('#toast')).toContainText('Could not open');
  await page.goForward();
  await expect(page.locator('#portal-screen')).toHaveAttribute('data-screen', 'case_history');
});

test('Portal read-only order viewers cannot select cases', async ({ page }) => {
  await boot(page, 'requisition', false, ['portal.requisition.view', 'portal.case.read']);
  await expect(page.locator('.farmer-card-checkbox')).toHaveCount(0);
  expect(await page.evaluate(() => window.__state.selectedRequisitions.size)).toBe(0);
});

test('Portal explicit selection clearing requires confirmation', async ({ page }) => {
  await boot(page, 'requisition');
  await page.locator('.farmer-card-checkbox').check();
  page.once('dialog', dialog => dialog.dismiss());
  await page.locator('#batch-clear-selection').click();
  await expect(page.locator('.farmer-card-checkbox')).toBeChecked();
  page.once('dialog', dialog => dialog.accept());
  await page.locator('#batch-clear-selection').click();
  await expect(page.locator('.farmer-card-checkbox')).not.toBeChecked();
  expect(await page.evaluate(() => window.__state.selectedRequisitions.size)).toBe(0);
});

test('Portal invalid history markup does not replace the queue', async ({ page }) => {
  await boot(page, 'all');
  await page.route('http://miniapp.test/portal/cases/**', route => route.fulfill({ contentType: 'text/html', body: '<div id="portal-screen" data-screen="all">Invalid history response</div>' }));
  await page.locator('.farmer-card').click();
  await expect(page.locator('#toast')).toContainText('could not start');
  await expect(page.locator('.farmer-card')).toHaveCount(1);
  await expect(page).toHaveURL(/\/s\/all\/$/);
});
