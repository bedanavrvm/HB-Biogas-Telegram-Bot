'use strict';
const fs = require('node:fs');
const path = require('node:path');
const {test, expect} = require('playwright/test');
const {mountPortalShell} = require('./fixtures/portal_shell');
const asset = name => path.resolve(__dirname, '../static/miniapp', name);
const template = fs.readFileSync(path.resolve(__dirname, '../templates/portal/portal.html'), 'utf8');
const sheet = template.slice(template.indexOf('<div class="sheet-overlay" id="sheet-overlay"'), template.indexOf('<!-- Invoice upload overlay -->'));

// Run the real sheet module, real overlay markup and production CSS cascade.
// Only identity, API replies and evidence bytes are synthetic; no remote calls.
async function mountReview(page, mode = 'final_review') {
  await page.route('http://127.0.0.1:8000/portal/',route=>route.fulfill({contentType:'text/html',body:'<!doctype html><html><body></body></html>'}));
  await page.goto('http://127.0.0.1:8000/portal/');
  await mountPortalShell(page, `<main id="content"><section id="portal-screen" data-history-source="credit"><div id="case360"></div></section>${sheet}</main>`);
  await page.addScriptTag({path:asset('secure_media_viewer.js')});
  await page.addScriptTag({path:asset('portal_farmer_sheet.js')});
  await page.evaluate(mode => {
    const el = id => document.getElementById(id);
    const escapeHtml = value => {const node = document.createElement('span'); node.textContent = String(value ?? ''); return node.innerHTML;};
    window.fixtureState = {
      capabilities:new Set(['portal.credit.write','portal.final_review.write','portal.case.read','portal.jbl_media.view']),
      metaDecisions:['Pending','Approved','Rejected','Deferred / On Hold'], metaImabOptions:['Yes','No','Pending'],
      metaFinalDecisions:['Approved','Rejected','Deferred / On Hold'],
      metaPipelineReasons:{rejected:[{value:'r01',label:'Affordability'},{value:'r07',label:'Other reason'}],deferred:[{value:'d01',label:'Customer deciding'},{value:'d12',label:'Other reason'}]},
      voiceInput:{enabled:true,fields:['credit_decision_comment','final_decision_comment']},
    };
    window.fixtureCase = {id:'synthetic-case',customer_name:'Synthetic training customer',county:'Training county',
      workflow_revision:1, credit_decision:'Approved',imab_created:'Yes',customer_no:'90001',
      final_decision:'Approved',repayment_day:12,repayment_tenor_months:24,jbl_media_count:3,
      final_decision_comment:'Customer prefers an afternoon installation.',product_terms:{}};
    window.requests = []; window.toasts = [];
    window.PortalMiniAppFarmerSheet.init({el,state:window.fixtureState,escapeHtml,fmt:value=>value || '-',fmtDate:value=>value || '-',
      locationText:()=> 'Training county',setButtonLoading:()=>{},onClose:()=>{},
      apiFetch:async(url,options)=>{window.requests.push({url,body:options?.body}); return {ok:true,data:{ok:true,media:[]}};},
      showToast:message=>window.toasts.push(message),reloadCurrentQueue:async()=>{},loadDashboard:async()=>{},
    });
    window.PortalMiniAppFarmerSheet.openFarmerSheet(window.fixtureCase, mode);
  },mode);
  await page.evaluate(()=>window.lucide.createIcons());
}

for (const width of [320,360,390,430,768,1280]) for (const theme of ['light','dark']) {
  test(`Final review aligns at ${width}px ${theme}`,async({page},info)=>{
    await page.setViewportSize({width,height:850});
    await mountReview(page);
    if(theme==='dark') await page.evaluate(()=>{
      for(const [key,value] of Object.entries({bg:'#111827',secondary_bg:'#1f2937',text:'#f9fafb',hint:'#cbd5e1',button:'#38bdf8',button_text:'#082f49'})) {
        document.documentElement.style.setProperty(`--tg-theme-${key.replaceAll('_','-')}-color`,value);
      }
    });
    const controls = ['#final-decision','#final-repayment-date','#final-repayment-tenor'];
    const boxes = await Promise.all(controls.map(selector=>page.locator(selector).boundingBox()));
    for(const box of boxes) {expect(box.height).toBeGreaterThanOrEqual(40); expect(Math.abs(box.height-boxes[0].height)).toBeLessThan(2);}
    expect(Math.abs(boxes[1].y-boxes[2].y)).toBeLessThan(2);
    expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    await expect(page.locator('#sheet-form')).not.toContainText('Day of the month');
    await page.locator('#final-ready-comment').click();
    await expect(page.locator('#final-comment')).toHaveValue('READY FOR INSTALLATION & PAYMENT\nCustomer prefers an afternoon installation.');
    await expect(page.locator('#final-ready-comment')).toBeDisabled();
    await page.locator('#final-decision').selectOption('Deferred / On Hold');
    await expect(page.locator('#final-ready-comment')).toBeHidden();
    await page.locator('#final-reason-code').selectOption('d01');
    await expect(page.locator('#final-comment')).not.toHaveAttribute('required');
    await page.locator('#final-decision').selectOption('Approved');
    await page.screenshot({path:info.outputPath(`final-review-${width}-${theme}.png`),animations:'disabled'});
  });
}

