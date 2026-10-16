'use strict';
const fs=require('node:fs');const path=require('node:path');const {execFileSync}=require('node:child_process');
const {test,expect}=require('playwright/test');
const root=path.resolve(__dirname,'../..');const fixture=path.join(root,'test-results/ui-lab-browser');
let manifest;
test.beforeAll(()=>{
  const python=path.join(root,'.venv',process.platform==='win32'?'Scripts/python.exe':'bin/python');
  execFileSync(fs.existsSync(python)?python:'python',['-c',
    "import sys,os; sys.argv=['manage.py','test']; os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings'); from django.conf import settings; settings.DATABASES={'default':{'ENGINE':'django.db.backends.sqlite3','NAME':':memory:'}}; import django; django.setup(); from django.core.management import call_command; call_command('export_ui_audit',output='test-results/ui-lab-browser')"],
    {cwd:root,env:{...process.env,ORIGINATION_LAF_BOOTSTRAP_ENABLED:'false'},stdio:'pipe'});
  manifest=JSON.parse(fs.readFileSync(path.join(fixture,'manifest.json'),'utf8'));
});

async function openLab(page,{width=390,denied=false}={}){
  await page.setViewportSize({width,height:844});const calls=[];const revisions=new Map();
  await page.route('**/*',async route=>{
    const request=route.request(),url=new URL(request.url());
    if(url.origin!=='http://127.0.0.1:8127')return route.abort();
    if(url.pathname==='/ui-lab/')return route.fulfill({contentType:'text/html',body:fs.readFileSync(path.join(fixture,'lab.html'))});
    if(manifest.assets[url.pathname]){
      const source=path.join(root,manifest.assets[url.pathname]);const ext=path.extname(source);
      return route.fulfill({contentType:ext==='.js'?'text/javascript':ext==='.css'?'text/css':ext==='.png'?'image/png':'text/plain',body:fs.readFileSync(source)});
    }
    if(!url.pathname.startsWith('/ui-lab/api/')){calls.push({unexpected:url.pathname,method:request.method()});return route.abort();}
    if(denied)return route.fulfill({status:403,json:{ok:false,error:'Design Lab requires an active Superuser account.'}});
    if(url.pathname.endsWith('/catalogue/'))return route.fulfill({json:{ok:true,patterns:manifest.patterns,states:manifest.states,roles:['staff','manager','it'],releases:[]}});
    if(url.pathname.includes('/patterns/')){
      const key=url.pathname.split('/').at(-2);return route.fulfill({json:{ok:true,manifest:manifest.comparisons[key],revisions:[...revisions.values()].filter(item=>item.pattern===key)}});
    }
    if(url.pathname==='/ui-lab/api/revisions/'){
      const body=request.postDataJSON();const revision={id:'rev-'+body.pattern,pattern:body.pattern,fingerprint:body.fingerprint,current:true,evidence:[],decisions:[]};
      revisions.set(revision.id,revision);calls.push({snapshot:body});return route.fulfill({json:{ok:true,revision}});
    }
    if(url.pathname.includes('/scenes/')){
      const parts=url.pathname.split('/');const file=`${parts[4]}-${parts[5]}-${url.searchParams.get('state')||'one'}.html`;
      return route.fulfill({contentType:'text/html',body:fs.readFileSync(path.join(fixture,file))});
    }
    if(url.pathname.endsWith('/decisions/')){
      const body=request.postDataJSON(),revision=revisions.get(url.pathname.split('/')[4]);calls.push({decision:body});
      revision.decisions.push({id:'decision-1',decision:body.decision,payload:body.payload,at:'2026-10-16T09:00:00+03:00'});
      return route.fulfill({json:{ok:true,revision}});
    }
    if(url.pathname.endsWith('/evidence/'))return route.fulfill({status:503,json:{ok:false,error:'Screenshot could not be stored. Keep the file and retry; no approval was recorded.'}});
    return route.fulfill({status:422,json:{ok:false,error:'Review foundations first. No standard is approved yet.'}});
  });
  await page.goto('http://127.0.0.1:8127/ui-lab/');
  if(!denied)await expect(page.locator('#pattern-list button')).toHaveCount(31);
  return calls;
}

for(const width of [320,390,1280])for(const mode of ['light','dark']){
  test(`Design Lab foundations fit ${width}px in ${mode}`,async({page},info)=>{
    const errors=[];page.on('pageerror',error=>errors.push(error.message));await openLab(page,{width});
    await page.locator('#lab-mode').selectOption(mode);await page.locator('#lab-theme').selectOption('jbl');
    await expect(page.locator('.specimen')).toContainText('Candidate only');
    await page.locator('#variant').selectOption('spacious');await page.locator('#toggle-measures').click();
    await expect(page.locator('.specimen')).toHaveAttribute('data-measures','true');
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    await page.screenshot({path:info.outputPath(`lab-foundations-${width}-${mode}.png`),fullPage:true});
    expect(errors).toEqual([]);
  });
}

