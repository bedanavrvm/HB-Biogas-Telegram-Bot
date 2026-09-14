(() => {
  'use strict';
  const tg = window.MiniAppUtils?.initTelegram?.() || window.Telegram?.WebApp;
  let backHandler = null;
  let mainHandler = null;
  let lastFocusedElement = null;

  function clearBackHandler() {
    if (backHandler && tg?.BackButton) tg.BackButton.offClick(backHandler);
    backHandler = null;
  }

  function portalBackFallbackUrl() {
    const caseBack = document.querySelector('.case-history-back[data-return-screen]');
    if (caseBack && /\/portal\/cases\/[^/]+\//.test(window.location.pathname)) return caseBack.href;
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
    const fallbackUrl = portalBackFallbackUrl();
    if (window.MiniAppUtils?.canNavigatePage?.(fallbackUrl) === false) return;
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

  function syncStableViewportHeight() {
    // Fixed sheets/media follow Telegram's last stable viewport so native
    // expansion animations never resize an open operational overlay.
    const height = Number(tg?.viewportStableHeight)
      || Number(tg?.viewportHeight)
      || Number(window.visualViewport?.height)
      || Number(window.innerHeight);
    if (height > 0) {
      document.documentElement.style.setProperty('--miniapp-stable-height', `${Math.round(height)}px`);
      document.documentElement.style.setProperty('--miniapp-viewport-height', `${Math.round(height)}px`);
    }
  }

  function syncLiveViewportHeight(preferBrowserViewport = false) {
    const height = (preferBrowserViewport ? Number(window.visualViewport?.height) : Number(tg?.viewportHeight))
      || (preferBrowserViewport ? Number(tg?.viewportHeight) : Number(window.visualViewport?.height))
      || Number(window.innerHeight);
    if (height > 0) document.documentElement.style.setProperty('--miniapp-live-height', `${Math.round(height)}px`);
  }

  function syncBrowserViewportHeight() {
    syncLiveViewportHeight(true);
    if (!tg) syncStableViewportHeight();
  }

  function handleTelegramViewportChanged(event = {}) {
    syncLiveViewportHeight();
    if (event.isStateStable !== false) syncStableViewportHeight();
  }

  function currentScreen() {
    // A full-page Portal route owns one screen. The rendered data attribute
    // also covers invoice and report subroutes with shared URL prefixes.
    const renderedScreen = document.getElementById('portal-screen')?.dataset.screen;
    if (renderedScreen) return renderedScreen;
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
        const screens = String(link.dataset.screens || link.dataset.screen || '').split(/\s+/).filter(Boolean);
        link.classList.toggle('active', screens.includes(screen));
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
    syncLiveViewportHeight();
    syncStableViewportHeight();
    tg.onEvent?.('themeChanged', syncTheme);
    tg.onEvent?.('viewportChanged', handleTelegramViewportChanged);
  }
  syncTheme();

  window.addEventListener('portal:reports-route-change', syncBackButton);
  window.addEventListener('resize', syncBrowserViewportHeight);
  window.addEventListener('orientationchange', syncBrowserViewportHeight);
  window.visualViewport?.addEventListener('resize', syncBrowserViewportHeight);

  document.body.addEventListener('htmx:configRequest', event => {
    if (tg?.initData) event.detail.headers['X-Telegram-Init-Data'] = tg.initData;
    const requestId = window.crypto?.randomUUID
      ? window.crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    event.detail.headers['X-Request-ID'] = requestId;
    event.detail.headers['Idempotency-Key'] = requestId;
  });
  document.body.addEventListener('htmx:afterSwap', () => window.lucide?.createIcons());
  document.addEventListener('click', event => {
    const link = event.target.closest?.('a[href]');
    if (!link || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey
        || event.shiftKey || event.altKey || link.target || link.hasAttribute('download')) return;
    const destination = new URL(link.href, window.location.href);
    if (destination.origin !== window.location.origin || !destination.pathname.startsWith('/portal/')) return;
    if (destination.href === window.location.href) return;
    if (window.MiniAppUtils?.canNavigatePage?.(destination.href) === false) {
      event.preventDefault();
      event.stopPropagation();
    }
  }, true);
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
