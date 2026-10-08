const fs = require('node:fs');
const path = require('node:path');
const {test, expect} = require('playwright/test');
const root = path.resolve(__dirname, '../..');
const html = fs.readFileSync(path.join(root, 'origination/templates/loan_origination/app.html'), 'utf8')
  .replace(/{% static '([^']+)' %}/g, '/static/$1')
  .replace(/{%[\s\S]*?%}/g, '').replace(/<script[\s\S]*?<\/script>/g, '');
const options = [{value:'draft',label:'Draft'}, {value:'correction_required',label:'Changes requested'},
  {value:'signing_pending',label:'Awaiting signatures'}, {value:'approved',label:'Approved'}];

async function boot(page, width, empty = false, native = false) {
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
  if(native) await page.evaluate(()=>{
    window.__handlers=new Set();window.__native={show(){this.visible=true;},hide(){this.visible=false;},setText(){},enable(){},disable(){},showProgress(){},hideProgress(){},onClick(fn){__handlers.add(fn);},offClick(fn){__handlers.delete(fn);}};
    window.Telegram={WebApp:{initData:'synthetic-only',ready(){},expand(){},onEvent(){},MainButton:__native,BackButton:{show(){},hide(){},onClick(){},offClick(){}}}};
  });
  for (const css of ['core/static/miniapp/base.css','core/static/miniapp/workflow_standard.css','origination/static/miniapp/loan_origination.css']) {
    await page.addStyleTag({path:path.join(root,css)});
  }
  await page.addScriptTag({path:path.join(root,'core/static/miniapp/utils.js')});
  await page.addScriptTag({path:path.join(root,'core/static/miniapp/secure_media_viewer.js')});
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

test('Origination read-only preview shares bounded zoom and does not navigate while panning', async ({page}) => {
  await boot(page,390);
  await page.evaluate(async () => {
    document.getElementById('document-preview-overlay').hidden=false;
    const image=document.getElementById('document-preview-image');
    image.src='data:image/svg+xml,'+encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="800"><rect width="100%" height="100%" fill="white"/><rect width="60" height="60" fill="red"/></svg>');
    await image.decode();
  });
  const stage=page.locator('#document-preview-stage'), initial=await stage.boundingBox();
  for(let i=0;i<16;i++) await page.locator('#preview-zoom-in').click();
  await expect(page.locator('#preview-zoom')).toHaveText('500%');
  await expect(stage).toHaveAttribute('data-zoom','5');
  await stage.dispatchEvent('pointerdown',{pointerId:1,clientX:150,clientY:150});
  await stage.dispatchEvent('pointermove',{pointerId:1,clientX:10000,clientY:10000});
  await stage.dispatchEvent('pointerup',{pointerId:1,clientX:10000,clientY:10000});
  expect((await stage.boundingBox()).height).toBe(initial.height);
  const boxes=await stage.evaluate(node=>({s:node.getBoundingClientRect().toJSON(),i:node.querySelector('img').getBoundingClientRect().toJSON()}));
  expect(boxes.i.left).toBeGreaterThanOrEqual(boxes.s.left-1);
  await page.locator('#preview-close').click();
  await expect(stage).not.toHaveAttribute('data-zoom',/.+/);
});

test('Origination native editor action keeps section validation and input intact',async({page})=>{
  await boot(page,390,false,true);
  await page.route('**/applications/00000000-0000-0000-0000-000000000001/',route=>route.fulfill({json:{ok:true,application:{
    id:'00000000-0000-0000-0000-000000000001',revision:1,status:'draft',reference_number:'ORG-TRAINING-1',product_name:'Training product',
    form_payload:{},form_schema:{sections:[{key:'applicant',label:'Applicant'}],fields:[{key:'applicant_name',label:'Applicant name',type:'text',section:'applicant',required:true}]},
  }}}));
  await page.locator('.application-card').click();
  await expect.poll(()=>page.evaluate(()=>__native.visible&&__handlers.size===1)).toBe(true);
  await page.evaluate(()=>[...__handlers][0]());
  await expect(page.locator('[data-field=applicant_name]')).toHaveAttribute('aria-invalid','true');
  await page.locator('[data-field=applicant_name]').fill('Synthetic Applicant');
  await expect(page.locator('[data-field=applicant_name]')).toHaveValue('Synthetic Applicant');
  await page.evaluate(()=>{document.getElementById('document-preview-overlay').hidden=false;});
  await expect.poll(()=>page.evaluate(()=>__native.visible)).toBe(false);
});
