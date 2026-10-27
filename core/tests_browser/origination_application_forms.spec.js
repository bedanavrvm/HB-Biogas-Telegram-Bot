'use strict';
const fs = require('node:fs');
const path = require('node:path');
const {execFileSync} = require('node:child_process');
const {test, expect} = require('playwright/test');
const root = path.resolve(__dirname, '../..');
// Render Django's complete shell, including its real stylesheet/script order.
// Only identity, operational API I/O and the Telegram client are synthetic.
const shell = execFileSync(path.join(root,process.platform==='win32'?'.venv/Scripts/python.exe':'.venv/bin/python'), ['-c',
  "import django; django.setup(); from django.template.loader import render_to_string; print(render_to_string('loan_origination/app.html'))"],
  {cwd:root,encoding:'utf8',env:{...process.env,PYTHONIOENCODING:'utf-8',DJANGO_SETTINGS_MODULE:'config.settings',DATABASE_URL:'sqlite:///:memory:',
    DJANGO_SECRET_KEY:'synthetic-origination-browser-only-'+ '0'.repeat(32),SENTRY_DSN:'',TELEGRAM_BOT_TOKEN:''}});
const clone = value => JSON.parse(JSON.stringify(value));

async function boot(page, {linked=false, failure=false, dark=false, width=360, delay=0, configure=()=>{}, documentUpdate=false, updateFailure=false}={}) {
  const runtimeErrors=[];
  page.on('pageerror',error=>runtimeErrors.push(error.message));
  await page.setViewportSize({width,height:844});
  const field = (key, section_key, subject='applicant', owner={kind:'main',section_key}) => ({
    key, label:key.replaceAll('_',' '),type:'text',section_key,input_owner:owner,
    value_contract:{version:2,scope:'application',source:'entered',subject},
  });
  const fields = [field('applicant_name','applicant'),field('applicant_phone','applicant'),field('applicant_id_number','applicant'),
    ...['name','id_number','phone'].map(key=>field(`spouse_${key}`,'applicant','spouse')),
    ...[1,2].flatMap(n=>['name','id_number','phone'].map(key=>field(`guarantor_${n}_${key}`,'guarantors',`guarantor_${n}`))),
    field('guaranteed_amount','document_details','loan',{kind:'document',document_key:'guarantee'})];
  const shared = fields.find(item=>item.key==='applicant_name');
  const amount = fields.at(-1);
  const note = {...field('guarantee_notes','undertaking','document'),value_contract:{scope:'document',source:'entered'}};
  const app = {id:'00000000-0000-4000-8000-000000000061',officer_id:1,revision:1,status:'draft',
    reference_number:'ORG-SYNTHETIC-FORMS',display_reference:'ORG-12',product_name:'Synthetic loan',branch:'Synthetic branch',
    applicant_summary:{name:'Synthetic Wanjiku Mwangi-Kamau',phone:'0700000001',national_id:'00099001'},
    value_contract_version:2,form_projection_version:1,product_terms:{},
    form_payload:{applicant_name:'Synthetic Wanjiku Mwangi-Kamau',applicant_phone:'0700000001',applicant_id_number:'00099001',
      spouse_name:'Synthetic spouse',spouse_id_number:'00099002',spouse_phone:'0700000002',
      guarantor_1_name:'Synthetic first',guarantor_1_id_number:'00099003',guarantor_1_phone:'0700000003',
      guarantor_2_name:'Synthetic spouse',guarantor_2_id_number:'00099002',guarantor_2_phone:'0700000002',
      _person_role_bindings:linked?{guarantor_2:'spouse'}:{}},
    person_role_fields:Object.fromEntries(['spouse','guarantor_1','guarantor_2'].map(role=>[role,{name:`${role}_name`,national_id:`${role}_id_number`,phone:`${role}_phone`}])),
    form_schema:{sections:[{key:'applicant',label:'Applicant'},{key:'guarantors',label:'Guarantors'},
      {key:'document_details',label:'Document details'}],fields},
    document_packet:{documents:[{key:'guarantee',name:'Guarantor form',role:'supporting',selected:true,applicable:true,
      field_payload:{applicant_name:'Stale document name',guarantee_notes:''},resolved_values:{applicant_name:'Synthetic Wanjiku Mwangi-Kamau'},
      schema:{sections:[{key:'undertaking',label:'Undertaking'}],fields:[shared,amount,note]}},
    {key:'confirmation',name:'Confirmation',role:'supporting',selected:true,applicable:true,field_payload:{},
      resolved_values:{applicant_name:'Synthetic Wanjiku Mwangi-Kamau'},schema:{sections:[],fields:[shared]}}]},
  };
  configure(app);
  const writes=[]; const previews=[]; const previewBodies=[]; const documentUpdates=[];
  let hasDocumentUpdate = documentUpdate === true;
  let failDocumentUpdate = updateFailure;
  let fail=failure;
  await page.route('http://127.0.0.1:8161/**',async route=>{
    const request=route.request(),url=new URL(request.url());
    if(url.pathname==='/') return route.fulfill({contentType:'text/html',body:shell});
    if(url.pathname.startsWith('/static/')) {
      const relative = url.pathname.slice('/static/'.length);
      const file = ['origination/static','core/static'].map(dir=>path.join(root,dir,relative)).find(file=>fs.existsSync(file));
      if(!file) return route.abort();
      const contentType = file.endsWith('.css')?'text/css':file.endsWith('.js')?'application/javascript':file.endsWith('.png')?'image/png':'application/octet-stream';
      return route.fulfill({contentType,body:fs.readFileSync(file)});
    }
    if(url.pathname.endsWith('/products/')) return route.fulfill({json:{ok:true,products:[],branches:[],capabilities:{can_create:true,user_id:1}}});
    if(url.pathname.endsWith('/applications/')) return route.fulfill({json:{ok:true,applications:[app],tab_counts:{action:1,applications:1},status_options:[],pagination:{page:1,pages:1,total:1},capabilities:{can_create:true,user_id:1}}});
    if(url.pathname.endsWith('/documents/updates/')) {
      expect(request.method()).toBe('POST');
      documentUpdates.push(request.postDataJSON());
      if(failDocumentUpdate) {failDocumentUpdate=false; return route.fulfill({status:503,json:{ok:false,error:'Could not check document updates. Your saved answers are kept.'}});}
      app.document_update_notice=null;
      if(hasDocumentUpdate) {
        hasDocumentUpdate=false;
        app.revision++;app.status='draft';
        const doc=app.document_packet.documents[0];doc.template_version=2;
        doc.schema.fields.push({key:'visit_reason',label:'Visit reason',type:'text',section_key:'undertaking',
          value_contract:{version:2,scope:'document',source:'entered',subject:'document'}});
        app.document_update_notice={status:'updated',message:'Documents updated automatically. Check any new or changed fields.'};
      }
      return route.fulfill({json:{ok:true,application:clone(app)}});
    }
    if(url.pathname.includes('/preview/')) {previews.push(url.pathname);previewBodies.push(request.postDataJSON());return route.fulfill({status:503,json:{ok:false,error:'Synthetic preview unavailable'}});}
    if(request.method()==='PATCH'||url.pathname.endsWith('/fields/')) {
      const body=request.postDataJSON();writes.push(clone(body));
      if(delay) await new Promise(resolve=>setTimeout(resolve,delay));
      if(fail) return route.fulfill({status:503,json:{ok:false,error:'Synthetic save failed'}});
      if(body.form_payload) app.form_payload=clone(body.form_payload);
      if(body.payload) {
        const doc=app.document_packet.documents.find(doc=>url.pathname.includes(`/documents/${doc.key}/`));
        for(const [key,value] of Object.entries(body.payload)) {
          if(fields.some(field=>field.key===key)) app.form_payload[key]=value;
          else doc.field_payload[key]=value;
        }
      }
      app.revision++;
      app.applicant_summary.name=app.form_payload.applicant_name;
      for(const doc of app.document_packet.documents) doc.resolved_values.applicant_name=app.form_payload.applicant_name;
    }
    if(url.pathname.includes(`/applications/${app.id}/`)) return route.fulfill({json:{ok:true,application:clone(app)}});
    return route.abort();
  });
  await page.route('https://telegram.org/**',route=>route.fulfill({contentType:'application/javascript',body:'/* Synthetic Telegram bridge supplied before page scripts. */'}));
  await page.addInitScript(({dark})=>{
    window.__copied=[];Object.defineProperty(navigator,'clipboard',{value:{writeText:async value=>window.__copied.push(value)},configurable:true});
    window.confirm=()=>true;
    window.Telegram={WebApp:{initData:'synthetic-only',colorScheme:dark?'dark':'light',ready(){},expand(){},onEvent(){},BackButton:{show(){},hide(){},onClick(){},offClick(){}}}};
    if(dark) document.addEventListener('DOMContentLoaded',()=>{
      for(const [key,value] of Object.entries({'bg-color':'#17201e','secondary-bg-color':'#111816','text-color':'#f4f7f5','hint-color':'#a7b5af'})) document.documentElement.style.setProperty(`--tg-theme-${key}`,value);
    });
  },{dark});
  const reopen = async () => {
  await page.goto('http://127.0.0.1:8161/');
  await page.locator('[data-application-open]').click();
  await page.evaluate(()=>document.fonts.ready);
  };
  await reopen();
  return {app,writes,previews,previewBodies,reopen,retry:()=>{fail=false;},documentUpdates,runtimeErrors,publishDocument:()=>{hasDocumentUpdate=true;}};
}

