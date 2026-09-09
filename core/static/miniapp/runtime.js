(function () {
  'use strict';
  if (window.MiniAppRuntime) return;

  const visibilitySubscribers = new Set();
  let visible = document.visibilityState !== 'hidden';
  let activeRequests = 0;
  let progressTimer = null;
  let progressStartedAt = 0;
  let toastTimer = null;

  function ensureProgressLine() {
    let line = document.getElementById('miniapp-top-progress');
    if (line) return line;
    line = document.createElement('div');
    line.id = 'miniapp-top-progress';
    line.className = 'miniapp-top-progress';
    line.setAttribute('role', 'progressbar');
    line.setAttribute('aria-label', 'Loading');
    line.setAttribute('aria-hidden', 'true');
    (document.body || document.documentElement).appendChild(line);
    return line;
  }

  function beginProgress() {
    activeRequests += 1;
    if (activeRequests !== 1) return;
    window.clearTimeout(progressTimer);
    progressTimer = window.setTimeout(function () {
      if (!activeRequests) return;
      const line = ensureProgressLine();
      progressStartedAt = Date.now();
      line.className = 'miniapp-top-progress is-active';
      line.setAttribute('aria-hidden', 'false');
    }, 120);
  }

  function endProgress() {
    activeRequests = Math.max(0, activeRequests - 1);
    if (activeRequests) return;
    window.clearTimeout(progressTimer);
    const line = document.getElementById('miniapp-top-progress');
    if (!line || !line.classList.contains('is-active')) return;
    const remaining = Math.max(0, 240 - (Date.now() - progressStartedAt));
    progressTimer = window.setTimeout(function () {
      line.className = 'miniapp-top-progress is-complete';
      window.setTimeout(function () {
        line.className = 'miniapp-top-progress';
        line.setAttribute('aria-hidden', 'true');
      }, 180);
    }, remaining);
  }

  function showToast(message, options) {
    const settings = options || {};
    const tone = ['success', 'error', 'warning', 'info'].includes(settings.tone)
      ? settings.tone : 'info';
    let toast = document.getElementById('miniapp-shared-toast');
    if (!toast) {
      toast = document.createElement('div');
      toast.id = 'miniapp-shared-toast';
      toast.className = 'miniapp-shared-toast';
      (document.body || document.documentElement).appendChild(toast);
    }
    toast.textContent = String(message || '');
    toast.dataset.tone = tone;
    toast.setAttribute('role', tone === 'error' ? 'alert' : 'status');
    toast.classList.add('is-visible');
    window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(function () {
      toast.classList.remove('is-visible');
    }, Number(settings.timeout || (tone === 'error' ? 5000 : 3200)));
    return toast;
  }

  // A delayed global fetch indicator gives navigation and writes BotFather-like
  // feedback without flashing for fast requests. Existing request semantics are
  // preserved, including rejected promises and Response objects.
  const nativeFetch = window.fetch && window.fetch.bind(window);
  if (nativeFetch && !window.fetch._miniAppProgressWrapped) {
    const progressFetch = function () {
      beginProgress();
      return nativeFetch.apply(null, arguments).finally(endProgress);
    };
    progressFetch._miniAppProgressWrapped = true;
    window.fetch = progressFetch;
  }

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
    beginProgress,
    endProgress,
    showToast,
  };
})();
