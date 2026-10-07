const fs = require('node:fs');
const path = require('node:path');
const {test, expect} = require('playwright/test');
const root = path.resolve(__dirname, '../..');
const html = fs.readFileSync(path.join(root, 'origination/templates/loan_origination/app.html'), 'utf8')
  .replace(/{% static '([^']+)' %}/g, '/static/$1')
  .replace(/{%[\s\S]*?%}/g, '').replace(/<script[\s\S]*?<\/script>/g, '');
const options = [{value:'draft',label:'Draft'}, {value:'correction_required',label:'Changes requested'},
  {value:'signing_pending',label:'Awaiting signatures'}, {value:'approved',label:'Approved'}];

async function boot(page, width, empty = false) {
  await page.setViewportSize({width,height:850});
  await page.route('http://127.0.0.1:8123/**', route => {
    const url = new URL(route.request().url());
    if (url.pathname === '/') return route.fulfill({contentType:'text/html',body:html});
    if (url.pathname === '/static/miniapp/jawabu-logo.png') return route.fulfill({contentType:'image/png',body:fs.readFileSync(path.join(root,'core/static/miniapp/jawabu-logo.png'))});
    if (url.pathname.endsWith('/products/')) return route.fulfill({json:{ok:true,products:[],branches:[],capabilities:{can_create:true,user_id:1}}});
    if (url.pathname.endsWith('/applications/')) {
      const filtered = url.searchParams.has('status') || url.searchParams.has('q');
      const app = {id:'00000000-0000-0000-0000-000000000001',applicant_summary:{name:'Synthetic applicant with a long name'},
        product_name:'Training product',branch:'Embu',reference_number:'ORG-TRAINING-1',status:'correction_required',
        status_label:'Changes requested',next_action:'Make corrections',review_alert:'Please check the repayment details.'};
      const apps = empty || filtered ? [] : [app];
      return route.fulfill({json:{ok:true,applications:apps,tab_counts:{action:1,applications:2},
        status_options:options,applications_label:'My applications',capabilities:{can_create:true,user_id:1},
        pagination:{page:1,pages:1,total:apps.length}}});
    }
    return route.abort();
  });
  await page.goto('http://127.0.0.1:8123/');
  for (const css of ['core/static/miniapp/base.css','core/static/miniapp/workflow_standard.css','origination/static/miniapp/loan_origination.css']) {
    await page.addStyleTag({path:path.join(root,css)});
  }
  await page.addScriptTag({path:path.join(root,'origination/static/miniapp/loan_origination.js')});
  await expect(page.locator('.queue-tab')).toHaveCount(2);
}

for (const width of [320,360,390,430,1280]) {
  test(`Origination two tabs and readable filters fit ${width}px`, async ({page}, info) => {
    await boot(page,width);
    await expect(page.getByRole('button',{name:'Needs your action 1'})).toHaveAttribute('aria-pressed','true');
    await expect(page.locator('.application-card')).toHaveCount(1);
    await expect(page.locator('.reviewer-alerts')).toHaveCount(0);
    await expect(page.locator('.application-card')).toContainText('Make corrections');
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    await page.screenshot({path:info.outputPath(`queues-${width}.png`)});
    await page.getByRole('button',{name:'Filters',exact:true}).click();
    await page.getByRole('combobox',{name:'Status',exact:true}).selectOption('correction_required');
    await page.screenshot({path:info.outputPath(`filters-${width}.png`)});
    await page.getByRole('button',{name:'Apply filters'}).click();
    await expect(page.getByText('No matching applications', {exact:true})).toBeVisible();
    await expect(page.getByRole('button',{name:'Changes requested',exact:true})).toBeVisible();
    await page.getByRole('button',{name:'My applications 2'}).click();
    await expect(page.getByRole('button',{name:'Changes requested',exact:true})).toBeVisible();
    await page.getByRole('button',{name:'Clear filters'}).click();
    await expect(page.locator('.application-card')).toHaveCount(1);
  });
}
test('Caught up state links directly to applications', async ({page}) => {
  await boot(page,390,true);
  await expect(page.getByText('You’re caught up')).toBeVisible();
  await page.getByRole('button',{name:'My applications',exact:true}).click();
  await expect(page.getByRole('button',{name:'My applications 2'})).toHaveAttribute('aria-pressed','true');
});
