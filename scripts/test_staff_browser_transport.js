'use strict';
// Launched only by LiveServerTestCase. Synthetic proof travels over stdin and
// is never written into reports, screenshots, command lines or request logs.
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const readline = require('node:readline');
const { chromium } = require('playwright');

async function main() {
  const lines = readline.createInterface({ input: process.stdin })[Symbol.asyncIterator]();
  const input = JSON.parse((await lines.next()).value);
  const root = path.resolve(__dirname, '..');
  const manifest = JSON.parse(fs.readFileSync(path.join(root, 'browser', input.build, 'build-manifest.json')));
  assert.equal(manifest.closedAuthentication, true); assert.equal(manifest.demoOnly, false);
  assert.ok(['production','development'].includes(manifest.mode));
  const origin = new URL(input.origin);
  assert.ok(['localhost','127.0.0.1'].includes(origin.hostname));
  const output = path.join(root, 'test-results', 'staff-browser-transport', manifest.mode);
  fs.mkdirSync(output, { recursive: true });
  const allowed = new Set(['/', ...manifest.files.map(row => '/' + row.name), ...['session','login','mfa','logout'].map(name => '/api/staff/auth/v1/' + name + '/'), '/test-context/identity/', '/test-context/complaints/']);
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width:1280, height:720 }, colorScheme:'light' });
  const page = await context.newPage();
  const requests=[], errors=[], captures=[], evidence=[];
  let checks=0;
  const control = async name => { process.stdout.write(JSON.stringify({control:name})+'\n'); assert.equal(JSON.parse((await lines.next()).value).ok,true); };
  await context.route('**/*', async route => {
    const request=route.request(), url=new URL(request.url());
    if(url.origin===origin.origin && allowed.has(url.pathname) && !url.search && ['GET','POST'].includes(request.method())) await route.continue();
    else { errors.push('Unexpected network destination or path'); await route.abort(); }
  });
  page.on('request', request => requests.push({path:new URL(request.url()).pathname,method:request.method()}));
  page.on('pageerror', () => errors.push('Unhandled browser exception'));
  page.on('console', message => { if(message.type()==='error' && !/^Failed to load resource:/.test(message.text())) errors.push('Unexpected console error'); });
  const heading=async name=>{ await page.getByRole('heading',{level:1,name,exact:true}).waitFor(); await page.getByTestId('auth-content').locator('section[aria-busy]').evaluate(async el=>{while(el.getAttribute('aria-busy')==='true')await new Promise(resolve=>setTimeout(resolve,10));}); };
  const capture=async name=>{
    // Never capture entered proof, including a synthetic TOTP/recovery value.
    for(const field of await page.locator('input[type=password], input[name=code]').all()) assert.equal(await field.inputValue(),'');
    const layout=await page.getByTestId('auth-content').evaluate(el=>({width:innerWidth,height:innerHeight,pageWidth:document.documentElement.scrollWidth,pageHeight:document.documentElement.scrollHeight,mainHeight:el.clientHeight,mainScrollHeight:el.scrollHeight}));
    assert.ok(layout.pageWidth<=layout.width,'No horizontal clipping in access tasks.');
    if(layout.width===1280){assert.ok(layout.pageHeight<=layout.height+1);assert.ok(layout.mainScrollHeight<=layout.mainHeight+1);}
    evidence.push({capture:name,...layout});
    await page.evaluate(async()=>{await Promise.all(document.getAnimations().filter(a=>a.effect?.getComputedTiming().iterations!==Infinity).map(a=>a.finished.catch(()=>{})));});
    await page.screenshot({path:path.join(output,name),fullPage:true}); captures.push(name);
  };
  const count=action=>requests.filter(row=>row.method==='POST' && row.path==='/api/staff/auth/v1/'+action+'/').length;
  const recheck=()=>page.evaluate(()=>document.dispatchEvent(new Event('visibilitychange')));
  const password=async(value=input.password)=>{
    await page.getByLabel(/^Staff username\s*\*?$/).fill(input.username);
    await page.getByLabel(/^Password\s*\*?$/).fill(value);
    await page.getByRole('button',{name:'Sign in',exact:true}).click();
  };
  const recovery=async index=>{
    await page.getByRole('button',{name:'Use a recovery code',exact:true}).click();
    await heading('Use a recovery code');
    await capture('recovery-light-1280-'+index+'.png');
    await page.getByLabel(/^Recovery code\s*\*?$/).fill(input.recovery[index]);
    await page.getByRole('button',{name:'Verify',exact:true}).click(); await heading('Your workspace');
  };
  const totp=()=>{
    const alphabet='ABCDEFGHIJKLMNOPQRSTUVWXYZ234567'; let bits='';
    for(const character of input.secret.toUpperCase().replace(/=+$/,'')) bits+=alphabet.indexOf(character).toString(2).padStart(5,'0');
    const bytes=[]; for(let i=0;i+8<=bits.length;i+=8)bytes.push(parseInt(bits.slice(i,i+8),2));
    const counter=Buffer.alloc(8);counter.writeBigUInt64BE(BigInt(Math.floor(Date.now()/30000)));
    const digest=crypto.createHmac('sha1',Buffer.from(bytes)).update(counter).digest(); const offset=digest[19]&15;
    return String((digest.readUInt32BE(offset)&0x7fffffff)%1000000).padStart(6,'0');
  };
  try {
    await page.goto(origin.origin+'/#authenticated'); await heading('Sign in');
    assert.equal(await page.getByRole('combobox').count(),0);
    assert.equal(await page.locator('input[readonly]').count(),0);
    assert.equal(await page.getByLabel(/^Staff username\s*\*?$/).getAttribute('autocomplete'),'username');
    await capture('login-light-1280.png'); checks++;
    await page.getByRole('button',{name:'Sign in',exact:true}).click();assert.equal(count('login'),0);checks++;
    const direct=await page.evaluate(async()=>({identity:(await fetch('/test-context/identity/')).status,noCsrf:(await fetch('/api/staff/auth/v1/login/',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:'unknown',password:'wrong'})})).status}));
    assert.deepEqual(direct,{identity:403,noCsrf:403});checks++;
    await password('incorrect-synthetic-value');await page.getByRole('alert').waitFor();await heading('Sign in');
    assert.equal(await page.getByLabel(/^Staff username\s*\*?$/).inputValue(),input.username);
    assert.equal(await page.getByLabel(/^Password\s*\*?$/).inputValue(),'');
    await capture('invalid-password-light-1280.png');checks++;
    const oldCsrf=(await context.cookies()).find(cookie=>cookie.name==='csrftoken').value;
    await password();await heading('Check your authenticator');
    const passwordOnly=await page.evaluate(async()=>(await fetch('/test-context/identity/')).status);
    assert.equal(passwordOnly,403);checks++;
    await page.getByLabel(/^Authenticator code\s*\*?$/).fill('invalid-code');await page.getByRole('button',{name:'Verify',exact:true}).click();await page.getByRole('alert').waitFor();await heading('Check your authenticator');checks++;
    await page.reload();await heading('Check your authenticator'); // no password re-entry
    await capture('mfa-light-1280.png');checks++;
    let dropped=0;
    await page.route('**/api/staff/auth/v1/mfa/',async route=>{dropped++;const response=await route.fetch();await route.fulfill({response,body:'{'});});
    await page.getByLabel(/^Authenticator code\s*\*?$/).fill(totp());await page.getByRole('button',{name:'Verify',exact:true}).click();await heading('Check your session');
    const used=count('mfa');assert.equal(dropped,1);assert.equal(await page.getByRole('heading',{name:'Your workspace',exact:true}).count(),0);
    await page.unroute('**/api/staff/auth/v1/mfa/');await page.getByRole('button',{name:'Check session',exact:true}).click();await heading('Your workspace');assert.equal(count('mfa'),used);checks++;
    const newCsrf=(await context.cookies()).find(cookie=>cookie.name==='csrftoken').value; assert.notEqual(oldCsrf,newCsrf);checks++;
    const authority=await page.evaluate(async()=>({identity:(await fetch('/test-context/identity/')).status,complaints:(await fetch('/test-context/complaints/')).status}));
    assert.deepEqual(authority,{identity:200,complaints:403});checks++;
    await capture('authenticated-light-1280.png');await page.reload();await heading('Your workspace');checks++;
    const stale=await page.evaluate(async token=>(await fetch('/api/staff/auth/v1/logout/',{method:'POST',headers:{'Content-Type':'application/json','X-CSRFToken':token},body:'{}'})).status,oldCsrf);
    assert.equal(stale,403);checks++;
    await page.route('**/api/staff/auth/v1/session/',route=>route.abort());
    await recheck();await heading('Check your session');
    assert.equal(await page.getByRole('button',{name:'Sign out',exact:true}).count(),0);
    await capture('network-unconfirmed-light-1280.png');
    await page.unroute('**/api/staff/auth/v1/session/');await page.getByRole('button',{name:'Check session',exact:true}).click();await heading('Your workspace');checks++;
    await control('expire');await recheck();await heading('Sign in');
    assert.equal(await page.evaluate(async()=>(await fetch('/test-context/identity/')).status),403);checks++;
    await password();await heading('Check your authenticator');await recovery(0);checks++;
    await control('revoke');await recheck();await heading('Sign in');
    assert.equal(await page.evaluate(async()=>(await fetch('/test-context/identity/')).status),403);checks++;
    await password();await page.getByRole('alert').waitFor();await heading('Sign in');
    assert.equal(await page.getByRole('button',{name:'Verify',exact:true}).count(),0);checks++;
    await control('authorize');await password();await heading('Check your authenticator');await recovery(1);checks++;
    await page.getByRole('button',{name:'Sign out',exact:true}).click();await heading('Sign in');await page.reload();await heading('Sign in');checks++;
    await page.route('**/api/staff/auth/v1/login/',route=>route.continue({headers:{...route.request().headers(),'x-csrftoken':'0'.repeat(32)}}));
    const before=count('login');await password();await heading('Check your session');assert.equal(count('login'),before+1);
    await page.unroute('**/api/staff/auth/v1/login/');await page.getByRole('button',{name:'Check session',exact:true}).click();await heading('Sign in');assert.equal(count('login'),before+1);checks++;
    // Late success after navigation must never bring authenticated UI back.
    let release, completed, finishDelivery, discarded=false;const gate=new Promise(resolve=>{release=resolve;}), accepted=new Promise(resolve=>{completed=resolve;}), delivery=new Promise(resolve=>{finishDelivery=resolve;});
    await page.route('**/api/staff/auth/v1/login/',async route=>{
      const response=await route.fetch();completed();await gate;
      // Navigation deliberately discards this response; a closed request cannot
      // be fulfilled. Do not turn the injected abort into a runner crash.
      try {await route.fulfill({response});} catch {if(!discarded)errors.push('Unexpected delayed-response delivery failure.');} finally {finishDelivery();}
    });
    await password();await accepted;
    discarded=true;await page.reload();release();await delivery;await page.unroute('**/api/staff/auth/v1/login/');
    await page.getByRole('heading',{level:1,name:/^(Sign in|Check your authenticator)$/}).waitFor();
    assert.equal(await page.getByRole('heading',{level:1,name:'Your workspace',exact:true}).count(),0);checks++;
    if(await page.getByRole('button',{name:'Cancel sign in',exact:true}).count())await page.getByRole('button',{name:'Cancel sign in',exact:true}).click();
    await heading('Sign in');
    await control('unenroll');await password();await heading('Authenticator setup required');
    assert.equal(await page.evaluate(async()=>(await fetch('/test-context/identity/')).status),403);
    await capture('setup-handoff-light-1280.png');await page.getByRole('button',{name:'Sign out',exact:true}).click();await heading('Sign in');checks++;
    await page.setViewportSize({width:390,height:844});await page.emulateMedia({colorScheme:'dark'});await page.reload();await heading('Sign in');
    await page.waitForFunction(()=>document.documentElement.dataset.colorMode==='dark');
    assert.equal(await page.getByRole('button',{name:'Show more',exact:true}).count(),0,'No empty mobile action menu on sign-in.');
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await capture('login-dark-390.png');checks++;
    await page.evaluate(()=>{document.documentElement.style.fontSize='200%';});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await capture('login-text-200-390.png');checks++;
    assert.deepEqual(await page.evaluate(()=>({local:localStorage.length,session:sessionStorage.length})),{local:0,session:0});
    assert.ok((await context.cookies()).every(cookie=>['csrftoken','sessionid'].includes(cookie.name)));
    assert.deepEqual(errors,[]);checks++;
    const harnessSources=['scripts/test_staff_browser_transport.js','staff_auth/browser_api.py','staff_auth/assurance.py','staff_auth/replay.py','staff_auth/tests_transport.py','staff_auth/transport_test_urls.py','staff_auth/transport_test_settings.py','staff_auth/transport_test_runner.py'].map(name=>({path:name,sha256:crypto.createHash('sha256').update(fs.readFileSync(path.join(root,name),'utf8').replace(/\r\n/g,'\n')).digest('hex')}));
    fs.writeFileSync(path.join(output,'report.json'),JSON.stringify({checks,sources:manifest.sources,harnessSources,dependencyLock:manifest.dependencyLock,mode:manifest.mode,captures,requests,evidence,syntheticOnly:true,realNativeAuthentication:true,productionAccepted:false,errors},null,2)+'\n');
    fs.rmSync(path.join(output,'failure.json'),{force:true});
    process.stdout.write(JSON.stringify({passed:true,checks,captures:captures.length})+'\n');
  } catch (error) {
    const diagnostic=await page.evaluate(()=>({headings:[...document.querySelectorAll('h1')].map(el=>el.textContent),visibility:document.visibilityState,inputs:[...document.querySelectorAll('input')].map(el=>({name:el.name,labelledBy:el.getAttribute('aria-labelledby'),labels:[...el.labels||[]].map(label=>label.textContent)})),buttons:[...document.querySelectorAll('button')].map(el=>({text:el.textContent,type:el.type}))})).catch(()=>({}));
    fs.writeFileSync(path.join(output,'failure.json'),JSON.stringify({checks,errorKind:error.name,requests,...diagnostic},null,2)+'\n');
    throw error;
  } finally {await browser.close();}
}
main().catch(error=>{process.stderr.write(String(error.stack).split('\n').filter(line=>/^\s+at /.test(line)).join('\n')+'\n');process.stdout.write(JSON.stringify({passed:false,message:'Closed browser scenario failed; inspect the test locally without retaining proof.'})+'\n');process.exitCode=1;});
