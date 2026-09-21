'use strict';

const path = require('node:path');
const { test, expect } = require('playwright/test');

const asset = name => path.resolve(__dirname, '../static/miniapp', name);

async function loadPortalStyles(page) {
  for (const name of ['base.css', 'components.css', 'portal.css', 'workflow_standard.css', 'theme.css']) {
    await page.addStyleTag({ path: asset(name) });
  }
}

test('FarmUp upload stays compact and usable on a 320px phone', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 320, height: 568 });
  await page.setContent(`
    <body class="workflow-standard portal-app">
      <header class="app-shell-header">
        <div class="portal-header-brand"><button class="shell-menu-button" type="button">Menu</button><div class="shell-title"><h1>Pipeline Portal</h1><p>JBL HomeBiogas</p></div></div>
        <div class="portal-header-actions"><button class="portal-notification-button" type="button"><span>11</span></button><div class="shell-actor"><span class="portal-connection-dot"></span><span class="portal-connection-label">Active</span></div></div>
      </header>
      <main id="content"><div id="portal-screen" data-screen="farmup"><section id="page-farmup" class="page active">
        <header class="farmup-intake-heading"><h1>FarmUp intake</h1><p class="meta">Reconcile the monthly farmer worklist before it enters the Portal.</p></header>
        <form class="portal-import-upload portal-farmup-upload">
          <div class="farmup-upload-heading"><div><span class="settings-eyebrow">Monthly worklist</span><h2>Upload a fresh CSV</h2></div><span class="farmup-upload-format">CSV</span></div>
          <div class="farmup-upload-controls"><label class="farmup-month-field"><span>Target month</span><input type="month" name="period"></label><div class="farmup-file-action"><label class="farmup-file-control invoice-upload-dropzone"><input type="file" name="file"><span>Choose CSV file</span></label><button type="submit" class="btn btn-primary">Upload</button></div></div>
          <p class="farmup-upload-help">Rows are reviewed before they are committed. Sheet synchronization follows separately.</p>
        </form>
        <section class="portal-import-history"><div class="portal-import-history-heading"><h2>Recent batches</h2><button class="btn btn-secondary" type="button">Refresh</button></div><div class="empty-state"><div class="es-title">No active FarmUp batches</div><div class="es-sub">Upload a Farmers CSV to begin.</div></div></section>
      </section></div></main>
    </body>
  `);
  await loadPortalStyles(page);

  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(320);
  const fileControl = await page.locator('.farmup-file-control').boundingBox();
  const uploadButton = await page.locator('.farmup-file-action .btn').boundingBox();
  expect(Math.abs(fileControl.y - uploadButton.y)).toBeLessThanOrEqual(1);
  expect(fileControl.x + fileControl.width).toBeLessThan(uploadButton.x);
  const upload = await page.locator('.portal-farmup-upload').boundingBox();
  expect(upload.height).toBeLessThanOrEqual(190);
  const history = await page.locator('.portal-import-history').boundingBox();
  expect(history.y).toBeLessThan(390);
  await page.screenshot({ path: testInfo.outputPath('farmup-upload-320.png'), fullPage: true });
});
