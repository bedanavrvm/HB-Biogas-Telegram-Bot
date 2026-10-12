'use strict';

const assert = require('node:assert/strict');
const path = require('node:path');

const mediaListeners = [];
const root = { dataset: {}, style: {} };
global.document = { documentElement: root };
global.window = {
  matchMedia() {
    return {
      matches: false,
      addEventListener(name, callback) {
        if (name === 'change') mediaListeners.push(callback);
      },
    };
  },
};

require(path.join(__dirname, '..', 'static', 'miniapp', 'utils.js'));

assert.equal(root.dataset.miniappColorScheme, 'light', 'the initial device fallback is applied at load');

const telegramEvents = {};
const chromeColors = {};
const changes = [];
const webApp = {
  colorScheme: 'dark',
  themeParams: {
    bg_color: '#101714',
    secondary_bg_color: '#18231e',
  },
  onEvent(name, callback) { telegramEvents[name] = callback; },
  setHeaderColor(value) { chromeColors.header = value; },
  setBackgroundColor(value) { chromeColors.background = value; },
  setBottomBarColor(value) { chromeColors.bottom = value; },
};

const binding = window.MiniAppUtils.bindMiniAppTheme(webApp, scheme => changes.push(scheme));

assert.equal(binding.colorScheme, 'dark');
assert.equal(root.dataset.miniappColorScheme, 'dark');
assert.equal(root.style.colorScheme, 'dark');
assert.deepEqual(chromeColors, {
  header: '#101714',
  background: '#101714',
  bottom: '#18231e',
});
assert.equal(typeof telegramEvents.themeChanged, 'function');
assert.equal(mediaListeners.length, 1);

webApp.colorScheme = 'light';
webApp.themeParams = {
  bg_color: '#f3f6f8',
  bottom_bar_bg_color: '#ffffff',
};
telegramEvents.themeChanged();

assert.equal(root.dataset.miniappColorScheme, 'light');
assert.equal(root.style.colorScheme, 'light');
assert.deepEqual(changes, ['dark', 'light']);
assert.deepEqual(chromeColors, {
  header: '#f3f6f8',
  background: '#f3f6f8',
  bottom: '#ffffff',
});

console.log('Mini App Telegram theme tests passed');

const hapticCalls=[];
window.navigator={vibrate(value){hapticCalls.push(['vibrate',value]);return true;}};
window.Telegram={WebApp:{isVersionAtLeast:()=>true,HapticFeedback:{
  notificationOccurred(value){hapticCalls.push(['notification',value]);},
  impactOccurred(value){hapticCalls.push(['impact',value]);},
}}};
window.MiniAppUtils.haptic('success');
assert.deepEqual(hapticCalls,[['notification','success']]);
window.Telegram.WebApp.HapticFeedback.notificationOccurred=()=>{throw new Error('Unsupported device');};
assert.equal(window.MiniAppUtils.haptic('error'),true);
assert.deepEqual(hapticCalls[1],['vibrate',[35,40,35]]);
delete window.Telegram;
assert.equal(window.MiniAppUtils.haptic('light'),true);
assert.deepEqual(hapticCalls[2],['vibrate',35]);
delete window.navigator;
assert.equal(window.MiniAppUtils.haptic('success'),false);
console.log('Shared haptic success, error and unsupported-device tests passed');