test('Negative credit hides IMAB, preserves existing identity, and requires only Other comment',async({page})=>{
  await mountReview(page,'credit');
  await page.locator('#credit-decision').selectOption('Deferred / On Hold');
  await expect(page.locator('#credit-imab-row')).toBeHidden();
  await expect(page.locator('#credit-customer-number-row')).toBeHidden();
  await page.locator('#credit-reason-code').selectOption('d01');
  await expect(page.locator('#credit-decision-comment')).not.toHaveAttribute('required');
  await page.locator('#credit-reason-code').selectOption('d12');
  await expect(page.locator('#credit-decision-comment')).toHaveAttribute('required','');
  await expect(page.getByRole('button',{name:'Dictate comment'})).toBeVisible();
  await page.locator('#credit-decision-comment').fill('Synthetic temporary issue');
  await page.locator('#credit-decision').selectOption('Approved');
  await expect(page.locator('#credit-customer-no')).toHaveValue('90001');
  await page.locator('#credit-decision').selectOption('Rejected');
  await page.locator('#credit-reason-code').selectOption('r01');
  await page.locator('#btn-submit-credit').click();
  const body = await page.evaluate(()=>JSON.parse(window.requests.find(request=>request.url==='/credit-queue/synthetic-case/').body));
  expect(body.decision).toBe('Rejected'); expect(body).not.toHaveProperty('imab_created'); expect(body).not.toHaveProperty('customer_no');
});

test('Gallery navigates, retries a failed document, and returns to the unchanged review',async({page},info)=>{
  await page.setViewportSize({width:390,height:850});
  await mountReview(page);
  await page.locator('#final-comment').fill('Unsaved review text');
  await page.locator('#final-comment').focus();
  await page.evaluate(()=>{
    window.evidenceCalls = []; let failed = false;
    window.fetch = async(url,options)=>{
      window.evidenceCalls.push({url,hasSignal:!!options.signal});
      if(url==='/synthetic/id' && !failed) {failed=true; return {ok:false,json:async()=>({message:'Synthetic interrupted download'})};}
      const image = new Blob(['<svg xmlns="http://www.w3.org/2000/svg" width="280" height="300"><rect width="280" height="300" fill="#dfeef7"/><text x="40" y="150">Training evidence</text></svg>'],{type:'image/svg+xml'});
      return {ok:true,blob:async()=>image};
    };
    window.gallery = [{preview_url:'/synthetic/photo',name:'Visit photo',mime_type:'image/svg+xml'},
      {preview_url:'/synthetic/id',name:'Client ID',mime_type:'image/svg+xml'},
      {preview_url:'/synthetic/laf',name:'LAF',mime_type:'image/svg+xml'}];
    window.PortalMiniAppFarmerSheet.openDocumentPreview(window.gallery[0],window.gallery);
  });
  await expect(page.locator('#media-viewer-content img')).toBeVisible();
  await expect(page.getByRole('button',{name:'Previous document'})).toBeDisabled();
  await page.getByRole('button',{name:'Next document'}).click();
  await expect(page.locator('#media-viewer-content')).toContainText('Synthetic interrupted download');
  await expect(page.locator('#client-media-gallery-controls')).toContainText('2 / 3');
  await page.getByRole('button',{name:'Retry',exact:true}).click();
  await expect(page.locator('#media-viewer-content img')).toBeVisible();
  await page.keyboard.press('ArrowRight');
  await expect(page.locator('#client-media-gallery-controls')).toContainText('3 / 3');
  await expect(page.getByRole('button',{name:'Next document'})).toBeDisabled();
  expect((await page.getByRole('button',{name:'Next document'}).boundingBox()).width).toBeCloseTo(44,1);
  await page.locator('#media-viewer-content img').dispatchEvent('pointerdown',{clientX:100,clientY:100});
  await page.locator('#media-viewer-content img').dispatchEvent('pointerup',{clientX:220,clientY:100});
  await expect(page.locator('#client-media-gallery-controls')).toContainText('2 / 3');
  await expect(page.locator('#media-viewer-content img')).toBeVisible();
  await page.locator('#media-viewer-content img').dispatchEvent('pointerdown',{clientX:220,clientY:100});
  await page.locator('#media-viewer-content img').dispatchEvent('pointerup',{clientX:100,clientY:100});
  await expect(page.locator('#client-media-gallery-controls')).toContainText('3 / 3');
  await expect(page.locator('#media-viewer-overlay')).toHaveCSS('opacity','1');
  await expect(page.locator('.media-viewer-panel')).toHaveCSS('background-color','rgb(255, 255, 255)');
  await page.screenshot({path:info.outputPath('gallery.png'),animations:'disabled'});
  await page.keyboard.press('Escape');
  await expect(page.locator('#media-viewer-overlay')).not.toHaveClass(/open/);
  await expect(page.locator('#sheet-overlay')).toHaveClass(/open/);
  await expect(page.locator('#final-comment')).toBeFocused();
  await expect(page.locator('#final-comment')).toHaveValue('Unsaved review text');
  expect(await page.evaluate(()=>window.evidenceCalls.map(call=>call.url))).toEqual(['/synthetic/photo','/synthetic/id','/synthetic/id','/synthetic/laf','/synthetic/id','/synthetic/laf']);
  expect(await page.evaluate(()=>window.evidenceCalls.every(call=>call.hasSignal))).toBe(true);
});

