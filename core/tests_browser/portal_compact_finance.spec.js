'use strict';
const fs = require('node:fs');
const path = require('node:path');
const {test, expect} = require('playwright/test');
const {mountPortalShell} = require('./fixtures/portal_shell');
const asset = name => path.resolve(__dirname, '../static/miniapp', name);
const template = fs.readFileSync(path.resolve(__dirname, '../templates/portal/portal.html'), 'utf8');
const clean = html => html.replace(/{%[^]*?%}/g, '').replace(/{{[^]*?}}/g, '');
const historyStart = template.indexOf('  <section id="page-history"');
const historyHtml = clean(template.slice(historyStart, template.indexOf('  {% endif %}', historyStart)));
const detailStart = template.indexOf('    <section id="payments-detail"');
const detailEnd = template.indexOf('    </section>', template.indexOf('<div id="payments-primary-action"', detailStart));
const detailHtml = clean(template.slice(detailStart, detailEnd + '    </section>'.length));

async function setTheme(page, dark) {
  await page.evaluate(dark => {
    document.documentElement.dataset.miniappColorScheme = dark ? 'dark' : 'light';
    const colors = dark ? {bg_color:'#17171e',secondary_bg_color:'#20202c',text_color:'#ffffff',hint_color:'#a8a8b3',link_color:'#7dbae8'}
      : {bg_color:'#f5f7f8',secondary_bg_color:'#ffffff',text_color:'#17212b',hint_color:'#6d7a86',link_color:'#0f766e'};
    for (const [key, value] of Object.entries(colors)) document.documentElement.style.setProperty('--tg-theme-' + key.replaceAll('_','-'), value);
  }, dark);
  await expect(page.locator('#content')).toHaveCSS('background-color', dark ? 'rgb(23, 23, 30)' : 'rgb(245, 247, 248)');
  // Wait for the shared button colour transition; screenshots must not capture
  // its grey intermediate frame when changing the synthetic Telegram theme.
  const icon = page.locator('#content .miniapp-icon-button:visible').first();
  if (await icon.count()) await expect(icon).toHaveCSS('background-color', dark ? 'rgb(32, 32, 44)' : 'rgb(255, 255, 255)');
}

async function expectAlignedHeading(page, heading, title, controls) {
  const box = await page.locator(heading).first().boundingBox();
  const text = await page.locator(title).first().boundingBox();
  const actions = await page.locator(controls).first().boundingBox();
  expect(text.x).toBeCloseTo(box.x, 0);
  expect(text.x + text.width).toBeLessThanOrEqual(actions.x);
  expect(Math.abs((text.y + text.height / 2) - (actions.y + actions.height / 2))).toBeLessThan(2);
  expect(actions.x + actions.width).toBeCloseTo(box.x + box.width, 0);
}

async function mountHistory(page) {
  await mountPortalShell(page, `<div id="portal-screen" data-screen="history">${historyHtml}</div>`);
  const source = fs.readFileSync(asset('portal.js'), 'utf8');
  const renderer = source.slice(source.indexOf('  function physicalSignoffMarkup('), source.indexOf('  async function loadHistory('));
  await page.addScriptTag({content: `const el=id=>document.getElementById(id); const escapeHtml=value=>String(value??'').replaceAll('&','&amp;').replaceAll('<','&lt;'); const fmtDateTime=value=>value; ${renderer}
    renderDocumentHistory([{id:'training-order',order_number:'HB-104',row_count:12,version:1,generated_at:'06-Oct-2026 10:15',generated_by:'Training Officer',sync_status:'succeeded',download_url:'/synthetic/workbook',physical_signoff:{id:'training-scan',status:'signed_approved',scan_filename:'Training-signed-order-with-a-long-filename-104.pdf',preview_url:'/synthetic/scan',drive_url:'/synthetic/drive',can_replace:true}},
    {id:'training-retry',order_number:'ECO-24',fulfillment_partner:'ECOCONSERVE',row_count:3,version:2,generated_at:'06-Oct-2026 11:15',sync_status:'retryable_failure',physical_signoff:{status:'awaiting_signed_scan'}}], 'orders');
    document.addEventListener('click', event => { const button = event.target.closest('.history-show-details,.history-show-replacement'); if (button) openDocumentHistoryPanel(button); });
    lucide.createIcons();`});
}