async function section(page,label) {
  await page.locator('#origination-section-picker').click();
  await page.locator('[data-section-index]').filter({hasText:label}).click();
  await expect(page.locator('#origination-section-picker strong')).toHaveText(label);
}

for(const {width,dark} of [{width:320,dark:false},{width:390,dark:true},{width:1280,dark:false}])
test(`delete is a single red header icon immediately before manage documents (${width}, dark=${dark})`,async({page},info)=>{
  await boot(page,{width,dark,configure:app=>{app.lifecycle={can_delete:true,can_invalidate:false};}});
  for(const label of ['Applicant','Guarantors','Review']) {
    await section(page,label);
    const remove=page.getByRole('button',{name:'Delete application',exact:true});
    await expect(remove).toHaveCount(1);
    await expect(page.locator('.editor-document-actions > #origination-remove + #origination-restart-laf')).toHaveCount(1);
    await expect(remove.locator('svg')).toHaveCount(1);
    expect((await remove.textContent()).trim()).toBe('');
    expect(await remove.evaluate(button=>getComputedStyle(button).color)).toBe(dark?'rgb(255, 138, 128)':'rgb(165, 42, 29)');
    await expect(page.locator('.wizard-card #origination-remove,.wizard-submit-actions #origination-remove')).toHaveCount(0);
    const removeBox=await remove.boundingBox(),manageBox=await page.locator('#origination-restart-laf').boundingBox();
    expect(removeBox.x+removeBox.width).toBeLessThanOrEqual(manageBox.x);
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  }
  await page.screenshot({path:info.outputPath('application-header.png'),fullPage:true});
  await page.getByRole('button',{name:'Delete application',exact:true}).click();
  await expect(page.locator('#origination-removal-confirm')).toBeVisible();
  await expect(page.locator('#origination-invalidation-reason')).toHaveCount(0);
});

test('signed application header uses invalidation and still requires an audit reason',async({page})=>{
  await boot(page,{configure:app=>{app.status='signed_pending_approval';app.lifecycle={can_delete:false,can_invalidate:true};}});
  const remove=page.getByRole('button',{name:'Invalidate application',exact:true});
  await expect(page.locator('.editor-document-actions #origination-remove')).toHaveCount(1);
  await expect(page.getByRole('button',{name:'Delete application',exact:true})).toHaveCount(0);
  await remove.click();
  await expect(page.locator('#origination-invalidation-reason')).toBeVisible();
  await page.locator('#origination-removal-confirm').click();
  await expect(page.locator('#origination-removal-error')).toHaveText('Enter a reason.');
});

test('application removal remains hidden without its own workflow authority',async({page})=>{
  await boot(page,{configure:app=>{app.lifecycle={can_delete:false,can_invalidate:false};}});
  await expect(page.locator('#origination-remove')).toHaveCount(0);
});

for(const dark of [false,true]) test(`unsigned documents update automatically without a confirmation (dark=${dark})`,async({page},info)=>{
  const {app,documentUpdates,runtimeErrors}=await boot(page,{dark,width:dark?390:360,documentUpdate:true,
    configure:app=>{app.auto_update_documents=true;app.status='reviewed';}});
  expect(documentUpdates).toHaveLength(1);
  expect(app.revision).toBe(2);
  await expect(page.locator('#miniapp-shared-toast')).toContainText('Documents updated automatically');
  await expect(page.getByRole('button',{name:'Update documents',exact:true})).toHaveCount(0);
  await expect(page.locator('#origination-sheet-overlay')).toBeHidden();
  await expect(page.locator('[data-field=applicant_name]')).toHaveValue('Synthetic Wanjiku Mwangi-Kamau');
  await section(page,'Guarantor form');
  await expect(page.locator('[data-reused-field=applicant_name]')).toHaveValue('Synthetic Wanjiku Mwangi-Kamau');
  await expect(page.getByLabel('Visit reason')).toBeVisible();
  await page.screenshot({path:info.outputPath(`automatic-support-${dark?'dark':'light'}.png`),fullPage:true});
  expect(runtimeErrors).toEqual([]);
});

test('automatic update failure keeps the saved form usable and reopening retries',async({page})=>{
  const {reopen,documentUpdates}=await boot(page,{documentUpdate:true,updateFailure:true,configure:app=>{app.auto_update_documents=true;}});
  await expect(page.locator('#miniapp-shared-toast')).toContainText('Your saved answers are kept');
  await expect(page.locator('[data-field=applicant_name]')).toHaveValue('Synthetic Wanjiku Mwangi-Kamau');
  await reopen();
  await expect(page.locator('#miniapp-shared-toast')).toContainText('Documents updated automatically');
  expect(documentUpdates).toHaveLength(2);
});

test('resuming an unsigned application adopts a publication without a refresh button',async({page})=>{
  const {publishDocument,documentUpdates,runtimeErrors}=await boot(page,{configure:app=>{app.auto_update_documents=true;}});
  expect(documentUpdates).toHaveLength(1);
  publishDocument();
  await page.locator('#origination-section-picker').focus();
  await page.evaluate(()=>window.dispatchEvent(new Event('pageshow')));
  await expect.poll(()=>documentUpdates.length).toBe(2);
  await expect(page.locator('#miniapp-shared-toast')).toContainText('Documents updated automatically');
  await section(page,'Guarantor form');
  await expect(page.getByLabel('Visit reason')).toBeVisible();
  expect(runtimeErrors).toEqual([]);
});

test('signed application does not request document updates',async({page})=>{
  const {documentUpdates}=await boot(page,{configure:app=>{app.status='approved';app.auto_update_documents=false;}});
  expect(documentUpdates).toHaveLength(0);
  await expect(page.getByRole('button',{name:'Update documents',exact:true})).toHaveCount(0);
});

