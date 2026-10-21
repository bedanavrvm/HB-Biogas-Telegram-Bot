const fs = require('node:fs');
const path = require('node:path');
const {execFileSync} = require('node:child_process');
const {test, expect} = require('playwright/test');
const root = path.resolve(__dirname, '../..');
const html = fs.readFileSync(path.join(root, 'origination/templates/loan_origination/app.html'), 'utf8')
  .replace(/{% static '([^']+)' %}/g, '/static/$1')
  .replace(/{%[\s\S]*?%}/g, '').replace(/<script[\s\S]*?<\/script>/g, '').replace(/<link[^>]+>/g,'');
const options = [{value:'draft',label:'Draft'}, {value:'correction_required',label:'Changes requested'},
  {value:'signing_pending',label:'Awaiting signatures'}, {value:'approved',label:'Approved'}];

async function boot(page, width, empty = false, native = false, locationCatalog = {}, filterOptions = null) {
  await page.setViewportSize({width,height:850});
  await page.route('http://127.0.0.1:8123/**', route => {
    const url = new URL(route.request().url());
    if (url.pathname === '/') return route.fulfill({contentType:'text/html',body:html});
    if (url.pathname === '/static/miniapp/jawabu-logo.png') return route.fulfill({contentType:'image/png',body:fs.readFileSync(path.join(root,'core/static/miniapp/jawabu-logo.png'))});
    if (url.pathname.endsWith('/products/')) return route.fulfill({json:{ok:true,products:[],branches:[],location_catalog:locationCatalog,capabilities:{can_create:true,user_id:1}}});
    if (url.pathname.endsWith('/applications/')) {
      const filtered = url.searchParams.has('status') || url.searchParams.has('q');
      const app = {id:'00000000-0000-0000-0000-000000000001',applicant_summary:{name:'Synthetic applicant with a long name',national_id:'12345678',phone:'0712345678'},
        product_name:'Training product',branch:'Embu',reference_number:'ORG-TRAINING-1',status:'correction_required',
        status_label:'Changes requested',next_action:'Make corrections',review_alert:'Please check the repayment details.'};
      const apps = empty || filtered ? [] : [app];
      return route.fulfill({json:{ok:true,applications:apps,tab_counts:{action:1,applications:2},
        status_options:options,...(filterOptions?{filter_options:filterOptions}:{}),applications_label:'My applications',capabilities:{can_create:true,user_id:1},
        pagination:{page:1,pages:1,total:apps.length}}});
    }
    return route.abort();
  });
  await page.goto('http://127.0.0.1:8123/');
  if(native) await page.evaluate(()=>{
    window.__handlers=new Set();window.__native={show(){this.visible=true;},hide(){this.visible=false;},setText(){},enable(){},disable(){},showProgress(){},hideProgress(){},onClick(fn){__handlers.add(fn);},offClick(fn){__handlers.delete(fn);}};
    window.Telegram={WebApp:{initData:'synthetic-only',ready(){},expand(){},onEvent(){},MainButton:__native,BackButton:{show(){},hide(){},onClick(){},offClick(){}}}};
  });
  for (const css of ['core/static/miniapp/base.css','core/static/miniapp/workflow_standard.css','origination/static/miniapp/loan_origination.css','origination/static/miniapp/origination_compact.css']) {
    await page.addStyleTag({content:fs.readFileSync(path.join(root,css),'utf8').replace(/^@import[^\r\n]*;\s*$/gm,'')});
  }
  await page.addScriptTag({path:path.join(root,'core/static/miniapp/utils.js')});
  await page.addScriptTag({path:path.join(root,'core/static/miniapp/secure_media_viewer.js')});
  await page.addScriptTag({path:path.join(root,'origination/static/miniapp/origination_field_rules.js')});
  await page.addScriptTag({path:path.join(root,'origination/static/miniapp/loan_origination.js')});
  await expect(page.locator('.queue-tab')).toHaveCount(2);
}

