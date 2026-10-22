'use strict';
// Started only by the opted-in isolated Django test server. No live fixtures.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');

async function main() {
  let text = ''; for await (const chunk of process.stdin) text += chunk;
  const input = JSON.parse(text), origin = new URL(input.origin);
  assert.ok(['127.0.0.1', 'localhost'].includes(origin.hostname));
  const output = path.resolve('test-results/complaints-browser-operations', input.build);
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1366, height: 900 }, colorScheme: 'light', acceptDownloads: true });
  const page = await context.newPage(); page.setDefaultTimeout(20000);
  page.on('dialog', dialog => dialog.accept());
  const errors = [], requests = [], layouts = []; let captures = 0;
  await context.route('**/*', route => {
    const url = new URL(route.request().url());
    if (url.origin === origin.origin) return route.continue();
    errors.push('External browser request'); return route.abort();
  });
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => requests.push({ url: request.url(), resource: request.resourceType() }));
  const heading = name => page.getByRole('heading', { name, exact: true }).waitFor();
  async function capture(name, keepScroll = false) {
    if (!keepScroll) await page.getByRole('main').evaluate(element => element.scrollTo(0, 0));
    await page.evaluate(() => new Promise(requestAnimationFrame));
    // Capture the settled control colours, not the middle of a theme transition.
    await page.evaluate(async () => { await Promise.all(document.getAnimations().filter(animation => animation instanceof CSSTransition).map(animation => animation.finished.catch(() => {}))); });
    const metrics = await page.evaluate(() => {
      const main = document.querySelector('[role="main"]');
      const detail = document.querySelector('[aria-label="Complaint detail"]');
      const content = document.querySelector('[data-testid="complaints-operations-content"]');
      return { width: innerWidth, page: document.documentElement.scrollWidth,
        main: main?.getBoundingClientRect().width, mainClient: main?.clientWidth,
        mainScroll: main?.scrollWidth, theme: document.documentElement.dataset.colorMode,
        detailRight: detail?.getBoundingClientRect().right, contentRight: content?.getBoundingClientRect().right };
    });
    assert.ok(metrics.page <= metrics.width, name + ': horizontal clipping'); layouts.push({ name, ...metrics });
    assert.ok(metrics.mainScroll <= metrics.mainClient + 1, name + ': workspace clipping');
    if (metrics.width >= 1024 && metrics.detailRight) assert.ok(metrics.contentRight - metrics.detailRight <= 32, name + ': unused detail width');
    await page.screenshot({ path: path.join(output, name + '.png'), fullPage: true }); captures++;
  }
  async function select(label, option) {
    const box = page.getByLabel(label, { exact: true }); await box.fill(option);
    const escaped = option.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    await page.getByRole('option', { name: new RegExp('^' + escaped + '(?:$| - )') }).click();
  }
  async function preferenceChecks() {
    await page.setViewportSize({ width: 1366, height: 900 }); await page.emulateMedia({ colorScheme: 'light' });
    const previousUrl=page.url();
    await page.getByRole('button', { name: 'Settings', exact: true }).click();
    assert.equal(await page.getByRole('grid').count(),0,'Settings must not be stacked above Reports');
    await page.getByRole('button', {name:'Closed',exact:true}).click(); await select('Default branch', 'Synthetic Other Branch');
    const saving = page.waitForResponse(response => response.url().endsWith('/preferences/') && response.request().method() === 'POST');
    await page.getByRole('button', { name: 'Save preferences', exact: true }).click();
    assert.deepEqual((await (await saving).json()).default_filters, { status: 'resolved', branch: 'Synthetic Other Branch' });
    await page.getByText('Preferences saved.', { exact: true }).waitFor(); await capture('settings-desktop');
    await page.emulateMedia({ colorScheme: 'dark' }); await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForFunction(() => document.documentElement.dataset.colorMode === 'dark');
    await capture('settings-dark-mobile');
    await page.goBack(); assert.equal(page.url(),previousUrl);
    await page.goForward(); await heading('Your preferences');
    const restored = page.waitForResponse(response => response.url().endsWith('/cases/') && response.request().method() === 'POST');
    await page.goto(origin.origin + '/staff/app/complaints/');
    const response = await restored;
    assert.equal(response.request().postDataJSON().status, 'resolved', 'Restored request must use the saved status');
    assert.equal((await response.json()).pagination.total, 4, 'Saved branch must include the synthetic cases');
    await heading('4 complaints');
    await page.getByText('Synthetic Other Branch', { exact: true }).waitFor();
    await page.goto(origin.origin + '/staff/app/complaints/?status=pending'); await heading('7 complaints');
    await page.getByRole('button', { name: 'Settings', exact: true }).click();
    await page.getByRole('button', {name:'Open + Reopened',exact:true}).click(); await select('Default branch', 'All branches');
    await page.getByRole('button', { name: 'Save preferences', exact: true }).click();
    await page.getByText('Preferences saved.', { exact: true }).waitFor();
    await page.goto(origin.origin + '/staff/app/complaints/'); await heading('7 complaints');
  }
  try {
    await page.goto(origin.origin + '/staff/app/complaints/');
    await heading('Sign in'); await page.getByLabel(/^Staff username/).fill(input.username);
    await page.getByLabel(/^Password/).fill(input.password);
    await page.getByRole('button', { name: 'Sign in', exact: true }).click();
    await heading('Check your authenticator');
    await page.getByRole('button', { name: 'Use a recovery code', exact: true }).click();
    await page.getByLabel(/^Recovery code/).fill(input.code);
    await page.getByRole('button', { name: 'Verify', exact: true }).click();
    await heading('7 complaints');
    if (input.preferences_only) { await preferenceChecks(); process.stdout.write(JSON.stringify({ passed: true, captures })); return; }
    const documentsBefore = requests.filter(row => row.resource === 'document').length;
    await page.getByRole('link', { name: /^Synthetic Customer 01/ }).click();
    await heading('Synthetic Customer 01');
    assert.equal(await page.getByText('Synthetic older note 000', { exact: true }).count(), 0);
    await page.route('**/cases/*/history/', route => route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: 'Older activity could not be loaded. Try again.' }) }), { times: 1 });
    await page.getByRole('button', { name: 'Load older activity', exact: true }).click();
    await page.getByRole('button', { name: 'Retry older activity', exact: true }).waitFor();
    await capture('history-retry');
    await page.route('**/cases/*/history/', route => route.fulfill({ status: 400, contentType: 'application/json', body: JSON.stringify({ error: 'Refresh the complaint activity and try again.', field_errors: { history_cursor: 'invalid' } }) }), { times: 1 });
    await page.getByRole('button', { name: 'Retry older activity', exact: true }).click();
    await page.getByRole('button', { name: 'Refresh activity', exact: true }).click();
    await page.getByRole('button', { name: 'Load older activity', exact: true }).click();
    await page.getByText('Synthetic older note 011', { exact: true }).waitFor();
    await page.getByRole('button', { name: 'Load older activity', exact: true }).click();
    await page.getByText('Synthetic older note 000', { exact: true }).waitFor();
    assert.equal(await page.getByText(/^Synthetic older note \d{3}$/).count(), 61);
    assert.equal(await page.getByRole('button', { name: 'Load older activity', exact: true }).count(), 0);
    await capture('history-all-loaded');
    await page.getByRole('link', { name: /^Synthetic Customer 00/ }).click();
    await heading('Synthetic Customer 00');
    assert.match(page.url(), /staff\/app\/complaints\/cases\/[a-f\d-]+\//);
    assert.equal(await page.locator('a[href^="tel:"]').count(), 1);
    await page.getByRole('button', {name:'Add resolution comment',exact:true}).click();
    await page.getByLabel(/^Resolution comment/).fill('Synthetic browser follow-up.');
    await page.getByRole('dialog').getByRole('button', { name: 'Add resolution comment', exact: true }).click();
    await page.getByText('Synthetic browser follow-up.', { exact: true }).waitFor();
    await capture('desktop-comment-saved');
    for (const theme of ['light', 'dark']) {
      await page.emulateMedia({ colorScheme: theme });
      await page.waitForFunction(value => document.documentElement.dataset.colorMode === value, theme);
      for (const width of [320, 360, 390, 768, 1280, 1366, 1440, 1920]) {
        await page.setViewportSize({ width, height: width < 768 ? 844 : 900 }); await capture(`queue-${theme}-${width}`);
      }
    }
    await page.setViewportSize({ width: 1366, height: 900 }); await page.emulateMedia({ colorScheme: 'light' });
    await page.getByRole('tab', {name:'Complaints',exact:true}).click();
    await page.getByLabel('Search name, ID, phone or branch').fill('999999999999');
    await page.waitForTimeout(450); await heading('7 complaints');
    assert.ok(!page.url().includes('999999999999'));
    assert.ok(!requests.some(row => new URL(row.url).search.includes('999999999999')));
    await page.getByRole('button', { name: 'Create complaint', exact: true }).click(); await heading('Create complaint');
    const formFont=await page.getByRole('dialog').evaluate(element=>getComputedStyle(element).fontFamily);
    assert.ok(!/Times New Roman|^serif$/i.test(formFont), 'Dialog must use the ADS body typography');
    fs.writeFileSync(path.join(output,'dialog-typography.json'),JSON.stringify(await page.getByRole('dialog').evaluate(element=>
      [element,...element.querySelectorAll('h2,label,input,button')].slice(0,12).map(item=>({tag:item.tagName,font:getComputedStyle(item).fontFamily,size:getComputedStyle(item).fontSize}))),null,2));
    await page.getByLabel(/^Customer name/).fill('Synthetic retained draft');
    await page.getByRole('button', { name: 'Submit complaint', exact: true }).click();
    assert.equal(await page.getByLabel(/^Customer name/).inputValue(), 'Synthetic retained draft');
    await capture('create-field-errors');
    await page.setViewportSize({width:390,height:844}); await capture('create-errors-mobile');
    await page.setViewportSize({width:1366,height:900});
    await page.getByRole('button', { name: 'Save draft', exact: true }).click();
    await page.getByText('Draft saved.', { exact: true }).waitFor();
    await page.getByRole('dialog').getByRole('button', { name: 'Close', exact: true }).click();
    await page.getByRole('button', { name: 'Create complaint', exact: true }).click();
    await page.getByRole('button', { name: 'Restore', exact: true }).click();
    assert.equal(await page.getByLabel(/^Customer name/).inputValue(), 'Synthetic retained draft');
    await page.keyboard.press('Escape');
    await page.getByRole('dialog').waitFor({state:'detached'});
    assert.equal(await page.evaluate(()=>document.activeElement?.textContent), 'Create complaint');

    await page.getByRole('tab', {name:'Reports',exact:true}).click();
    await page.getByRole('grid', {name:'Complaint results'}).waitFor();
    assert.equal(await page.getByRole('columnheader').count(),7);
    assert.equal(await page.getByLabel('From',{exact:true}).count(),0);
    await select('Date range','All dates'); await heading('11 complaints');
    const metricFont=await page.getByRole('button',{name:'View closed complaints',exact:true}).getByText('4',{exact:true}).evaluate(element=>Number.parseFloat(getComputedStyle(element).fontSize));
    assert.ok(metricFont>=24,'KPI value must retain metric hierarchy rather than body-size text');
    const closedRows=page.waitForResponse(response=>response.url().endsWith('/reports/')&&response.request().postDataJSON()?.selection?.status==='resolved');
    await page.getByRole('button',{name:'View closed complaints',exact:true}).press('Enter');
    assert.equal((await(await closedRows).json()).table.count,4);
    await page.getByRole('button',{name:'Clear chart selection',exact:true}).click();await heading('11 complaints');
    await select('Count by','Closed date');await heading('4 complaints');
    assert.equal(await page.getByRole('button',{name:'View still open complaints',exact:true}).isDisabled(),true);
    await select('Count by','Reported date');await heading('11 complaints');
    await select('Date range','Custom dates');
    await page.getByLabel('From',{exact:true}).fill('not-a-date');await page.getByLabel('From',{exact:true}).press('Tab');
    await page.getByText('Use a date such as 22 Oct 2026.',{exact:true}).waitFor();
    const customRows=page.waitForResponse(response=>response.url().endsWith('/reports/')&&response.request().postDataJSON()?.date_from===input.month_start);
    await page.getByLabel('From',{exact:true}).fill(input.month_start);await page.getByLabel('From',{exact:true}).press('Tab');await customRows;
    await select('Date range','All dates');await heading('11 complaints');
    async function reportCaptures(view) {
      for (const theme of ['light','dark']) {
        await page.emulateMedia({colorScheme:theme});
        await page.waitForFunction(value=>document.documentElement.dataset.colorMode===value,theme);
        for (const width of [320,360,390,768,1366,1440,1920]) {
          await page.setViewportSize({width,height:width<768?844:900}); await capture('reports-'+view+'-'+theme+'-'+width);
        }
      }
      await page.setViewportSize({width:1366,height:900});await page.emulateMedia({colorScheme:'light'});
      for (const width of [390,1366]) {
        await page.setViewportSize({width,height:width<768?844:900});
        for (const chart of await page.locator('svg[aria-label$="Complaints."],svg[aria-label$="Hours."]').all()) {
          const title=await chart.getAttribute('aria-label');await chart.scrollIntoViewIfNeeded();
          await capture('chart-'+view+'-'+width+'-'+title.replace(/[^a-zA-Z]+/g,'-'),true);
        }
        await page.getByRole('grid',{name:'Complaint results'}).scrollIntoViewIfNeeded();
        await capture('table-'+view+'-'+width,true);
      }
      await page.setViewportSize({width:1366,height:900});
    }
    await reportCaptures('overview');
    const sorted=page.waitForResponse(response=>response.url().endsWith('/reports/')&&response.request().postDataJSON()?.sort==='customer_name');
    await page.getByRole('columnheader',{name:/^Customer/}).click(); await sorted;
    await page.getByRole('grid').getByRole('row').nth(1).getByRole('gridcell').first().press('Enter');
    await page.getByRole('region',{name:'Complaint detail'}).waitFor();
    await page.getByRole('tab',{name:'Reports',exact:true}).click(); await page.getByRole('grid').waitFor();
    assert.equal(await page.locator('svg[aria-label^="Complaint types."]').count(), 0, 'Do not draw a single-category chart');
    await page.locator('svg[aria-label^="Reported vs resolved."]').getByRole('button').first().press('Enter');
    await page.waitForFunction(()=>document.activeElement?.getAttribute('aria-label')==='Filtered report complaints');
    await page.getByRole('button',{name:'Clear chart selection',exact:true}).click();
    await page.getByRole('tab',{name:'Turnaround',exact:true}).click(); await heading('Resolution time');
    await select('Group by','Day');
    await page.locator('svg[aria-label^="Resolution time."]').getByRole('button',{name:/192 hours/}).waitFor();
    assert.equal(await page.locator('svg[aria-label^="Resolution time."]').count(),1);
    await page.locator('svg[aria-label^="Resolution time."]').getByRole('button',{name:/Median resolution: 0 hours/}).waitFor();
    const late=page.waitForResponse(response=>response.url().endsWith('/reports/')&&response.request().postDataJSON()?.selection?.metric==='late');
    await page.locator('svg[aria-label^="Resolution targets."]').getByRole('button',{name:/^Late:/}).press('Enter');
    assert.equal((await(await late).json()).table.count,1); await reportCaptures('turnaround');
    await page.getByRole('button',{name:'Export report',exact:true}).click();
    const downloading=page.waitForEvent('download');
    await page.getByRole('button',{name:'Download filtered Excel',exact:true}).click();
    const file=await downloading;assert.match(file.suggestedFilename(),/^.{2,}\.xlsx$/);
    await page.getByRole('tab',{name:'Open follow-up',exact:true}).click();await heading('Open-case age');
    assert.equal(await page.locator('svg[aria-label^="Open-case age."]').count(),1);
    await reportCaptures('follow-up');
    await page.setViewportSize({width:390,height:844});
    await page.evaluate(()=>{document.documentElement.style.fontSize='200%';});await capture('reports-large-text');
    await page.evaluate(()=>{document.documentElement.style.fontSize='';});
    await page.setViewportSize({width:1366,height:900});
    await page.route('**/operations/v1/groups/*/reports/',route=>route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:'Synthetic unavailable report'})}),{times:1});
    await select('Group by','Month');await heading('Report could not be loaded');await capture('reports-error');
    await page.getByRole('button',{name:'Retry report',exact:true}).click();await heading('Open-case age');
    assert.equal(requests.filter(row=>row.resource==='document').length,documentsBefore);
    await page.reload();await heading('Open-case age');
    // Synthetic paging metadata isolates initial grid-sort behavior; actual
    // canonical sorting/cohort facts are checked separately above and server-side.
    await page.route('**/operations/v1/groups/*/reports/',async route=>{
      const response=await route.fetch();const body=await response.json();
      body.table.count=100;body.table.page=route.request().postDataJSON().page;
      await route.fulfill({response,json:body});
    });
    await page.goto(origin.origin+'/staff/app/complaints/reports/?range=all&report_page=2');
    await page.getByText('Page 2 of 2',{exact:true}).waitFor();
    await page.waitForTimeout(250);
    assert.equal(new URL(page.url()).searchParams.get('report_page'),'2','Initial grid sort must not reset a restored page');
    await page.unroute('**/operations/v1/groups/*/reports/');
    await preferenceChecks();
    assert.deepEqual(await page.evaluate(() => ({ local: localStorage.length, session: sessionStorage.length })), { local: 0, session: 0 });
    assert.deepEqual(errors, []);
    fs.writeFileSync(path.join(output, 'layout.json'), JSON.stringify(layouts, null, 2));
    process.stdout.write(JSON.stringify({ passed: true, captures }));
  } catch(error) { await page.screenshot({path:path.join(output,'failure.png'),fullPage:true});fs.writeFileSync(path.join(output,'failure.txt'),(await page.locator('body').innerText()).slice(0,20000));throw error; } finally { await browser.close(); }
}
main().catch(error => { console.error(error.stack); process.exitCode = 1; });
