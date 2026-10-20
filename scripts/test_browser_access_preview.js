'use strict';

// Exercise the synthetic wireframe using the repository's existing Playwright.
// Start scripts/serve_browser_access_preview.py first. No application DB is used.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { createHash } = require('node:crypto');
const { chromium } = require('playwright');

async function main() {
  const base = 'http://127.0.0.1:8765/';
  const output = path.resolve(__dirname, '../test-results/browser-access-preview');
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const errors = [];
  const requests = [];
  const captures = [];
  let checks = 0;
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const page = await context.newPage();
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
  page.on('request', request => requests.push({ url: request.url(), method: request.method() }));
  // A defect attempting non-preview I/O is blocked and recorded as a failure.
  await context.route('**/*', async route => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.origin === new URL(base).origin && ['/', '/preview.css', '/preview.js'].includes(url.pathname) && request.method() === 'GET') await route.continue();
    else { errors.push(`Unexpected request: ${url.origin}${url.pathname}`); await route.abort(); }
  });
  const heading = title => page.getByRole('heading', { level: 2, name: title, exact: true }).waitFor();
  const choosePage = async screen => {
    await page.locator('#screen-picker').selectOption(screen);
    await page.waitForFunction(value => document.getElementById('screen-picker').value === value && !document.getElementById('page').hasAttribute('aria-busy'), screen);
    await page.waitForTimeout(30);
  };
  try {
    await page.goto(base);
    await heading('Sign in to your workspace');
    // Normal sign-in and per-tool authority boundary.
    await page.getByRole('button', { name: 'Sign in with demo account' }).click();
    await heading('Check your authenticator');
    await page.getByRole('button', { name: 'Use a recovery code instead' }).click();
    await heading('Use a recovery code');
    await page.getByRole('button', { name: 'Verify demo code' }).click();
    await heading('Welcome to your workspace');
    assert.equal(await page.locator('.app-card button:disabled').count(), 4);
    await page.getByRole('button', { name: 'Sign out of demo' }).click();
    await heading('Sign in to your workspace');
    checks += 1;

    // Initial setup must return to login rather than issue a signed-in state.
    await page.getByRole('link', { name: 'First time here? Set up your account' }).click();
    await heading('Verify your setup link');
    await page.getByRole('button', { name: 'Verify demo setup link' }).click();
    await heading('Choose your first password');
    await page.getByRole('button', { name: 'Save demo password' }).click();
    await heading('Your next step is to sign in');
    checks += 1;

    // Enrollment includes a fresh password check and one-time code viewing.
    await choosePage('login');
    await page.locator('#scenario-picker').selectOption('enrollment');
    await page.getByRole('button', { name: 'Sign in with demo account' }).click();
    await heading('Set up your authenticator');
    await page.locator('#scenario-picker').selectOption('success');
    await page.getByRole('button', { name: 'Continue with demo password' }).click();
    await heading('Add your staff account');
    await page.getByRole('button', { name: 'Confirm demo authenticator' }).click();
    await heading('Save your recovery codes');
    await page.getByRole('button', { name: 'Show demo recovery codes once' }).click();
    await heading('Store these somewhere safe');
    assert.equal(await page.locator('.codes li').count(), 4);
    await page.getByRole('button', { name: 'I saved the demo codes · continue' }).click();
    await heading('Your next step is to sign in');
    await choosePage('recovery');
    assert.equal(await page.getByText('Codes have already been shown').count(), 1);
    assert.equal(await page.locator('.codes').count(), 0);
    await page.goto(`${base}#codes`);
    await heading('Save your recovery codes');
    assert.equal(await page.locator('.codes').count(), 0);
    checks += 1;

    // Error/retry states retain the current page and cannot claim a login.
    for (const scenario of ['invalid', 'unavailable', 'limited', 'expired']) {
      await choosePage('login');
      await page.locator('#scenario-picker').selectOption(scenario);
      await page.getByRole('button', { name: 'Sign in with demo account' }).click();
      await page.locator('#feedback:not([hidden])').waitFor();
      assert.equal(await page.locator('#username').inputValue(), 'demo.staff');
      assert.equal(await page.locator('#password').getAttribute('readonly'), '');
      await heading('Sign in to your workspace');
      const filename = `response-${scenario}-1440.png`;
      await page.screenshot({ path: path.join(output, filename), fullPage: true });
      captures.push(filename);
      checks += 1;
    }
    await page.locator('#scenario-picker').selectOption('success');
    await page.getByRole('button', { name: 'Sign in with demo account' }).click();
    await heading('Check your authenticator');
    checks += 1;

    // Switching pages while a simulated response is pending cancels it.
    await choosePage('login');
    await page.getByRole('button', { name: 'Sign in with demo account' }).click();
    await choosePage('help');
    await page.waitForTimeout(550);
    await heading('Get help with your account');
    checks += 1;

    // Capture source-faithful synthetic light/dark pages at phone and desktop sizes.
    const screens = ['login', 'setup', 'password', 'mfa', 'enroll', 'recovery', 'reauthenticate', 'shell', 'help'];
    for (const width of [320, 390, 1440]) {
      await page.setViewportSize({ width, height: width < 500 ? 844 : 1000 });
      for (const theme of ['light', 'dark']) {
        await page.locator('#theme-picker').selectOption(theme);
        for (const screen of screens) {
          await choosePage(screen);
          assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), `Overflow: ${screen}/${theme}/${width}`);
          for (const input of await page.locator('#page input').all()) assert.equal(await input.getAttribute('readonly'), '');
          const filename = `${screen}-${theme}-${width}.png`;
          await page.screenshot({ path: path.join(output, filename), fullPage: true });
          captures.push(filename);
          checks += 1;
        }
        await page.getByRole('button', { name: 'Reset demo' }).click();
        await choosePage('enroll');
        await page.getByRole('button', { name: 'Continue with demo password' }).click();
        await heading('Add your staff account');
        let filename = `scan-${theme}-${width}.png`;
        await page.screenshot({ path: path.join(output, filename), fullPage: true });
        captures.push(filename);
        await page.getByRole('button', { name: 'Confirm demo authenticator' }).click();
        await heading('Save your recovery codes');
        await page.getByRole('button', { name: 'Show demo recovery codes once' }).click();
        await heading('Store these somewhere safe');
        filename = `codes-${theme}-${width}.png`;
        await page.screenshot({ path: path.join(output, filename), fullPage: true });
        captures.push(filename);
        checks += 2;
      }
    }
    // Keyboard navigation has a skip link and a named page heading.
    await page.goto(base);
    await page.keyboard.press('Tab');
    assert.equal(await page.evaluate(() => document.activeElement.textContent), 'Skip to page content');
    await page.keyboard.press('Enter');
    assert.equal(await page.evaluate(() => document.activeElement.id), 'content');
    await page.locator('#screen-picker').selectOption('mfa');
    await heading('Check your authenticator');
    assert.equal(await page.evaluate(() => document.activeElement.id), 'page-heading');
    await page.keyboard.press('Tab');
    assert.equal(await page.evaluate(() => document.activeElement.id), 'mfa-code');
    checks += 1;

    // Text enlargement must retain content and avoid horizontal scrolling.
    await page.setViewportSize({ width: 390, height: 844 });
    await choosePage('login');
    await page.evaluate(() => { document.documentElement.style.fontSize = '200%'; });
    assert.ok(await page.locator('#page-heading').evaluate(node => parseFloat(getComputedStyle(node).fontSize)) >= 54);
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));
    await page.evaluate(() => { document.documentElement.style.fontSize = ''; });
    checks += 1;

    const storage = await page.evaluate(() => ({ local: localStorage.length, session: sessionStorage.length }));
    assert.deepEqual(storage, { local: 0, session: 0 });
    assert.deepEqual(await context.cookies(), []);
    assert.deepEqual(errors, []);
    checks += 1;
    const sources = ['index.html', 'preview.css', 'preview.js'].map(filename => {
      const relative = `codebase-analysis-docs/assets/browser-access-preview/${filename}`;
      const source = fs.readFileSync(path.resolve(__dirname, '..', relative), 'utf8').replace(/\r\n/g, '\n');
      return { path: relative, sha256: createHash('sha256').update(source).digest('hex') };
    });
    fs.writeFileSync(path.join(output, 'report.json'), JSON.stringify({ checks, sources, captures, requests, errors, syntheticOnly: true, humanApproval: false }, null, 2) + '\n');
    console.log(`Access preview: ${checks} checks passed; ${captures.length} synthetic screenshots; no unexpected requests, storage or cookies.`);
  } finally {
    await browser.close();
  }
}

main().catch(error => { console.error(error); process.exitCode = 1; });