for(const linked of [false,true]) test(`clear Guarantor 2 persists without changing source (linked=${linked})`,async({page})=>{
  const {app}=await boot(page,{linked});
  await section(page,'Guarantors');
  await page.getByRole('button',{name:'Clear Guarantor 2',exact:true}).click();
  await expect.poll(()=>app.form_payload.guarantor_2_name).toBe('');
  expect(app.form_payload._person_role_bindings).not.toHaveProperty('guarantor_2');
  expect(app.form_payload.spouse_name).toBe('Synthetic spouse');
  expect(app.form_payload.guarantor_1_name).toBe('Synthetic first');
  await section(page,'Applicant');await section(page,'Guarantors');
  await expect(page.locator('[data-field=guarantor_2_name]')).toHaveValue('');
  await page.locator('#origination-back').click();await page.locator('.application-card').click();
  await section(page,'Guarantors');
  await expect(page.locator('[data-field=guarantor_2_name]')).toHaveValue('');
});

test('supporting documents have one page each and reuse Main LAF values',async({page},info)=>{
  const {app,writes,previews}=await boot(page);
  await page.locator('#origination-section-picker').click();
  await expect(page.locator('[data-section-index]')).toHaveCount(5);
  await expect(page.locator('[data-section-index]').filter({hasText:'Document details'})).toHaveCount(0);
  await expect(page.locator('[data-section-index]').filter({hasText:'Supporting documents'})).toHaveCount(0);
  await page.locator('[data-section-index]').filter({hasText:'Guarantor form'}).click();
  await expect(page.locator('[data-document-field=guaranteed_amount]')).toBeVisible();
  await expect(page.locator('[data-document-field=applicant_name]')).toHaveCount(0);
  await expect(page.locator('[data-reused-field=applicant_name]')).toHaveValue(app.applicant_summary.name);
  await expect(page.locator('[data-reused-field=applicant_name]')).toHaveAttribute('readonly','');
  await expect(page.locator('[data-input-source]')).toHaveCount(0);
  await page.locator('[data-document-field=guarantee_notes]').fill('Synthetic undertaking');
  await page.locator('[data-document-field=guaranteed_amount]').fill('25000');
  await page.getByRole('button',{name:'Preview document',exact:true}).click();
  await expect.poll(()=>previews.length).toBe(1);
  expect(previews[0]).toContain('/documents/guarantee/');
  expect(writes.at(-1).payload).toMatchObject({guarantee_notes:'Synthetic undertaking',guaranteed_amount:'25000'});
  await page.locator('#preview-close').click();
  await section(page,'Confirmation');
  await expect(page.getByRole('button',{name:'Preview document',exact:true})).toBeVisible();
  await expect(page.locator('[data-reused-field=applicant_name]')).toHaveValue(app.applicant_summary.name);
  await page.screenshot({path:info.outputPath('autofilled-document.png'),fullPage:true});
});

for(const dark of [false,true]) test(`two-row header without contact or reference clutter (${dark?'dark':'light'})`,async({page},info)=>{
  await boot(page,{dark,width:dark?390:360});
  await expect(page.locator('.editor-contacts')).toHaveCount(0);
  await expect(page.locator('.editor-summary')).not.toContainText('0700000001');
  await expect(page.locator('.editor-summary')).not.toContainText('00099001');
  await expect(page.locator('.editor-summary>.editor-context')).toHaveCount(1);
  await expect(page.locator('.editor-summary>.wizard-progress-compact')).toHaveCount(1);
  await expect(page.locator('.editor-summary .wizard-progress-track')).toHaveCount(1);
  await expect(page.locator('[data-field=applicant_phone]')).toHaveValue('0700000001');
  await expect(page.locator('[data-field=applicant_id_number]')).toHaveValue('00099001');
  expect((await page.locator('.editor-summary').boundingBox()).height).toBeLessThanOrEqual(112);
  await page.screenshot({path:info.outputPath(`application-header-${dark?'dark':'light'}.png`),fullPage:true});
  await expect(page.locator('.editor-identity')).not.toContainText('ORG-SYNTHETIC');
  await expect(page.getByText('Applicant contacts',{exact:true})).toHaveCount(0);
  await expect(page.getByRole('button',{name:'Manage documents',exact:true})).toHaveCount(1);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await section(page,'Guarantor form');
  await page.screenshot({path:info.outputPath(`supporting-document-${dark?'dark':'light'}.png`),fullPage:true});
});

for(const dark of [false,true]) test(`header dropdown is anchored, keyboard-operable and closes cleanly (${dark?'dark':'light'})`,async({page},info)=>{
  const {runtimeErrors}=await boot(page,{dark,configure:app=>{
    app.applicant_summary.name='Mary Wanjiku';app.product_name='Inua';
    app.form_schema.sections[0].label='Applicant details';
  }});
  const trigger=page.locator('#origination-section-picker'),menu=page.locator('#origination-section-menu');
  await expect(page.locator('#section-previous')).toBeDisabled();
  await trigger.focus();await trigger.press('ArrowDown');
  await expect(trigger).toHaveAttribute('aria-expanded','true');
  await expect(menu.locator('[aria-current=step]')).toBeFocused();
  await expect(page.locator('#origination-sheet-overlay')).toBeHidden();
  const header=await page.locator('.editor-summary').boundingBox(),box=await menu.boundingBox();
  expect(box.y).toBeGreaterThanOrEqual(header.y+header.height);
  expect(box.x).toBeGreaterThanOrEqual(0);expect(box.x+box.width).toBeLessThanOrEqual(360);
  await page.screenshot({path:info.outputPath(`section-menu-${dark?'dark':'light'}.png`),fullPage:true});
  await menu.locator('[aria-current=step]').press('ArrowDown');
  await expect(menu.locator('[data-section-index="1"]')).toBeFocused();
  await page.keyboard.press('Escape');
  await expect(menu).toBeHidden();await expect(trigger).toBeFocused();
  await expect(trigger).toHaveAttribute('aria-expanded','false');
  await trigger.click();await page.locator('[data-field=spouse_phone]').click();
  await expect(menu).toBeHidden();
  await trigger.click();await page.locator('[data-field=applicant_name]').focus();
  await expect(menu).toBeHidden();
  await trigger.focus();await trigger.press('ArrowDown');await page.keyboard.press('End');
  await expect(menu.locator('[data-section-index="4"]')).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(trigger.locator('strong')).toHaveText('Review');await expect(trigger).toBeFocused();
  await expect(page.locator('#section-next')).toBeDisabled();
  await expect(page.locator('.wizard-progress-track')).toHaveAttribute('aria-valuenow','5');
  expect(runtimeErrors).toEqual([]);
});

test('header controls use real preview, document choices and individual/combined downloads',async({page})=>{
  const {previews,writes,runtimeErrors}=await boot(page,{configure:app=>{
    app.download_choices=[{document_key:'',label:'All documents',description:'Combined PDF',available:true},
      ...app.document_packet.documents.map(doc=>({document_key:doc.key,label:doc.name,available:true}))];
  }});
  let choices=0;
  await page.route('**/documents/choices/',route=>{
    choices++;
    return route.fulfill({json:{ok:true,primary_template_id:'synthetic-main',catalogue_revision:'fixture',
      main_lafs:[{id:'synthetic-main',name:'Synthetic Main LAF',selected:true,version:6}],supporting_documents:[]}});
  });
  await page.locator('#origination-restart-laf').click();
  await expect(page.locator('#origination-documents-form')).toContainText('Synthetic Main LAF');
  expect(choices).toBe(1);
  await page.locator('[data-sheet-cancel]').click();
  await page.locator('#origination-preview-early').click();
  await expect.poll(()=>previews.length).toBe(1);
  await expect(page.locator('#miniapp-shared-toast')).toContainText('Synthetic preview unavailable');
  await page.locator('#preview-close').click();
  await page.locator('#origination-download').click();
  await expect(page.locator('.document-download-choice')).toHaveCount(3);
  await expect(page.locator('.document-download-list')).toContainText('Guarantor form');
  await expect(page.locator('.document-download-list')).toContainText('Confirmation');
  await page.locator('#origination-sheet-close').click();
  expect(writes).toHaveLength(0);expect(runtimeErrors).toEqual([]);
});

