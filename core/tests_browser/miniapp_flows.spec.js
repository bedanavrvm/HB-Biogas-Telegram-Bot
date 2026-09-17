'use strict';

const path = require('node:path');
const fs = require('node:fs');
const { test, expect } = require('playwright/test');

const root = path.resolve(__dirname, '..', '..');
const asset = (name) => path.join(root, 'core', 'static', 'miniapp', name);

async function loadUtilities(page) {
  await page.addScriptTag({ path: asset('utils.js') });
}

test('Portal case-card policy distinguishes work, inspection and unsupported queues',async({page})=>{
  const source=fs.readFileSync(asset('portal.js'),'utf8');
  const routing=source.match(/  function openQueueCase\([^]*?\n  \}/)[0];
  const mode=source.match(/  function reviewCardMode\([^]*?\n  \}/)[0];
  await page.setContent('<p>Portal case-card routing</p>');
  await page.addScriptTag({content:`
    window.calls=[];
    const state={filters:{reviewStage:'final'}};
    const portalFilters={rememberSelection:()=>{}};
    const openCurrentFarmerSheet=(farmer,mode)=>calls.push({kind:'action',id:farmer.id,mode});
    const caseHistoryUrl=(id,queue)=>'/portal/cases/'+id+'/?from='+queue;
    const navigateToUrl=url=>calls.push({kind:'history',url});
    const showToast=message=>calls.push({kind:'error',message});
    ${routing}\n${mode}
    window.openQueueCase=openQueueCase;
    window.reviewCardMode=reviewCardMode;
    window.routingState=state;
  `});
  for(const [queue,mode] of [['jbl','jbl_visit'],['credit','credit'],['final','final_review'],['deferred','deferred']]){
    await page.evaluate(({queue,mode})=>window.openQueueCase({id:'case-1'},queue,mode),{queue,mode});
    expect(await page.evaluate(()=>window.calls.at(-1))).toEqual({kind:'action',id:'case-1',mode});
  }
  for (const queue of ['all', 'my_visits', 'requisition']) {
    await page.evaluate(queue=>window.openQueueCase({id:'case-1'},queue,null),queue);
    expect(await page.evaluate(()=>window.calls.at(-1))).toEqual({kind:'history',url:'/portal/cases/case-1/?from='+queue});
  }
  await page.evaluate(()=>window.openQueueCase({id:'case-1'},'unknown',null));
  expect(await page.evaluate(()=>window.calls.at(-1).kind)).toBe('error');
  expect(await page.evaluate(()=>{window.routingState.filters.reviewStage='payment';return window.reviewCardMode({mode:'final_review'},'final');})).toBeNull();
  // Both server-fragment and client-rendered cards use this same tested policy.
  expect(source).toContain('openQueueCase({ id: card.dataset.farmerId }, queue, card.dataset.mode || null)');
  expect(source).toContain('openQueueCase(farmer, qKey, reviewCardMode(cfg, qKey))');
});

