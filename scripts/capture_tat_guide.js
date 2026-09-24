/* Offline synthetic screenshots for TAT_TRACKER_MINI_APP_GUIDE.md. */
'use strict';
const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

const root = path.resolve(__dirname, '..');
const assets = name => path.join(root, 'core/static/miniapp', name);
const out = path.join(root, 'docs/images/tat');
const now = '2026-09-24T09:00:00+03:00';
const cases = [
  { case_id:'JBL-TR-2026-001', client_name:'TRAINING CUSTOMER ONE', national_id:'900000001', primary_phone:'0700000001', product:'Training Biogas Loan', branch:'Training Branch', amount:'54000', status:'Active', next_stage:'BRO Application', updated_at:now },
  { case_id:'JBL-TR-2026-002', client_name:'TRAINING CUSTOMER TWO', national_id:'900000002', primary_phone:'0700000002', product:'Training Biogas Loan', branch:'Training Branch', amount:'62000', status:'Stalled', next_stage:'Credit Analysis', updated_at:now },
  { case_id:'JBL-TR-2026-003', client_name:'TRAINING CUSTOMER THREE', national_id:'900000003', primary_phone:'0700000003', product:'Training Biogas Loan', branch:'Training Branch', amount:'48000', status:'Active', next_stage:'BRO Application', updated_at:now },
];
const fields = [
  { key:'application_received', label:'Application received', role:'BRO', kind:'timestamp', value:'23-09-2026 09:00', raw_value:now, editable:false, can_correct:true, target_minutes:60, elapsed_seconds:2100, sla_status:'within' },
  { key:'bro_applied', label:'BRO Application', role:'BRO', kind:'dropdown', value:'', editable:true, options:['Met','Not Met'], target_minutes:120, elapsed_seconds:3000, sla_status:'within' },
  { key:'credit_analysis', label:'Credit Analysis', role:'CA', kind:'timestamp', value:'', editable:false, locked_reason:'Complete BRO Application first.', target_minutes:180 },
  { key:'branch_manager', label:'Branch Manager decision', role:'BM', kind:'dropdown', value:'', editable:false, locked_reason:'Waiting for Credit Analysis.', target_minutes:120 },
];
const events = [
  { stage:'Application received', detail:'Training application logged.', actor:'Training Officer', occurred_at:now },
  { stage:'Case created', detail:'Training Biogas Loan · KES 54,000', actor:'Training Officer', occurred_at:'2026-09-23T08:45:00+03:00' },
];
const detail = (caseId='JBL-TR-2026-001') => ({
  summary:{ ...cases.find(item => item.case_id === caseId) || cases[0], requested_amount:(cases.find(item => item.case_id === caseId) || cases[0]).amount, bro_name:'Training Officer', next_stage:'BRO Application', elapsed_seconds:86400, calculated_at:now, running:true, sla_status:'near', read_only:caseId==='JBL-TR-2026-003' },
  fields: caseId==='JBL-TR-2026-003' ? fields.map(item => ({...item, editable:false, can_correct:false, locked_reason:'Closed Pilot cycle'})) : fields,
  remarks:'Waiting for the training applicant to complete the final document.',
  timeline:events, can_correct_details:caseId!=='JBL-TR-2026-003', correction_branches:['Training Branch'],
  product_requirements:[], credit_assessment_enabled:false,
});
const home = queue => ({ queue, items:queue==='all' ? cases : cases.slice(0,2), metrics:{ role:2,total:3,completed:1,stalled:1 }, pagination:{ page:1,pages:1,total:queue==='all'?3:2,offset:0 }, visibility:{ filters_active:false } });
const bootstrap = {
  authorized:true, user:{ name:'Training Officer', roles:['BRO'], capabilities:['tat.home.view','tat.case.create','tat.case.search','tat.case.view','tat.reports.view','tat.recognition.view','tat.settings.view','tat.case.correct_details','tat.stage.correct'] },
  products:[{key:'training-biogas',label:'Training Biogas Loan',minimum_amount:10000,maximum_amount:100000}], branches:['Training Branch'],
  statuses:['Active','Stalled','Declined','Disbursed'], bro_users:[{id:'training-bro',name:'Training Officer'}], default_bro_user_id:'training-bro',
  ...home('role'), private_alerts:{connected:true,status:'connected'},
  task_inbox:{items:[{task_id:'training-task',case_id:cases[0].case_id,client_name:cases[0].client_name,stage_key:'bro_applied',stage_label:'BRO Application',product:cases[0].product,branch:cases[0].branch,status:'Active',role:'BRO',unread:true}],unread_count:1,total:1},
  workflow_mode:{is_pilot:false,mode_version:'training'}, personal:{default_screen:'home',compact_cards:false},
};
const reportSummary = view => ({
  response_mode:'focused_v1', metric_basis:view==='performance'?'completed_stage_actions':'cases',
  metrics:view==='performance' ? {created:3,finished:7,disbursed:1,declined:1,sla_met_percent:82.5,median_tat_minutes:85,p90_tat_minutes:190} : {active:2,within_target:1,near_target:1,overdue:0,target_unavailable:0},
  freshness:{latest_snapshot:now,pending_rebuilds:0,failed_rebuilds:0},
  filters:{branches:['Training Branch'],products:[['training-biogas','Training Biogas Loan']],stages:[['bro_applied','BRO Application']],roles:['BRO','CA','BM']},
  charts:{ trend:{title:view==='performance'?'Created, Disbursed and Declined':'Workload over Time',question:'How is work changing?',interpretation:'Compare the daily counts.',sample_count:4,labels:['2026-09-21','2026-09-22','2026-09-23','2026-09-24'],series:[{label:'Active',key:'active',values:[1,2,2,2]}]},
    backlog_age:{title:'Current-stage Backlog Age',sample_count:2,labels:['BRO Application','Credit Analysis'],series:[{label:'Cases',values:[1,1]}]} },
});
const reportCases = {count:3,page:1,page_size:25,stage_columns:[],results:cases.map(item=>({case_id:item.case_id,client_name:item.client_name,branch:item.branch,product:item.product,status:item.status,stage:item.next_stage,role:'BRO',created_at:now,elapsed_minutes:85,target_minutes:120,sla_status:'Within Target'}))};
const settings = {
  personal:{default_screen:'home',compact_cards:false}, account:{name:'Training Officer',roles:['BRO'],app_release:'Training capture'},workflow_mode:{is_pilot:false},dispatch_attention_count:0,
  configuration:{cards:{tat_targets:{can_propose:true,can_approve:true},tat_escalation:{can_propose:false,can_approve:true}},targets:[{key:'training-biogas',label:'Training Biogas Loan',total_minutes:480,stages:[{key:'bro_applied',label:'BRO Application',target_minutes:120},{key:'credit_analysis',label:'Credit Analysis',target_minutes:180}]}],pending:[{id:'training-proposal',setting_key:'tat_targets',reason:'Training example of a proposed target review.',requested_by:'Training Analyst',requested_at:'24-09-2026 09:00'}],target_sheet_sync:{status:'synced'}},
};

