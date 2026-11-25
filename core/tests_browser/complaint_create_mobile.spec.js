'use strict';
const fs = require('node:fs');
const path = require('node:path');
const {test, expect} = require('playwright/test');
const root = path.resolve(__dirname, '../..');
const asset = name => path.join(root, 'core/static/miniapp', name);

async function openCreate(page) {
  const template = fs.readFileSync(path.join(root, 'core/templates/complaint_cases/app.html'), 'utf8')
    .replace('{% include "complaint_cases/lucide_icons.html" %}', fs.readFileSync(path.join(root, 'core/templates/complaint_cases/lucide_icons.html'), 'utf8'))
    .replace("{% static 'miniapp/jawabu-logo.png' %}", `data:image/png;base64,${fs.readFileSync(asset('jawabu-logo.png')).toString('base64')}`)
    .replace(/{#[\s\S]*?#}/g, '').replace(/{%[^%]+%}/g, '')
    .replace(/<script[^>]*>[\s\S]*?<\/script>/g, '').replace(/<link[^>]*>/g, '');
  await page.setContent(template);
  for (const name of ['components.css', 'base.css', 'complaint_cases.css']) await page.addStyleTag({path: asset(name)});
  await page.addScriptTag({path: asset('utils.js')});
  await page.evaluate(() => {
    const webApp = {initData: 'synthetic-layout-only', BackButton: {onClick() {}, show() {}, hide() {}}, onEvent() {}};
    window.Telegram = {WebApp: webApp};
    Object.assign(window.MiniAppUtils, {initTelegram: () => webApp, setCloseProtection() {},
      bindCreationDraft(form, hooks) {window.__draftHooks = hooks; return {load() {}};}});
    const locations = {branches: [{code: 'TRAINING', name: 'Training Branch'}], counties: [{code: 'TEST', name: 'Training County'}], sub_counties: [{code: 'TEST-SUB', name: 'Training Constituency'}]};
    const matches = ['Training Client', 'Training Client With Several Names For A Longer Wrapped Result', 'Training Client Two'].map((name, i) => ({key: 'fixture-'+i, reference: 'JBL-TEST-'+i, name,
      national_id: '1234567', primary_phone: '0700000000', branch: i === 1 ? 'Training Branch With A Longer Name' : 'Training',
      location: i === 2 ? '' : 'Training County', matched_on: 'name', conflicts: i === 1 ? ['Different entered ID'] : []}));
    const selection = {fields: {portal_source_key: 'fixture-0', portal_source_label: 'JBL-TEST-0', client_name: 'Training Client', customer_id: '1234567', customer_phone: '0700000000', secondary_phone: '', branch_region: 'TRAINING', county: 'TEST', sub_county: 'TEST-SUB', village: 'Training Village'}, location_options: locations, field_issues: {}, warnings: []};
    window.__selection = selection;
    window.ComplaintCasesMiniAppApi = {
      async postJson(url, data) {
        if (url === 'bootstrap/') return {data: {actor: {name: 'Training Officer', role: 'OFFICER', capabilities: ['complaint.queue.view', 'complaint.case.create']}, counts: {}, branches: ['Training Branch'], categories: ['Product Issue'], location_options: locations}};
        if (url === 'customers/suggest/') return {data: data.source_key ? {selection} : {matches}};
        if (url === 'cases/') return {cases: [], pagination: {page: 1, pages: 1, total: 0}};
        return {data: {}};
      },
      async getJson() {return {data: locations};},
    };
  });
  await page.addScriptTag({path: asset('complaint_cases.js')});
  await page.locator('#newCaseBtn').click();
}

test.beforeEach(async ({page}) => {
  await page.setViewportSize({width: 390, height: 844});
  await openCreate(page);
});

test('customer suggestions align wrapped and short results on mobile', async ({page}, info) => {
  await page.locator('[name=client_name]').fill('Training');
  await expect(page.locator('[data-customer-choice]')).toHaveCount(3);
  for (const width of [320, 390, 768]) {
    await page.setViewportSize({width, height: 844});
    await page.locator('#portalCustomerSuggestions').scrollIntoViewIfNeeded();
    await page.screenshot({path: info.outputPath('suggestions-'+width+'.png')});
    const rows = await page.locator('[data-customer-choice]').evaluateAll(nodes => nodes.map(node => {
      const box = node.getBoundingClientRect();
      return {left: box.left, right: box.right, text: [...node.children].map(child => child.getBoundingClientRect().left)};
    }));
    for (const row of rows) {
      expect(Math.abs(row.left-rows[0].left)).toBeLessThan(1);
      for (const left of row.text) expect(Math.abs(left-row.left-10)).toBeLessThan(1);
    }
  }
});

test('selected biodata has only an inline clear icon and keeps entered values when cleared', async ({page}, info) => {
  const errors = []; page.on('pageerror', error => errors.push(error.message));
  await page.locator('[name=complaint_description]').fill('Keep the entered complaint');
  await page.locator('[name=client_name]').fill('Training');
  await page.locator('[data-customer-choice]').first().click();
  const clear = page.getByRole('button', {name: 'Clear Master Data selection', exact: true});
  await expect(clear).toBeVisible();
  await expect(page.getByText('Biodata copied from Master Data. You can edit these fields.', {exact: true})).toHaveCount(0);
  await expect(page.locator('#portalCustomerSuggestions')).toBeHidden();
  const name = page.locator('[name=client_name]');
  const inputBox = await name.boundingBox(), clearBox = await clear.boundingBox();
  expect(Math.abs(inputBox.x+inputBox.width-clearBox.x-clearBox.width)).toBeLessThan(1);
  expect(clearBox.y+clearBox.height).toBeLessThanOrEqual(inputBox.y);
  await name.scrollIntoViewIfNeeded();
  await page.screenshot({path: info.outputPath('selected-mobile.png')});
  await page.emulateMedia({colorScheme: 'dark'});
  await page.screenshot({path: info.outputPath('selected-mobile-dark.png')});
  await clear.click();
  await expect(clear).toBeHidden();
  await expect(page.locator('[name=portal_source_key]')).toHaveValue('');
  await expect(name).toHaveValue('Training Client');
  await expect(page.locator('[name=complaint_description]')).toHaveValue('Keep the entered complaint');
  await name.fill('Training'); await page.locator('[data-customer-choice]').first().click();
  await page.locator('#createCaseForm [name=customer_id]').fill('7654321'); await expect(clear).toBeHidden();
  await page.evaluate(async () => window.__draftHooks.restore({portal_source_key: 'fixture-0', portal_source_label: 'JBL-TEST-0', branch_region: 'TRAINING', county: 'TEST', sub_county: 'TEST-SUB'}));
  await expect(clear).toBeVisible();
  await expect(page.getByText('Biodata copied from Master Data. You can edit these fields.', {exact: true})).toHaveCount(0);
  await page.locator('#createCaseForm').evaluate(form => form.reset()); await expect(clear).toBeHidden();
  expect(errors).toEqual([]);
});

test('selection review warnings remain visible and the clear icon supports the keyboard', async ({page}) => {
  await page.evaluate(() => {window.__selection.warnings = ['Review the historical location']; window.__selection.field_issues = {client_name: 'Review the customer name'};});
  await page.locator('[name=client_name]').fill('Training'); await page.locator('[data-customer-choice]').first().click();
  await expect(page.locator('#portalCustomerSuggestions')).toHaveText('Review the historical location');
  await expect(page.locator('.customer-name-field [data-portal-field-note]')).toHaveText('Review the customer name');
  const clear = page.getByRole('button', {name: 'Clear Master Data selection', exact: true});
  await clear.focus(); await page.keyboard.press('Enter');
  await expect(clear).toBeHidden();
  await expect(page.locator('[name=client_name]')).toBeFocused();
  await expect(page.locator('[data-portal-field-note]')).toHaveCount(0);
  await expect(page.locator('#portalCustomerSuggestions')).toBeHidden();
});

test('supporting document actions fill the available row', async ({page}, info) => {
  for (const width of [320, 390, 768]) {
    await page.setViewportSize({width, height: 844});
    const actions = page.locator('.create-evidence-picker .evidence-actions');
    await actions.scrollIntoViewIfNeeded();
    await page.screenshot({path: info.outputPath('evidence-'+width+'.png')});
    const parent = await page.locator('.create-evidence-picker').evaluate(node => {
      const box = node.getBoundingClientRect(), style = getComputedStyle(node);
      return {left: box.left+parseFloat(style.paddingLeft)+parseFloat(style.borderLeftWidth), right: box.right-parseFloat(style.paddingRight)-parseFloat(style.borderRightWidth)};
    });
    const buttons = await actions.locator('button').evaluateAll(nodes => nodes.map(node => {
      const box = node.getBoundingClientRect(); return {left: box.left, right: box.right, width: box.width, top: box.top};
    }));
    expect(Math.abs(buttons[0].left-parent.left)).toBeLessThan(1);
    expect(Math.abs(buttons[1].right-parent.right)).toBeLessThan(1);
    expect(Math.abs(buttons[0].width-buttons[1].width)).toBeLessThan(1);
    expect(buttons[0].top).toBe(buttons[1].top);
  }
  const chooser = page.waitForEvent('filechooser');
  await page.locator('[data-files-target=create]').click();
  await (await chooser).setFiles({name: 'training.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.4\nSynthetic local attachment')});
  await expect(page.locator('#createSelectedEvidence')).toContainText('training.pdf');
});
