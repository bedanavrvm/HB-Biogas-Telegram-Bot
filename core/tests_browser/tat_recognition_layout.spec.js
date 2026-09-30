'use strict';

const fs = require('node:fs');
const path = require('node:path');
const { test, expect } = require('playwright/test');

const asset = name => path.resolve(__dirname, '../static/miniapp', name);
const trackerSource = fs.readFileSync(asset('tat_tracker.js'), 'utf8');
const recognitionStart = trackerSource.indexOf('  function recognitionContext(');
const recognitionEnd = trackerSource.indexOf('  async function loadTatRecognition', recognitionStart);
const recognitionRenderer = trackerSource.slice(recognitionStart, recognitionEnd);
const templateSource = fs.readFileSync(path.resolve(__dirname, '../templates/tat_tracker/app.html'), 'utf8');
const logoData = `data:image/png;base64,${fs.readFileSync(asset('jawabu-logo.png')).toString('base64')}`;
const fullShellMarkup = `<body>${templateSource.slice(
  templateSource.indexOf('<main class="tat-app"'), templateSource.lastIndexOf('</main>') + '</main>'.length,
).replaceAll("{% static 'miniapp/jawabu-logo.png' %}", logoData)
  .replace(/{%[\s\S]*?%}|{{[\s\S]*?}}/g, '')}</body>`;

const recognitionMarkup = `<main class="tat-app"><section id="recognitionView" class="view recognition-view active">
  <header class="recognition-header"><div><h2>Standings</h2></div><div class="recognition-header-actions"><button id="tatRecognitionPeriodButton" type="button">Period</button><span id="tatRecognitionUpdated"></span></div></header>
  <section id="tatRecognitionOverall" class="recognition-overall"></section>
  <div id="tatRecognitionToolbar" class="recognition-toolbar"><div id="tatRecognitionViews" class="recognition-view-toggle"><button type="button" data-recognition-view="people">People</button><button type="button" data-recognition-view="branches">Branches</button></div><button id="tatRecognitionFilterButton" type="button">Filter</button></div>
  <div id="tatRecognitionActiveFilters" class="recognition-active-filters" hidden></div><section id="tatRecognitionSlice" class="recognition-slice" hidden></section>
  <section id="tatRecognitionDetails" class="recognition-details" hidden><header><button id="tatRecognitionDetailsBack" type="button" aria-label="Back to standings">←</button><h2>Score details</h2></header><p id="tatRecognitionCapture" hidden></p></section>
  <section id="tatPersonalRecognition" class="recognition-personal"></section><section id="tatRecognitionBreakdown" class="recognition-breakdown"></section>
  <section id="tatRecognitionStageDetail" class="recognition-stage-detail" hidden><header><button id="tatRecognitionStagesBack" type="button">Back</button><h2>All stages</h2></header><div id="tatRecognitionStageRows" class="recognition-stage-list"></div><nav id="tatRecognitionStagePagination" class="recognition-pagination" hidden><button id="tatRecognitionStagePrevious">Previous</button><span id="tatRecognitionStagePage"></span><button id="tatRecognitionStageNext">Next</button></nav></section>
  <section id="tatRecognitionStandings" class="recognition-standings" hidden><div class="stage-summary-heading"><h2 id="tatRecognitionStandingsTitle"></h2><span id="tatRecognitionMinimum"></span></div><div id="tatRecognitionPinned" class="recognition-pinned" hidden></div><div id="tatRecognitionRows" class="recognition-list"></div><nav id="tatRecognitionPagination" class="recognition-pagination" hidden><button id="tatRecognitionPrevious">Previous</button><span id="tatRecognitionPage"></span><button id="tatRecognitionNext">Next</button></nav></section>
  <details id="tatRecognitionTechnical" class="recognition-technical" hidden><summary>How rankings work</summary><div id="tatRecognitionTechnicalContent"></div></details>
  <div id="tatRecognitionControlsOverlay" class="tat-sheet-overlay" role="dialog" aria-hidden="true" hidden><section id="tatRecognitionControlsSheet" class="tat-sheet recognition-controls-sheet"><h2 id="tatRecognitionControlsTitle"></h2><button id="tatRecognitionControlsClose" type="button">Close</button><div id="tatRecognitionPeriodControls" class="recognition-period-controls"><label>View by<select id="tatRecognitionPeriodKind"><option value="month">Month</option><option value="quarter">Quarter</option><option value="year">Year</option></select></label><label id="tatRecognitionMonthControl">Month<input id="tatRecognitionPeriod" type="month" value="2026-09"></label><label id="tatRecognitionQuarterControl" hidden>Quarter<select id="tatRecognitionQuarter"><option value="1">Q1</option><option value="2">Q2</option></select></label><label id="tatRecognitionYearControl" hidden>Year<input id="tatRecognitionYear" type="number" value="2026"></label></div><div id="tatRecognitionContextControls" class="recognition-context-controls" hidden><label>Role<select id="tatRecognitionRole"></select></label><label>Product<select id="tatRecognitionProduct"></select></label><label>Branch<select id="tatRecognitionBranch"></select></label></div><button id="tatRecognitionClearFilters" type="button">Clear</button><button id="tatRecognitionControlsApply" type="button">Apply</button></section></div>
</section></main>`;

