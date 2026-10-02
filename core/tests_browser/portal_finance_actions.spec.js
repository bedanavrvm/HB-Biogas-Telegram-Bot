'use strict';
const fs = require('node:fs');
const path = require('node:path');
const {test, expect} = require('playwright/test');
const asset = name => path.resolve(__dirname, '../static/miniapp', name);
async function styles(page) {
  await page.addScriptTag({path:asset('portal_helpers.js')});
  for (const file of ['base.css', 'components.css', 'workflow_standard.css', 'portal.css']) await page.addStyleTag({path: asset(file)});
  await page.addScriptTag({path: asset('vendor-lucide-1.44.0.min.js')});
}
for (const width of [320, 360, 390, 430, 768, 1280]) {
  test(`document actions align at ${width}px`, async ({page}, info) => {
    await page.setViewportSize({width,height:850});
    await page.setContent('<body class="workflow-standard portal-app"><main id="content"><div id="history-list"></div></main></body>');
    await styles(page);
    const source = fs.readFileSync(asset('portal.js'), 'utf8');
    const renderer = source.slice(source.indexOf('  function physicalSignoffMarkup('), source.indexOf('  async function loadHistory('));
    await page.addScriptTag({content: `const el=id=>document.getElementById(id); const escapeHtml=value=>String(value||''); const fmtDateTime=value=>value; ${renderer}
      renderDocumentHistory([{id:'synthetic-document',order_number:104,fulfillment_partner:'HB',row_count:12,version:1,
      generated_at:'02-Oct-2026 10:15',generated_by:'Synthetic Officer',sync_status:'succeeded',download_url:'/synthetic/workbook',
      physical_signoff:{id:'synthetic-scan',status:'signed_approved',scan_filename:'Synthetic-signed-order-with-long-filename-104.pdf',preview_url:'/synthetic/scan',drive_url:'/synthetic/drive',can_replace:true}}], 'orders'); lucide.createIcons();`});
    for (const dark of [false,true]) {
      await page.evaluate(dark=>{
        document.documentElement.dataset.miniappColorScheme=dark?'dark':'light';
        for(const [key,value] of Object.entries(dark?{bg_color:'#17171e',secondary_bg_color:'#20202c',text_color:'#ffffff',hint_color:'#a8a8b3'}:{bg_color:'#f5f7f8',secondary_bg_color:'#ffffff',text_color:'#17212b',hint_color:'#6d7a86'})) document.documentElement.style.setProperty('--tg-theme-'+key.replaceAll('_','-'),value);
      },dark);
      await expect.poll(()=>page.locator('.history-document-actions .miniapp-icon-button').first().evaluate(node=>getComputedStyle(node).backgroundColor)).toBe(dark?'rgb(32, 32, 44)':'rgb(255, 255, 255)');
      const geometry = await page.locator('.physical-signoff-approved .miniapp-icon-button').evaluateAll(nodes=>nodes.map(node=>({y:node.getBoundingClientRect().y,width:node.getBoundingClientRect().width,icon:node.querySelector('svg').getBoundingClientRect().width})));
      expect(geometry).toHaveLength(2);
      const signedRow = await page.locator('.physical-signoff-approved').boundingBox();
      expect(geometry[0].y).toBeLessThan(signedRow.y + 28);
      expect(Math.abs(geometry[0].y-geometry[1].y)).toBeLessThan(1);
      geometry.forEach(box=>{expect(box.width).toBe(44);expect(box.icon).toBe(20);});
      expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
      await expect(page.getByRole('button',{name:'Preview workbook',exact:true})).toBeVisible();
      await page.screenshot({path:info.outputPath(`history-${width}-${dark?'dark':'light'}.png`)});
    }
  });
}