async function main() {
  fs.mkdirSync(out,{recursive:true});
  const browser = await chromium.launch({headless:true});
  const page = await browser.newPage({viewport:{width:390,height:844},deviceScaleFactor:1,colorScheme:'light'});
  const errors = [];
  page.on('pageerror',error=>errors.push(error.message));
  let template = fs.readFileSync(path.join(root,'core/templates/tat_tracker/app.html'),'utf8');
  const logo = fs.readFileSync(assets('jawabu-logo.png')).toString('base64');
  template = template
    .replace(/{% static 'miniapp\/jawabu-logo.png' %}/g,`data:image/png;base64,${logo}`)
    .replace(/{% if credit_assessment_enabled %}[\s\S]*?{% endif %}/g,'')
    .replace(/{%[\s\S]*?%}/g,'').replace(/{{[\s\S]*?}}/g,'')
    .replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi,'').replace(/<link\b[^>]*>/gi,'');
  await page.setContent(template,{waitUntil:'domcontentloaded'});
  for (const file of ['base.css','vendor-ag-grid-community-36.1.0.min.css','vendor-ag-grid-quartz-font-36.1.0.min.css','vendor-ag-grid-theme-quartz-36.1.0.min.css','tat_tracker.css']) await page.addStyleTag({path:assets(file)});
  await page.evaluate(({bootstrap,cases,settings,reportCases})=>{
    document.body.dataset.groupId='training-tat-group'; document.body.dataset.token=''; document.body.dataset.taskToken='';
    const tg={initData:'synthetic-test-session',platform:'android',ready(){},expand(){},BackButton:{show(){},hide(){},onClick(){}},HapticFeedback:{impactOccurred(){},notificationOccurred(){}}};
    window.Telegram={WebApp:tg}; window.MiniAppTelegram={init:()=>tg};
    window.MiniAppUtils={initTelegram:()=>tg,ensureRequestId:()=>`guide-${Date.now()}`,haptic(){},impactWithFallback(){},bindMiniAppTheme(){},bindFormCloseProtection(){return {reset(){},clear(){}}}};
    window.__guide={bootstrap,cases,settings,reportCases};
    window.TatMiniAppApi={
      async postJson(url,payload){
        if(url.endsWith('/bootstrap/'))return {ok:true,data:bootstrap};
        if(url.endsWith('/home/'))return {ok:true,data:window.__guide.home(payload.queue==='all'?'all':'role')};
        if(url.endsWith('/detail/'))return {ok:true,data:window.__guide.detail(payload.case_id)};
        if(url.endsWith('/search/'))return {ok:true,results:cases.filter(item=>JSON.stringify(item).toLowerCase().includes((payload.query||'').toLowerCase()))};
        if(url.endsWith('/identity-context/'))return {ok:true,data:{matched_on:['national ID'],matches:[{case_id:cases[1].case_id,client_name:cases[1].client_name,product:cases[1].product}]}};
        if(url.endsWith('/settings/'))return {ok:true,data:settings};
        if(url.endsWith('/tasks/'))return {ok:true,data:bootstrap.task_inbox};
        if(url.endsWith('/tasks/read/'))return {ok:true,data:{}};
        if(url.endsWith('/recognition/'))return {ok:true,data:{contract_version:2,minimum_ranked_sample:20,calculated_at:'2026-09-24T09:00:00+03:00',view:'personal',selected:{role:'BRO',role_label:'BRO',product:'training-biogas',product_label:'Training Biogas Loan'},role_options:[{key:'BRO',label:'BRO'}],product_options:[{key:'training-biogas',label:'Training Biogas Loan'}],personal_result:{label:'You',role:'BRO',branch:'Training Branch',product:'Training Biogas Loan',ranked:false,completed:16,completed_total:16,on_time_rate:87.5,score:64.1,is_current_user:true},role_summary:{role:'BRO',product:'Training Biogas Loan',completed:40,completed_total:40,on_time_rate:85,score:72},standings:{dimension:'personal',rows:[],page:1,pages:1,total:0,page_size:5,has_competition:false,eligible_count:0},people_visible:false,technical_details_visible:false}};
        return {ok:true,data:{}};
      },
      async postFragment(){return ''},
    };
    window.fetch=async (url,options={})=>{
      const payload=JSON.parse(options.body||'{}');
      const result=String(url).includes('/reports/cases/')?window.__guide.reportCases:window.__guide.reportSummary(payload.view||'current');
      return new Response(JSON.stringify({ok:true,data:result}),{status:200,headers:{'Content-Type':'application/json'}});
    };
  },{bootstrap,cases,settings,reportCases});
  // Functions cannot cross the browser boundary as data; install executable
  // fixture factories explicitly, while keeping all values synthetic.
  await page.evaluate(({cases,fields,events,bootstrap,settings,reportCases})=>{
    const home=queue=>({queue,items:queue==='all'?cases:cases.slice(0,2),metrics:{role:2,total:3,completed:1,stalled:1},pagination:{page:1,pages:1,total:queue==='all'?3:2,offset:0},visibility:{filters_active:false}});
    const detail=id=>({summary:{...(cases.find(item=>item.case_id===id)||cases[0]),requested_amount:(cases.find(item=>item.case_id===id)||cases[0]).amount,bro_name:'Training Officer',next_stage:'BRO Application',elapsed_seconds:86400,calculated_at:'2026-09-24T09:00:00+03:00',running:true,sla_status:'near',read_only:id===cases[2].case_id},fields:id===cases[2].case_id?fields.map(item=>({...item,editable:false,can_correct:false,locked_reason:'Closed Pilot cycle'})):fields,remarks:'Waiting for the training applicant to complete the final document.',timeline:events,can_correct_details:id!==cases[2].case_id,correction_branches:['Training Branch'],product_requirements:[],credit_assessment_enabled:false});
    const reportSummary=view=>({response_mode:'focused_v1',metric_basis:view==='performance'?'completed_stage_actions':'cases',metrics:view==='performance'?{created:3,finished:7,disbursed:1,declined:1,sla_met_percent:82.5,median_tat_minutes:85,p90_tat_minutes:190}:{active:2,within_target:1,near_target:1,overdue:0,target_unavailable:0},freshness:{latest_snapshot:'2026-09-24T09:00:00+03:00',pending_rebuilds:0,failed_rebuilds:0},filters:{branches:['Training Branch'],products:[['training-biogas','Training Biogas Loan']],stages:[['bro_applied','BRO Application']],roles:['BRO','CA','BM']},charts:{trend:{title:view==='performance'?'Created, Disbursed and Declined':'Workload over Time',question:'How is work changing?',interpretation:'Compare the daily counts.',sample_count:4,labels:['2026-09-21','2026-09-22','2026-09-23','2026-09-24'],series:[{label:'Active',key:'active',values:[1,2,2,2]}]},backlog_age:{title:'Current-stage Backlog Age',sample_count:2,labels:['BRO Application','Credit Analysis'],series:[{label:'Cases',values:[1,1]}]}}});
    window.__guide.home=home;window.__guide.detail=detail;window.__guide.reportSummary=view=>{const result=reportSummary(view);result.freshness.near_target_percent=80;return result;};
    window.__guide.bootstrap=bootstrap;window.__guide.settings=settings;window.__guide.cases=cases;window.__guide.reportCases=reportCases;
  },{cases,fields,events,bootstrap,settings,reportCases});
  for (const file of ['tat_bro_assignment.js','tat_case_validation.js','tat_formatters.js','vendor-ag-grid-community-36.1.0.min.js','vendor-chartjs-4.5.1.umd.min.js','tat_tracker.js']) await page.addScriptTag({path:assets(file)});
  await page.locator('#queueList .case-card').first().waitFor({state:'visible',timeout:10000});
  const shot=async (name,selector)=>{await page.locator(selector).first().scrollIntoViewIfNeeded();await page.locator('#noticeModal').evaluate(el=>el.classList.add('hidden'));await page.screenshot({path:path.join(out,name),animations:'disabled'});};
  const tab=async view=>{await page.locator(`[data-view="${view}"]`).first().click();await page.locator(`#${view==='new'?'newView':view==='search'?'searchView':view==='settings'?'settingsView':'queueView'}`).waitFor({state:'visible'});};
  const open=async id=>{await tab('search');await page.locator('#searchInput').fill(id);await page.locator('#searchBtn').click();await page.locator('#searchList .case-card').first().waitFor({state:'visible'});await page.locator('#searchList .case-card').first().click();await page.locator('#detailView').waitFor({state:'visible'});};
  await shot('01-tracker-overview.png','#queueView');
  await shot('02-telegram-launch.png','#appHeader');
  await page.locator('[data-home-queue="all"]').click();await page.locator('#queueList .case-card').nth(2).waitFor({state:'visible'});await shot('03-case-queues.png','#homeQueueTabs');
  await page.locator('#openQueueFiltersBtn').click();await page.locator('#queueFilterOverlay').waitFor({state:'visible'});await shot('04-queue-filters.png','#queueFilterSheet');await page.locator('#closeQueueFiltersBtn').click();
  await tab('new');const form=page.locator('#newCaseForm');await form.locator('[name="product_key"]').selectOption('training-biogas');await form.locator('[name="branch"]').selectOption('Training Branch');await form.locator('[name="client_name"]').fill('NEW TRAINING CUSTOMER');await form.locator('[name="national_id"]').fill('900000004');await form.locator('[name="primary_phone"]').fill('0700000004');await form.locator('[name="amount"]').fill('50000');await shot('05-create-case.png','#newView');
  await form.locator('[name="national_id"]').fill('900000002');await page.waitForTimeout(500);await page.locator('#existingLoanContext').waitFor({state:'visible'});await shot('06-existing-loan-context.png','#existingLoanContext');
  await tab('search');await page.locator('#searchInput').fill('JBL-TR-2026-001');await page.locator('#searchBtn').click();await page.locator('#searchList .case-card').first().waitFor({state:'visible'});await shot('07-find-case.png','#searchView');
  await page.locator('#searchList .case-card').first().click();await page.locator('#detailView').waitFor({state:'visible'});await shot('08-case-summary.png','#detailSummary');
  await shot('09-stage-states.png','#stageFields');
  await page.locator('#stageFields [data-stage-key="bro_applied"]').scrollIntoViewIfNeeded();await shot('10-stage-outcome.png','#stageFields [data-stage-key="bro_applied"]');
  await page.locator('#eventList').evaluate(el=>{el.closest('details').open=true});await shot('11-remarks-activity.png','#eventList');
  await page.locator('#correctCaseDetailsBtn').click();await shot('12-case-correction.png','#caseCorrectionPanel');await page.locator('#cancelCaseCorrectionBtn').click();
  await tab('settings');await shot('13-settings-alerts.png','#privateAlertSettings');
  await shot('14-configuration-review.png','#configurationReviewList');
  await open('JBL-TR-2026-003');await shot('15-pilot-mode.png','#detailSummary');
  await page.locator('#dashboardWorkspaceBtn').click();await page.locator('#tatReportMetrics .report-metric').first().waitFor({state:'visible',timeout:10000});await shot('16-current-workload.png','#tatReportMetrics');
  await page.locator('#openTatReportFiltersBtn').click();await shot('17-report-filters.png','#tatReportFilterSheet');await page.locator('#closeTatReportFiltersBtn').click();
  await shot('18-insights-table.png','#tatTrendPanel');
  await page.locator('[data-report-view="performance"]').click();await page.waitForTimeout(200);await shot('19-period-performance.png','#tatReportMetrics');
  if(errors.length)throw new Error(`Browser errors: ${errors.join(' | ')}`);
  await browser.close();console.log('Captured 19 synthetic TAT Mini App screenshots in '+out);
}
main().catch(error=>{console.error(error);process.exitCode=1});