const selected = { role: 'BRO', role_label: 'BRO', product: 'standard', product_label: 'Standard HomeBiogas' };
const personalResult = {
  label: 'You', role: 'BRO', branch: 'Embu', product: 'Standard HomeBiogas',
  ranked: true, rank: 11, completed: 16, completed_total: 16,
  on_time_rate: 87.5, score: 64.1, is_current_user: true,
};
const basePayload = {
  contract_version: 3,
  minimum_ranked_sample: 1, minimum_personal_best_sample: 20,
  calculated_at: '2026-09-17T10:45:00+03:00',
  view: 'people', selected,
  period: '2026-09', period_kind: 'month', result_status: 'live_provisional',
  overall_result: {completed: 16, on_time_rate: 87.5, score: 64.1, ranked: false},
  slice_result: {completed: 16, on_time_rate: 87.5, score: 64.1, ranked: false, share_of_overall: 100},
  breakdown: {overall: {counted: 16, recorded: 16, within_target: 14, near_target: 0, over_target: 2, target_unavailable: 0, percentages: {within_target: 87.5, near_target: 0, over_target: 12.5}}, slice: {counted: 16, recorded: 16, within_target: 14, near_target: 0, over_target: 2, target_unavailable: 0, percentages: {within_target: 87.5, near_target: 0, over_target: 12.5}}},
  stage_contributions: [], personal_best: null,
  role_options: [{ key: 'BRO', label: 'BRO' }],
  product_options: [{ key: 'standard', label: 'Standard HomeBiogas' }],
  branch_options: [{ key: '', label: 'All branches' }, {key: 'Embu', label: 'Embu'}],
  personal_result: personalResult,
  role_summary: { role: 'BRO', product: 'Standard HomeBiogas', completed: 48, completed_total: 48, on_time_rate: 89.6, score: 78.0 },
  standings: { dimension: 'people', rows: [], current_user_row: null, page: 1, pages: 1, total: 0, page_size: 10, has_competition: false, eligible_count: 0 },
  people_visible: false, technical_details_visible: false, methodology: null,
};

test('hidden no-graphs notice does not appear beside available graphs', async ({ page }) => {
  await page.setContent('<main><p id="tatNoInsights" class="chart-empty-static" hidden>No report graphs are available for your access.</p><article id="tatTrendPanel">Workload graph</article></main>');
  await page.addStyleTag({ path: asset('tat_tracker.css') });
  await expect(page.locator('#tatNoInsights')).toBeHidden();
  await expect(page.locator('#tatTrendPanel')).toBeVisible();
});