test('Origination opens its own recovery panel without leaving application filters', async({page},info)=>{
  await boot(page,390);
  await page.addStyleTag({path:path.join(root,'core/static/miniapp/miniapp_recovery.css')});
  await page.addScriptTag({path:path.join(root,'core/static/miniapp/miniapp_recovery.js')});
  await page.route('**/api/origination/api/settings/recovery/**',route=>route.fulfill({json:{ok:true,data:{items:[],pagination:{page:1,pages:1,total:0}}}}));
  await expect(page.locator('.application-card')).toHaveCount(1);
  await page.evaluate(()=>{
    window.searchBeforeSettings=document.querySelector('#origination-search input');
    window.searchBeforeSettings.value='Keep this search';
  });
  await page.getByRole('button',{name:'Settings',exact:true}).click();
  await expect(page.locator('#origination-settings')).toBeVisible();
  await expect(page.locator('#origination-recovery')).toContainText('No updates need attention.');
  await page.screenshot({path:info.outputPath('origination-settings-390.png'),fullPage:true});
  await page.getByRole('button',{name:'Close settings',exact:true}).click();
  await expect(page.locator('#origination-settings')).toBeHidden();
  await expect(page.locator('#origination-search input')).toHaveValue('Keep this search');
  expect(await page.evaluate(()=>window.searchBeforeSettings===document.querySelector('#origination-search input'))).toBe(true);
});

function placedFormFixture(supportingDetails = false) {
  const script = `
import os, json
os.environ['DJANGO_SETTINGS_MODULE']='config.settings'
import django
django.setup()
from origination.tests_form_projection import application, layout, N
from origination.tests_value_contracts import field, schema
from origination.services.origination_value_contracts import application_input_schema, application_document_schema
main=schema(field('applicant_full_name', required=True), field('applicant_phone', type='phone', required=True), field('purpose'), field('unused', required=True))
main['fields'][2].update(section_key='request',label='Loan purpose')
main['sections'] += [{'key':'request','label':'Request'}, {'key':'unused_section','label':'Unused section'}]
support=N(document_key='support',selected=True,applicable=True,document_role='supporting',signer_rules_snapshot=[],
    schema_snapshot=schema(field('private_note',scope='document')),template_snapshot={'configuration':layout('private_note')})
if ${supportingDetails ? 'True' : 'False'}:
    details=[field('private_note',scope='document',required=True),field('visit_phone',scope='document',type='phone'),
             field('visit_outcome',scope='document',type='choice'),field('unused_local',scope='document',required=True),
             field('visit_location')]
    for item in details: item['section_key']='visit_details'
    details[1]['section_key']='visit_contact'
    details[2]['options']=[{'code':'confirmed','label':'Confirmed'},{'code':'pending','label':'Pending'}]
    support.schema_snapshot=schema(*details)
    support.schema_snapshot['sections']=[{'key':'visit_details','label':'Visit details'}, {'key':'visit_contact','label':'Visit contact'}]
    support.template_snapshot={'configuration':layout('private_note','visit_phone','visit_outcome','visit_location')}
app=application(main, layout('purpose'),support)
print(json.dumps({'form_schema':application_input_schema(app),'document_schema':application_document_schema(app,support)}))
`;
  return JSON.parse(execFileSync(path.join(root,'.venv',process.platform==='win32'?'Scripts/python.exe':'bin/python'), ['-c',script], {
    cwd:root,encoding:'utf8',env:{...process.env,DATABASE_URL:'sqlite:///:memory:',
      DJANGO_SECRET_KEY:'synthetic-projection-browser-only-'.padEnd(64,'x'),ORIGINATION_LAF_BOOTSTRAP_ENABLED:'false'},
  }));
}

