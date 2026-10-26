'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');

async function main() {
  let source = ''; for await (const chunk of process.stdin) source += chunk;
  const input = JSON.parse(source), origin = new URL(input.origin);
  assert.ok(['127.0.0.1', 'localhost'].includes(origin.hostname));
  const browser = await chromium.launch({headless:true});
  const context = await browser.newContext({viewport:{width:1366,height:900}});
  const page = await context.newPage(); page.setDefaultTimeout(12000);
  const evidence=path.resolve('test-results/complaints-task-recovery',input.build);fs.mkdirSync(evidence,{recursive:true});
  await context.route('**/*',route=>new URL(route.request().url()).origin===origin.origin?route.continue():route.abort());
  page.on('dialog',dialog=>dialog.accept());
  let codeIndex=0;
  async function login() {
    await page.getByRole('heading',{name:'Sign in',exact:true}).waitFor();
    await page.getByLabel(/^Staff username/).fill(input.username);
    await page.getByLabel(/^Password/).fill(input.password);
    await page.getByRole('button',{name:'Sign in',exact:true}).click();
    await page.getByRole('button',{name:'Use a recovery code',exact:true}).click();
    await page.getByRole('heading',{name:'Use a recovery code',exact:true}).waitFor();
    await page.getByLabel(/^Recovery code/).fill(input.codes[codeIndex++]);
    await page.getByRole('button',{name:'Verify',exact:true}).click();
  }
  async function expire() {
    await page.evaluate(async()=>{
      const state=await(await fetch('/api/staff/auth/v1/session/')).json();
      await fetch('/api/staff/auth/v1/logout/',{method:'POST',headers:{'Content-Type':'application/json','X-CSRFToken':state.csrf_token},body:'{}'});
    });
  }
  try {
    await page.goto(origin.origin+'/staff/app/complaints/'); await login();
    await page.getByRole('button',{name:'Settings',exact:true}).click();
    await page.getByRole('button',{name:'Closed',exact:true}).click();
    await context.setOffline(true);await page.getByRole('button',{name:'Save preferences',exact:true}).click();
    await page.getByRole('alert').filter({has:page.getByRole('heading',{name:'Changes not saved',exact:true})}).getByText('You are offline. Your changes are retained. Reconnect before saving.',{exact:true}).waitFor();
    await context.setOffline(false);
    await expire(); await page.getByRole('button',{name:'Save preferences',exact:true}).click();
    await page.getByRole('button',{name:'Sign in again',exact:true}).click(); await login();
    await page.getByRole('heading',{name:'Your preferences',exact:true}).waitFor();
    await page.screenshot({path:path.join(evidence,'retained-settings.png')});
    const savedPreferences=page.waitForResponse(response=>response.url().endsWith('/preferences/')&&response.request().method()==='POST');
    await page.getByRole('button',{name:'Save preferences',exact:true}).click();
    assert.equal((await savedPreferences).request().postDataJSON().preferences.default_filters.status,'resolved','Unsaved preference must survive native reauthentication');
    await page.getByText('Preferences saved.',{exact:true}).waitFor();
    await page.getByRole('button',{name:'New schedule',exact:true}).click();
    await page.getByLabel('Schedule name',{exact:true}).fill('Synthetic retained schedule');
    await page.getByLabel('Recipient email addresses (comma separated)',{exact:true}).fill('synthetic@example.invalid');
    await expire();await page.getByRole('button',{name:'Save schedule',exact:true}).click();
    await page.getByRole('button',{name:'Sign in again',exact:true}).click();await login();
    await page.getByLabel('Schedule name',{exact:true}).waitFor();
    assert.equal(await page.getByLabel('Schedule name',{exact:true}).inputValue(),'Synthetic retained schedule');
    await page.setViewportSize({width:390,height:844});
    await page.screenshot({path:path.join(evidence,'retained-schedule-mobile.png')});
    await page.setViewportSize({width:1366,height:900});
    const scheduleRequests=[];
    await page.route('**/reports/email-settings/',async route=>{
      if(route.request().postDataJSON()?.action!=='save')return route.continue();
      scheduleRequests.push(route.request().postDataJSON());
      const response=await route.fetch();assert.equal(response.status(),200);await route.abort('failed');
    },{times:1});
    await page.getByRole('button',{name:'Save schedule',exact:true}).click();
    await page.getByRole('button',{name:'Retry previous save',exact:true}).waitFor();
    await page.getByRole('button',{name:'Account',exact:true}).click();
    await page.getByRole('menuitem',{name:'Sign out',exact:true}).click();
    await page.getByText('Check the previous save before leaving this form.',{exact:true}).waitFor();
    assert.equal(await page.getByRole('dialog',{name:'Sign out?',exact:true}).count(),0);
    assert.equal(await page.getByLabel('Schedule name',{exact:true}).inputValue(),'Synthetic retained schedule');
    const scheduleRetry=page.waitForResponse(response=>response.url().endsWith('/reports/email-settings/')&&response.request().postDataJSON()?.action==='save');
    await page.getByRole('button',{name:'Retry previous save',exact:true}).click();
    const scheduleResult=await scheduleRetry;
    assert.deepEqual(scheduleResult.request().postDataJSON(),scheduleRequests[0]);
    assert.equal((await scheduleResult.json()).data.schedules.filter(row=>row.title==='Synthetic retained schedule').length,1);
    await page.getByText('Email schedule saved.',{exact:true}).waitFor();
    await page.getByRole('button',{name:'← Back to complaints',exact:true}).click();
    await page.getByRole('tab',{name:'Reports',exact:true}).click();
    const filteredReport=page.waitForResponse(response=>response.url().endsWith('/reports/')&&response.request().postDataJSON()?.table_search==='Synthetic');
    await page.getByLabel('Search report table',{exact:true}).fill('Synthetic');await filteredReport;
    await page.getByRole('button',{name:'Export',exact:true}).click();
    await page.getByRole('menuitem',{name:'Email report',exact:true}).click();
    await page.getByLabel('Email address',{exact:true}).fill('synthetic@example.invalid');
    await expire();await page.getByRole('button',{name:'Send report',exact:true}).click();
    await page.getByRole('button',{name:'Sign in again',exact:true}).click();await login();
    await page.getByLabel('Email address',{exact:true}).waitFor();
    assert.equal(await page.getByLabel('Email address',{exact:true}).inputValue(),'synthetic@example.invalid');
    await page.screenshot({path:path.join(evidence,'retained-email.png')});
    const emailRequests=[];
    await page.route('**/reports/email/',async route=>{
      emailRequests.push(route.request().postDataJSON());
      const response=await route.fetch();assert.equal(response.status(),200);await route.abort('failed');
    },{times:1});
    await page.getByRole('button',{name:'Send report',exact:true}).click();
    await page.getByRole('button',{name:'Retry previous save',exact:true}).waitFor();
    assert.equal(await page.getByRole('button',{name:'Download filtered Excel',exact:true}).isDisabled(),true,'Uncertain email cannot be dismissed by starting an Excel export');
    assert.equal(await page.getByRole('button',{name:'Download all complaints',exact:true}).isDisabled(),true);
    const retriedDelivery=page.waitForResponse(response=>response.url().endsWith('/reports/email/'));
    await page.getByRole('button',{name:'Retry previous save',exact:true}).click();
    const deliveryResponse=await retriedDelivery;
    assert.deepEqual(deliveryResponse.request().postDataJSON(),emailRequests[0]);
    assert.equal(emailRequests[0].filters.search,'Synthetic','Email scope must survive native reauthentication even when the visible report resets');
    await page.getByRole('button',{name:'Check delivery',exact:true}).waitFor();
    // Modal focus is contained and keyboard dismissal uses the existing guard.
    await page.getByRole('button',{name:'Check delivery',exact:true}).focus();
    for(let index=0;index<8;index++){await page.keyboard.press('Tab');const focus=await page.evaluate(()=>({inside:Boolean(document.activeElement?.closest('dialog[open]')),chrome:document.activeElement===document.body,tag:document.activeElement?.tagName}));assert.ok(focus.inside||focus.chrome,'Keyboard focus must not enter the inert background: '+JSON.stringify(focus));}
    await page.keyboard.press('Escape');
    await page.getByRole('dialog',{name:'Export report',exact:true}).waitFor({state:'detached'});
    process.stdout.write(JSON.stringify({passed:true}));
  } finally {await browser.close();}
}
main().catch(error=>{process.stderr.write(error.stack+'\n');process.exitCode=1;});