const peopleRows = Array.from({ length: 5 }, (_, index) => ({
  label: `Peer ${index + 1}`, role: 'BRO', branch: index % 2 ? 'Nakuru' : 'Embu',
  product: 'Standard HomeBiogas', ranked: true, rank: index + 1,
  completed: 28 - index, on_time_rate: 94 - index, score: 82 - index,
  is_current_user: false,
}));

async function mount(page, payload = basePayload, markup = recognitionMarkup) {
  await page.setContent(markup);
  if (markup === fullShellMarkup) await page.evaluate(() => {
    document.querySelectorAll('.view').forEach(node => node.classList.remove('active'));
    document.getElementById('recognitionView').classList.add('active');
    document.getElementById('trackerTabs').hidden = true;
    document.getElementById('loadingBrand').hidden = true;
    document.getElementById('loadingBrand').style.display = 'none';
    document.getElementById('recognitionWorkspaceBtn').hidden = false;
    document.getElementById('recognitionWorkspaceBtn').classList.add('active');
    document.getElementById('dashboardWorkspaceBtn').hidden = false;
    document.getElementById('userLine').textContent = 'Test staff · TAT';
  });
  await page.addStyleTag({ path: asset('base.css') });
  await page.addStyleTag({ path: asset('tat_tracker.css') });
  await page.addScriptTag({ content: `
    const $ = id => document.getElementById(id);
    const state = { currentView: 'recognition', recognition: { view: 'people', returnView: 'people', role: '', product: '', branch: '', page: 1, stagePage: 1, stagesOpen: false, sequence: 0, controlsOpen: false } };
    const tg = null;
    const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, character => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[character]));
    const formatTatDateTime = () => '17-09-2026 10:45';
    ${recognitionRenderer}
    window.renderTatRecognitionForTest = renderTatRecognition;
    window.openRecognitionControlsForTest = openRecognitionControls;
    window.closeRecognitionControlsForTest = closeRecognitionControls;
    window.closeRecognitionDetailsForTest = closeRecognitionDetails;
    window.recognitionStateForTest = state.recognition;
    bindRecognitionStageControls();
  ` });
  await page.evaluate(value => window.renderTatRecognitionForTest(value), payload);
}

for (const width of [320, 360, 390, 430]) {
  for (const theme of ['light', 'dark']) {
    test(`full TAT shell keeps standings columns aligned at ${width}px in ${theme}`, async ({ page }, testInfo) => {
      await page.setViewportSize({ width, height: 844 });
      await mount(page, {
        ...basePayload,
        standings: {
          dimension: 'people',
          rows: [...peopleRows, ...peopleRows.map((row, index) => ({
            ...row, label: `Very Long Staff Name From A Different Operational Branch ${index + 1}`,
            rank: index + 6, movement: index % 2
              ? {direction: 'up', places: 2} : {direction: 'down', places: 1},
          }))],
          current_user_row: {...personalResult, movement: {direction: 'up', places: 3}},
          page: 2, pages: 4, total: 37, page_size: 10,
        },
      }, fullShellMarkup);
      await page.evaluate(value => { document.documentElement.dataset.miniappColorScheme = value; }, theme);
      await expect(page.locator('#appHeader')).toBeVisible();
      await expect(page.locator('#workspaceTabs')).toBeVisible();
      await expect(page.locator('#tatRecognitionRows .recognition-row')).toHaveCount(10);
      await expect(page.locator('#tatRecognitionPinned .recognition-movement')).toHaveText('↑ 3');
      const positions = await page.locator('.recognition-row').evaluateAll(rows => rows.map(row => {
        const rank = row.querySelector('.recognition-rank').getBoundingClientRect();
        const main = row.querySelector('.recognition-row-main').getBoundingClientRect();
        const score = row.querySelector('.recognition-score').getBoundingClientRect();
        return {rank: rank.left, main: main.left, score: score.left, right: score.right};
      }));
      for (const position of positions) {
        expect(Math.abs(position.rank - positions[0].rank)).toBeLessThanOrEqual(1);
        expect(Math.abs(position.main - positions[0].main)).toBeLessThanOrEqual(1);
        expect(Math.abs(position.score - positions[0].score)).toBeLessThanOrEqual(1);
        expect(position.right).toBeLessThanOrEqual(width);
      }
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
      if (process.env.TAT_RECOGNITION_SCREENSHOT) {
        await page.screenshot({ path: testInfo.outputPath(`full-shell-${width}-${theme}.png`), fullPage: true });
      }
    });
  }
}

