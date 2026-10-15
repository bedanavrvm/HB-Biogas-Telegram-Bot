'use strict';
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test, expect} = require('playwright/test');
const {mountPortalShell} = require('./fixtures/portal_shell');
const asset = name => path.resolve(__dirname, '../static/miniapp', name);
const template = fs.readFileSync(path.resolve(__dirname, '../templates/portal/portal.html'), 'utf8');

for (const width of [320, 390, 430, 1280]) {
  test(`payment header icons and search close stay aligned at ${width}px`, async ({page}, info) => {
    await page.setViewportSize({width, height:900});
    const start = template.indexOf('    <section id="payments-detail"');
    const markup = template.slice(start, template.indexOf('  <dialog id="payment-receipt-dialog"', start));
    await mountPortalShell(page, '<div id="portal-screen" data-screen="payments" data-payment-batch-id="synthetic-batch">' + markup + '</div>');
    await page.evaluate(() => document.body.classList.add('portal-app', 'workflow-standard'));
    await page.addScriptTag({path:asset('portal_payments.js')});
    await page.evaluate(async () => {
      const batch = {id:'synthetic-batch', payment_number:12345, status:'draft', revision:2,
        status_label:'Draft', total_amount:'12345678.90', counts:{total:1, pending:1},
        cases:[], activity:[]};
      PortalMiniAppPayments.init({el:id=>document.getElementById(id), escapeHtml:value=>String(value??''), state:{capabilities:new Set(['portal.payment.view','portal.payment.prepare'])},
        showToast(){}, apiFetch:async url => ({ok:true, data:{ok:true, batch, farmers:[], pagination:{}, cases:[]}})});
      await PortalMiniAppPayments.load();
    });
    await expect(page.locator('.payment-detail-header #payments-preview-sheet')).toBeVisible();
    await expect(page.locator('.payment-detail-header #payments-cancel')).toBeVisible();
    await expect(page.locator('#payments-preview-sheet')).toHaveText('');
    await page.locator('#payments-search').focus();
    await expect(page.locator('#payments-search-close')).toBeVisible();
    const geometry = await page.evaluate(() => {
      const rect = id => document.getElementById(id).getBoundingClientRect().toJSON();
      return {search:rect('payments-search'), close:rect('payments-search-close'),
        actions:rect('payments-header-actions'), header:document.querySelector('.payment-detail-header').getBoundingClientRect().toJSON(),
        overflow:document.documentElement.scrollWidth > innerWidth};
    });
    expect(Math.abs(geometry.search.y - geometry.close.y)).toBeLessThanOrEqual(2);
    expect(geometry.actions.right).toBeLessThanOrEqual(geometry.header.right);
    expect(geometry.actions.right).toBeGreaterThan(geometry.header.right - 5);
    expect(geometry.overflow).toBe(false);
    for (const dark of [false,true]) {
      await page.evaluate(dark => {
        document.documentElement.dataset.miniappColorScheme = dark ? 'dark' : 'light';
        for (const [key,value] of Object.entries(dark ? {bg:'#17171e','secondary-bg':'#20202c',text:'#ffffff',hint:'#a8a8b3'} : {bg:'#f5f7f8','secondary-bg':'#ffffff',text:'#17212b',hint:'#6d7a86'})) document.documentElement.style.setProperty('--tg-theme-'+key+'-color', value);
      }, dark);
      await expect(page.locator('#payments-preview-sheet')).toHaveCSS('color', dark ? 'rgb(255, 255, 255)' : 'rgb(23, 33, 43)');
      await page.screenshot({path:info.outputPath(`payment-${width}-${dark?'dark':'light'}.png`), animations:'disabled'});
    }
    await page.locator('#payments-search-close').click();
    await expect(page.locator('#payments-search-results')).toBeHidden();
  });
}

