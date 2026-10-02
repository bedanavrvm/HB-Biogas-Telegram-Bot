'use strict';
const fs = require('node:fs');
const path = require('node:path');
const { test, expect } = require('playwright/test');
const root = path.resolve(__dirname, '../..');
const asset = name => path.join(root, 'core/static/miniapp', name);

test('Portal duplicate selection works without changing the review filter', async ({ page }) => {
  const source = fs.readFileSync(asset('portal_invoices.js'), 'utf8');
  const fn = source.match(/  async function selectAllFilteredDuplicates\([^]*?\n  \}/)[0];
  await page.setContent('<button id="invoice-select-all-duplicates"></button><div id="invoice-pool-list"></div>');
  await page.addScriptTag({ content: `
    const state = { workspace: 'inbox', review: '', selectedIds: new Set() };
    const el = id => document.getElementById(id);
    const canWriteInvoices = () => true;
    const updateBulkToolbar = () => {};
    const deps = { apiFetch: async url => { window.requestUrl = url; return {ok:true,data:{ok:true,duplicate_ids:['copy-1']}}; }, showToast: () => {} };
    ${fn}
    window.runSelection = async () => { await selectAllFilteredDuplicates(); return Array.from(state.selectedIds); };
  ` });
  expect(await page.evaluate(() => window.runSelection())).toEqual(['copy-1']);
  expect(await page.evaluate(() => window.requestUrl)).toContain('review=duplicates');
});

test('Portal notifications scroll within small screens', async ({ page }) => {
  for (const width of [320, 360, 390, 430]) {
    await page.setViewportSize({ width, height: 640 });
    await page.setContent(`<body class="portal-app"><section id="portal-notification-panel" class="portal-notification-panel"><div><h2>Needs your input</h2><button id="portal-notification-close">×</button></div><div id="portal-notification-list">${Array.from({length:40},(_,i)=>`<a class="portal-notification-row">Synthetic task ${i}</a>`).join('')}</div></section></body>`);
    await page.addStyleTag({ path: asset('base.css') });
    await page.addStyleTag({ path: asset('portal.css') });
    const bounds = await page.locator('#portal-notification-panel').boundingBox();
    expect(bounds.height).toBeLessThan(600);
    expect(await page.locator('#portal-notification-list').evaluate(node => ['auto','scroll'].includes(getComputedStyle(node).overflowY))).toBe(true);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: `test-results/portal-notifications-${width}.png` });
  }
});

test('Phone links dial without opening the containing case', async ({ page }) => {
  await page.setContent('<article id="case"></article>');
  await page.evaluate(() => document.addEventListener('click', event => event.preventDefault(), true));
  await page.addScriptTag({ path: asset('portal_helpers.js') });
  await page.evaluate(() => {
    const card = document.getElementById('case');
    card.innerHTML = window.PortalMiniAppHelpers.phoneLink('0712 000 000');
    card.addEventListener('click', () => { window.caseOpened = true; });
  });
  const phone = page.getByRole('link', { name: 'Call 0712 000 000' });
  await expect(phone).toHaveAttribute('href', 'tel:0712000000');
  await phone.click();
  expect(await page.evaluate(() => Boolean(window.caseOpened))).toBe(false);
});

test('Large queue pagination and HB status pills fit a narrow phone', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 640 });
  await page.setContent(`<body class="portal-app"><nav class="pagination"><button class="pagination-icon">Previous</button><div class="pagination-pages"><button class="pagination-page">1</button><span class="pagination-ellipsis">…</span><button class="pagination-page">499</button><button class="pagination-page is-current">500</button><button class="pagination-page">501</button><span class="pagination-ellipsis">…</span><button class="pagination-page">1000</button></div><button class="pagination-icon">Next</button><span class="pagination-total">30,000 entries</span></nav><div class="hb-action-counts"><button>Not installed</button><button>Installed</button></div></body>`);
  await page.addStyleTag({ path: asset('base.css') });
  await page.addStyleTag({ path: asset('portal.css') });
  await expect(page.locator('.pagination-page:visible')).toHaveCount(1);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  const widths = await page.locator('.hb-action-counts button').evaluateAll(nodes => nodes.map(node => node.getBoundingClientRect().width));
  expect(Math.abs(widths[0] - widths[1])).toBeLessThan(1);
  expect(widths[0]).toBeGreaterThan(140);
});
