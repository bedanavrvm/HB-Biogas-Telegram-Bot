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

  window.MiniAppRuntime = {
    isVisible: function () { return visible; },
    subscribeVisibility,
    createVisibleInterval,
    createServerClock,
  };
})();