test('full shell branch movement and unfiltered summary stay aligned at 320px', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 320, height: 568 });
  await mount(page, {
    ...basePayload,
    view: 'branches',
    selected: {role: '', role_label: '', product: '', product_label: '', branch: ''},
    standings: {dimension: 'branches', rows: [
      {label: 'Long Operational Branch Name Nakuru North', branch: 'Long Operational Branch Name Nakuru North', rank: 1, ranked: true, score: 82, within_target: 17, near_target: 2, over_target: 1, movement: {direction: 'up', places: 2}},
      {label: 'Embu', branch: 'Embu', rank: 2, ranked: true, score: 78, within_target: 12, near_target: 3, over_target: 2, movement: {direction: 'down', places: 1}},
    ], current_user_row: null, page: 1, pages: 1, total: 2},
  }, fullShellMarkup);
  await expect(page.locator('#tatRecognitionSlice')).toBeHidden();
  await expect(page.locator('#tatRecognitionRows .recognition-movement.up')).toContainText('2');
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(320);
  if (process.env.TAT_RECOGNITION_SCREENSHOT) {
    await page.screenshot({path: testInfo.outputPath('full-shell-branches-320.png'), fullPage: true});
  }
});

for (const viewport of [
  { width: 320, height: 568 },
  { width: 360, height: 800 },
  { width: 390, height: 844 },
  { width: 430, height: 932 },
]) {
  test(`standings open compact and readable at ${viewport.width}x${viewport.height}`, async ({ page }, testInfo) => {
    await page.setViewportSize(viewport);
    await mount(page);

    await expect(page.locator('#tatRecognitionOverall')).toContainText('Your score');
    await expect(page.locator('#tatRecognitionPeriodButton')).toHaveText('Sep 2026 ▾');
    await expect(page.locator('#tatRecognitionUpdated')).toHaveText('Live');
    await expect(page.locator('#tatRecognitionBreakdown')).toBeHidden();
    await expect(page.locator('#tatRecognitionSlice')).toContainText('Selected work');
    await expect(page.locator('#tatRecognitionTechnical')).toBeHidden();
    await expect(page.locator('#tatRecognitionStandings')).toBeVisible();
    await expect(page.locator('[data-recognition-view="people"]')).toHaveAttribute('aria-pressed', 'true');
    expect(await page.locator('body').innerText()).not.toMatch(/Wilson|quality floor|legacy actor|corrected records|workflow group/i);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(viewport.width);
    if (viewport.width === 390 && process.env.TAT_RECOGNITION_SCREENSHOT) {
      await page.screenshot({ path: testInfo.outputPath('recognition-standings.png'), fullPage: true });
    }
    const resultBox = await page.locator('.recognition-result-card').first().boundingBox();
    expect(resultBox.y + resultBox.height).toBeLessThanOrEqual(viewport.height + 20);
    await page.evaluate(() => { document.documentElement.dataset.miniappColorScheme = 'dark'; });
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(viewport.width);
    await expect.poll(() => page.locator('.recognition-result-card header strong').evaluate(node => getComputedStyle(node).color)).toBe('rgb(241, 245, 249)');
  });
}