test('Staff activation remains readable in dark mode and follows Telegram theme changes',async({page},testInfo)=>{
  const source=fs.readFileSync(path.join(root,'core/templates/staff_telegram_activation.html'),'utf8');
  const html=source.replace(/\{%[^]*?%\}/g,'').replace(/<script src=[^]*?<\/script>/g,'').replace(/<link[^>]*>/g,'');
  await page.emulateMedia({colorScheme:'light'});
  await page.setViewportSize({width:390,height:740});
  await page.setContent(html.replace(/<script>[^]*?<\/script>/g,''));
  await page.addStyleTag({path:asset('base.css')});
  await page.evaluate(()=>{
    window.__themeEvents={};
    window.Telegram={WebApp:{ready:()=>{},expand:()=>{},colorScheme:'dark',themeParams:{},onEvent:(key,fn)=>window.__themeEvents[key]=fn}};
  });
  await loadUtilities(page);
  await page.addScriptTag({content:source.match(/<script>\s*\(function[^]*?<\/script>/)[0].replace(/<\/?script>/g,'').replace(/\{%[^]*?%\}/g,'/activation/')});
  await expect(page.locator('html')).toHaveAttribute('data-miniapp-color-scheme','dark');
  await page.locator('#activation-code').fill('12345678');
  const colours=await page.locator('.activation').evaluate(el=>({background:getComputedStyle(el).backgroundColor,text:getComputedStyle(el).color}));
  expect(colours.background).not.toBe('rgb(255, 255, 255)');
  expect(colours.text).toBe('rgb(255, 255, 255)');
  await page.evaluate(()=>{const status=document.getElementById('activation-status');status.hidden=false;status.className='activation-status error';status.textContent='This code has expired. Ask your administrator for a new code.';});
  await page.screenshot({path:testInfo.outputPath('activation-dark.png'),fullPage:true});
  await page.evaluate(()=>{window.Telegram.WebApp.colorScheme='light';window.__themeEvents.themeChanged();});
  await expect(page.locator('html')).toHaveAttribute('data-miniapp-color-scheme','light');
  await page.screenshot({path:testInfo.outputPath('activation-light.png'),fullPage:true});
});

test('Portal date labels use readable full-year dates',async({page})=>{
  await page.setContent('<p>Portal dates</p>');
  await loadUtilities(page);
  await page.addScriptTag({path:asset('portal_helpers.js')});
  expect(await page.evaluate(()=>window.PortalMiniAppHelpers.fmtDate('2026-05-05'))).toBe('05-05-2026');
  expect(await page.evaluate(()=>window.PortalMiniAppHelpers.fmtDateTime('2026-09-17T07:30:00Z'))).toBe('17-09-2026 10:30');
});

test('Order preview exposes and highlights every blocked case reason',async({page})=>{
  const source=fs.readFileSync(asset('portal_requisitions.js'),'utf8');
  const render=source.match(/  function openRequisitionPreview\([^]*?\n  \}/)[0];
  const ids=['requisition-preview-overlay','requisition-preview-sub','requisition-preview-summary','requisition-preview-warnings','requisition-preview-list','requisition-preview-confirm','requisition-preview-cancel','requisition-preview-progress','requisition-finalize-note'];
  await page.setContent(`<body class="portal-app">${ids.map(id=>id.includes('confirm')||id.includes('cancel')?`<button id="${id}"></button>`:`<div id="${id}"></div>`).join('')}</body>`);
  for(const file of ['base.css','portal.css']) await page.addStyleTag({path:asset(file)});
  await page.addScriptTag({content:`const el=id=>document.getElementById(id);const deps={fmtDate:x=>x,escapeHtml:x=>String(x).replaceAll('<','&lt;'),summaryGrid:()=>'',renderWarnings:()=>{}};const renderPrintableRequisition=()=>'<p>Document preview</p>';${render};window.openPreview=openRequisitionPreview;`});
  await page.evaluate(()=>window.openPreview({order_number:'1',blocked_count:1,ready_count:0,blocked:[{farmer:{id:'case-1',customer_name:'Test farmer'},missing:['Enter the customer account number.','Enter the village.']}]}));
  await expect(page.locator('.requisition-blocked-case')).toContainText('Test farmer');
  await expect(page.locator('.requisition-blocked-case')).toContainText('Enter the customer account number.');
  await expect(page.locator('.requisition-blocked-case')).toContainText('Enter the village.');
  await expect(page.locator('#requisition-preview-confirm')).toBeDisabled();
  expect(await page.locator('.requisition-blocker-list').evaluate(el=>getComputedStyle(el).borderTopColor)).toBe('rgb(239, 68, 68)');
});

test('Order review scrolls the entire final row above its bottom actions',async({page},testInfo)=>{
  const source=fs.readFileSync(path.join(root,'core/templates/portal/portal.html'),'utf8');
  const start=source.indexOf('<div class="sheet-overlay" id="requisition-preview-overlay"');
  const html=source.slice(start,source.indexOf('<!-- Batch detail overlay -->',start));
  await page.setContent(`<body class="portal-app">${html}</body>`);
  for(const file of ['base.css','portal.css']) await page.addStyleTag({path:asset(file)});
  await page.evaluate(()=>{
    document.getElementById('requisition-preview-overlay').classList.add('open');
    document.getElementById('requisition-preview-list').innerHTML=`<article class="requisition-print-preview"><header><h3>Order review</h3></header><div class="requisition-print-scroll"><table><thead><tr><th>Customer</th><th>Village</th></tr></thead><tbody>${Array.from({length:40},(_,index)=>`<tr data-review-row="${index}"><td>Test farmer ${index}</td><td>Test village ${index}</td></tr>`).join('')}</tbody></table></div></article>`;
  });
  for(const height of [700,440]){
    await page.setViewportSize({width:390,height});
    await page.locator('[data-review-row="39"]').scrollIntoViewIfNeeded();
    const row=await page.locator('[data-review-row="39"]').boundingBox();
    const body=await page.locator('#requisition-preview-overlay .sheet-body').boundingBox();
    const footer=await page.locator('#requisition-preview-overlay .sheet-footer').boundingBox();
    expect(row.y+row.height).toBeLessThanOrEqual(body.y+body.height);
    expect(row.y).toBeGreaterThanOrEqual(body.y);
    expect(footer.y+footer.height).toBeLessThanOrEqual(height);
    await page.screenshot({path:testInfo.outputPath(`order-last-row-${height}.png`)});
  }
});

test('Order preview shows one Telegram main action with a browser fallback',async({page})=>{
  const render=fs.readFileSync(asset('portal_requisitions.js'),'utf8').match(/  function openRequisitionPreview\([^]*?\n  \}/)[0];
  const ids=['requisition-preview-sub','requisition-preview-summary','requisition-preview-warnings','requisition-preview-list','requisition-preview-confirm','requisition-preview-cancel','requisition-finalize-note'];
  await page.setContent(`<main id="content"><section id="portal-screen" data-screen="requisition"></section><div id="requisition-preview-overlay" class="sheet-overlay">${ids.map(id=>id.includes('confirm')||id.includes('cancel')?`<button id="${id}"></button>`:`<div id="${id}"></div>`).join('')}</div></main>`);
  await page.addScriptTag({content:`window.nativeVisible=false;window.finalClicks=0;window.Telegram={WebApp:{onEvent(){},MainButton:{show(){window.nativeVisible=true;},hide(){window.nativeVisible=false;},setText(){},onClick(handler){window.mainClick=handler;},offClick(){}}}};const el=id=>document.getElementById(id);const deps={tg:Telegram.WebApp,fmtDate:x=>x,escapeHtml:x=>String(x),summaryGrid:()=>'',renderWarnings:()=>{}};const renderPrintableRequisition=()=>'<p>Preview</p>';${render};window.openPreview=openRequisitionPreview;window.previewDeps=deps;document.getElementById('requisition-preview-confirm').onclick=()=>window.finalClicks++;`});
  await page.addScriptTag({path:asset('miniapp-nav.js')});
  await page.evaluate(()=>openPreview({order_number:'1',ready_count:1}));
  await expect(page.locator('#requisition-preview-confirm')).toBeHidden();
  await expect(page.locator('#requisition-preview-confirm')).toHaveAttribute('data-main-action-proxy','true');
  await expect.poll(()=>page.evaluate(()=>window.nativeVisible)).toBe(true);
  await page.evaluate(()=>window.mainClick());
  expect(await page.evaluate(()=>window.finalClicks)).toBe(1);
  await page.evaluate(()=>openPreview({order_number:'1',ready_count:1},{readOnly:true}));
  await expect.poll(()=>page.evaluate(()=>window.nativeVisible)).toBe(false);
  await page.evaluate(()=>{window.previewDeps.tg=null;openPreview({order_number:'2',ready_count:1});});
  await expect(page.locator('#requisition-preview-confirm')).toBeVisible();
});

test('Order failures display every customer issue and the field correction',async({page})=>{
  const handler=fs.readFileSync(asset('portal_requisitions.js'),'utf8').match(/  function showRequisitionError\([^]*?\n  \}/)[0];
  await page.setContent('<div id="requisition-preview-warnings"></div><button id="requisition-preview-confirm"></button><p id="requisition-finalize-note"></p>');
  await page.addScriptTag({content:`window.messages=[];const el=id=>document.getElementById(id);const deps={escapeHtml:x=>String(x).replaceAll('<','&lt;'),showToast:message=>window.messages.push(message)};${handler};window.showOrderFailure=showRequisitionError;`});
  await page.evaluate(()=>showOrderFailure({error:'Some information needs attention.',field_errors:{requisition_date:'Choose a valid date.'},blocked:[{farmer:{customer_name:'Test customer'},missing:['Enter the village.','Enter the constituency.']}]},'Try again.'));
  await expect(page.locator('[role="alert"]')).toContainText('Test customer: Enter the village.');
  await expect(page.locator('[role="alert"]')).toContainText('Test customer: Enter the constituency.');
  await expect(page.locator('[role="alert"]')).toContainText('Requisition date: Choose a valid date.');
  await expect(page.locator('#requisition-preview-confirm')).toBeDisabled();
  expect(await page.evaluate(()=>window.messages[0])).toBe('Requisition date: Choose a valid date.');
});

test('Workbook download click uses Telegram native download and browser fallback',async({page})=>{
  await page.setContent('<a id="requisition-workbook-download" href="https://miniapp.test/api/portal/requisition-download/signed-test/" data-filename="Order-1.xlsx">Download workbook</a>');
  await page.addScriptTag({path:asset('portal_requisitions.js')});
  await page.evaluate(()=>{
    window.downloads=[];window.browserLinks=[];window.messages=[];
    window.downloadTg={downloadFile:(options,callback)=>{window.downloads.push(options);callback(true);}};
    const downloadPortalFile=({url,filename})=>{
      if(typeof window.downloadTg.downloadFile==='function') return window.downloadTg.downloadFile({url,file_name:filename},accepted=>window.messages.push(accepted===false?'Download cancelled.':'Download started.'));
      window.browserLinks.push(url);
    };
    PortalMiniAppRequisitions.init({el:id=>document.getElementById(id),state:{capabilities:new Set()},tg:window.downloadTg,showToast:message=>window.messages.push(message),openPortalLink:url=>window.browserLinks.push(url),downloadPortalFile});
  });
  await page.locator('#requisition-workbook-download').click();
  expect(await page.evaluate(()=>window.downloads)).toEqual([{url:'https://miniapp.test/api/portal/requisition-download/signed-test/',file_name:'Order-1.xlsx'}]);
  expect(await page.evaluate(()=>window.browserLinks)).toHaveLength(0);
  await page.evaluate(()=>{window.downloadTg.downloadFile=(_options,callback)=>callback(false);});
  await page.locator('#requisition-workbook-download').click();
  expect(await page.evaluate(()=>window.messages.at(-1))).toContain('Download cancelled.');
  await page.evaluate(()=>{delete window.downloadTg.downloadFile;});
  await page.locator('#requisition-workbook-download').click();
  expect(await page.evaluate(()=>window.browserLinks)).toEqual(['https://miniapp.test/api/portal/requisition-download/signed-test/']);
});

test('Hidden main action can retry finalization and produces a working workbook control',async({page})=>{
  const source=fs.readFileSync(asset('portal_requisitions.js'),'utf8');
  const generate=source.match(/  async function generateRequisitionFromPreview\([^]*?\n  \}/)[0];
  const errorHandler=source.match(/  function showRequisitionError\([^]*?\n  \}/)[0];
  const ids=['requisition-preview-confirm','requisition-preview-summary','requisition-preview-warnings','requisition-preview-list','requisition-finalize-note','requisition-preview-sub','requisition-preview-cancel','batch-order-num','batch-req-date'];
  await page.setContent(ids.map(id=>id.includes('confirm')||id.includes('cancel')?`<button id="${id}"></button>`:`<input id="${id}">`).join(''));
  // Results are containers rather than form inputs.
  await page.evaluate(()=>['requisition-preview-summary','requisition-preview-warnings','requisition-preview-list'].forEach(id=>document.getElementById(id).outerHTML=`<div id="${id}"></div>`));
  await page.addScriptTag({content:`
    window.calls=[];window.messages=[];window.testState={pendingRequisitionPayload:{preview_token:'same-preview',finalize_request_id:'same-request'},selectedRequisitions:new Set(['case-1']),selectedRequisitionRevisions:new Map([['case-1',1]])};
    const state=()=>window.testState,el=id=>document.getElementById(id),csrfHeader=()=>({}),updateBatchPanel=()=>{},scheduleRequisitionDriveSync=async()=>{};
    const deps={tg:{MainButton:{setText(){},showProgress(){},hideProgress(){}}},escapeHtml:x=>String(x),fmtDate:x=>x,summaryGrid:()=>'',showToast:message=>window.messages.push(message),setButtonLoading(){},loadQueue(){},portalApi:{postJson:async(path,body)=>{window.calls.push({...body});return window.calls.length===1?{ok:false,data:{ok:false,error:'Ask IT to check the workbook template.'}}:{ok:true,data:{ok:true,filename:'Order-1.xlsx',download_url:'https://miniapp.test/signed-download/',batch:{order_number:'1',farmer_count:1,filename:'Order-1.xlsx'}}};}}};
    ${errorHandler}\n${generate};window.finalizePreview=generateRequisitionFromPreview;
    const button=el('requisition-preview-confirm');button.hidden=true;button.dataset.mainAction='Finalize Order 1';button.dataset.mainActionProxy='true';
  `});
  await page.evaluate(()=>finalizePreview());
  await expect(page.locator('#requisition-preview-confirm')).toBeEnabled();
  await expect(page.locator('#requisition-preview-confirm')).toBeHidden();
  await expect(page.locator('[role="alert"]')).toContainText('Ask IT to check the workbook template.');
  await page.evaluate(()=>finalizePreview());
  expect(await page.evaluate(()=>window.calls)).toEqual([{preview_token:'same-preview',client_request_id:'same-request'},{preview_token:'same-preview',client_request_id:'same-request'}]);
  await expect(page.locator('#requisition-workbook-download')).toHaveAttribute('href','https://miniapp.test/signed-download/');
  await expect(page.locator('#requisition-workbook-download')).toHaveAttribute('data-filename','Order-1.xlsx');
  expect(await page.evaluate(()=>window.testState.pendingRequisitionPayload)).toBeNull();
});

test('FarmUp final review row stays above the scrollbar and commit bar',async({page})=>{
  await page.setViewportSize({width:390,height:700});
  await page.setContent('<body class="portal-app"><main id="content" style="height:100dvh;overflow:auto"><div id="portal-screen" data-screen="farmup"><section id="page-farmup"><form id="portal-farmup-upload"></form><div id="portal-farmup-feedback"></div><section id="portal-farmup-review" class="portal-import-review" hidden></section><div id="portal-farmup-list"></div></section></div></main></body>');
  for(const name of ['base.css','portal.css','vendor-ag-grid-community-36.1.0.min.css','vendor-ag-grid-theme-quartz-36.1.0.min.css']) await page.addStyleTag({path:asset(name)});
  await page.addScriptTag({path:asset('vendor-ag-grid-community-36.1.0.min.js')});
  await page.evaluate(()=>{
    const batch={id:'test-batch',source_filename:'Test.csv',status:'pending_review',total_rows:35,review_needed:0,committed_count:0,version_number:1,is_current_version:false,mapping:{state:'auto_ready'},revision_token:'test'};
    const rows=Array.from({length:35},(_,index)=>({row_id:index+1,approved:false,disposition:'hold','Customer Name':`Test farmer ${index+1}`,'National ID':'12345678','Primary Phone':'254700000001','Application Action':'update_existing',County:'Embu','HBG Visit Date':'2026-05-01'}));
    window.PortalAppShell={hasCapability:()=>true,showToast:()=>{}};
    window.PortalMiniAppApi={apiFetch:async path=>({ok:true,data:path==='/farmup/'?{ok:true,batches:[batch]}:{ok:true,batch:{...batch,rows}}}),postJson:async()=>({ok:true,data:{ok:true,rows:[],counts:{}}})};
  });
  await page.addScriptTag({path:asset('portal_farmup.js')});
  await page.evaluate(()=>PortalMiniAppFarmUp.load());
  await page.locator('.farmup-open').click();
  for(const height of [700,440]){
    await page.setViewportSize({width:390,height});
    await page.locator('#farmup-grid').evaluate(grid=>grid.scrollIntoView({block:'start'}));
    expect((await page.locator('#farmup-grid').boundingBox()).height).toBeGreaterThanOrEqual(192);
    await page.locator('#farmup-grid .ag-grid-viewport').evaluate(viewport=>{viewport.scrollTop=viewport.scrollHeight;});
    const row=page.locator('#farmup-grid .ag-grid-scrolling-container .ag-row[row-index="34"]');
    await expect(row).toBeVisible();
    await expect.poll(async()=>{
      // Resizing recalculates the grid height asynchronously; keep scrolling
      // to the bottom until that layout and row virtualization have settled.
      await page.locator('#farmup-grid .ag-grid-viewport').evaluate(viewport=>{viewport.scrollTop=viewport.scrollHeight;});
      const last=await row.boundingBox();
      const scrollbar=await page.locator('#farmup-grid .ag-body-horizontal-scroll').boundingBox();
      const footer=await page.locator('.farmup-commit-bar').boundingBox();
      return {rowOverlap:Math.max(0,Math.round(last.y+last.height-scrollbar.y)),footerOverlap:Math.max(0,Math.round(scrollbar.y+scrollbar.height-footer.y))};
    }).toEqual({rowOverlap:0,footerOverlap:0});
  }
});

test('FarmUp confirms upload before review loading and keeps the uploaded filename',async({page})=>{
  await page.setContent(`<div id="portal-screen" data-screen="farmup"><form id="portal-farmup-upload"><input name="period" type="month" value="2026-09"><label class="invoice-upload-dropzone"><input name="file" type="file" data-farmup-file><span data-farmup-file-label>Tap to select CSV file</span></label><button type="submit">Upload CSV</button><p data-farmup-upload-status></p></form><div id="portal-farmup-feedback"></div><div id="portal-farmup-list"></div></div>`);
  await page.evaluate(()=>{
    window.PortalMiniAppApi={postForm:async()=>({ok:true,data:{ok:true,batch:{id:'uploaded'}}}),apiFetch:async()=>{throw new Error('Review unavailable');}};
    window.PortalAppShell={showToast:()=>{}};
  });
  await page.addScriptTag({path:asset('portal_farmup.js')});
  await page.locator('input[type="file"]').setInputFiles({name:'Farmers.csv',mimeType:'text/csv',buffer:Buffer.from('Name\nTest')});
  await expect(page.locator('[data-farmup-file-label]')).toHaveText('Selected: Farmers.csv');
  await page.locator('button[type="submit"]').click();
  await expect(page.locator('[data-farmup-file-label]')).toHaveText('Uploaded: Farmers.csv');
  await expect(page.locator('[data-farmup-upload-status]')).toContainText('uploaded successfully');
  await expect(page.locator('#portal-farmup-feedback')).toContainText('CSV uploaded successfully, but its review could not open');
  await expect(page.locator('input[type="month"]')).toHaveValue('2026-09');
  await page.locator('input[type="file"]').setInputFiles({name:'Updated.csv',mimeType:'text/csv',buffer:Buffer.from('Name\nTest')});
  await expect(page.locator('[data-farmup-file-label]')).toHaveText('Selected: Updated.csv');
});

test('Portal secondary actions use blue without changing primary or destructive colours', async ({page})=>{
  await page.setContent(`<body class="workflow-standard portal-app"><main id="content"><section id="page-farmup"><button class="btn btn-secondary">Refresh</button><button class="btn btn-primary">Upload</button></section><button class="miniapp-filter-trigger">Filters</button><button class="queue-refresh-button">Refresh queue</button><button class="btn-secondary danger">Delete</button></main><div class="sheet-overlay open jbl-visit-sheet"><button class="btn-secondary case360-toggle"><svg viewBox="0 0 24 24"><path stroke="currentColor" d="M1 1h10"/></svg>Case history</button><button class="jbl-media-remove">Remove</button><button class="primary">Save</button></div></body>`);
  for(const name of ['base.css','workflow_standard.css','portal.css']) await page.addStyleTag({path:asset(name)});
  for(const background of ['#ffffff','#17212b']){
    await page.evaluate(bg=>document.documentElement.style.setProperty('--tg-theme-bg-color',bg),background);
    await page.waitForTimeout(200); // Let existing button colour transitions settle.
    const colour=selector=>page.locator(selector).first().evaluate(el=>getComputedStyle(el).color);
    const blue=await colour('.queue-refresh-button');
    expect(await colour('#page-farmup .btn-secondary')).toBe(blue);
    expect(await colour('.miniapp-filter-trigger')).toBe(blue);
    expect(await colour('.case360-toggle')).toBe(blue);
    expect(await colour('.case360-toggle svg')).toBe(blue);
    expect(await colour('.btn-primary')).toBe(await colour('button.primary'));
    expect(await colour('.danger')).toBe(await colour('.jbl-media-remove'));
    expect(await colour('.danger')).not.toBe(blue);
    expect(await colour('.btn-primary')).not.toBe(blue);
  }
});

test('Portal refresh actions sit at the right content edge across screens', async ({page},testInfo)=>{
  const template=fs.readFileSync(path.join(root,'core/templates/portal/portal.html'),'utf8');
  const queueHeaders=template.match(/<header class="portal-queue-header">[^]*?<\/header>/g);
  await page.setContent(`<body class="workflow-standard portal-app"><main id="content" style="padding:12px"><div class="dashboard-intro"><div><h2>Overview</h2></div><button class="dashboard-refresh-button">Refresh</button></div>${queueHeaders.join('')}<section id="page-farmup"><div class="portal-import-history"><div class="portal-import-history-heading"><h2>Recent batches</h2><button>Refresh</button></div></div></section><section id="page-imports"><div class="portal-import-history"><div class="portal-import-history-heading"><h2>Recent imports</h2><button>Refresh</button></div></div></section></main></body>`);
  for(const name of ['base.css','workflow_standard.css','portal.css']) await page.addStyleTag({path:asset(name)});
  for(const width of [390,1280]){
    await page.setViewportSize({width,height:900});
    const positions=await page.locator('.portal-queue-header, .dashboard-intro, .portal-import-history-heading').evaluateAll(headers=>headers.map(header=>{
      const bounds=header.getBoundingClientRect();const button=header.querySelector('button').getBoundingClientRect();
      return {gap:bounds.right-button.right,top:button.top-bounds.top,width:bounds.width};
    }));
    const contentWidth=await page.locator('#content').evaluate(el=>el.clientWidth-24);
    for(const position of positions){expect(Math.abs(position.gap)).toBeLessThan(2);expect(position.top).toBeLessThan(10);expect(Math.abs(position.width-contentWidth)).toBeLessThan(2);}
    await page.screenshot({path:testInfo.outputPath(`refresh-${width}.png`),fullPage:true});
  }
});

test('Portal camera uses full height with an edge-to-edge preview on mobile and desktop', async ({page},testInfo)=>{
  const template=fs.readFileSync(path.join(root,'core/templates/portal/portal.html'),'utf8');
  const start=template.indexOf('<div class="sheet-overlay jbl-camera-overlay"');
  const end=template.indexOf('</section>',start)+10;
  await page.setContent(`<body class="portal-app">${template.slice(start,end)}</div></body>`);
  await page.addStyleTag({path:asset('base.css')});
  await page.addStyleTag({path:asset('portal.css')});
  await page.locator('#jbl-camera-overlay').evaluate(el=>el.classList.add('open'));
  for(const [label,width,height] of [['mobile',390,800],['desktop',1280,900],['landscape',700,390]]){
    await page.setViewportSize({width,height});
    const bounds=await page.locator('.jbl-camera-sheet').boundingBox();
    expect(Math.abs(bounds.height-height)).toBeLessThan(2);
    expect(bounds.width).toBeLessThanOrEqual(620);
    expect(Math.abs(bounds.y+bounds.height-height)).toBeLessThan(2);
    await expect(page.locator('#jbl-camera-done')).toBeVisible();
    expect(await page.locator('#jbl-camera-video').evaluate(video=>getComputedStyle(video).objectFit)).toBe('cover');
    await page.screenshot({path:testInfo.outputPath(`camera-${label}.png`),fullPage:true});
  }
});

test('All Cases checkbox filters apply automatically, combine and clear cleanly', async ({page})=>{
  const template=fs.readFileSync(path.join(root,'core/templates/portal/partials/queue_tools.html'),'utf8')
    .replace(/\{% else %\}[^]*?\{% endif %\}/g,'').replace(/\{%[^]*?%\}/g,'').replace(/\{\{ queue_key \}\}/g,'all').replace(/\{\{[^]*?\}\}/g,'Cases');
  await page.setContent(`<body class="portal-app">${template}</body>`);
  await page.addStyleTag({path:asset('components.css')});
  await page.addScriptTag({path:asset('components.js')});
  await page.addScriptTag({path:asset('portal_queues.js')});
  await page.addScriptTag({path:asset('portal_filters.js')});
  await page.evaluate(()=>{
    window.filterState={activePage:'all',pages:{all:1},searches:{},filtersByQueue:{},metaCounties:['Kiambu','Nakuru','Embu','Nyeri'],metaBranches:['Corporate']};
    window.filterLoads=0;
    window.PortalMiniAppFilters.init({state:window.filterState,queueConfig:{all:{}},loadQueue:()=>{window.filterLoads++;}});
    window.PortalMiniAppFilters.setupQueueTools('all');
  });
  await page.locator('[data-portal-filter-trigger]').click();
  await page.locator('input[name="status"][value="deferred"]').check();
  await page.locator('input[name="status"][value="credit"]').check();
  await page.locator('input[name="county"][value="Kiambu"]').check();
  await expect.poll(()=>page.evaluate(()=>window.filterLoads)).toBeGreaterThan(0);
  expect(await page.evaluate(()=>window.filterState.filtersByQueue.all.status)).toEqual(['credit','deferred']);
  expect(await page.evaluate(()=>window.PortalMiniAppQueues.queueUrl('all',1,window.filterState))).toContain('status=deferred');
  expect(await page.evaluate(()=>window.PortalMiniAppQueues.queueUrl('all',1,window.filterState))).toContain('status=credit');
  await expect(page.locator('[data-portal-filter-overlay]')).toBeVisible();
  await expect(page.locator('.portal-filter-help')).toHaveCount(0);
  await page.setViewportSize({width:390,height:700});
  for(const file of ['base.css','portal.css']) await page.addStyleTag({path:asset(file)});
  const boxes=await page.locator('[data-portal-filter-options="county"] label').evaluateAll(labels=>labels.map(label=>({top:label.offsetTop,height:label.getBoundingClientRect().height})));
  expect(boxes.filter(box=>box.top===boxes[0].top).length).toBe(2);
  expect(Math.max(...boxes.map(box=>box.height))).toBeLessThan(40);
  await page.evaluate(()=>window.PortalMiniAppFilters.updateResultCount('all',17));
  await expect(page.locator('[data-portal-matching-count]')).toHaveText('17 matching cases');
  await page.locator('[data-portal-filter-reset]').click();
  expect(await page.evaluate(()=>window.filterState.filtersByQueue.all.status)).toEqual([]);
});

test('Portal filter sheet matches compact mobile controls with one search clear', async ({page}, testInfo)=>{
  const template=fs.readFileSync(path.join(root,'core/templates/portal/partials/queue_tools.html'),'utf8').replace(/\{% if queue_key == 'all' %\}[^]*?\{% endif %\}/g,'').replace(/\{%[^]*?%\}/g,'').replace(/\{\{ queue_key \}\}/g,'credit').replace(/\{\{[^]*?\}\}/g,'Cases');
  await page.setViewportSize({width:390,height:700});
  await page.setContent(`<body class="portal-app"><main id="content"><div style="padding:12px">${template}</div></main></body>`);
  for(const file of ['base.css','components.css','portal.css']) await page.addStyleTag({path:asset(file)});
  await loadUtilities(page);
  await page.addScriptTag({path:asset('components.js')});
  await page.addScriptTag({path:asset('portal_filters.js')});
  await page.evaluate(()=>{
    window.PortalMiniAppFilters.init({state:{activePage:'credit',pages:{credit:1},searches:{},filtersByQueue:{},metaCounties:['Kiambu'],metaBranches:['Corporate']},queueConfig:{credit:{}},loadQueue:()=>{}});
    window.PortalMiniAppFilters.setupQueueTools('credit');
  });
  await page.locator('[data-portal-queue-search]').fill('Sample');
  await expect(page.locator('[data-portal-search-clear]')).toBeVisible();
  // Chromium does not expose native search pseudo-element styles via getComputedStyle.
  expect(await page.evaluate(()=>Array.from(document.styleSheets).flatMap(sheet=>Array.from(sheet.cssRules)).some(rule=>rule.selectorText?.includes('body.portal-app input[type="search"]::-webkit-search-cancel-button') && rule.style.appearance==='none'))).toBe(true);
  await page.locator('[data-portal-search-clear]').click();
  await expect(page.locator('[data-portal-queue-search]')).toHaveValue('');
  await expect(page.locator('[data-portal-search-clear]')).toBeHidden();
  await page.locator('[data-portal-filter-trigger]').click();
  await expect(page.locator('[data-portal-filter-sheet]')).toBeVisible();
  expect(await page.locator('[data-portal-filter-sheet]').evaluate(el=>el.scrollWidth<=el.clientWidth)).toBe(true);
  await page.screenshot({path:testInfo.outputPath('portal-filters-mobile.png'),fullPage:true});
  await page.locator('[data-miniapp-sheet-close]').first().click();
  await expect(page.locator('[data-portal-filter-overlay]')).toBeHidden();
});

test('Invoice record stays compact and editable on a 360px mobile viewport', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 360, height: 740 });
  await page.setContent(`<!doctype html><body class="workflow-standard portal-app">
    <main id="content"><div id="portal-screen" data-screen="invoices" data-invoice-view="detail" data-invoice-id="invoice-1">
      <section id="invoice-detail-page"></section>
    </div></main>
    <div id="media-viewer-overlay"><button id="media-viewer-close"></button><div id="media-viewer-content"></div></div>
  </body>`);
  for (const file of ['base.css', 'components.css', 'workflow_standard.css', 'portal.css']) {
    await page.addStyleTag({ path: asset(file) });
  }
  await page.addScriptTag({ path: asset('portal_invoices.js') });
  await page.evaluate(() => {
    const invoice = {
      id: 'invoice-1', revision: 4, status: 'matched', invoice_no: '10031',
      invoice_date: '2026-09-16', customer_name: 'JOHN MAINA NDIRANGU',
      customer_id: '', customer_phone: '254710825661', invoice_amount: '54000',
      total_after_discount: '49500', discount: '4500', payment: '5000',
      balance_due: '44500', calculated_balance_due: '44500',
      balance_due_difference: '0', balance_due_check: 'OK',
      balance_due_check_basis: 'total_after_discount_minus_payment', page: 1,
      matched_order_number: '101', matched_farmer_name: 'JOHN MAINA NDIRANGU',
      identity: {
        status_label: 'Matched', discrepancy_codes: ['national_id_missing'],
        match_eligibility: { eligible: true },
        lead_identity: { name: 'JOHN MAINA NDIRANGU', national_id: '7192741' },
        applicant_identity: { name: 'JOHN MAINA NDIRANGU', national_id: '7192741' },
        invoice_identity: { name: 'JOHN MAINA NDIRANGU', national_id: '' },
      },
    };
    window.PortalMiniAppInvoices.init({
      el: id => document.getElementById(id),
      escapeHtml: value => String(value ?? ''),
      fmtDate: value => value === '2026-09-16' ? '16-09-2026' : String(value || '-'),
      state: { capabilities: new Set(['portal.invoice.write']) },
      apiFetch: async () => ({
        ok: true,
        data: {
          ok: true, invoice, batch: { original_filename: 'invoice-10031.pdf' },
          events: [{ action: 'parsed', actor: 'Operations', created_at: '2026-09-16' }],
          duplicates: [], source_pdf_url: 'https://miniapp.test/invoice.pdf',
        },
      }),
      portalApi: { postJson: async () => ({ ok: true, data: { ok: true } }) },
      showToast() {}, setButtonLoading() {}, getCookie() { return ''; },
    });
    return window.PortalMiniAppInvoices.load(1);
  });

  await expect(page.locator('.invoice-record-summary')).toBeVisible();
  await expect(page.locator('.invoice-financial-strip')).toContainText('KES 54,000');
  await expect(page.locator('.invoice-parsed-grid')).toContainText('National ID');
  await expect(page.locator('.invoice-parsed-grid')).toContainText('Check basis');
  await expect(page.locator('.invoice-identity-comparison')).toBeVisible();
  expect(await page.locator('#invoice-detail-page').evaluate(node => node.scrollWidth <= node.clientWidth)).toBe(true);

  await page.locator('.invoice-parsed-edit-toggle').click();
  await expect(page.locator('.invoice-parsed-edit-form')).toBeVisible();
  await expect(page.locator('.invoice-parsed-grid')).toBeHidden();
  await page.locator('input[name="customer_id"]').fill('7192741');
  await expect(page.locator('textarea[name="correction_reason"]')).toBeVisible();
  expect(await page.locator('.invoice-parsed-edit-form').evaluate(node => node.scrollWidth <= node.clientWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath('invoice-record-mobile.png'), fullPage: true });
});

