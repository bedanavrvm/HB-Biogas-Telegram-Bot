'use strict';
// Only launched by the isolated LiveServer test; native proof is stdin-only.
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const readline = require('node:readline');
const { chromium } = require('playwright');

async function main() {
  const lines = readline.createInterface({ input: process.stdin })[Symbol.asyncIterator]();
  const input = JSON.parse((await lines.next()).value);
  const root = path.resolve(__dirname, '..');
  const manifest = JSON.parse(fs.readFileSync(path.join(root, 'browser', input.build, 'build-manifest.json')));
  assert.equal(manifest.closedComplaints, true); assert.equal(manifest.closedAuthentication, true); assert.equal(manifest.demoOnly, false);
  const origin = new URL(input.origin);
  assert.ok(['localhost', '127.0.0.1'].includes(origin.hostname));
  const output = path.join(root, 'test-results', 'complaints-browser-transport', manifest.mode);
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1280, height: 720 }, colorScheme: 'light' });
  const page = await context.newPage(); page.setDefaultTimeout(15000);
  const errors = [], captures = [], layouts = [], requests = [];
  let checks = 0;
  const base = '/api/staff/complaints/v1/';
  const queuePath = `${base}groups/${input.group}/cases/`;
  const allowed = new Set(['/', ...manifest.files.map(row => '/' + row.name), ...['session', 'login', 'mfa', 'logout', 'enrollment/session', 'setup/session'].map(name => '/api/staff/auth/v1/' + name + '/')]);
  await context.route('**/*', async route => {
    const request = route.request(), url = new URL(request.url());
    const read = url.pathname.startsWith(base) && (url.pathname === base + 'groups/' || /^\/api\/staff\/complaints\/v1\/groups\/\d+\/cases\/(?:[\da-f-]+\/)?$/.test(url.pathname));
    if (url.origin === origin.origin && ((allowed.has(url.pathname) && !url.search && ['GET', 'POST'].includes(request.method())) || (read && ['GET', 'POST'].includes(request.method()) && [...url.searchParams.keys()].every(key => ['q', 'status', 'page'].includes(key))))) await route.continue();
    else { errors.push('Unexpected network destination or path'); await route.abort(); }
  });
  page.on('request', request => { const url = new URL(request.url()); requests.push({ path: url.pathname, method: request.method() }); });
  page.on('pageerror', () => errors.push('Unhandled browser exception'));
  page.on('console', message => { if (message.type() === 'error' && !message.text().startsWith('Failed to load resource:')) errors.push('Unexpected browser console error'); });
  const control = async command => { process.stdout.write(JSON.stringify({ control: command }) + '\n'); assert.equal(JSON.parse((await lines.next()).value).ok, true); };
  const heading = name => page.getByRole('heading', { level: 1, name, exact: true }).waitFor();
  const read = async pathname => page.evaluate(async url => { const response = await fetch(url, { cache: 'no-store' }); return { status: response.status, data: await response.json(), cache: response.headers.get('Cache-Control') }; }, pathname);
  const capture = async name => {
    const theme = name.includes('-dark-') ? 'dark' : name.includes('-light-') ? 'light' : null;
    if (theme) await page.waitForFunction(expected => document.documentElement.dataset.colorMode === expected, theme);
    await page.evaluate(async () => {
      await Promise.all(document.getAnimations().filter(animation => animation.effect?.getComputedTiming().iterations !== Infinity).map(animation => animation.finished.catch(() => {})));
      await new Promise(requestAnimationFrame); await new Promise(requestAnimationFrame);
    });
    assert.equal(await page.locator('input[type=password],input[name=code]').count(), 0);
    const metrics = await page.getByTestId('complaints-content').evaluate(el => ({ theme: document.documentElement.dataset.colorMode, width: innerWidth, height: innerHeight, pageWidth: document.documentElement.scrollWidth, pageHeight: document.documentElement.scrollHeight, mainWidth: el.parentElement.clientWidth, mainHeight: el.parentElement.clientHeight, mainScrollHeight: el.parentElement.scrollHeight }));
    assert.ok(metrics.pageWidth <= metrics.width, 'No horizontal clipping');
    layouts.push({ name, ...metrics });
    fs.writeFileSync(path.join(output, 'layout-diagnostic.json'), JSON.stringify(await page.getByTestId('complaints-content').evaluate(el => {
      const rows = [];
      for (let current = el; current; current = current.parentElement) {
        const style = getComputedStyle(current);
        rows.push({ tag: current.tagName, classes: current.className, width: current.getBoundingClientRect().width, maxWidth: style.maxWidth, columns: style.gridTemplateColumns });
      }
      return rows;
    }), null, 2));
    await page.screenshot({ path: path.join(output, name), fullPage: true }); captures.push(name);
  };
  const signIn = async index => {
    await heading('Sign in');
    await page.getByLabel(/^Staff username\s*\*?$/).fill(input.username);
    await page.getByLabel(/^Password\s*\*?$/).fill(input.password);
    await page.getByRole('button', { name: 'Sign in', exact: true }).click(); await heading('Check your authenticator');
    assert.equal((await read(queuePath)).status, 401); checks++;
    await page.getByRole('button', { name: 'Use a recovery code', exact: true }).click();
    await page.getByLabel(/^Recovery code\s*\*?$/).fill(input.codes[index]);
    await page.getByRole('button', { name: 'Verify', exact: true }).click(); await heading('Complaints');
  };
  const loaded = async () => {
    await page.getByRole('heading', { name: '7 cases', exact: true }).waitFor();
    await page.getByRole('heading', { name: 'Synthetic Customer 00', exact: true }).waitFor();
  };
  try {
    await page.goto(origin.origin); await heading('Sign in');
    assert.equal((await read(queuePath)).status, 401); checks++;
    await signIn(0); await loaded();
    const result = await read(queuePath);
    assert.equal(result.status, 200); assert.equal(result.data.items.length, 5); assert.equal(result.cache, 'no-store, private');
    assert.equal(result.data.pagination.total, 7); checks++;
    const first = result.data.items[0];
    const detail = await read(queuePath + first.key + '/');
    assert.equal(detail.status, 200); assert.equal(detail.data.case.history[0].action, 'commented');
    for (const forbidden of ['EXCLUDED', '0000000000', '999999999999', 'case_id', 'customer_phone', 'customer_id', 'evidence', 'gps_link']) assert.ok(!JSON.stringify([result.data, detail.data]).includes(forbidden)); checks++;
    await page.getByText('Resolution comment added', { exact: true }).waitFor();
    await capture('queue-detail-light-1280.png');
    assert.ok(layouts.at(-1).mainWidth >= 1279 && layouts.at(-1).pageHeight <= 721 && layouts.at(-1).mainScrollHeight <= layouts.at(-1).mainHeight + 1, 'Normal laptop queue/detail fill the width and fit'); checks++;
    assert.equal((await read(`${base}groups/${input.other}/cases/`)).status, 403);
    assert.equal((await read(queuePath + input.foreign + '/')).status, 404); checks++;
    await page.getByRole('button', { name: 'Next', exact: true }).click();
    await page.getByText('Page 2 of 2', { exact: true }).waitFor();
    assert.equal(await page.getByRole('region', { name: 'Complaint queue' }).getByRole('button', { name: /^CMP-/ }).count(), 2); checks++;
    await page.getByRole('button', { name: 'Previous', exact: true }).click(); await loaded();
    await page.getByLabel('Search name or reference').fill('Customer 03'); await page.getByRole('button', { name: 'Search', exact: true }).click();
    await page.getByRole('heading', { name: '1 case', exact: true }).waitFor();
    await page.getByRole('heading', { name: 'Synthetic Customer 03', exact: true }).waitFor(); checks++;
    await page.getByRole('button', { name: 'Refresh', exact: true }).click();
    await page.getByRole('heading', { name: 'Synthetic Customer 03', exact: true }).waitFor();
    assert.equal(await page.getByLabel('Search name or reference').inputValue(), 'Customer 03'); checks++;
    await page.getByLabel('Search name or reference').fill('No matching customer'); await page.getByRole('button', { name: 'Search', exact: true }).click();
    await page.getByRole('heading', { name: '0 cases', exact: true }).waitFor(); await capture('empty-light-1280.png'); checks++;
    await page.getByLabel('Search name or reference').fill(''); await page.getByRole('button', { name: 'Search', exact: true }).click(); await loaded();
    await page.getByLabel('Status', { exact: true }).focus(); await page.keyboard.press('ArrowDown'); await page.keyboard.press('ArrowDown'); await page.keyboard.press('Enter');
    await page.getByRole('heading', { name: '1 case', exact: true }).waitFor();
    await page.getByRole('heading', { name: 'Synthetic Customer 08', exact: true }).waitFor(); checks++;
    await page.getByLabel('Status', { exact: true }).focus(); await page.keyboard.press('ArrowDown'); await page.keyboard.press('Home'); await page.keyboard.press('Enter'); await loaded();
    // A superseded response must not replace the newly selected case.
    let release, held;
    const released = new Promise(resolve => { release = resolve; });
    const intercepted = new Promise(resolve => { held = resolve; });
    const secondPath = queuePath + result.data.items[1].key + '/';
    const delay = async route => { const response = await route.fetch(); held(); await released; await route.fulfill({ response }).catch(() => {}); };
    await page.route('**' + secondPath, delay);
    await page.getByRole('region', { name: 'Complaint queue' }).getByRole('button', { name: result.data.items[1].reference, exact: true }).click(); await intercepted;
    await page.getByRole('region', { name: 'Complaint queue' }).getByRole('button', { name: result.data.items[2].reference, exact: true }).click();
    await page.getByRole('heading', { name: 'Synthetic Customer 02', exact: true }).waitFor(); release();
    await page.unroute('**' + secondPath, delay); assert.equal(await page.getByRole('heading', { name: 'Synthetic Customer 01', exact: true }).count(), 0); checks++;
    await page.getByRole('region', { name: 'Complaint queue' }).getByRole('button', { name: first.reference, exact: true }).click(); await loaded();
    await page.emulateMedia({ colorScheme: 'dark' }); await capture('queue-detail-dark-1280.png'); checks++;
    await page.setViewportSize({ width: 390, height: 844 }); await capture('queue-detail-dark-mobile.png');
    await page.getByRole('region', { name: 'Case detail' }).scrollIntoViewIfNeeded(); await capture('detail-dark-mobile.png');
    await page.emulateMedia({ colorScheme: 'light' });
    await page.getByRole('heading', { name: 'Complaints', exact: true }).scrollIntoViewIfNeeded(); await capture('queue-detail-light-mobile.png');
    await page.getByRole('region', { name: 'Case detail' }).scrollIntoViewIfNeeded(); await capture('detail-light-mobile.png'); checks++;
    await page.setViewportSize({ width: 640, height: 360 }); await capture('queue-detail-200-percent-reflow.png');
    await page.getByRole('heading', { name: 'History', exact: true }).scrollIntoViewIfNeeded(); checks++;
    await page.setViewportSize({ width: 1280, height: 720 });
    await page.getByRole('region', { name: 'Complaint queue' }).getByRole('button', { name: result.data.items[1].reference, exact: true }).focus();
    await page.keyboard.press('Enter'); await page.getByRole('heading', { name: 'Synthetic Customer 01', exact: true }).waitFor(); checks++;
    const failList = route => route.fulfill({ status: 503, contentType: 'application/json', body: '{"error":"unavailable"}' });
    await page.route('**' + queuePath + '?*', failList);
    await page.getByRole('button', { name: 'Refresh', exact: true }).click();
    await page.getByRole('alert').waitFor();
    assert.equal(await page.getByRole('heading', { name: 'Synthetic Customer 00', exact: true }).count(), 0);
    await capture('failure-light-1280.png'); checks++;
    await page.emulateMedia({ colorScheme: 'dark' }); await capture('failure-dark-1280.png');
    await page.setViewportSize({ width: 390, height: 844 }); await capture('failure-dark-mobile.png');
    await page.emulateMedia({ colorScheme: 'light' }); await capture('failure-light-mobile.png');
    await page.unroute('**' + queuePath + '?*', failList);
    await page.setViewportSize({ width: 1280, height: 720 });
    await page.getByRole('button', { name: 'Refresh', exact: true }).click(); await loaded(); checks++;
    const loginCount = requests.filter(row => row.path.endsWith('/login/') && row.method === 'POST').length;
    await page.reload(); await heading('Complaints'); await loaded();
    await capture('resumed-light-1280.png');
    assert.ok(layouts.at(-1).mainWidth >= 1279 && layouts.at(-1).mainScrollHeight <= layouts.at(-1).mainHeight + 1);
    assert.equal(await page.title(), 'Complaints - JBL staff workspace');
    assert.equal(requests.filter(row => row.path.endsWith('/login/') && row.method === 'POST').length, loginCount); checks++;
    await control('revoke_browser');
    await page.getByRole('button', { name: 'Refresh', exact: true }).click(); await heading('Sign in');
    assert.equal(await page.getByTestId('complaints-content').count(), 0); checks++;
    await signIn(1); await loaded();
    await control('revoke_workflow');
    assert.equal((await read(queuePath)).status, 403); checks++;
    await page.getByRole('button', { name: 'Refresh', exact: true }).click();
    await page.getByRole('heading', { name: 'No Complaints workspace available', exact: true }).waitFor();
    assert.equal(await page.getByRole('heading', { name: 'Synthetic Customer 00', exact: true }).count(), 0); await capture('no-access-light-1280.png'); checks++;
    assert.deepEqual(await page.evaluate(() => [localStorage.length, sessionStorage.length]), [0, 0]);
    assert.equal(requests.filter(row => row.path.startsWith(base) && row.method !== 'GET').length, 0); checks++;
    assert.deepEqual(errors, []);
    const sources = [...manifest.sources, ...['scripts/test_complaints_browser_transport.js', 'core/api/browser_complaint_views.py', 'core/api/browser_complaint_urls.py', 'core/services/complaint_cases.py', 'core/services/telegram_identity.py', 'core/services/workflow_access.py', 'core/services/access_control.py', 'core/tests_browser_complaints.py', 'config/settings.py', 'staff_auth/abuse.py', 'staff_auth/cache_keys.py', 'staff_auth/checks.py', 'staff_auth/browser_api.py', 'staff_auth/assurance.py', 'staff_auth/replay.py', 'staff_auth/enrollment.py', 'staff_auth/enrollment_state.py', 'staff_auth/setup_api.py', 'staff_auth/initial_setup.py', 'staff_auth/session_protection.py', 'staff_auth/tests_complaints_transport.py', 'staff_auth/complaints_transport_test_urls.py', 'staff_auth/transport_test_urls.py', 'staff_auth/transport_test_settings.py', 'staff_auth/transport_test_runner.py'].map(source => ({ path: source, sha256: crypto.createHash('sha256').update(fs.readFileSync(path.join(root, source), 'utf8').replace(/\r\n/g, '\n')).digest('hex') }))];
    fs.writeFileSync(path.join(output, 'report.json'), JSON.stringify({ candidateOnly: true, operationalAcceptance: false, dependencyLock: manifest.dependencyLock, mode: manifest.mode, checks, captures, layouts, sources, errors }, null, 2));
    process.stdout.write(JSON.stringify({ passed: true, checks, captures: captures.length }) + '\n');
  } finally { await browser.close(); }
}
main().catch(error => { console.error(error.stack); process.exit(1); });
