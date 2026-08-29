(function () {
  function initTelegramWebApp() {
    if (window.MiniAppUtils && typeof window.MiniAppUtils.initTelegram === 'function') {
      return window.MiniAppUtils.initTelegram();
    }
    const tg = window.Telegram && window.Telegram.WebApp;
    if (!tg) return null;
    tg.ready();
    tg.expand();
    if (typeof tg.disableVerticalSwipes === 'function') tg.disableVerticalSwipes();
    if (typeof tg.disableClosingConfirmation === 'function') tg.disableClosingConfirmation();
    return tg;
  }

  window.MiniAppTelegram = { init: initTelegramWebApp };
})();
