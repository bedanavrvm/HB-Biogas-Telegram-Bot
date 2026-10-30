/* Direct manual browser observations; no assertions or automated test runner. */
const {chromium}=require('playwright');
const fs=require('node:fs');const path=require('node:path');
const base=__dirname,origin='http://127.0.0.1:8778';
(async()=>{
 const browser=await chromium.launch();const context=await browser.newContext({viewport:{width:390,height:886}});
 const errors=[],requests=[],observations=[];let stage='start';
 await context.route('**/*',route=>{const url=new URL(route.request().url());if(url.origin===origin&&route.request().method()==='GET')return route.continue();requests.push({method:route.request().method(),url:route.request().url()});return route.abort();});
 const page=await context.newPage();page.setDefaultTimeout(10000);page.on('pageerror',e=>errors.push({stage,message:e.message}));
 const open=async(id,v='a')=>{stage=id+'-'+v;await page.goto(`${origin}/preview.html?case=${id}&variant=${v}`);};
 const output=path.join(base,'assets','interactions');fs.mkdirSync(output,{recursive:true});
 const capture=async(name)=>{await page.screenshot({path:path.join(output,name+'.png'),animations:'disabled'});};
 try{
  for(const v of ['a','b']){
   await open('queue',v);await page.getByRole('searchbox').fill('no-such-case');
   observations.push({stage:'queue-no-results',variant:v,visible:await page.getByText('No matching cases',{exact:true}).isVisible(),rows:await page.locator('.queue-card:visible').count()});await capture('queue-empty-'+v);
   await page.getByRole('button',{name:'Clear search',exact:true}).click();await page.getByRole('button',{name:'Open',exact:true}).nth(1).click();await page.waitForURL('**record=1');
   observations.push({stage:'selected-case',variant:v,url:page.url(),identity:await page.locator('.identity-summary').innerText()});
  }
  await open('credit','b');await page.locator('[name=credit-decision]').selectOption('Approved');
  observations.push({stage:'credit-approved-fields',negativeVisible:await page.locator('#negative-fields').isVisible(),approvalVisible:await page.locator('#approval-fields').isVisible()});await capture('credit-approval-fields-b');
  await page.locator('[name=credit-decision]').selectOption('Rejected');await page.locator('[name=decision-note]').fill('SYNTHETIC preview: negative outcome reason retained.');
  await page.getByRole('button',{name:'Save credit decision',exact:true}).click();await page.locator('#task-dialog[open]').waitFor();await page.keyboard.press('Escape');
  observations.push({stage:'credit-cancel-retains-note',value:await page.locator('[name=decision-note]').inputValue()});
  await open('visit','b');await page.locator('[name=village]').fill('SYNTHETIC local landmark');await page.locator('[data-section=visit-evidence]').click();
  await capture('visit-evidence-section-b');await page.getByRole('button',{name:'Add',exact:true}).first().click();
  await page.locator('#task-dialog input[type=file]').setInputFiles(path.join(base,'assets/before/queue.png'));
  observations.push({stage:'local-evidence-selected',file:await page.locator('#task-dialog input[type=file]').evaluate(n=>n.files[0]?.name),message:await page.locator('[data-local-feedback]').innerText()});await page.keyboard.press('Escape');
  await page.locator('[data-section=visit-details]').click();observations.push({stage:'visit-tabs-retain-value',value:await page.locator('[name=village]').inputValue()});
  await open('final-review','b');await page.locator('[name=final-decision]').selectOption('Rejected');
  observations.push({stage:'final-negative-fields',visible:await page.locator('#final-negative').isVisible(),readyShortcutVisible:await page.locator('[data-action=ready-comment]').isVisible()});await capture('final-rejected-fields-b');
  await page.locator('[name=final-decision]').selectOption('Approved');await page.locator('[data-action=ready-comment]').click();await page.locator('[data-action=ready-comment]').click();
  observations.push({stage:'final-ready-phrase',comment:await page.locator('[name=final-comment]').inputValue()});
  await open('farmup','b');await page.locator('[data-select-row]').first().uncheck();
  observations.push({stage:'bulk-selection-retains-unseen-rows',selection:await page.locator('#selection-count').innerText(),footer:await page.locator('.footer-copy').innerText()});
  await page.getByRole('button',{name:'Review commit',exact:true}).click();await capture('farmup-confirmation-b');observations.push({stage:'bulk-confirmation',text:await page.locator('#task-dialog').innerText()});await page.keyboard.press('Escape');
  await page.locator('[data-row-filter=held]').click();observations.push({stage:'held-filter',visibleRows:await page.locator('[data-row-held]:visible').count()});
  await open('payment-return','b');await page.locator('[data-payment-filter=Returned]').click();
  observations.push({stage:'payment-returned-filter',rows:await page.locator('[data-payment-case]:visible').count()});
  await page.locator('[data-action=payment-case-1]').click();await page.locator('#task-dialog [data-mode=LOAN-JAWABU]').click();await capture('payment-returned-case-b');await page.keyboard.press('Escape');
  observations.push({stage:'payment-mode-local-retention',mode:await page.locator('[data-payment-case="1"] .payment-row-action .caption').innerText()});
  for(const v of ['a','b']){
   await open('upload-error',v);await page.locator('input[data-file=agreement]').setInputFiles({name:'synthetic-agreement.pdf',mimeType:'application/pdf',buffer:Buffer.from('Synthetic preview selection only')});
   await page.getByRole('button',{name:'Retry upload',exact:true}).click();
   const before={file:await page.locator('#chosen-file').innerText(),confirmed:await page.locator('[name=confirmed]').isChecked(),message:await page.locator('#upload-result').innerText()};await capture('upload-denied-retained-'+v);
   await page.getByRole('button',{name:'Simulate access restored',exact:true}).click();await page.getByRole('button',{name:'Retry upload',exact:true}).click();
   observations.push({stage:'upload-retry-retained',variant:v,before,fileAfter:await page.locator('#chosen-file').innerText(),result:await page.locator('#upload-result').innerText()});
  }
  await open('document','b');await page.getByRole('button',{name:'Next page',exact:true}).click();await page.getByRole('button',{name:'Next page',exact:true}).click();await page.locator('#document-page').evaluate(img=>img.decode());
  await capture('retained-document-page-three-b');observations.push({stage:'document-page-three',source:await page.locator('#document-page').getAttribute('src'),counter:await page.locator('#page-number').innerText()});
  await page.locator('[data-action=zoom-document]').click();observations.push({stage:'document-zoom',viewport:await page.evaluate(()=>innerWidth),pageWidth:await page.evaluate(()=>document.documentElement.scrollWidth),documentWidth:await page.locator('.document-canvas').evaluate(n=>n.scrollWidth)});
  await open('performance','b');await page.locator('[data-action=performance-filters]').click();await page.locator('[name=period]').selectOption('June 2026');await page.getByRole('button',{name:'Apply period',exact:true}).click();
  observations.push({stage:'performance-empty-period',text:await page.locator('#standings').innerText()});await capture('performance-empty-period-b');
  await page.locator('[data-action=performance-filters]').click();await page.locator('[name=period]').selectOption('October 2026');await page.getByRole('button',{name:'Apply period',exact:true}).click();
  observations.push({stage:'performance-restored-period',text:await page.locator('#standings').innerText()});
  await open('settings','b');await page.locator('[name=start-on]').selectOption('All cases');await page.locator('[data-settings-category=account]').click();await page.locator('[data-settings-category=preferences]').click();observations.push({stage:'settings-category-retains-choice',value:await page.locator('[name=start-on]').inputValue()});
  await page.goto(origin+'/index.html');await page.locator('#review-search').fill('invoice');observations.push({stage:'gallery-search',groups:await page.locator('.recommendation:visible').count()});await page.locator('#review-search').fill('');
  const scenario=page.locator('#scenario-invoice');await scenario.locator('[data-mode-button=b]').click();await scenario.locator('[data-panel=b] img').click();await page.locator('#image-viewer[open]').waitFor();await page.keyboard.press('Escape');observations.push({stage:'gallery-image-close',viewerOpen:await page.locator('#image-viewer').evaluate(n=>n.open),mode:await scenario.getAttribute('data-mode')});
  await page.setViewportSize({width:1280,height:900});await page.goto(origin+'/index.html');await capture('gallery-desktop');
  await page.setViewportSize({width:390,height:844});await page.goto(origin+'/index.html');await capture('gallery-mobile');observations.push({stage:'gallery-mobile-size',viewport:await page.evaluate(()=>innerWidth),documentWidth:await page.evaluate(()=>document.documentElement.scrollWidth)});
 }catch(error){observations.push({stage,error:String(error.stack||error)});console.log('Browser interaction stopped at '+stage+': '+error.message);}
 finally{fs.writeFileSync(path.join(base,'interaction-observations.json'),JSON.stringify({captured_at:new Date().toISOString(),method:'Direct Playwright interactions; no assertions or test runner',observations,errors,blockedRequests:requests},null,2)+'\n');await browser.close();console.log(JSON.stringify({observations:observations.length,errors,blockedRequests:requests}));}
})();
