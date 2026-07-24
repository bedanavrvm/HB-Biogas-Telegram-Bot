(() => {
  'use strict';
  const tg = window.Telegram?.WebApp;
  let backHandler = null;
  let mainHandler = null;

  function syncTheme() {
    const params = tg?.themeParams || {};
    Object.entries(params).forEach(([key, value]) => {
      const cssKey = key.replace(/_/g, '-');
      document.documentElement.style.setProperty(`--tg-theme-${cssKey}`, value);
    });
  }

  function currentScreen() {
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
  document.body.addEventListener('htmx:responseError', event => {
    if (event.detail.target?.id !== 'content') return;
    event.detail.target.innerHTML = '<section class="shell-error" role="alert"><h2>Screen unavailable</h2><p>The request failed. Check your connection and try again.</p></section>';
  });
  document.addEventListener('DOMContentLoaded', activateScreen);
  new MutationObserver(() => {
    syncBackButton();
    syncMainButton();
  }).observe(document.body, {subtree: true, attributes: true, attributeFilter: ['class', 'hidden', 'disabled']});
})();
