'use strict';

const fs = require('node:fs');
const path = require('node:path');
const { test, expect } = require('playwright/test');
const { mountPortalShell } = require('./fixtures/portal_shell');

const asset = name => path.resolve(__dirname, '../static/miniapp', name);
const template = fs.readFileSync(path.resolve(__dirname, '../templates/portal/portal.html'), 'utf8');
const performanceMarkup = template.split("{% if active_screen == 'performance' %}")[1].split('{% endif %}')[0];

function payload(query) {
  const params = new URLSearchParams(query.split('?')[1] || '');
  const view = params.get('view') || 'people';
  const page = Number(params.get('page') || 1);
  const selected = { score: 83, points: 83, cases: 24, visits: 24,
    milestones: [{ key: 'jbl_visit_completed', label: 'JBL visit', count: 24 }] };
  return { ok: true, data: {
    period: '2026-09', period_kind: 'month', view,
    branch: params.get('branch') || '', product: params.get('product') || '',
    filter_options: { branches: ['Embu', 'Nakuru'], products: ['HB'],
      products_by_branch: { Embu: ['HB'], Nakuru: ['HB'] } },
    personal: selected, slice: selected,
    people_visible: true, final: false,
    page, pages: 2, total: 20,
    rows: Array.from({ length: 10 }, (_, index) => ({
      rank: (page - 1) * 10 + index + 1,
      label: index === 0 ? 'A very long staff name that must wrap without moving the score' : `Staff ${index + 1}`,
      cases: 24, visits: 24, points: 83, score: 83,
      movement: index === 0 ? { direction: 'up', places: 2 } : { direction: 'none', places: 0 },
    })),
  } };
}