test('people standings render ten rows plus a pinned current result', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 568 });
  await mount(page, {
    ...basePayload,
    view: 'people',
    standings: {
      dimension: 'people', rows: [...peopleRows, ...peopleRows.map((row, index) => ({...row, label: `Peer ${index + 6}`, rank: index + 6}))], current_user_row: personalResult,
      page: 2, pages: 4, total: 37, page_size: 10, has_competition: true, eligible_count: 31,
    },
  });

  await expect(page.locator('#tatRecognitionStandings')).toBeVisible();
  await expect(page.locator('#tatRecognitionStandingsTitle')).toHaveText('People');
  await expect(page.locator('#tatRecognitionSlice')).toContainText('100%');
  await expect(page.locator('#tatRecognitionPinned')).toContainText('You');
  await expect(page.locator('#tatRecognitionPage')).toHaveText('Page 2 of 4');
  await expect(page.locator('#tatRecognitionRows .recognition-row')).toHaveCount(10);
  await expect(page.locator('.recognition-row')).toHaveCount(11);
  await expect(page.locator('#tatRecognitionBreakdown')).toBeHidden();
  await expect(page.locator('.recognition-row').first()).toContainText('11');
  await expect(page.locator('.recognition-row').first()).toContainText('87.5% on time');
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(320);
  const pinnedRow = await page.locator('#tatRecognitionPinned .recognition-row').boundingBox();
  expect(pinnedRow.y).toBeLessThan(568);
  const firstListRow = await page.locator('#tatRecognitionRows .recognition-row').first().boundingBox();
  expect(firstListRow.height).toBeLessThanOrEqual(90);
  expect(await page.locator('.recognition-row-main > strong').first().evaluate(node => parseFloat(getComputedStyle(node).fontSize))).toBeGreaterThanOrEqual(12);
  expect(await page.locator('.recognition-row-metrics').first().evaluate(node => parseFloat(getComputedStyle(node).fontSize))).toBeGreaterThanOrEqual(11);
});

test('management can inspect one collapsed methodology section and named rows', async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 800 });
  await mount(page, {
    ...basePayload,
    view: 'people', people_visible: true, technical_details_visible: true,
    standings: {
      dimension: 'people', rows: [{ ...peopleRows[0], label: 'Mary Wanjiku' }],
      current_user_row: null, page: 1, pages: 1, total: 1, page_size: 5,
      has_competition: false, eligible_count: 1,
    },
    methodology: {
      score_method: 'The performance score is the 95% Wilson lower bound.',
      cohort_basis: 'Same group, role and product.', correction_policy: 'Audited corrections update live results.',
      late_work_policy: 'Late work does not count as on time.', completed_total: 30, counted_total: 28,
      excluded_target_unavailable: 2, corrected: 1, attribution_fallback: 0, overdue_recovered: 3,
    },
  });

  await expect(page.locator('#tatRecognitionRows')).toContainText('Mary Wanjiku');
  const details = page.locator('#tatRecognitionTechnical');
  await expect(details).toBeHidden();
  await page.evaluate(value => window.renderTatRecognitionForTest(value), {
    ...basePayload, view: 'personal', people_visible: true, technical_details_visible: true,
    methodology: {
      score_method: 'The performance score is the 95% Wilson lower bound.',
      cohort_basis: 'Same group, role and product.', correction_policy: 'Audited corrections update live results.',
      late_work_policy: 'Late work does not count as on time.', completed_total: 30, counted_total: 28,
      excluded_target_unavailable: 2, corrected: 1, attribution_fallback: 0, overdue_recovered: 3,
    },
  });
  await expect(details).toBeVisible();
  await expect(details).not.toHaveAttribute('open', '');
  await details.locator('summary').focus();
  await page.keyboard.press('Enter');
  await expect(details).toHaveAttribute('open', '');
  await expect(page.locator('#tatRecognitionTechnicalContent')).toContainText('Wilson');
  await expect(page.locator('#tatRecognitionTechnicalContent')).toContainText('No target configured');

  await page.evaluate(() => { document.documentElement.dataset.miniappColorScheme = 'dark'; });
  await expect.poll(() => page.locator('.recognition-row-main > strong').first().evaluate(node => getComputedStyle(node).color)).toBe('rgb(241, 245, 249)');
});