async function bootDocumentManager(page, {dark=false, alternative=false, status='draft'}={}) {
  await boot(page,360);
  if(dark) await page.evaluate(()=>{
    document.documentElement.dataset.telegramTheme='dark';
    document.documentElement.dataset.miniappColorScheme='dark';
    for(const [key,value] of Object.entries({'bg-color':'#17201e','secondary-bg-color':'#111816','text-color':'#f4f7f5','hint-color':'#a7b5af'}))
      document.documentElement.style.setProperty(`--tg-theme-${key}`,value);
  });
  const id='00000000-0000-0000-0000-000000000001';
  const app={id,officer_id:1,revision:1,status,reference_number:'ORG-SYNTHETIC-1',product_name:'Training loan',branch:'Training',
    form_schema:{sections:[{key:'applicant',label:'Applicant'}],fields:[{key:'applicant_full_name',type:'text',label:'Applicant name',section_key:'applicant'}]},
    form_payload:{applicant_full_name:'Synthetic Applicant'},product_terms:{},
    document_packet:{documents:[{key:'primary',role:'primary',name:'Application form',template_id:'main-1',template_version:3,selected:true,applicable:true},
      {key:'guarantee',role:'supporting',name:'Guarantee',template_id:'support-1',template_version:2,selected:true,applicable:true,inclusion_mode:'optional',schema:{fields:[]}}]}};
  const choices={ok:true,revision:1,primary_template_id:'main-1',catalogue_revision:'synthetic-catalogue',
    main_lafs:[{id:'main-1',name:'Application form',version:3,selected:true},...(alternative?[{id:'main-2',name:'Alternative application form',version:4,selected:false}]:[])],
    supporting_documents:[{id:'support-1',key:'guarantee',name:'Guarantee',version:2,selected:true,available:true,compatible_main_ids:['main-1','main-2']},
      {id:'support-2',key:'visit',name:'Newly published home visit form',version:1,selected:false,available:true,compatible_main_ids:['main-1','main-2']}]};
  await page.route(`**/applications/${id}/`,route=>route.fulfill({json:{ok:true,application:app}}));
  await page.route(`**/applications/${id}/documents/choices/`,route=>route.fulfill({json:choices}));
  await page.locator('.application-card').click();
  return {app,choices,id};
}