test('Import History keeps compact mobile cards and working review navigation', async ({page}, testInfo) => {
  const template = fs.readFileSync(path.join(root,'core/templates/portal/portal.html'),'utf8');
  const start = template.indexOf('<section id="page-imports"');
  const section = template.slice(start,template.indexOf('{% endif %}',start+100)).replace(/\{%[^]*?%\}/g,'');
  await page.setViewportSize({width:390,height:700});
  await page.setContent(`<body class="portal-app"><div id="portal-screen" data-screen="imports" style="padding:12px">${section}</div></body>`);
  await page.addStyleTag({path:asset('base.css')});
  await page.addStyleTag({path:asset('portal.css')});
  await page.evaluate(()=>{
    window.__importPaths=[];
    const batches=[{id:'needs-review',kind:'sysup',source_filename:'Customers Without Loans.xlsx',created_at:'2026-09-14T09:30:00',total_rows:115,review_needed:4,committed_count:0,archive_state:'needs_attention'},
      {id:'staged',kind:'sysup',source_filename:'Previous export.csv',total_rows:40,review_needed:0,committed_count:0,archive_state:'archived'}];
    window.PortalMiniAppApi={apiFetch:async path=>{
      window.__importPaths.push(path);
      return {ok:true,data:{ok:true,...(path==='/imports/'?{batches}:{batch:{...batches[0],source_table:{headers:['Source row'],rows:[['Sample row']]}}})}};
    }};
  });
  await page.addScriptTag({path:asset('portal_imports.js')});
  await page.evaluate(()=>window.PortalMiniAppImports.load());
  await expect(page.locator('.needs-attention .import-history-state')).toHaveText('Needs attention');
  await expect(page.locator('.settled .import-history-state')).toHaveText('Staged');
  await expect(page.locator('.portal-import-archive')).toHaveCount(1);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
  await page.screenshot({path:testInfo.outputPath('imports-mobile.png'),fullPage:true});
  await page.setViewportSize({width:1280,height:800});
  expect(await page.locator('.portal-import-upload-grid').evaluate(el=>el.getBoundingClientRect().width)).toBeLessThanOrEqual(620);
  await page.screenshot({path:testInfo.outputPath('imports-desktop.png'),fullPage:true});
  await page.locator('.needs-attention .portal-import-review-button').click();
  await expect(page.locator('#portal-import-review')).toContainText('Sample row');
  await page.locator('#portal-import-review-close').click();
  await expect(page.locator('#portal-import-review')).toBeHidden();
});

test('FarmUp landing highlights pending work without mobile overflow', async ({ page }, testInfo) => {
  const template = fs.readFileSync(path.join(root, 'core/templates/portal/portal.html'), 'utf8');
  const section = template.slice(template.indexOf('<section id="page-farmup"'), template.indexOf('{% endif %}', template.indexOf('<section id="page-farmup"') + 100))
    .replace(/\{%[^]*?%\}/g, '').replace(/\{\{[^]*?\}\}/g, '5');
  await page.setViewportSize({ width:390, height:700 });
  await page.setContent(`<body class="portal-app"><div id="portal-screen" data-screen="farmup" style="padding:12px">${section}</div></body>`);
  await page.addStyleTag({ path:asset('base.css') });
  await page.addStyleTag({ path:asset('portal.css') });
  await page.evaluate(() => {
    window.PortalAppShell = {hasCapability:()=>true};
    window.PortalMiniAppApi = {apiFetch:async()=>({ok:true,data:{ok:true,batches:[
      {id:'pending',source_filename:'May Farmers.csv',period_label:'May 2026',remaining_count:104,committed_count:6,total_rows:115,version_number:2,archive_state:'archived',publication:{status:'pending'},is_portal_archived:Boolean(window.__farmupArchived)},
      {id:'complete',source_filename:'April Farmers.csv',period_label:'April 2026',remaining_count:0,committed_count:120,total_rows:120,is_portal_archived:true,archive_state:'archived'}
    ]}})};
    window.PortalMiniAppApi.postJson=async()=>{window.__farmupArchived=true;return {ok:true,data:{ok:true}};};
    window.confirm=()=>true;
  });
  await page.addScriptTag({path:asset('portal_farmup.js')});
  await page.evaluate(()=>window.PortalMiniAppFarmUp.load());
  await expect(page.locator('#farmup-pending-badge')).toContainText('May 2026: 104 rows pending review');
  await expect(page.locator('#farmup-pending-action button')).toHaveAttribute('data-batch-id','pending');
  const footerAtBottom=async()=>{
    const bounds=await page.locator('#farmup-pending-action button').boundingBox();
    expect(Math.abs(bounds.y+bounds.height-page.viewportSize().height)).toBeLessThan(2);
  };
  await footerAtBottom();
  await expect(page.locator('.needs-review .farmup-open')).toHaveText('Review rows');
  await expect(page.locator('.farmup-batch-card')).toHaveCount(1);
  await expect(page.locator('#portal-farmup-list')).not.toContainText('April Farmers.csv');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({path:testInfo.outputPath('farmup-mobile.png'),fullPage:true});
  await page.setViewportSize({width:1280,height:800});
  await footerAtBottom();
  expect(await page.locator('.portal-farmup-upload').evaluate(el=>el.getBoundingClientRect().width)).toBeLessThanOrEqual(620);
  await page.screenshot({path:testInfo.outputPath('farmup-desktop.png'),fullPage:true});
  await page.locator('.farmup-archive').click();
  await expect(page.locator('.farmup-batch-card')).toHaveCount(0);
  await expect(page.locator('#farmup-pending-badge')).toBeHidden();
  await expect(page.locator('#farmup-pending-action')).toBeHidden();
  await page.evaluate(()=>window.PortalMiniAppFarmUp.load());
  await expect(page.locator('.farmup-batch-card')).toHaveCount(0);
});

test('Portal shell follows live viewport while sheets wait for stable Telegram height', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 620 });
  await page.setContent(`
    <header class="app-shell-header">Portal</header>
    <aside id="sidebar"></aside><button id="sidebar-backdrop"></button>
    <main id="content"><div id="portal-shell"><div id="portal-screen" data-screen="dashboard" data-top-level="true"></div></div></main>
    <div id="test-sheet" class="sheet-overlay open"><div class="sheet-panel"></div></div>
  `);
  await page.evaluate(() => { document.body.className = 'workflow-standard portal-app'; });
  await page.addStyleTag({ path: asset('base.css') });
  await page.addStyleTag({ path: asset('theme.css') });
  await page.addStyleTag({ path: asset('portal.css') });
  await page.evaluate(() => {
    window.__viewportEvents = {};
    const webApp = {
      viewportHeight: 620,
      viewportStableHeight: 700,
      themeParams: { bg_color: '#e8f0ec', secondary_bg_color: '#ffffff' },
      onEvent(name, callback) { window.__viewportEvents[name] = callback; },
      BackButton: { onClick() {}, offClick() {}, show() {}, hide() {} },
      MainButton: { onClick() {}, offClick() {}, show() {}, hide() {}, setText() {} },
    };
    window.Telegram = { WebApp: webApp };
    window.MiniAppUtils = { initTelegram: () => webApp };
    window.PortalAppShell = { activate() {} };
  });
  await page.addScriptTag({ path: asset('miniapp-nav.js') });

  async function dimensions() {
    return page.evaluate(() => ({
      body: document.body.getBoundingClientRect().height,
      content: document.getElementById('content').getBoundingClientRect().bottom,
      sheet: document.getElementById('test-sheet').getBoundingClientRect().height,
      live: getComputedStyle(document.documentElement).getPropertyValue('--miniapp-live-height').trim(),
      stable: getComputedStyle(document.documentElement).getPropertyValue('--miniapp-stable-height').trim(),
      background: getComputedStyle(document.documentElement).backgroundColor,
    }));
  }
  expect(await dimensions()).toMatchObject({ body: 620, content: 620, sheet: 700, live: '620px', stable: '700px' });

  await page.evaluate(() => {
    window.Telegram.WebApp.viewportHeight = 580;
    window.__viewportEvents.viewportChanged({ isStateStable: false });
  });
  expect(await dimensions()).toMatchObject({ body: 580, content: 580, sheet: 700, live: '580px', stable: '700px' });

  await page.setViewportSize({ width: 390, height: 700 });
  await page.evaluate(() => {
    window.Telegram.WebApp.viewportHeight = 700;
    window.Telegram.WebApp.viewportStableHeight = 700;
    window.__viewportEvents.viewportChanged({ isStateStable: true });
  });
  expect(await dimensions()).toMatchObject({ body: 700, content: 700, sheet: 700, live: '700px', stable: '700px' });

  await page.setViewportSize({ width: 700, height: 390 });
  await page.evaluate(() => {
    window.Telegram.WebApp.viewportHeight = 390;
    window.Telegram.WebApp.viewportStableHeight = 390;
    window.dispatchEvent(new Event('orientationchange'));
    window.__viewportEvents.viewportChanged({ isStateStable: true });
  });
  expect(await dimensions()).toMatchObject({ body: 390, content: 390, sheet: 390, live: '390px', stable: '390px' });
});

