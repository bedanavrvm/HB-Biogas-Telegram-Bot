'use strict';
const fs = require('node:fs');
const path = require('node:path');
const { test, expect } = require('playwright/test');
const { mountPortalShell } = require('./fixtures/portal_shell');
const root = path.resolve(__dirname, '../..');
const template = fs.readFileSync(path.join(root, 'core/templates/portal/portal.html'), 'utf8');
const source = fs.readFileSync(path.join(root, 'core/static/miniapp/portal.js'), 'utf8');
const section = template.match(/<section id="portal-report-email-settings"[^]*?<\/section>/)[0].replace(' hidden>', '>');
const handler = source.slice(source.indexOf("  let pendingReportEmailKey = ''"), source.indexOf('  function renderPortalTatTargets'));

test('Report send control fits mobile widths and stays single-flight', async ({ page }) => {
  for (const width of [320, 360, 390, 430, 1280]) {
    await page.setViewportSize({ width, height: 740 });
    await mountPortalShell(page, `<main class="page active" style="padding:12px">${section}</main>`);
    await page.locator('#portal-report-email-status').evaluate(node => { node.textContent = '3 active schedules'; });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    const button = await page.locator('#portal-report-email-send').boundingBox();
    expect(button.width).toBeGreaterThan(120);
    expect(button.height).toBeGreaterThanOrEqual(34);
    await page.screenshot({ path: `test-results/report-email-settings-${width}.png` });
  }
  await page.addScriptTag({ content: `
    const el = id => document.getElementById(id);
    const tg = null;
    window.__calls = [];
    window.confirm = () => true;
    window.__uuid = 0;
    window.crypto.randomUUID = () => '00000000-0000-4000-8000-00000000000' + (++window.__uuid);
    const showToast = message => { window.__toast = message; };
    const portalApi = {postJson: (url, body) => new Promise(resolve => { window.__calls.push({url, body}); window.__resolve = resolve; })};
    ${handler}
  ` });
  await page.locator('#portal-report-email-send').click();
  await expect(page.locator('#portal-report-email-send')).toBeDisabled();
  await page.locator('#portal-report-email-send').evaluate(node => node.click());
  expect(await page.evaluate(() => window.__calls.length)).toBe(1);
  await page.evaluate(() => window.__resolve({ok:true,data:{ok:true,message:'3 report emails queued.'}}));
  await expect(page.locator('#portal-report-email-status')).toHaveText('3 report emails queued.');
  await expect(page.locator('#portal-report-email-send')).toBeEnabled();
});

test('A lost response retries the same report action key', async ({ page }) => {
  await page.setContent(section);
  await page.addScriptTag({ content: `
    const el = id => document.getElementById(id);
    const tg = null;
    window.confirm = () => true;
    window.crypto.randomUUID = () => '00000000-0000-4000-8000-000000000001';
    window.__calls = [];
    const showToast = () => {};
    const portalApi = {postJson: async (url, body) => { window.__calls.push(body); throw new Error('Synthetic lost response'); }};
    ${handler}
  ` });
  await page.locator('#portal-report-email-send').click();
  await page.locator('#portal-report-email-send').click();
  expect(await page.evaluate(() => window.__calls.length)).toBe(2);
  expect(await page.evaluate(() => window.__calls[0].client_request_id === window.__calls[1].client_request_id)).toBe(true);
});
