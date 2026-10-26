'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { chromium } = require('playwright');

async function main() {
  const root = path.resolve(__dirname, '..');
  const development = process.argv.includes('--development');
  const base = development ? 'http://127.0.0.1:8767/' : 'http://127.0.0.1:8766/';
  const build = JSON.parse(fs.readFileSync(path.join(root, development ? 'browser/dist-development/build-manifest.json' : 'browser/dist/build-manifest.json')));
  const sources = ['index.html', 'index.tsx', 'preview.tsx', 'review.html'].map(name => {
    const relative = 'browser/src/' + name;
    return { path: relative, sha256: crypto.createHash('sha256').update(fs.readFileSync(path.join(root, relative), 'utf8').replace(/\r\n/g, '\n')).digest('hex') };
  });
  assert.deepEqual(build.sources, sources, 'Reject stale source/build evidence.');
  for (const pkg of ['@atlaskit/navigation-system@11.3.1','@atlaskit/side-nav-items@2.5.8','@atlaskit/section-message@10.2.6','@atlaskit/select@23.1.3','@atlaskit/primitives@22.6.0','@atlaskit/form@18.2.0']) assert.ok(build.packages.includes(pkg), 'Missing bundled component: '+pkg);
  assert.ok(!build.packages.some(pkg => pkg.startsWith('@atlaskit/logo@')));
  const output = path.join(root, 'test-results', development ? 'ads-browser-preview-development' : 'ads-browser-preview');
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: {width:1366,height:768}, colorScheme:'light' });
  await context.addInitScript(()=>{
    window.__adsFirstFieldPaint=null;
    const observer=new MutationObserver(()=>{
      const field=document.querySelector('input[name="username"]');
      if(!field)return;
      observer.disconnect();
      requestAnimationFrame(()=>{
        const probe=document.createElement('span');probe.style.color='var(--ds-text)';probe.style.backgroundColor='var(--ds-background-input)';document.body.append(probe);
        window.__adsFirstFieldPaint={theme:document.documentElement.dataset.colorMode,color:getComputedStyle(field).color,expectedColor:getComputedStyle(probe).color,background:getComputedStyle(field.parentElement).backgroundColor,expectedBackground:getComputedStyle(probe).backgroundColor};
        probe.remove();
      });
    });
    observer.observe(document,{childList:true,subtree:true});
  });
  const page = await context.newPage();
  const errors=[], requests=[], captures=[], viewportEvidence=[], designEvidence=[];
  let checks=1;
  const allowed = new Set(['/', ...build.files.map(row=>'/'+row.name)]);
  page.on('pageerror', error=>errors.push(error.message));
  page.on('console', message=>{if(message.type()==='error')errors.push(message.text());});
  page.on('request', request=>requests.push({method:request.method(),url:request.url()}));
  await context.route('**/*', async route=>{
    const request=route.request(), url=new URL(request.url());
    if(url.origin===new URL(base).origin && allowed.has(url.pathname) && !url.search && request.method()==='GET')await route.continue();
    else {errors.push('Unexpected request: '+url.origin+url.pathname);await route.abort();}
  });
  const titles={login:'Sign in',setup:'Verify your setup link',password:'Create your password',mfa:'Check your authenticator',enroll:'Set up your authenticator',scan:'Confirm your authenticator',recovery:'Save your recovery codes',codes:'Store these somewhere safe',reauthenticate:'You are ready to sign in',shell:'Your workspace',help:'Account help'};
  const responses={success:'Success',invalid:'Invalid details',unavailable:'Service unavailable',limited:'Too many attempts',expired:'Expired session or link',enrollment:'Enrollment required'};
  const submits={login:'Sign in',setup:'Verify link',password:'Save password',mfa:'Verify',enroll:'Continue',scan:'Confirm',recovery:'Show codes'};
  const heading=title=>page.getByRole('heading',{name:title,level:1,exact:true}).waitFor();
  const capture=async name=>{
    await page.evaluate(async()=>{await Promise.all(document.getAnimations().filter(animation=>animation.effect?.getComputedTiming().iterations!==Infinity).map(animation=>animation.finished.catch(()=>{})));});
    await page.screenshot({path:path.join(output,name),fullPage:true});captures.push(name);
  };
  const select=async(label, option)=>{
    await page.getByRole('combobox',{name:label,exact:true}).focus();
    await page.keyboard.press('ArrowDown');
    await page.getByRole('option',{name:option,exact:true}).click();
  };
  const idle=()=>page.waitForFunction(()=>document.querySelector('[data-testid="access-page"]')?.getAttribute('aria-busy')==='false');
  const choose=async screen=>{
    if(new URL(page.url()).pathname==='/review.html')await select('Page',titles[screen]);
    else await page.evaluate(value=>{location.hash=value;}, screen);
    await heading(titles[screen]);await idle();
  };
  const reset=async()=>{
    if(new URL(page.url()).pathname==='/review.html')await page.getByRole('button',{name:'Reset demo',exact:true}).click();
    else await page.goto(base);
    await heading(titles.login);
  };
  const show=async screen=>{
    if(['scan','codes','recovery'].includes(screen))await reset();
    if(['scan','codes'].includes(screen)){
      await choose('enroll');await page.getByRole('button',{name:'Continue',exact:true}).click();await heading(titles.scan);
      if(screen==='codes'){
        await page.getByRole('button',{name:'Confirm',exact:true}).click();await heading(titles.recovery);
        await page.getByRole('button',{name:'Show codes',exact:true}).click();await heading(titles.codes);
      }
    } else await choose(screen);
  };
  const fit=async(screen,theme,state,entry)=>{
    await page.getByTestId('content').evaluate(el=>{el.scrollTop=0;});
    const row=await page.evaluate(()=>{
      const content=document.querySelector('[data-testid="content"]'), card=document.querySelector('[data-testid="access-page"]');
      const rect=card.getBoundingClientRect();
      const outside=[...content.querySelectorAll('button,input,a')].filter(el=>{
        const r=el.getBoundingClientRect();return r.width>0 && r.height>0 && (r.bottom>innerHeight+1||r.top<0||r.left<0||r.right>innerWidth+1);
      }).map(el=>el.getAttribute('aria-label')||el.textContent||el.name);
      return {width:innerWidth,height:innerHeight,pageHeight:document.documentElement.scrollHeight,pageWidth:document.documentElement.scrollWidth,mainHeight:content.clientHeight,mainScrollHeight:content.scrollHeight,outside,cardWidth:rect.width,cardShadow:getComputedStyle(card).boxShadow,noticeCount:document.querySelectorAll('#demo-notice').length};
    });
    const label=[entry,screen,state,theme,row.width+'x'+row.height].join('/');
    assert.ok(row.pageHeight<=row.height+1,'Body scrolling: '+label+' '+row.pageHeight);
    assert.ok(row.mainScrollHeight<=row.mainHeight+1,'Main scrolling: '+label+' '+JSON.stringify(row));
    assert.ok(row.pageWidth<=row.width,'Horizontal overflow: '+label);
    assert.deepEqual(row.outside,[],'Offscreen action: '+label);
    assert.equal(row.cardShadow,'none','Flat access/workspace surface: '+label);
    assert.equal(row.noticeCount,1);
    if(!['shell','help'].includes(screen))assert.ok(row.cardWidth<=500.1,'Keep access task bounded: '+label);
    viewportEvidence.push({entry,screen,theme,state,...row});checks++;
    if(row.width===1280 && (state==='normal'||screen==='login'))await capture([entry,screen,state,theme,'1280x720.png'].join('-'));
  };
  try {
    await page.goto(base);await heading(titles.login);
    assert.equal(await page.getByRole('combobox').count(),0);
    assert.equal(await page.getByTestId('review-controls').count(),0);
    assert.equal(await page.locator('#demo-notice').count(),1);
    assert.equal(await page.getByLabel('Staff username',{exact:true}).inputValue(),'demo.staff');
    assert.equal(await page.getByLabel('Password',{exact:true}).getAttribute('readonly'),'');
    assert.equal(await page.getByText('Fixed demo value. Do not enter real credentials.',{exact:true}).count(),0);checks++;
    await page.getByRole('button',{name:'Sign in',exact:true}).click();await heading(titles.mfa);
    await page.getByRole('button',{name:'Use a recovery code',exact:true}).click();await heading('Use a recovery code');
    await page.getByRole('button',{name:'Verify',exact:true}).click();await heading(titles.shell);
    assert.equal(await page.getByTestId('workflow-card').count(),4);
    assert.equal(await page.getByTestId('workflow-card').locator('button:disabled').count(),0);
    await page.getByRole('link',{name:'Sign out',exact:true}).click();await heading(titles.login);checks++;
    await page.getByRole('link',{name:'Set up your account',exact:true}).click();await heading(titles.setup);
    await page.getByRole('button',{name:'Verify link',exact:true}).click();await heading(titles.password);
    await page.getByRole('button',{name:'Save password',exact:true}).click();await heading(titles.reauthenticate);checks++;

    await page.goto(base+'review.html');await heading(titles.login);
    assert.equal(await page.getByRole('combobox').count(),3);checks++;
    await select('Response',responses.enrollment);await page.getByRole('button',{name:'Sign in',exact:true}).click();await heading(titles.enroll);
    await select('Response',responses.success);await page.getByRole('button',{name:'Continue',exact:true}).click();await heading(titles.scan);
    await page.getByRole('button',{name:'Confirm',exact:true}).click();await heading(titles.recovery);
    await page.getByRole('button',{name:'Show codes',exact:true}).click();await heading(titles.codes);
    await page.getByRole('link',{name:'I saved my codes',exact:true}).click();await heading(titles.reauthenticate);
    await choose('recovery');assert.ok(await page.getByText('Codes have already been shown.',{exact:false}).count());
    await page.evaluate(()=>{location.hash='codes';});await heading(titles.recovery);assert.equal(await page.getByTestId('demo-codes').count(),0);checks++;

    for(const entry of ['staff','review']){
      for(const theme of ['light','dark']){
        await page.mouse.move(0,0);
        await page.emulateMedia({colorScheme:theme});await page.goto(base+(entry==='review'?'review.html':''));await heading(titles.login);
        await page.waitForFunction(value=>document.documentElement.dataset.colorMode===value,theme);
        await page.waitForFunction(()=>window.__adsFirstFieldPaint!==null);
        const firstPaint=await page.evaluate(()=>window.__adsFirstFieldPaint);
        assert.equal(firstPaint.theme,theme,'First field paint must honor the system theme.');
        assert.equal(firstPaint.background,firstPaint.expectedBackground,'First field paint must use the loaded input background token.');
        assert.equal(firstPaint.color,firstPaint.expectedColor,'First field paint must use the loaded text token.');
        const evidence=await page.evaluate(()=>{
          const probe=document.createElement('div');document.body.append(probe);
          const resolve=(property,variable)=>{probe.style.cssText=property+':var('+variable+')';return getComputedStyle(probe).getPropertyValue(property);};
          const rows=[['heading',getComputedStyle(document.querySelector('h1')).font,resolve('font','--ds-font-heading-large')],['body',getComputedStyle(document.querySelector('[data-testid="task-description"]')).font,resolve('font','--ds-font-body')]];
          probe.remove();return rows;
        });
        for(const [kind,actual,expected] of evidence)assert.equal(actual,expected,'Loaded ADS '+kind+' typography must remain authoritative.');
        designEvidence.push({entry,theme,firstPaint,values:evidence});checks++;
        for(const screen of Object.keys(titles)){
          await show(screen);
          for(const viewport of [{width:1280,height:720},{width:1366,height:768},{width:1440,height:900}]){
            await page.setViewportSize(viewport);await fit(screen,theme,'normal',entry);
          }
        }
      }
    }
    for(const theme of ['light','dark']){
      await page.emulateMedia({colorScheme:theme});await page.goto(base+'review.html');await heading(titles.login);
      for(const [screen,submit] of Object.entries(submits)){
        await select('Response',responses.success);await show(screen);
        for(const state of ['invalid','unavailable','limited','expired']){
          await select('Response',responses[state]);await page.getByRole('button',{name:submit,exact:true}).click();await idle();await page.getByRole('alert').waitFor();
          const order=await page.getByTestId('access-page').evaluate(el=>{
            const alert=el.querySelector('[role="alert"]'), form=el.querySelector('form');return Boolean(alert.compareDocumentPosition(form)&Node.DOCUMENT_POSITION_FOLLOWING);
          });assert.ok(order,'Feedback must precede the form.');
          assert.equal(await page.getByRole('alert').getByRole('heading',{level:2}).count(),1);
          assert.equal(await page.getByRole('alert').getByRole('button',{name:'Details'}).count(),0);
          for(const viewport of [{width:1280,height:720},{width:1366,height:768},{width:1440,height:900}]){await page.setViewportSize(viewport);await fit(screen,theme,state,'review');}
        }
      }
      await select('Response',responses.success);await choose('login');await page.getByRole('button',{name:'Sign in',exact:true}).click();await heading(titles.mfa);checks++;
    }

    for(const width of [320,390])for(const theme of ['light','dark']){
      await page.setViewportSize({width,height:844});await page.emulateMedia({colorScheme:theme});await page.goto(base);await heading(titles.login);
      for(const screen of Object.keys(titles)){
        await show(screen);
        assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Mobile overflow: '+screen);
        for(const field of await page.getByTestId('access-page').locator('input').all())assert.equal(await field.getAttribute('readonly'),'');
        await capture(screen+'-'+theme+'-'+width+'.png');checks++;
      }
    }
    await page.setViewportSize({width:390,height:844});await page.goto(base+'#shell');await heading(titles.shell);
    await page.getByRole('button',{name:'Open navigation',exact:true}).click();await page.getByRole('link',{name:'Overview',exact:true}).waitFor();
    await page.getByRole('button',{name:'Close navigation',exact:true}).click();checks++;
    await page.goto(base+'review.html');await heading(titles.login);
    await page.getByRole('combobox',{name:'Theme',exact:true}).focus();await page.keyboard.press('ArrowDown');await page.getByRole('option',{name:'Dark',exact:true}).click();
    await page.waitForFunction(()=>document.documentElement.dataset.colorMode==='dark');
    await select('Theme','System');await page.emulateMedia({colorScheme:'light'});await page.waitForFunction(()=>document.documentElement.dataset.colorMode==='light');
    await page.emulateMedia({colorScheme:'dark'});await page.waitForFunction(()=>document.documentElement.dataset.colorMode==='dark');checks++;
    await page.goto(base);await heading(titles.login);await page.keyboard.press('Tab');
    await page.getByRole('link',{name:'Page content',exact:true}).click();
    assert.equal(await page.evaluate(()=>document.activeElement.id),'content');checks++;
    await choose('mfa');assert.equal(await page.evaluate(()=>document.activeElement.id),'page-heading');await page.keyboard.press('Tab');assert.equal(await page.evaluate(()=>document.activeElement.name),'mfa-code');checks++;
    await page.setViewportSize({width:390,height:844});await choose('login');await page.evaluate(()=>{document.documentElement.style.fontSize='200%';});
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await capture('access-text-200-390.png');
    await page.getByRole('button',{name:'Sign in',exact:true}).scrollIntoViewIfNeeded();await page.getByRole('button',{name:'Sign in',exact:true}).click();await heading(titles.mfa);checks++;
    await page.evaluate(()=>{document.documentElement.style.fontSize='';});
    assert.deepEqual(await context.cookies(),[]);assert.deepEqual(await page.evaluate(()=>({local:localStorage.length,session:sessionStorage.length})),{local:0,session:0});assert.deepEqual(errors,[]);checks++;
    fs.writeFileSync(path.join(output,'report.json'),JSON.stringify({checks,sources,designEvidence,viewportEvidence,captures,requests,errors,buildMode:build.mode,dependencyLock:build.dependencyLock,actualADSPackages:build.packages.filter(pkg=>pkg.startsWith('@atlaskit/')),syntheticOnly:true,humanApproval:false},null,2)+'\n');
    console.log('ADS composition: '+checks+' checks passed, '+viewportEvidence.length+' desktop fits, '+captures.length+' captures; no unexpected network/errors/storage/cookies.');
  } finally {await browser.close();}
}
main().catch(error=>{console.error(error);process.exitCode=1;});
