(() => {
  'use strict';
  const tg = window.Telegram?.WebApp;
  let backHandler = null;
  let mainHandler = null;

  function setSidebar(open) {
    const sidebar = document.getElementById('sidebar');
    const backdrop = document.getElementById('sidebar-backdrop');
    const button = document.getElementById('shell-menu-button');
    if (!sidebar) return;
    sidebar.classList.toggle('open', open);
    backdrop?.classList.toggle('open', open);
    button?.setAttribute('aria-expanded', String(open));
    document.body.classList.toggle('sidebar-is-open', open);
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
    event.stopPropagation();
    overlay.classList.remove('open');
    overlay.setAttribute('aria-hidden', 'true');
    syncBackButton();
  }, true);

  function syncTheme() {
    const params = tg?.themeParams || {};
    Object.entries(params).forEach(([key, value]) => {
      const cssKey = key.replace(/_/g, '-');
      document.documentElement.style.setProperty(`--tg-theme-${cssKey}`, value);
    });
  }

  function currentScreen() {
    if (/\/portal\/cases\/[^/]+\//.test(window.location.pathname)) return 'case_history';
    const match = window.location.pathname.match(/\/portal\/s\/([^/]+)\//);
    return match ? match[1] : 'dashboard';
  }

  function syncBackButton() {
    if (!tg?.BackButton) return;
    const openOverlay = document.querySelector('#content .sheet-overlay.open');
    if (openOverlay) {
      if (backHandler) tg.BackButton.offClick(backHandler);
      backHandler = () => {
        const close = openOverlay.querySelector('.sheet-close-button, [id$="-cancel"]');
        if (close) close.click();
        else openOverlay.classList.remove('open');
      };
      tg.BackButton.onClick(backHandler);
      tg.BackButton.show();
      return;
    }
    const topLevel = document.querySelector('#content [data-top-level="true"]');
    if (topLevel) {
      tg.BackButton.hide();
      return;
    }
    if (backHandler) tg.BackButton.offClick(backHandler);
    backHandler = () => window.history.back();
    tg.BackButton.onClick(backHandler);
    tg.BackButton.show();
  }

  function syncMainButton() {
    if (!tg?.MainButton) return;
    if (mainHandler) tg.MainButton.offClick(mainHandler);
    const action = [...document.querySelectorAll('#content [data-main-action]')]
      .find(element => element.getClientRects().length && !element.disabled);
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
    const screen = currentScreen();
    document.querySelectorAll('.shell-nav-link').forEach(link => {
      link.classList.toggle('active', link.dataset.screen === screen);
    });
    window.PortalAppShell?.activate(screen);
    syncBackButton();
    syncMainButton();
    window.lucide?.createIcons();
  }

  if (tg) {
    tg.ready();
    tg.expand();
    tg.onEvent?.('themeChanged', syncTheme);
  }
  syncTheme();

  document.body.addEventListener('htmx:configRequest', event => {
    if (tg?.initData) event.detail.headers['X-Telegram-Init-Data'] = tg.initData;
  });
  document.body.addEventListener('htmx:afterSwap', activateScreen);
  window.addEventListener('popstate', () => {
    // htmx restores cached history entries when available. For Telegram's
    // hardware/browser back on a cold or uncached entry, request the screen
    // fragment explicitly so the shell does not remain on the old page.
    if (!window.htmx) return;
    const match = window.location.pathname.match(/\/portal\/s\/([^/]+)\//);
    if (!match) return;
    const target = document.getElementById('content');
    if (!target) return;
    window.htmx.ajax('GET', window.location.pathname, {
      target: '#content',
      swap: 'innerHTML transition:true',
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
    if (target.id === 'content') {
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
  document.addEventListener('DOMContentLoaded', activateScreen);
  new MutationObserver(() => {
    syncBackButton();
    syncMainButton();
  }).observe(document.body, {subtree: true, attributes: true, attributeFilter: ['class', 'hidden', 'disabled']});
})();
