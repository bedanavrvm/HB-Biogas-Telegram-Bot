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
  <header class="recognition-header"><div><p class="eyebrow">Recognition</p><h2>Monthly recognition</h2><p>See your on-time performance and how your role is doing this month.</p></div><label class="recognition-period"><span>Month</span><input id="tatRecognitionPeriod" type="month" value="2026-09"></label><p id="tatRecognitionUpdated" class="recognition-updated"></p></header>
  <section id="tatPersonalRecognition" class="recognition-personal"></section>
  <section class="recognition-standings"><div class="stage-summary-heading"><h2>Role standings</h2><span id="tatRecognitionMinimum"></span></div><div id="tatTeamRecognition" class="recognition-list"></div></section>
  <section id="tatPeopleRecognitionSection" class="recognition-standings" hidden><div class="stage-summary-heading"><h2>Individual breakdown</h2><span>Management and IT only</span></div><div id="tatPeopleRecognition" class="recognition-list"></div></section>
  <details id="tatRecognitionTechnical" class="recognition-technical" hidden><summary>Calculation and data checks</summary><div id="tatRecognitionTechnicalContent"></div></details>
</section></main>`;

const ordinaryPayload = {
  minimum_ranked_sample: 20,
  calculated_at: '2026-09-17T10:45:00+03:00',
  personal_rows: [{ role: 'Branch Relationship Officer', branch: 'Embu', product: 'Standard HomeBiogas', ranked: false, rank: null, completed: 16, on_time_rate: 87.5, score: 64.1 }],
  team_rows: [
    { role: 'Credit Analyst', label: 'Credit Analyst', branch: 'Nakuru', product: 'HOCC', ranked: true, rank: 1, completed: 32, on_time_rate: 93.8, score: 79.9 },
    { role: 'Branch Relationship Officer with a deliberately long readable role label', label: 'BRO', branch: 'Embu', product: 'Standard HomeBiogas', ranked: false, rank: null, completed: 16, on_time_rate: 87.5, score: 64.1 },
  ],
  people_rows: [], people_visible: false, technical_details_visible: false, methodology: null,
};

async function mount(page, payload = ordinaryPayload) {
  await page.setContent(recognitionMarkup);
  await page.addStyleTag({ path: asset('base.css') });
  await page.addStyleTag({ path: asset('tat_tracker.css') });
  await page.addScriptTag({ content: `
    const $ = id => document.getElementById(id);
    const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, character => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[character]));
    const formatTatDateTime = () => '17-09-2026 10:45';
    ${recognitionRenderer}
    window.renderTatRecognitionForTest = renderTatRecognition;
  ` });
  await page.evaluate(value => window.renderTatRecognitionForTest(value), payload);
}

for (const viewport of [
  { width: 320, height: 568 },
  { width: 360, height: 800 },
  { width: 430, height: 932 },
]) {
  test(`ordinary recognition is compact and readable at ${viewport.width}x${viewport.height}`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await mount(page);

    await expect(page.locator('#tatPersonalRecognition')).toContainText('Your result this month');
    await expect(page.locator('#tatRecognitionUpdated')).toHaveText('Updated at 17-09-2026 10:45');
    await expect(page.locator('#tatPersonalRecognition')).toContainText('16 of 20 counted stages');
    await expect(page.locator('#tatPersonalRecognition')).toContainText('Complete 4 more counted stages');
    await expect(page.locator('.recognition-row').first()).toContainText('93.8% On time');
    await expect(page.locator('.recognition-row').first()).toContainText('32 Stages');
    await expect(page.locator('#tatRecognitionTechnical')).toBeHidden();
    await expect(page.locator('#tatPeopleRecognitionSection')).toBeHidden();
    expect(await page.locator('body').innerText()).not.toMatch(/Wilson|quality floor|legacy actor|corrected records|workflow group/i);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(viewport.width);

    const firstRow = page.locator('.recognition-row').first();
    const box = await firstRow.boundingBox();
    expect(box.y).toBeLessThan(viewport.height);
    expect(box.height).toBeLessThanOrEqual(90);
    const role = page.locator('.recognition-row-main > strong').last();
    const roleMetrics = await role.evaluate(node => {
      const style = getComputedStyle(node);
      return { height: node.getBoundingClientRect().height, lineHeight: parseFloat(style.lineHeight), fontSize: parseFloat(style.fontSize) };
    });
    expect(roleMetrics.height).toBeLessThanOrEqual(roleMetrics.lineHeight * 2 + 1);
    expect(roleMetrics.fontSize).toBeGreaterThanOrEqual(12);
    expect(await page.locator('.recognition-row-metrics').first().evaluate(node => parseFloat(getComputedStyle(node).fontSize))).toBeGreaterThanOrEqual(11);
  });
}

test('management can inspect one collapsed methodology section and named rows', async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 800 });
  await mount(page, {
    ...ordinaryPayload,
    people_visible: true,
    technical_details_visible: true,
    people_rows: [{ label: 'Mary Wanjiku', role: 'BRO', branch: 'Embu', product: 'Standard', ranked: true, rank: 2, completed: 24, on_time_rate: 87.5, score: 68.4 }],
    methodology: {
      score_method: 'The performance score is the 95% Wilson lower bound.',
      cohort_basis: 'Like-for-like comparison.', correction_policy: 'Audited corrections update live results.',
      late_work_policy: 'Late work does not count as on time.', completed_total: 30, counted_total: 28,
      excluded_target_unavailable: 2, corrected: 1, attribution_fallback: 0, overdue_recovered: 3,
    },
  });

  await expect(page.locator('#tatPeopleRecognitionSection')).toBeVisible();
  await expect(page.locator('#tatPeopleRecognition')).toContainText('Mary Wanjiku');
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
  expect(await page.locator('.recognition-result-card').evaluate(node => getComputedStyle(node).backgroundColor)).not.toBe('rgb(255, 255, 255)');
});

test('recognition empty states use plain language', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 568 });
  await mount(page, { ...ordinaryPayload, personal_rows: [], team_rows: [] });
  await expect(page.locator('#tatPersonalRecognition')).toContainText('Your result will appear after you complete a stage.');
  await expect(page.locator('#tatTeamRecognition')).toContainText('No counted stages for this month');
});