for (const width of [320, 360, 390, 430, 768, 1280]) {
  for (const theme of ['light', 'dark']) {
    test(`Portal Performance aligns at ${width}px in ${theme} theme`, async ({ page }, testInfo) => {
      test.setTimeout(45000);
      await page.setViewportSize({ width, height: 740 });
      await mountPortalShell(page, `<div id="portal-screen">${performanceMarkup}</div>`);
      await page.addScriptTag({ path: asset('vendor-lucide-1.44.0.min.js') });
      if (theme === 'dark') await page.evaluate(() => {
        document.documentElement.dataset.miniappColorScheme = 'dark';
        document.documentElement.style.setProperty('--tg-theme-bg-color', '#111827');
        document.documentElement.style.setProperty('--tg-theme-secondary-bg-color', '#1f2937');
        document.documentElement.style.setProperty('--tg-theme-text-color', '#f9fafb');
        document.documentElement.style.setProperty('--tg-theme-hint-color', '#cbd5e1');
        document.documentElement.style.setProperty('--tg-theme-button-color', '#38bdf8');
        document.documentElement.style.setProperty('--tg-theme-button-text-color', '#082f49');
      });
      await page.addScriptTag({ path: asset('portal_recognition.js') });
      await page.exposeFunction('__performancePayload', payload);
      await page.evaluate(() => window.PortalRecognitionUI.load({
        apiFetch: async url => ({ ok: true, data: await window.__performancePayload(url) }),
        showToast: message => { throw new Error(message); },
      }));
      await expect(page.locator('.portal-performance-row')).toHaveCount(10);
      await expect(page.locator('.portal-performance-own-cell')).toHaveCount(3);
      expect(await page.locator('.portal-performance-row').first().evaluate(node => getComputedStyle(node).borderStyle)).not.toBe('none');
      await expect(page.locator('#portal-performance-metrics')).toHaveCount(0);
      await expect(page.locator('.portal-performance-rank').first()).toHaveText('1');
      const toolbar = await page.locator('.portal-performance-header').boundingBox();
      const filter = await page.locator('#portal-performance-filter').boundingBox();
      expect(Math.abs(toolbar.x + toolbar.width - filter.x - filter.width)).toBeLessThanOrEqual(5);
      if ([320,430,1280].includes(width)) {
        expect(await page.locator('.portal-performance-header').screenshot({animations:'disabled'}))
          .toMatchSnapshot(`toolbar-${width}-${theme}.png`, {maxDiffPixelRatio:0.01});
      }
      await expect(page.locator('.portal-performance-movement').first()).toHaveText('↑2');
      const layout = await page.evaluate(() => {
        const first = document.querySelector('.portal-performance-row');
        const second = first.nextElementSibling;
        const score = first.querySelector('.portal-performance-row-score').getBoundingClientRect();
        const nextScore = second.querySelector('.portal-performance-row-score').getBoundingClientRect();
        return { overflow: document.documentElement.scrollWidth - innerWidth,
          scoreRight: score.right, nextScoreRight: nextScore.right };
      });
      expect(layout.overflow).toBeLessThanOrEqual(0);
      expect(Math.abs(layout.scoreRight - layout.nextScoreRight)).toBeLessThan(1);
      await page.screenshot({ path: testInfo.outputPath(`portal-performance-${width}-${theme}.png`), fullPage: true });
      await page.locator('#portal-performance-filter').click();
      await expect(page.locator('#portal-performance-filters')).toHaveAttribute('aria-hidden', 'false');
      const headerAlignment = await page.evaluate(() => {
        const title = document.getElementById('portal-performance-filter-title').getBoundingClientRect();
        const close = document.getElementById('portal-performance-filter-close').getBoundingClientRect();
        return { titleCenter:title.y + title.height / 2, closeCenter:close.y + close.height / 2, closeWidth:close.width, titleRight:title.right, closeLeft:close.left };
      });
      expect(Math.abs(headerAlignment.titleCenter - headerAlignment.closeCenter)).toBeLessThan(2);
      expect(headerAlignment.closeWidth).toBeGreaterThanOrEqual(44);
      expect(headerAlignment.closeLeft).toBeGreaterThanOrEqual(headerAlignment.titleRight);
      if ([320,430,1280].includes(width)) {
        expect(await page.locator('#portal-performance-filters .sheet-header').screenshot({animations:'disabled'}))
          .toMatchSnapshot(`filter-heading-${width}-${theme}.png`, {maxDiffPixelRatio:0.01});
      }
      const filterHeight = await page.locator('#portal-performance-filters .sheet-panel').evaluate(node => node.getBoundingClientRect().height);
      expect(filterHeight).toBeLessThan(500);
      await page.locator('#portal-performance-period').fill('2026-05');
      await expect(page.locator('#portal-performance-month-display')).toHaveText('May 2026');
      if (width === 320) {
        await page.waitForTimeout(250);
        await page.screenshot({ path: testInfo.outputPath(`portal-performance-filters-${theme}.png`) });
      }
      await page.locator('#portal-performance-filter-close').click();
      await page.locator('#portal-performance-details-open').click();
      await expect(page.locator('#portal-performance-details')).toHaveAttribute('aria-hidden', 'false');
      const detailsClose = await page.locator('#portal-performance-details-close').boundingBox();
      expect(detailsClose.width).toBeGreaterThanOrEqual(44);
      expect(detailsClose.height).toBeGreaterThanOrEqual(44);
      const closeIcon = await page.locator('#portal-performance-details-close svg').boundingBox();
      expect(closeIcon.width).toBe(16);
      expect(closeIcon.height).toBe(16);
      if ([320,430,1280].includes(width)) {
        expect(await page.locator('#portal-performance-details .sheet-header').screenshot({animations:'disabled'}))
          .toMatchSnapshot(`details-heading-${width}-${theme}.png`, {maxDiffPixelRatio:0.01});
      }
      if (width === 320) {
        await page.waitForTimeout(250);
        await page.screenshot({ path: testInfo.outputPath(`portal-performance-details-${theme}.png`) });
      }
      await page.locator('#portal-performance-details-close').click();
      await page.locator('#portal-performance-next').click();
      await expect(page.locator('.portal-performance-rank').first()).toHaveText('11');
    });
  }
}