async function mountPayment(page) {
  await mountPortalShell(page, `<div id="portal-screen" data-screen="payments" data-payment-batch-id="training-batch">${detailHtml}</div>`);
  await page.addScriptTag({path:asset('portal_helpers.js')});
  await page.addScriptTag({path:asset('components.js')});
  await page.addScriptTag({path:asset('portal_payments.js')});
  await page.evaluate(async () => {
    window.__requests = [];
    window.__batch = {id:'training-batch',status:'draft',status_label:'Draft',revision:1,total_amount:'42000',counts:{total:1,pending:1},cases:[{farmer_id:'included',customer_name:'Training Existing Member',national_id:'99999990',invoice_number:'INV-90',balance_due:'42000',review:{decision:'pending'}}],activity:[]};
    const result = (id, selectable, reason='') => ({farmer_id:id,customer_name:`Training Applicant ${id}`,national_id:'99999999',invoice_number:'INV-101',selectable,unavailable_reason:reason,row:{hb_invoice_amount:'42000'}});
    PortalMiniAppPayments.init({el:id=>document.getElementById(id),escapeHtml:value=>String(value??''),state:{capabilities:new Set(['portal.payment.prepare','portal.payment.view'])},showToast(){},setButtonLoading(){},apiFetch:async(url, options={})=>{
      window.__requests.push({url,body:options.body && JSON.parse(options.body)});
      if(url.includes('/candidates/')) {
        const params=new URLSearchParams(url.split('?')[1]);
        const search=params.get('search');
        if(search==='slow') await new Promise(resolve=>setTimeout(resolve,700));
        if(search==='slow-failure') { await new Promise(resolve=>setTimeout(resolve,700)); throw new Error('Old search failed'); }
        if(search==='failure') throw new Error('Current search failed');
        const results=search ? [result(search,true)] : params.get('page')==='2' ? [result('next',true)] : [result('ready',true),result('unmatched',false,'No matched invoice'),result('paid',false,'Already paid'),result('included',false,'Already in this payment')];
        return {ok:true,data:{ok:true,results,pagination:{page:Number(params.get('page')),pages:search?1:2,total:search?1:21}}};
      }
      if(options.method==='POST' && url.endsWith('/cases/')) {
        if(window.__rejectAdd) { window.__rejectAdd=false; return {ok:false,data:{ok:false,error:'Invoice changed. Refresh and review.'}}; }
        window.__batch.revision++;
        return {ok:true,data:{ok:true,batch:window.__batch}};
      }
      if(url.includes('/batches/?')) return {ok:true,data:{ok:true,batches:[]}};
      return {ok:true,data:{ok:true,batch:window.__batch}};
    }});
    await PortalMiniAppPayments.load();
  });
}

async function mountInvoices(page) {
  await mountPortalShell(page, '<div id="portal-screen" data-screen="invoices" data-invoice-view="inbox"><section id="page-invoices" class="page active"><header><h1>Invoices</h1></header><div id="invoice-pool-list" class="farmer-list"></div><div id="pg-invoices"></div></section></div>');
  await page.addScriptTag({path:asset('portal_helpers.js')});
  await page.addScriptTag({path:asset('portal_invoices.js')});
  await page.evaluate(async()=>{
    PortalMiniAppInvoices.init({state:{capabilities:new Set(['portal.invoice.view','portal.invoice.write'])},showToast(){},apiFetch:async()=>({ok:true,data:{ok:true,invoices:[
      {id:'training-matched',status:'matched',invoice_no:'10116',customer_name:'Training Applicant With A Longer Full Name',customer_id:'99999991',matched_order_number:'HB-100'},
      {id:'training-duplicate',status:'unmatched',invoice_no:'10117',customer_name:'Training Applicant Two',customer_id:'99999992',customer_phone:'0700000092',duplicate_count:2},
      {id:'training-ambiguous',status:'ambiguous',invoice_no:'10118',customer_name:'Training Applicant Three',customer_id:'99999993'},
    ],pagination:{page:1,pages:1}}})});
    await PortalMiniAppInvoices.load();
  });
  await page.evaluate(()=>lucide.createIcons());
}

for (const width of [320,360,390,430,768,1280]) {
  test(`compact finance screens at ${width}px`, async ({page}, info)=>{
    await page.setViewportSize({width,height:850});
    await mountHistory(page);
    await expect(page.locator('.history-document-card').first()).toBeVisible();
    const card=await page.locator('.history-document-card').first().boundingBox();
    expect(card.height).toBeLessThan(155);
    await expect(page.locator('.history-document-card').first()).toHaveCSS('padding','8px');
    await expect(page.locator('.physical-signoff-muted span')).toHaveCSS('font-size','12px');
    await expectAlignedHeading(page,'.history-document-header','.history-document-title','.history-document-header .history-document-actions');
    await expect(page.locator('.physical-signoff-upload')).toBeHidden();
    await expect(page.locator('.history-document-details').first()).toBeHidden();
    const tabs=await page.locator('.history-tabs').boundingBox(), filter=await page.locator('#history-filter-open').boundingBox();
    expect(Math.abs(tabs.y-filter.y)).toBeLessThan(2);
    await page.getByLabel('More document actions').first().click();
    await expect(page.getByRole('button',{name:'Replace signed scan'})).toBeVisible();
    await page.getByLabel('More document actions').first().click();
    for(const dark of [false,true]) {
      await setTheme(page, dark);
      expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
      await page.screenshot({path:info.outputPath(`documents-${width}-${dark?'dark':'light'}.png`),fullPage:true});
    }
    await mountPayment(page);
    await expect(page.locator('#payments-search-results')).toBeHidden();
    const search=await page.locator('#payments-search').boundingBox(), members=await page.locator('#payments-current-section').boundingBox();
    expect(search.y).toBeLessThan(members.y);
    await page.locator('#payments-search').focus();
    await expect(page.locator('.payment-candidate-checkbox:disabled')).toHaveCount(3);
    expect((await page.locator('.payment-candidate-checkbox:enabled').count())).toBe(1);
    await expect(page.locator('[data-payment-filter]')).toHaveCount(0);
    await expectAlignedHeading(page,'.payment-search-results-heading','#payments-result-count','#payments-search-close');
    for(const dark of [false,true]) {
      await setTheme(page, dark);
      expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
      await page.screenshot({path:info.outputPath(`payment-search-${width}-${dark?'dark':'light'}.png`),fullPage:true});
    }
    await mountInvoices(page);
    await expect(page.locator('.invoice-card-customer').first()).toContainText('Longer Full Name');
    await expect(page.locator('.invoice-card-alert').first()).toContainText('2 possible duplicate');
    await expect(page.getByText('Phone not provided')).toHaveCount(0);
    const hitbox=await page.locator('.invoice-card-select').first().boundingBox();
    expect(hitbox.width).toBe(44); expect(hitbox.height).toBeGreaterThanOrEqual(44);
    expect((await page.locator('.invoice-pool-card').first().boundingBox()).height).toBeLessThan(width < 900 ? 111 : 88);
    for(const dark of [false,true]) {
      await setTheme(page, dark);
      expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
      await page.screenshot({path:info.outputPath(`invoices-${width}-${dark?'dark':'light'}.png`),fullPage:true});
    }
  });
}

