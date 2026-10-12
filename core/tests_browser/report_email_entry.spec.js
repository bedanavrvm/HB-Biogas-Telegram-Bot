'use strict';
const fs=require('node:fs');
const path=require('node:path');
const {test,expect}=require('playwright/test');
const root=path.resolve(__dirname,'../..');
const source=fs.readFileSync(path.join(root,'core/static/miniapp/tat_tracker.js'),'utf8');
const start=source.indexOf('  async function startApp() {');
const entryFunction=source.slice(start,source.indexOf('\n  function startRuntimeTimers()',start));

for(const scenario of ['authorized','denied','task']) test('TAT email report entry '+scenario+' respects access and task priority',async({page})=>{
  await page.route('http://127.0.0.1/report-entry**',route=>route.fulfill({contentType:'text/html',body:'<form id="tatReportFilters"><input name="date_from" type="date"><input name="date_to" type="date"><select name="date_mode"><option value="custom">Custom</option><option value="all">Any time</option></select><select name="branch"><option value="">All branches</option></select><select name="product"><option value="">All products</option></select></form>'}));
  await page.goto('http://127.0.0.1/report-entry?view=reports&report_view=performance&date_from=2026-10-05&date_to=2026-10-11&branch=Training&product=synthetic');
  await page.evaluate(scenario=>{
    window.state={taskToken:scenario==='task'?'synthetic-task':'',data:null,report:{view:'current'}};
    window.$=id=>document.getElementById(id);window.__entryCalls=[];
    window.api=async route=>{
      window.__entryCalls.push(route);
      return route.includes('resolve')?{data:{group_id:'synthetic-group',case_id:'synthetic-case'}}:
        {data:{user:{capabilities:scenario==='denied'?[]:['tat.reports.view']}}};
    };
    window.bootstrap=data=>{window.state.data=data;};
    window.consumeTaskLaunchUrl=()=>{};window.setStatus=()=>{};
    window.openCase=async id=>{window.__entryCalls.push('case:'+id);};
    window.syncTatPeriodControls=()=>{};
    window.show=view=>{window.__entryCalls.push('show:'+view);};
    window.setTatReportView=view=>{window.__entryCalls.push('report:'+view);};
  },scenario);
  await page.addScriptTag({content:entryFunction+'\nwindow.__startEmailEntry=startApp;'});
  await page.evaluate(()=>window.__startEmailEntry());
  const calls=await page.evaluate(()=>window.__entryCalls);
  expect(calls).toContain('/api/tat-tracker/bootstrap/');
  if(scenario==='authorized') {
    expect(calls).toContain('report:performance');
    await expect(page.locator('[name="branch"]')).toHaveValue('Training');
    await expect(page.locator('[name="date_from"]')).toHaveValue('2026-10-05');
  } else {
    expect(calls).not.toContain('report:performance');
    if(scenario==='task') expect(calls).toContain('case:synthetic-case');
  }
});