async function mountCorrection(page, phoneNoteRequired = false) {
  await page.setViewportSize({width:390,height:844});
  await mountPortalShell(page, '<div id="portal-screen" data-screen="invoices" data-invoice-view="detail" data-invoice-id="synthetic-invoice"><div id="invoice-detail-page"></div></div>');
  await page.evaluate(() => document.body.classList.add('portal-app','workflow-standard'));
  for (const name of ['utils.js','portal_dialogs.js','portal_invoices.js']) await page.addScriptTag({path:asset(name)});
  await page.evaluate(async phoneNoteRequired => {
    const person={name:'Synthetic Applicant',national_id:'12345678'};
    window.saveAttempts=[];
    window.letterLinkRequests=0;
    window.downloads=[];
    PortalMiniAppInvoices.init({state:{capabilities:new Set(['portal.invoice.view','portal.invoice.write','portal.invoice_identity.manage'])},showToast(){},
      downloadPortalFile:file=>window.downloads.push(file),
      apiFetch:async (url,options) => {
        if (url.endsWith('/download-link/')) {
          window.letterLinkRequests++;
          return {ok:true,data:{ok:true,filename:'Synthetic Letter v2.docx',download_url:'https://example.invalid/fresh-'+window.letterLinkRequests}};
        }
        if (url.endsWith('/replacement/')) {
          window.saveAttempts.push(JSON.parse(options.body));
          return window.saveAttempts.length === 1 ? {ok:false,data:{error:'Synthetic temporary failure'}} : {ok:true,data:{ok:true}};
        }
        if (url.includes('replacement-candidates')) return {ok:true,data:{ok:true,revision:3,candidates:[{
          invoice:{id:'replacement',revision:7,invoice_no:'TEST-2',customer_name:'S. Applicant',customer_id:'12345678',status:'unmatched'},
          id_match:true,name_match:false,selectable:true,phone_note_required:phoneNoteRequired,warnings:['The name differs. National ID matches.']}]}};
        return {ok:true,data:{ok:true,invoice:{id:'synthetic-invoice',revision:4,status:'matched',invoice_no:'TEST-1',customer_name:person.name,
          identity:{invoice_identity:person,applicant_identity:person,name_change:{id:'correction',status:'awaiting_replacement',
            latest_letter:{id:'letter-artifact',filename:'Old label.docx',download_url:'https://example.invalid/expired'}}}},batch:{},events:[],duplicates:[]}};
      }});
    await PortalMiniAppInvoices.load();
  }, phoneNoteRequired);
}

test('corrected invoice accepts name warning and preserves editable note after failure', async ({page},info) => {
  await mountCorrection(page, true);
  await page.locator('.invoice-name-change-replacement').click();
  await expect(page.locator('.choose-replacement')).toBeEnabled();
  await page.locator('.choose-replacement').click();
  const note=page.locator('#corrected-invoice-note');
  await note.click();
  await page.keyboard.type('Synthetic verified alternate phone');
  await page.getByRole('button',{name:'Confirm replacement',exact:true}).click();
  await expect(page.locator('.invoice-workflow-error')).toHaveText('Synthetic temporary failure');
  await expect(note).toHaveValue('Synthetic verified alternate phone');
  await expect(page.locator('.replacement-candidate-list').locator('..').locator('..').locator('..')).toHaveJSProperty('inert',true);
  await page.screenshot({path:info.outputPath('corrected-invoice-note.png')});
  await page.getByRole('button',{name:'Confirm replacement',exact:true}).click();
  await expect(page.locator('#corrected-invoice-note')).toHaveCount(0);
  expect(await page.evaluate(() => window.saveAttempts.every(row=>row.revision===3 && row.invoice_revision===7 && row.verification_note.includes('Synthetic')))).toBe(true);
});

test('letter download refreshes the link, names the actual file and respects cancellation', async ({page}) => {
  await mountCorrection(page);
  await page.locator('.invoice-name-change-download').click();
  await expect(page.locator('.invoice-action-confirm')).toContainText('Synthetic Letter v2.docx');
  await page.locator('[data-confirm-cancel]').click();
  expect(await page.evaluate(()=>window.downloads)).toEqual([]);
  await page.locator('.invoice-name-change-download').click();
  await page.locator('[data-confirm-yes]').click();
  expect(await page.evaluate(()=>window.downloads)).toEqual([{url:'https://example.invalid/fresh-2',filename:'Synthetic Letter v2.docx'}]);
});

test('corrected invoice without a phone discrepancy uses a confirmation with no note', async ({page}, info) => {
  await mountCorrection(page);
  await page.locator('.invoice-name-change-replacement').click();
  await page.locator('.choose-replacement').click();
  await expect(page.locator('.invoice-action-confirm')).toContainText(/national ID matches/i);
  await expect(page.locator('.invoice-action-confirm input, .invoice-action-confirm textarea')).toHaveCount(0);
  await page.screenshot({path:info.outputPath('corrected-invoice-confirmation.png')});
  await page.locator('[data-confirm-cancel]').click();
  expect(await page.evaluate(() => window.saveAttempts)).toHaveLength(0);
  await page.locator('.choose-replacement').click();
  await page.locator('[data-confirm-yes]').click();
  expect(await page.evaluate(() => window.saveAttempts)).toHaveLength(1);
  await expect(page.locator('.choose-replacement')).toBeEnabled();
});

test('download handler falls back when Telegram exposes an unsupported download method', () => {
  const source=fs.readFileSync(asset('portal.js'),'utf8');
  const code=source.slice(source.indexOf('  function downloadPortalFile('),source.indexOf('  function summaryGrid('));
  for (const supported of [false,true]) {
    const opened=[];
    const context={tg:{isVersionAtLeast:()=>supported,downloadFile(){throw new Error('WebAppMethodUnsupported');}},showToast(){},openPortalLink:url=>opened.push(url)};
    vm.createContext(context);vm.runInContext(code,context);
    vm.runInContext("downloadPortalFile({url:'https://example.invalid/synthetic-letter',filename:'Synthetic Letter.docx'})",context);
    expect(opened).toEqual(['https://example.invalid/synthetic-letter']);
  }
});