test('header arrows serialize navigation and keep unsaved answers on failure',async({page})=>{
  const {writes,retry,runtimeErrors}=await boot(page,{failure:true,delay:150});
  await page.locator('[data-field=applicant_name]').fill('Keep this synthetic name');
  await page.locator('#section-next').evaluate(button=>{button.click();button.click();});
  await expect(page.locator('#miniapp-shared-toast')).toContainText('Synthetic save failed');
  await expect(page.locator('#origination-section-picker strong')).toHaveText('Applicant');
  await expect(page.locator('[data-field=applicant_name]')).toHaveValue('Keep this synthetic name');
  expect(writes).toHaveLength(1);
  retry();await page.locator('#section-next').click();
  await expect(page.locator('#origination-section-picker strong')).toHaveText('Guarantors');
  await page.locator('#section-previous').click();
  await expect(page.locator('[data-field=applicant_name]')).toHaveValue('Keep this synthetic name');
  expect(runtimeErrors).toEqual([]);
});

test('header tolerates long names, long section labels and 200 percent text',async({page},info)=>{
  const {runtimeErrors}=await boot(page,{width:320,configure:app=>{
    app.applicant_summary.name="Synthetic Wanjiku O'Kamau-Mwangi Wambui";
    app.product_name='Synthetic product with a long descriptive name';
    app.form_schema.sections[0].label='Applicant identity, household and residence details';
  }});
  await page.evaluate(()=>document.documentElement.style.fontSize='200%');
  await page.locator('#origination-section-picker').click();
  const metrics=await page.locator('.editor-summary').evaluate(header=>{
    const box=element=>{const rect=element.getBoundingClientRect();return {left:rect.left,right:rect.right,top:rect.top,bottom:rect.bottom};};
    return {title:box(header.querySelector('.editor-identity')),actions:box(header.querySelector('.editor-document-actions')),
      previous:box(header.querySelector('#section-previous')),trigger:box(header.querySelector('#origination-section-picker')),next:box(header.querySelector('#section-next'))};
  });
  expect(metrics.title.right).toBeLessThanOrEqual(metrics.actions.left);
  expect(metrics.previous.right).toBeLessThanOrEqual(metrics.trigger.left);
  expect(metrics.trigger.right).toBeLessThanOrEqual(metrics.next.left);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.screenshot({path:info.outputPath('header-large-text.png'),fullPage:true});
  expect(runtimeErrors).toEqual([]);
});

test('reused values are read only and refresh after saving their source section',async({page})=>{
  const {app}=await boot(page);
  await section(page,'Guarantor form');
  await page.locator('[data-document-field=guarantee_notes]').fill('Keep this document note');
  await expect(page.locator('[data-input-source]')).toHaveCount(0);
  await section(page,'Applicant');
  await page.locator('[data-field=applicant_name]').fill('Synthetic updated applicant');
  await section(page,'Guarantor form');
  await expect(page.locator('[data-reused-field=applicant_name]')).toHaveValue('Synthetic updated applicant');
  await expect(page.locator('[data-document-field=guarantee_notes]')).toHaveValue('Keep this document note');
  expect(app.document_packet.documents[0].field_payload.guarantee_notes).toBe('Keep this document note');
});

test('failed document save prevents navigation and keeps typed values for retry',async({page},info)=>{
  const {app,retry}=await boot(page,{failure:true});
  await section(page,'Guarantor form');
  await page.locator('[data-document-field=guarantee_notes]').fill('Keep after failure');
  await page.locator('#section-next').click();
  await expect(page.locator('#miniapp-shared-toast')).toContainText('Synthetic save failed');
  await expect(page.locator('[data-document-field=guarantee_notes]')).toHaveValue('Keep after failure');
  await page.screenshot({path:info.outputPath('document-save-failed.png'),fullPage:true});
  retry();await page.locator('#section-next').click();
  await expect(page.getByRole('heading',{name:'Confirmation',exact:true})).toBeVisible();
  expect(app.document_packet.documents[0].field_payload.guarantee_notes).toBe('Keep after failure');
});

test('clearing during an earlier save cannot restore the previous guarantor',async({page})=>{
  const {app,writes}=await boot(page,{linked:true,delay:500});
  await section(page,'Guarantors');
  await page.locator('[data-field=guarantor_1_name]').fill('Synthetic first updated');
  await expect.poll(()=>writes.length).toBe(1);
  await page.getByRole('button',{name:'Clear Guarantor 2',exact:true}).click();
  await expect.poll(()=>app.form_payload.guarantor_2_name).toBe('');
  expect(app.form_payload.guarantor_1_name).toBe('Synthetic first updated');
  expect(app.form_payload.spouse_name).toBe('Synthetic spouse');
  expect(app.form_payload._person_role_bindings).not.toHaveProperty('guarantor_2');
});

test('clearing save failure never reports success and can be retried',async({page})=>{
  const {app,retry}=await boot(page,{linked:true,failure:true});
  await section(page,'Guarantors');
  await page.getByRole('button',{name:'Clear Guarantor 2',exact:true}).click();
  await expect(page.locator('#miniapp-shared-toast')).toContainText('Could not save the cleared guarantor');
  expect(app.form_payload.guarantor_2_name).toBe('Synthetic spouse');
  retry();await page.getByRole('button',{name:'Clear Guarantor 2',exact:true}).click();
  await expect.poll(()=>app.form_payload.guarantor_2_name).toBe('');
});

test('applicant header reflects confirmed saves, not failed edits',async({page})=>{
  const {retry}=await boot(page,{failure:true});
  await page.locator('[data-field=applicant_name]').fill('Synthetic saved name');
  await page.locator('#section-next').click();
  await expect(page.locator('#miniapp-shared-toast')).toContainText('Synthetic save failed');
  await expect(page.locator('.editor-identity>strong')).toHaveText('Synthetic Wanjiku Mwangi-Kamau');
  retry();await page.locator('#section-next').click();
  await expect(page.locator('.editor-identity>strong')).toHaveText('Synthetic saved name');
  await expect(page.locator('.editor-identity>strong')).toHaveAttribute('title','Synthetic saved name');
});

test('separate document instances share canonical values but keep their own notes',async({page})=>{
  const {app,reopen}=await boot(page);
  const second=clone(app.document_packet.documents[0]);
  second.key='second-guarantee';second.name='Second guarantee';second.field_payload={};
  app.document_packet.documents.splice(1,0,second);
  await reopen();
  await section(page,'Guarantor form');
  await page.locator('[data-document-field=guaranteed_amount]').fill('25000');
  await page.locator('[data-document-field=guarantee_notes]').fill('First guarantee');
  await section(page,'Second guarantee');
  await expect(page.locator('[data-document-field=guaranteed_amount]')).toHaveCount(0);
  await expect(page.locator('[data-reused-field=guaranteed_amount]')).toHaveValue('25000');
  await expect(page.locator('[data-document-field=guarantee_notes]')).toHaveValue('');
  await page.locator('[data-document-field=guarantee_notes]').fill('Second guarantee');
  await section(page,'Review');
  expect(app.document_packet.documents[0].field_payload.guarantee_notes).toBe('First guarantee');
  expect(app.document_packet.documents[1].field_payload.guarantee_notes).toBe('Second guarantee');
  expect(app.form_payload.guaranteed_amount).toBe('25000');
});

test('incomplete document preview asks and sends explicit confirmation',async({page})=>{
  const {app,reopen,previewBodies}=await boot(page);
  const doc=app.document_packet.documents[0];
  doc.schema.fields.find(field=>field.key==='guarantee_notes').required=true;
  doc.missing_fields=['guarantee_notes'];
  await reopen();await section(page,'Guarantor form');
  await page.evaluate(()=>window.confirm=()=>false);
  await page.getByRole('button',{name:'Preview document',exact:true}).click();
  expect(previewBodies).toHaveLength(0);
  await page.evaluate(()=>window.confirm=()=>true);
  await page.getByRole('button',{name:'Preview document',exact:true}).click();
  await expect.poll(()=>previewBodies.length).toBe(1);
  expect(previewBodies[0].allow_incomplete).toBe(true);
});