test('Case History keeps loan-cycle order for every entry source',async({page})=>{
  await mountReview(page);
  const order = ['identity','intake','jbl_visit','credit','final_review','order','invoice','homebiogas'];
  for(const source of ['jbl','my_visits','credit','final','all']) {
    await page.evaluate(({source,order})=>{
      document.getElementById('portal-screen').dataset.historySource=source;
      const sections = Object.fromEntries([...order].reverse().map(key=>[key,{}]));
      window.PortalMiniAppFarmerSheet.renderCase360({sections});
    },{source,order});
    expect(await page.locator('[data-case-section]').evaluateAll(nodes=>nodes.map(node=>node.dataset.caseSection))).toEqual(order);
    const selected = {jbl:'jbl_visit',my_visits:'jbl_visit',credit:'credit',final:'final_review'}[source];
    if(selected) await expect(page.locator(`[data-case-section="${selected}"]`)).toHaveAttribute('open','');
  }
});

test('Server-rendered PDF previews keep gallery controls inside the mobile viewport',async({page},info)=>{
  await page.setViewportSize({width:320,height:650});
  await mountReview(page);
  await page.evaluate(()=>{
    window.fetch = async()=>({ok:true,blob:async()=>new Blob([
      '<!doctype html><html><body><figure><img alt="Page 1" src="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j7ioAAAAASUVORK5CYII="></figure><figure><img alt="Page 2" src="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j7ioAAAAASUVORK5CYII="></figure></body></html>'
    ],{type:'text/html'})});
    const documents = [{preview_url:'/synthetic/pdf-1',name:'Synthetic LAF',mime_type:'application/pdf'},
      {preview_url:'/synthetic/pdf-2',name:'Synthetic ID',mime_type:'application/pdf'}];
    window.PortalMiniAppFarmerSheet.openDocumentPreview(documents[0],documents);
  });
  await expect(page.locator('#media-viewer-content img')).toBeVisible();
  await expect(page.locator('#media-viewer-content iframe')).toHaveCount(0);
  await expect(page.getByRole('button',{name:'Next document'})).toBeInViewport({ratio:1});
  await page.getByRole('button',{name:'Next document'}).click();
  await expect(page.locator('#client-media-gallery-controls')).toContainText('2 / 2');
  await expect(page.getByRole('button',{name:'Previous document'})).toBeInViewport({ratio:1});
  await expect(page.locator('#media-viewer-close')).toBeInViewport({ratio:1});
  await page.screenshot({path:info.outputPath('pdf-gallery-320.png'),animations:'disabled'});
});

