'use strict';

const fs = require('node:fs');
const path = require('node:path');
const { test, expect } = require('playwright/test');

const asset = name => path.resolve(__dirname, '../static/miniapp', name);
const trackerSource = fs.readFileSync(asset('tat_tracker.js'), 'utf8');
const recognitionStart = trackerSource.indexOf('  function recognitionContext(');
const recognitionEnd = trackerSource.indexOf('  async function loadTatRecognition', recognitionStart);
const recognitionRenderer = trackerSource.slice(recognitionStart, recognitionEnd);

const recognitionMarkup = `<main class="tat-app"><section id="recognitionView" class="view recognition-view active">
  <header class="recognition-header"><div><p class="eyebrow">Recognition</p><h2>Period standings</h2></div><div class="recognition-period-controls"><label class="recognition-period"><span>View by</span><select id="tatRecognitionPeriodKind"><option value="month">Month</option><option value="quarter">Quarter</option><option value="year">Year</option></select></label><label class="recognition-period"><span>Month</span><input id="tatRecognitionPeriod" type="month" value="2026-09"></label></div><p id="tatRecognitionUpdated" class="recognition-updated"></p></header>
  <section id="tatRecognitionOverall" class="recognition-overall"></section>
  <button id="tatRecognitionFilterButton" class="tat-report-filter-bar recognition-filter-button"><span class="tat-report-filter-action"><strong>Filters</strong></span><span class="tat-report-filter-summary"><strong id="tatRecognitionFilterSummary"></strong><small>Compare a specific part of your work</small></span></button>
  <div id="tatRecognitionContextControls" class="recognition-context-controls" hidden><label><span>Role</span><select id="tatRecognitionRole"></select></label><label><span>Product</span><select id="tatRecognitionProduct"></select></label><label><span>Branch</span><select id="tatRecognitionBranch"></select></label></div>
  <section id="tatRecognitionSlice" class="recognition-slice" hidden></section>
  <div id="tatRecognitionViews" class="recognition-view-toggle" role="group"><button type="button" data-recognition-view="personal">My result</button><button type="button" data-recognition-view="people">People</button><button type="button" data-recognition-view="branches">Branches</button></div>
  <section id="tatPersonalRecognition" class="recognition-personal"></section>
  <section id="tatRecognitionStageDetail" class="recognition-stage-detail" hidden><header><button id="tatRecognitionStagesBack" type="button">Back</button><h2>All stages</h2></header><div id="tatRecognitionStageRows" class="recognition-stage-list"></div><nav id="tatRecognitionStagePagination" class="recognition-pagination" hidden><button id="tatRecognitionStagePrevious">Previous</button><span id="tatRecognitionStagePage"></span><button id="tatRecognitionStageNext">Next</button></nav></section>
  <section id="tatRecognitionStandings" class="recognition-standings" hidden><div class="stage-summary-heading"><div><h2 id="tatRecognitionStandingsTitle"></h2><p id="tatRecognitionStandingsBasis"></p></div><span id="tatRecognitionMinimum"></span></div><div id="tatRecognitionPinned" class="recognition-pinned" hidden></div><div id="tatRecognitionRows" class="recognition-list"></div><nav id="tatRecognitionPagination" class="recognition-pagination" hidden><button id="tatRecognitionPrevious">Previous</button><span id="tatRecognitionPage"></span><button id="tatRecognitionNext">Next</button></nav></section>
  <section id="tatRecognitionBreakdown" class="recognition-breakdown"></section>
  <details id="tatRecognitionTechnical" class="recognition-technical" hidden><summary>Data checks</summary><div id="tatRecognitionTechnicalContent"></div></details>
</section></main>`;

const selected = { role: 'BRO', role_label: 'BRO', product: 'standard', product_label: 'Standard HomeBiogas' };
const personalResult = {
  label: 'You', role: 'BRO', branch: 'Embu', product: 'Standard HomeBiogas',
  ranked: false, rank: null, completed: 16, completed_total: 16,
  on_time_rate: 87.5, score: 64.1, is_current_user: true,
};
const basePayload = {
  contract_version: 3,
  minimum_ranked_sample: 20,
  calculated_at: '2026-09-17T10:45:00+03:00',
  view: 'personal', selected,
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
  standings: { dimension: 'personal', rows: [], current_user_row: null, page: 1, pages: 1, total: 0, page_size: 5, has_competition: false, eligible_count: 0 },
  people_visible: false, technical_details_visible: false, methodology: null,
};