test('document secondary actions reveal only the chosen card and retain signed-copy details', async ({page}) => {
  await mountHistory(page);
  await page.getByLabel('More document actions').first().click();
  await page.getByRole('button', {name:'Details',exact:true}).first().click();
  await expect(page.locator('.history-document-details').first()).toBeVisible();
  await expect(page.locator('.history-document-details').first()).toContainText('Training-signed-order-with-a-long-filename-104.pdf');
  await expect(page.locator('.history-document-details').nth(1)).toBeHidden();
  await page.getByLabel('More document actions').first().click();
  await page.getByRole('button', {name:'Replace signed scan'}).click();
  await expect(page.locator('.physical-signoff-upload')).toBeVisible();
  await expect(page.locator('.history-signed-scan')).toHaveAttribute('accept', 'application/pdf,image/jpeg,image/png');
  await expect(page.locator('.history-document-menu').first()).not.toHaveAttribute('open');
});

test('payment picker preserves selection and mode across pages, rejects stale results and closes cleanly', async({page})=>{
  await page.setViewportSize({width:390,height:844});
  await mountPayment(page);
  await page.locator('#payments-search').focus();
  await page.locator('.payment-candidate-checkbox:enabled').check();
  await page.locator('[data-payment-candidate-cash="ready"]').click();
  await page.getByRole('button',{name:'Next',exact:true}).click();
  await page.locator('.payment-candidate-checkbox:enabled').check();
  await expect(page.locator('#payments-selected-count')).toHaveText('2 selected');
  await page.getByRole('button',{name:'Previous',exact:true}).click();
  await expect(page.locator('[data-payment-candidate-cash="ready"]')).toHaveAttribute('aria-pressed','true');
  await page.locator('#payments-search-close').click();
  await expect(page.locator('#payments-search-results')).toBeHidden();
  await page.locator('#payments-search').fill('slow');
  await page.waitForFunction(()=>window.__requests.some(row=>row.url.includes('search=slow')));
  await page.locator('#payments-search').fill('fast');
  await expect(page.locator('.payment-candidate')).toContainText('Applicant fast');
  await page.waitForTimeout(800);
  await expect(page.locator('.payment-candidate')).toContainText('Applicant fast');
  await page.locator('#payments-search').fill('slow-failure');
  await page.waitForFunction(()=>window.__requests.some(row=>row.url.includes('search=slow-failure')));
  await page.locator('#payments-search').fill('fast');
  await expect(page.locator('.payment-candidate')).toContainText('Applicant fast');
  await page.waitForTimeout(800);
  await expect(page.locator('.payment-candidate')).toContainText('Applicant fast');
  await page.evaluate(()=>window.__rejectAdd=true);
  await page.locator('#payments-add-selected').click();
  await expect(page.locator('#payments-selected-count')).toHaveText('2 selected');
  await page.locator('#payments-add-selected').click();
  await expect(page.locator('#payments-search-results')).toBeHidden();
  expect(await page.evaluate(()=>window.__requests.filter(row=>row.body?.payment_modes).pop().body.payment_modes)).toEqual({ready:'CASH',next:'LOAN-JAWABU'});
  await expect(page.locator('#payments-search')).toBeVisible();
  await page.locator('#payments-search').fill('failure');
  await expect(page.locator('#payments-list')).toContainText('Current search failed');
  await page.locator('#payments-search').press('Escape');
  await expect(page.locator('#payments-search-results')).toBeHidden();
  await expect(page.locator('#payments-search')).toHaveValue('failure');
});
