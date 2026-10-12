'use strict';
const fs = require('node:fs');
const path = require('node:path');
const {test, expect} = require('playwright/test');
const root = path.resolve(__dirname, '../..');
const asset = (owner, name) => path.join(root, owner, 'static', 'miniapp', name);
const html = fs.readFileSync(path.join(root, 'origination/templates/loan_origination/sign.html'), 'utf8')
  .replace(/\{%[\s\S]*?%\}/g, '').replace(/<script[\s\S]*?<\/script>/g, '').replace(/<link[^>]+>/g, '')
  .replace('src=""', `src="data:image/png;base64,${fs.readFileSync(asset('core','jawabu-logo.png')).toString('base64')}"`);
async function mount(page, options = {}) {
  const errors = [], requests = [];
  let packetReads = 0, verifyAttempts = 0, consentAttempts = 0;
  const session = {reference:'ORG-SYNTHETIC', signer_name:'Synthetic Applicant', signer_role:'borrower',
    phone_masked:'*******0000', access_mode:options.assisted ? 'assisted' : 'self_service',
    status:options.verified ? 'verified' : 'pending', consented:options.verified || false,
    documents:[{key:'main', name:'Main LAF', page_count:1}], reviewed_pages:[], packet_version:'synthetic-v1',
    signing_policy:'all_required', application_status:options.approved ? 'approved' : 'partially_signed',
    verified_at:'2026-10-12T09:00:00+03:00', otp:{}, consent_text:'I reviewed these documents and agree to sign.'};
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/*', async route => {
    const url = new URL(route.request().url());
    if(url.hostname !== '127.0.0.1') return route.abort();
    if(url.pathname === '/sign/') return route.fulfill({contentType:'text/html', body:html});
    if(url.pathname.endsWith('/session/')) return route.fulfill({json:{ok:true,session}});
    if(url.pathname.endsWith('/packet/')) {
      packetReads++;
      return route.fulfill({contentType:'image/png',body:fs.readFileSync(asset('core','jawabu-logo.png')),
        headers:{'X-Preview-Page-Count':'1','X-Signing-Packet-Version':'synthetic-v1'}});
    }
    requests.push({path:url.pathname, key:route.request().headers()['idempotency-key']});
    if(url.pathname.endsWith('/consent/')) {
      consentAttempts++;
      if(options.captureFailure) return route.fulfill({status:400,json:{ok:false,message:'Signature could not be saved.'}});
      if(options.captureTimeout && consentAttempts===1) return route.abort();
      session.consented = true;
      return route.fulfill({json:{ok:true,session}});
    }
    if(url.pathname.endsWith('/otp/')) {
      if(options.smsFailure) return route.fulfill({status:502,json:{ok:false,message:'Code delivery failed.'}});
      session.otp={expires_at:'2099-01-01T00:00:00Z',resend_available_at:'2000-01-01T00:00:00Z'};
      return route.fulfill({json:{ok:true,session}});
    }
    if(url.pathname.endsWith('/verify/')) {
      verifyAttempts++;
      if(options.wrongCode) return route.fulfill({status:400,json:{ok:false,message:'The code is incorrect. Try again.'}});
      session.status='verified';
      if(options.verifyTimeout && verifyAttempts===1) return route.abort();
      return route.fulfill({json:{ok:true,session}});
    }
    return route.fulfill({json:{ok:true}});
  });
  await page.goto('http://127.0.0.1/sign/#synthetic-signing-token');
  await page.addStyleTag({path:asset('core','base.css')});
  for(const name of ['origination_signing.css','origination_signing_feedback.css','origination_signing_completion.css'])
    await page.addStyleTag({path:asset('origination',name)});
  await page.evaluate(telegram => {
    window.__closed=0;
    if(telegram) window.Telegram={WebApp:{initData:'synthetic-init',close(){window.__closed++;},ready(){},expand(){},onEvent(){}}};
  }, options.telegram || false);
  await page.addScriptTag({path:asset('core','utils.js')});
  await page.addScriptTag({path:asset('origination','origination_signing_completion.js')});
  await page.addScriptTag({path:asset('origination','origination_signing.js')});
  if(!options.verified) await expect(page.locator('#signature-card')).toBeVisible();
  return {errors, requests, packetReads:()=>packetReads};
}
async function save(page, assisted=false) {
  await page.getByRole('button',{name:'Type',exact:true}).click();
  await page.getByLabel('Type your full legal name').fill('Synthetic Applicant');
  await page.locator('#packet-consent').check();
  if(assisted) await page.locator('#assisted-consent').check();
  await page.locator('#save-signature').click();
}
async function finish(page) {
  await save(page);
  await page.getByLabel('Six-digit code').fill('123456');
  await page.getByRole('button',{name:'Finish signing',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Signature saved'})).toBeVisible();
}
for(const width of [320,375,430,1280]) for(const colorScheme of ['light','dark']) test(`signing acknowledgement ${width} ${colorScheme}`,async({page},info)=>{
  await page.emulateMedia({colorScheme});
  await page.setViewportSize({width,height:844});
  const audit=await mount(page);
  await save(page);
  await expect(page.locator('#sign-status')).toContainText('to finish signing');
  await expect(page.locator('#sign-completion')).toBeHidden();
  await page.screenshot({path:info.outputPath(`verify-${width}-${colorScheme}.png`),fullPage:true});
  await page.getByLabel('Six-digit code').fill('123456');
  await page.getByRole('button',{name:'Finish signing',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Signature saved'})).toBeVisible();
  await expect(page.getByText('Awaiting other signatures or stamps.',{exact:true})).toBeVisible();
  await expect(page.locator('#sign-content')).toBeHidden();
  await expect(page.getByText('Signed 12 Oct 2026, 09:00 EAT',{exact:true})).toBeVisible();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  expect(await page.evaluate(()=>location.hash)).toBe('');
  expect(await page.evaluate(()=>sessionStorage.getItem('jbl-origination-signing-token'))).toBeNull();
  expect(audit.errors).toEqual([]);
  await page.getByRole('button',{name:'Stay here',exact:true}).click();
  await page.screenshot({path:info.outputPath(`signed-${width}-${colorScheme}.png`),fullPage:true});
});
test('verified reload skips preview; Telegram closes once after ten seconds',async({page})=>{
  await page.clock.install();
  const audit=await mount(page,{verified:true,telegram:true,approved:true});
  await expect(page.getByText('Application approved.',{exact:true})).toBeVisible();
  expect(audit.packetReads()).toBe(0);
  await page.clock.fastForward(9000);
  expect(await page.evaluate(()=>window.__closed)).toBe(0);
  await page.clock.fastForward(1000);
  expect(await page.evaluate(()=>window.__closed)).toBe(1);
  await page.clock.fastForward(20000);
  expect(await page.evaluate(()=>window.__closed)).toBe(1);
});
test('Stay here cancels exit and normal browsers get a clear close-tab fallback',async({page})=>{
  await page.clock.install();
  await mount(page,{verified:true});
  await page.getByRole('button',{name:'Stay here',exact:true}).click();
  await page.clock.fastForward(20000);
  await expect(page.getByText('Your signature is saved. Close when you are ready.',{exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Close now',exact:true}).click();
  await expect(page.getByText('You can close this tab.',{exact:true})).toBeVisible();
});
test('SMS failure keeps capture and never shows completion',async({page})=>{
  await mount(page,{smsFailure:true}); await save(page);
  await expect(page.locator('#sign-status')).toContainText('Signature saved. Code delivery failed.');
  await expect(page.getByRole('button',{name:'Resend code'})).toBeEnabled();
  await expect(page.locator('#sign-completion')).toBeHidden();
});
test('failed signature capture preserves input; wrong OTP is not completion',async({page})=>{
  const audit=await mount(page,{captureFailure:true}); await save(page);
  await expect(page.locator('#typed-name')).toHaveValue('Synthetic Applicant');
  await expect(page.locator('#sign-status')).toHaveText('Signature could not be saved.');
  await expect(page.locator('#sign-completion')).toBeHidden();
  expect(audit.errors).toEqual([]);
});
test('wrong code keeps verification open and errors visible',async({page})=>{
  await mount(page,{wrongCode:true}); await save(page);
  await page.getByLabel('Six-digit code').fill('123456');
  await page.getByRole('button',{name:'Finish signing',exact:true}).click();
  await expect(page.locator('#sign-status')).toHaveText('The code is incorrect. Try again.');
  await expect(page.locator('#otp-code')).toHaveValue('123456');
  await expect(page.locator('#sign-completion')).toBeHidden();
});
test('network loss after verified commit recovers completion from server state',async({page})=>{
  await mount(page,{verifyTimeout:true}); await finish(page);
  await expect(page.locator('#sign-status')).toBeHidden();
});
test('uncertain capture retry uses the same request key',async({page})=>{
  const audit=await mount(page,{captureTimeout:true}); await save(page);
  await expect(page.locator('#sign-status')).toContainText('could not confirm');
  await page.locator('#save-signature').click();
  await expect(page.locator('#otp-panel')).toBeVisible();
  const captures=audit.requests.filter(item=>item.path.endsWith('/consent/'));
  expect(captures).toHaveLength(2); expect(captures[0].key).toBe(captures[1].key);
});
test('assisted confirmation remains required before capture',async({page})=>{
  const audit=await mount(page,{assisted:true}); await save(page);
  expect(audit.requests).toHaveLength(0);
  await page.locator('#assisted-consent').check();
  await page.locator('#save-signature').click();
  await expect(page.locator('#otp-panel')).toBeVisible();
});
test('Admin role labels and Origination scope stay separate on workflow changes',async({page})=>{
  await page.setContent('<form><select name="workflow"><option value="jawabu_portal">Portal</option><option value="loan_origination">Origination</option><option value="tat_tracker">TAT</option></select><select name="role"><option value="BM" data-workflows="jawabu_portal,loan_origination,tat_tracker" data-role-labels=\'{"jawabu_portal":"Branch Manager","loan_origination":"Branch Manager","tat_tracker":"Branch Manager"}\'>Mixed role label</option><option value="BUSINESS_ADMIN" data-workflows="jawabu_portal,loan_origination,tat_tracker" data-role-labels=\'{"jawabu_portal":"Head of Rural","loan_origination":"Business Administrator","tat_tracker":"Business Administrator"}\'>Mixed admin label</option></select><select name="group_configuration"><option value="">All groups</option><option value="origination" data-workflow-type="loan_origination">Origination group</option><option value="tat" data-workflow-type="tat_tracker">TAT group</option></select></form>');
  await page.addScriptTag({path:path.join(root,'core/static/admin/js/access_grant_inline.js')});
  await page.locator('[name="workflow"]').selectOption('loan_origination');
  await expect(page.locator('[name="role"] option[value="BUSINESS_ADMIN"]')).toHaveText('Business Administrator');
  await expect(page.locator('[name="group_configuration"] option[value="origination"]')).toBeEnabled();
  await expect(page.locator('[name="group_configuration"] option[value="tat"]')).toBeDisabled();
  await page.locator('[name="workflow"]').selectOption('jawabu_portal');
  await expect(page.locator('[name="role"] option[value="BUSINESS_ADMIN"]')).toHaveText('Head of Rural');
  await expect(page.locator('[name="group_configuration"] option[value="origination"]')).toBeDisabled();
});