test('document recovery reopens the correct page and saves restored fields',async({page})=>{
  const {app,writes,retry,reopen}=await boot(page,{failure:true});
  await section(page,'Guarantor form');
  await page.locator('[data-document-field=guarantee_notes]').fill('Recover this document');
  await expect.poll(()=>writes.length).toBeGreaterThan(0);
  await expect(page.locator('#origination-save-status')).toContainText('Not saved');
  await reopen();
  await expect(page.locator('[data-document-field=guarantee_notes]')).toHaveValue('Recover this document');
  retry();await page.locator('#section-next').click();
  await expect(page.getByRole('heading',{name:'Confirmation',exact:true})).toBeVisible();
  expect(app.document_packet.documents[0].field_payload.guarantee_notes).toBe('Recover this document');
});

for (const width of [320,360,390,430]) for(const dark of [false,true]) test(`compact header and aligned fields ${width} ${dark?'dark':'light'}`,async({page},info)=>{
  await boot(page,{width,dark,configure:app=>{
    app.form_schema.fields.slice(0,2).forEach((field,index)=>Object.assign(field,{
      label:index?'Short label':'Applicant contact email with a longer visible label',
      help_text:index?'':'A longer explanation that should wrap below the input, not displace its neighbour.',
      ...(index?{}:{validation:{format:'email'}}),
    }));
    const doc=app.document_packet.documents[0];
    for(const [key,type,value] of [['zero','number',0],['consent','boolean',false],['nationality','choice','ke'],['missing','text','']]) {
      app.form_payload[key]=value;
      const field={key,label:key,type,value_contract:{source:'entered',scope:'application'},options:[{code:'ke',label:'Kenya'}]};
      app.form_schema.fields.push({...field,section_key:'guarantors',input_owner:{kind:'main',section_key:'guarantors'}});
      doc.schema.fields.push(field);
    }
  }});
  const first=page.locator('[data-field=applicant_name]'),second=page.locator('[data-field=applicant_phone]');
  if(width>390) {
    expect(Math.abs((await first.boundingBox()).y-(await second.boundingBox()).y)).toBeLessThan(1);
    await first.fill('bad');await second.focus();
    await page.locator('#section-next').click();
    await expect(page.locator('[data-field-wrap=applicant_name] .miniapp-field-error')).toBeVisible();
    expect(Math.abs((await first.boundingBox()).y-(await second.boundingBox()).y)).toBeLessThan(1);
    const error=await page.locator('[data-field-wrap=applicant_name] .miniapp-field-error').boundingBox();
    expect(error.y).toBeGreaterThanOrEqual((await first.boundingBox()).y+(await first.boundingBox()).height);
    await page.screenshot({path:info.outputPath('aligned-validation.png'),fullPage:true});
    await first.fill('synthetic@example.invalid');await second.focus();
  }
  const header=await page.locator('.editor-summary').boundingBox();
  expect(header.y).toBeLessThanOrEqual(1);
  const fontEvidence=await page.evaluate(()=>({
    bodyFont:getComputedStyle(document.body).fontFamily,
    loadedFaces:[...document.fonts].map(font=>({family:font.family,status:font.status})),
    sourceStyles:[...document.styleSheets].map(sheet=>sheet.href).filter(Boolean),
  }));
  const fontPath=info.outputPath('font-and-shell-evidence.json');
  fs.writeFileSync(fontPath,JSON.stringify(fontEvidence,null,2));
  await info.attach('font-and-shell-evidence',{contentType:'application/json',path:fontPath});
  for(const id of ['origination-back','origination-restart-laf','origination-preview-early','origination-download']) {
    const button=page.locator(`#${id}`),box=await button.boundingBox();
    expect(box.width).toBeGreaterThanOrEqual(44);expect(box.height).toBeGreaterThanOrEqual(44);
    await expect(button).toHaveCSS('border-top-width','0px');
    await expect(button).toHaveCSS('background-color','rgba(0, 0, 0, 0)');
  }
  await page.screenshot({path:info.outputPath('header.png'),fullPage:true});
  await section(page,'Guarantor form');
  for(const [key,value] of [['zero','0'],['consent','No'],['nationality','Kenya']]) await expect(page.locator(`[data-reused-field=${key}]`)).toHaveValue(value);
  await expect(page.locator('[data-reused-field=missing]')).toHaveAttribute('placeholder','Not entered');
  await expect(page.locator('[data-input-source]')).toHaveCount(0);
  await page.screenshot({path:info.outputPath('supporting-fields.png'),fullPage:true});
  await page.evaluate(()=>document.documentElement.style.fontSize='200%');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});

for(const width of [320,390,768]) for(const dark of [false,true]) test(`review uses two columns and a full-width preview ${width} ${dark?'dark':'light'}`,async({page},info)=>{
  await boot(page,{width,dark});
  await section(page,'Review');
  const cards=page.locator('.review-card');
  const first=await cards.nth(0).boundingBox(),second=await cards.nth(1).boundingBox();
  expect(Math.abs(first.y-second.y)).toBeLessThan(1);
  expect(second.x).toBeGreaterThan(first.x+first.width);
  const container=await page.locator('.review-intro').boundingBox();
  const preview=await page.locator('#origination-preview').boundingBox();
  expect(Math.abs(preview.width-container.width)).toBeLessThan(2);
  expect(Math.abs(preview.x-container.x)).toBeLessThan(2);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.screenshot({path:info.outputPath('review.png'),fullPage:true,animations:'disabled'});
  await page.evaluate(()=>document.documentElement.style.fontSize='200%');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});

test('eye preview shows loading before a slow save, avoids double opening and ignores a closed request',async({page})=>{
  await boot(page,{delay:1200});
  await page.locator('[data-field=applicant_name]').fill('Synthetic changed name');
  let release;
  const pending = new Promise(resolve=>{release=resolve;});
  const requests=[];
  await page.route('**/packet/preview/',async route=>{
    requests.push(route.request().postDataJSON());
    await pending;
    await route.fulfill({contentType:'image/png',body:fs.readFileSync(path.join(root,'core/static/miniapp/jawabu-logo.png')),
      headers:{'X-Preview-Page-Count':'1'}});
  });
  // Dispatch synchronously: a 1.2s saved-data wait must not leave the screen inert.
  await page.locator('#origination-preview-early').dispatchEvent('click');
  await expect(page.locator('#document-preview-overlay')).toBeVisible({timeout:500});
  await expect(page.locator('#preview-page')).toHaveText('Saving changes…');
  await page.locator('#origination-preview-early').dispatchEvent('click');
  await expect.poll(()=>requests.length).toBe(1);
  await page.locator('#preview-close').click();
  release();
  await expect(page.locator('#document-preview-overlay')).toBeHidden();
  await expect(page.locator('#document-preview-image')).not.toHaveAttribute('src',/.+/);
});

