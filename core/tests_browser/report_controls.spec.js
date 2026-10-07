'use strict';
const fs = require('node:fs');
const path = require('node:path');
const { test, expect } = require('playwright/test');
const asset = name => path.resolve(__dirname, '../static/miniapp', name);
const source = fs.readFileSync(asset('tat_tracker.js'), 'utf8');
const heatmapRenderer = source.slice(source.indexOf('  function formatHeatmapValue('), source.indexOf('  function renderTargetReviewSignals('));
const complaintSource = fs.readFileSync(asset('complaint_cases.js'), 'utf8');
const copyRenderer = complaintSource.slice(complaintSource.indexOf('  async function copyReportCell('), complaintSource.indexOf('  function clearReportGridCopy('));
const template = fs.readFileSync(path.resolve(__dirname, '../templates/tat_tracker/app.html'), 'utf8');
const heatmapMarkup = template.match(/<article id="tatHeatmapPanel"[\s\S]*?<\/article>/)[0];

async function mount(page) {
  await page.setContent(`<main class="tat-app" style="padding:12px"><button id="export">Download Excel</button><section class="tat-report-charts">${heatmapMarkup}</section><div id="tatReportGrid" tabindex="-1">Case results</div></main>`);
  for (const name of ['base.css', 'components.css', 'tat_tracker.css']) await page.addStyleTag({path:asset(name)});
  await page.addScriptTag({path:asset('components.js')});
  await page.evaluate(() => { window.__scope = undefined; document.getElementById('export').onclick = async event => { window.__scope = await MiniAppReportControls.chooseExcelExport({trigger:event.currentTarget}); }; });
}

test('shared Excel choices, cancellation, single dialog and focus return', async ({page}) => {
  await mount(page);
  await page.locator('#export').click();
  await expect(page.getByRole('dialog')).toHaveCount(1);
  await expect(page.getByRole('button', {name:'Download filtered', exact:true})).toBeFocused();
  await page.evaluate(() => MiniAppReportControls.chooseExcelExport());
  await expect(page.getByRole('dialog')).toHaveCount(1);
  await page.getByRole('button', {name:'Download all', exact:true}).click();
  expect(await page.evaluate(() => window.__scope)).toBe('all');
  await expect(page.locator('#export')).toBeFocused();
  await page.locator('#export').click(); await page.keyboard.press('Escape');
  expect(await page.evaluate(() => window.__scope)).toBeNull();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await page.locator('#export').click();
  await page.getByRole('button', {name:'Download filtered', exact:true}).click();
  expect(await page.evaluate(() => window.__scope)).toBe('filtered');
});

