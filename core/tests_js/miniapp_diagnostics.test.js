'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(
  path.join(__dirname, '..', 'static', 'miniapp', 'diagnostics.js'),
  'utf8'
);
const storageValues = new Map();

function launch(options) {
  const listeners = {};
  const documentListeners = {};
  const localStorage = options && options.brokenStorage ? {
    getItem() { throw new Error('storage denied'); },
    setItem() { throw new Error('storage denied'); }
  } : {
    getItem(key) { return storageValues.get(key) || null; },
    setItem(key, value) { storageValues.set(key, value); }
  };
  function Xhr() {}
  Xhr.prototype.open = function () {};
  Xhr.prototype.setRequestHeader = function () {};
  Xhr.prototype.send = function () {};
  const document = {
    visibilityState: 'visible',
    addEventListener(name, callback) { documentListeners[name] = callback; }
  };
  const window = {
    MINIAPP_DIAGNOSTICS_CONFIG: { enabled: true, heartbeatSeconds: 60 },
    Telegram: { WebApp: { platform: 'android', initData: 'signed', close() {} } },
    location: { pathname: '/api/portal/' },
    localStorage,
    crypto: { randomUUID: () => require('node:crypto').randomUUID() },
    fetch: () => Promise.reject(new Error('offline')),
    addEventListener(name, callback) { listeners[name] = callback; },
    setTimeout() { return 1; },
    clearTimeout() {},
    setInterval() { return 2; },
    clearInterval() {},
    Sentry: options && options.brokenSentry ? { init() { throw new Error('sdk failed'); } } : undefined
  };
  window.window = window;
  const context = {
    window, document,
    navigator: { onLine: false, deviceMemory: 2 },
    XMLHttpRequest: Xhr,
    Headers: class { get() { return ''; } },
    Blob: class {},
    Promise, Set, Math, Date, JSON, Number, String, Array, Object,
    encodeURIComponent
  };
  vm.runInNewContext(source, context, { filename: 'diagnostics.js' });
  return { window, document, listeners, documentListeners };
}

storageValues.clear();
launch();
launch();
const third = launch();
let persisted = JSON.parse(storageValues.get('jbl-miniapp-diagnostics-v1'));
assert.equal(persisted.sessions.length, 3, 'two consecutive offline relaunches remain queued');
assert.ok(
  persisted.sessions.slice(0, 2).every((session) => session.recovery_event_added),
  'each previous offline launch receives one durable recovery marker'
);

third.document.visibilityState = 'hidden';
third.documentListeners.visibilitychange();
third.document.visibilityState = 'visible';
third.documentListeners.visibilitychange();
persisted = JSON.parse(storageValues.get('jbl-miniapp-diagnostics-v1'));
const lifecycle = persisted.sessions[persisted.sessions.length - 1].events.map((event) => event.event_type);
assert.deepEqual(lifecycle.slice(-2), ['backgrounded', 'resumed']);
assert.equal(persisted.sessions[persisted.sessions.length - 1].last_visibility, 'visible');

const hiddenSession = persisted.sessions[persisted.sessions.length - 1];
const hiddenUuid = hiddenSession.session_uuid;
hiddenSession.events = [];
hiddenSession.last_visibility = 'hidden';
hiddenSession.recovery_event_added = false;
storageValues.set('jbl-miniapp-diagnostics-v1', JSON.stringify(persisted));
launch();
persisted = JSON.parse(storageValues.get('jbl-miniapp-diagnostics-v1'));
const recoveredHidden = persisted.sessions.find((session) => session.session_uuid === hiddenUuid);
assert.equal(recoveredHidden.events[0].event_type, 'recovery_complete');
assert.equal(recoveredHidden.events[0].visibility, 'hidden', 'acked background state survives relaunch');

assert.doesNotThrow(() => launch({ brokenStorage: true, brokenSentry: true }));
assert.equal(typeof third.window.MiniAppDiagnostics.intentionalClose, 'function');

console.log('miniapp diagnostics client tests passed');
