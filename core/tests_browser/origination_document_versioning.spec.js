'use strict';
const fs = require('node:fs');
const path = require('node:path');
const {execFileSync} = require('node:child_process');
const {test, expect} = require('playwright/test');
const root = path.resolve(__dirname, '../..');
function render(mode) {
  const file = mode === 'detail' ? 'change_form.html' : 'calibrate.html';
  const html = fs.readFileSync(path.join(root, 'origination/templates/admin/core/originationdocumenttemplate', file), 'utf8');
  const fragment = (mode === 'detail'
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
document=N(pk='00000000-0000-0000-0000-000000000001',name='Synthetic published legacy Main LAF',status='active',product_definition_id='00000000-0000-0000-0000-000000000002')
context=dict(request=N(user=N(is_superuser=True)),original=document,template_record=document,origination_create_editable_template_url='/admin/synthetic/create-editable-version/',calibration_create_editable_url='/admin/synthetic/create-editable-version/',calibration_back_url='/admin/synthetic/')
print(engines['django'].from_string(sys.stdin.read()).render(context))
`], {cwd: root, input: fragment, encoding: 'utf8', env: {...process.env,
    DATABASE_URL: 'sqlite:///:memory:', DJANGO_SECRET_KEY: 'synthetic-browser-only-'.padEnd(64, 'x')},
  });
}
for (const mode of ['detail', 'alignment']) {
  test(`published legacy document ${mode} has a usable version action`, async ({page}, testInfo) => {
    await page.route(/^https?:\/\//, route => route.abort());
    await page.setContent(render(mode));
    await page.addStyleTag({content: 'body{font:14px/1.4 Arial,sans-serif;margin:8px;background:#f5f7fa}button{font:inherit}'});
    await page.addStyleTag({path: path.join(root, 'origination/static/admin', mode === 'detail' ? 'origination_product_builder.css' : 'origination_calibration.css')});
    const action = page.getByRole('button', {name: mode === 'detail' ? 'Create editable version' : 'Edit new version', exact: true});
    await expect(action).toBeVisible();
    await expect(action.locator('..')).toHaveAttribute('method', 'post');
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
