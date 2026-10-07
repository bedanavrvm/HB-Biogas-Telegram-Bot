'use strict';
const path = require('node:path');
const fs = require('node:fs');
const {test, expect} = require('playwright/test');
const asset = name => path.resolve(__dirname, '../static/miniapp', name);

test('shared phone rendering validates contacts, preserves labels and never dials identifiers', async ({page}) => {
  await page.setContent('<main id="contacts"></main>');
  await page.addScriptTag({path: asset('utils.js')});
  const rendered = await page.evaluate(() => ['0712 345 678', '+254 (712) 345-678', '254712345678', '020 123 4567', '', 'Not recorded', '0712***678', '<img src=x onerror=alert(1)>', 'tel:0712345678'].map(value => window.MiniAppUtils.phoneLink(value)));
  await page.locator('#contacts').evaluate((node, html) => {node.innerHTML = html.join('<br>');}, rendered);
  await expect(page.locator('a[href^="tel:"]')).toHaveCount(4);
  await expect(page.getByRole('link', {name: 'Call 0712 345 678'})).toHaveAttribute('href', 'tel:+254712345678');
  await expect(page.getByRole('link', {name: 'Call +254 (712) 345-678'})).toHaveAttribute('href', 'tel:+254712345678');
  await expect(page.locator('img')).toHaveCount(0);
});

test('dynamic and server-rendered phone fields are hydrated without changing IDs, inputs or masked contacts', async ({page}) => {
  await page.setContent('<main><span data-miniapp-phone>0712 345 678</span><span id="national-id">0712345678</span><input type="tel" value="0712345678"><span data-miniapp-phone>0712***678</span><div class="ag-cell" col-id="customer_phone">0700000002</div><div class="ag-cell" col-id="national_id">0700000003</div></main>');
  await page.addScriptTag({path: asset('utils.js')});
  await expect(page.getByRole('link', {name:'Call 0712 345 678'})).toBeVisible();
  await page.evaluate(() => {
    const node = document.createElement('span'); node.dataset.miniappPhone = ''; node.textContent = '+254700000001'; document.querySelector('main').append(node);
  });
  await expect(page.getByRole('link', {name:'Call +254700000001'})).toBeVisible();
  await expect(page.locator('#national-id a')).toHaveCount(0);
  await expect(page.locator('input')).toHaveValue('0712345678');
  await expect(page.locator('a[href^="tel:"]')).toHaveCount(3);
  await expect(page.locator('.ag-cell[col-id="national_id"] a')).toHaveCount(0);
  await page.locator('.ag-cell[col-id="customer_phone"]').evaluate(node => { node.textContent = '0700000004'; });
  await expect(page.getByRole('link', {name:'Call 0700000004'})).toHaveAttribute('href','tel:+254700000004');
});

test('TAT identifiers use the shared phone action and do not open their parent case', async ({page}) => {
  await page.setContent('<div id="card" role="button" tabindex="0"></div>');
  await page.addScriptTag({path: asset('utils.js')});
  const source = fs.readFileSync(asset('tat_tracker.js'), 'utf8');
  const renderer = source.slice(source.indexOf('  function caseIdentifierMarkup('), source.indexOf('  function renderEmpty('));
  await page.addScriptTag({content: `const escapeHtml = MiniAppUtils.escapeHtml; ${renderer} document.getElementById('card').innerHTML=caseIdentifierMarkup({national_id:'TEST-ID-1',primary_phone:'0700000001'}); window.__caseOpened=0; document.getElementById('card').onclick=()=>window.__caseOpened++;`});
  await expect(page.getByRole('link', {name:'Call 0700000001'})).toHaveAttribute('href','tel:+254700000001');
  await page.getByRole('link', {name:'Call 0700000001'}).click();
  expect(await page.evaluate(() => window.__caseOpened)).toBe(0);
});

test('Portal final review exposes the displayed customer phone as a link, not a read-only input', async ({page}) => {
  await page.setContent('<main id="review"></main>');
  await page.addScriptTag({path: asset('utils.js')});
  const source = fs.readFileSync(asset('portal_farmer_sheet.js'), 'utf8');
  const renderer = source.slice(source.indexOf('  function buildFinalReviewForm('), source.indexOf('  function wireFinalCommentShortcut('));
  await page.addScriptTag({content: `const deps={escapeHtml:MiniAppUtils.escapeHtml}; const state=()=>({metaFinalDecisions:['Approved']}); const decisionReasonMarkup=()=>''; const voiceWidget=()=>''; const productConfigurationMarkup=()=>''; ${renderer} document.getElementById('review').innerHTML=buildFinalReviewForm({primary_phone:'0700000005'});`});
  await expect(page.locator('.phone-action-field [data-miniapp-phone] a')).toHaveAttribute('href', 'tel:+254700000005');
  await expect(page.locator('.phone-action-field input')).toHaveCount(0);
});