test('Portal queue controls filter the full list and keep search data ephemeral', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 700 });
  await page.route('http://miniapp.test/**', route => route.fulfill({ contentType: 'text/html', body: '<!doctype html><title>Portal controls</title>' }));
  await page.goto('http://miniapp.test/portal-controls');
  await page.setContent(`
    <section data-portal-queue-tools="credit">
      <label><input data-portal-queue-search="credit"><button type="button" data-portal-search-clear hidden>Clear</button></label>
      <button type="button" data-portal-filter-trigger>Filters <span data-portal-filter-count hidden>0</span></button>
      <div data-portal-filter-chips></div>
      <div data-portal-filter-overlay hidden aria-hidden="true"><aside data-portal-filter-sheet>
        <button type="button" data-miniapp-sheet-close>Close</button>
        <form data-portal-filter-form>
          <fieldset><div data-portal-filter-options="county"></div></fieldset>
          <fieldset><div data-portal-filter-options="branch"></div></fieldset>
          <select name="ordering"><option value="">Queue priority</option><option value="newest">Newest created</option></select>
          <button type="button" data-portal-filter-reset>Clear all</button><button type="submit">Apply</button>
        </form>
      </aside></div>
    </section>
  `);
  await loadUtilities(page);
  await page.addScriptTag({ path: asset('components.js') });
  await page.addScriptTag({ path: asset('portal_filters.js') });
  await page.evaluate(() => {
    window.__queueLoads = [];
    const state = { activePage: 'credit', pages: { credit: 1 }, searches: {}, filtersByQueue: {}, metaCounties: ['Kiambu', 'Nakuru'], metaBranches: ['Ruiru', 'Naivasha'] };
    window.PortalMiniAppFilters.init({ state, queueConfig: { credit: {} }, loadQueue: (key, pageNumber) => window.__queueLoads.push({ key, pageNumber, search: state.searches.credit, filters: { ...state.filtersByQueue.credit } }) });
    window.PortalMiniAppFilters.setupQueueTools('credit');
  });

  await page.locator('[data-portal-queue-search]').fill('Customer 12345678');
  await page.waitForTimeout(300);
  await page.locator('[data-portal-filter-trigger]').click();
  await page.locator('input[name="county"][value="Kiambu"]').check();
  await page.locator('input[name="county"][value="Nakuru"]').check();
  await page.waitForTimeout(250);

  const result = await page.evaluate(() => ({
    loads: window.__queueLoads,
    stored: Object.keys(sessionStorage).map(key => sessionStorage.getItem(key)).join(' '),
    count: document.querySelector('[data-portal-filter-count]').textContent,
  }));
  expect(result.loads.at(-1)).toMatchObject({ key: 'credit', pageNumber: 1, filters: { county: ['Kiambu', 'Nakuru'] } });
  expect(result.stored).not.toContain('Customer 12345678');
  expect(result.count).toBe('1');
});

test('Portal search renders one accessible field at mobile widths and in dark mode', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 640 });
  await page.setContent(`<main id="content"><label class="portal-queue-search" aria-label="Search cases"><i aria-hidden="true">⌕</i><input type="search" aria-label="Search cases" placeholder="Search cases"><button type="button" data-portal-search-clear>Clear</button></label></main>`);
  await page.evaluate(() => { document.body.className = 'workflow-standard portal-app'; });
  await page.addStyleTag({ path: asset('base.css') });
  await page.addStyleTag({ path: asset('portal.css') });
  await page.addStyleTag({ path: asset('workflow_standard.css') });
  await page.addStyleTag({ path: asset('theme.css') });
  const search = page.getByRole('searchbox', { name: 'Search cases' });
  const geometry = await page.evaluate(() => {
    const wrapper = document.querySelector('.portal-queue-search');
    const input = wrapper.querySelector('input');
    return { wrapperBorder: getComputedStyle(wrapper).borderTopWidth, inputBorder: getComputedStyle(input).borderTopWidth, inputWidth: input.getBoundingClientRect().width, wrapperWidth: wrapper.getBoundingClientRect().width };
  });
  expect(geometry.wrapperBorder).toBe('0px');
  expect(geometry.inputBorder).toBe('1px');
  expect(geometry.inputWidth).toBeLessThanOrEqual(geometry.wrapperWidth);
  await search.fill('Sample');
  await expect(search).toHaveValue('Sample');
  await page.evaluate(() => document.documentElement.style.setProperty('--tg-theme-secondary-bg-color', '#17221f'));
  await expect(search).toHaveCSS('background-color', 'rgb(23, 34, 31)');
});

test('Portal visit camera keeps one stream across ID, LAF, and supporting captures', async ({ page }) => {
  await page.route('http://miniapp.test/**', route => route.fulfill({ contentType: 'text/html', body: '<!doctype html><title>Portal camera</title>' }));
  await page.goto('http://miniapp.test/portal-camera');
  await page.setContent(`<div id="sheet-overlay"><div id="sheet-navigation"><button id="sheet-back"><span></span></button></div><div id="sheet-avatar"></div><div id="sheet-header-state"></div><div id="sheet-header-status"></div><button id="sheet-close"></button><h2 id="sheet-name"></h2><p id="sheet-sub"></p><ul id="sheet-info"></ul><div class="sheet-quick-actions"><section id="sheet-client-media"></section></div><button id="case360-toggle"></button><div id="sheet-gate-warning"></div><div id="sheet-form"></div><div id="sheet-footer"></div></div>
    <div id="jbl-camera-overlay"><h2 id="jbl-live-camera-title"></h2><button id="jbl-camera-close"></button><video id="jbl-camera-video"></video><span id="jbl-camera-status"></span><div id="jbl-camera-steps"></div><span id="jbl-camera-capture-state"></span><button id="jbl-camera-done"></button><button id="jbl-camera-shutter" disabled>Take Photo</button></div>
    <div id="media-viewer-overlay"><button id="media-viewer-close"></button><h2 id="media-viewer-title"></h2><p id="media-viewer-sub"></p><div id="media-viewer-content"></div></div>`);
  await page.addScriptTag({ path: asset('portal_farmer_sheet.js') });
  await page.evaluate(() => {
    window.__stops = 0;
    window.__permissions = 0;
    window.__writes = 0;
    window.__toasts = [];
    window.__protection = {};
    window.__shutterHaptics = [];
    window.__savedFrame = null;
    window.MiniAppUtils = {
      setCloseProtection(key, value) { window.__protection[key] = value; },
      impactWithFallback(kind, duration) { window.__shutterHaptics.push({kind, duration}); return true; },
    };
    Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: { async getUserMedia() {
      window.__permissions += 1;
      const stream = new MediaStream();
      stream.getTracks = () => [{ stop() { window.__stops += 1; } }];
      return stream;
    } } });
    HTMLMediaElement.prototype.play = async function () {};
    HTMLMediaElement.prototype.pause = function () {};
    Object.defineProperty(HTMLVideoElement.prototype, 'videoWidth', { configurable: true, get: () => 640 });
    Object.defineProperty(HTMLVideoElement.prototype, 'videoHeight', { configurable: true, get: () => 480 });
    HTMLCanvasElement.prototype.getContext = () => ({ drawImage(video, x, y, width, height) { window.__savedFrame = {x, y, width, height}; } });
    HTMLCanvasElement.prototype.toBlob = callback => callback(new Blob(['photo'.repeat(1000)], { type: 'image/jpeg' }));
    window.createImageBitmap = undefined;
    document.getElementById('case360-toggle').outerHTML = '<a id="case360-toggle"></a>';
    const state = { capabilities: new Set(['portal.case.read', 'portal.jbl_visit.write', 'portal.jbl_media.write']), metaStatuses: ['Visited'], metaCounties: [], jblVisitMediaMaxFiles: 6, businessDate: '2026-09-13' };
    window.PortalMiniAppFarmerSheet.init({ el: id => document.getElementById(id), state, tg: {}, escapeHtml: value => String(value ?? ''), fmt: value => String(value ?? '-'), fmtDate: value => String(value ?? '-'), locationText: () => '-', showToast: message => window.__toasts.push(message), apiFetch: async () => ({ ok: true, data: { ok: true, counties: [], sub_counties: [] } }) });
    window.PortalMiniAppFarmerSheet.openFarmerSheet({ id: 'case-1', customer_name: 'Sample', workflow_revision: 1 }, 'jbl_visit');
  });
  await page.setViewportSize({ width: 390, height: 800 });
  await page.evaluate(() => document.body.className = 'workflow-standard portal-app');
  await page.addStyleTag({ path: asset('base.css') });
  await page.addStyleTag({ path: asset('portal.css') });
  const documentHeights = await page.locator('.jbl-document-upload').evaluateAll(cards =>
    cards.map(card => Math.round(card.getBoundingClientRect().height)));
  expect(documentHeights).toHaveLength(2);
  expect(Math.max(...documentHeights)).toBeLessThan(110);
  await expect(page.locator('#case360-toggle')).toHaveAttribute('href','/portal/cases/case-1/?from=jbl');
  await expect(page.locator('#case360-toggle')).toBeVisible();
  await expect(page.locator('#jbl-village')).toHaveAttribute('required','');
  await expect(page.locator('#jbl-village')).toHaveAttribute('maxlength','255');
  await page.locator('#jbl-village').fill('   ');
  await page.locator('#btn-submit-jbl').click();
  await expect(page.locator('[data-jbl-field="village"]')).toHaveClass(/invalid/);
  await expect(page.locator('#jbl-village-error')).toHaveText('Enter the village.');
  expect(await page.evaluate(()=>window.__writes)).toBe(0);
  await page.locator('#jbl-village').fill('Test village');
  expect(await page.locator('#case360-toggle').evaluate(link=>{
    window.MiniAppUtils.canNavigatePage=()=>false;
    return !link.dispatchEvent(new MouseEvent('click',{bubbles:true,cancelable:true}));
  })).toBe(true);
  await page.locator('[data-camera-category="CLIENT_ID"]').click();
  await expect(page.locator('#jbl-camera-overlay')).toHaveClass(/open/);
  await expect(page.locator('#jbl-camera-shutter')).toBeEnabled();
  await expect(page.locator('#jbl-live-camera-title')).toContainText('Front');
  await page.locator('#jbl-camera-shutter').click();
  await expect(page.locator('#jbl-live-camera-title')).toContainText('Back');
  expect(await page.evaluate(()=>window.__shutterHaptics)).toEqual([{kind:'medium',duration:35}]);
  expect(await page.evaluate(()=>window.__savedFrame)).toEqual({x:0,y:0,width:640,height:480});
  await page.locator('#jbl-camera-shutter').click();
  await expect(page.locator('#jbl-id-media-name')).toContainText('Ready');
  await expect(page.locator('#jbl-live-camera-title')).toContainText('Page 1');
  await page.locator('#jbl-camera-shutter').click();
  await expect(page.locator('#jbl-live-camera-title')).toContainText('Page 2');
  await page.locator('#jbl-camera-shutter').click();
  await expect(page.locator('#jbl-laf-media-name')).toContainText('Ready');
  await expect(page.locator('#jbl-live-camera-title')).toContainText('Supporting photos');
  await page.locator('#jbl-camera-shutter').click();
  await page.locator('#jbl-camera-shutter').click();
  await expect(page.locator('#jbl-visit-photo-media-name')).toContainText('2 selected');
  await expect(page.locator('#jbl-camera-capture-state')).toContainText('2 of 6');
  expect(await page.evaluate(() => ({ permissions: window.__permissions, stops: window.__stops }))).toEqual({ permissions: 1, stops: 0 });
  await page.locator('[data-camera-step-category="CLIENT_ID"][data-camera-step-side="0"]').click();
  await expect(page.locator('#jbl-camera-shutter')).toContainText('Retake Front');
  await page.locator('#jbl-camera-shutter').click();
  expect(await page.evaluate(() => ({ permissions: window.__permissions, stops: window.__stops }))).toEqual({ permissions: 1, stops: 0 });
  await page.locator('#jbl-camera-done').click();
  expect(await page.evaluate(() => window.__stops)).toBe(1);
  await page.evaluate(() => {
    window.__viewerCloses = 0;
    new MutationObserver(() => {
      if (!document.getElementById('media-viewer-overlay').classList.contains('open')) window.__viewerCloses += 1;
    }).observe(document.getElementById('media-viewer-overlay'), { attributes: true, attributeFilter: ['class'] });
  });
  await page.locator('.jbl-document-slot-preview').first().click();
  await expect(page.locator('#media-viewer-title')).toContainText('Front');
  await page.locator('[data-selection-preview-action="next"]').click();
  await expect(page.locator('#media-viewer-title')).toContainText('Back');
  expect(await page.evaluate(() => window.__viewerCloses)).toBe(0);
  await page.locator('#media-viewer-close').click();
  await page.locator('.jbl-media-preview-open').first().click();
  await page.locator('[data-selection-preview-action="retake"]').click();
  await expect(page.locator('#jbl-visit-photo-media-name')).toContainText('2 selected');
  await page.locator('#jbl-camera-shutter').click();
  await expect(page.locator('#jbl-visit-photo-media-name')).toContainText('2 selected');
  await expect(page.locator('#jbl-camera-overlay')).toHaveClass(/open/);
  await page.locator('#jbl-camera-done').click();
  expect(await page.evaluate(() => ({ stops: window.__stops, writes: window.__writes, protected: window.__protection['portal-jbl-media-selected'] }))).toEqual({ stops: 2, writes: 0, protected: true });
  await page.evaluate(() => { navigator.mediaDevices.getUserMedia = async () => { throw new DOMException('Denied', 'NotAllowedError'); }; });
  await page.locator('#jbl-visit-photo-camera').click();
  await expect(page.locator('#jbl-camera-overlay')).not.toHaveClass(/open/);
  expect(await page.evaluate(() => window.__toasts.at(-1))).toContain('Camera permission was denied');
  await expect(page.locator('#jbl-visit-photo-media')).toHaveCount(1);
});

test('Portal report table zoom reaches the 20 percent accessibility floor', async ({ page }) => {
  await page.setContent(`<div data-miniapp-table-zoom="portal"><button data-miniapp-table-zoom-out>−</button><button data-miniapp-table-zoom-reset>100%</button><button data-miniapp-table-zoom-in>+</button><div data-miniapp-table-zoom-target></div></div>`);
  await loadUtilities(page);
  await page.addScriptTag({ path: asset('components.js') });
  await page.evaluate(() => window.MiniAppComponents.bindTableZoom(document.querySelector('[data-miniapp-table-zoom]'), 'browser-table-zoom'));
  for (let index = 0; index < 5; index += 1) await page.locator('[data-miniapp-table-zoom-out]').click();
  await expect(page.locator('[data-miniapp-table-zoom-reset]')).toHaveText('20%');
  await expect(page.locator('[data-miniapp-table-zoom-out]')).toBeDisabled();
  expect(await page.locator('[data-miniapp-table-zoom-target]').evaluate(node => node.style.getPropertyValue('--miniapp-table-scale'))).toBe('0.2');
});

