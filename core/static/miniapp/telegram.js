(function () {
  function initTelegramWebApp() {
    const tg = window.Telegram && window.Telegram.WebApp;
    if (!tg) return null;
    tg.ready();
    tg.expand();
    if (typeof tg.enableClosingConfirmation === 'function') {
      tg.enableClosingConfirmation();
    }
    return tg;
  }

  window.MiniAppTelegram = { init: initTelegramWebApp };
})();
