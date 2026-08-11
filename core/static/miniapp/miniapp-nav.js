(() => {
  'use strict';
  const tg = window.Telegram?.WebApp;
  let backHandler = null;
  let mainHandler = null;
  let lastFocusedElement = null;
  let portalHistoryDepth = 0;
  let viewportRestoreScheduled = false;
  let viewportRestoreFallback = null;
  let activationFallback = null;
  let lastViewportRestoreAt = 0;

  function isPortalRoute(pathname = window.location.pathname) {
    return /^\/portal\/(?:s\/[^/]+\/|cases\/[^/]+\/)/.test(pathname);
  }

  function markPortalHistoryEntry(depth = 0) {
    if (!isPortalRoute() || !window.history?.replaceState) return;
    const current = window.history.state || {};
    const existingDepth = Number.isInteger(current.portalMiniAppDepth)
      ? current.portalMiniAppDepth
      : depth;
    portalHistoryDepth = Math.max(0, existingDepth);
    window.history.replaceState({
      ...current,
      portalMiniAppHistory: true,
      portalMiniAppDepth: portalHistoryDepth,
    }, document.title, window.location.href);
  }

  function clearBackHandler() {
    if (backHandler && tg?.BackButton) tg.BackButton.offClick(backHandler);
    backHandler = null;
  }

  function portalBackFallbackUrl() {
    // A directly opened case (or a WebView restored from a cold page) has no
    // reliable Portal entry behind it. Going back in that situation sends the
    // Android WebView out of the Mini App, so use an allowed top-level screen
    // instead. Prefer All Cases for a case detail, then Dashboard for roles
    // that do not have that queue.
    const preferredScreen = /\/portal\/cases\/[^/]+\//.test(window.location.pathname)
      ? 'all'
      : /\/portal\/s\/invoices\/[^/]+\//.test(window.location.pathname)
        ? 'invoices'
      : /\/portal\/s\/reports\/[^/]+\//.test(window.location.pathname)
        ? 'reports'
        : 'dashboard';
    const fallbackLink = document.querySelector(`.shell-nav-link[data-screen="${preferredScreen}"]`)
      || document.querySelector('.shell-nav-link[data-screen="dashboard"]')
      || document.querySelector('.shell-nav-link');
    return fallbackLink?.href || '/portal/s/dashboard/';
  }

  function navigateBackWithinPortal() {
    const state = window.history.state || {};
    if (state.portalMiniAppHistory && portalHistoryDepth > 0) {
      window.history.back();
      return;
    }

    const fallbackUrl = portalBackFallbackUrl();
    const target = document.getElementById('portal-screen');
    if (window.htmx && target) {
      window.htmx.ajax('GET', fallbackUrl, {
        target: '#portal-screen',
        swap: 'outerHTML transition:true',
        pushURL: true,
      });
      return;
    }
    window.location.assign(fallbackUrl);
  }

  function setSidebar(open) {
    const sidebar = document.getElementById('sidebar');
    const backdrop = document.getElementById('sidebar-backdrop');
    const button = document.getElementById('shell-menu-button');
    if (!sidebar) return;
    if (open) lastFocusedElement = document.activeElement;
    sidebar.classList.toggle('open', open);
    backdrop?.classList.toggle('open', open);
    button?.setAttribute('aria-expanded', String(open));
    document.body.classList.toggle('sidebar-is-open', open);
    if (open) {
      window.requestAnimationFrame(() => sidebar.querySelector('.shell-nav-link')?.focus());
    } else if (lastFocusedElement && typeof lastFocusedElement.focus === 'function') {
      lastFocusedElement.focus();
      lastFocusedElement = null;
    }
  }

  // Overlay controls are delegated because several panels are rendered or
  // replaced after the initial page load. This keeps close buttons reliable
  // across htmx swaps and dynamically opened invoice/payment previews.
  document.addEventListener('click', event => {
    const close = event.target.closest?.('.sheet-overlay .sheet-close-button');
    if (!close) return;
    const overlay = close.closest('.sheet-overlay');
    if (!overlay) return;
    event.preventDefault();
    // Let the screen controller handle its own cleanup first (for example,
    // destroying a map or clearing the selected batch).  The shell only owns
    // the common visibility and Telegram BackButton state.
    overlay.classList.remove('open');
    overlay.setAttribute('aria-hidden', 'true');
    syncBackButton();
  });

  function syncTheme() {
    const params = tg?.themeParams || {};
    Object.entries(params).forEach(([key, value]) => {
      const cssKey = key.replace(/_/g, '-');
      document.documentElement.style.setProperty(`--tg-theme-${cssKey}`, value);
    });
  }

  function syncTelegramViewportHeight() {
    // Fixed Portal sheets should only follow Telegram's last stable viewport.
    // The live height changes throughout native activity/viewport animations
    // and applying it here would visibly resize the entire Portal.
    const height = Number(tg?.viewportStableHeight)
      || Number(tg?.viewportHeight)
      || Number(window.visualViewport?.height)
      || Number(window.innerHeight);
    if (height > 0) {
      document.documentElement.style.setProperty('--miniapp-viewport-height', `${Math.round(height)}px`);
    }
  }

  function syncBrowserViewportHeight() {
    if (tg) return;
    syncTelegramViewportHeight();
  }

  function handleTelegramViewportChanged(event = {}) {
    if (event.isStateStable === false) return;
    if (viewportRestoreFallback) {
      window.clearTimeout(viewportRestoreFallback);
      viewportRestoreFallback = null;
    }
    syncTelegramViewportHeight();
  }

  function restoreTelegramViewport() {
    // Android may return from an external viewer with the WebView contracted.
    // Activity and visibility events often arrive together, so coalesce them
    // into one expansion and wait for Telegram's stable viewport notification.
    const now = Date.now();
    if (viewportRestoreScheduled || now - lastViewportRestoreAt < 250) return;
    viewportRestoreScheduled = true;
    window.requestAnimationFrame(() => {
      viewportRestoreScheduled = false;
      lastViewportRestoreAt = Date.now();
      tg?.expand?.();
      if (viewportRestoreFallback) window.clearTimeout(viewportRestoreFallback);
      // Older Telegram clients may not emit viewportChanged when they already
      // consider the Mini App expanded. Measure once after their animation.
      viewportRestoreFallback = window.setTimeout(() => {
        viewportRestoreFallback = null;
        syncTelegramViewportHeight();
      }, 300);
    });
  }

  function handleTelegramActivated() {
    if (activationFallback) {
      window.clearTimeout(activationFallback);
      activationFallback = null;
    }
    restoreTelegramViewport();
  }

  function scheduleVisibilityRestore() {
    if (document.visibilityState !== 'visible') {
      if (activationFallback) window.clearTimeout(activationFallback);
      activationFallback = null;
      return;
    }
    if (activationFallback) return;
    // Modern clients emit activated as well as visibilitychange. Give that
    // authoritative event time to arrive; this remains a fallback for older
    // clients that only expose document visibility.
    activationFallback = window.setTimeout(() => {
      activationFallback = null;
      restoreTelegramViewport();
    }, 200);
  }

  function currentScreen() {
    if (/\/portal\/cases\/[^/]+\//.test(window.location.pathname)) return 'case_history';
    const match = window.location.pathname.match(/\/portal\/s\/([^/]+)\//);
    return match ? match[1] : 'dashboard';
  }

  function syncBackButton() {
    if (!tg?.BackButton) return;
    const openOverlay = [...document.querySelectorAll('#content .sheet-overlay.open')]
      .map((overlay, index) => ({
        overlay,
        index,
        zIndex: Number.parseInt(window.getComputedStyle(overlay).zIndex, 10) || 0,
      }))
      .sort((left, right) => right.zIndex - left.zIndex || right.index - left.index)[0]?.overlay;
    if (openOverlay) {
      clearBackHandler();
      backHandler = () => {
        const close = openOverlay.querySelector('.sheet-close-button, [id$="-cancel"]');
        if (close) close.click();
        else openOverlay.classList.remove('open');
      };
      tg.BackButton.onClick(backHandler);
      tg.BackButton.show();
      return;
    }
    // Report setup is a mobile wizard. Its internal steps are not separate
    // business screens, so Telegram Back should move through the wizard
    // before it falls back to Portal browser history or closes the Mini App.
    const reports = window.PortalMiniAppReports;
    if (reports?.canHandleBack?.()) {
      clearBackHandler();
      backHandler = () => {
        if (!reports.handleBack?.()) navigateBackWithinPortal();
      };
      tg.BackButton.onClick(backHandler);
      tg.BackButton.show();
      return;
    }
    const topLevel = document.querySelector('#content [data-top-level="true"]');
    if (topLevel) {
      clearBackHandler();
      tg.BackButton.hide();
      return;
    }
    clearBackHandler();
    backHandler = navigateBackWithinPortal;
    tg.BackButton.onClick(backHandler);
    tg.BackButton.show();
  }

  function syncMainButton() {
    if (!tg?.MainButton) return;
    if (mainHandler) tg.MainButton.offClick(mainHandler);
    const action = [...document.querySelectorAll('#content [data-main-action]')]
      .find(element => {
        const overlay = element.closest('.sheet-overlay');
        const visibleOverlay = !overlay || overlay.classList.contains('open');
        const visibleAction = element.getClientRects().length || element.dataset.mainActionProxy === 'true';
        return visibleOverlay && visibleAction && !element.disabled;
      });
    if (!action) {
      tg.MainButton.hide();
      mainHandler = null;
      return;
    }
    tg.MainButton.setText(action.dataset.mainAction || action.textContent.trim() || 'Continue');
    mainHandler = () => action.click();
    tg.MainButton.onClick(mainHandler);
    tg.MainButton.show();
  }

  function activateScreen() {
    try {
      const screen = currentScreen();
      document.querySelectorAll('.shell-nav-link').forEach(link => {
        link.classList.toggle('active', link.dataset.screen === screen);
      });
      if (!window.PortalAppShell?.activate) throw new Error('Portal screen loader is unavailable.');
      window.PortalAppShell.activate(screen);
      syncBackButton();
      syncMainButton();
      window.lucide?.createIcons();
    } catch (error) {
      console.warn('Portal route activation failed.', error);
      const target = document.getElementById('portal-screen');
      if (target) {
        target.innerHTML = '<section class="shell-error" role="alert"><h2>Screen could not start</h2>'
          + '<p>Refresh the Portal or choose the screen again from the menu.</p></section>';
      }
    }
  }

  if (tg) {
    tg.ready();
    restoreTelegramViewport();
    tg.onEvent?.('themeChanged', syncTheme);
    tg.onEvent?.('viewportChanged', handleTelegramViewportChanged);
    tg.onEvent?.('activated', handleTelegramActivated);
  }
  syncTheme();
  markPortalHistoryEntry();

  window.addEventListener('portal:reports-route-change', syncBackButton);
  window.addEventListener('resize', syncBrowserViewportHeight);
  window.visualViewport?.addEventListener('resize', syncBrowserViewportHeight);
  document.addEventListener('visibilitychange', scheduleVisibilityRestore);

  document.body.addEventListener('htmx:configRequest', event => {
    if (tg?.initData) event.detail.headers['X-Telegram-Init-Data'] = tg.initData;
    event.detail.headers['X-Request-ID'] = window.crypto?.randomUUID
      ? window.crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  });
  document.body.addEventListener('htmx:afterSwap', activateScreen);
  document.body.addEventListener('htmx:afterSettle', activateScreen);
  document.body.addEventListener('htmx:historyRestore', activateScreen);
  document.body.addEventListener('htmx:pushedIntoHistory', () => {
    // htmx owns browser history for in-shell links. Stamp its new entry with
    // a Portal-only depth so Telegram Back never crosses into the host app.
    markPortalHistoryEntry(portalHistoryDepth + 1);
  });
  window.addEventListener('popstate', () => {
    // htmx restores cached history entries when available. For Telegram's
    // hardware/browser back on a cold or uncached entry, request the screen
    // fragment explicitly so the shell does not remain on the old page.
    const state = window.history.state || {};
    if (state.portalMiniAppHistory && Number.isInteger(state.portalMiniAppDepth)) {
      portalHistoryDepth = Math.max(0, state.portalMiniAppDepth);
    } else if (isPortalRoute()) {
      // A cold/direct Portal page has no trustworthy in-app predecessor.
      markPortalHistoryEntry(0);
    }
    if (!window.htmx) return;
    const match = window.location.pathname.match(/\/portal\/s\/([^/]+)\//);
    if (!match) return;
    const target = document.getElementById('portal-screen');
    if (!target) return;
    window.htmx.ajax('GET', window.location.pathname, {
      target: '#portal-screen',
      swap: 'outerHTML transition:true',
      pushURL: false,
    });
  });
  document.addEventListener('click', event => {
    if (event.target.closest('#shell-menu-button')) {
      setSidebar(!document.getElementById('sidebar')?.classList.contains('open'));
      return;
    }
    if (event.target.closest('#sidebar-backdrop, #sidebar .shell-nav-link')) setSidebar(false);
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') setSidebar(false);
  });
  document.body.addEventListener('htmx:responseError', event => {
    const target = event.detail.target;
    if (!target) return;
    if (target.id === 'content' || target.id === 'portal-screen') {
      target.innerHTML = '<section class="shell-error" role="alert"><h2>Screen unavailable</h2><p>'
        + (event.detail.xhr?.status === 403
          ? 'Your Telegram account is not authorized for this Portal screen.'
          : 'The request failed. Check your connection and try again.')
        + '</p></section>';
    } else if (target.closest?.('#sidebar, #bottom-tabs')) {
      target.innerHTML = '<span class="shell-nav-status">Navigation unavailable: '
        + (event.detail.xhr?.status === 403 ? 'Telegram access is not authorized.' : 'request failed.')
        + '</span>';
    }
  });
  document.body.addEventListener('htmx:timeout', event => {
    const target = event.detail?.target;
    if (!target || (target.id !== 'content' && target.id !== 'portal-screen')) return;
    target.innerHTML = '<section class="shell-error" role="alert"><h2>Screen took too long to load</h2>'
      + '<p>Check your connection, then choose the screen again from the menu.</p></section>';
  });
  document.addEventListener('DOMContentLoaded', activateScreen);
  new MutationObserver(() => {
    syncBackButton();
    syncMainButton();
  }).observe(document.body, {subtree: true, attributes: true, attributeFilter: ['class', 'hidden', 'disabled']});
})();
