'use strict';

const fs = require('node:fs');
const path = require('node:path');
const { test, expect } = require('playwright/test');

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
      await page.setContent(`<html><head><meta charset="utf-8"></head><body class="workflow-standard portal-app"><header class="app-shell-header">Pipeline Portal</header><main id="content"><div id="portal-screen">${performanceMarkup}</div></main></body></html>`);
      for (const name of ['base.css', 'components.css', 'workflow_standard.css', 'portal.css', 'theme.css']) {
        await page.addStyleTag({ path: asset(name) });
      }
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
      await expect(page.locator('#portal-performance-metrics')).toHaveCount(0);
      await expect(page.locator('.portal-performance-rank').first()).toHaveText('1');
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
      await page.locator('#portal-performance-period').fill('2026-05');
      await expect(page.locator('#portal-performance-month-display')).toHaveText('May 2026');
      if (width === 320) {
        await page.waitForTimeout(250);
        await page.screenshot({ path: testInfo.outputPath(`portal-performance-filters-${theme}.png`) });
      }
      await page.locator('#portal-performance-filter-close').click();
      await page.locator('#portal-performance-details-open').click();
      await expect(page.locator('#portal-performance-details')).toHaveAttribute('aria-hidden', 'false');
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
