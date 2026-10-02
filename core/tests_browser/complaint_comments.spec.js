'use strict';
const fs = require('node:fs');
const path = require('node:path');
const { test, expect } = require('playwright/test');
const root = path.resolve(__dirname, '../..');
const asset = name => path.join(root, 'core/static/miniapp', name);
const { initData } = require('./fixtures/local_mcp_fixtures.js');

test('HB comments retain resolution drafts, keep cases open, and fit narrow screens', async ({ page }, testInfo) => {
  const errors = []; page.on('pageerror', error => errors.push(error.message));
  const template = fs.readFileSync(path.join(root, 'core/templates/complaint_cases/app.html'), 'utf8')
    .replace('{% include "complaint_cases/lucide_icons.html" %}', fs.readFileSync(path.join(root, 'core/templates/complaint_cases/lucide_icons.html'), 'utf8'))
    .replace(/{#[\s\S]*?#}/g, '')
    .replace("{% static 'miniapp/jawabu-logo.png' %}", `data:image/png;base64,${fs.readFileSync(asset('jawabu-logo.png')).toString('base64')}`)
    .replace(/{% load static %}/g, '').replace(/{% include [^%]+%}/g, '')
    .replace(/{% static '[^']+' %}/g, '').replace(/<script[^>]*>[\s\S]*?<\/script>/g, '').replace(/<link[^>]*>/g, '');
  await page.setViewportSize({ width: 320, height: 800 });
  await page.setContent(template);
  await page.addStyleTag({ path: asset('complaint_cases.css') });
  await page.evaluate(initData => {
    document.body.dataset.groupId = '-100-comment-fixture';
    const item = { case_id: 'synthetic-comment', id: 'synthetic-comment', reference_number: 'CMP-TEST',
      customer_name: 'Training customer', customer_phone: '0700000000', customer_id: '123456',
      description: 'Synthetic burner issue', status: 'OPEN', revision: 1, hb_comment_count: 0,
      category: 'Product issue', branch: 'Training branch', source_attribution: {type:'officer', label:'Recorded by an officer'}, resolution_comments: [], updates: [{note:'Complaint recorded.', updated_by:'Training officer', created_at:'02-Oct-2026 13:30', status:'Open', actor_affiliation:'JBL'}], evidence: [] };
    window.__commentWrites = [];
    const webApp = { initData, BackButton: { onClick() {}, show() {}, hide() {} }, onEvent() {} };
    window.Telegram = { WebApp: webApp };
    window.MiniAppUtils = { initTelegram: () => webApp, setCloseProtection() {}, haptic() {} };
    window.ComplaintCasesMiniAppApi = {
      async postJson(path) {
        if (path === 'bootstrap/') return { data: {
          actor: { name: 'Training HB', role: 'HB_STAFF', capabilities: ['complaint.queue.view', 'complaint.case.close', 'complaint.case.comment'] },
          counts: { pending: 1, resolved: 0, total: 1 }, branches: [], categories: [], category_catalogue: [],
          voice_input: { enabled: true, fields: ['complaint_resolution_comment', 'complaint_resolution_note'] },
        } };
        if (path === 'cases/') return { cases: [{ ...item }], pagination: { page: 1, pages: 1, total: 1 }, start_index: 0 };
        return { case: { ...item } };
      },
      async postForm(path, data) {
        window.__commentWrites.push({ path, text: data.get('comment_text'), revision: data.get('expected_revision') });
        item.revision++; item.hb_comment_count++;
        item.resolution_comments.unshift({ note: data.get('comment_text'), updated_by: 'Training HB', created_at: '02-Oct-2026 14:35', action: 'commented' });
        item.updates.unshift({note:data.get('comment_text'), updated_by:'Training HB', created_at:'02-Oct-2026 14:35', action:'commented', status:'Open', actor_affiliation:'HB'});
        return { ok: true, case: { ...item }, message: 'Comment saved.' };
      },
    };
  }, initData);
  await page.addScriptTag({ path: asset('complaint_cases.js') });
  await page.locator('#caseList .case-row').click();
  await expect(page.locator('#commentForm')).toBeVisible();
  await expect(page.locator('#commentForm h2')).toHaveText('Add Comment');
  await expect(page.locator('#detailSource')).toBeHidden();
  await expect(page.locator('#commentsPanel, #previousResolution')).toHaveCount(0);
  await expect(page.locator('#resolveForm')).toBeHidden();
  await expect(page.locator('[data-voice-field="complaint_resolution_comment"] .voice-input')).toBeVisible();
  await page.locator('#resolveTab').click();
  await page.locator('#complaintResolutionNote').fill('Unfinished resolution draft');
  await page.locator('#commentTab').click();
  await page.locator('#complaintResolutionComment').fill('Technician will visit tomorrow.');
  await page.locator('#commentForm button[type="submit"]').click();
  await expect(page.locator('#activityList')).toContainText('Technician will visit tomorrow.');
  await expect(page.locator('#activityList .history-affiliation')).toHaveText(['HB', 'JBL']);
  await expect(page.locator('#activityList .history-item').filter({hasText:'Technician will visit tomorrow.'})).toHaveCount(1);
  await expect(page.locator('#detailStatus')).toHaveText('OPEN');
  await expect(page.locator('#complaintResolutionComment')).toHaveValue('');
  await page.locator('#resolveTab').click();
  await expect(page.locator('#complaintResolutionNote')).toHaveValue('Unfinished resolution draft');
  await page.locator('#commentTab').click();
  for (const width of [320, 360, 390, 430]) {
    await page.setViewportSize({ width, height: 800 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    const buttons = await page.locator('#hbActionTabs button').evaluateAll(nodes => nodes.map(node => node.getBoundingClientRect().width));
    expect(Math.abs(buttons[0] - buttons[1])).toBeLessThanOrEqual(1);
    await page.screenshot({ path: testInfo.outputPath(`hb-comments-${width}.png`), fullPage: true });
  }
  await page.screenshot({ path: testInfo.outputPath('hb-comments-mobile.png'), fullPage: true });
  await page.evaluate(() => document.documentElement.dataset.miniappColorScheme = 'dark');
  await expect(page.locator('#commentForm')).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('hb-comments-dark.png'), fullPage: true, animations: 'disabled' });
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.screenshot({ path: testInfo.outputPath('hb-comments-desktop.png'), fullPage: true });
  await page.locator('#detailBackBtn').click();
  await expect(page.locator('#caseList .hb-comment-count')).toHaveAttribute('aria-label', '1 HB comments');
  await page.screenshot({ path: testInfo.outputPath('hb-comment-queue.png'), fullPage: true });
  expect(await page.evaluate(() => window.__commentWrites)).toHaveLength(1);
  expect(errors).toEqual([]);
});
