'use strict';
const fs = require('node:fs');
const path = require('node:path');
const {test, expect} = require('playwright/test');
const root = path.resolve(__dirname, '../..');
const shell = fs.readFileSync(path.join(root, 'origination/templates/loan_origination/app.html'), 'utf8')
  .replace(/{% static '([^']+)' %}/g, '/static/$1').replace(/{%[\s\S]*?%}/g, '')
  .replace(/<script[\s\S]*?<\/script>/g, '').replace(/<link[^>]+>/g, '');
const clone = value => JSON.parse(JSON.stringify(value));

async function boot(page, {linked=false, failure=false, dark=false, width=360, delay=0}={}) {
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
    reference_number:'ORG-SYNTHETIC-FORMS',product_name:'Synthetic loan',branch:'Synthetic branch',
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
  const writes=[]; const previews=[]; const previewBodies=[];
  let fail=failure;
  await page.route('http://127.0.0.1:8161/**',async route=>{
    const request=route.request(),url=new URL(request.url());
    if(url.pathname==='/') return route.fulfill({contentType:'text/html',body:shell});
    if(url.pathname.endsWith('/products/')) return route.fulfill({json:{ok:true,products:[],branches:[],capabilities:{can_create:true,user_id:1}}});
    if(url.pathname.endsWith('/applications/')) return route.fulfill({json:{ok:true,applications:[app],tab_counts:{action:1,applications:1},status_options:[],pagination:{page:1,pages:1,total:1},capabilities:{can_create:true,user_id:1}}});
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
  const reopen = async () => {
  await page.goto('http://127.0.0.1:8161/');
  await page.evaluate(({dark})=>{
    window.__copied=[];Object.defineProperty(navigator,'clipboard',{value:{writeText:async value=>window.__copied.push(value)},configurable:true});
    window.confirm=()=>true;
    window.Telegram={WebApp:{initData:'synthetic-only',ready(){},expand(){},onEvent(){},BackButton:{show(){},hide(){},onClick(){},offClick(){}}}};
    if(dark){document.documentElement.dataset.telegramTheme='dark';document.documentElement.dataset.miniappColorScheme='dark';
      for(const [key,value] of Object.entries({'bg-color':'#17201e','secondary-bg-color':'#111816','text-color':'#f4f7f5','hint-color':'#a7b5af'})) document.documentElement.style.setProperty(`--tg-theme-${key}`,value);}
  },{dark});
  for(const file of ['core/static/miniapp/base.css','core/static/miniapp/workflow_standard.css',
    'origination/static/miniapp/loan_origination.css','origination/static/miniapp/origination_compact.css'])
    await page.addStyleTag({content:fs.readFileSync(path.join(root,file),'utf8').replace(/^@import[^\r\n]*;\s*$/gm,'')});
  for(const file of ['core/static/miniapp/utils.js','origination/static/miniapp/origination_field_rules.js','origination/static/miniapp/loan_origination.js'])
    await page.addScriptTag({path:path.join(root,file)});
  await page.locator('.application-card').click();
  };
  await reopen();
  return {app,writes,previews,previewBodies,reopen,retry:()=>{fail=false;}};
}

async function section(page,label) {
  await page.locator('#origination-section-picker').click();
  await page.locator('[data-section-index]').filter({hasText:label}).click();
  await expect(page.locator('#origination-section-picker strong')).toHaveText(label);
}

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
  await expect(page.locator('.supporting-shared-values')).toContainText(app.applicant_summary.name);
  await expect(page.locator('.supporting-shared-values')).not.toContainText('Stale document name');
  await page.locator('[data-document-field=guarantee_notes]').fill('Synthetic undertaking');
  await page.locator('[data-document-field=guaranteed_amount]').fill('25000');
  await page.getByRole('button',{name:'Preview document',exact:true}).click();
  await expect.poll(()=>previews.length).toBe(1);
  expect(previews[0]).toContain('/documents/guarantee/');
  expect(writes.at(-1).payload).toMatchObject({guarantee_notes:'Synthetic undertaking',guaranteed_amount:'25000'});
  await page.locator('#preview-close').click();
  await section(page,'Confirmation');
  await expect(page.getByRole('button',{name:'Preview document',exact:true})).toBeVisible();
  await expect(page.locator('.supporting-shared-values')).toContainText(app.applicant_summary.name);
  await page.screenshot({path:info.outputPath('autofilled-document.png'),fullPage:true});
});

for(const dark of [false,true]) test(`header contacts dial and copy without reference clutter (${dark?'dark':'light'})`,async({page},info)=>{
  await boot(page,{dark,width:dark?390:360});
  await expect(page.locator('.editor-contacts a[href="tel:+254700000001"]')).toBeVisible();
  await page.screenshot({path:info.outputPath(`application-header-${dark?'dark':'light'}.png`),fullPage:true});
  await page.getByRole('button',{name:'Copy National ID',exact:true}).click();
  expect(await page.evaluate(()=>window.__copied)).toEqual(['00099001']);
  await expect(page.locator('.editor-identity')).not.toContainText('ORG-SYNTHETIC');
  await expect(page.getByText('Applicant contacts',{exact:true})).toHaveCount(0);
  await expect(page.getByRole('button',{name:'Manage documents',exact:true})).toHaveCount(1);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await section(page,'Guarantor form');
  await page.screenshot({path:info.outputPath(`supporting-document-${dark?'dark':'light'}.png`),fullPage:true});
});

test('reused values jump to their owner, then refresh after saving',async({page})=>{
  const {app}=await boot(page);
  await section(page,'Guarantor form');
  await page.locator('[data-document-field=guarantee_notes]').fill('Keep this document note');
  await page.getByRole('button',{name:'Edit applicant name in Applicant',exact:true}).click();
  await page.locator('[data-field=applicant_name]').fill('Synthetic updated applicant');
  await section(page,'Guarantor form');
  await expect(page.locator('.supporting-shared-values')).toContainText('Synthetic updated applicant');
  await expect(page.locator('[data-document-field=guarantee_notes]')).toHaveValue('Keep this document note');
  expect(app.document_packet.documents[0].field_payload.guarantee_notes).toBe('Keep this document note');
});

test('failed document save prevents navigation and keeps typed values for retry',async({page},info)=>{
  const {app,retry}=await boot(page,{failure:true});
  await section(page,'Guarantor form');
  await page.locator('[data-document-field=guarantee_notes]').fill('Keep after failure');
  await page.locator('#section-next').click();
  await expect(page.locator('#origination-toast')).toContainText('Synthetic save failed');
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
  await expect(page.locator('#origination-toast')).toContainText('Could not save the cleared guarantor');
  expect(app.form_payload.guarantor_2_name).toBe('Synthetic spouse');
  retry();await page.getByRole('button',{name:'Clear Guarantor 2',exact:true}).click();
  await expect.poll(()=>app.form_payload.guarantor_2_name).toBe('');
});

test('clipboard failure is visible without a false success message',async({page})=>{
  await boot(page);
  await page.evaluate(()=>navigator.clipboard.writeText=async()=>{throw new Error('Synthetic denial');});
  await page.getByRole('button',{name:'Copy National ID',exact:true}).click();
  await expect(page.locator('#origination-toast')).toContainText('Could not copy');
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
  await expect(page.locator('.supporting-shared-values')).toContainText('25000');
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