test('bundle confirmation opens incomplete preview but never unlocks submission after refresh',async({page})=>{
  await boot(page);
  const requests=[];
  await page.route('**/packet/preview/',route=>{
    const body=route.request().postDataJSON();requests.push(body);
    if(!body.allow_incomplete) return route.fulfill({status:400,json:{ok:false,code:'incomplete_preview_confirmation_required',error:'Some details are missing.'}});
    return route.fulfill({contentType:'image/png',body:fs.readFileSync(path.join(root,'core/static/miniapp/jawabu-logo.png')),
      headers:{'X-Preview-Complete':'false','X-Preview-Page-Count':'1'}});
  });
  await page.getByRole('button',{name:'Preview application',exact:true}).click();
  await expect(page.locator('#document-preview-image')).toBeVisible();
  expect(requests.map(body=>body.allow_incomplete)).toEqual([false,true]);
  await page.getByRole('button',{name:'Refresh preview',exact:true}).click();
  await expect.poll(()=>requests.length).toBe(3);
  await page.getByRole('button',{name:'Close preview',exact:true}).click();
  await section(page,'Review');
  await expect(page.locator('.review-card').filter({hasText:'Guarantor form'})).toContainText('Preview required');
  await page.locator('#origination-submit').click();
  await expect(page.locator('#miniapp-shared-toast')).toContainText('Preview the filled document');
});

function identityFixture(app) {
  app.identity_copies=[{key:'borrower_id_copy',label:'Borrower ID copy',type:'document',identity_role:'borrower',identity_field:'applicant_id_number',subject_sha256:'synthetic-only'}];
}

test('signed invalidation requires a reason and keeps the retry key',async({page},info)=>{
  await boot(page,{configure:app=>{app.lifecycle={can_invalidate:true};}});
  await page.locator('#origination-remove').click();
  await page.locator('#origination-removal-confirm').click();
  await expect(page.locator('#origination-removal-error')).toContainText('Enter a reason');
  await page.locator('#origination-invalidation-reason').fill('Synthetic duplicate application');
  const requests=[];
  await page.route('**/invalidate/',route=>{requests.push(route.request().postDataJSON());return route.fulfill({status:503,json:{ok:false,error:'Synthetic unavailable'}});});
  await page.locator('#origination-removal-confirm').click();
  await expect(page.locator('#origination-removal-error')).toContainText('Synthetic unavailable');
  await page.locator('#origination-removal-confirm').click();
  await expect.poll(()=>requests.length).toBe(2);
  expect(requests[1].client_request_id).toBe(requests[0].client_request_id);
  expect(requests[0].reason).toBe('Synthetic duplicate application');
  await page.screenshot({path:info.outputPath('signed-invalidation-reason.png'),fullPage:true});
});

test('archived application shows reason and no editing or removal action',async({page})=>{
  await boot(page,{configure:app=>{app.status='invalidated';app.lifecycle={invalidation:{reason:'Synthetic duplicate'}};}});
  await expect(page.locator('.wizard-card')).toContainText('Invalidated and archived');
  await expect(page.locator('.wizard-card')).toContainText('Synthetic duplicate');
  await expect(page.locator('#origination-remove')).toHaveCount(0);
});

test('cancelling an incomplete bundle closes preview without a false error or readiness',async({page})=>{
  await boot(page);
  let requests=0;
  await page.route('**/packet/preview/',route=>{requests++;return route.fulfill({status:400,json:{
    ok:false,code:'incomplete_preview_confirmation_required',error:'Some required details are missing.'}});});
  await page.evaluate(()=>window.confirm=()=>false);
  await page.getByRole('button',{name:'Preview application',exact:true}).click();
  await expect(page.locator('#document-preview-overlay')).toBeHidden();
  expect(requests).toBe(1);
  await expect(page.locator('#miniapp-shared-toast')).not.toHaveClass(/is-visible/);
  await section(page,'Review');
  await expect(page.locator('.review-card').filter({hasText:'Guarantor form'})).toContainText('Preview required');
});

test('camera captures both sides, retakes and stops tracks without losing photos on failed upload',async({page},info)=>{
  await page.addInitScript(()=>{
    window.__cameraStreams=[];
    navigator.mediaDevices.getUserMedia=async()=>{
      const canvas=document.createElement('canvas');canvas.width=480;canvas.height=300;
      const context=canvas.getContext('2d');context.fillStyle='#dceee4';context.fillRect(0,0,480,300);
      context.fillStyle='#173d2d';context.font='32px sans-serif';context.fillText('Synthetic ID photo',40,140);
      const stream=canvas.captureStream(5);window.__cameraStreams.push(stream);return stream;
    };
  });
  await boot(page,{width:390,configure:identityFixture});
  await section(page,'Product requirements');
  await page.locator('[data-id-capture]').click();
  for(let i=0;i<2;i++) {
    await expect(page.locator('#evidence-camera-capture')).toBeEnabled();
    await page.locator('#evidence-camera-capture').click();
    await expect(page.locator('#identity-captured-photos img')).toHaveCount(i+1);
  }
  await page.locator('[data-id-retake="0"]').click();
  await page.locator('#evidence-camera-capture').click();
  await expect(page.locator('#identity-captured-photos img')).toHaveCount(2);
  await page.screenshot({path:info.outputPath('captured-front-back.png'),fullPage:true});
  const uploads=[];
  await page.route('**/requirements/borrower_id_copy/evidence/',route=>{
    uploads.push(route.request().postDataBuffer().toString());
    return route.fulfill({status:502,json:{ok:false,error:'Synthetic upload failed.'}});
  });
  await page.locator('#identity-camera-save').click();
  await expect(page.locator('#miniapp-shared-toast')).toContainText('Synthetic upload failed');
  await expect(page.locator('#identity-captured-photos img')).toHaveCount(2);
  await page.locator('#identity-camera-save').click();
  await expect.poll(()=>uploads.length).toBe(2);
  expect(uploads[0].match(/name="file"/g)).toHaveLength(2);
  const requestKey=body=>body.match(/name="request_id"\r\n\r\n([^\r]+)/)?.[1];
  expect(requestKey(uploads[1])).toBe(requestKey(uploads[0]));
  await page.getByRole('button',{name:'Close camera',exact:true}).click();
  expect(await page.evaluate(()=>__cameraStreams.every(stream=>stream.getTracks().every(track=>track.readyState==='ended')))).toBe(true);
});

test('camera denial leaves direct multiple-file upload available',async({page})=>{
  await page.addInitScript(()=>navigator.mediaDevices.getUserMedia=async()=>{throw new DOMException('Synthetic denial','NotAllowedError');});
  await boot(page,{configure:identityFixture});await section(page,'Product requirements');
  await page.locator('[data-id-capture]').click();
  await expect(page.locator('#miniapp-shared-toast')).toContainText('Camera access was unavailable');
  await expect(page.locator('[data-id-upload]')).toHaveAttribute('multiple','');
  await page.evaluate(()=>navigator.mediaDevices.getUserMedia=undefined);
  await page.locator('[data-id-capture]').click();
  await expect(page.locator('#miniapp-shared-toast')).toContainText('Use Choose file instead');
});

test('queue identity slots remain aligned with absent data and show the readable reference',async({page},info)=>{
  await boot(page,{configure:app=>{app.applicant_summary={name:'Synthetic applicant',phone:'',national_id:''};}});
  await page.locator('#origination-back').click();
  await expect(page.locator('.application-reference')).toHaveText('ORG-12');
  await expect(page.locator('.application-card-identifiers>span')).toHaveCount(2);
  await expect(page.locator('.application-card-identifiers')).toContainText('Not provided');
  await expect(page.locator('.application-card-identifiers a')).toHaveCount(0);
  await expect(page.locator('.application-officer')).toHaveCount(0);
  const labels=await page.locator('.application-card-identifiers>span>small').evaluateAll(nodes=>nodes.map(node=>node.getBoundingClientRect().y));
  expect(Math.abs(labels[0]-labels[1])).toBeLessThan(1);
  const separated=await page.locator('.application-card-identifiers>span').evaluateAll(nodes=>nodes.every(node=>
    node.querySelector('small').getBoundingClientRect().right+3<=node.querySelector('span').getBoundingClientRect().left));
  expect(separated).toBe(true);
  await page.screenshot({path:info.outputPath('missing-card-values.png'),fullPage:true});
});

