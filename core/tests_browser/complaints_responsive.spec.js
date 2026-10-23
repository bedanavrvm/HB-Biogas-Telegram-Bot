'use strict';
// Opt-in, synthetic loopback review only. No credentials or session state on disk.
const { test, expect } = require('playwright/test');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const origin = process.env.COMPLAINTS_REVIEW_ORIGIN;
test.use({ trace: 'off', video: 'off', screenshot: 'off' });
test.skip(!origin, 'Start the isolated local review host and set COMPLAINTS_REVIEW_ORIGIN.');
test('responsive Complaints, automatic drafts, charts and media', async ({ page, context }, testInfo) => {
  test.setTimeout(180000);
  page.setDefaultTimeout(15000);
  page.on('pageerror',error=>console.error('Browser runtime:',error.message));
  expect(['127.0.0.1','localhost']).toContain(new URL(origin).hostname);
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  page.on('response',response=>{if(response.status()>=500)console.error('Synthetic HTTP failure:',new URL(response.url()).pathname,response.status());});
  const artifact=path.resolve('browser',process.env.COMPLAINTS_REVIEW_BUILD||'dist-complaints-operations');
  const manifest=JSON.parse(fs.readFileSync(path.join(artifact,'build-manifest.json'),'utf8'));
  const assets=new Map(manifest.files.map(item=>{const bytes=fs.readFileSync(path.join(artifact,item.name));expect(crypto.createHash('sha256').update(bytes).digest('hex')).toBe(item.sha256);return ['/'+item.name,bytes];}));
  // A running human review is startup-pinned. This context alone reads the new
  // checked build while keeping its real isolated native API and authorization.
  await context.route('**/*',async route=>{
    const url=new URL(route.request().url());if(url.origin!==origin)return route.abort();
    const doc=url.pathname.startsWith('/staff/app/complaints/');
    const body=assets.get(doc?'/complaints-operations.html':url.pathname);
    if(!body)return route.continue();
    const contentType=doc?'text/html':url.pathname.endsWith('.css')?'text/css':'application/javascript';
    await route.fulfill({status:200,contentType,body,headers:{'Cache-Control':'no-store'}});
  });
  let credentials;
  if(process.env.COMPLAINTS_REVIEW_USERNAME) credentials=[process.env.COMPLAINTS_REVIEW_USERNAME,process.env.COMPLAINTS_REVIEW_PASSWORD,process.env.COMPLAINTS_REVIEW_CODE];
  else {await page.goto(origin+'/_review/');credentials=await page.locator('dd code').allTextContents();}
  await page.goto(origin+'/staff/app/complaints/');
  await page.getByLabel(/^Staff username/).fill(credentials[0]);await page.getByLabel(/^Password/).fill(credentials[1]);await page.getByRole('button',{name:'Sign in',exact:true}).click();
  await page.getByRole('heading',{name:'Check your authenticator',exact:true}).waitFor();
  await page.getByRole('button',{name:'Use a recovery code',exact:true}).click();
  await page.getByLabel(/^Recovery code/).fill(credentials[2]);await page.getByRole('button',{name:'Verify',exact:true}).click();
  await page.getByRole('button',{name:'Create complaint',exact:true}).waitFor();
  await page.locator('section[aria-label="Complaint queue"] a').first().waitFor();
  const capture=async name=>{await page.screenshot({path:testInfo.outputPath(name+'.png')});const dismiss=page.getByRole('button',{name:'Dismiss notification',exact:true});if(await dismiss.count())await dismiss.click();};
  const select=async(label,value)=>{const scope=page.getByRole('dialog');await scope.getByLabel(label,{exact:true}).fill(value);await scope.getByRole('option',{name:value,exact:true}).click();};
  await page.route('**/cases/',async route=>{const response=await route.fetch(),data=await response.json();if(data.filter_options)data.filter_options.branches=Array.from({length:100},(_,i)=>({label:`Synthetic branch ${String(i).padStart(3,'0')}`,count:1}));await route.fulfill({response,json:data});});
  for(const theme of ['light','dark']){
    await page.emulateMedia({colorScheme:theme});
    for(const width of [320,360,390,768,1366,1920]){
      await page.setViewportSize({width,height:width<768?844:900});await page.waitForTimeout(100);
      await expect(page.getByRole('button',{name:/^Switch to (light|dark) mode$/})).toBeVisible();
      const geometry=await page.getByLabel('Scrollable complaints',{exact:true}).evaluate(element=>({height:element.clientHeight,content:element.scrollHeight,bottom:element.getBoundingClientRect().bottom,overflow:getComputedStyle(element).overflowY,main:document.querySelector('[role="main"]').scrollHeight,available:document.querySelector('[role="main"]').clientHeight}));
      expect(geometry.overflow).toBe('auto');expect(geometry.height).toBeGreaterThan(150);expect(geometry.content).toBeGreaterThan(geometry.height);expect(geometry.bottom).toBeLessThanOrEqual(page.viewportSize().height);expect(geometry.main).toBeLessThanOrEqual(geometry.available+32);
      expect(await page.getByRole('combobox').count()).toBe(0);
      await capture('queue-'+theme+'-'+width);
    }
  }
  await page.setViewportSize({width:390,height:844});
  await page.getByRole('button',{name:'Refresh workspace',exact:true}).click();await page.waitForResponse(response=>response.url().endsWith('/cases/'));
  await page.getByRole('button',{name:/^Filters/}).click();const filters=page.getByRole('dialog',{name:'Filter complaints',exact:true});await expect(filters).toBeVisible();
  const filterBounds=await filters.boundingBox(),filterScroll=await filters.getByLabel('Dialog content',{exact:true}).evaluate(node=>node.scrollTop);
  await filters.getByLabel('Branch',{exact:true}).click();const lastBranch=filters.getByRole('option',{name:'Synthetic branch 099',exact:true});await lastBranch.scrollIntoViewIfNeeded();
  expect(await filters.getByRole('listbox').evaluate(node=>node.scrollHeight>node.clientHeight)).toBe(true);
  expect((await filters.boundingBox()).height).toBe(filterBounds.height);expect(await filters.getByLabel('Dialog content',{exact:true}).evaluate(node=>node.scrollTop)).toBe(filterScroll);
  const menuBounds=await filters.getByRole('listbox').boundingBox();expect(menuBounds.y).toBeGreaterThanOrEqual(0);expect(menuBounds.y+menuBounds.height).toBeLessThanOrEqual(844);
  await capture('long-filter-menu-mobile');await lastBranch.click();await filters.getByRole('button',{name:'Reset filters',exact:true}).click();await capture('queue-filters-mobile');await filters.getByRole('button',{name:'Done',exact:true}).click();
  await page.getByLabel('Scrollable complaints',{exact:true}).evaluate(element=>element.scrollTop=250);const position=await page.getByLabel('Scrollable complaints',{exact:true}).evaluate(element=>element.scrollTop);
  await page.locator('section[aria-label="Complaint queue"] a').nth(3).click();await page.getByRole('button',{name:/Back to complaints/}).click();expect(await page.getByLabel('Scrollable complaints',{exact:true}).evaluate(element=>element.scrollTop)).toBeGreaterThanOrEqual(position-5);
  await page.getByRole('button',{name:'Switch to light mode',exact:true}).click();await expect(page.locator('html')).toHaveAttribute('data-color-mode','light');await expect(page.getByRole('dialog')).toHaveCount(0);
  await page.getByRole('button',{name:'Switch to dark mode',exact:true}).click();await expect(page.locator('html')).toHaveAttribute('data-color-mode','dark');
  const draftRead=page.waitForResponse(response=>response.url().endsWith('/draft/')&&response.request().method()==='GET');await page.getByRole('button',{name:'Create complaint',exact:true}).click();await draftRead;await page.waitForTimeout(100);await expect(page.getByRole('button',{name:'Save draft',exact:true})).toHaveCount(0);
  if(await page.getByRole('button',{name:'Discard',exact:true}).count()){page.once('dialog',d=>d.accept());const discarded=page.waitForResponse(response=>response.url().endsWith('/draft/')&&response.request().method()==='POST');await page.getByRole('button',{name:'Discard',exact:true}).click();await discarded;await page.waitForTimeout(100);}
  const create=page.getByRole('dialog',{name:'Create complaint',exact:true}),firstField=page.getByLabel(/^Customer name/),beforeSave=await firstField.boundingBox();let draftRequest;
  await page.route('**/draft/',route=>{if(route.request().method()==='POST')draftRequest=route;else return route.continue();});
  const saved=page.waitForResponse(response=>response.url().endsWith('/draft/')&&response.request().method()==='POST');await firstField.fill('Synthetic responsive draft');
  await expect(create.getByLabel('Draft save status',{exact:true})).toHaveText('Saving…');expect(Math.abs((await firstField.boundingBox()).y-beforeSave.y)).toBeLessThan(1);await capture('create-saving-header');
  await draftRequest.continue();await saved;await page.unroute('**/draft/');
  await expect(create.getByLabel('Draft save status',{exact:true})).toHaveText('Saved');expect(Math.abs((await firstField.boundingBox()).y-beforeSave.y)).toBeLessThan(1);await capture('create-saved-header');
  for(const width of [320,360,390,768,1366,1920]){await page.setViewportSize({width,height:width<768?844:900});const bounds=await create.boundingBox();expect(bounds.x).toBeGreaterThanOrEqual(0);expect(bounds.x+bounds.width).toBeLessThanOrEqual(width);await expect(create.getByLabel('Draft save status',{exact:true})).toBeVisible();await expect(create.getByRole('button',{name:'Submit complaint',exact:true})).toBeVisible();await capture('create-layout-'+width);}
  await page.setViewportSize({width:390,height:844});await page.evaluate(()=>document.documentElement.style.fontSize='32px');await expect.poll(()=>create.getByLabel('Dialog actions',{exact:true}).locator('> div').evaluate(node=>getComputedStyle(node).gridTemplateColumns.split(' ').length)).toBe(1);await capture('create-enlarged-text');await page.evaluate(()=>document.documentElement.style.fontSize='');
  const submit=create.getByRole('button',{name:'Submit complaint',exact:true});expect(await submit.evaluate(node=>getComputedStyle(node).backgroundColor)).not.toBe('rgba(0, 0, 0, 0)');
  await create.getByLabel('Dialog content',{exact:true}).evaluate(node=>node.scrollTop=node.scrollHeight);await expect(submit).toBeVisible();await expect(create.getByLabel('Draft save status',{exact:true})).toBeVisible();await capture('create-attachments-footer');
  const submitBox=await submit.boundingBox(),cancelBox=await create.getByRole('button',{name:'Cancel',exact:true}).boundingBox();expect(Math.abs(submitBox.y-cancelBox.y)).toBeLessThan(1);expect(Math.abs(submitBox.width-cancelBox.width)).toBeLessThan(1);
  await context.setOffline(true);await firstField.fill('Synthetic offline draft');await expect(create.getByLabel('Draft save status',{exact:true})).toHaveText('Offline');await page.waitForTimeout(900);await expect(firstField).toHaveValue('Synthetic offline draft');await capture('create-offline-status');await context.setOffline(false);await create.getByRole('button',{name:'Retry draft',exact:true}).click();await expect(create.getByLabel('Draft save status',{exact:true})).toHaveText('Saved');
  await page.route('**/draft/',route=>route.request().method()==='POST'?route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:'Synthetic draft unavailable'})}):route.continue());await firstField.fill('Synthetic recovered draft');await expect(create.getByLabel('Draft save status',{exact:true})).toHaveText('Not saved');await expect(firstField).toHaveValue('Synthetic recovered draft');await capture('create-save-failure');await page.unroute('**/draft/');await create.getByRole('button',{name:'Retry draft',exact:true}).click();await expect(create.getByLabel('Draft save status',{exact:true})).toHaveText('Saved');
  await create.getByLabel('Dialog content',{exact:true}).evaluate(node=>node.scrollTop=0);
  await page.getByRole('button',{name:'Submit complaint',exact:true}).click();await capture('two-column-field-errors');
  const labelTypeface=await page.locator('label').first().evaluate(node=>getComputedStyle(node).fontFamily);
  expect(labelTypeface).not.toMatch(/Times New Roman|^serif$/i);
  const typographySession=await context.newCDPSession(page);
  await typographySession.send('DOM.enable');await typographySession.send('CSS.enable');
  const documentNode=await typographySession.send('DOM.getDocument');
  const labelNode=await typographySession.send('DOM.querySelector',{nodeId:documentNode.root.nodeId,selector:'dialog label'});
  const renderedTypeface=await typographySession.send('CSS.getPlatformFontsForNode',{nodeId:labelNode.nodeId});
  await typographySession.detach();
  await testInfo.attach('rendered-label-typeface',{body:JSON.stringify({declared:labelTypeface,rendered:renderedTypeface.fonts}),contentType:'application/json'});
  expect(renderedTypeface.fonts.some(font=>/Times New Roman|Cambria|Georgia/i.test(font.familyName))).toBe(false);
  const alignment=await page.evaluate(()=>{const borderTop=input=>{let node=input;while(node&&!(parseFloat(getComputedStyle(node).borderTopWidth)>0))node=node.parentElement;return node.getBoundingClientRect().top;};return Math.abs(borderTop(document.querySelector('[id="create-sub_county"]'))-borderTop(document.querySelector('[name="village"]')));});expect(alignment).toBeLessThan(3);
  page.once('dialog',d=>d.accept());await page.getByRole('dialog',{name:'Create complaint',exact:true}).getByRole('button',{name:'Close',exact:true}).click();
  await page.getByRole('tab',{name:'Reports',exact:true}).click();await page.getByRole('grid',{name:'Complaint results',exact:true}).waitFor();
  expect(await page.getByRole('combobox').count()).toBe(0);
  await page.getByRole('button',{name:/^Filters/}).click();await select('Date range','Specific quarter');await page.getByLabel('Year',{exact:true}).fill('2025');await select('Quarter','Q2');
  expect(new URL(page.url()).searchParams.get('from')).toBe('2025-04-01');expect(new URL(page.url()).searchParams.get('to')).toBe('2025-06-30');await capture('report-filters-mobile');await select('Date range','All dates');await page.getByRole('button',{name:'Done',exact:true}).click();
  await page.getByRole('grid',{name:'Complaint results',exact:true}).waitFor();await page.getByRole('button',{name:'Columns',exact:true}).click();await expect(page.getByLabel('Visible columns',{exact:true})).toBeVisible();await capture('report-columns');await page.getByRole('button',{name:'Done',exact:true}).click();
  await page.getByRole('button',{name:'Export report',exact:true}).click();const downloaded=page.waitForEvent('download');await page.getByRole('button',{name:'Download filtered Excel',exact:true}).click();expect((await downloaded).suggestedFilename()).toMatch(/\.xlsx$/);await page.getByRole('dialog',{name:'Export report',exact:true}).waitFor({state:'detached'});await page.waitForTimeout(100);await expect(page.getByRole('tab',{name:'Turnaround',exact:true})).toBeVisible();
  const category=page.getByRole('region',{name:'Complaint types chart',exact:true});await category.getByRole('button',{name:'Pie chart',exact:true}).click();await expect(category.locator('svg[aria-label="Complaint types"]')).toBeVisible();await capture('category-pie');
  await category.getByRole('button',{name:'Bar chart',exact:true}).click();
  for(const width of [360,390,768,1366]){await page.setViewportSize({width,height:width<768?844:900});await page.getByRole('button',{name:/^Switch to (light|dark) mode$/}).scrollIntoViewIfNeeded();await capture('reports-'+width);}
  await page.getByRole('tab',{name:'Turnaround',exact:true}).click();
  for(const width of [320,360,390]){await page.setViewportSize({width,height:844});const metrics=page.getByRole('group',{name:'Turnaround metrics',exact:true});await metrics.waitFor();const tops=await metrics.evaluate(node=>Array.from(node.children).map(item=>item.getBoundingClientRect().top));expect(Math.max(...tops)-Math.min(...tops)).toBeLessThan(2);await capture('turnaround-metrics-'+width);}
  await page.evaluate(()=>document.documentElement.style.fontSize='32px');await expect.poll(()=>page.getByRole('group',{name:'Turnaround metrics',exact:true}).evaluate(node=>getComputedStyle(node).gridTemplateColumns.split(' ').length)).toBe(1);await capture('turnaround-enlarged-text');await page.evaluate(()=>document.documentElement.style.fontSize='');
  await page.setViewportSize({width:1366,height:900});await page.getByRole('tab',{name:'Overview',exact:true}).click();
  await category.getByRole('button',{name:'About Complaint types',exact:true}).click();await expect(page.getByRole('dialog',{name:'Complaint types',exact:true})).toBeVisible();await page.getByRole('dialog').getByRole('button',{name:'Close',exact:true}).click();
  await category.locator('svg[aria-label^="Complaint types."]').getByRole('button').first().press('Enter');await expect(page.locator('[aria-label="Filtered report complaints"]')).toBeFocused();await capture('chart-drill-table');
  // Network fixtures exercise presentation only; the endpoint's real ownership,
  // CSRF and subprocess PDF contracts are covered by native Django tests.
  const png=await page.screenshot();
  await page.route(/\/cases\/[a-f0-9-]+\/$/,async route=>{const response=await route.fetch(),data=await response.json();data.case.evidence=[{id:'synthetic-image',name:'Synthetic evidence.png',mime_type:'image/png'},{id:'synthetic-pdf',name:'Synthetic evidence.pdf',mime_type:'application/pdf'},{id:'synthetic-timeout',name:'Synthetic timeout.png',mime_type:'image/png'}];await route.fulfill({response,json:data});});
  await page.route('**/evidence/synthetic-image/',route=>route.fulfill({status:200,contentType:'image/png',body:png}));
  await page.route('**/evidence/synthetic-pdf/preview/',route=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({image:'data:image/png;base64,'+png.toString('base64'),page:route.request().postDataJSON().page,page_count:2})}));
  await page.getByRole('tab',{name:'Complaints',exact:true}).click();await page.locator('section[aria-label="Complaint queue"] a').first().click();await page.getByRole('button',{name:'Preview',exact:true}).first().click();
  const viewer=page.getByRole('dialog',{name:'Synthetic evidence.png',exact:true});await viewer.getByAltText('Synthetic evidence.png',{exact:true}).waitFor();
  await viewer.getByRole('button',{name:'Zoom in',exact:true}).click();await viewer.getByRole('button',{name:'Zoom in',exact:true}).click();
  expect(await viewer.getByLabel('Scrollable document preview',{exact:true}).evaluate(node=>node.scrollWidth>node.clientWidth)).toBe(true);
  await viewer.getByLabel('Scrollable document preview',{exact:true}).evaluate(node=>{node.scrollLeft=node.scrollWidth;node.scrollTop=node.scrollHeight;});await capture('media-zoomed-edge');await viewer.getByRole('button',{name:'Close',exact:true}).click();
  await page.getByRole('button',{name:'Preview',exact:true}).nth(1).click();const pdf=page.getByRole('dialog',{name:'Synthetic evidence.pdf',exact:true});await pdf.getByAltText('Synthetic evidence.pdf',{exact:true}).waitFor();await pdf.getByRole('button',{name:'Next page',exact:true}).click();await expect(pdf.getByText('Page 2 of 2',{exact:true})).toBeVisible();await capture('pdf-second-page');await pdf.getByRole('button',{name:'Close',exact:true}).click();
  await page.clock.install();let pending;await page.route('**/evidence/synthetic-timeout/',route=>{pending=route;});await page.getByRole('button',{name:'Preview',exact:true}).nth(2).click();await page.clock.runFor(31000);const timed=page.getByRole('dialog',{name:'Synthetic timeout.png',exact:true});await expect(timed.getByText('Preview took too long. Try again or download the file.',{exact:true}).first()).toBeVisible();await expect(timed.getByRole('button',{name:'Retry preview',exact:true})).toBeVisible();await capture('preview-timeout-toast');await timed.getByRole('button',{name:'Close',exact:true}).click();if(pending)await pending.abort().catch(()=>{});
  expect(errors).toEqual([]);
});
