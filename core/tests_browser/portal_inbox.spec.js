'use strict';
const fs = require('node:fs');
const path = require('node:path');
const { test, expect } = require('playwright/test');
const { mountPortalShell } = require('./fixtures/portal_shell');
const asset = name => path.resolve(__dirname, '../static/miniapp', name);
const source = fs.readFileSync(asset('portal.js'), 'utf8');
const inboxCode = source.slice(source.indexOf('  let notificationInbox'), source.indexOf('  function focusRequestedQueueCard'));
const eventsCode = source.slice(source.indexOf("  el('portal-notification-button')?.addEventListener"), source.indexOf('  updateConnectionBanner();', source.indexOf("  el('portal-notification-button')?.addEventListener")));

async function mountInbox(page, total = 19) {
  await mountPortalShell(page, '<div id="portal-screen" data-screen="dashboard"><section data-top-level="true"></section></div>');
  await page.addScriptTag({ path: asset('components.js') });
  await page.addScriptTag({ path: asset('vendor-lucide-1.44.0.min.js') });
  await page.evaluate(total => {
    window.inboxTotal = total; window.inboxErrors = []; window.pendingInbox = [];
    window.fixtureInbox = page => {
      const total = window.inboxTotal;
      const pages = Math.max(1, Math.ceil(total / 10));
      page = Math.max(1, Math.min(page, pages));
      const start = (page - 1) * 10;
      const rows = Array.from({length: Math.min(10, total - start)}, (_, i) => ({
        key: `visit:${start + i}`, kind:'case', label:`Synthetic customer ${start + i + 1}`,
        detail: 'JBL visit required', context:'Training branch', url:`/portal/s/jbl/?focus=training-${start + i}`,
      }));
      return {notification_items: rows, notification_count: total,
        notification_pagination: {page, pages, total, start:total ? start + 1 : 0, end:start + rows.length}};
    };
    window.Telegram = {WebApp:{onEvent(){}, BackButton:{offClick(){}, onClick(fn){window.telegramBack=fn;}, show(){}, hide(){}}}};
  }, total);
  await page.addScriptTag({ content: `
    const el = id => document.getElementById(id);
    const hasCapability = () => true;
    const escapeHtml = value => { const node = document.createElement('span'); node.textContent = String(value); return node.innerHTML; };
    const showToast = message => window.inboxErrors.push(message);
    const navigateToUrl = url => window.inboxDestination = url;
    const apiFetch = async url => {
      const page = Number(new URLSearchParams(url.split('?')[1]).get('notification_page') || 1);
      if (window.failInbox) return {ok:false,data:{message:'Unable to refresh notifications.'}};
      if (window.deferInbox) return new Promise(resolve => window.pendingInbox.push(() => resolve({ok:true,data:window.fixtureInbox(page)})));
      return {ok:true,data:window.fixtureInbox(page)};
    };
    ${inboxCode}
    ${eventsCode}
    window.testInbox = portalNotificationInbox();
    renderPortalNotifications(window.fixtureInbox(1));
    window.lucide.createIcons();
  ` });
  await page.addScriptTag({ path: asset('miniapp-nav.js') });
}

for (const width of [320,360,390,430,768,1280]) {
  for (const theme of ['light','dark']) {
    test(`Complete Portal inbox at ${width}px in ${theme}`, async ({page}, testInfo) => {
      await page.setViewportSize({width,height:740});
      await mountInbox(page);
      await page.evaluate(theme => {
        document.documentElement.dataset.miniappColorScheme = theme;
        if (theme === 'dark') {
          for (const [key, value] of Object.entries({bg:'#111827',secondary_bg:'#1f2937',text:'#f9fafb',hint:'#cbd5e1',button:'#38bdf8',button_text:'#082f49'})) {
            document.documentElement.style.setProperty(`--tg-theme-${key.replaceAll('_','-')}-color`, value);
          }
        }
      }, theme);
      await page.locator('#portal-notification-button').click();
      await expect(page.locator('#portal-notification-list a')).toHaveCount(10);
      await expect(page.locator('#portal-notification-count')).toHaveText('19');
      await expect(page.locator('#portal-notification-range')).toHaveText('1–10 of 19');
      const heading = await page.locator('#portal-notification-panel > header').boundingBox();
      const close = await page.locator('#portal-notification-close').boundingBox();
      expect(close.width).toBe(44); expect(close.height).toBe(44);
      expect(await page.locator('#portal-notification-panel').evaluate(node => getComputedStyle(node).borderStyle)).toBe('solid');
      expect(Math.abs(heading.x + heading.width - 12 - close.x - close.width)).toBeLessThan(1);
      if ([320,430,1280].includes(width)) {
        expect(await page.locator('#portal-notification-panel > header').screenshot({animations:'disabled'}))
          .toMatchSnapshot(`inbox-heading-${width}-${theme}.png`, {maxDiffPixelRatio:0.01});
      }
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await page.screenshot({path:testInfo.outputPath(`inbox-${width}-${theme}.png`), animations:'disabled'});
      await page.locator('#portal-notification-next').click();
      await expect(page.locator('#portal-notification-list a')).toHaveCount(9);
      await expect(page.locator('#portal-notification-range')).toHaveText('11–19 of 19');
      await expect(page.locator('#portal-notification-next')).toBeDisabled();
      await page.evaluate(() => window.telegramBack());
      await expect(page.locator('#portal-notification-panel')).toBeHidden();
      await expect(page.locator('#portal-notification-button')).toBeFocused();
    });
  }
}

test('Inbox retains content on failure and discards stale responses', async ({page}) => {
  await mountInbox(page);
  await page.evaluate(() => window.failInbox = true);
  await page.evaluate(() => window.testInbox.load(2));
  await expect(page.locator('#portal-notification-range')).toHaveText('1–10 of 19');
  expect(await page.evaluate(() => window.inboxErrors)).toEqual(['Unable to refresh notifications.']);
  await page.evaluate(() => { window.failInbox=false; window.deferInbox=true; void window.testInbox.load(2); });
  await page.evaluate(() => { window.inboxTotal=1; window.testInbox.setPayload(window.fixtureInbox(1)); window.pendingInbox[0](); });
  await expect(page.locator('#portal-notification-count')).toHaveText('1');
  await expect(page.locator('#portal-notification-list a')).toHaveCount(1);
  await expect(page.locator('#portal-notification-pagination')).toBeHidden();
});

for (const total of [0,1,10,35]) {
  test(`Inbox count and range remain consistent for ${total} tasks`, async ({page}) => {
    await mountInbox(page,total);
    await page.locator('#portal-notification-button').click();
    await expect(page.locator('#portal-notification-list a')).toHaveCount(Math.min(total,10));
    if (total > 10) await expect(page.locator('#portal-notification-pagination')).toBeVisible();
    else await expect(page.locator('#portal-notification-pagination')).toBeHidden();
    await page.locator('#portal-notification-close').press('Escape');
    await expect(page.locator('#portal-notification-panel')).toBeHidden();
  });
}
