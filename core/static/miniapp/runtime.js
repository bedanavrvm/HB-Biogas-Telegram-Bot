(function () {
  'use strict';
  if (window.MiniAppRuntime) return;

  const visibilitySubscribers = new Set();
  let visible = document.visibilityState !== 'hidden';

  function currentVisible() {
    return document.visibilityState !== 'hidden';
  }

  function publishVisibility(source) {
    const nextVisible = currentVisible();
    const resumed = nextVisible && (!visible || source === 'pageshow' || source === 'focus');
    visible = nextVisible;
    visibilitySubscribers.forEach((subscriber) => {
      try { subscriber({ visible, resumed, source }); } catch (_) {}
    });
  }

  document.addEventListener('visibilitychange', () => publishVisibility('visibilitychange'));
  window.addEventListener('pageshow', () => publishVisibility('pageshow'));
  window.addEventListener('focus', () => publishVisibility('focus'));

  function subscribeVisibility(subscriber, options) {
    if (typeof subscriber !== 'function') return function () {};
    visibilitySubscribers.add(subscriber);
    if (!options || options.immediate !== false) {
      subscriber({ visible, resumed: false, source: 'subscribe' });
    }
    return function () { visibilitySubscribers.delete(subscriber); };
  }

  function createVisibleInterval(callback, intervalMs, options) {
    const settings = options || {};
    const delay = Math.max(1000, Number(intervalMs || 0));
    let timer = null;

    function stopTimer() {
      if (timer !== null) window.clearInterval(timer);
      timer = null;
    }

    function startTimer(runImmediately) {
      stopTimer();
      if (!visible) return;
      if (runImmediately) Promise.resolve().then(callback).catch(function () {});
      timer = window.setInterval(function () {
        if (visible) Promise.resolve().then(callback).catch(function () {});
      }, delay);
    }

    const unsubscribe = subscribeVisibility(function (event) {
      if (!event.visible) {
        stopTimer();
      } else {
        startTimer(Boolean(event.resumed && settings.immediateOnResume));
      }
    });
    return function () {
      stopTimer();
      unsubscribe();
    };
  }

  function createServerClock(serverNow) {
    const parsed = Date.parse(String(serverNow || ''));
    if (!Number.isFinite(parsed)) return null;
    const monotonicStart = window.performance && typeof window.performance.now === 'function'
      ? window.performance.now()
      : 0;
    return {
      serverEpochMs: parsed,
      monotonicStart,
      nowMs: function () {
        const monotonicNow = window.performance && typeof window.performance.now === 'function'
          ? window.performance.now()
          : monotonicStart;
        return parsed + Math.max(0, monotonicNow - monotonicStart);
      },
    };
  }

  function formatElapsedSeconds(value) {
    let seconds = Math.max(0, Math.floor(Number(value) || 0));
    const days = Math.floor(seconds / 86400);
    seconds %= 86400;
    const hours = Math.floor(seconds / 3600);
    seconds %= 3600;
    const minutes = Math.floor(seconds / 60);
    seconds %= 60;
    const parts = [];
    if (days) parts.push(`${days}d`);
    if (hours || days) parts.push(`${hours}h`);
    parts.push(`${minutes}m`);
    parts.push(`${String(seconds).padStart(2, '0')}s`);
    return parts.join(' ');
  }

  function hydrateServerCounters(root, options) {
    const settings = options || {};
    const selector = settings.selector || '[data-server-counter]';
    (root || document).querySelectorAll(selector).forEach(function (node) {
      node._serverClock = createServerClock(node.dataset.calculatedAt);
    });
    return tickServerCounters(root, settings);
  }

  function tickServerCounters(root, options) {
    const settings = options || {};
    const selector = settings.selector || '[data-server-counter]';
    (root || document).querySelectorAll(selector).forEach(function (node) {
      let elapsed = Math.max(0, Number(node.dataset.elapsedSeconds) || 0);
      if (node.dataset.running === 'true' && node._serverClock) {
        elapsed += Math.max(0, Math.floor((node._serverClock.nowMs() - node._serverClock.serverEpochMs) / 1000));
      }
      node.textContent = formatElapsedSeconds(elapsed);
      if (typeof settings.onTick === 'function') settings.onTick(node, elapsed);
    });
  }

  function bindServerCounters(root, options) {
    const settings = options || {};
    hydrateServerCounters(root, settings);
    return createVisibleInterval(function () {
      tickServerCounters(root, settings);
    }, settings.intervalMs || 1000, { immediateOnResume: true });
  }

  window.MiniAppRuntime = {
    isVisible: function () { return visible; },
    subscribeVisibility,
    createVisibleInterval,
    createServerClock,
    formatElapsedSeconds,
    hydrateServerCounters,
    tickServerCounters,
    bindServerCounters,
  };
})();
