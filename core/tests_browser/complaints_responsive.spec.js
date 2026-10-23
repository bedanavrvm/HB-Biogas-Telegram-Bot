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
  const capture=async name=>{await page.screenshot({path:testInfo.outputPath(name+'.png')});};
  const select=async(label,value)=>{const scope=page.getByRole('dialog');await scope.getByLabel(label,{exact:true}).fill(value);await scope.getByRole('option',{name:value,exact:true}).click();};
  for(const theme of ['light','dark']){
    await page.emulateMedia({colorScheme:theme});
    for(const width of [320,360,390,768,1366,1920]){
      await page.setViewportSize({width,height:width<768?844:900});await page.waitForTimeout(100);
      await expect(page.getByRole('button',{name:'Change colour theme',exact:true})).toBeVisible();
      const geometry=await page.getByLabel('Scrollable complaints',{exact:true}).evaluate(element=>({height:element.clientHeight,content:element.scrollHeight,bottom:element.getBoundingClientRect().bottom,overflow:getComputedStyle(element).overflowY,main:document.querySelector('[role="main"]').scrollHeight,available:document.querySelector('[role="main"]').clientHeight}));
      expect(geometry.overflow).toBe('auto');expect(geometry.height).toBeGreaterThan(150);expect(geometry.content).toBeGreaterThan(geometry.height);expect(geometry.bottom).toBeLessThanOrEqual(page.viewportSize().height);expect(geometry.main).toBeLessThanOrEqual(geometry.available+32);
      expect(await page.getByRole('combobox').count()).toBe(0);
      await capture('queue-'+theme+'-'+width);
    }
  }
  await page.setViewportSize({width:390,height:844});
  await page.getByRole('button',{name:/^Filters/}).click();await expect(page.getByRole('dialog',{name:'Filter complaints',exact:true})).toBeVisible();await capture('queue-filters-mobile');await page.getByRole('button',{name:'Done',exact:true}).click();
  await page.getByLabel('Scrollable complaints',{exact:true}).evaluate(element=>element.scrollTop=250);const position=await page.getByLabel('Scrollable complaints',{exact:true}).evaluate(element=>element.scrollTop);
  await page.locator('section[aria-label="Complaint queue"] a').nth(3).click();await page.getByRole('button',{name:/Back to complaints/}).click();expect(await page.getByLabel('Scrollable complaints',{exact:true}).evaluate(element=>element.scrollTop)).toBeGreaterThanOrEqual(position-5);
  await page.getByRole('button',{name:'Change colour theme',exact:true}).click();await page.getByRole('button',{name:'Light',exact:true}).click();await expect(page.locator('html')).toHaveAttribute('data-color-mode','light');
  await page.getByRole('button',{name:'Change colour theme',exact:true}).click();await page.getByRole('button',{name:'System',exact:true}).click();
  const draftRead=page.waitForResponse(response=>response.url().endsWith('/draft/')&&response.request().method()==='GET');await page.getByRole('button',{name:'Create complaint',exact:true}).click();await draftRead;await page.waitForTimeout(100);await expect(page.getByRole('button',{name:'Save draft',exact:true})).toHaveCount(0);
  if(await page.getByRole('button',{name:'Discard',exact:true}).count()){page.once('dialog',d=>d.accept());const discarded=page.waitForResponse(response=>response.url().endsWith('/draft/')&&response.request().method()==='POST');await page.getByRole('button',{name:'Discard',exact:true}).click();await discarded;await page.waitForTimeout(100);}
  const saved=page.waitForResponse(response=>response.url().endsWith('/draft/')&&response.request().method()==='POST');await page.getByLabel(/^Customer name/).fill('Synthetic responsive draft');await saved;
  await expect(page.getByRole('status').filter({hasText:/^Saved$/})).toBeVisible();
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
  for(const width of [360,390,768,1366]){await page.setViewportSize({width,height:width<768?844:900});await page.getByRole('button',{name:'Change colour theme',exact:true}).scrollIntoViewIfNeeded();await capture('reports-'+width);}
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