test('recognition empty states use plain language', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 568 });
  await mount(page, {
    ...basePayload, personal_result: null,
    overall_result: { completed: 0, on_time_rate: 0, score: 0, ranked: false },
    slice_result: { completed: 0, on_time_rate: 0, score: 0, ranked: false, share_of_overall: 0 },
    breakdown: { overall: { counted: 0, recorded: 0, within_target: 0, near_target: 0, over_target: 0, target_unavailable: 0, percentages: {} }, slice: {} },
    role_summary: { completed: 0, completed_total: 0, on_time_rate: 0, score: 0 },
  });
  await expect(page.locator('#tatRecognitionOverall')).toContainText('No counted actions');
  await expect(page.locator('#tatRecognitionBreakdown')).toBeHidden();
});

test('score effects are labelled and single-role stage details stay secondary', async ({ page }) => {
  await mount(page, {
    ...basePayload, view: 'personal',
    stage_contributions: [
      { role: 'BRO', stage: 'BRO action', completed: 8, on_time_rate: 75, score: 55 },
      { role: 'BRO', stage: 'BRO follow-up', completed: 5, on_time_rate: 80, score: 60 },
    ],
  });
  await expect(page.locator('#tatRecognitionBreakdown .recognition-breakdown-positive')).toHaveCount(2);
  await expect(page.locator('#tatRecognitionBreakdown .recognition-breakdown-negative')).toContainText('Over target');
  await expect(page.locator('#tatRecognitionBreakdown .recognition-breakdown-neutral')).toContainText('No target');
  await expect(page.locator('#tatPersonalRecognition .recognition-stage-row')).toHaveCount(0);
  await expect(page.locator('#tatRecognitionAllStages')).toContainText('Stage contributions (2)');
});

test('branch standings show disjoint within, near and over counts', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 568 });
  await mount(page, {
    ...basePayload, view: 'branches',
    standings: {
      dimension: 'branches', rows: [{
        branch: 'Embu', label: 'Embu', rank: 1, ranked: true,
        completed: 19, on_time_rate: 89.5, score: 74.5,
        within_target: 14, near_target: 3, over_target: 2,
      }], current_user_row: null, page: 1, pages: 1, total: 1,
    },
  });
  const row = page.locator('#tatRecognitionRows .recognition-row');
  await expect(row).toContainText('1');
  await expect(row).toContainText('Within 14');
  await expect(row).toContainText('Near 3');
  await expect(row).toContainText('Over 2');
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(320);
});