for(const dark of [false,true]) test(`reference main page uses aligned clickable cards without repeated actions (${dark?'dark':'light'})`,async({page},info)=>{
  const {app,runtimeErrors}=await boot(page,{dark,width:dark?390:360});
  const entries=[clone(app),clone(app),clone(app)];
  entries.forEach((entry,index)=>{
    entry.id=`00000000-0000-4000-8000-00000000007${index}`;
    entry.display_reference=`ORG-${11+index}`;entry.product_name='Inua';entry.branch='Synthetic branch';
    entry.officer_name='Synthetic officer';entry.next_action='Complete application';
  });
  entries[0].applicant_summary.name='Synthetic Mary Wanjiku';
  entries[1].applicant_summary={name:'',national_id:'',phone:''};
  entries[2].status='correction_required';entries[2].status_label='Changes requested';
  entries[2].applicant_summary.name="Synthetic Wanjiku O'Kamau-Mwangi with a long applicant name";
  await page.route('**/applications/?*',route=>route.fulfill({json:{ok:true,applications:entries,
    tab_counts:{action:3,applications:12},status_options:[],pagination:{page:1,pages:1,total:3},
    capabilities:{can_create:true,can_review:true,user_id:1}}}));
  await page.route(`**/applications/${entries[0].id}/`,route=>route.fulfill({json:{ok:true,application:entries[0]}}));
  await page.locator('#origination-back').click();await page.locator('#origination-list-refresh').click();
  await expect(page.locator('.application-card')).toHaveCount(3);
  await expect(page.getByText('Complete application',{exact:true})).toHaveCount(0);
  await expect(page.locator('.application-card-state')).toHaveCount(0);
  await expect(page.locator('.application-officer')).toHaveCount(3);
  await expect(page.locator('.application-officer').first()).toContainText('Officer:');
  await expect(page.locator('.application-card').nth(1)).toContainText('Applicant details pending');
  await expect(page.locator('.application-card').nth(1).locator('.not-provided')).toHaveCount(2);
  for(const card of await page.locator('.application-card').all()) {
    const geometry=await card.evaluate(node=>{
      const cells=[...node.querySelectorAll('.application-card-identifiers>span')];
      return {labels:cells.map(cell=>cell.querySelector('small').getBoundingClientRect().y),
        values:cells.map(cell=>cell.querySelector('span').getBoundingClientRect().y)};
    });
    expect(Math.abs(geometry.labels[0]-geometry.labels[1])).toBeLessThan(1);
    expect(Math.abs(geometry.values[0]-geometry.values[1])).toBeLessThan(1);
    const inline=await card.locator('.application-card-identifiers>span').evaluateAll(cells=>cells.every(cell=>{
      const label=cell.querySelector('small').getBoundingClientRect(),value=cell.querySelector('span').getBoundingClientRect();
      return label.right<=value.left&&Math.abs(label.y+label.height/2-value.y-value.height/2)<1;
    }));
    expect(inline).toBe(true);
  }
  const phone=page.locator('.application-card').first().getByRole('link',{name:'Call 0700000001'});
  await expect(phone).toHaveAttribute('href','tel:+254700000001');
  expect((await phone.boundingBox()).height).toBeGreaterThanOrEqual(44);
  const search=await page.getByRole('searchbox',{name:'Search applications'}).boundingBox();
  const filter=await page.locator('#origination-open-filters').boundingBox();
  expect(Math.abs(search.y-filter.y)).toBeLessThan(1);expect(search.x+search.width).toBeLessThan(filter.x);
  for(const control of ['#origination-start','#origination-list-refresh','#origination-open-filters','.queue-tab.active'])
    expect((await page.locator(control).boundingBox()).height).toBeGreaterThanOrEqual(44);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  const cardEvidence=await page.locator('.application-card').evaluateAll(cards=>cards.map(card=>{
    const style=selector=>{const node=card.querySelector(selector),css=getComputedStyle(node);return {font:css.fontFamily,size:css.fontSize,weight:css.fontWeight,lineHeight:css.lineHeight};};
    const rect=card.getBoundingClientRect();
    return {height:rect.height,top:rect.top,bottom:rect.bottom,fullyVisible:rect.top>=0&&rect.bottom<=innerHeight,
      title:style('.application-card-header strong'),identity:style('[data-card-id-value]'),metadata:style('.application-card-meta'),status:style('.status-chip')};
  }));
  fs.writeFileSync(info.outputPath('card-layout-evidence.json'),JSON.stringify(cardEvidence,null,2));
  await page.screenshot({path:info.outputPath(`main-page-${dark?'dark':'light'}.png`),fullPage:true});
  await page.evaluate(()=>document.documentElement.style.fontSize='200%');
  await page.setViewportSize({width:320,height:844});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  const bounds=await page.locator('.list-toolbar button').evaluateAll(buttons=>buttons.map(button=>{
    const rect=button.getBoundingClientRect();return {left:rect.left,right:rect.right};
  }));
  expect(bounds.every(rect=>rect.left>=0&&rect.right<=320)).toBe(true);
  const largeAlignment=await page.locator('.application-card').first().evaluate(card=>{
    const cells=[...card.querySelectorAll('.application-card-identifiers>span')];
    const tabs=[...document.querySelectorAll('.queue-tab')];
    return {values:cells.map(cell=>cell.querySelector('span').getBoundingClientRect().y),
      tabsFit:tabs.every(tab=>tab.getBoundingClientRect().right<=innerWidth)};
  });
  // Enlarged text may stack the two labelled identifiers instead of squeezing them.
  expect(largeAlignment.values[1]).toBeGreaterThanOrEqual(largeAlignment.values[0]);
  expect(largeAlignment.tabsFit).toBe(true);
  await page.screenshot({path:info.outputPath(`main-page-large-text-${dark?'dark':'light'}.png`),fullPage:true});
  await page.evaluate(()=>document.documentElement.style.fontSize='');
  await page.setViewportSize({width:dark?390:360,height:844});
  await phone.click({noWaitAfter:true});await expect(page.locator('.application-card')).toHaveCount(3);
  await page.locator('.application-card-open').first().focus();await page.keyboard.press('Enter');
  await expect(page.locator('.editor-summary')).toBeVisible();expect(runtimeErrors).toEqual([]);
});

for(const width of [320,360,390,430]) for(const dark of [false,true]) test(`numbered compact queue fits more cards at ${width}px ${dark?'dark':'light'}`,async({page},info)=>{
  const {app,runtimeErrors}=await boot(page,{width,dark});
  const entries=Array.from({length:10},(_,index)=>({...clone(app),id:`00000000-0000-4000-8000-0000000001${String(index).padStart(2,'0')}`,
    product_name:'Inua',branch:'Embu',display_reference:`ORG-${index+1}`,officer_name:'Synthetic officer',
    applicant_summary:{name:`Synthetic applicant ${index+1}`,national_id:index===1?'':'00099001',phone:index===1?'':'0700000001'}}));
  await page.route('**/applications/?*',route=>route.fulfill({json:{ok:true,applications:entries,
    tab_counts:{action:10,applications:10},pagination:{page:1,page_size:10,pages:1,total:10},
    capabilities:{can_create:true,can_review:true,user_id:1}}}));
  await page.locator('#origination-back').click();await page.locator('#origination-list-refresh').click();
  await expect(page.locator('.application-card-number')).toHaveText(entries.map((_,index)=>`#${index+1}`));
  await expect(page.locator('.application-reference').first()).toHaveText('ORG-1');
  await expect(page.locator('.application-card-footer')).toHaveCount(0);
  await expect(page.locator('.application-officer')).toHaveCount(10);
  const geometry=await page.locator('.application-card').evaluateAll(cards=>cards.map(card=>{
    const rect=card.getBoundingClientRect();return {height:rect.height,fullyVisible:rect.top>=0&&rect.bottom<=innerHeight};
  }));
  expect(geometry.every(card=>card.height<=120)).toBe(true);
  expect(geometry.filter(card=>card.fullyVisible).length).toBeGreaterThanOrEqual(4);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  fs.writeFileSync(info.outputPath('density.json'),JSON.stringify({width,dark,cards:geometry},null,2));
  await page.screenshot({path:info.outputPath(`compact-queue-${width}-${dark?'dark':'light'}.png`)});
  expect(runtimeErrors).toEqual([]);
});