test('Rejected cases stay inspectable without offering stale deferred stage actions',async({page})=>{
  await mountReview(page);
  await page.evaluate(()=>window.PortalMiniAppFarmerSheet.openFarmerSheet({...window.fixtureCase,
    workflow_state:'rejected',deferred_stage:'credit',credit_decision:'Rejected',
    approvals:{credit:{comment:'Synthetic rejected reason'}}},'deferred'));
  await expect(page.locator('#sheet-header-status')).toHaveText('Rejected');
  await expect(page.locator('#sheet-form')).toContainText('Rejected case');
  await expect(page.locator('#sheet-form')).toContainText('Synthetic rejected reason');
  await expect(page.locator('#sheet-form')).not.toContainText('Review due');
  await expect(page.locator('#sheet-footer button')).toHaveCount(0);
});

test('Late media is aborted and cannot replace the newer selection; Telegram Back closes preview only',async({page})=>{
  await mountReview(page);
  await page.evaluate(()=>{
    window.Telegram={WebApp:{onEvent(){},BackButton:{onClick(fn){window.telegramBack=fn;},offClick(){},show(){},hide(){}}}};
    window.abortSeen=false;
    window.fetch=async(url,options)=> {
      if(url==='/synthetic/slow') return new Promise(resolve=>{
        options.signal.addEventListener('abort',()=>{window.abortSeen=true;});
        window.finishSlow=()=>resolve({ok:true,blob:async()=>new Blob(['old'],{type:'text/plain'})});
      });
      return {ok:true,blob:async()=>new Blob(['new'],{type:'text/plain'})};
    };
    window.gallery=[{preview_url:'/synthetic/slow',name:'Old file'},{preview_url:'/synthetic/new',name:'New file'}];
    window.PortalMiniAppFarmerSheet.openDocumentPreview(window.gallery[0],window.gallery);
  });
  await page.addScriptTag({path:asset('miniapp-nav.js')});
  await page.getByRole('button',{name:'Next document'}).click();
  await expect(page.locator('#media-viewer-content iframe')).toHaveAttribute('title','New file');
  await page.evaluate(()=>window.finishSlow());
  await expect(page.locator('#media-viewer-content iframe')).toHaveAttribute('title','New file');
  expect(await page.evaluate(()=>window.abortSeen)).toBe(true);
  await page.evaluate(()=>window.telegramBack());
  await expect(page.locator('#media-viewer-overlay')).not.toHaveClass(/open/);
  await expect(page.locator('#sheet-overlay')).toHaveClass(/open/);
});

test('Review maps use labelled street detail and retain user zoom on refresh',async({page})=>{
  await mountReview(page,'credit');
  await page.evaluate(()=>{
    window.mapViews=[]; window.mapSizes=0; window.tileUrls=[];
    class TileLayer {addTo(){return this;} on(){return this;} setUrl(url){window.tileUrls.push(url);return this;} redraw(){return this;}}
    window.L={TileLayer,divIcon:()=>({}),map:()=>({
      setView(coords,zoom){window.mapViews.push({coords,zoom});return this;},
      eachLayer(fn){fn(new TileLayer());},invalidateSize(){window.mapSizes++;},remove(){},
    }),tileLayer:url=>{window.tileUrls.push(url);return new TileLayer();},
    marker:()=>({addTo(){return this;},bindPopup(){return this;},setLatLng(){return this;}})};
    window.fixtureState.cartoBasemaps={enabled:true,light_url:'/synthetic/labelled-tiles',dark_url:'/synthetic/overview-tiles'};
    window.PortalMiniAppFarmerSheet.openFarmerSheet({...window.fixtureCase,latitude:-0.25,longitude:36.1},'credit');
  });
  await expect.poll(()=>page.evaluate(()=>window.mapViews.length)).toBe(1);
  await page.locator('#sheet-map-refresh').click();
  expect(await page.evaluate(()=>window.mapViews)).toEqual([{coords:[-0.25,36.1],zoom:18}]);
  expect(await page.evaluate(()=>window.tileUrls.every(url=>url==='/synthetic/labelled-tiles'))).toBe(true);
  await expect.poll(()=>page.evaluate(()=>window.mapSizes)).toBeGreaterThan(0);
});