for (const width of [320, 360, 390, 430]) {
  test(`long stage names stay readable and all stages are paged at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 800 });
    const stage_contributions = Array.from({ length: 16 }, (_, index) => ({
      role: index % 2 ? 'Credit Analyst' : 'BRO',
      stage: `Business administration disbursement verification and final register stage ${index + 1}`,
      completed: index === 15 ? 0 : 16 - index, on_time_rate: 75, score: 62.4,
    }));
    await mount(page, { ...basePayload, view: 'personal', stage_contributions });
    await expect(page.locator('#tatPersonalRecognition .recognition-stage-row')).toHaveCount(0);
    await expect(page.locator('#tatRecognitionAllStages')).toContainText('Stage contributions (15)');
    await expect(page.locator('#tatRecognitionBreakdown .recognition-data-checks > div')).toHaveCount(4);
    if (width === 390 && process.env.TAT_RECOGNITION_SCREENSHOT) {
      await page.screenshot({ path: testInfo.outputPath('recognition-summary.png'), fullPage: true });
    }
    await page.locator('#tatRecognitionAllStages').click();
    await expect(page.locator('#tatRecognitionStageDetail')).toBeVisible();
    await expect(page.locator('#tatRecognitionOverall')).toBeHidden();
    expect((await page.locator('#tatRecognitionStagesBack').boundingBox()).width).toBeLessThan(120);
    await expect(page.locator('#tatRecognitionStageRows .recognition-stage-row')).toHaveCount(10);
    await expect(page.locator('#tatRecognitionStagePage')).toHaveText('Page 1 of 2');
    if (width === 390 && process.env.TAT_RECOGNITION_SCREENSHOT) {
      await page.screenshot({ path: testInfo.outputPath('recognition-stages.png'), fullPage: true });
    }
    const stageName = page.locator('#tatRecognitionStageRows .recognition-stage-name').first();
    await expect(stageName).toHaveText(/Business administration disbursement verification/);
    await expect(stageName).not.toHaveAttribute('aria-expanded');
    expect(await stageName.evaluate(node => getComputedStyle(node, '::after').content)).toBe('none');
    await page.locator('#tatRecognitionStageNext').click();
    await expect(page.locator('#tatRecognitionStageRows .recognition-stage-row')).toHaveCount(5);
    await page.locator('#tatRecognitionStagesBack').click();
    await expect(page.locator('#tatRecognitionBreakdown')).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
  });
}

test('quarter and year labels identify the selected period', async ({ page }) => {
  await mount(page, { ...basePayload, period_kind: 'quarter', period: '2026-Q2' });
  await expect(page.locator('#tatRecognitionPeriodButton')).toContainText('Q2 2026');
  await page.evaluate(value => window.renderTatRecognitionForTest(value), {
    ...basePayload, period_kind: 'year', period: '2025',
  });
  await expect(page.locator('#tatRecognitionPeriodButton')).toContainText('2025');
});

test('period and filters stay behind focused controls and cancellation restores the current selection', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 568 });
  await mount(page);
  await page.evaluate(() => window.openRecognitionControlsForTest('period', document.getElementById('tatRecognitionPeriodButton')));
  await expect(page.locator('#tatRecognitionControlsOverlay')).toBeVisible();
  await expect(page.locator('#tatRecognitionContextControls')).toBeHidden();
  await page.locator('#tatRecognitionPeriod').fill('2026-08');
  await page.evaluate(() => window.closeRecognitionControlsForTest());
  await expect(page.locator('#tatRecognitionControlsOverlay')).toBeHidden();
  await expect(page.locator('#tatRecognitionPeriod')).toHaveValue('2026-09');
  await expect(page.locator('#tatRecognitionPeriodButton')).toBeFocused();
  await page.evaluate(() => window.openRecognitionControlsForTest('filters', document.getElementById('tatRecognitionFilterButton')));
  await expect(page.locator('#tatRecognitionContextControls')).toBeVisible();
  await expect(page.locator('#tatRecognitionPeriodControls')).toBeHidden();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(320);
});

test('score details return to the existing standings without re-ranking', async ({ page }) => {
  await mount(page);
  await page.evaluate(value => {
    window.recognitionStateForTest.lastStandingsPayload = window.recognitionStateForTest.lastPayload;
    window.recognitionStateForTest.returnView = 'people';
    window.renderTatRecognitionForTest({ ...value, view: 'personal' });
  }, basePayload);
  await expect(page.locator('#tatRecognitionDetails')).toBeVisible();
  await expect(page.locator('#tatRecognitionStandings')).toBeHidden();
  await page.evaluate(() => window.closeRecognitionDetailsForTest());
  await expect(page.locator('#tatRecognitionStandings')).toBeVisible();
  await expect(page.locator('#tatRecognitionDetails')).toBeHidden();
  await expect(page.locator('#tatRecognitionOverall')).toContainText('64.1');
});
