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
labels = [('identity','Product and availability'),('terms','Financial terms'),('form','Form and signers'),('publish','Review and publish')]
rows = [dict(key=k,label=v,status='stale' if k=='terms' else 'complete',status_label='Review changes' if k=='terms' else 'Complete',detail='Review the current values before publishing.',url='/setup/'+k+'/') for k,v in labels]
context = dict(definition=definition,steps=rows,review_rows=rows,step_key='terms' if mode=='legacy' else 'publish',step_label='Financial terms' if mode=='legacy' else 'Review and publish',terms_readonly=mode=='legacy',terms_summary=terms,published_readonly=False,document_catalogue=dict(ready=False,reasons=['No compatible Main LAF is available.']),expected_tokens='{}',request_id='synthetic-request',dashboard_url='/setup/',advanced_url='/advanced/')
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

for (const mode of ['review','legacy','conflict']) {
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
      await expect(page.getByRole('link',{name:'Continue to form'})).toHaveAttribute('href',/\/form\/$/);
    } else {
      await expect(page.getByRole('button',{name:'Publish product'})).toBeEnabled();
      await expect(page.locator('.osw-readiness')).toContainText('Review changes');
      await expect(page.getByText('You can publish this profile', {exact:false})).toBeVisible();
    }
    if(mode==='conflict') {
      await page.getByText('Keep a copy of my submitted values').click();
      await expect(page.locator('pre')).toContainText('12');
    }
    if(mode==='review') {
      await expect(page.getByText('Publishing replaces the earlier version', {exact:false})).toBeVisible();
      await expect(page.getByText('Its history and existing applications are kept.', {exact:false})).toBeVisible();
    }
    for(const width of [390,1280]) {
      await page.setViewportSize({width,height:900});
      expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
      await page.screenshot({path:testInfo.outputPath(`guided-${mode}-${width}.png`),fullPage:true});
    }
  });
}
