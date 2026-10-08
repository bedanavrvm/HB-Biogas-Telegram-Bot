'use strict';
const fs = require('node:fs');
const path = require('node:path');
const {execFileSync} = require('node:child_process');
const {test, expect} = require('playwright/test');
const root = path.resolve(__dirname, '../..');
const template = fs.readFileSync(path.join(root, 'origination/templates/admin/core/origination_setup/workspace.html'), 'utf8');
const fragment = '{% load static %}' + template.slice(template.indexOf('<main'), template.indexOf('</main>') + 7);
const renderer = `
import os, sys
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()
from types import SimpleNamespace as N
from django.template import engines
mode = sys.argv[1]
terms = N(version=1,min_amount='1000',max_amount='50000',min_tenor=1,max_tenor=12,interest_rate='10%',get_tenor_unit_display='Months',get_interest_method_display='Flat')
definition = N(pk='00000000-0000-0000-0000-000000000001',name='Synthetic Loan',product_key='synthetic',version=1,product_version=terms)
labels = [('identity','Product'),('terms','Terms'),('documents','Documents'),('publish','Preview & enable')]
rows = [dict(key=k,label=v,status='stale' if k=='terms' else 'complete',status_label='Review changes' if k=='terms' else 'Complete',detail='Review the current values before publishing.',url='/setup/'+k+'/') for k,v in labels]
context = dict(definition=definition,steps=rows,review_rows=rows,step_key='terms' if mode=='legacy' else 'publish',step_label='Terms' if mode=='legacy' else 'Preview & enable',terms_readonly=mode=='legacy',terms_summary=terms,published_readonly=False,can_enable=mode not in ['incomplete'],document_errors=['Choose a Main LAF.'] if mode=='incomplete' else [],documents_url='/setup/documents/',expected_tokens='{}',request_id='synthetic-request',dashboard_url='/setup/',advanced_url='/advanced/',signer_labels=['Applicant','Officer','Branch Manager'],branches=[N(branch=N(name='Sample Branch'))],applicant_fields=[dict(label='Applicant name',type='text',required=True)])
if mode=='documents':
    from django import forms
    selection=forms.Form()
    selection.fields['templates']=forms.MultipleChoiceField(choices=[('1','Reviewed Jawabu LAF - Main LAF'),('2','Supporting declaration with a long readable name')],widget=forms.CheckboxSelectMultiple,required=False)
    upload=forms.Form()
    upload.fields['name']=forms.CharField(label='Document name')
    upload.fields['pdf_file']=forms.FileField(label='Blank PDF')
    options=[N(pk='00000000-0000-0000-0000-000000000002',name='Reviewed Jawabu LAF',document_role='primary',version=1,get_document_role_display='Main LAF'),N(pk='00000000-0000-0000-0000-000000000003',name='Supporting declaration with a long readable name',document_role='supporting',version=1,get_document_role_display='Supporting document')]
    context.update(step_key='documents',step_label='Documents',form=selection,upload_form=upload,replacement_options=options,documents=[dict(template=N(pk=options[0].pk,name='Reviewed Jawabu LAF',document_role='primary',version=1,status='active',get_document_role_display='Main LAF'),url='/align/')])
if mode=='conflict':context['conflict']=dict(changed=['Financial terms'],submitted={'interest_rate':'12'})
if mode=='review':context['same_day_replacement']=True
print(engines['django'].from_string(sys.stdin.read()).render(context))
`;

function rendered(mode) {
  const python = path.join(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
  return execFileSync(fs.existsSync(python) ? python : 'python', ['-c',renderer,mode], {
    cwd:root,input:fragment,encoding:'utf8',env:{...process.env,DATABASE_URL:'sqlite:///:memory:',
      DJANGO_SECRET_KEY:'synthetic-browser-fixture-only-'.padEnd(64,'x')},
  });
}

for (const mode of ['review','legacy','conflict','incomplete','documents']) {
  test(`guided setup ${mode} is navigable and compact`, async({page},testInfo)=>{
    await page.route(/^https?:\/\//, route=>route.abort());
    await page.setContent(rendered(mode));
    await page.addStyleTag({content:'body{font:14px/1.4 Arial,sans-serif;margin:0;background:#f5f7fa}button,input{font:inherit}'});
    for(const name of ['origination_setup.css','origination_setup_layout.css']) {
      await page.addStyleTag({path:path.join(root,'origination/static/admin',name)});
    }
    await expect(page.locator('.osw-stepper a')).toHaveCount(4);
    await expect(page.locator('.osw-stepper')).not.toContainText('Publish terms');
    await expect(page.locator('.osw-hash')).toHaveCount(0);
    if(mode==='legacy') {
      await expect(page.getByRole('button',{name:'Create editable successor'})).toBeVisible();
      await expect(page.getByRole('link',{name:'Continue to documents'})).toHaveAttribute('href',/\/documents\/$/);
    } else if(mode==='documents') {
      await page.getByText('Add document',{exact:true}).click();
      await expect(page.getByRole('button',{name:'Add & continue'})).toBeVisible();
      await expect(page.getByRole('textbox',{name:'Document name'})).not.toBeVisible();
      await page.getByText('Upload a new document',{exact:true}).click();
      await expect(page.getByRole('textbox',{name:'Document name'})).toBeVisible();
    } else {
      if(mode==='incomplete') await expect(page.getByRole('button',{name:'Enable applications'})).toBeDisabled();
      else await expect(page.getByRole('button',{name:'Enable applications'})).toBeEnabled();
      await expect(page.locator('.osw-readiness .stale')).toContainText('Terms');
      await expect(page.locator('.osw-readiness .complete')).toHaveCount(0);
      await expect(page.getByText('You can publish this profile', {exact:false})).toHaveCount(0);
    }
    if(mode==='conflict') {
      await page.getByText('Keep a copy of my submitted values').click();
      await expect(page.locator('pre')).toContainText('12');
    }
    if(mode==='review') {
      await expect(page.getByText('Publishing replaces the earlier version', {exact:false})).toBeVisible();
      await expect(page.getByText('Its history and existing applications are kept.', {exact:false})).toBeVisible();
    }
    for(const width of [320,390,1280]) {
      await page.setViewportSize({width,height:900});
      expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
      await page.screenshot({path:testInfo.outputPath(`guided-${mode}-${width}.png`),fullPage:true});
    }
  });
}
