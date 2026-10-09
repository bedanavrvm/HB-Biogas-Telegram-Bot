const fs = require('node:fs');
const path = require('node:path');
const {test, expect} = require('playwright/test');
const root = path.resolve(__dirname, '../..');
const html = fs.readFileSync(path.join(root, 'origination/templates/loan_origination/app.html'), 'utf8')
  .replace(/{% static '([^']+)' %}/g, '/static/$1')
  .replace(/{%[\s\S]*?%}/g, '').replace(/<script[\s\S]*?<\/script>/g, '');
const options = [{value:'draft',label:'Draft'}, {value:'correction_required',label:'Changes requested'},
  {value:'signing_pending',label:'Awaiting signatures'}, {value:'approved',label:'Approved'}];

async function boot(page, width, empty = false, native = false, locationCatalog = {}) {
  await page.setViewportSize({width,height:850});
  await page.route('http://127.0.0.1:8123/**', route => {
    const url = new URL(route.request().url());
    if (url.pathname === '/') return route.fulfill({contentType:'text/html',body:html});
    if (url.pathname === '/static/miniapp/jawabu-logo.png') return route.fulfill({contentType:'image/png',body:fs.readFileSync(path.join(root,'core/static/miniapp/jawabu-logo.png'))});
    if (url.pathname.endsWith('/products/')) return route.fulfill({json:{ok:true,products:[],branches:[],location_catalog:locationCatalog,capabilities:{can_create:true,user_id:1}}});
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
  await page.addScriptTag({path:path.join(root,'origination/static/miniapp/origination_field_rules.js')});
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

for (const width of [320, 430]) {
  test(`Typed field validation preserves input and mobile layout at ${width}px`, async ({page}, info) => {
    await boot(page, width);
    const id = '00000000-0000-0000-0000-000000000001';
    let writes = 0;
    let app = {id, revision:1, status:'draft', product_name:'Training product', reference_number:'ORG-TRAINING-1',
      form_payload:{nationality:'ke', consent:false, children:0, people:[{row_id:'00000000-0000-0000-0000-000000000002',active:false}]},
      form_schema:{sections:[{key:'applicant',label:'Applicant'}], fields:[
        {key:'email',label:'Email',type:'text',validation:{format:'email'},section_key:'applicant'},
        {key:'children',label:'Children',type:'number',validation:{integer:true,min:0},section_key:'applicant'},
        {key:'nationality',label:'Nationality',type:'choice',required:true,required_by:['support'],section_key:'applicant',options:[{code:'ke',label:'Kenya'},{code:'ug',label:'Uganda',active:false}]},
        {key:'birth_date',label:'Date of birth',type:'date',validation:{no_future:true},section_key:'applicant'},
        {key:'consent',label:'Consent',type:'boolean',section_key:'applicant'},
        {key:'people',label:'Related people',type:'repeating_group',section_key:'applicant',structure:{max_items:2,columns:[{key:'active',label:'Active',type:'boolean'}]}},
      ]}};
    await page.route(`**/applications/${id}/`, route => {
      if (route.request().method() === 'PATCH') {writes++; app = {...app,revision:app.revision+1,form_payload:route.request().postDataJSON().form_payload};}
      return route.fulfill({json:{ok:true,application:app}});
    });
    await page.locator('.application-card').click();
    const email = page.locator('[data-field=email]'), children = page.locator('[data-field=children]');
    await expect(email).toHaveAttribute('type','email');
    await expect(children).toHaveAttribute('inputmode','numeric');
    await expect(page.locator('[data-field=nationality] option')).toHaveCount(2);
    await expect(page.getByText('Required by a supporting document',{exact:true})).toBeVisible();
    await expect(page.locator('[data-field=consent]')).toHaveValue('false');
    await expect(page.locator('[data-repeat-column=active]')).toHaveValue('false');
    await expect(page.locator('[data-field=birth_date]')).toHaveAttribute('max', /\d{4}-\d{2}-\d{2}/);
    await expect(page.locator('[aria-invalid=true]')).toHaveCount(0);
    await email.fill('bad');
    await children.fill('1.5');
    await page.locator('#wizard-next').click();
    await expect(email).toHaveAttribute('aria-invalid','true');
    await expect(children).toHaveAttribute('aria-invalid','true');
    expect(writes).toBe(0);
    await expect(email).toHaveValue('bad');
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({path:info.outputPath(`field-rules-${width}.png`),fullPage:true});
    await email.fill('synthetic@example.test');
    await children.fill('0');
    await page.locator('[data-field=birth_date]').fill('2000-01-01');
    await expect(email).not.toHaveAttribute('aria-invalid','true');
    await expect(children).not.toHaveAttribute('aria-invalid','true');
    await page.locator('#wizard-next').click();
    await expect.poll(() => writes).toBeGreaterThan(0);
    expect(app.form_payload.people[0].active).toBe(false);
    expect(app.form_payload.nationality).toBe('ke');
    expect(app.form_payload.birth_date).toBe('2000-01-01');
    await expect(page.locator('.miniapp-form-errors')).toHaveCount(0);
  });
  test(`Shared Origination values are collected once and local values stay editable at ${width}px`, async ({page}, info) => {
    await boot(page, width);
    const id = '00000000-0000-0000-0000-000000000001';
    const meaning = (scope, source = 'entered') => ({version:2, scope, source, subject:'applicant'});
    const name = {key:'applicant_name', label:'Applicant name', type:'text', section_key:'applicant', value_contract:meaning('application')};
    const note = {key:'notes', label:'Document notes', type:'textarea', value_contract:meaning('document')};
    const interest = {key:'interest', label:'Interest amount', type:'money', source_type:'system', value_contract:meaning('application','calculated')};
    let app = {id, revision:1, status:'draft', reference_number:'ORG-TRAINING-1', product_name:'Training product',
      value_contract_version:2, form_payload:{applicant_name:'Synthetic Applicant', inactive_saved_value:'Retained only on server'},
      form_schema:{sections:[{key:'applicant',label:'Applicant'}],fields:[name]},
      document_packet:{primary_ready:true, documents:[
        {key:'primary',role:'primary',name:'Main',selected:true,applicable:true,complete:true,previewed:true,schema:{fields:[name]}},
        {key:'support',role:'supporting',name:'Synthetic supporting document',selected:true,applicable:true,inclusion_mode:'optional',
          complete:true,previewed:true,schema:{fields:[name,note,interest]},field_payload:{notes:'Saved local note'},
          resolved_values:{applicant_name:'Synthetic Applicant',interest:0}}]},
    };
    const writes = [];
    await page.route(`**/applications/${id}/`, route => {
      if(route.request().method() === 'PATCH') {
        const payload = route.request().postDataJSON();
        writes.push(payload.form_payload);
        app = {...app, revision:app.revision+1, form_payload:{...app.form_payload,...payload.form_payload}};
      }
      return route.fulfill({json:{ok:true,application:app}});
    });
    await page.route(`**/applications/${id}/documents/selection/`, route => route.fulfill({json:{ok:true,application:app}}));
    await page.locator('.application-card').click();
    await expect(page.locator('[data-field="applicant_name"]')).toHaveCount(1);
    await page.locator('[data-field="applicant_name"]').fill('Updated Synthetic Applicant');
    await page.locator('#wizard-next').click();
    await expect(page.getByRole('heading',{name:'Supporting documents',exact:true})).toBeVisible();
    expect(writes.length).toBeGreaterThan(0);
    expect(writes.at(-1).inactive_saved_value).toBeUndefined();
    await page.locator('#wizard-next').click();
    await expect(page.locator('[data-document-field="notes"]')).toBeEditable();
    await expect(page.locator('[data-document-field="applicant_name"]')).toHaveCount(0);
    await expect(page.locator('[data-document-field="interest"]')).toHaveCount(0);
    await expect(page.locator('.laf-field').filter({hasText:'Interest amount'})).toContainText('0');
    await expect(page.locator('[data-document-field="notes"]')).toHaveValue('Saved local note');
    for(const dark of [false,true]) {
      await page.evaluate(value => {
        const root = document.documentElement;
        root.dataset.miniappColorScheme = root.dataset.telegramTheme = value ? 'dark' : 'light';
        const colors = value
          ? {bg_color:'#17171e',secondary_bg_color:'#20202c',text_color:'#ffffff',hint_color:'#a8a8b3',section_separator_color:'#3c4542',button_color:'#6ab2f2',button_text_color:'#172d25'}
          : {bg_color:'#ffffff',secondary_bg_color:'#f3f6f5',text_color:'#172d25',hint_color:'#65756f',section_separator_color:'#d8e2de',button_color:'#126448',button_text_color:'#ffffff'};
        for(const [key,color] of Object.entries(colors)) root.style.setProperty('--tg-theme-' + key.replaceAll('_','-'), color);
      }, dark);
      await expect(page.locator('[data-document-field="notes"]')).toHaveCSS('color', dark ? 'rgb(255, 255, 255)' : 'rgb(23, 45, 37)');
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await page.screenshot({path:info.outputPath(`shared-document-${width}-${dark?'dark':'light'}.png`),fullPage:true});
    }
  });
}

test('Each sub-county uses its own county and preserves the other person', async ({page}) => {
  const catalogue = {counties:[{code:'COUNTY-A',name:'Synthetic A',sub_counties:[{code:'AREA-A',name:'Area A'}]},
    {code:'COUNTY-B',name:'Synthetic B',sub_counties:[{code:'AREA-B',name:'Area B'}]}]};
  await boot(page,320,false,false,catalogue);
  const id = '00000000-0000-0000-0000-000000000001';
  const app = {id,revision:1,status:'draft',form_payload:{applicant_county:'COUNTY-A',applicant_area:'AREA-A',
    guarantor_county:'COUNTY-B',guarantor_area:'AREA-B'},form_schema:{sections:[{key:'people',label:'People'}],fields:[
      {key:'applicant_county',label:'Applicant county',type:'county',section_key:'people'},
      {key:'applicant_area',label:'Applicant area',type:'sub_county',section_key:'people',validation:{parent_field:'applicant_county'}},
      {key:'guarantor_county',label:'Guarantor county',type:'county',section_key:'people'},
      {key:'guarantor_area',label:'Guarantor area',type:'sub_county',section_key:'people',validation:{parent_field:'guarantor_county'}},
    ]}};
  await page.route(`**/applications/${id}/`,route => route.fulfill({json:{ok:true,application:app}}));
  await page.locator('.application-card').click();
  const applicantArea = page.locator('[data-field=applicant_area]');
  const guarantorArea = page.locator('[data-field=guarantor_area]');
  await expect(applicantArea).toHaveValue('AREA-A');
  await expect(guarantorArea).toHaveValue('AREA-B');
  await page.locator('[data-field=applicant_county]').selectOption('COUNTY-B');
  await expect(applicantArea).toHaveValue('');
  await expect(applicantArea.locator('option')).toHaveText(['Choose sub-county','Area B']);
  await expect(guarantorArea).toHaveValue('AREA-B');
});