for (const width of [320, 360, 390, 430, 768, 1280]) {
  test(`heatmap cells, help and Excel dialog fit ${width}px`, async ({page}, info) => {
    await page.setViewportSize({width, height:850}); await mount(page);
    await page.addScriptTag({content:`
      const $ = id => document.getElementById(id);
      const state = {report:{page:4}};
      const escapeHtml = value => String(value).replace(/[&<>"']/g, x => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[x]));
      const compactTatReportLabel = value => value;
      const formatLocalizedNumber = value => String(value);
      const formatLocalizedPercent = value => value + '%';
      const formatMinutes = value => value + ' min';
      const tatChartExplanation = payload => payload.question + '\\n' + payload.interpretation;
      const showTatChartHelp = (target, payload) => MiniAppReportControls.setChartHelp(target, tatChartExplanation(payload));
      const refreshTatReport = async () => {window.__selection = state.report.heatSelection;window.__page = state.report.page;};
      ${heatmapRenderer}
      window.renderHeatmapForTest = renderTatHeatmap;
    `});
    await page.evaluate(() => window.renderHeatmapForTest({id:'heatmap',title:'Stage × Branch',metric:'sla_met',row_dimension:'stage',
      question:'Where are stages meeting their targets?',interpretation:'Select a cell to see its contributing cases.',
      rows:['Credit analysis sent', 'HOCC held', 'Finance disbursement'],columns:['Training A','Training B'],
      cells:[{row:'Credit analysis sent',column:'Training A',value:80,sample_count:5,case_count:4},
        {row:'Credit analysis sent',column:'Training B',value:79.9,sample_count:5,case_count:5},
        {row:'HOCC held',column:'Training A',value:60,sample_count:3,case_count:3},
        {row:'HOCC held',column:'Training B',value:59.9,sample_count:3,case_count:3},
        {row:'Finance disbursement',column:'Training A',value:0,sample_count:2,case_count:2},
        {row:'Finance disbursement',column:'Training B',value:null,sample_count:0,case_count:0}]}));
    await expect(page.locator('[data-heat-tone="good"]')).toHaveCount(1);
    await expect(page.locator('[data-heat-tone="warning"]')).toHaveCount(2);
    await expect(page.locator('[data-heat-tone="bad"]')).toHaveCount(2);
    await expect(page.locator('[data-heat-tone="unavailable"]')).toBeDisabled();
    const cell = page.locator('[data-heat-row="0"][data-heat-column="0"]');
    const value = await cell.locator('strong').boundingBox(), count = await cell.locator('small').boundingBox();
    expect(count.y).toBeGreaterThanOrEqual(value.y + value.height);
    await expect(cell.locator('small')).toHaveText('4 cases');
    await expect(cell.locator('strong')).toHaveCSS('font-size','16px');
    await expect(cell.locator('small')).toHaveCSS('font-size','11px');
    await expect(page.locator('#tatHeatmapBasis')).toBeHidden();
    await page.getByLabel('About this chart').click();
    await expect(page.locator('.miniapp-chart-help-content')).toContainText('contributing cases');
    await page.keyboard.press('Escape');
    await expect(page.locator('.miniapp-chart-help')).not.toHaveAttribute('open');
    await cell.click();
    expect(await page.evaluate(() => window.__selection)).toEqual({heat_row:'Credit analysis sent',heat_column:'Training A'});
    expect(await page.evaluate(() => window.__page)).toBe(1);
    await page.locator('#tatHeatmapSelection').click();
    expect(await page.evaluate(() => window.__selection)).toBeNull();
    for (const dark of [false, true]) {
      await page.evaluate(dark => {document.documentElement.dataset.miniappColorScheme = dark?'dark':'light';}, dark);
      expect(await page.locator('[data-heat-tone="unavailable"]').evaluate(node => {
        const actual=getComputedStyle(node),theme=getComputedStyle(document.documentElement);
        const probe=document.createElement('span');probe.style.color=theme.getPropertyValue('--tat-muted');node.appendChild(probe);
        const expected=getComputedStyle(probe).color;probe.remove();
        return actual.color===expected && actual.opacity==='1';
      })).toBe(true);
      const neutralBackground=await page.locator('[data-heat-tone="unavailable"]').evaluate(node => {
        const probe=document.createElement('span');probe.style.backgroundColor='var(--tat-surface-2)';node.appendChild(probe);
        const expected=getComputedStyle(probe).backgroundColor;probe.remove();return expected;
      });
      await expect(page.locator('[data-heat-tone="unavailable"]')).toHaveCSS('background-color',neutralBackground);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await page.screenshot({path:info.outputPath(`heatmap-${width}-${dark?'dark':'light'}.png`),fullPage:true});
    }
    await page.locator('#export').click();
    const title = await page.locator('.miniapp-report-dialog-head h2').boundingBox();
    const close = await page.getByLabel('Close download options').boundingBox();
    expect(close.x).toBeGreaterThan(title.x + title.width);
    expect(Math.abs(close.y + close.height/2 - title.y - title.height/2)).toBeLessThan(2);
    await page.screenshot({path:info.outputPath(`excel-options-${width}.png`)});
    await page.keyboard.press('Escape');
  });
}

test('copy feedback preserves the entire multiline value', async ({page}) => {
  await mount(page); await page.addScriptTag({path:asset('runtime.js')});
  await page.addScriptTag({content:`
    const state = {reportGridApi:{getDisplayedRowAtIndex:()=>({}),getColumn:()=>({})}};
    const notify = text => window.MiniAppRuntime.showToast(text,{tone:'success'});
    Object.defineProperty(navigator,'clipboard',{value:{writeText:async value=>{window.__copied=value;}}});
    ${copyRenderer}
    window.copyCellForTest = copyReportCell;
  `});
  const value = ('Synthetic long comment with Unicode ✓ and a long identifier ABCDEFGHIJKLMNOPQRSTUVWXYZ\n').repeat(5).trim();
  await page.evaluate(value => {
    const row = document.createElement('div'); row.className='ag-row'; row.setAttribute('row-index','0');
    const cell = document.createElement('div');cell.className='ag-cell';cell.setAttribute('col-id','comment');cell.style.whiteSpace='pre-wrap';cell.textContent=value;
    row.appendChild(cell);document.body.appendChild(row);return window.copyCellForTest(cell);
  }, value);
  expect(await page.evaluate(() => window.__copied)).toBe(value);
  await expect(page.locator('#miniapp-shared-toast')).toHaveText(`Copied: ${value}`);
  await expect(page.locator('#miniapp-shared-toast')).toHaveCSS('white-space','pre-wrap');
});