test('Portal FarmUp renders a compact mobile grid with explicit selection counts', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 700 });
  await page.setContent(`
    <div id="portal-screen" data-screen="farmup">
      <form id="portal-farmup-upload"></form><div id="portal-farmup-feedback"></div>
      <section id="portal-farmup-review" hidden></section><button id="portal-farmup-refresh">Refresh</button>
      <div id="portal-farmup-list"></div>
    </div>
  `);
  await page.addStyleTag({ path: asset('base.css') });
  await page.addStyleTag({ path: asset('portal.css') });
  await page.evaluate(()=>{
    const root=document.getElementById('portal-screen');
    const screen=document.createElement('section');screen.id='page-farmup';
    while(root.firstChild) screen.append(root.firstChild);
    root.append(screen);document.body.classList.add('portal-app');
  });
  await page.addStyleTag({ path: asset('vendor-ag-grid-community-36.1.0.min.css') });
  await page.addStyleTag({ path: asset('vendor-ag-grid-theme-quartz-36.1.0.min.css') });
  await page.addScriptTag({ path: asset('vendor-ag-grid-community-36.1.0.min.js') });
  await page.evaluate(() => {
    const row = {
      row_id: 1, approved: true, 'Import Status': 'active', 'Customer Name': 'Test Farmer',
      'National ID': '12345678', 'Primary Phone': '254700000001', 'Secondary Phone': '254700000002',
      'Application Action': 'update_existing', 'Additional Unit Reason': '', County: 'Embu',
      'HBG Visit Date': '01-05-2026', 'Deposit Paid to HB': '5000', 'HB Sales Person': 'Test Officer',
      'Cleaning Notes': '',
    };
    const mapping = { state: 'auto_ready', columns: [], canonical_fields: [], missing_required_fields: [] };
    const validation = [{ row_id: '1', state: 'ready', selected: true, disposition: 'commit_now', warning_acknowledged: false, update_acknowledged: false, match: {kind:'new', changed_fields:[]}, issues: [] }];
    const batch = { id: 'batch-1', source_filename: 'farmers.csv', status: 'pending_review', total_rows: 1, review_needed: 0, committed_count: 0, archive_state: 'archived', mapping_state: 'auto_ready', is_current_version: true, version_number: 1, period_label: 'August 2026', versions: [{id:'batch-1'}] };
    window.PortalAppShell = { hasCapability: () => true, showToast: () => {} };
    window.__farmupSwipeGuards = 0;
    window.Telegram = { WebApp: { disableVerticalSwipes: () => { window.__farmupSwipeGuards += 1; } } };
    window.__farmupProtection = [];
    window.MiniAppUtils = { createRequestId: () => 'farmup-browser-request-1', setCloseProtection: (reason, active) => window.__farmupProtection.push([reason, active]) };
    window.__farmupCommits = [];
    window.PortalMiniAppApi = {
      async apiFetch(path) {
        if (path === '/farmup/') return { ok: true, data: { ok: true, batches: [null, batch] } };
        return { ok: true, data: { ok: true, batch: { ...batch, mapping, validation, rows: [{ ...row }], revision_token: 'opaque-token' } } };
      },
      async postJson(path, payload) {
        if (path.includes('/validate/')) return { ok: true, data: { ok: true, rows: validation, counts: { selected: 1, new: 1, updates: 0, unchanged: 0, held: 0, excluded: 0, removed: 0, warning_overrides: 0, unresolved: 0 } } };
        if (path.includes('/commit/')) window.__farmupCommits.push(payload);
        return { ok: true, data: { ok: true, result: { success: true, committed: 1, skipped: 0, review_needed: 0 }, batch } };
      },
    };
  });
  await page.addScriptTag({ path: asset('portal_farmup.js') });
  await page.evaluate(() => window.PortalMiniAppFarmUp.load());
  await page.locator('.farmup-open').click();
  await expect(page.locator('#farmup-grid .ag-root-wrapper')).toBeVisible();
  await expect(page.locator('#farmup-grid .ag-header')).toBeVisible();
  await expect(page.locator('.farmup-mobile-card')).toHaveCount(0);
  await expect(page.locator('#farmup-selection-summary')).toContainText('1 commit');
  await page.screenshot({path:testInfo.outputPath('farmup-review-mobile.png'),fullPage:true});
  expect(await page.locator('.farmup-grid-wrap').evaluate(element => element.scrollWidth === element.clientWidth)).toBe(true);
  expect(await page.locator('.farmup-grid .ag-body-horizontal-scroll-viewport').evaluate(element => element.scrollWidth > element.clientWidth)).toBe(true);
  const nameCell = page.locator('.ag-cell').filter({ hasText: 'Test Farmer' }).first();
  await nameCell.dblclick();
  await page.keyboard.press('Control+A');
  await page.keyboard.type('Edited Farmer');
  await page.keyboard.press('Enter');
  await expect(page.locator('.ag-cell').filter({ hasText: 'Edited Farmer' }).first()).toHaveClass(/farmup-cell-edited/);
  await expect(page.locator('#farmup-selection-summary')).toContainText('1 edits');
  await page.locator('[data-farmup-mode="carousel"]').click();
  await expect(page.locator('.farmup-carousel-card')).toContainText('Edited Farmer');
  await expect(page.locator('.farmup-carousel-field.edited')).toHaveCount(1);
  await expect(page.locator('.farmup-carousel-track')).toHaveCSS('scroll-snap-type', 'x mandatory');
  await page.evaluate(() => document.dispatchEvent(new Event('visibilitychange')));
  expect(await page.evaluate(() => window.__farmupSwipeGuards)).toBeGreaterThan(0);
  await page.locator('[data-farmup-mode="table"]').click();
  await page.locator('#farmup-clear-all').click();
  await expect(page.locator('#farmup-selection-summary')).toContainText('0 commit');
  await expect(page.locator('#farmup-selection-summary')).toContainText('1 held');
  await page.locator('#farmup-select-all').click();
  await expect(page.locator('#farmup-selection-summary')).toContainText('1 commit');
  await page.locator('#farmup-commit').click();
  await expect(page.locator('.farmup-confirm-dialog')).toContainText('1selected');
  await expect(page.locator('.farmup-confirm-dialog')).toContainText('1edited cells');
  await expect(page.locator('.farmup-confirm-dialog')).toContainText('0unresolved');
  await page.locator('.farmup-confirm-dialog button[value="confirm"]').click();
  await expect.poll(() => page.evaluate(() => window.__farmupCommits.length)).toBe(1);
  expect(await page.evaluate(() => window.__farmupCommits[0])).toMatchObject({
    revision_token: 'opaque-token', client_request_id: 'farmup-browser-request-1',
  });
});

test('FarmUp accepts generic-MIME CSVs and picker cancellation preserves dirty protection', async ({ page }) => {
  await page.setContent('<div id="portal-screen" data-screen="farmup"><div id="portal-farmup-feedback"></div><input id="farmup-file" type="file" data-farmup-file></div>');
  await page.evaluate(() => {
    window.__closeReasons = new Set(['portal-farmup-review-dirty']);
    window.MiniAppUtils = { setCloseProtection(reason, active) { if (active) window.__closeReasons.add(reason); else window.__closeReasons.delete(reason); } };
    window.Telegram = { WebApp: { disableVerticalSwipes() {} } };
    window.PortalMiniAppApi = {};
  });
  await page.addScriptTag({ path: asset('portal_farmup.js') });
  await expect(page.locator('#farmup-file')).not.toHaveAttribute('accept', /.+/);
  await page.locator('#farmup-file').setInputFiles({ name: 'farmers.CSV', mimeType: 'application/octet-stream', buffer: Buffer.from('Full Name\nJane') });
  expect(await page.evaluate(() => window.__closeReasons.has('portal-farmup-file-selected'))).toBe(true);
  await page.evaluate(() => {
    const input = document.getElementById('farmup-file');
    input.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    input.dispatchEvent(new Event('cancel', { bubbles: true }));
  });
  expect(await page.evaluate(() => ({ dirty: window.__closeReasons.has('portal-farmup-review-dirty'), picker: window.__closeReasons.has('portal-farmup-file-picker') }))).toEqual({ dirty: true, picker: false });
});

test('AG Grid zoom changes real row and header sizing', async ({ page }) => {
  await page.setContent(`
    <div id="controls" hidden>
      <button id="out">−</button><button id="reset">100%</button><button id="in">+</button>
    </div>
    <div id="grid" class="ag-theme-quartz" style="height:240px;--ag-font-size:11px"></div>
  `);
  await page.addStyleTag({ path: asset('vendor-ag-grid-community-36.1.0.min.css') });
  await page.addStyleTag({ path: asset('vendor-ag-grid-quartz-font-36.1.0.min.css') });
  await page.addStyleTag({ path: asset('vendor-ag-grid-theme-quartz-36.1.0.min.css') });
  await page.addScriptTag({ path: asset('vendor-ag-grid-community-36.1.0.min.js') });
  await page.addScriptTag({ path: asset('ag_grid_zoom.js') });
  await page.evaluate(() => {
    window.agGrid.ModuleRegistry.registerModules([window.agGrid.AllCommunityModule]);
    window.__zoomGridApi = window.agGrid.createGrid(document.getElementById('grid'), {
      theme: 'legacy', rowData: [{ name: 'Case one', status: 'Active' }],
      columnDefs: [{ field: 'name', width: 200, minWidth: 100 }, { field: 'status', width: 160, minWidth: 80 }],
    });
    window.__zoomControl = window.MiniAppAgGridZoom.bind({
      container: document.getElementById('controls'),
      gridElement: document.getElementById('grid'),
      outButton: document.getElementById('out'),
      resetButton: document.getElementById('reset'),
      inButton: document.getElementById('in'),
      storage: null,
      apiProvider: () => window.__zoomGridApi,
      defaults: { fontSize: 11, gridSize: 4, rowHeight: 34, headerHeight: 36, cellPadding: 4 },
    });
  });

  await expect(page.locator('#controls')).toBeVisible();
  const defaultRowHeight = await page.locator('.ag-row').evaluate(node => node.getBoundingClientRect().height);
  const defaultHeaderHeight = await page.locator('.ag-header').evaluate(node => node.getBoundingClientRect().height);
  const defaultColumnWidth = await page.locator('.ag-header-cell').first().evaluate(node => node.getBoundingClientRect().width);
  await expect(page.locator('#grid')).toHaveCSS('--ag-cell-horizontal-padding', '4px');
  await page.locator('#in').click();
  await expect(page.locator('#reset')).toHaveText('110%');
  await expect.poll(() => page.locator('.ag-row').evaluate(node => node.getBoundingClientRect().height)).toBeGreaterThan(defaultRowHeight);
  await expect.poll(() => page.locator('.ag-header').evaluate(node => node.getBoundingClientRect().height)).toBeGreaterThan(defaultHeaderHeight);
  await expect(page.locator('#grid')).toHaveCSS('--ag-font-size', '12.1px');
  await page.evaluate(() => window.__zoomControl.setLevel(20));
  await expect(page.locator('#reset')).toHaveText('20%');
  await expect.poll(() => page.locator('.ag-row').evaluate(node => node.getBoundingClientRect().height)).toBeLessThan(defaultRowHeight);
  await expect.poll(() => page.locator('.ag-header').evaluate(node => node.getBoundingClientRect().height)).toBeLessThan(defaultHeaderHeight);
  await expect.poll(() => page.locator('.ag-header-cell').first().evaluate(node => node.getBoundingClientRect().width)).toBeLessThan(defaultColumnWidth / 2);
  await page.locator('#reset').click();
  await expect(page.locator('#reset')).toHaveText('100%');
});