test('theme selection persists, density choice remains a proposal',async({page})=>{
  await openLab(page);await page.locator('#lab-theme').selectOption('jbl');await page.locator('#lab-mode').selectOption('dark');
  await page.reload();await expect(page.locator('#lab-theme')).toHaveValue('jbl');await expect(page.locator('body')).toHaveAttribute('data-ui-mode','dark');
  await expect(page.locator('#release-list')).toBeEmpty();
  await page.locator('#prepare-release').click();await expect(page.locator('#lab-toast')).toContainText('No standard is approved');
});

for(const app of ['portal','tat','complaints','origination']){
  test(`source-backed ${app} card scene is interactive but cannot write`,async({page},info)=>{
    const calls=await openLab(page);await page.locator('[data-pattern=cards]').click();await page.locator('#variant').selectOption(app);
    const selector={portal:'.farmer-card',tat:'.case-card',complaints:'.case-row',origination:'.application-card'}[app];
    const frame=page.frameLocator('#specimen-host iframe');await expect(frame.locator(selector)).toHaveCount(1);
    await expect(frame.locator(selector)).toContainText('Synthetic Wanjiku');
    await expect(page.locator('#specimen-host iframe')).toHaveAttribute('sandbox','allow-scripts');
    const child=page.frames().find(item=>item.parentFrame());
    expect(await child.evaluate(async()=>{try{window.parent.document.body;return true;}catch(_error){return false;}})).toBe(false);
    expect(await child.evaluate(async()=>{const r=await fetch('/api/portal/payments/forbidden-business-write/',{method:'POST'});return r.status;})).toBe(403);
    expect(calls.filter(item=>item.unexpected)).toEqual([]);
    await page.screenshot({path:info.outputPath(`lab-source-${app}-390.png`),fullPage:true});
  });
}

test('saving a requested change keeps evidence and live migration distinct',async({page})=>{
  const calls=await openLab(page);const form=page.locator('#decision-form');
  await form.locator('[name=decision]').selectOption('changes');await form.locator('[name=reason]').fill('Use the compact layout, but leave more space around the close control.');
  await form.getByRole('button',{name:'Save decision'}).click();await expect(page.locator('#lab-toast')).toContainText('Decision saved');
  const decision=calls.find(item=>item.decision).decision;expect(decision.decision).toBe('changes');expect(decision.payload.variant).toBe('compact');
  expect(decision.request_key).toBeTruthy();await expect(page.locator('.lab-hold')).toHaveText('Phase 6 on hold');
  await expect(page.locator('#review-history')).toContainText('Use the compact layout');
  await page.locator('#review-filter').selectOption('changes');
  await expect(page.locator('#pattern-list button')).toHaveCount(1);
  await expect(page.locator('#pattern-list button')).toHaveAttribute('data-pattern','foundations');
  await page.locator('#review-filter').selectOption('approved');
  await expect(page.locator('#pattern-list button')).toHaveCount(0);
});

test('original Portal redirects stay inside the synthetic navigation adapter',async({page})=>{
  const calls=await openLab(page);await page.locator('[data-pattern=history]').click();await page.locator('#variant').selectOption('portal');
  const frame=page.frameLocator('#specimen-host iframe');await expect(frame.locator('#portal-screen')).toBeVisible();
  await expect.poll(async()=>{const child=page.frames().find(item=>item.parentFrame());return child.evaluate(()=>window.UI_SCENE.calls.some(item=>item.method==='page-navigation-blocked'));}).toBe(true);
  expect(calls.filter(item=>item.unexpected)).toEqual([]);
});

test('evidence upload failure keeps file selected and records no approval',async({page})=>{
  const calls=await openLab(page);await page.locator('#evidence-panel summary').click();const input=page.locator('#evidence-form input[type=file]');
  await input.setInputFiles({name:'Synthetic capture.png',mimeType:'image/png',buffer:Buffer.from('synthetic-fixture')});
  await page.locator('[name=synthetic_only]').check();await page.getByRole('button',{name:'Save screenshot'}).click();
  await expect(page.locator('#lab-toast')).toContainText('Keep the file and retry');expect(await input.evaluate(node=>node.files.length)).toBe(1);
  expect(calls.filter(item=>item.decision)).toEqual([]);
});

test('unauthorized bootstrap reveals no patterns and browser diagnostics do not impersonate Telegram',async({page})=>{
  await openLab(page,{denied:true});await expect(page.locator('#lab-access')).toContainText('active Superuser');await expect(page.locator('#lab-workspace')).toBeHidden();
  await page.getByRole('button',{name:'Device checks'}).click();await expect(page.locator('#device-values')).not.toContainText('initData');
  await page.getByRole('button',{name:'Test vibration'}).click();await expect(page.locator('#lab-toast')).toContainText('inside Telegram');
});
