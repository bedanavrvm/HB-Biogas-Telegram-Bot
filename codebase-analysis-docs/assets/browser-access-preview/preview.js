'use strict';

// Static review content only. No API, credentials, storage, SDK or analytics.
(() => {
  const page = document.getElementById('page');
  const screenPicker = document.getElementById('screen-picker');
  const scenarioPicker = document.getElementById('scenario-picker');
  const announcer = document.getElementById('announcer');
  let current = 'login';
  let recoveryMode = false;
  let recoveryViewed = false;
  let showCodesOnNextRender = false;
  let busy = false;
  let pending = null;

  const field = (id, label, value, type = 'text', hint = '') => `<div class="field"><label for="${id}">${label}</label><input id="${id}" type="${type}" value="${value}" readonly autocomplete="off" aria-describedby="${id}-hint"><p class="hint" id="${id}-hint">${hint || 'Fixed demo value. Do not enter real credentials.'}</p></div>`;
  const heading = (step, title, description) => `<p class="step">${step}</p><h2 id="page-heading" tabindex="-1">${title}</h2><p class="description">${description}</p><div id="feedback" class="feedback" role="alert" hidden></div>`;
  const action = (key, label) => `<button class="primary wide" type="submit" data-action="${key}">${label}</button>`;
  const links = '<div class="links"><a href="#login">Back to sign in</a><a href="#help">Get access help</a></div>';
  const messages = {
    invalid: ['We could not verify these details', 'Check your details and try again. If you need help, contact your administrator.'],
    unavailable: ['This service is temporarily unavailable', 'Your access has not been confirmed. Try again shortly or contact your administrator.'],
    limited: ['Please wait before trying again', 'There have been too many attempts. In the working client, the server determines when you can retry.'],
    expired: ['This session or setup link has expired', 'Return to sign in. For an interrupted account setup, contact your administrator; do not create another account.'],
  };
  const screens = {
    login: () => heading('Welcome back', 'Sign in to your workspace', 'Use your existing staff account. Browser access must first be enabled by your administrator.') +
      `<form>${field('username', 'Staff username', 'demo.staff')}${field('password', 'Password', 'demo-only', 'password')}${action('login', 'Sign in with demo account')}</form><div class="links"><a href="#setup">First time here? Set up your account</a><a href="#help">Trouble signing in?</a></div>`,
    setup: () => heading('Account setup · 1 of 2', 'Verify your setup link', 'Account setup is for an existing staff account. You will need a setup link from the approved onboarding process.') +
      '<div class="notice"><strong>Demo link ready to review</strong><p>No email has been sent. Proof delivery is not yet connected. This button simulates a valid link being verified in this browser.</p></div>' +
      `<form>${action('verify', 'Verify demo setup link')}</form>${links}`,
    password: () => heading('Account setup · 2 of 2', 'Choose your first password', 'After your mailbox is verified, set a password for your existing account. You will sign in separately to set up your authenticator.') +
      `<form>${field('new-password', 'New password', 'demo-password-only', 'password', 'Password rules will be enforced by the server. This field is a fixed demo value.')}${field('confirm-password', 'Confirm new password', 'demo-password-only', 'password')}${action('password', 'Save demo password')}</form>${links}`,
    mfa: () => heading('Sign in · Security check', recoveryMode ? 'Use a recovery code' : 'Check your authenticator', recoveryMode ? 'Use one of your saved recovery codes. Each code can only be used once.' : 'Enter the current code from your authenticator app to finish signing in.') +
      `<form>${field('mfa-code', recoveryMode ? 'Recovery code' : 'Authenticator code', recoveryMode ? 'DEMO-CODE-ONLY' : '000000', 'text', 'Preview value only; this cannot authenticate an account.')}${action('mfa', 'Verify demo code')}</form><div class="links"><button type="button" class="text-button" data-action="toggle-recovery">${recoveryMode ? 'Use authenticator instead' : 'Use a recovery code instead'}</button><a href="#login">Cancel sign in</a></div>`,
    enroll: () => heading('Secure your account · 1 of 2', 'Set up your authenticator', 'Confirm your password, then add the account to your authenticator app. Setup alone does not sign you in.') +
      `<form>${field('recheck-password', 'Confirm your password', 'demo-only', 'password')}${action('begin-enrollment', 'Continue with demo password')}</form>${links}`,
    scan: () => heading('Secure your account · 1 of 2', 'Add your staff account', 'Scan the setup code with your authenticator app, then enter the current code to confirm.') +
      `<div class="auth-placeholder"><strong>Authenticator setup placeholder</strong>The working client will display a protected setup code here. This preview contains no QR code, secret or usable enrollment link.</div><form>${field('enrollment-code', 'Authenticator code', '000000', 'text', 'Preview value only; no authenticator is activated.')}${action('confirm-enrollment', 'Confirm demo authenticator')}</form>${links}`,
    recovery: () => heading('Secure your account · 2 of 2', 'Save your recovery codes', 'Keep your recovery codes somewhere private. They provide access if your authenticator is unavailable.') +
      (recoveryViewed ? '<div class="notice"><strong>Codes have already been shown</strong><p>The working service does not show them again. If they were lost, use your authenticator to sign in and follow the approved support process.</p></div><button type="button" class="primary wide" data-action="finish-enrollment">Return to sign in</button>' :
        `<div class="notice"><strong>One viewing only</strong><p>Request your codes when you are ready to save them. If the response is lost, they cannot be requested again through this handoff.</p></div><form>${action('view-recovery', 'Show demo recovery codes once')}</form>`) + links,
    codes: () => heading('Secure your account · 2 of 2', 'Store these somewhere safe', 'These are deliberately invalid demo labels. The working service reveals real recovery codes only once.') +
      '<ul class="codes" aria-label="Invalid demo recovery codes"><li>DEMO · CODE 01</li><li>DEMO · CODE 02</li><li>DEMO · CODE 03</li><li>DEMO · CODE 04</li></ul><p class="description">After saving your codes, sign out and sign in again with your password and authenticator.</p><button type="button" class="primary wide" data-action="finish-enrollment">I saved the demo codes · continue</button>',
    reauthenticate: () => heading('Setup complete · Sign in required', 'Your next step is to sign in', 'Account setup and authenticator enrollment do not open your workspace. Complete a fresh password and MFA sign-in.') +
      '<a class="back" href="#login">Continue to sign in →</a><div class="notice">This is a simulated completion state. No password, mailbox or authenticator has changed.</div>',
    shell: () => heading('Staff workspace · Demo session', 'Welcome to your workspace', 'Signing in confirms your identity. Each tool separately checks your current role and scope.') +
      '<div class="notice"><strong>Business tools are not connected</strong><p>This preview contains no workflow records or permissions. Complaints is the first planned pilot; the other tools follow separate reviews.</p></div><div class="apps">' +
      ['Complaints', 'TAT Tracker', 'Loan Origination', 'Jawabu Portal'].map((name, i) => `<article class="app-card"><p>0${i + 1} · ${i ? 'Later review' : 'First planned pilot'}</p><h3>${name}</h3><button type="button" disabled>Not connected</button></article>`).join('') +
      '<button type="button" data-action="logout">Sign out of demo</button>',
    help: () => heading('Staff access', 'Get help with your account', 'Contact your company administrator using your existing internal support channel. Do not send passwords, authenticator secrets or recovery codes.') +
      '<ul class="support-list"><li><strong>New to browser access?</strong> Ask your administrator to enable access for your existing staff account.</li><li><strong>Setup link expired or interrupted?</strong> Ask for assistance. Do not create a second account or change your verified address.</li><li><strong>Authenticator unavailable?</strong> Use a saved recovery code. If you cannot, follow the approved identity-verification process.</li></ul><div class="notice">Support ownership, setup delivery and recovery procedures still need operational acceptance. This page does not submit a support request.</div>' + links,
  };

  function render(screen, focus = true) {
    if (pending !== null) window.clearTimeout(pending);
    pending = null;
    busy = false;
    current = Object.hasOwn(screens, screen) ? screen : 'login';
    if (current === 'login') recoveryMode = false;
    // A one-time viewing cannot be replayed using Back or a direct hash.
    if (current === 'codes' && !showCodesOnNextRender) current = 'recovery';
    showCodesOnNextRender = false;
    page.innerHTML = screens[current]();
    page.classList.toggle('shell', current === 'shell');
    page.removeAttribute('aria-busy');
    screenPicker.value = current === 'scan' ? 'enroll' : current === 'codes' ? 'recovery' : current;
    document.title = `${document.getElementById('page-heading').textContent} · JBL preview`;
    if (focus) document.getElementById('page-heading').focus();
  }

  function navigate(screen) {
    if (window.location.hash.slice(1) === screen) render(screen);
    else window.location.hash = screen;
  }

  function feedback(kind) {
    const node = document.getElementById('feedback');
    const message = messages[kind];
    node.replaceChildren();
    const title = document.createElement('strong');
    title.textContent = message[0];
    const description = document.createElement('p');
    description.textContent = message[1];
    node.append(title, description);
    if (kind === 'expired') {
      const link = document.createElement('a');
      link.href = '#help';
      link.textContent = 'Get access help';
      node.append(link);
    }
    node.hidden = false;
  }

  function simulate(key, button) {
    if (busy) return;
    if (key === 'toggle-recovery') {
      recoveryMode = !recoveryMode;
      render('mfa');
      return;
    }
    if (key === 'logout' || key === 'finish-enrollment') {
      navigate(key === 'logout' ? 'login' : 'reauthenticate');
      return;
    }
    const originalLabel = button.textContent;
    const requestedScreen = current;
    const scenario = scenarioPicker.value;
    busy = true;
    button.disabled = true;
    button.textContent = 'Checking demo response…';
    page.setAttribute('aria-busy', 'true');
    announcer.textContent = 'Simulating a response. No request is sent.';
    pending = window.setTimeout(() => {
      pending = null;
      busy = false;
      page.removeAttribute('aria-busy');
      if (current !== requestedScreen) return;
      button.disabled = false;
      button.textContent = originalLabel;
      if (Object.hasOwn(messages, scenario)) {
        feedback(scenario);
        announcer.textContent = '';
        return;
      }
      const next = {
        login: scenario === 'enrollment' ? 'enroll' : 'mfa',
        verify: 'password', password: 'reauthenticate', mfa: 'shell',
        'begin-enrollment': 'scan', 'confirm-enrollment': 'recovery',
        'view-recovery': 'codes',
      }[key];
      if (next === 'codes') {
        recoveryViewed = true;
        showCodesOnNextRender = true;
        navigate('codes');
      } else if (next) navigate(next);
      announcer.textContent = 'Demo response complete.';
    }, 450);
  }

  page.addEventListener('submit', (event) => {
    event.preventDefault();
    const button = event.submitter;
    if (button && button.dataset.action) simulate(button.dataset.action, button);
  });
  page.addEventListener('click', (event) => {
    const button = event.target.closest('button[data-action]');
    if (button && button.type !== 'submit') simulate(button.dataset.action, button);
  });
  screenPicker.addEventListener('change', () => navigate(screenPicker.value));
  document.getElementById('theme-picker').addEventListener('change', (event) => {
    if (event.target.value === 'system') delete document.documentElement.dataset.theme;
    else document.documentElement.dataset.theme = event.target.value;
  });
  document.getElementById('reset-preview').addEventListener('click', () => {
    recoveryMode = false;
    recoveryViewed = false;
    showCodesOnNextRender = false;
    scenarioPicker.value = 'success';
    navigate('login');
    announcer.textContent = 'Demo reset.';
  });
  window.addEventListener('hashchange', () => {
    const screen = window.location.hash.slice(1);
    if (screen !== 'content') render(screen);
  });
  render(window.location.hash.slice(1), false);
})();
