'use strict';
const fs = require('node:fs');
const path = require('node:path');
const {execFileSync} = require('node:child_process');
const {test, expect} = require('playwright/test');
const root = path.resolve(__dirname, '../..');
function render(mode) {
  const file = mode === 'detail' ? 'change_form.html' : 'calibrate.html';
  const html = fs.readFileSync(path.join(root, 'origination/templates/admin/core/originationdocumenttemplate', file), 'utf8');
  const fragment = (mode === 'editor' ? html.slice(html.indexOf('<div id="calibration-app"'), html.indexOf('<script src=')) : mode === 'detail'
    ? html.slice(html.indexOf('{% block form_before %}'), html.indexOf('{% block field_sets %}'))
    : '<div id="calibration-app">' + html.slice(html.indexOf('<header class="calibration-topbar'), html.indexOf('</header>') + 9) + '</div>')
    .replace('{% block form_before %}', '').replace('{% endblock %}', '').replaceAll('{{ block.super }}', '');
  const python = path.join(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
  return execFileSync(python, ['-c', `
import os, sys
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django
django.setup()
from types import SimpleNamespace as N
from django.template import engines
document=N(pk='00000000-0000-0000-0000-000000000001',name='Synthetic Main LAF',status='${mode === 'editor' ? 'ready' : 'active'}',page_count=1,product_definition_id=None)
context=dict(request=N(user=N(is_superuser=True)),original=document,template_record=document,origination_create_editable_template_url='/admin/synthetic/create-editable-version/',calibration_create_editable_url='/admin/synthetic/create-editable-version/',editor_edit_url='/admin/synthetic/edit-document/',calibration_back_url='/admin/synthetic/')
print(engines['django'].from_string(sys.stdin.read()).render(context))
`], {cwd: root, input: fragment, encoding: 'utf8', env: {...process.env,
    DATABASE_URL: 'sqlite:///:memory:', DJANGO_SECRET_KEY: 'synthetic-browser-only-'.padEnd(64, 'x'), PYTHONUTF8:'1'},
  });
}

test('Document editor loads and saves input rules without moving the PDF fields', async ({page}, info) => {
  const markup = '<!doctype html><meta charset="utf-8">' + render('editor');
  const field = {id:'00000000-0000-0000-0000-000000000002',key:'synthetic_email',label:'Email',
    type:'text',attached:true,required:true,source_type:'user_input',validation:{format:'email',max_length:40}};
  const configuration = {document_type:'synthetic',version:1,
    field_overlay_manifest:{fields:{email:{context_key:field.key,page_number:1,box:{x:50,y:50,width:180,height:20}}}},
    signature_overlay_manifest:{slots:{}}, sample_context:{synthetic_email:'synthetic@example.test'}};
  let saved;
  await page.route('http://127.0.0.1:8124/**', route => {
    const url = new URL(route.request().url());
    if (url.pathname === '/') return route.fulfill({contentType:'text/html',body:markup});
    if (url.pathname.endsWith('/calibration-state/')) return route.fulfill({json:{configuration,revision:1,schema_revision:1,
      page_sizes:[{page_number:1,width:595,height:842}], context_keys:[field],form_sections:[{key:'applicant',label:'Applicant'}],
      details:{name:'Synthetic Main LAF',shared_values:false},readiness:{tasks:[],can_publish:false}}});
    if (url.pathname.endsWith('/calibration-page/')) return route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="595" height="842"><rect width="100%" height="100%" fill="white"/></svg>'});
    if (url.pathname.endsWith('/editor-readiness/')) return route.fulfill({json:{readiness:{tasks:[],can_publish:false},shared_review:{}}});
    if (url.pathname.endsWith('/calibration-save/')) return route.fulfill({json:{revision:2,
      configuration:route.request().postDataJSON().configuration,readiness:{tasks:[],can_publish:false}}});
    if (url.pathname.endsWith('/calibration-field/')) {
      saved = route.request().postDataJSON();
      Object.assign(field, saved.presentation);
      return route.fulfill({json:{field,context_keys:[field],schema_revision:2,form_sections:[{key:'applicant',label:'Applicant'}]}});
    }
    return route.abort();
  });
  await page.goto('http://127.0.0.1:8124/');
  await page.addStyleTag({content:'body{font:14px/1.4 Arial,sans-serif;margin:0;background:#f5f7fa}button,input{font:inherit}'});
  await page.addStyleTag({path:path.join(root,'origination/static/admin/origination_calibration.css')});
  await page.addScriptTag({path:path.join(root,'origination/static/admin/origination_calibration.js')});
  await expect(page.locator('[data-nav-action=edit]')).toHaveCount(1);
  await page.locator('[data-nav-action=edit]').click();
  await page.locator('#cal-field-rules summary').first().click();
  await expect(page.locator('#cal-rule-format')).toHaveValue('email');
  await expect(page.locator('#cal-rule-max-length')).toHaveValue('40');
  await page.locator('#cal-field-required').uncheck();
  await page.locator('#cal-rule-max-length').fill('');
  for (const width of [320,430,1280]) {
    await page.setViewportSize({width,height:900});
    expect(await page.locator('#calibration-field-dialog').evaluate(node => node.scrollWidth <= node.clientWidth)).toBe(true);
    await page.screenshot({path:info.outputPath(`field-editor-${width}.png`)});
  }
  await page.getByRole('button',{name:'Save field',exact:true}).click();
  await expect(page.locator('#calibration-field-dialog')).not.toBeVisible();
  expect(saved.presentation.required).toBe(false);
  expect(saved.presentation.validation).toEqual({format:'email'});
  expect(configuration.field_overlay_manifest.fields.email.box).toEqual({x:50,y:50,width:180,height:20});
});
for (const mode of ['detail', 'alignment']) {
  test(`published legacy document ${mode} has a usable version action`, async ({page}, testInfo) => {
    await page.route(/^https?:\/\//, route => route.abort());
    await page.setContent(render(mode));
    await page.addStyleTag({content: 'body{font:14px/1.4 Arial,sans-serif;margin:8px;background:#f5f7fa}button{font:inherit}'});
    await page.addStyleTag({path: path.join(root, 'origination/static/admin', mode === 'detail' ? 'origination_product_builder.css' : 'origination_calibration.css')});
    const action = mode === 'detail'
      ? page.getByRole('button', {name: 'Create editable version', exact: true})
      : page.getByRole('link', {name: 'Edit', exact: true});
    await expect(action).toBeVisible();
    if (mode === 'detail') await expect(action.locator('..')).toHaveAttribute('method', 'post');
    else await expect(action).toHaveAttribute('href', '/admin/synthetic/edit-document/');
    if (mode === 'alignment') {
      await page.locator('#calibration-publish').evaluate(button => {button.disabled = true;});
      await expect(action).toBeEnabled();
      await expect(page.getByText('Published', {exact: true})).toBeVisible();
      await expect(page.locator('#calibration-save')).toBeHidden();
      await expect(page.locator('#calibration-publish')).toBeHidden();
    }
    for (const width of [390, 1280]) {
      await page.setViewportSize({width, height: 900});
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await page.screenshot({path: testInfo.outputPath(`legacy-${mode}-${width}.png`), fullPage: true});
    }
  });
}