test('queue numbering follows pagination, survives refresh and resets with search',async({page})=>{
  const {app,runtimeErrors}=await boot(page);
  const queries=[];
  await page.route('**/applications/?*',route=>{
    const params=new URL(route.request().url()).searchParams;
    const pageNumber=Number(params.get('page')||1),query=params.get('q')||'';
    queries.push({page:pageNumber,query});
    const entries=query==='none'?[]:Array.from({length:2},(_,index)=>({...clone(app),
      id:`00000000-0000-4000-8000-0000000002${pageNumber}${index}`,display_reference:`ORG-${pageNumber*10+index}`}));
    return route.fulfill({json:{ok:true,applications:entries,tab_counts:{action:12,applications:12},
      pagination:{page:pageNumber,page_size:10,pages:2,total:12},capabilities:{can_create:true,user_id:1}}});
  });
  await page.locator('#origination-back').click();await page.locator('#origination-list-refresh').click();
  await expect(page.locator('.application-card-number')).toHaveText(['#1','#2']);
  await page.locator('#origination-page-next').click();
  await expect(page.locator('.application-card-number')).toHaveText(['#11','#12']);
  await page.locator('#origination-list-refresh').click();
  await expect(page.locator('.application-card-number')).toHaveText(['#11','#12']);
  await page.getByRole('searchbox',{name:'Search applications'}).fill('Synthetic');
  await expect(page.locator('.application-card-number')).toHaveText(['#1','#2']);
  expect(queries.at(-1)).toEqual({page:1,query:'Synthetic'});
  await page.getByRole('searchbox',{name:'Search applications'}).fill('none');
  await expect(page.locator('.application-card-number')).toHaveCount(0);
  await expect(page.getByText('No matching applications',{exact:true})).toBeVisible();
  expect(runtimeErrors).toEqual([]);
});

test('card typography matches TAT and Complaint source styles without changing form scale',async({page},info)=>{
  const {runtimeErrors}=await boot(page);
  const formStyle=await page.locator('[data-field=applicant_name]').evaluate(input=>{
    const css=getComputedStyle(input);return {font:css.fontFamily,size:css.fontSize,height:input.getBoundingClientRect().height};
  });
  await page.locator('#origination-back').click();
  const actual=await page.locator('.application-card').evaluate(card=>{
    const profile=selector=>{const css=getComputedStyle(card.querySelector(selector));return {font:css.fontFamily,size:css.fontSize,weight:css.fontWeight};};
    return {title:profile('.application-card-title strong'),identity:profile('[data-card-id-value]'),
      metadata:profile('.application-card-meta'),number:profile('.application-card-number')};
  });
  const references={};
  for(const name of ['tat_tracker','complaint_cases']) {
    const template=fs.readFileSync(path.join(root,`core/templates/${name}/app.html`),'utf8');
    const links=(template.match(/<link\b[^>]+>/g)||[]).join('\n').replace(/{% static '([^']+)' %}/g,'/static/$1');
    const probe=name==='tat_tracker'
      ? '<main class="tat-app"><div class="case-card"><div class="case-title"><span class="case-number">#1</span><strong class="case-name">Synthetic applicant</strong></div><div class="case-details">Training branch</div><div class="case-identifiers"><span class="case-identifier"><small>ID</small><span class="case-identifier-value">00099001</span></span></div></div></main>'
      : '<main class="complaint-app"><div class="case-row"><h2>Synthetic applicant</h2><span class="case-subtitle">Training branch</span></div></main>';
    await page.route(`**/type-reference-${name}/`,route=>route.fulfill({contentType:'text/html',
      body:`<!doctype html><html><head>${links}</head><body class="${name==='complaint_cases'?'complaint-cases-app':''}">${probe}</body></html>`}));
    await page.evaluate(name=>{const frame=document.createElement('iframe');frame.name=name;frame.hidden=true;frame.src=`/type-reference-${name}/`;document.body.append(frame);},name);
    await expect.poll(()=>Boolean(page.frame({name}))).toBe(true);
    const frame=page.frame({name});
    await frame.locator(name==='tat_tracker'?'.case-name':'.case-row h2').waitFor({state:'attached'});
    references[name]=await frame.evaluate(async name=>{
      await document.fonts.load('13px "Plus Jakarta Sans"');
      const profile=selector=>{const css=getComputedStyle(document.querySelector(selector));return {font:css.fontFamily,size:css.fontSize,weight:css.fontWeight};};
      return name==='tat_tracker'
        ? {title:profile('.case-name'),identity:profile('.case-identifier-value'),metadata:profile('.case-details'),number:profile('.case-number')}
        : {title:profile('.case-row h2')};
    },name);
  }
  expect(actual.title.font).toBe(references.tat_tracker.title.font);
  expect(actual.title.font).toBe(references.complaint_cases.title.font);
  for(const role of ['title','identity','metadata','number']) expect(actual[role].size).toBe(references.tat_tracker[role].size);
  expect(actual.title.weight).toBe(references.tat_tracker.title.weight);
  fs.writeFileSync(info.outputPath('typography-comparison.json'),JSON.stringify({actual,references,formStyle},null,2));
  await page.locator('.application-card-open').click();
  const after=await page.locator('[data-field=applicant_name]').evaluate(input=>{
    const css=getComputedStyle(input);return {font:css.fontFamily,size:css.fontSize,height:input.getBoundingClientRect().height};
  });
  expect(after).toEqual(formStyle);expect(runtimeErrors).toEqual([]);
});

test('phone check belongs to its Applicant field, not the header',async({page},info)=>{
  await boot(page,{configure:app=>{
    app.phone_id_checks={allowed:true,enabled:true,environment:'sandbox',revision:1,targets:[{
      target:'primary',field_key:'applicant_phone',id_field_key:'applicant_id_number',status:'not_matched',
      checked_at:'2026-10-21T10:00:00Z',freshness:'current',can_check:true,
    }]};
  }});
  const target=page.locator('[data-phone-id-target=primary]');
  await expect(page.locator('.editor-summary [data-phone-id-target]')).toHaveCount(0);
  await expect(page.locator('[data-field-wrap=applicant_phone] [data-phone-id-target=primary]')).toBeVisible();
  await expect(target).toContainText('Registration does not match');
  await expect(target.getByRole('button',{name:/Check primary Applicant phone/})).toBeVisible();
  await section(page,'Guarantor form');
  await expect(page.locator('[data-phone-id-target]')).toHaveCount(0);
  await page.screenshot({path:info.outputPath('phone-check-details.png'),fullPage:true});
});

test('cancelled pending camera permission releases the eventual stream',async({page})=>{
  await page.addInitScript(()=>{
    window.__cameraStopped=0;
    navigator.mediaDevices.getUserMedia=()=>new Promise(resolve=>{
      window.__releaseCamera=()=>resolve({getTracks:()=>[{stop:()=>window.__cameraStopped++}]});
    });
  });
  await boot(page,{configure:identityFixture});await section(page,'Product requirements');
  await page.locator('[data-id-capture]').click();
  await page.getByRole('button',{name:'Close camera',exact:true}).click();
  await page.evaluate(()=>__releaseCamera());
  await expect.poll(()=>page.evaluate(()=>__cameraStopped)).toBe(1);
  await expect(page.locator('.camera-capture-dialog')).toHaveCount(0);
  await expect(page.locator('[data-id-capture]')).toBeVisible();
});
