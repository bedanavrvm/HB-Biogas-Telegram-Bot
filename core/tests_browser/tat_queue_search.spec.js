'use strict';
const fs = require('node:fs');
const path = require('node:path');
const {test, expect} = require('playwright/test');
const asset = name => path.resolve(__dirname, '../static/miniapp', name);
const reportPanelViews = JSON.parse(fs.readFileSync(path.resolve(__dirname,'../services/tat_presentation.py'),'utf8')
  .match(/REPORT_PANEL_VIEWS = (\{[\s\S]*?\})/)[1].replace(/'/g,'"').replace(/,\s*}/,'}'));
const source = fs.readFileSync(path.resolve(__dirname, '../templates/tat_tracker/app.html'), 'utf8');
const markup = source.slice(source.indexOf('<main class="tat-app"'), source.lastIndexOf('</main>') + 7)
  .replace(/{%[\s\S]*?%}|{{[\s\S]*?}}/g, '').replace(/<img[^>]*>/g, '');

async function mount(page, reports = false, native = false) {
  await page.route(/^https?:\/\//, route => route.request().url()==='http://miniapp.test/'
    ? route.fulfill({contentType:'text/html',body:'<!doctype html><html></html>'}) : route.abort());
  if(native)await page.goto('http://miniapp.test/');
  await page.setContent(`<!doctype html><html lang="en-KE"><head><meta name="viewport" content="width=device-width,initial-scale=1"></head><body>${markup}</body></html>`);
  for (const name of ['base.css','components.css','tat_tracker.css']) await page.addStyleTag({content:fs.readFileSync(asset(name),'utf8').replace(/^@import[^\r\n]*(?:\r?\n|$)/gm,'')});
  await page.evaluate(({reports,native,reportPanelViews}) => {
    if (native) {
      window.__handlers=new Set(); window.__native={show(){this.visible=true;},hide(){this.visible=false;},setText(){},enable(){},disable(){},hideProgress(){},
        onClick(fn){__handlers.add(fn);},offClick(fn){__handlers.delete(fn);}};
      window.Telegram={WebApp:{initData:'synthetic-only',ready(){},expand(){},onEvent(){},MainButton:__native,BackButton:{show(){},hide(){},onClick(){}}}};
    }
    window.__calls = [];
    const summary = {case_id:'JBL-TEST-1',client_name:'Synthetic Applicant',national_id:'12345678',primary_phone:'712345678',branch:'Training',bro_name:'Synthetic BRO',product:'Training product',status:'Active',amount:'10000',next_stage:'Visit',next_role:'BRO'};
    const roster = [{id:7,name:'Synthetic BRO',username:'synthetic-bro'}, {id:8,name:'Synthetic BRO',username:'synthetic-other'}];
    const home = body => ({queue:body.queue||'role',items:[{...summary,client_name:body.query||summary.client_name}],metrics:{role:1,total:1},pagination:{page:body.page||1,pages:1,total:1,page_size:10},visibility:{}});
    window.TatMiniAppApi = {postJson:async (url, body) => {
      window.__calls.push({url,body});
      if(url.includes('bootstrap')) return {ok:true,data:{authorized:true,presentation:{report_panel_views:reportPanelViews},user:{name:'Synthetic Officer',roles:['IT'],capabilities:['tat.home.view','tat.case.search','tat.case.create', ...(reports?['tat.reports.view','tat.reports.export',...(reports==='all'?Object.keys(reportPanelViews).map(key=>'tat.reports.insight.'+key):['tat.reports.insight.trend'])]:[])]},products:[{key:'business',label:'Training product'}],branches:['Training'],bro_users:window.__emptyRoster?[]:roster,statuses:[],...home({})}};
      if(url.includes('/home/')) { if(body.query==='slow') await new Promise(resolve=>setTimeout(resolve,650)); return {ok:true,data:home(body)}; }
      if(url.includes('/detail/')) return {ok:true,data:{summary:{...summary,next_stage:window.__nextStage||summary.next_stage,primary_phone:window.__phone??summary.primary_phone},credit_assessment_enabled:false,can_correct_details:true,correction_branches:['Training'],correction_bro_users:roster,fields:window.__fields||[],events:[],timeline:window.__timeline||[]}};
      if(url.includes('/tasks/')) {
        if(window.__taskError)throw new Error('Synthetic network failure');
        const all=Array.from({length:23},(_,i)=>({task_id:String(i),case_id:'TASK-'+i,client_name:'Training '+i,stage_label:'Visit',role:'BRO',unread:window.__unread!==false}));
        const offset=body.offset||0; return {ok:true,data:{items:all.slice(offset,offset+10),total:all.length,unread_count:window.__unread===false?0:23,pagination:{offset,page_size:10,has_more:offset+10<all.length}}};
      }
      return {ok:true,data:{}};
    }};
    if (reports) window.fetch = async (url, options) => {
      const body = JSON.parse(options.body); __calls.push({url,body});
      if(url.includes('/export/'))return new Response(JSON.stringify({ok:true,data:{download_url:'https://miniapp.test/synthetic-download',filename:'tat-report-13-10-26.xlsx'}}));
      const chart = {id:'trend',title:'Completed actions',basis:'completed_stage_actions',sample_count:2,labels:['2026-10-01','2026-10-02'],
        series:window.__multiTrend ? [{key:'created',label:'Created',values:[1,1]},{key:'disbursed',label:'Disbursed',values:[3,4]}] : [{key:'completed_actions',label:'Actions',values:[1,1]}],drilldown:{available:!window.__historical,reason:'Individual cases aren’t available for this historical total.'}};
      const key=body.insight||'trend';chart.id=key;
      chart.interpretation=key==='tat_percentiles' ? 'Median is the middle completion time. P90 is the time within which 90% finished.' : 'Each point shows the last recorded queue size for that period.';
      chart.scope_note='Scope: all records you are allowed to view.';
      chart.filter_guidance={applicable_filters:['search','branch','product','status'],basis_changing_filters:[],chart_controls:[],unavailable_filters:[{key:'stage',reason:'Stage narrows the table, not this graph.'}]};
      const visiblePanelKeys=Object.keys(reportPanelViews).filter(k=>reportPanelViews[k]===(body.view||'current')&&(reports==='all'||k==='trend'));
      const result = url.includes('/summary/') ? {response_mode:'focused_v1',metrics:{},filters:{stages:[['training','Training stage']]},visible_panel_keys:visiblePanelKeys,charts:{[key]:chart}}
        : {results:[{case_id:body.drill_bucket?'TAT-SELECTED':'TAT-ALL',client_name:'Synthetic Applicant'}],count:body.drill_bucket?1:30,stage_columns:[]};
      return new Response(JSON.stringify({ok:true,data:result}));
    };
  }, {reports,native,reportPanelViews});
  if (reports) {
    for(const name of ['vendor-ag-grid-community-36.1.0.min.css','vendor-ag-grid-theme-quartz-36.1.0.min.css'])await page.addStyleTag({path:asset(name)});
    for (const name of ['vendor-chartjs-4.5.1.umd.min.js','vendor-ag-grid-community-36.1.0.min.js']) await page.addScriptTag({path:asset(name)});
  }
  for (const name of ['utils.js','components.js','activity_changes.js','tat_formatters.js','tat_bro_assignment.js','tat_case_validation.js','tat_tracker.js']) await page.addScriptTag({path:asset(name)});
  await expect(page.locator('#queueList')).toContainText('Synthetic Applicant');
}

test('real TAT queue searches the selected queue, ignores stale responses and preserves query on return', async({page})=>{
  await mount(page);
  await expect(page.locator('#trackerTabs [data-view="search"]')).toHaveCount(0);
  await page.locator('#queueSearchInput').fill('slow');
  await expect.poll(()=>page.evaluate(()=>window.__calls.some(c=>c.body.query==='slow'))).toBe(true);
  await page.locator('#queueSearchInput').fill('Current');
  await expect(page.locator('#queueList')).toContainText('Current');
  await page.waitForTimeout(700);
  await expect(page.locator('#queueList')).not.toContainText('slow');
  await page.locator('[data-home-queue="all"]').click();
  await expect.poll(()=>page.evaluate(()=>window.__calls.filter(c=>c.url.includes('/home/')).at(-1).body)).toMatchObject({query:'Current',queue:'all',page:1});
  await page.locator('#queueList .case-name').first().click();
  await expect(page.locator('#detailView')).toHaveClass(/active/);
  await expect(page.locator('#detailSummary a[href="tel:+254712345678"]')).toHaveCount(1);
  await page.locator('#backBtn').click();
  await expect(page.locator('#queueSearchInput')).toHaveValue('Current');
  await page.locator('#queueSearchInput').fill('');
  await expect(page.locator('#queueList')).toContainText('Synthetic Applicant');
});

test('TAT queue sends identifiers and branches in either queue and resets pagination', async ({page}) => {
  await mount(page);
  for (const queue of ['all','role']) {
    await page.locator(`[data-home-queue="${queue}"]`).click();
    for (const query of ['99000001','0712345678','+254 712 345 678','nAkUrU']) {
      await page.locator('#queueSearchInput').fill(query);
      await expect.poll(() => page.evaluate(() => __calls.filter(c=>c.url.includes('/home/')).at(-1).body)).toMatchObject({query,queue,page:1});
    }
  }
});

for (const width of [320,360,390,430,768,1280]) test(`TAT report filters hide specialist controls and keep warnings ${width}px`, async ({page},info) => {
  await page.setViewportSize({width,height:850}); await mount(page,'all');
  await page.locator('#dashboardWorkspaceBtn').click();
  await page.locator('#openTatReportFiltersBtn').click();
  for (const theme of ['light','dark']) {
    await page.evaluate(t => document.documentElement.dataset.miniappColorScheme=t,theme);
    const more=page.locator('#tatReportMoreOptions');
    await more.evaluate(node=>node.open=false);
    await expect(page.locator('#tatReportFilters [name=chart_metric]')).toBeHidden();
    await expect(page.locator('#tatReportFilters [name=branch]')).toBeVisible();
    await expect(page.locator('.tat-report-filter-legend')).toBeHidden();
    const helpBox=await page.getByLabel('Help with report filters',{exact:true}).boundingBox();
    const closeBox=await page.locator('#closeTatReportFiltersBtn').boundingBox();
    expect(Math.abs(helpBox.y+helpBox.height/2-closeBox.y-closeBox.height/2)).toBeLessThan(4);
    expect(helpBox.x+helpBox.width).toBeLessThanOrEqual(closeBox.x);
    await page.getByLabel('Help with report filters',{exact:true}).click();
    await expect(page.locator('.tat-report-filter-legend')).toBeVisible();
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    await page.getByLabel('Help with report filters',{exact:true}).click();
    await page.screenshot({path:info.outputPath(`tat-report-filters-${width}-${theme}.png`),fullPage:true});
    await more.locator('summary').click();
    await expect(page.locator('#tatReportFilters [name=chart_metric]')).toBeVisible();
    const footer=await page.locator('#tatReportFilterSheet > footer').boundingBox();
    expect(footer.y+footer.height).toBeLessThanOrEqual(851);
    await page.screenshot({path:info.outputPath(`tat-report-more-${width}-${theme}.png`),fullPage:true});
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  }
  await page.locator('#tatReportFilters [name=stage]').selectOption('training');
  await expect.poll(()=>page.evaluate(()=>__calls.filter(c=>c.url.includes('/reports/cases/')).at(-1).body.stage)).toBe('training');
  await expect(page.locator('#tatReportFilterWarning')).toBeVisible();
  await page.locator('#closeTatReportFiltersBtn').click();
  await page.locator('#tatReportFilterWarning').click();
  await expect(page.locator('#tatReportMoreOptions')).toHaveAttribute('open','');
  await expect(page.locator('[data-report-filter=stage] .report-filter-guidance-note')).toBeVisible();
});

test('TAT simplification retains every stage and its action or blocker', async ({page}) => {
  await mount(page);
  await page.evaluate(()=>window.__fields=[
    {key:'created',label:'Case created',role:'BRO',value:'01-10-26',editable:false},
    {key:'bro_applied',label:'Loan applied',role:'BRO',kind:'dropdown',options:['Met'],editable:true},
    {key:'credit_ready',label:'Credit ready',role:'CA',editable:false,locked_reason:'Complete the loan application first.'},
  ]);
  await page.locator('#queueList .case-name').click();
  await expect(page.locator('#stageFields .stage-row:visible')).toHaveCount(3);
  await expect(page.getByRole('button',{name:'Save outcome'})).toBeVisible();
  await expect(page.locator('[data-stage-key=credit_ready]')).toContainText('Credit ready');
});

for (const width of [390, 1280]) test(`BM analysis approval fits the existing stage layout ${width}px`, async ({page}, info) => {
  await page.setViewportSize({width, height:850});
  await mount(page);
  await page.evaluate(() => window.__nextStage = 'BM analysis approval');
  await page.evaluate(() => window.__fields = [
    {key:'mpesa_to_admin',label:'MPESA sent to Admin',role:'BRO',kind:'timestamp',value:'14-10-26 09:00',editable:false},
    {key:'bm_analysis_approval',label:'BM analysis approval',role:'BM',kind:'dropdown',options:['Approved','Declined'],value:'',editable:true},
    {key:'mpesa_verified',label:'MPESA verified by Business Admin and sent to CA',role:'BUSINESS_ADMIN',kind:'timestamp',value:'',editable:false,locked_reason:'Complete BM analysis approval first.'},
  ]);
  await page.locator('#queueList .case-name').click();
  await expect(page.locator('#creditAssessmentPanel')).toBeHidden();
  expect(await page.evaluate(() => getComputedStyle(document.body).fontFamily)).toContain('Segoe UI');
  expect(await page.locator('#detailSummary').evaluate(node => getComputedStyle(node).fontFamily)).toContain('Segoe UI');
  const bm = page.locator('[data-stage-key=bm_analysis_approval]');
  await expect(bm).toContainText('BM analysis approval');
  await expect(bm.locator('select')).toBeEnabled();
  await expect(bm.locator('select option')).toHaveText(['Select outcome...', 'Approved', 'Declined']);
  await expect(page.locator('[data-stage-key=mpesa_verified]')).toContainText('Complete BM analysis approval first.');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({path:info.outputPath(`bm-analysis-${width}.png`),fullPage:true});
});

test('IT creation and corrections use the complete BRO selector with empty-state retry',async({page})=>{
  await mount(page);
  await page.locator('[data-view="new"]').click();
  await expect(page.locator('#newCaseForm [name=bro_user_id] option')).toHaveCount(3);
  await expect(page.locator('#newCaseForm [name=bro_user_id]')).toHaveValue('');
  await expect(page.locator('#newCaseForm [name=bro_user_id] option').nth(1)).toHaveText('Synthetic BRO (synthetic-bro)');
  await page.locator('[data-view="queue"]').click();
  await page.locator('#queueList .case-name').first().click();
  await page.locator('#correctCaseDetailsBtn').click();
  await expect(page.locator('#caseCorrectionForm [name=bro_name]')).toHaveCount(0);
  await expect(page.locator('#caseCorrectionForm [name=bro_user_id]')).toHaveValue('unchanged');
  await expect(page.locator('#caseCorrectionForm [name=bro_user_id] option')).toHaveCount(4);
});

for (const width of [320,360,390,430,768,1280]) test(`TAT uneven field errors keep paired inputs aligned ${width}px`, async ({page}, info) => {
  await page.setViewportSize({width,height:850}); await mount(page);
  await page.locator('[data-view="new"]').click();
  const form = page.locator('#newCaseForm');
  await form.locator('[name=client_name]').fill('Retained applicant');
  const tops = () => form.locator('[name=national_id],[name=primary_phone]').evaluateAll(nodes => nodes.map(n => n.getBoundingClientRect().top));
  for (const theme of ['light','dark']) {
    await page.evaluate(t => document.documentElement.dataset.miniappColorScheme=t, theme);
    await page.evaluate(() => MiniAppUtils.bindAccessibleForm(document.getElementById('newCaseForm')).show({national_id:'Enter a National ID using digits only. Check the identification document before saving.'},false));
    let y = await tops(); expect(Math.abs(y[0]-y[1])).toBeLessThan(1);
    const bro = await form.locator('[name=bro_user_id]').boundingBox();
    const error = await form.locator('.miniapp-field-error:visible').boundingBox();
    expect(bro.y).toBeGreaterThan(error.y+error.height);
    await page.screenshot({path:info.outputPath(`tat-uneven-errors-${width}-${theme}.png`),fullPage:true});
    await page.evaluate(() => MiniAppUtils.bindAccessibleForm(document.getElementById('newCaseForm')).show({national_id:'Check this ID.',primary_phone:'Enter a complete Kenyan phone number, including the area prefix. Do not include words or extensions.'},false));
    y = await tops(); expect(Math.abs(y[0]-y[1])).toBeLessThan(1);
    expect(await page.evaluate(() => document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    await form.locator('[name=national_id]').fill('99000001');
    await expect(form.locator('[name=national_id]')).not.toHaveAttribute('aria-invalid','true');
    await form.locator('[name=primary_phone]').fill('0712345678');
    await expect(form.locator('.miniapp-field-error:visible')).toHaveCount(0);
    await expect(form.locator('[name=client_name]')).toHaveValue('Retained applicant');
    y = await tops(); expect(Math.abs(y[0]-y[1])).toBeLessThan(1);
  }
});

for (const width of [320,768,1280]) test(`TAT corrections and dynamic requirements preserve error rows ${width}px`, async ({page},info) => {
  await page.setViewportSize({width,height:850}); await mount(page);
  await page.locator('#queueList .case-name').click();
  await page.locator('#correctCaseDetailsBtn').click();
  await page.evaluate(() => MiniAppUtils.bindAccessibleForm(document.getElementById('caseCorrectionForm')).show({client_name:'Check the full client name against the identification document. Keep the original input until the change is confirmed.',national_id:'Check the ID.'},false));
  await expect(page.locator('#caseCorrectionForm .miniapp-field-error:visible')).toHaveCount(2);
  const correction=page.locator('#caseCorrectionForm');
  const name=await correction.locator('[name=client_name]').boundingBox(), id=await correction.locator('[name=national_id]').boundingBox();
  if(width>=640)expect(Math.abs(name.y-id.y)).toBeLessThan(1);
  await page.screenshot({path:info.outputPath(`tat-correction-errors-${width}.png`),fullPage:true});
  await page.locator('#cancelCaseCorrectionBtn').click();
  await page.locator('[data-view=new]').click();
  await page.evaluate(()=>{
    const panel=document.getElementById('newCaseProductConfiguration');
    panel.hidden=false;
    panel.innerHTML='<h3>Product details</h3><label><strong>A long requirement name that wraps over several lines</strong><input name="requirement_one" required><small>Keep this existing help.</small></label><label>Second field<input name="requirement_two" required></label><label>Third field<input name="requirement_three" required></label><label>Fourth field<input name="requirement_four" required></label>';
  });
  await expect(page.locator('[name=requirement_one]')).toHaveAttribute('aria-required','true');
  await expect(page.getByRole('textbox',{name:'A long requirement name that wraps over several lines'})).toHaveCount(1);
  await page.evaluate(()=>MiniAppUtils.bindAccessibleForm(document.getElementById('newCaseForm')).show({requirement_one:'Check the supplied requirement carefully before saving. This longer error should wrap without covering any neighbouring field.',requirement_two:'Check this field.'},false));
  const rows=await page.locator('#newCaseProductConfiguration input').evaluateAll(nodes=>nodes.map(n=>n.getBoundingClientRect().top));
  expect(Math.abs(rows[0]-rows[1])).toBeLessThan(1);
  expect(Math.abs(rows[2]-rows[3])).toBeLessThan(1);
  const messages=await page.locator('#newCaseProductConfiguration .miniapp-field-error:visible').evaluateAll(nodes=>nodes.map(n=>n.getBoundingClientRect().bottom));
  expect(rows[2]).toBeGreaterThan(Math.max(...messages));
  await expect(page.locator('#newCaseProductConfiguration')).toContainText('Keep this existing help.');
  await page.screenshot({path:info.outputPath(`tat-product-errors-${width}.png`),fullPage:true});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});

test('personal inbox pages ten, preserves rows on failure and hides a zero unread badge',async({page})=>{
  await mount(page); await page.locator('#privateTaskButton').click();
  await expect(page.locator('#privateTaskCount')).toHaveText('23');
  await expect(page.locator('#privateTaskHeading')).toHaveText('Needs your input (23)');
  await expect(page.locator('.task-inbox-card')).toHaveCount(10);
  await page.locator('#privateTaskMore').click();
  await expect(page.locator('.task-inbox-card')).toHaveCount(20);
  await page.evaluate(()=>{window.__taskError=true;});
  await page.locator('#privateTaskMore').click();
  await expect(page.locator('.task-inbox-card')).toHaveCount(20);
  await expect(page.locator('#privateTaskStatus')).toContainText('Could not refresh');
  await page.evaluate(()=>{window.__taskError=false;});
  await page.locator('#privateTaskStatus button').click();
  await expect(page.locator('.task-inbox-card')).toHaveCount(23);
  await expect(page.locator('#privateTaskMore')).toBeHidden();
  await page.locator('#closePrivateTasks').click();
  await page.evaluate(()=>{window.__unread=false;});
  await page.locator('#privateTaskButton').click();
  await expect(page.locator('#privateTaskCount')).toBeHidden();
  await expect(page.locator('.task-inbox-card')).toHaveCount(10);
});

for(const width of [320,360,390,430,768,1280])test(`compact create and right-aligned inbox ${width}px`,async({page},info)=>{
  await page.setViewportSize({width,height:850});await mount(page);
  await expect(page.locator('#queueFreshness')).toBeHidden();
  for(const theme of ['light','dark']){
    await page.evaluate(t=>document.documentElement.dataset.miniappColorScheme=t,theme);
    await page.locator('[data-view="new"]').click();
    const id=await page.locator('#newCaseForm [name=national_id]').boundingBox(),phone=await page.locator('#newCaseForm [name=primary_phone]').boundingBox();
    expect(Math.abs(id.y-phone.y)).toBeLessThan(1);
    const bro=await page.locator('#newCaseForm [name=bro_user_id]').boundingBox(),amount=await page.locator('#newCaseForm [name=amount]').boundingBox();
    expect(Math.abs(bro.y-amount.y)).toBeLessThan(1);
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    await page.screenshot({path:info.outputPath(`tat-create-${width}-${theme}.png`),fullPage:true});
    await page.locator('#privateTaskButton').click();
    await expect(page.locator('.task-inbox-card')).toHaveCount(10);
    const head=await page.locator('.task-inbox-panel-heading').boundingBox(),close=await page.locator('#closePrivateTasks').boundingBox();
    expect(Math.abs(head.x+head.width-close.x-close.width-10)).toBeLessThan(2);
    expect(close.y).toBeLessThan(head.y+15);
    expect(close.width).toBe(36);
    await page.screenshot({path:info.outputPath(`tat-inbox-${width}-${theme}.png`),fullPage:true});
    await page.locator('#closePrivateTasks').click();
  }
});

for(const result of ['accepted','cancelled','throws','unsupported'])test(`native TAT workbook download ${result}`,async({page})=>{
  await mount(page,true,true);
  await page.evaluate(result=>{
    window.__downloads=[];
    if(result!=='unsupported')Telegram.WebApp.downloadFile=(options,callback)=>{
      __downloads.push(options);if(result==='throws')throw new Error('Synthetic native failure');callback(result!=='cancelled');
    };
  },result);
  await page.locator('#dashboardWorkspaceBtn').click();
  await expect(page.locator('#tatReportPage')).toHaveText('Page 1 of 2');
  await page.locator('#tatReportExport').click();
  await page.getByRole('button',{name:'Download filtered',exact:true}).click();
  const status=page.locator('#tatReportDownloadStatus');
  if(result==='cancelled'){
    await expect(status).toContainText('Download cancelled');await expect(status.locator('a')).toHaveCount(0);
  }else await expect(status.locator('a')).toHaveText('Download tat-report-13-10-26.xlsx');
  if(result==='accepted')await expect(status).toContainText('Download requested');
  expect(await page.evaluate(()=>__downloads.length)).toBe(result==='unsupported'?0:1);
  expect(await page.evaluate(()=>__calls.find(c=>c.url.includes('/export/')).body.prepare_download)).toBe(true);
  await expect(status).not.toContainText('report downloaded');
});

test('an empty BRO roster is explained and Retry preserves entered form values',async({page})=>{
  await mount(page);await page.locator('[data-view="new"]').click();
  // Simulate a refreshed bootstrap with no active BROs, through the real retry path.
  await page.evaluate(()=>{window.__emptyRoster=true;});
  await page.locator('[data-view="queue"]').click();await page.locator('#queueList .case-name').first().click();
  await page.locator('#correctCaseDetailsBtn').click();
  await page.locator('#caseCorrectionForm [name=client_name]').fill('Unsaved correction');
  await page.evaluate(()=>{
    // The real bootstrap uses the same select renderer. Drive its visible retry
    // using an empty correction roster returned by the detail endpoint.
    const original=TatMiniAppApi.postJson;
    TatMiniAppApi.postJson=async(url,body)=>{const response=await original(url,body);if(url.includes('/detail/'))response.data.correction_bro_users=[];return response;};
  });
  await page.locator('#cancelCaseCorrectionBtn').click();await page.locator('#backBtn').click();
  await page.locator('#queueList .case-name').first().click();await page.locator('#correctCaseDetailsBtn').click();
  await page.locator('#caseCorrectionForm [name=client_name]').fill('Keep this correction');
  await expect(page.locator('#correctionBroStatus')).toContainText('No active TAT BROs');
  await page.evaluate(()=>{window.__emptyRoster=false;});
  await page.locator('#correctionBroStatus button').click();
  await expect(page.locator('#caseCorrectionForm [name=client_name]')).toHaveValue('Keep this correction');
  await expect(page.locator('#caseCorrectionForm [name=bro_user_id] option')).toHaveCount(4);
});

for (const width of [320,360,390,430,768,1280]) test(`TAT queue identifiers align and search has no heading at ${width}px`, async ({page}, info) => {
  await page.setViewportSize({width,height:850}); await mount(page);
  await expect(page.getByText('Search this queue', {exact:true})).toHaveCount(0);
  await expect(page.locator('#activeQueueHeading')).toHaveCount(0);
  const searchBox=await page.locator('#queueSearchInput').boundingBox(), filterBox=await page.locator('#openQueueFiltersBtn').boundingBox();
  expect(Math.abs(searchBox.y+searchBox.height/2-filterBox.y-filterBox.height/2)).toBeLessThan(2);
  for (const theme of ['light','dark']) {
    await page.evaluate(value=>document.documentElement.dataset.miniappColorScheme=value,theme);
    const boxes=await page.locator('#queueList .case-identifier-value').evaluateAll(nodes=>nodes.map(n=>n.getBoundingClientRect().top));
    expect(boxes).toHaveLength(2); expect(Math.abs(boxes[0]-boxes[1])).toBeLessThan(1);
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    await page.screenshot({path:info.outputPath(`queue-identifiers-${width}-${theme}.png`),fullPage:true});
  }
  await page.locator('#queueList a[href^="tel:"]').click();
  await expect(page.locator('#queueView')).toHaveClass(/active/);
});

for(const width of [320,360,390,430,768,1280]) test(`TAT correction Cancel stays right-aligned at ${width}px`,async({page},info)=>{
  await page.setViewportSize({width,height:850}); await mount(page);
  await page.locator('#queueList .case-name').first().click();
  await page.locator('#correctCaseDetailsBtn').click();
  for(const theme of ['light','dark']) {
    await page.evaluate(value=>{document.documentElement.dataset.miniappColorScheme=value;},theme);
    const header=await page.locator('#caseCorrectionPanel .section-head').boundingBox(), cancel=await page.locator('#cancelCaseCorrectionBtn').boundingBox();
    expect(Math.abs(header.x+header.width-cancel.x-cancel.width-8)).toBeLessThan(2);
    expect(Math.abs(cancel.y+cancel.height/2-header.y-header.height/2)).toBeLessThan(2);
    await page.screenshot({path:info.outputPath(`tat-correction-${width}-${theme}.png`),fullPage:true});
  }
  await page.locator('#cancelCaseCorrectionBtn').click();
  await expect(page.locator('#caseCorrectionPanel')).toBeHidden();
});

test('TAT native correction submit retains validation and hides on Cancel',async({page})=>{
  await mount(page,false,true);
  await page.locator('#queueList .case-name').first().click();
  await page.locator('#correctCaseDetailsBtn').click();
  await expect.poll(()=>page.evaluate(()=>__native.visible&&__handlers.size===1)).toBe(true);
  await page.locator('#caseCorrectionForm [name=client_name]').fill('');
  await page.evaluate(()=>[...__handlers][0]());
  await expect(page.locator('#caseCorrectionForm [name=client_name]')).toHaveAttribute('aria-invalid','true');
  await page.locator('#cancelCaseCorrectionBtn').click();
  await expect.poll(()=>page.evaluate(()=>__handlers.size)).toBe(0);
});

test('real TAT chart click narrows the grid, survives paging and clears with base filters', async ({page}) => {
  await mount(page,true);
  await page.locator('#dashboardWorkspaceBtn').click();
  await expect(page.locator('#tatReportPage')).toHaveText('Page 1 of 2');
  const clickPoint = async () => {
    const point = await page.evaluate(() => {
      const chart=Chart.getChart(document.getElementById('tatTrendChart')); chart.stop(); chart.update('none');
      const p=chart.getDatasetMeta(0).data[0];
      const box=chart.canvas.getBoundingClientRect(); return {x:box.left+p.x,y:box.top+p.y};
    });
    await page.mouse.click(point.x,point.y);
  };
  expect(await page.evaluate(()=>Chart.getChart(document.getElementById('tatTrendChart')).data.labels)).toEqual(['01-10-26','02-10-26']);
  await clickPoint();
  await expect.poll(() => page.evaluate(() => __calls.filter(c=>c.url.includes('/reports/cases/')).at(-1).body)).toMatchObject({drill_chart:'trend',drill_series:'completed_actions',drill_bucket:'2026-10-01',page:1});
  await expect(page.locator('#tatHeatmapSelection')).toBeVisible();
  await expect(page.locator('#tatReportPage')).toHaveText('Page 1 of 1');
  await page.locator('#tatHeatmapSelection').click();
  await expect(page.locator('#tatReportPage')).toHaveText('Page 1 of 2');
  await clickPoint();
  await page.locator('#openTatReportFiltersBtn').click();
  await page.locator('#tatReportFilters [name=search]').fill('Training');
  await expect(page.locator('#tatHeatmapSelection')).toBeHidden();
  await expect.poll(() => page.evaluate(() => __calls.filter(c=>c.url.includes('/reports/cases/')).at(-1).body.drill_chart || '')).toBe('');
});

test('TAT chart selection identifies the clicked series, not the first tooltip series', async ({page}) => {
  await mount(page,true);
  await page.evaluate(() => { window.__multiTrend=true; });
  await page.locator('#dashboardWorkspaceBtn').click();
  await expect(page.locator('#tatReportPage')).toHaveText('Page 1 of 2');
  const point=await page.evaluate(() => {
    const chart=Chart.getChart(document.getElementById('tatTrendChart')); chart.stop(); chart.update('none');
    const p=chart.getDatasetMeta(1).data[0], box=chart.canvas.getBoundingClientRect();
    return {x:box.left+p.x,y:box.top+p.y};
  });
  await page.mouse.click(point.x,point.y);
  await expect.poll(() => page.evaluate(() => __calls.filter(c=>c.url.includes('/reports/cases/')).at(-1).body)).toMatchObject({drill_series:'disbursed',drill_bucket:'2026-10-01'});
});

test('TAT historical totals explain unavailable case drilldown without changing the grid', async ({page}) => {
  await mount(page,true);
  await page.evaluate(() => { window.__historical=true; });
  await page.locator('#dashboardWorkspaceBtn').click();
  await expect(page.locator('#tatReportPage')).toHaveText('Page 1 of 2');
  const point=await page.evaluate(() => {
    const chart=Chart.getChart(document.getElementById('tatTrendChart')); chart.stop(); chart.update('none');
    const p=chart.getDatasetMeta(0).data[0], box=chart.canvas.getBoundingClientRect();
    return {x:box.left+p.x,y:box.top+p.y};
  });
  await page.mouse.click(point.x,point.y);
  await expect(page.locator('#tatReportPage')).toHaveText('Page 1 of 2');
  expect(await page.evaluate(() => __calls.some(c=>c.body.drill_chart))).toBe(false);
  await expect(page.getByText('Individual cases aren’t available for this historical total.',{exact:true}).first()).toBeVisible();
});

test('TAT report calendar controls use the shared period calculation',async({page})=>{
  await mount(page);
  await page.evaluate(()=>{document.querySelectorAll('.view').forEach(n=>n.classList.remove('active'));document.getElementById('dashboardView').classList.add('active');document.getElementById('tatReportFilterOverlay').hidden=false;});
  await page.locator('#tatReportFilters [name="date_mode"]').selectOption('quarter');
  await page.locator('#tatReportFilters [name="year"]').fill('2025');
  await page.locator('#tatReportFilters [name="quarter"]').selectOption('3');
  expect(await page.locator('#tatReportFilters [name="date_from"]').inputValue()).toBe('2025-07-01');
  expect(await page.locator('#tatReportFilters [name="date_to"]').inputValue()).toBe('2025-09-30');
  await expect(page.locator('#tatReportFilters label[data-report-filter="granularity"]')).toHaveCount(0);
});

test('TAT detail does not make missing or masked contacts dialable',async({page})=>{
  await mount(page);
  for(const phone of ['', '07******78', 'not a phone']) {
    await page.evaluate(value=>{window.__phone=value;},phone);
    await page.locator('#queueList .case-card').first().click();
    await expect(page.locator('#detailSummary a[href^="tel:"]')).toHaveCount(0);
    await page.locator('#backBtn').click();
  }
});

test('TAT activity displays the stage once alongside the recorded change',async({page})=>{
  await mount(page);await page.evaluate(()=>window.__timeline=[{stage:'Credit analysis',actor:'Training analyst',
    occurred_at:'2026-10-01T09:00:00+03:00',changes:[{field:'value',label:'Credit analysis',old_value:'Pending',new_value:'Approved'}]}]);
  await page.locator('#queueList .case-name').first().click();
  await page.locator('.activity-panel summary').click();
  await expect(page.locator('#eventList').getByText('Credit analysis',{exact:true})).toHaveCount(1);
  await expect(page.locator('#eventList')).toContainText('Approved');
});

test('TAT graph help stays inside the question control without repeating its title',async({page},info)=>{
  await page.setViewportSize({width:390,height:850});await mount(page,'all');
  await page.locator('#dashboardWorkspaceBtn').click();
  await page.locator('[data-report-view="performance"]').click();
  await page.locator('#tatChartNext').click();
  const panel=page.locator('[data-report-key="tat_percentiles"]'), help=panel.locator('.miniapp-chart-help');
  await expect(help.locator('.miniapp-chart-help-content')).toBeHidden();
  await help.locator('summary').click();
  await expect(help).toContainText('P90 is the time within which 90% finished.');
  await expect(help).not.toContainText('How to read it:');
  await expect(help).not.toContainText('Question:');
  await expect(help).not.toContainText(await panel.locator('h3').innerText());
  await page.screenshot({path:info.outputPath('tat-graph-help-390.png'),fullPage:true});
});

for (const width of [320,360,390,430,768,1280]) test(`TAT report tabs and icon/grouping controls fit ${width}px`,async({page},info)=>{
  await page.setViewportSize({width,height:850});await mount(page,'all');
  await page.locator('#dashboardWorkspaceBtn').click();
  const keys=()=>page.locator('#tatReportCharts [data-report-slide]').evaluateAll(nodes=>nodes.filter(n=>!n.hidden).map(n=>n.dataset.reportKey));
  const current=await keys();expect(current).toHaveLength(5);
  await expect(page.locator('#tatReportPage')).toHaveText('Page 1 of 2');
  for(const [key,grouping] of [['trend','day'],['sla_compliance','week'],['tat_percentiles','year']]) {
    if(key==='sla_compliance')await page.locator('[data-report-view="performance"]').click();
    if(key==='tat_percentiles')await page.locator('#tatChartNext').click();
    const panel=page.locator(`[data-report-key="${key}"]`),toggle=panel.getByLabel('Chart options',{exact:true});
    await expect(panel).toBeVisible();const before=await toggle.boundingBox();await toggle.click();
    const after=await toggle.boundingBox();expect(Math.abs(before.x-after.x)).toBeLessThan(1);expect(Math.abs(before.y-after.y)).toBeLessThan(1);
    const line=panel.getByRole('button',{name:'Line chart',exact:true});await expect(line.locator('svg')).toHaveCount(1);
    expect((await line.boundingBox()).width).toBeLessThanOrEqual(44);
    expect(await panel.getByLabel('Time grouping').locator('option').allTextContents()).toEqual(['Day','Week','Month','Year']);
    await page.screenshot({path:info.outputPath(`tat-${key}-controls-${width}.png`),fullPage:true});
    await panel.getByLabel('Time grouping').selectOption(grouping);
    await expect.poll(()=>page.evaluate(()=>__calls.filter(c=>c.url.includes('/reports/summary/')).at(-1).body.granularity)).toBe(grouping);
    await toggle.click();await panel.getByRole('button',{name:'Bar chart',exact:true}).click();
    await expect(toggle.locator('..')).not.toHaveAttribute('open','');
  }
  const performance=await keys();expect(performance).toHaveLength(5);expect(current.filter(k=>performance.includes(k))).toEqual([]);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});