const peopleRows = Array.from({ length: 5 }, (_, index) => ({
  label: `Peer ${index + 1}`, role: 'BRO', branch: index % 2 ? 'Nakuru' : 'Embu',
  product: 'Standard HomeBiogas', ranked: true, rank: index + 1,
  completed: 28 - index, on_time_rate: 94 - index, score: 82 - index,
  is_current_user: false,
}));

async function mount(page, payload = basePayload) {
  await page.setContent(recognitionMarkup);
  await page.addStyleTag({ path: asset('base.css') });
  await page.addStyleTag({ path: asset('tat_tracker.css') });
  await page.addScriptTag({ content: `
    const $ = id => document.getElementById(id);
    const state = { recognition: { view: 'personal', role: '', product: '', branch: '', page: 1, stagePage: 1, stagesOpen: false, sequence: 0 } };
    const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, character => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[character]));
    const formatTatDateTime = () => '17-09-2026 10:45';
    ${recognitionRenderer}
    window.renderTatRecognitionForTest = renderTatRecognition;
    bindRecognitionStageControls();
  ` });
  await page.evaluate(value => window.renderTatRecognitionForTest(value), payload);
}

for (const viewport of [
  { width: 320, height: 568 },
  { width: 360, height: 800 },
  { width: 390, height: 844 },
  { width: 430, height: 932 },
]) {
  test(`personal recognition is compact and readable at ${viewport.width}x${viewport.height}`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await mount(page);

    await expect(page.locator('#tatRecognitionOverall')).toContainText('Your overall score');
    await expect(page.locator('#tatRecognitionUpdated')).toContainText('September 2026 · Live · Updated 17-09-2026 10:45');
    await expect(page.locator('#tatRecognitionBreakdown')).toContainText('Within target');
    await expect(page.locator('#tatRecognitionSlice')).toContainText('Selected work');
    await expect(page.locator('#tatRecognitionTechnical')).toBeHidden();
    await expect(page.locator('#tatRecognitionStandings')).toBeHidden();
    expect(await page.locator('body').innerText()).not.toMatch(/Wilson|quality floor|legacy actor|corrected records|workflow group/i);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(viewport.width);
    const resultBox = await page.locator('.recognition-result-card').first().boundingBox();
    expect(resultBox.y + resultBox.height).toBeLessThanOrEqual(viewport.height + 20);
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
  await expect(page.locator('#tatRecognitionStandingsTitle')).toHaveText('People standings');
  await expect(page.locator('#tatRecognitionSlice')).toContainText('100%');
  await expect(page.locator('#tatRecognitionPinned')).toContainText('Your position');
  await expect(page.locator('#tatRecognitionPage')).toHaveText('Page 2 of 4');
  await expect(page.locator('#tatRecognitionRows .recognition-row')).toHaveCount(10);
  await expect(page.locator('.recognition-row')).toHaveCount(11);
  await expect(page.locator('#tatRecognitionBreakdown')).toBeHidden();
  await expect(page.locator('.recognition-row').first()).toContainText('87.5% On time');
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
  await expect(page.locator('#tatRecognitionBreakdown')).toContainText('0 counted of 0 completed actions');
});

for (const width of [320, 360, 390, 430]) {
  test(`long stage names stay readable and all stages are paged at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 800 });
    const stage_contributions = Array.from({ length: 16 }, (_, index) => ({
      stage: `Business administration disbursement verification and final register stage ${index + 1}`,
      completed: index === 15 ? 0 : 16 - index, on_time_rate: 75, score: 62.4,
    }));
    await mount(page, { ...basePayload, stage_contributions });
    await expect(page.locator('#tatPersonalRecognition .recognition-stage-row')).toHaveCount(3);
    await expect(page.locator('#tatRecognitionAllStages')).toHaveText('View all 15 stages');
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
    await stageName.click();
    await expect(stageName).toHaveAttribute('aria-expanded', 'true');
    await page.locator('#tatRecognitionStageNext').click();
    await expect(page.locator('#tatRecognitionStageRows .recognition-stage-row')).toHaveCount(5);
    await page.locator('#tatRecognitionStagesBack').click();
    await expect(page.locator('#tatRecognitionBreakdown')).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
  });
}

test('quarter and year labels identify the selected period', async ({ page }) => {
  await mount(page, { ...basePayload, period_kind: 'quarter', period: '2026-Q2' });
  await expect(page.locator('#tatRecognitionUpdated')).toContainText('2026 · Q2');
  await page.evaluate(value => window.renderTatRecognitionForTest(value), {
    ...basePayload, period_kind: 'year', period: '2025',
  });
  await expect(page.locator('#tatRecognitionUpdated')).toContainText('2025 · Live');
});
