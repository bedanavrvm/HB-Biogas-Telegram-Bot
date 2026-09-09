'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(
  path.join(__dirname, '..', 'static', 'miniapp', 'runtime.js'), 'utf8'
);
let now = 0;
let nextTimer = 1;
const timers = new Map();
const nodes = new Map();
const classHistory = [];

function setTimeoutFake(callback, delay = 0) {
  const id = nextTimer++;
  timers.set(id, { callback, due: now + Number(delay || 0) });
  return id;
}
function clearTimeoutFake(id) { timers.delete(id); }
function tick(milliseconds) {
  const target = now + milliseconds;
  while (true) {
    const ready = [...timers.entries()]
      .filter(([, timer]) => timer.due <= target)
      .sort((a, b) => a[1].due - b[1].due)[0];
    if (!ready) break;
    timers.delete(ready[0]);
    now = ready[1].due;
    ready[1].callback();
  }
  now = target;
}
function element() {
  let className = '';
  const node = {
    id: '', dataset: {}, textContent: '',
    setAttribute() {},
    classList: {
      contains(value) { return className.split(/\s+/).includes(value); },
      add(value) { node.className = `${className} ${value}`.trim(); },
      remove(value) { node.className = className.split(/\s+/).filter(item => item !== value).join(' '); },
    },
  };
  Object.defineProperty(node, 'className', {
    get() { return className; },
    set(value) { className = value; classHistory.push(value); },
  });
  return node;
}

const listeners = {};
const document = {
  visibilityState: 'visible',
  documentElement: { appendChild(node) { nodes.set(node.id, node); } },
  body: { appendChild(node) { nodes.set(node.id, node); } },
  createElement: element,
  getElementById(id) { return nodes.get(id) || null; },
  addEventListener(name, callback) { listeners[name] = callback; },
  querySelectorAll() { return []; },
};
class FakeDate extends Date { static now() { return now; } }
const window = {
  window: null, document,
  fetch() { return Promise.resolve({ ok: true }); },
  performance: { now: () => now },
  setTimeout: setTimeoutFake, clearTimeout: clearTimeoutFake,
  setInterval: setTimeoutFake, clearInterval: clearTimeoutFake,
  addEventListener() {},
};
window.window = window;
vm.runInNewContext(source, {
  window, document, Date: FakeDate, Promise, Set, Math, Number, String, Array, Object,
}, { filename: 'runtime.js' });

const runtime = window.MiniAppRuntime;
runtime.beginProgress();
tick(120);
assert.equal(nodes.get('miniapp-top-progress').className, 'miniapp-top-progress is-active');
runtime.endProgress();
tick(240);
assert.equal(nodes.get('miniapp-top-progress').className, 'miniapp-top-progress is-complete');

// A request entirely inside the completion fade must not reactivate the line.
runtime.beginProgress();
tick(50);
runtime.endProgress();
tick(250);
assert.equal(nodes.get('miniapp-top-progress').className, 'miniapp-top-progress');
assert.equal(
  classHistory.filter(value => value === 'miniapp-top-progress is-active').length,
  1,
  'completion-phase requests must not produce a second flash',
);
assert.equal(typeof listeners['htmx:beforeRequest'], 'function');
assert.equal(typeof listeners['htmx:afterRequest'], 'function');

console.log('Mini App progress coalescing tests passed');