test('Complaints and TAT follow Telegram theme independently of the device theme', async ({ page }) => {
  await page.emulateMedia({ colorScheme: 'light' });
  await page.setContent('<input id="nativeControl" type="date"><div id="tatGrid" class="ag-theme-quartz tat-report-grid"></div>');
  await page.addStyleTag({ path: asset('base.css') });
  await page.addStyleTag({ path: asset('complaint_cases.css') });
  await loadUtilities(page);
  await page.evaluate(() => {
    window.__themeEvents = {};
    window.__themeChrome = {};
    window.__themeWebApp = {
      colorScheme: 'dark',
      themeParams: { bg_color: '#101714', secondary_bg_color: '#18231e' },
      onEvent(name, callback) { window.__themeEvents[name] = callback; },
      setHeaderColor(value) { window.__themeChrome.header = value; },
      setBackgroundColor(value) { window.__themeChrome.background = value; },
      setBottomBarColor(value) { window.__themeChrome.bottom = value; },
    };
    window.MiniAppUtils.bindMiniAppTheme(window.__themeWebApp);
  });

  await expect(page.locator('html')).toHaveAttribute('data-miniapp-color-scheme', 'dark');
  expect(await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--raised').trim())).toBe('#202d27');
  expect(await page.locator('#nativeControl').evaluate(node => getComputedStyle(node).colorScheme)).toContain('dark');
  expect(await page.evaluate(() => window.__themeChrome)).toEqual({
    header: '#101714', background: '#101714', bottom: '#18231e',
  });

  await page.emulateMedia({ colorScheme: 'dark' });
  await page.evaluate(() => {
    window.__themeWebApp.colorScheme = 'light';
    window.__themeWebApp.themeParams = { bg_color: '#f3f6f8', bottom_bar_bg_color: '#ffffff' };
    window.__themeEvents.themeChanged();
  });
  await expect(page.locator('html')).toHaveAttribute('data-miniapp-color-scheme', 'light');
  expect(await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--raised').trim())).toBe('#fff');
  expect(await page.locator('#nativeControl').evaluate(node => getComputedStyle(node).colorScheme)).toContain('light');

  await page.addStyleTag({ path: asset('vendor-ag-grid-community-36.1.0.min.css') });
  await page.addStyleTag({ path: asset('vendor-ag-grid-quartz-font-36.1.0.min.css') });
  await page.addStyleTag({ path: asset('vendor-ag-grid-theme-quartz-36.1.0.min.css') });
  await page.addStyleTag({ path: asset('tat_tracker.css') });
  await page.evaluate(() => {
    window.__themeWebApp.colorScheme = 'dark';
    window.__themeWebApp.themeParams = { bg_color: '#0f172a', secondary_bg_color: '#1e293b' };
    window.__themeEvents.themeChanged();
  });
  expect(await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--tat-danger-text').trim())).toBe('#ffaaa3');
  expect(await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--tat-border').trim())).toBe('rgba(255, 255, 255, 0.12)');
  expect(await page.locator('#tatGrid').evaluate(node => getComputedStyle(node).getPropertyValue('--ag-background-color').trim())).toBe('#1e293b');
});

test('Complaint management report contains horizontal grid scrolling and Telegram back navigation', async ({ page }) => {
  const template = fs.readFileSync(path.join(root, 'core', 'templates', 'complaint_cases', 'app.html'), 'utf8')
    .replace(/{% load static %}/g, '')
    .replace(/{% include [^%]+%}/g, '')
    .replace(/{% static '[^']+' %}/g, '')
    .replace(/<script[^>]*>[\s\S]*?<\/script>/g, '')
    .replace(/<link[^>]*>/g, '');
  await page.setViewportSize({ width: 360, height: 780 });
  await page.setContent(template);
  await page.addStyleTag({ path: asset('vendor-ag-grid-community-36.1.0.min.css') });
  await page.addStyleTag({ path: asset('vendor-ag-grid-quartz-font-36.1.0.min.css') });
  await page.addStyleTag({ path: asset('vendor-ag-grid-theme-quartz-36.1.0.min.css') });
  await page.addStyleTag({ path: asset('complaint_cases.css') });
  await page.evaluate(() => {
    document.body.dataset.groupId = '-100-report-test';
    window.__backVisible = false; window.__backHandler = null; window.__reportRequests = []; window.__sharedFiles = [];
    window.__reportDataDelays = []; window.__reportAborted = 0;
    const webApp = {
      initData: 'synthetic-signed-init-data',
      platform: 'android',
      BackButton: {
        onClick(callback) { window.__backHandler = callback; },
        show() { window.__backVisible = true; },
        hide() { window.__backVisible = false; },
      },
      onEvent() {}, disableVerticalSwipes() {},
    };
    window.Telegram = { WebApp: webApp };
    window.MiniAppUtils = { initTelegram: () => webApp, haptic() {}, setCloseProtection() {} };
    window.ComplaintCasesMiniAppApi = {
      async postJson(path) {
        if (path === 'bootstrap/') return { data: {
          actor: { name: 'IT Manager', role: 'IT', capabilities: ['complaint.queue.view', 'complaint.reports.view', 'complaint.case.export'] },
          counts: { pending: 1, resolved: 0, total: 1 }, branches: [], categories: [], category_catalogue: [],
          evidence_limits: { max_files: 10, max_file_size_mb: 10, max_total_upload_mb: 30 },
        } };
        if (path === 'cases/') return { cases: [], pagination: { page: 1, pages: 1, total: 0 }, start_index: 0 };
        return { data: {} };
      },
      async getJson(path, params, _initData, _utils, requestSettings) {
        window.__reportRequests.push({ path, params: Object.assign({}, params || {}) });
        if (path === 'reports/summary/') return {
          total: 1, pending: 1, resolved: 0, needs_details: 0,
          by_branch: [{ label: 'Nakuru', count: 1 }], by_category: [{ label: 'Leakage', count: 1 }],
          by_time: (params?.granularity || 'month') === 'day'
            ? Array.from({ length: 31 }, (_, index) => ({ label: `2026-07-${String(index + 1).padStart(2, '0')}`, count: (index % 4) + 1 }))
            : [{ label: ({ week: '2026-08-31', month: '2026-09', year: '2026' })[params?.granularity || 'month'], count: 1 }],
          time_granularity: params?.granularity || 'month',
          filter_options: { branches: [{ label: 'Nakuru', count: 1 }], categories: [{ label: 'Leakage', count: 1 }] },
        };
        const delay = path === 'reports/data/' ? (window.__reportDataDelays.shift() || 0) : 0;
        if (delay) await new Promise((resolve, reject) => {
          const timer = setTimeout(resolve, delay);
          requestSettings?.signal?.addEventListener('abort', () => {
            clearTimeout(timer); window.__reportAborted += 1;
            reject(new DOMException('The request was cancelled.', 'AbortError'));
          }, { once: true });
        });
        return { results: [{
          complaint_id: 'CMP-1004', date_reported: '2026-09-01T10:00:00+03:00', status: 'Pending', needs_details: false,
          customer_name: 'TEST CUSTOMER', customer_id: '12345678', phone_number: '254700000000', reported_by: 'Officer',
          branch_region: 'Nakuru', complaint_category: 'Leakage', complaint_description: 'A sufficiently wide complaint description',
          source: 'complaint_mini_app', gps_link: '', attachments: 0, resolution_details: '', date_resolved: '2026-09-02T14:00:00+03:00', days_open: 1,
        }], count: 1, page: 1, page_size: 50 };
      },
      async postBlob() {
        return {
          blob: new Blob(['synthetic-xlsx'], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }),
          filename: 'Complaint-Cases-Test.xlsx',
        };
      },
    };
    Object.defineProperty(navigator, 'canShare', {
      configurable: true,
      value: payload => Boolean(payload?.files?.length),
    });
    Object.defineProperty(navigator, 'share', {
      configurable: true,
      value: async payload => {
        window.__sharedFiles = payload.files.map(file => ({ name: file.name, type: file.type, size: file.size }));
      },
    });
  });
  await page.addScriptTag({ path: asset('vendor-ag-grid-community-36.1.0.min.js') });
  await page.addScriptTag({ path: asset('vendor-chartjs-4.5.1.umd.min.js') });
  await page.addScriptTag({ path: asset('complaint_cases.js') });
  await page.locator('#globalWorkspaceBtn').click();
  await expect(page.locator('#globalView')).toBeVisible();
  await expect(page.locator('.ag-row')).toHaveCount(1);
  await expect(page.locator('.ag-header-cell-movable')).toHaveCount(0);
  await expect(page.locator('.ag-header-cell-resize:visible')).toHaveCount(0);
  await expect(page.locator('.ag-cell[col-id="date_reported"]')).toHaveText('01-09-26');
  await expect(page.locator('.report-status')).toHaveCSS('background-color', 'rgba(0, 0, 0, 0)');
  await expect.poll(() => page.evaluate(() => document.fonts.check('16px agGridQuartz'))).toBe(true);
  await expect(page.locator('.ag-header-cell[col-id="complaint_id"] .ag-sort-indicator-icon:visible')).toHaveCount(0);
  await expect(page.getByText('CMP-1004', { exact: true })).toBeVisible();
  await expect(page.locator('.ag-header-cell[col-id="date_reported"] .ag-sort-indicator-icon:visible')).toHaveCount(1);
  await page.locator('.ag-header-cell[col-id="date_reported"]').click();
  await expect(page.locator('.ag-header-cell[col-id="date_reported"]')).toHaveAttribute('aria-sort', 'ascending');
  await expect(page.locator('.ag-header-cell[col-id="date_reported"] .ag-sort-indicator-icon:visible .ag-icon-asc')).toHaveCount(1);
  await expect.poll(() => page.evaluate(() => window.Chart.getChart('timeChart')?.data.labels[0])).toBe('01-09-26');
  const monthlyPlotHeight = await page.evaluate(() => window.Chart.getChart('timeChart').chartArea.height);
  await page.locator('.ag-body-horizontal-scroll-viewport').evaluate(node => {
    node.scrollLeft = node.scrollWidth;
    node.dispatchEvent(new Event('scroll'));
  });
  await expect(page.locator('.ag-cell[col-id="date_resolved"]')).toHaveText('02-09-26');

  await page.locator('#reportDateMode').selectOption('month');
  await page.locator('input[name="report_month"]').fill('2026-07');
  await page.locator('input[name="report_month"]').dispatchEvent('change');
  await expect.poll(() => page.evaluate(() => window.__reportRequests.filter(item => item.params.date_from === '2026-07-01').length)).toBe(2);
  const julyRequests = await page.evaluate(() => window.__reportRequests.filter(item => item.params.date_from === '2026-07-01'));
  expect(julyRequests.map(item => item.path).sort()).toEqual(['reports/data/', 'reports/summary/']);
  expect(julyRequests.every(item => item.params.date_to === '2026-07-31')).toBe(true);
  await expect(page.locator('#reportPeriodLabel')).toContainText('July 2026');

  const requestsBeforePie = await page.evaluate(() => window.__reportRequests.length);
  await page.locator('[data-category-chart="pie"]').click();
  await expect(page.locator('[data-category-chart="pie"]')).toHaveAttribute('aria-pressed', 'true');
  expect(await page.evaluate(() => window.__reportRequests.length)).toBe(requestsBeforePie);
  const dataRequestsBeforeGrouping = await page.evaluate(() => window.__reportRequests.filter(item => item.path === 'reports/data/').length);
  await page.locator('#reportGranularity').selectOption('week');
  await expect.poll(() => page.evaluate(() => window.__reportRequests.some(item => item.path === 'reports/summary/' && item.params.granularity === 'week'))).toBe(true);
  await expect.poll(() => page.evaluate(() => window.Chart.getChart('timeChart')?.data.labels[0])).toBe('31-08-26');
  const timeAxis = await page.evaluate(() => {
    const ticks = window.Chart.getChart('timeChart').options.scales.x.ticks;
    return { maxRotation: ticks.maxRotation, minRotation: ticks.minRotation, maxTicksLimit: ticks.maxTicksLimit, fontSize: ticks.font.size };
  });
  expect(timeAxis).toEqual({ maxRotation: 0, minRotation: 0, maxTicksLimit: 4, fontSize: 9 });
  await page.locator('#reportGranularity').selectOption('day');
  await expect.poll(() => page.evaluate(() => window.Chart.getChart('timeChart')?.data.labels.at(-1))).toBe('31-07-26');
  const dailyPlotHeight = await page.evaluate(() => window.Chart.getChart('timeChart').chartArea.height);
  expect(Math.abs(dailyPlotHeight - monthlyPlotHeight)).toBeLessThanOrEqual(2);
  await page.locator('#reportGranularity').selectOption('year');
  await expect.poll(() => page.evaluate(() => window.Chart.getChart('timeChart')?.data.labels[0])).toBe('01-01-26');
  expect(await page.evaluate(() => window.__reportRequests.filter(item => item.path === 'reports/data/').length)).toBe(dataRequestsBeforeGrouping);

  const dataRequestsBeforeRace = await page.evaluate(() => window.__reportRequests.filter(item => item.path === 'reports/data/').length);
  await page.evaluate(() => { window.__reportDataDelays = [250, 10]; });
  await page.locator('select[name="status"]').selectOption('pending');
  await expect.poll(() => page.evaluate(() => window.__reportRequests.filter(item => item.path === 'reports/data/').length)).toBe(dataRequestsBeforeRace + 1);
  await page.locator('select[name="status"]').selectOption('resolved');
  await expect.poll(() => page.evaluate(() => window.__reportRequests.filter(item => item.path === 'reports/data/').length)).toBe(dataRequestsBeforeRace + 2);
  await expect.poll(() => page.evaluate(() => window.__reportAborted)).toBe(1);
  await expect(page.locator('.ag-overlay-loading-center:visible')).toHaveCount(0);
  await expect(page.locator('.ag-row')).toHaveCount(1);

  for (const width of [320, 360, 390]) {
    await page.setViewportSize({ width, height: 780 });
    const overflow = await page.evaluate(() => ({
      document: document.documentElement.scrollWidth - window.innerWidth,
      grid: document.querySelector('.ag-body-horizontal-scroll-viewport').scrollWidth - document.querySelector('.ag-body-horizontal-scroll-viewport').clientWidth,
      backVisible: window.__backVisible,
    }));
    expect(overflow.document).toBeLessThanOrEqual(1);
    expect(overflow.grid).toBeGreaterThan(0);
    expect(overflow.backVisible).toBe(true);
  }
  await page.emulateMedia({ colorScheme: 'light' });
  const lightSurface = await page.locator('#complaintReportGrid').evaluate(node => getComputedStyle(node).getPropertyValue('--ag-background-color'));
  await page.emulateMedia({ colorScheme: 'dark' });
  const darkSurface = await page.locator('#complaintReportGrid').evaluate(node => getComputedStyle(node).getPropertyValue('--ag-background-color'));
  expect(darkSurface).not.toBe(lightSurface);

  await page.locator('#exportAllBtn').click();
  await expect(page.locator('#exportConfirm')).toBeVisible();
  await page.locator('#confirmExportBtn').click();
  await expect.poll(() => page.evaluate(() => window.__sharedFiles.length)).toBe(1);
  expect(await page.evaluate(() => window.__sharedFiles[0])).toMatchObject({
    name: 'Complaint-Cases-Test.xlsx',
    type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  });
  await expect(page.locator('#downloadResultTitle')).toHaveText('Excel file ready');
  await expect(page.locator('#openExportBtn')).toBeVisible();

  await page.evaluate(() => window.__backHandler());
  await expect(page.locator('#queueView')).toBeVisible();
});

test('Complaint camera stops when Telegram deactivates the Mini App', async ({ page }) => {
  const template = fs.readFileSync(path.join(root, 'core', 'templates', 'complaint_cases', 'app.html'), 'utf8')
    .replace(/{% load static %}/g, '')
    .replace(/{% include [^%]+%}/g, '')
    .replace(/{% static '[^']+' %}/g, '')
    .replace(/<script[^>]*>[\s\S]*?<\/script>/g, '')
    .replace(/<link[^>]*>/g, '');
  await page.setContent(template);
  await page.evaluate(() => {
    document.body.dataset.groupId = '-100-camera-test';
    window.__cameraTrackStopped = 0;
    window.__telegramEvents = {};
    Object.defineProperty(HTMLMediaElement.prototype, 'srcObject', {
      configurable: true,
      get() { return this.__syntheticStream || null; },
      set(value) { this.__syntheticStream = value; },
    });
    HTMLMediaElement.prototype.play = async function () {};
    navigator.mediaDevices = {
      async getUserMedia() {
        return { getTracks: () => [{ stop() { window.__cameraTrackStopped += 1; } }] };
      },
    };
    const webApp = {
      initData: 'synthetic-signed-init-data',
      BackButton: { onClick() {}, show() {}, hide() {} },
      onEvent(name, callback) { window.__telegramEvents[name] = callback; },
    };
    window.Telegram = { WebApp: webApp };
    window.MiniAppUtils = {
      initTelegram: () => webApp,
      createRequestId: prefix => `${prefix}-synthetic-request`,
      setCloseProtection() {},
    };
    window.ComplaintCasesMiniAppApi = {
      async postJson(path) {
        if (path === 'bootstrap/') return { data: {
          actor: { name: 'Manager', role: 'MANAGER', capabilities: ['complaint.case.create'] },
          counts: { pending: 0, resolved: 0, total: 0 }, branches: [], categories: [],
          evidence_limits: { max_files: 10, max_file_size_mb: 10, max_total_upload_mb: 30 },
        } };
        if (path === 'cases/') return { cases: [], pagination: { page: 1, pages: 1, total: 0 }, start_index: 0 };
        return { data: {} };
      },
    };
  });
  await page.addScriptTag({ path: asset('complaint_cases.js') });
  await page.locator('#newCaseBtn').click();
  await page.locator('[data-camera-target="create"]').click();
  await expect(page.locator('#cameraOverlay')).toBeVisible();

  const stopped = await page.evaluate(() => {
    window.__telegramEvents.deactivated();
    return window.__cameraTrackStopped;
  });

  expect(stopped).toBe(1);
  await expect(page.locator('#cameraOverlay')).toBeHidden();
});

test('Complaint camera captures multiple photos and the viewer navigates deletes and retakes', async ({ page }) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error.message));
  const template = fs.readFileSync(path.join(root, 'core', 'templates', 'complaint_cases', 'app.html'), 'utf8')
    .replace(/{% load static %}/g, '')
    .replace(/{% include [^%]+%}/g, '')
    .replace(/{% static '[^']+' %}/g, '')
    .replace(/<script[^>]*>[\s\S]*?<\/script>/g, '')
    .replace(/<link[^>]*>/g, '');
  await page.setContent(template);
  await page.addStyleTag({ path: asset('complaint_cases.css') });
  await page.evaluate(() => {
    document.body.dataset.groupId = '-100-camera-gallery-test';
    Object.defineProperty(HTMLMediaElement.prototype, 'srcObject', {
      configurable: true,
      get() { return this.__syntheticStream || null; },
      set(value) { this.__syntheticStream = value; },
    });
    HTMLMediaElement.prototype.play = async function () {};
    const cameraVideo = document.getElementById('cameraVideo');
    Object.defineProperty(cameraVideo, 'videoWidth', { configurable: true, get: () => 1280 });
    Object.defineProperty(cameraVideo, 'videoHeight', { configurable: true, get: () => 960 });
    const cameraCanvas = document.getElementById('cameraCanvas');
    Object.defineProperty(cameraCanvas, 'getContext', {
      configurable: true, value: () => ({ drawImage() {} }),
    });
    Object.defineProperty(cameraCanvas, 'toBlob', {
      configurable: true,
      value: callback => callback(new Blob(['synthetic-photo'], { type: 'image/jpeg' })),
    });
    navigator.mediaDevices = {
      async getUserMedia() { return { getTracks: () => [{ stop() {} }] }; },
    };
    Object.defineProperty(navigator, 'geolocation', {
      configurable: true,
      value: { getCurrentPosition(success) { success({ coords: { latitude: -1.2612164, longitude: 36.8423884 } }); } },
    });
    const webApp = {
      initData: 'synthetic-signed-init-data',
      BackButton: { onClick() {}, show() {}, hide() {} },
      onEvent() {},
    };
    window.Telegram = { WebApp: webApp };
    window.__requestSequence = 0;
    window.MiniAppUtils = {
      initTelegram: () => webApp,
      createRequestId: prefix => `${prefix}-synthetic-${++window.__requestSequence}`,
      setCloseProtection() {},
    };
    window.SecureMediaViewer = {
      renderBlob(container, blob, options) {
        const image = document.createElement('img');
        image.className = 'media-viewer-image'; image.alt = options?.name || ''; container.replaceChildren(image);
        return URL.createObjectURL(blob);
      },
      revoke(url) { if (url) URL.revokeObjectURL(url); },
    };
    window.ComplaintCasesMiniAppApi = {
      async postJson(path) {
        if (path === 'bootstrap/') return { data: {
          actor: { name: 'Officer', role: 'OFFICER', capabilities: ['complaint.case.create'] },
          counts: { pending: 0, resolved: 0, total: 0 }, branches: [], categories: [],
          evidence_limits: { max_files: 10, max_file_size_mb: 10, max_total_upload_mb: 30 },
        } };
        if (path === 'cases/') return { cases: [], pagination: { page: 1, pages: 1, total: 0 }, start_index: 0 };
        return { data: {} };
      },
    };
  });
  await page.addScriptTag({ path: asset('complaint_cases.js') });

  await page.locator('#newCaseBtn').click();
  for (const width of [320, 360, 390]) {
    await page.setViewportSize({ width, height: 780 });
    const attachmentActions = await page.locator('.create-evidence-picker').evaluate(picker => {
      const bounds = picker.getBoundingClientRect();
      const buttons = Array.from(picker.querySelectorAll('.evidence-actions button')).map(button => {
        const box = button.getBoundingClientRect();
        return { left: box.left, right: box.right, top: box.top, width: box.width, scrollWidth: button.scrollWidth };
      });
      return { left: bounds.left, right: bounds.right, scrollWidth: picker.scrollWidth, clientWidth: picker.clientWidth, buttons };
    });
    expect(attachmentActions.buttons).toHaveLength(2);
    expect(Math.abs(attachmentActions.buttons[0].width - attachmentActions.buttons[1].width)).toBeLessThanOrEqual(1);
    expect(Math.abs(attachmentActions.buttons[0].top - attachmentActions.buttons[1].top)).toBeLessThanOrEqual(1);
    expect(attachmentActions.buttons.every(button => button.left >= attachmentActions.left && button.right <= attachmentActions.right + 1)).toBe(true);
    expect(attachmentActions.scrollWidth).toBeLessThanOrEqual(attachmentActions.clientWidth);
  }
  await page.locator('#captureLocationBtn').click();
  await expect(page.locator('#captureLocationBtn')).toContainText('Location Captured');
  await expect(page.locator('#captureLocationBtn')).toHaveClass(/location-success/);
  await expect(page.locator('#captureState')).toHaveText('GPS: -1.261216, 36.842388');
  await expect(page.locator('#captureState')).toHaveClass(/location-coordinate/);
  await page.locator('[data-camera-target="create"]').click();
  expect(await page.locator('#cameraVideo').evaluate(video => [video.videoWidth, video.videoHeight])).toEqual([1280, 960]);
  await page.locator('#cameraCaptureBtn').click();
  await page.waitForTimeout(100);
  expect(pageErrors).toEqual([]);
  await expect(page.locator('#toast')).toContainText('Photo added');
  await expect(page.locator('#createSelectedEvidence li')).toHaveCount(1);
  await page.locator('#cameraCaptureBtn').click();
  await expect(page.locator('#createSelectedEvidence li')).toHaveCount(2);
  expect(pageErrors).toEqual([]);
  await expect(page.locator('#cameraOverlay')).toBeVisible();
  await expect(page.locator('#cameraCaptureState')).toContainText('2 photos added this session');
  await page.locator('#cameraCancelBtn').click();
  await expect(page.locator('#createSelectedEvidence li')).toHaveCount(2);

  await page.locator('#createSelectedEvidence .view-file').first().click();
  await expect(page.locator('#mediaViewerOverlay')).toBeVisible();
  await expect(page.locator('#mediaViewerSub')).toContainText('1 of 2');
  const viewerHeader = await page.evaluate(() => {
    const subtitle = document.getElementById('mediaViewerSub');
    const close = document.getElementById('mediaViewerClose');
    subtitle.textContent = `${'very-long-evidence-file-name-'.repeat(20)}.jpg`;
    const closeBox = close.getBoundingClientRect();
    return {
      closeWidth: closeBox.width,
      closeRight: closeBox.right,
      viewportWidth: window.innerWidth,
      filenameClipped: subtitle.scrollWidth > subtitle.clientWidth,
    };
  });
  expect(viewerHeader.closeWidth).toBe(40);
  expect(viewerHeader.closeRight).toBeLessThanOrEqual(viewerHeader.viewportWidth);
  expect(viewerHeader.filenameClipped).toBe(true);

  const dispatchViewerPointers = sequence => page.evaluate(events => {
    const target = document.getElementById('mediaViewerContent');
    events.forEach(item => target.dispatchEvent(new PointerEvent(item.type, {
      bubbles: true, cancelable: true, pointerId: item.id, pointerType: 'touch',
      clientX: item.x, clientY: item.y, buttons: item.type === 'pointerup' ? 0 : 1,
    })));
  }, sequence);
  await dispatchViewerPointers([
    { type: 'pointerdown', id: 1, x: 320, y: 300 },
    { type: 'pointermove', id: 1, x: 90, y: 305 },
    { type: 'pointerup', id: 1, x: 90, y: 305 },
  ]);
  await expect(page.locator('#mediaViewerSub')).toContainText('2 of 2');
  await dispatchViewerPointers([
    { type: 'pointerdown', id: 2, x: 80, y: 300 },
    { type: 'pointermove', id: 2, x: 310, y: 295 },
    { type: 'pointerup', id: 2, x: 310, y: 295 },
  ]);
  await expect(page.locator('#mediaViewerSub')).toContainText('1 of 2');

  await dispatchViewerPointers([
    { type: 'pointerdown', id: 3, x: 100, y: 300 },
    { type: 'pointerdown', id: 4, x: 200, y: 300 },
    { type: 'pointermove', id: 4, x: 300, y: 300 },
    { type: 'pointerup', id: 4, x: 300, y: 300 },
    { type: 'pointerup', id: 3, x: 100, y: 300 },
  ]);
  await expect(page.locator('#mediaViewerContent')).toHaveAttribute('data-zoom', '200');
  await expect.poll(() => page.locator('#mediaViewerContent .media-viewer-image').evaluate(image => image.style.width)).toBe('200%');
  await dispatchViewerPointers([
    { type: 'pointerdown', id: 5, x: 50, y: 300 },
    { type: 'pointerdown', id: 6, x: 250, y: 300 },
    { type: 'pointermove', id: 6, x: 100, y: 300 },
    { type: 'pointerup', id: 6, x: 100, y: 300 },
    { type: 'pointerup', id: 5, x: 50, y: 300 },
  ]);
  await expect(page.locator('#mediaViewerContent')).toHaveAttribute('data-zoom', '50');
  await page.locator('#mediaViewerNext').click();
  await expect(page.locator('#mediaViewerSub')).toContainText('2 of 2');
  await expect(page.locator('#mediaViewerContent')).toHaveAttribute('data-zoom', '100');
  await page.locator('#mediaViewerDelete').click();
  await expect(page.locator('#createSelectedEvidence li')).toHaveCount(1);
  await expect(page.locator('#mediaViewerSub')).toContainText('1 of 1');

  await page.locator('#mediaViewerRetake').click();
  await expect(page.locator('#cameraOverlay')).toBeVisible();
  await expect(page.locator('#cameraTitle')).toHaveText('Retake Photo');
  await expect(page.locator('#createSelectedEvidence li')).toHaveCount(1);
  await page.locator('#cameraCaptureBtn').click();
  await expect(page.locator('#cameraOverlay')).toBeHidden();
  await expect(page.locator('#mediaViewerOverlay')).toBeVisible();
  await expect(page.locator('#createSelectedEvidence li')).toHaveCount(1);
  await expect(page.locator('#mediaViewerSub')).toContainText('1 of 1');
});

test('Mini App bootstrap initializes Telegram once', async ({ page }) => {
  await page.setContent('<main id="app">Ready</main>');
  await page.evaluate(() => {
    window.__telegramCalls = { ready: 0, expand: 0, swipes: 0 };
    window.Telegram = { WebApp: {
      initData: 'synthetic-signed-init-data',
      ready() { window.__telegramCalls.ready += 1; },
      expand() { window.__telegramCalls.expand += 1; },
      disableVerticalSwipes() { window.__telegramCalls.swipes += 1; },
      disableClosingConfirmation() {},
    } };
  });
  await loadUtilities(page);
  await page.addScriptTag({ path: asset('telegram.js') });
  const result = await page.evaluate(() => {
    window.MiniAppTelegram.init();
    window.MiniAppTelegram.init();
    return window.__telegramCalls;
  });
  expect(result).toEqual({ ready: 1, expand: 1, swipes: 1 });
});

test('authentication failure renders reviewed Portal guidance', async ({ page }) => {
  await page.route('http://miniapp.test/**', route => route.fulfill({
    contentType: 'text/html',
    body: `<!doctype html><style>
      #sidebar { position: fixed; z-index: 2; width: 240px; height: 100%; transform: translateX(-100%); }
      #sidebar.open { transform: translateX(0); }
      #sidebar-backdrop { display: none; position: fixed; inset: 0; z-index: 1; }
      #sidebar-backdrop.open { display: block; }
    </style><body>
      <nav id="sidebar"><a class="shell-nav-link" data-screen="dashboard" href="/portal/s/dashboard/">Dashboard</a></nav>
      <button id="shell-menu-button" aria-expanded="false">Menu</button><div id="sidebar-backdrop"></div>
      <main id="content"><section id="portal-screen" data-top-level="true"></section></main>
    </body>`,
  }));
  await page.addInitScript(() => {
    window.Telegram = { WebApp: {
      ready() {}, expand() {}, disableVerticalSwipes() {}, disableClosingConfirmation() {},
      themeParams: {}, onEvent() {},
      BackButton: { onClick() {}, offClick() {}, show() {}, hide() {} },
      MainButton: { onClick() {}, offClick() {}, show() {}, hide() {}, setText() {} },
    } };
    window.PortalAppShell = { activate() {} };
  });
  await page.goto('http://miniapp.test/portal/s/dashboard/');
  await loadUtilities(page);
  await page.addScriptTag({ path: asset('miniapp-nav.js') });
  await page.evaluate(() => {
    const target = document.getElementById('portal-screen');
    document.body.dispatchEvent(new CustomEvent('htmx:responseError', {
      bubbles: true,
      detail: { target, xhr: { status: 403 } },
    }));
  });
  await expect(page.getByRole('alert')).toContainText(
    'Your Telegram account is not authorized for this Portal screen.',
  );
});

test('double-submit protection shares one browser request', async ({ page }) => {
  await page.setContent('<button id="submit">Submit</button>');
  await loadUtilities(page);
  const result = await page.evaluate(async () => {
    let calls = 0;
    let release;
    const operation = () => {
      calls += 1;
      return new Promise(resolve => { release = resolve; });
    };
    const first = window.MiniAppUtils.singleFlight('same-action-12345678', operation);
    const second = window.MiniAppUtils.singleFlight('same-action-12345678', operation);
    await Promise.resolve();
    const samePromise = first === second;
    release({ ok: true });
    await Promise.all([first, second]);
    return { calls, samePromise };
  });
  expect(result).toEqual({ calls: 1, samePromise: true });
});

async function installPortalRouteFixture(page) {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.addInitScript(() => {
    window.Telegram = { WebApp: {
      ready() {}, expand() {}, disableVerticalSwipes() {}, disableClosingConfirmation() {},
      enableClosingConfirmation() {}, themeParams: {}, onEvent() {},
      BackButton: {
        onClick(callback) { window.__backHandler = callback; }, offClick() {}, show() {}, hide() {},
      },
      MainButton: { onClick() {}, offClick() {}, show() {}, hide() {}, setText() {} },
    } };
    window.PortalAppShell = { activate(screen) { document.body.dataset.activated = screen; } };
  });
  await page.route('http://miniapp.test/**', route => {
    const pathname = new URL(route.request().url()).pathname;
    if (pathname.startsWith('/miniapp-assets/')) {
      return route.fulfill({ contentType: 'application/javascript', body: fs.readFileSync(asset(pathname.split('/').at(-1))) });
    }
    const screen = pathname.includes('/cases/') ? 'case_history' : pathname.match(/\/s\/([^/]+)\//)?.[1] || 'dashboard';
    return route.fulfill({ contentType: 'text/html', body: `<!doctype html><html><head><style>
      #sidebar { position: fixed; z-index: 2; width: 240px; height: 100%; transform: translateX(-100%); }
      #sidebar.open { transform: translateX(0); }
      #sidebar-backdrop { display: none; position: fixed; inset: 0; z-index: 1; }
      #sidebar-backdrop.open { display: block; }
    </style></head><body>
      <button id="shell-menu-button" aria-expanded="false">Menu</button>
      <aside id="sidebar"><a class="shell-nav-link" data-screen="all" href="/portal/s/all/">All cases</a><a class="shell-nav-link" data-screen="credit" href="/portal/s/credit/">Credit</a></aside>
      <div id="sidebar-backdrop"></div>
      <main id="content"><section id="portal-screen" data-screen="${screen}" ${screen === 'dashboard' || screen === 'credit' || screen === 'all' ? 'data-top-level="true"' : ''}>
        <h1>${screen}</h1><input id="draft"><a id="invoice-link" href="/portal/s/invoices/">Invoices</a>
      </section></main>
      <script src="/miniapp-assets/utils.js"></script><script src="/miniapp-assets/miniapp-nav.js"></script>
    </body></html>` });
  });
}

test('Portal links load a complete screen, survive reload, and Telegram Back stays inside Portal', async ({ page }) => {
  await installPortalRouteFixture(page);
  await page.goto('http://miniapp.test/portal/s/dashboard/');
  await page.locator('#shell-menu-button').click();
  await page.locator('#sidebar a[data-screen="credit"]').click();
  await expect(page).toHaveURL('http://miniapp.test/portal/s/credit/');
  await expect(page.locator('#portal-screen')).toHaveAttribute('data-screen', 'credit');
  await expect(page.locator('body')).toHaveAttribute('data-activated', 'credit');
  await page.reload();
  await expect(page.locator('body')).toHaveAttribute('data-activated', 'credit');
  await page.goto('http://miniapp.test/portal/cases/synthetic-case/');
  await page.locator('#shell-menu-button').click();
  await expect(page.locator('#sidebar')).toHaveClass(/open/);
  await page.mouse.click(370, 420);
  await expect(page.locator('#sidebar')).not.toHaveClass(/open/);
  await page.evaluate(() => window.__backHandler());
  await expect(page).toHaveURL('http://miniapp.test/portal/s/all/');
  await expect(page.locator('body')).toHaveAttribute('data-activated', 'all');
});

test('Portal route guard retains dirty edits and an in-flight action', async ({ page }) => {
  await installPortalRouteFixture(page);
  await page.goto('http://miniapp.test/portal/s/dashboard/');
  await page.evaluate(() => window.MiniAppUtils.setCloseProtection('test-draft', true));
  page.once('dialog', dialog => dialog.dismiss());
  await page.locator('#shell-menu-button').click();
  await page.locator('#sidebar a[data-screen="credit"]').click();
  await page.waitForTimeout(200);
  await expect(page).toHaveURL('http://miniapp.test/portal/s/dashboard/');
  await page.evaluate(() => window.MiniAppUtils.setCloseProtection('test-draft', false));
  await page.evaluate(() => window.MiniAppUtils.setCloseProtection('network-write:test', true));
  expect(await page.evaluate(() => window.MiniAppUtils.canNavigatePage())).toBe(false);
  await page.locator('#sidebar a[data-screen="credit"]').click();
  await page.waitForTimeout(200);
  await expect(page).toHaveURL('http://miniapp.test/portal/s/dashboard/');
  await page.evaluate(() => window.MiniAppUtils.setCloseProtection('network-write:test', false));
  await page.locator('#sidebar a[data-screen="credit"]').click();
  await expect(page).toHaveURL('http://miniapp.test/portal/s/credit/');
});

test('Case inspection allows only recovery autosaves, not submissions or invoice edits',async({page})=>{
  await installPortalRouteFixture(page);
  await page.goto('http://miniapp.test/portal/s/dashboard/');
  let pendingRoute;
  await page.route('http://miniapp.test/api/portal/**',route=>{pendingRoute=route;});
  for(const [endpoint,allowed] of [['jbl-queue/case-1/draft/',true],['credit-queue/case-1/draft/',true],['final-review-queue/case-1/draft/',true],['jbl-queue/case-1/complete-visit/',false],['invoice-pool/invoice-1/draft/',false]]){
    pendingRoute=null;
    await page.evaluate(path=>{window.pendingAction=fetch('/api/portal/'+path,{method:'POST',body:'{}'});},endpoint);
    await expect.poll(()=>Boolean(pendingRoute)).toBe(true);
    expect(await page.evaluate(()=>MiniAppUtils.canNavigatePage('/portal/cases/case-1/',{preserveEdits:true}))).toBe(allowed);
    expect(await page.evaluate(()=>MiniAppUtils.canNavigatePage('/portal/s/all/'))).toBe(false);
    await pendingRoute.fulfill({status:200,body:'{}'});
    await page.evaluate(()=>window.pendingAction);
    expect(await page.evaluate(()=>MiniAppUtils.canNavigatePage('/portal/cases/case-1/',{preserveEdits:true}))).toBe(true);
  }
});

test('Case History click does not create a blocking save and Back retains edits and photos',async({page})=>{
  await installPortalRouteFixture(page);
  await page.goto('http://miniapp.test/portal/s/dashboard/');
  await page.route('http://miniapp.test/portal/cases/case-1/**',route=>route.fulfill({contentType:'text/html',body:'<section id="portal-screen" data-screen="case_history" data-case-farmer-id="case-1"><a class="case-history-back" href="/portal/s/dashboard/" data-return-screen="dashboard" aria-label="Back"><span class="sr-only">Back</span></a></section>'}));
  await page.evaluate(()=>{
    document.getElementById('portal-screen').insertAdjacentHTML('beforeend','<input id="retained-village"><input id="retained-photo" type="file"><a id="case360-toggle" href="/portal/cases/case-1/?from=jbl">Case History</a>');
    window.__saves=0;window.__messages=[];
  });
  await page.addScriptTag({path:asset('portal_case_navigation.js')});
  const handler=fs.readFileSync(asset('portal_farmer_sheet.js'),'utf8').match(/    caseToggle.onclick = event => \{[^]*?\n    \};/)[0];
  await page.addScriptTag({content:`
    const caseToggle=document.getElementById('case360-toggle'),mode='jbl_visit',farmer={id:'case-1'},WORKFLOW_DRAFT_CONFIG={};
    const saveJblVisitDraft=()=>{window.__saves++;MiniAppUtils.setCloseProtection('network-write:unexpected-save',true);};
    const saveWorkflowDraft=saveJblVisitDraft;
    PortalCaseNavigation.init({hasCapability:()=>true,headers:()=>({}),showToast:message=>window.__messages.push(message),activate:()=>{}});
    ${handler}
  `});
  await page.locator('#retained-village').fill('Test village');
  await page.locator('#retained-photo').setInputFiles({name:'Test.jpg',mimeType:'image/jpeg',buffer:Buffer.from('synthetic photo')});
  await page.locator('#case360-toggle').click();
  await expect(page.locator('#portal-screen')).toHaveAttribute('data-screen','case_history');
  expect(await page.evaluate(()=>window.__saves)).toBe(0);
  expect(await page.evaluate(()=>window.__messages)).not.toContain('Please wait for the current action to finish.');
  await page.evaluate(()=>PortalCaseNavigation.back());
  await expect(page.locator('#retained-village')).toHaveValue('Test village');
  expect(await page.locator('#retained-photo').evaluate(input=>input.files[0].name)).toBe('Test.jpg');
});

test('Case History and media controls align symmetrically in operational forms',async({page},testInfo)=>{
  for(const classes of ['jbl-visit-sheet','credit-analysis-sheet','operational-detail-sheet']){
    await page.setContent(`<body class="workflow-standard portal-app"><div class="sheet-overlay open"><section class="sheet-panel ${classes}"><div class="sheet-quick-actions has-client-media"><section class="sheet-client-media"><button class="btn btn-secondary sheet-client-media-toggle"><svg viewBox="0 0 24 24"></svg><span>3 Media Files</span></button></section><a class="btn btn-secondary case360-toggle" href="#"><svg viewBox="0 0 24 24"></svg><span>Case History</span></a></div></section></div></body>`);
    for(const name of ['base.css','workflow_standard.css','portal.css'])await page.addStyleTag({path:asset(name)});
    for(const width of [390,1280]){
      await page.setViewportSize({width,height:700});
      const media=await page.locator('.sheet-client-media-toggle').boundingBox();
      const history=await page.locator('.case360-toggle').boundingBox();
      expect(Math.abs(media.y-history.y)).toBeLessThan(1);
      expect(Math.abs(media.height-history.height)).toBeLessThan(1);
      expect(Math.abs(media.width-history.width)).toBeLessThan(1);
    }
    await page.screenshot({path:testInfo.outputPath(`history-alignment-${classes}.png`)});
  }
});

test('multipart upload failure can retry with the same request key', async ({ page }) => {
  await page.setContent('<main>Upload</main>');
  await page.evaluate(() => {
    window.__requests = [];
    window.__attempt = 0;
    window.fetch = async (url, options) => {
      window.__requests.push({
        url,
        requestId: options.headers['X-Request-ID'],
        idempotencyKey: options.headers['Idempotency-Key'],
      });
      window.__attempt += 1;
      if (window.__attempt === 1) throw new TypeError('synthetic network failure');
      return new Response(JSON.stringify({ ok: true }), {
        status: 200, headers: { 'Content-Type': 'application/json' },
      });
    };
  });
  await loadUtilities(page);
  await page.addScriptTag({ path: asset('order_approval_api.js') });
  const result = await page.evaluate(async () => {
    const form = new FormData();
    form.set('group_id', '-100-synthetic');
    try { await window.OrderApprovalMiniAppApi.postForm('/api/order-approval/webapp/submit/', form); } catch (_) {}
    const response = await window.OrderApprovalMiniAppApi.postForm('/api/order-approval/webapp/submit/', form);
    return { response, key: form.get('client_request_id'), requests: window.__requests };
  });
  expect(result.response.ok).toBe(true);
  expect(result.requests).toHaveLength(2);
  expect(result.requests[0].requestId).toBe(result.key);
  expect(result.requests[1].requestId).toBe(result.key);
  expect(result.requests[1].idempotencyKey).toBe(result.key);
});

test('Portal dialogs trap focus, protect edits, and restore the opener', async ({ page }) => {
  await page.setContent(`
    <button id="open-dialog" type="button">Open case</button>
    <div id="sheet-overlay" class="sheet-overlay" role="dialog" aria-modal="true">
      <div class="sheet-panel">
        <button id="sheet-close" type="button">Close</button>
        <label>Comment<textarea id="case-comment"></textarea></label>
        <button id="save-case" type="button">Save</button>
      </div>
    </div>
    <style>.sheet-overlay { display:none }.sheet-overlay.open { display:block }</style>
  `);
  await page.evaluate(() => {
    window.__closingCalls = [];
    window.Telegram = { WebApp: {
      ready() {}, expand() {}, disableVerticalSwipes() {},
      enableClosingConfirmation() { window.__closingCalls.push('enable'); },
      disableClosingConfirmation() { window.__closingCalls.push('disable'); },
    } };
  });
  await loadUtilities(page);
  await page.addScriptTag({ path: asset('portal_dialogs.js') });
  await page.evaluate(() => {
    const opener = document.getElementById('open-dialog');
    const overlay = document.getElementById('sheet-overlay');
    opener.addEventListener('click', () => overlay.classList.add('open'));
    document.getElementById('sheet-close').addEventListener('click', () => overlay.classList.remove('open'));
  });

  await page.locator('#open-dialog').click();
  await expect(page.locator('#sheet-close')).toBeFocused();
  await page.keyboard.press('Shift+Tab');
  await expect(page.locator('#save-case')).toBeFocused();
  await page.locator('#case-comment').fill('Reviewed in the field');
  await expect.poll(() => page.evaluate(() => window.__closingCalls.includes('enable'))).toBe(true);
  await page.keyboard.press('Escape');
  await expect(page.locator('#sheet-overlay')).not.toHaveClass(/open/);
  await expect(page.locator('#open-dialog')).toBeFocused();
  await expect.poll(() => page.evaluate(() => window.__closingCalls.at(-1))).toBe('disable');
});

test('Portal pinned shell dependencies load without runtime CDNs', async ({ page }) => {
  await page.setContent('<main><i data-lucide="menu"></i><div id="map"></div></main>');
  await page.addScriptTag({ path: asset('vendor-htmx-2.0.4.min.js') });
  await page.addScriptTag({ path: asset('vendor-lucide-1.44.0.min.js') });
  await page.addScriptTag({ path: asset('vendor-leaflet-1.9.4.js') });
  const loaded = await page.evaluate(() => {
    window.lucide.createIcons();
    return {
      htmx: window.htmx.version,
      lucide: Boolean(document.querySelector('svg.lucide-menu')),
      leaflet: window.L.version,
    };
  });
  expect(loaded).toEqual({ htmx: '2.0.4', lucide: true, leaflet: '1.9.4' });
});

function signingHtml() {
  return `<!doctype html><body>
    <main class="sign-shell" data-session-url="/api/origination/sign/api/session/">
      <div id="sign-status"></div><section id="sign-content" hidden>
        <strong id="sign-reference"></strong><strong id="sign-role"></strong><strong id="sign-phone"></strong>
        <div id="signing-mode-banner"></div><span id="signing-mode-label"></span><span id="signing-mode-detail"></span>
        <div id="shared-phone-warning" hidden></div><div id="document-list"></div>
        <span id="packet-consent-text"></span><div id="preview-loading"></div><img id="packet-page" hidden>
        <span id="page-label"></span><button id="page-prev"></button><button id="page-next"></button>
        <canvas id="signature-pad" width="800" height="260"></canvas><button id="signature-clear"></button>
        <button id="mode-drawn" class="active"></button><button id="mode-typed"></button>
        <div id="draw-panel"></div><label id="type-panel" hidden><input id="typed-name"></label>
        <label><input id="packet-consent" type="checkbox"></label>
        <label id="assisted-confirmation" hidden><input id="assisted-consent" type="checkbox"></label>
        <button id="save-signature">Save signature</button><button id="send-otp" disabled>Send code</button>
        <div id="otp-panel" hidden><input id="otp-code"><span id="otp-detail"></span>
          <button id="verify-otp">Verify</button></div>
      </section>
    </main>
  </body>`;
}

test('Origination signing completes its happy path with test-mode services', async ({ page }) => {
  let session = {
    test_mode: true,
    reference: 'SYNTHETIC-LAF-001', signer_role: 'borrower', phone_masked: '+254 *** 001',
    shared_phone_override: false, access_mode: 'remote', documents: [{ key: 'laf', name: 'Loan form', page_count: 1 }],
    reviewed_pages: [], consented: false, status: 'pending', otp: {}, packet_version: 'test-v1',
  };
  await page.route('http://miniapp.test/**', async route => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith('/packet/')) {
      return route.fulfill({
        status: 200, body: 'synthetic-image', contentType: 'image/png',
        headers: { 'X-Preview-Page-Count': '1', 'X-Signing-Packet-Version': 'test-v1' },
      });
    }
    if (url.pathname.endsWith('/consent/')) session = { ...session, consented: true, reviewed_pages: [1] };
    if (url.pathname.endsWith('/otp/')) session = { ...session, otp: { expires_at: '2026-08-31T22:00:00Z' } };
    if (url.pathname.endsWith('/verify/')) {
      session = { ...session, status: 'verified', completion_text: 'Synthetic signing complete.' };
    }
    return route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ ok: true, session }),
    });
  });
  await page.route('http://miniapp.test/sign', route => route.fulfill({
    status: 200, contentType: 'text/html', body: signingHtml(),
  }));
  await page.goto('http://miniapp.test/sign#synthetic-test-token');
  await loadUtilities(page);
  await page.addScriptTag({ path: asset('origination_signing.js') });
  await expect(page.locator('#sign-content')).toBeVisible();
  await expect(page.locator('#page-label')).toHaveText('1 / 1');
  await page.locator('#mode-typed').click();
  await page.locator('#typed-name').fill('Synthetic Borrower');
  await page.locator('#packet-consent').check();
  await page.locator('#save-signature').click();
  await expect(page.locator('#sign-status')).toContainText('signature is ready');
  await page.locator('#send-otp').click();
  await expect(page.locator('#otp-panel')).toBeVisible();
  await page.locator('#otp-code').fill('123456');
  await page.locator('#verify-otp').click();
  await expect(page.locator('#sign-status')).toHaveText('Synthetic signing complete.');
});