for(const dark of [false,true]) test(`Manage documents works with one Main LAF and fits a phone ${dark?'dark':'light'}`,async({page},info)=>{
  const {app,id}=await bootDocumentManager(page,{dark});
  let body;
  await page.route(`**/applications/${id}/documents/selection/`,route=>{
    body=route.request().postDataJSON();
    return route.fulfill({json:{ok:true,application:{...app,revision:2}}});
  });
  await page.getByRole('button',{name:'Manage documents',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Manage documents',exact:true})).toBeVisible();
  await expect(page.locator('#origination-documents-form input[type=radio]')).toHaveCount(1);
  await page.locator('[name=supporting_template_ids][value=support-1]').uncheck();
  await page.locator('[name=supporting_template_ids][value=support-2]').check();
  await expect(page.getByText('Newly published home visit form',{exact:true})).toBeVisible();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.screenshot({path:info.outputPath(`manage-documents-360-${dark?'dark':'light'}.png`),fullPage:true});
  await page.getByRole('button',{name:'Save changes',exact:true}).click();
  await expect(page.locator('#origination-sheet-overlay')).toBeHidden();
  expect(body.supporting_template_ids).toEqual(['support-2']);
  expect(body.revision).toBe(1);
  expect(body).not.toHaveProperty('selected_keys');
  await expect(page.locator('[data-field=applicant_full_name]')).toHaveValue('Synthetic Applicant');
});

test('Main LAF change cancels once before sending and starts a blank replacement',async({page},info)=>{
  const {app,id}=await bootDocumentManager(page,{alternative:true});
  let requests=0,body;
  await page.route(`**/applications/${id}/restart/`,route=>{
    requests++;body=route.request().postDataJSON();
    return route.fulfill({json:{ok:true,application:{...app,id:'00000000-0000-0000-0000-000000000099',reference_number:'ORG-SYNTHETIC-NEW',form_payload:{}}}});
  });
  await page.getByRole('button',{name:'Manage documents',exact:true}).click();
  await page.locator('[name=primary_template_id][value=main-2]').check();
  page.once('dialog',async dialog=>{
    expect(dialog.message()).toContain('blank application');await dialog.dismiss();
  });
  await page.getByRole('button',{name:'Save changes',exact:true}).click();
  expect(requests).toBe(0);
  await expect(page.locator('[name=primary_template_id][value=main-2]')).toBeChecked();
  page.once('dialog',dialog=>dialog.accept());
  await page.getByRole('button',{name:'Save changes',exact:true}).click();
  await expect(page.locator('#origination-sheet-overlay')).toBeHidden();
  expect(requests).toBe(1);expect(body.primary_template_id).toBe('main-2');
  await expect(page.locator('[data-field=applicant_full_name]')).toHaveValue('');
  await page.screenshot({path:info.outputPath('main-laf-blank-replacement-360.png'),fullPage:true});
});

test('failed document selection keeps choices and retries the identical request',async({page},info)=>{
  const {app,id}=await bootDocumentManager(page);
  const bodies=[];
  await page.route(`**/applications/${id}/documents/selection/`,route=>{
    bodies.push(route.request().postDataJSON());
    return bodies.length===1?route.fulfill({status:503,json:{ok:false,error:'Could not connect. Your choices are kept; try again.'}})
      :route.fulfill({json:{ok:true,application:{...app,revision:2}}});
  });
  await page.getByRole('button',{name:'Manage documents',exact:true}).click();
  await page.locator('[name=supporting_template_ids][value=support-2]').check();
  await page.getByRole('button',{name:'Save changes',exact:true}).click();
  await expect(page.locator('#origination-toast')).toBeVisible();
  await expect(page.locator('[name=supporting_template_ids][value=support-2]')).toBeChecked();
  await page.screenshot({path:info.outputPath('manage-documents-failure-360.png'),fullPage:true});
  await page.getByRole('button',{name:'Save changes',exact:true}).click();
  await expect(page.locator('#origination-sheet-overlay')).toBeHidden();
  expect(bodies[1]).toEqual(bodies[0]);
});

test('supporting forms use placed fields and sections and restore saved answers after reselecting',async({page},info)=>{
  const {app,choices,id}=await bootDocumentManager(page);
  const initial=placedFormFixture(), selected=placedFormFixture(true);
  Object.assign(app,{value_contract_version:2,form_projection_version:1,form_schema:initial.form_schema});
  const support={key:'visit',name:'Home visit',role:'supporting',applicable:true,selected:false,
    schema:selected.document_schema,field_payload:{},template_id:'support-2',template_version:1};
  app.document_packet.documents.push(support);
  choices.supporting_documents[1].name='Home visit';
  choices.supporting_documents[0].selected=false;
  app.document_packet.documents[1].selected=false;
  await page.locator('#origination-back').click();
  await page.locator('.application-card').click();
  let fieldWrites=[];
  await page.route(`**/applications/${id}/documents/selection/`,route=>{
    support.selected=route.request().postDataJSON().supporting_template_ids.includes('support-2');
    choices.supporting_documents[1].selected=support.selected;
    choices.revision=++app.revision;
    app.form_schema=support.selected?selected.form_schema:initial.form_schema;
    return route.fulfill({json:{ok:true,application:app}});
  });
  await page.route(`**/applications/${id}/documents/visit/fields/`,route=>{
    const body=route.request().postDataJSON();fieldWrites.push(body.payload);
    support.field_payload=body.payload;choices.revision=++app.revision;
    return route.fulfill({json:{ok:true,application:app}});
  });
  const chooseVisit=async()=>{
    await page.getByRole('button',{name:'Choose application section'}).click();
    await page.locator('[data-section-index]').filter({hasText:'Home visit'}).click();
  };
  await page.getByRole('button',{name:'Manage documents',exact:true}).click();
  await page.locator('[name=supporting_template_ids][value=support-2]').check();
  await page.getByRole('button',{name:'Save changes',exact:true}).click();
  await expect(page.locator('#origination-sheet-overlay')).toBeHidden();
  await chooseVisit();
  await expect(page.getByRole('heading',{name:'Visit details',exact:true})).toBeVisible();
  await expect(page.getByRole('heading',{name:'Visit contact',exact:true})).toBeVisible();
  await expect(page.locator('[data-document-field=unused_local]')).toHaveCount(0);
  await expect(page.locator('[data-document-field=visit_phone]')).toHaveAttribute('type','tel');
  expect((await page.locator('[data-support-preview]').boundingBox()).width).toBe(44);
  await page.locator('[data-document-field=private_note]').fill('Saved visit note');
  await page.locator('[data-document-field=visit_phone]').fill('0700000000');
  await page.locator('[data-document-field=visit_outcome]').selectOption('confirmed');
  await page.screenshot({path:info.outputPath('supporting-form-360.png'),fullPage:true});
  await page.getByRole('button',{name:'Choose application section'}).click();
  await page.locator('[data-section-index]').filter({hasText:'Review'}).click();
  await expect.poll(()=>fieldWrites.at(-1)).toEqual({private_note:'Saved visit note',visit_phone:'0700000000',visit_outcome:'confirmed'});
  await page.getByRole('button',{name:'Manage documents',exact:true}).click();
  await page.locator('[name=supporting_template_ids][value=support-2]').uncheck();
  await page.getByRole('button',{name:'Save changes',exact:true}).click();
  await expect(page.locator('#origination-sheet-overlay')).toBeHidden();
  await page.getByRole('button',{name:'Choose application section'}).click();
  await expect(page.locator('[data-section-index]').filter({hasText:'Home visit'})).toHaveCount(0);
  await page.getByRole('button',{name:'Close',exact:true}).click();
  await page.getByRole('button',{name:'Manage documents',exact:true}).click();
  await page.locator('[name=supporting_template_ids][value=support-2]').check();
  await page.getByRole('button',{name:'Save changes',exact:true}).click();
  await expect(page.locator('#origination-sheet-overlay')).toBeHidden();
  await chooseVisit();
  await expect(page.locator('[data-document-field=private_note]')).toHaveValue('Saved visit note');
});

test('Cancel makes no document writes and approved applications have no management action',async({page})=>{
  const {id}=await bootDocumentManager(page);
  let writes=0;
  await page.route(`**/applications/${id}/documents/selection/`,route=>{writes++;return route.abort();});
  await page.getByRole('button',{name:'Manage documents',exact:true}).click();
  await page.locator('[name=supporting_template_ids][value=support-2]').check();
  await page.getByRole('button',{name:'Cancel',exact:true}).click();
  expect(writes).toBe(0);
  await page.reload();
  await bootDocumentManager(page,{status:'approved'});
  await expect(page.getByRole('button',{name:'Manage documents',exact:true})).toHaveCount(0);
});

for(const width of [320,430,1280]) for(const dark of [false,true]) {
  test(`Placement-driven form stays compact at ${width}px ${dark?'dark':'light'}`,async({page},info)=>{
    await boot(page,width);
    if(dark) await page.evaluate(()=>{
      document.documentElement.dataset.telegramTheme='dark';
      document.documentElement.dataset.miniappColorScheme='dark';
      for(const [key,value] of Object.entries({'bg-color':'#17201e','secondary-bg-color':'#111816','text-color':'#f4f7f5','hint-color':'#a7b5af'}))
        document.documentElement.style.setProperty(`--tg-theme-${key}`,value);
    });
    const fixture=placedFormFixture(), id='00000000-0000-0000-0000-000000000001';
    let lastPayload;
    let app={id,officer_id:1,revision:1,status:'draft',product_name:'Training product',reference_number:'ORG-TRAINING-1',
      branch:'Training',form_projection_version:1,value_contract_version:2,form_schema:fixture.form_schema,
      // Simulate an older client retaining an inactive answer; it must not be posted.
      form_payload:{applicant_full_name:'Synthetic Applicant',applicant_phone:'0700000000',unused:'Recoverable'},
      product_terms:{},document_packet:{documents:[{key:'support',name:'Visit notes',role:'supporting',selected:true,applicable:true,
        officer_selectable:true,inclusion_mode:'optional',schema:fixture.document_schema,field_payload:{}}]}};
    await page.route(`**/applications/${id}/documents/selection/`,route=>route.fulfill({json:{ok:true,application:app}}));
    await page.route(`**/applications/${id}/`,route=>{
      if(route.request().method()==='PATCH') {
        lastPayload=route.request().postDataJSON().form_payload;
        app={...app,revision:app.revision+1,form_payload:{...app.form_payload,...lastPayload}};
      }
      return route.fulfill({json:{ok:true,application:app}});
    });
    await page.locator('.application-card').click();
    await expect(page.locator('[data-field=unused]')).toHaveCount(0);
    await expect(page.getByText('Unused section',{exact:true})).toHaveCount(0);
    await expect(page.locator('[data-field=applicant_full_name]')).toHaveCount(1);
    await expect(page.locator('[data-field=applicant_phone]')).toHaveCount(1);
    await expect(page.getByRole('heading',{name:'Applicant',exact:true})).toBeVisible();
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    await page.screenshot({path:info.outputPath(`placed-form-${width}-${dark?'dark':'light'}.png`),fullPage:true});
    await page.locator('[data-field=applicant_full_name]').fill('Synthetic Applicant Updated');
    await page.locator('#section-next').click();
    await expect(page.locator('[data-field=purpose]')).toBeVisible();
    expect(lastPayload).not.toHaveProperty('unused');
    await page.locator('[data-field=purpose]').fill('Synthetic request');
    await page.locator('#section-next').click();
    await expect(page.getByRole('heading',{name:'Supporting documents',exact:true})).toHaveCount(0);
    await expect(page.locator('[data-document-field=private_note]')).toBeVisible();
    await page.screenshot({path:info.outputPath(`placed-support-${width}-${dark?'dark':'light'}.png`),fullPage:true});
  });
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
for (const width of [320,390,430,1280]) for (const dark of [false,true]) {
  test(`Origination compact cards show usable identity at ${width}px ${dark?'dark':'light'}`, async ({page},info) => {
    await boot(page,width);
    if(dark) await page.evaluate(()=>{
      document.documentElement.dataset.telegramTheme='dark';
      document.documentElement.dataset.miniappColorScheme='dark';
      for(const [key,value] of Object.entries({'bg-color':'#17201e','secondary-bg-color':'#111816','text-color':'#f4f7f5','hint-color':'#a7b5af'}))
        document.documentElement.style.setProperty(`--tg-theme-${key}`,value);
    });
    const card=page.locator('article.application-card');
    await expect(card).toBeVisible();
    await expect(card.locator('.application-card-identifiers')).toContainText('12345678');
    const phone=card.getByRole('link',{name:'Call 0712345678'});
    await expect(phone).toHaveAttribute('href','tel:+254712345678');
    await expect(card.getByRole('button',{name:/Open application for Synthetic applicant/})).toBeVisible();
    await expect(card.locator('button a')).toHaveCount(0);
    expect(await page.locator('.list-heading').evaluate(node=>node.getBoundingClientRect().height)).toBeLessThanOrEqual(1);
    const header=await page.locator('.origination-header').evaluate(node=>{
      const title=node.querySelector('h1').getBoundingClientRect();
      const settings=node.querySelector('#origination-settings-open').getBoundingClientRect();
      return {titleTop:title.top,titleBottom:title.bottom,settingsTop:settings.top,settingsBottom:settings.bottom};
    });
    expect(header.settingsTop).toBeLessThan(header.titleBottom);
    expect(header.settingsBottom).toBeGreaterThan(header.titleTop);
    const geometry=await card.evaluate(node=>{
      const id=node.querySelector('[data-card-id-value]').getBoundingClientRect();
      const phone=node.querySelector('a[href^="tel:"]').getBoundingClientRect();
      return {idTop:id.top,phoneTop:phone.top,height:node.getBoundingClientRect().height,overflow:document.documentElement.scrollWidth>innerWidth};
    });
    expect(Math.abs(geometry.idTop-geometry.phoneTop)).toBeLessThanOrEqual(2);
    expect(geometry.height).toBeLessThan(180);
    expect(geometry.overflow).toBe(false);
    let opens=0;
    await page.route('**/applications/00000000-0000-0000-0000-000000000001/',route=>{opens++;return route.abort();});
    await phone.click({noWaitAfter:true});
    expect(opens).toBe(0);
    await page.screenshot({path:info.outputPath(`cards-${width}-${dark?'dark':'light'}.png`)});
    await card.getByRole('button',{name:/Open application for/}).click({position:{x:10,y:10}});
    await expect.poll(()=>opens).toBe(1);
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
  const strip = await page.locator('.wizard-actions').boundingBox();
  await page.locator('#section-next').click();
  await expect.poll(()=>page.evaluate(()=>__native.visible&&__handlers.size===1)).toBe(true);
  expect((await page.locator('.wizard-actions').boundingBox()).height).toBe(strip.height);
  expect((await page.locator('.wizard-submit-actions').boundingBox()).height).toBe(0);
  await page.evaluate(()=>[...__handlers][0]());
  await expect(page.locator('[data-field=applicant_name]')).toHaveAttribute('aria-invalid','true');
  await page.locator('[data-field=applicant_name]').fill('Synthetic Applicant');
  await expect(page.locator('[data-field=applicant_name]')).toHaveValue('Synthetic Applicant');
  await page.evaluate(()=>{document.getElementById('document-preview-overlay').hidden=false;});
  await expect.poll(()=>page.evaluate(()=>__native.visible)).toBe(false);
});

test('application filter choices come from the queue even without available new products',async({page},info)=>{
  const queries=[];page.on('request',request=>queries.push(request.url()));
  await boot(page,390,false,false,{}, {products:[{product_key:'retired-training',name:'Training Loan'}],
    statuses:[{value:'draft',label:'Draft'},{value:'changes',label:'Needs changes'},{value:'progress',label:'In progress'},{value:'completed',label:'Completed'},{value:'closed',label:'Closed'}]});
  await page.getByRole('button',{name:'Filters',exact:true}).click();
  await expect(page.getByLabel('Product')).toContainText('Training Loan');
  await expect(page.getByLabel('Status').locator('option')).toHaveCount(6);
  await page.getByLabel('Product').selectOption('retired-training');
  await page.getByLabel('Status').selectOption('completed');
  await page.screenshot({path:info.outputPath('application-filters-390.png')});
  await page.getByRole('button',{name:'Apply filters',exact:true}).click();
  await expect.poll(()=>queries.some(url=>url.includes('product_key=retired-training')&&url.includes('status_group=completed'))).toBe(true);
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
    await page.locator('#section-next').click();
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
    await page.locator('#section-next').click();
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
    await page.locator('#section-next').click();
    await expect(page.locator('[data-document-field="notes"]')).toBeEditable();
    await expect(page.getByRole('heading',{name:'Supporting documents',exact:true})).toHaveCount(0);
    expect(writes.length).toBeGreaterThan(0);
    expect(writes.at(-1).inactive_saved_value).toBeUndefined();
    await expect(page.locator('[data-document-field="notes"]')).toBeEditable();
    await expect(page.locator('[data-document-field="applicant_name"]')).toHaveCount(0);
    await expect(page.locator('[data-document-field="interest"]')).toHaveCount(0);
    await expect(page.locator('.supporting-shared-values>div').filter({hasText:'Interest amount'})).toContainText('0');
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

for(const width of [320,390,430,1280]) test(`optional ID pair preserves photos after failed upload ${width}`,async({page},info)=>{
  await boot(page,width);
  const id='00000000-0000-0000-0000-000000000001';
  let app={id,officer_id:1,revision:1,status:'draft',reference_number:'ORG-SYNTHETIC-ID',product_name:'Training',
    form_schema:{sections:[{key:'applicant',label:'Applicant'}],fields:[{key:'applicant_id_number',type:'national_id',label:'National ID',section_key:'applicant'}]},
    form_payload:{applicant_id_number:'99000001'},product_terms:{},requirement_evidence:[],identity_copy_policy:1,
    identity_copies:[{key:'borrower_id_copy',label:'Borrower ID copy',type:'document',identity_role:'borrower',identity_field:'applicant_id_number',subject_sha256:'synthetic-subject'}]};
  await page.route(`**/applications/${id}/`,route=>route.fulfill({json:{ok:true,application:app}}));
  const uploads=[];
  await page.route(`**/requirements/borrower_id_copy/evidence/`,route=>{
    uploads.push(route.request().postDataBuffer().toString());
    if(uploads.length===1) return route.fulfill({status:502,json:{ok:false,error:'Could not save. Retry.',evidence:{status:'failed'},application:app}});
    app={...app,revision:2,requirement_evidence:[{id:'synthetic-copy',requirement_key:'borrower_id_copy',requirement_label:'Borrower ID copy',filename:'client-id.pdf',byte_size:1000,status:'uploaded'}]};
    return route.fulfill({json:{ok:true,application:app}});
  });
  await page.locator('.application-card').click();
  await expect(page.locator('.origination-header')).toBeHidden();
  await page.locator('#section-next').click();
  await expect(page.getByText('Borrower ID copy',{exact:true})).toBeVisible();
  await expect(page.locator('.required-mark')).toHaveCount(0);
  await page.locator('[data-id-capture]').click();
  await page.locator('[data-id-upload]').click();
  await expect(page.locator('[data-id-status]')).toContainText('Add both');
  for(const side of ['front','back']) await page.locator(`[data-id-side="${side}"]`).setInputFiles({name:`synthetic-${side}.png`,mimeType:'image/png',buffer:fs.readFileSync(path.join(root,'core/static/miniapp/jawabu-logo.png'))});
  await expect(page.locator('[data-id-image="front"]')).toBeVisible();
  await expect(page.locator('[data-id-image="back"]')).toBeVisible();
  await page.screenshot({path:info.outputPath(`identity-pair-${width}.png`),fullPage:true});
  await page.locator('[data-id-image="front"]').click();
  await expect(page.locator('.identity-photo-preview')).toBeVisible();
  await page.getByRole('button',{name:'Next photo',exact:true}).click();
  await expect(page.locator('.identity-photo-controls span')).toHaveText('Back');
  await page.getByRole('button',{name:'Close photo preview',exact:true}).click();
  await page.locator('[data-id-upload]').click();
  await expect(page.locator('[data-id-status]')).toContainText('Could not save');
  await expect(page.locator('[data-id-image="front"]')).toBeVisible();
  await page.locator('[data-id-upload]').click();
  await expect(page.locator('#origination-sheet-overlay')).toBeHidden();
  await expect(page.locator('.evidence-row')).toContainText('client-id.pdf');
  expect(uploads).toHaveLength(2);
  expect(uploads[1]).toContain('name="front"');expect(uploads[1]).toContain('name="back"');
});

test('Main LAF radio is a circle with document version and no rectangular input border',async({page},info)=>{
  await boot(page,390);
  await page.route('**/products/**',route=>route.fulfill({json:{ok:true,branches:['Synthetic'],products:[
    {product_key:'training',name:'Training',template_ready:true,document_catalogue:{ready:true,main_lafs:[{id:'synthetic-template',name:'Same named LAF',version:3}],supporting_documents:[]}}]}}));
  await page.getByRole('button',{name:'Start application',exact:true}).click();
  await page.locator('#origination-create-branch').evaluate(node=>{node.add(new Option('Synthetic','Synthetic'));});
  await page.locator('#origination-create-branch').selectOption('Synthetic');
  await page.locator('#origination-create-product').selectOption('training');
  const radio=page.locator('.packet-document-option input[type=radio]');
  await expect(radio).toHaveCSS('height','18px');
  await expect(radio).toHaveCSS('box-shadow','none');
  await expect(page.getByText(/version 3/)).toBeVisible();
  await radio.check();
  await expect(radio).toHaveCSS('outline-style','none');
  await page.screenshot({path:info.outputPath('main-laf-radio-390.png'),fullPage:true});
});

test('native Start application removes its duplicate footer gap',async({page},info)=>{
  await boot(page,390,false,true);
  await page.route('**/products/**',route=>route.fulfill({json:{ok:true,branches:['Synthetic'],products:[
    {product_key:'training',name:'Training',template_ready:true,document_catalogue:{ready:true,main_lafs:[{id:'synthetic-template',name:'Training LAF',version:3}],supporting_documents:[]}}]}}));
  await page.getByRole('button',{name:'Start application',exact:true}).click();
  await page.locator('#origination-create-branch').evaluate(node=>node.add(new Option('Synthetic','Synthetic')));
  await page.locator('#origination-create-branch').selectOption('Synthetic');
  await page.locator('#origination-create-product').selectOption('training');
  await page.locator('.packet-document-option input[type=radio]').check();
  await expect.poll(()=>page.evaluate(()=>__native.visible&&__handlers.size===1)).toBe(true);
  const footer=await page.locator('#origination-sheet-footer').boundingBox();
  expect(footer.height).toBe(0);
  const content=await page.locator('#origination-create-documents').boundingBox();
  const sheet=await page.locator('#origination-sheet').boundingBox();
  expect(sheet.y+sheet.height-content.y-content.height).toBeLessThan(18);
  await page.screenshot({path:info.outputPath('create-application-native-390.png'),fullPage:true});
});