test('delivery previews preserve the parent dialog and Cash choices', async ({page}, info) => {
  await page.setViewportSize({width:390,height:844});
  await page.route('http://127.0.0.1:8007/**', route=>route.fulfill({contentType:'text/html',body:'<body></body>'}));
  await page.goto('http://127.0.0.1:8007/portal/s/payments/');
  const template=fs.readFileSync(path.resolve(__dirname,'../templates/portal/portal.html'),'utf8');
  const dialogs=template.slice(template.indexOf('  <dialog id="payment-receipt-dialog"'),template.indexOf('  <dialog id="payment-submit-confirm"'));
  await page.setContent(`<body class="workflow-standard portal-app"><main id="content"><div id="portal-screen" data-screen="payments"><div id="payments-batches"></div><div id="payments-receipts-list"></div></div></main>${dialogs}</body>`);
  await styles(page);
  await page.addScriptTag({path:asset('secure_media_viewer.js')});
  await page.addScriptTag({path:asset('portal_payments.js')});
  await page.evaluate(async()=>{
    const receipt={id:'delivery-1',status:'open',counts:{matched:1,review:1},items:[
      {id:'invoice-1',invoice_no:'INV-101',farmer_id:'case-1',applicant_name:'Synthetic Applicant With A Long Name',status:'matched',preview_url:'/synthetic/preview/'},
      {id:'invoice-2',invoice_no:'INV-102',status:'review',reason:'National ID needs review',preview_url:'/synthetic/preview/'}]};
    window.SecureMediaViewer.fetchAuthorizedBlob=async()=>new Blob(['<html>Only synthetic invoice evidence</html>'],{type:'text/html'});
    PortalMiniAppPayments.init({el:id=>document.getElementById(id),escapeHtml:value=>String(value??''),state:{capabilities:new Set(['portal.payment.prepare'])},showToast(){},
      apiFetch:async url=>({ok:true,data:{ok:true,...(url.includes('/invoice-receipts/delivery-1/')?{receipt_batch:receipt}:url.includes('/invoice-receipts/')?{batches:[receipt]}:{batches:[]})}})});
    await PortalMiniAppPayments.load();
  });
  await page.locator('.payment-open-receipt').click();
  await expect(page.locator('.payment-receipt-invoice-preview')).toHaveCount(2);
  const cash=page.locator('[data-payment-receipt-dialog-cash]');
  await cash.click();
  await expect(cash).toHaveAttribute('aria-pressed','true');
  await page.screenshot({path:info.outputPath('delivery-390.png')});
  await page.locator('.payment-receipt-invoice-preview').first().click();
  await expect(page.locator('#payment-receipt-preview')).toBeVisible();
  await expect(page.locator('#payment-receipt-dialog')).toHaveAttribute('open','');
  await page.locator('#payment-receipt-preview-close').click();
  await expect(page.locator('#payment-receipt-preview')).not.toBeVisible();
  await expect(cash).toHaveAttribute('aria-pressed','true');
  await page.locator('.payment-receipt-invoice-preview').last().click();
  await page.goBack();
  await expect(page.locator('#payment-receipt-preview')).not.toBeVisible();
  await expect(page.locator('#payment-receipt-dialog')).toBeVisible();
});

test('duplicate selection can be deleted without first applying the duplicate filter', async ({page}, info)=>{
  await page.setViewportSize({width:320,height:850});
  const template=fs.readFileSync(path.resolve(__dirname,'../templates/portal/portal.html'),'utf8');
  const toolbar=template.slice(template.indexOf('    <div class="batch-panel portal-initially-hidden" id="invoice-bulk-toolbar"'),template.indexOf('    <div id="invoice-pool-list"'));
  await page.setContent(`<body class="workflow-standard portal-app"><main id="content"><section id="portal-screen" data-screen="invoices" data-invoice-view="inbox"><div id="invoice-pool-summary"></div>${toolbar}<div id="invoice-pool-list"></div><div id="pg-invoices"></div></section></main></body>`);
  await styles(page);
  await page.addScriptTag({path:asset('portal_invoices.js')});
  await page.evaluate(async()=>{
    let rows=['original','copy'].map(id=>({id,revision:9,status:'unmatched',invoice_no:'INV-SYNTHETIC',customer_name:'Training Applicant',batch:{}}));
    let pending=0;
    window.__invoiceRequests=[];
    PortalMiniAppInvoices.init({state:{capabilities:new Set(['portal.invoice.view','portal.invoice.write'])},showToast(){},apiFetch:async(path,options={})=>{
      const body=options.body?JSON.parse(options.body):{};window.__invoiceRequests.push({path,body});
      if(path.includes('/cleanup/')) {if(body.retry)pending=0;return {ok:true,data:{ok:true,pending_count:pending}};}
      if(path.includes('/bulk-action/')) {rows=rows.filter(row=>!body.invoice_ids.includes(row.id));pending=1;return {ok:true,data:{ok:true,changed_count:1,skipped_count:0}};}
      return {ok:true,data:{ok:true,invoices:rows,summary:{invoice_count:rows.length},duplicate_ids:['copy'],pagination:{page:1,pages:1}}};
    }});
    await PortalMiniAppInvoices.load();
  });
  await page.locator('#invoice-select-all-duplicates').click();
  await expect(page.locator('#invoice-selected-count')).toHaveText('1 selected');
  await expect(page.locator('#invoice-bulk-restore')).toBeHidden();
  await page.locator('#invoice-bulk-delete').click();
  await expect(page.getByRole('dialog')).toContainText('This cannot be undone.');
  await page.locator('[data-confirm-yes]').click();
  await expect(page.locator('.invoice-pool-card')).toHaveCount(1);
  expect(await page.evaluate(()=>window.__invoiceRequests.find(row=>row.path.includes('/bulk-action/')).body)).toMatchObject({action:'delete',invoice_ids:['copy'],revisions:{copy:9}});
  await expect(page.locator('#invoice-retry-cleanup')).toBeVisible();
  await page.screenshot({path:info.outputPath('invoice-actions-320.png')});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.locator('#invoice-retry-cleanup').click();
  await expect(page.locator('#invoice-retry-cleanup')).toBeHidden();
});
