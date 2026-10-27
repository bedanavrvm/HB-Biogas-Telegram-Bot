'use strict';
const {chromium,expect}=require('playwright/test');
const crypto=require('node:crypto');
const fs=require('node:fs');
const path=require('node:path');
function totp(secret) {
  const alphabet='ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';let bits='';
  for(const value of secret.toUpperCase().replace(/=+$/,'')) bits+=alphabet.indexOf(value).toString(2).padStart(5,'0');
  const bytes=[];for(let i=0;i+8<=bits.length;i+=8)bytes.push(parseInt(bits.slice(i,i+8),2));
  const counter=Buffer.alloc(8);counter.writeBigUInt64BE(BigInt(Math.floor(Date.now()/30000)));
  const digest=crypto.createHmac('sha1',Buffer.from(bytes)).update(counter).digest(),offset=digest[19]&15;
  return String((digest.readUInt32BE(offset)&0x7fffffff)%1000000).padStart(6,'0');
}
(async()=>{
  let raw='';for await(const part of process.stdin)raw+=part;
  const input=JSON.parse(raw),origin=new URL(input.origin).origin;
  if(!['localhost','127.0.0.1'].includes(new URL(origin).hostname))throw Error('Loopback required');
  const browser=await chromium.launch(),context=await browser.newContext({viewport:{width:1366,height:900}}),page=await context.newPage();
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  await context.route('**/*',route=>new URL(route.request().url()).origin===origin?route.continue():route.abort());
  const capture=async name=>{
    for(const theme of ['light','dark']) {
      await page.emulateMedia({colorScheme:theme});
      await page.waitForFunction(value=>document.documentElement.dataset.colorMode===value,theme);
      for(const width of [390,1366]) {
        await page.setViewportSize({width,height:900});
        await page.getByRole('main').evaluate(element=>element.scrollTo(0,0));
        await page.evaluate(()=>new Promise(requestAnimationFrame));
        await page.screenshot({path:path.join(input.output,`${name}-${theme}-${width}.png`),fullPage:true,
          mask:[page.locator('[data-sensitive], input[type="password"], input[autocomplete="one-time-code"]')]});
      }
    }
    await page.emulateMedia({colorScheme:'light'});
  };
  const password=async()=>{
    await expect(page.getByRole('heading',{name:'Sign in',exact:true})).toBeVisible();
    await page.getByLabel(/^Staff username/).fill(input.username);
    await page.getByLabel(/^Password/).fill(input.password);
    await page.getByRole('button',{name:'Sign in',exact:true}).click();
  };
  try {
    await page.goto(origin+'/staff/login/#'+new URLSearchParams({setup:input.setupId,key:input.proof}));
    await expect(page.getByRole('heading',{name:'Set up your account',exact:true})).toBeVisible();
    expect(new URL(page.url()).hash).toBe('');
    expect(await page.getByRole('link',{name:'Open-source notices'}).getAttribute('href')).toBe('/THIRD_PARTY_NOTICES.txt');
    const notices=await context.request.get(origin+'/THIRD_PARTY_NOTICES.txt');
    expect(notices.status()).toBe(200);
    await capture('mailbox-proof');
    await page.getByRole('button',{name:'Continue setup',exact:true}).click();
    await password();
    await expect(page.getByRole('heading',{name:'Set up your authenticator',exact:true})).toBeVisible();
    const secret=await page.locator('code[data-sensitive]').innerText();
    const remaining=30000-Date.now()%30000;if(remaining<4000)await new Promise(resolve=>setTimeout(resolve,remaining+100));
    const codesResponse=page.waitForResponse(response=>response.url().endsWith('/enrollment/recovery-codes/')&&response.request().method()==='POST');
    await page.getByLabel(/^Authenticator code/).fill(totp(secret));
    await page.getByRole('button',{name:'Verify',exact:true}).click();
    const codes=(await(await codesResponse).json()).recovery_codes;
    await expect(page.getByRole('heading',{name:'Save your recovery codes',exact:true})).toBeVisible();
    await page.getByRole('button',{name:'I saved my codes - sign in',exact:true}).click();
    await password();
    await expect(page.getByRole('heading',{name:'Check your authenticator',exact:true})).toBeVisible();
    await page.getByRole('button',{name:'Use a recovery code',exact:true}).click();
    await page.getByLabel(/^Recovery code/).fill(codes[0]);
    await page.getByRole('button',{name:'Verify',exact:true}).click();
    await expect(page.getByRole('heading',{name:'Complaints',exact:true})).toBeVisible();
    await page.goto(origin+'/staff/app/complaints/?workspace='+input.group);
    await expect(page.getByText('Synthetic Customer 01',{exact:true}).first()).toBeVisible();
    const session=await page.evaluate(async()=>await(await fetch('/api/staff/auth/v1/session/')).json());
    expect(session.is_authenticated).toBe(true);
    const typography=await page.evaluate(()=>({body:getComputedStyle(document.body).fontFamily,
      font:getComputedStyle(document.documentElement).getPropertyValue('--ds-font-body')}));
    fs.writeFileSync(path.join(input.output,'typography.json'),JSON.stringify(typography,null,2));
    expect(typography.body).not.toMatch(/Times New Roman|^serif$/i);
    await capture('production-complaints');
    await page.reload();await expect(page.getByText('Synthetic Customer 01',{exact:true}).first()).toBeVisible();
    expect(errors).toEqual([]);
    process.stdout.write('PASS: production routes, mailbox proof, retained password, native MFA enrollment/recovery, authenticated Complaints and reload.\n');
  } catch(error) {
    await page.screenshot({path:path.join(input.output,'failure.png'),fullPage:true,
      mask:[page.locator('[data-sensitive], input[type="password"], input[autocomplete="one-time-code"]')]}).catch(()=>{});
    throw error;
  } finally {await browser.close();}
})().catch(error=>{console.error(error.message);process.exitCode=1;});
