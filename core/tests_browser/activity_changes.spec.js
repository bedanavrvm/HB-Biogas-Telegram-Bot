'use strict';
const path = require('node:path');
const fs = require('node:fs');
const {test, expect} = require('playwright/test');
const asset = name => path.resolve(__dirname, '../static/miniapp', name);

for (const app of ['portal', 'complaint_cases', 'tat_tracker']) {
  for (const width of [320, 390, 430, 1280]) {
    test(`${app} activity comparisons fit ${width}px`, async ({page}, info) => {
      await page.setViewportSize({width,height:844});
      const cls = app === 'portal' ? 'workflow-standard portal-app' : app === 'complaint_cases' ? 'complaint-cases-app' : 'workflow-standard tat-app';
      await page.setContent(`<body class="${cls}"><main style="max-width:650px;margin:12px auto;padding:12px"><article id="activity"><strong>Case updated</strong><small style="display:block">Training officer · 02 Oct 2026 10:00</small></article></main></body>`);
      for (const name of ['base.css', ...(app === 'portal' ? ['workflow_standard.css','portal.css'] : app === 'complaint_cases' ? ['complaint_cases.css'] : ['workflow_standard.css','tat_tracker.css']), 'activity_changes.css']) await page.addStyleTag({path:asset(name)});
      await page.addScriptTag({path:asset('activity_changes.js')});
      await page.evaluate(() => MiniAppActivityChanges.append(document.getElementById('activity'), [
        {label:'County',old_value:'Kiambu',new_value:'Nakuru',previous_recorded:true},
        {label:'Amount',old_value:2000,new_value:0,previous_recorded:true},
        {label:'Comment',old_value:'Earlier note',new_value:'Updated explanation '.repeat(24)+'<img src=x onerror=alert(1)>',previous_recorded:true},
        {label:'Phone',new_value:'0712345678',previous_recorded:false},
        {label:'Installed on',old_value:null,new_value:'2026-10-02',previous_recorded:true},
      ]));
      await expect(page.locator('.activity-change').first()).toContainText('Kiambu → Nakuru');
      await expect(page.locator('.activity-change').nth(1)).toContainText('2000 → 0');
      await expect(page.locator('.activity-change')).toHaveCount(5);
      await expect(page.locator('.activity-change').nth(2)).toContainText('Earlier note → Updated explanation');
      await expect(page.locator('.activity-more')).toHaveCount(1);
      await expect(page.locator('.activity-more summary').first()).toHaveText('More changes (3)');
      await page.screenshot({path:info.outputPath(`${app}-${width}-compact.png`),animations:'disabled'});
      await page.locator('.activity-more summary').first().click();
      await page.locator('.activity-long-text summary').click();
      await expect(page.locator('#activity img')).toHaveCount(0);
      await expect(page.locator('.activity-change').nth(3)).toContainText('Phone: 0712345678');
      await expect(page.locator('.activity-change').nth(3)).not.toContainText('→');
      await expect(page.locator('#activity')).toContainText('02 Oct 2026');
      expect(await page.evaluate(()=>document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await page.screenshot({path:info.outputPath(`${app}-${width}.png`),animations:'disabled'});
      await page.evaluate(() => {
        document.documentElement.dataset.miniappColorScheme = 'dark';
        for (const [key,value] of Object.entries({bg_color:'#17171e',secondary_bg_color:'#20202c',text_color:'#ffffff',hint_color:'#a8a8b3'})) document.documentElement.style.setProperty('--tg-theme-'+key.replaceAll('_','-'),value);
      });
      expect(await page.evaluate(()=>document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await page.screenshot({path:info.outputPath(`${app}-${width}-dark.png`),animations:'disabled'});
    });
  }
}

test('all history consumers use the shared comparison renderer', () => {
  for (const file of ['portal_farmer_sheet.js','portal_payments.js','complaint_cases.js','tat_tracker.js']) expect(fs.readFileSync(asset(file),'utf8')).toContain('MiniAppActivityChanges');
  for (const app of ['portal','complaint_cases','tat_tracker']) {
    const template = fs.readFileSync(path.resolve(__dirname, app === 'portal' ? '../templates/base_shell.html' : `../templates/${app}/app.html`),'utf8');
    expect(template).toContain('activity_changes.js');
    expect(template).toContain('activity_changes.css');
  }
});

test('Portal case history groups imports and keeps routine approval concise at 320px', async ({page}, info) => {
  await page.setViewportSize({width:320,height:844});
  await page.setContent('<body class="workflow-standard portal-app"><main id="case360"></main></body>');
  for (const name of ['base.css','workflow_standard.css','portal.css','activity_changes.css']) await page.addStyleTag({path:asset(name)});
  for (const name of ['activity_changes.js','portal_farmer_sheet.js']) await page.addScriptTag({path:asset(name)});
  await page.evaluate(() => {
    PortalMiniAppFarmerSheet.init({el:id=>document.getElementById(id),state:{capabilities:new Set()},tg:{},escapeHtml:value=>String(value ?? ''),fmt:value=>String(value ?? '-'),fmtDate:()=> '05 Oct 2026',locationText:()=>'-'});
    PortalMiniAppFarmerSheet.renderCase360({sections:{},timeline:[
      {title:'Approved',actor:'Training reviewer',occurred_at:'2026-10-05',changes:[{field:'status',label:'Status',old_value:'pending',new_value:'approved',previous_recorded:true}]},
      {title:'Case corrected',actor:'Training officer',occurred_at:'2026-10-05',changes:[{field:'county',label:'County',old_value:'Kiambu',new_value:'Nakuru',previous_recorded:true}]},
      {title:'Customer details updated',actor:'FarmUp',occurred_at:'2026-10-05',detail:'1 field updated from FarmUp.',children:[{title:'Customer field synchronized',detail:'primary_phone updated from test.csv',changes:[{field:'primary_phone',label:'Phone',new_value:'0712345678',previous_recorded:false}]}]},
    ]});
  });
  await page.locator('[data-case360-tab="timeline"]').click();
  await expect(page.locator('.case360-timeline')).not.toContainText('Pending');
  await expect(page.locator('.case360-timeline')).toContainText('County: Kiambu → Nakuru');
  await page.locator('.case360-timeline-children summary').click();
  await expect(page.locator('.case360-timeline')).not.toContainText('Customer field synchronized');
  await expect(page.locator('.case360-timeline')).toContainText('Phone: 0712345678');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({path:info.outputPath('portal-real-timeline-320.png'),animations:'disabled'});
});

test('routine outcomes, removals and notes are concise without losing corrections', async ({page}) => {
  await page.setContent('<article id="activity"></article>');
  await page.addScriptTag({path:asset('activity_changes.js')});
  await page.evaluate(() => MiniAppActivityChanges.append(document.getElementById('activity'), [
    {field:'status',label:'Status',old_value:'pending',new_value:'approved',previous_recorded:true},
    {field:'county',label:'County',old_value:'Kiambu',new_value:'Nakuru',previous_recorded:true},
    {field:'secondary_phone',label:'Secondary phone',old_value:'0712345678',new_value:'',previous_recorded:true},
    {field:'county',label:'County',old_value:'Kiambu',new_value:'Nakuru',previous_recorded:true},
    {field:'comment',label:'Comment',old_value:'',new_value:'Visit confirmed',previous_recorded:true},
    {field:'name',label:'Name',old_value:'Test',new_value:'Test',previous_recorded:true},
    {field:'blank',label:'Blank',new_value:null,previous_recorded:false},
  ], {title:'Approved',detail:'Visit confirmed'}));
  await expect(page.locator('.activity-change')).toHaveCount(2);
  await expect(page.locator('#activity')).toHaveText('County: Kiambu → NakuruSecondary phone removed');
});
