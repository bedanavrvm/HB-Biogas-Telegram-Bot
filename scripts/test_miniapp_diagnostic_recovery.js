/* Native PostgreSQL faults are injected by the live Django fixture, not browser routes. */
'use strict';
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require('playwright');
(async()=>{
  let input='';for await(const chunk of process.stdin)input+=chunk;
  const config=JSON.parse(input);assert.ok(['localhost','127.0.0.1'].includes(new URL(config.origin).hostname));
  fs.mkdirSync(config.artifacts,{recursive:true});const browser=await chromium.launch();
  const page=await browser.newPage({viewport:{width:1280,height:900}}),errors=[];
  page.setDefaultTimeout(30000);page.on('pageerror',error=>errors.push(error.message));
  await page.route('**/*',route=>new URL(route.request().url()).origin===config.origin?route.continue():route.abort());
  await page.setExtraHTTPHeaders({'X-Telegram-Init-Data':config.initData});
  await page.addInitScript(initData=>{window.Telegram={WebApp:{initData,ready(){},expand(){},onEvent(){},offEvent(){},BackButton:{onClick(){},offClick(){},show(){},hide(){}},MainButton:{hide(){},offClick(){},onClick(){}}}};},config.initData);
  const signal=r=>new URL(r.url()).pathname.startsWith('/api/miniapp-diagnostics/sessions/')&&r.url().includes('/signals/');
  const failed=page.waitForResponse(r=>signal(r)&&r.status()===503).then(response=>({response,at:Date.now()}));
  const recovered=page.waitForResponse(r=>signal(r)&&r.status()===200).then(response=>({response,at:Date.now()}));
  try{
    await page.goto(config.origin+'/portal/s/legacy/');
    const failedResult=await failed,failure=failedResult.response,body=await failure.json();
    assert.deepEqual(body.acknowledged,[]);assert.equal(failure.headers()['retry-after'],'5');
    const originalEvents=failure.request().postDataJSON().events.map(event=>event.event_uuid);
    await page.getByRole('heading',{name:'Legacy import',exact:true}).waitFor();
    await page.getByRole('button',{name:'Eco-conserve',exact:true}).click();
    await page.waitForFunction(()=>document.querySelector('[data-source-sheet="Eco-conserve"]').getAttribute('aria-pressed')==='true');
    await page.screenshot({path:path.join(config.artifacts,'01-ui-responsive-during-diagnostic-outage.png'),animations:'disabled'});
    const recoveredResult=await recovered,success=recoveredResult.response,delay=recoveredResult.at-failedResult.at,ack=await success.json();
    assert.ok(delay>=4500,'The client must honor the server five-second backoff');
    assert.ok(originalEvents.every(id=>ack.acknowledged.includes(id)),'Retry must preserve the original event UUIDs');
    await page.screenshot({path:path.join(config.artifacts,'02-events-recovered-without-reload.png'),animations:'disabled'});
    await page.goto(config.origin+'/portal/s/settings/');
    const mode=page.locator('[data-portal-maintenance-form] [name=mode]');await mode.waitFor();
    assert.equal(await mode.inputValue(),'maintenance','Telemetry recovery must not unlock Portal');
    await mode.selectOption('live');
    const switched=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/portal/health/maintenance/'&&r.request().method()==='POST');
    await page.getByRole('button',{name:'Save maintenance mode',exact:true}).click();
    assert.equal((await switched).status(),200);
    const pump=await page.evaluate(async()=>{const r=await fetch('/api/portal/publication/pump/',{method:'POST',headers:{'Content-Type':'application/json','X-Request-ID':crypto.randomUUID()},body:'{}'});return {status:r.status,data:await r.json()};});
    assert.equal(pump.status,200);assert.equal(pump.data.paused,true);assert.equal(pump.data.reason,'legacy_cutover_maintenance');
    await page.screenshot({path:path.join(config.artifacts,'03-it-restores-live-with-cutover-still-held.png'),animations:'disabled'});
    assert.deepEqual(errors,[]);
    fs.writeFileSync(path.join(config.artifacts,'observations.json'),JSON.stringify({signals:[503,200],emptyAckDuringOutage:true,originalEventsAcknowledged:true,retryDelayMs:delay,uiResponsive:true,maintenancePreservedDuringTelemetry:true,itRestoresLive:true,cutoverStillHeld:true,scriptErrors:errors},null,2));
  }catch(error){await page.screenshot({path:path.join(config.artifacts,'failure.png'),animations:'disabled'});throw error;}
  finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