test('Home shows compact first-load progress and retains work through a failed refresh',async({page},info)=>{
  await page.setViewportSize({width:320,height:850});
  const home = template.slice(template.indexOf('<section id="page-dashboard"'),template.indexOf('<div id="dashboard-legacy"'));
  await mountPortalShell(page, `<main id="content"><div id="portal-screen" data-screen="dashboard">${home}</section></div></main>`);
  const source = fs.readFileSync(asset('portal.js'),'utf8');
  const loader = source.slice(source.indexOf('  async function loadDashboard('),source.indexOf('  function renderPortalHome()'));
  await page.addScriptTag({content:`
    const el = id => document.getElementById(id);
    const state = {}; let dashboardLoading = false; let dashboardLoadVersion = 0;
    const isCurrentScreen = screen => screen === 'dashboard';
    const utils = {}; const escapeHtml = value => {const node = document.createElement('span');node.textContent = value;return node.innerHTML;};
    const markPortalFresh = () => {}; const renderPortalNotifications = () => {};
    const canManagePortalWorkspace = () => false;
    const fetchDashboardPayload = () => new Promise(resolve => window.finishHomeRequest = resolve);
    const renderPortalHome = () => {
      el('portal-home-actions').hidden = false;
      el('portal-home-actions-list').textContent = 'Synthetic customer: log visit';
    };
    ${loader}
    window.refreshHome = loadDashboard;
    window.refreshHome();
  `});
  await expect(page.locator('#dash-loading .spinner-inline')).toBeVisible();
  await expect(page.locator('#dash-loading')).toHaveAttribute('aria-busy','true');
  const heading = await page.locator('.dashboard-intro').boundingBox();
  const refresh = await page.locator('#dashboard-refresh').boundingBox();
  expect(refresh.y).toBeLessThan(heading.y+15);
  expect(refresh.x+refresh.width).toBeCloseTo(heading.x+heading.width,1);
  const rows = await page.locator('.dashboard-skeletons span').evaluateAll(nodes=>nodes.map(node=>({x:node.getBoundingClientRect().x,y:node.getBoundingClientRect().y,height:node.getBoundingClientRect().height})));
  expect(rows).toHaveLength(3);
  expect(new Set(rows.map(row=>row.x)).size).toBe(1);
  expect(rows[1].y).toBeGreaterThan(rows[0].y+rows[0].height);
  await page.screenshot({path:info.outputPath('home-loading-320.png'),animations:'disabled'});
  await page.evaluate(()=>window.finishHomeRequest({ok:true,data:{calculated_at:'2026-10-06T08:00:00+03:00'}}));
  await expect(page.locator('#portal-home-actions')).toBeVisible();
  await page.evaluate(()=>{window.refreshHome();});
  await expect(page.locator('#portal-home-actions-list')).toHaveText('Synthetic customer: log visit');
  await expect(page.locator('.dashboard-skeletons')).toHaveCount(0);
  await expect(page.locator('#dashboard-refresh')).toBeDisabled();
  await page.evaluate(()=>window.finishHomeRequest({ok:false,status:503,data:{message:'Synthetic connection failure'}}));
  await expect(page.getByRole('button',{name:'Retry',exact:true})).toBeVisible();
  await expect(page.locator('#portal-home-actions')).toBeVisible();
  await expect(page.locator('#dashboard-refresh')).toBeEnabled();
});

test('Camera uses one document target and an accessible icon-only capture control',async({page})=>{
  await mountReview(page);
  const source = fs.readFileSync(asset('portal_farmer_sheet.js'),'utf8');
  const captureState = source.slice(source.indexOf('  function updateJblCameraCaptureState()'),source.indexOf('  function setJblCameraTarget('));
  await page.addScriptTag({content:`
    const el = id => document.getElementById(id); const state = () => ({});
    const jblDocumentSlots = {CLIENT_ID:2,LAF:2};
    const jblDocumentLabels = {CLIENT_ID:['Front','Back'],LAF:['Page 1','Page 2']};
    const jblMediaSelections = {CLIENT_ID:[],LAF:[],JBL_VISIT_PHOTO:[]};
    let jblCameraCategory = 'CLIENT_ID', jblCameraSide = 0, jblCameraReplaceId = '', jblCameraStream = null;
    ${captureState}
    el('jbl-camera-overlay').classList.add('open');
    updateJblCameraCaptureState();
    window.testRetake = () => {jblCameraReplaceId='synthetic-photo'; updateJblCameraCaptureState();};
  `});
  await expect(page.locator('#jbl-live-camera-title')).toHaveText('Client ID — Front');
  await expect(page.locator('#jbl-camera-capture-state')).toBeEmpty();
  await expect(page.locator('#jbl-camera-shutter')).toHaveAttribute('aria-label','Capture Client ID Front');
  await expect(page.locator('#jbl-camera-shutter')).toHaveText('');
  await expect(page.locator('#jbl-camera-shutter svg')).toBeVisible();
  await page.evaluate(()=>window.testRetake());
  await expect(page.locator('#jbl-camera-shutter')).toHaveAttribute('aria-label','Retake Client ID Front');
  await expect(page.locator('#jbl-camera-capture-state')).toBeEmpty();
});
